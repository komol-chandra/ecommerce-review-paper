"""
flipkart_common.py

Parsing helpers shared by fetch_and_extract.py, ported from
dataset-pipeline/codebase/flipkart/extract_to_json.py (same ld+json /
window.__INITIAL_STATE__ / "Verified Purchase" DOM-walk techniques), adapted
to work on live-fetched HTML strings instead of saved files.
"""

import html as html_module
import json
import re
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup

MONTH_YEAR_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+(\d{4})"
)
RELATIVE_DATE_RE = re.compile(r"\d+\s+(day|week|month|year)s?\s+ago", re.IGNORECASE)

BLOCK_MARKERS = (
    "flipkart recaptcha",
    "recaptcha/enterprise.js",
    "are you a human?",
)


def to_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def looks_blocked(html):
    lower = html[:4000].lower()
    return any(marker in lower for marker in BLOCK_MARKERS)


# ---------- window.__INITIAL_STATE__ extraction (best-effort seller data) ----------

def extract_initial_state(html):
    marker = "window.__INITIAL_STATE__ = "
    start = html.find(marker)
    if start == -1:
        return {}
    start += len(marker)
    depth = 0
    end = None
    for i in range(start, len(html)):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return {}
    try:
        return json.loads(html[start:end])
    except json.JSONDecodeError:
        return {}


def flatten_strings(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            flatten_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            flatten_strings(v, out)
    elif isinstance(obj, str):
        out.append(obj)


LLABEL_PAIR_RE = re.compile(r'"label_1":\{"properties":\{\},"visible":true,"value":\{"text":"([^"]+)"\}\},"label_0":\{"properties":\{\},"visible":true,"value":\{"text":"([^"]+)"\}\}')
SELLER_TITLE_RATING_RE = re.compile(r'seller_details_seller_title_0.{0,300}?"label_4":\{"properties":\{\},"visible":true,"value":\{"text":"([\d.]+)"\}\}', re.DOTALL)


def extract_seller_best_effort(html):
    seller = {
        "company_name": None,
        "average_rating": None,
        "products_sold": None,
        "quality_score": None,
    }
    try:
        state = extract_initial_state(html)
        if not state:
            return seller
        strings = []
        flatten_strings(state, strings)
        for s in strings:
            m = re.search(r"experience with\s+([^.\n]+?)\s*\.\s*$", s.strip())
            if m and seller["company_name"] is None:
                seller["company_name"] = m.group(1).strip()
                break

        marker = "window.__INITIAL_STATE__"
        idx = html.find(marker)
        window_text = html[idx:idx + 400000] if idx != -1 else ""

        m = SELLER_TITLE_RATING_RE.search(window_text)
        if m:
            seller["average_rating"] = to_float(m.group(1))

        for m in LLABEL_PAIR_RE.finditer(window_text):
            label, value = m.group(1), m.group(2)
            if label == "Product Sold" and seller["products_sold"] is None:
                seller["products_sold"] = value
            elif label == "Quality Score" and seller["quality_score"] is None:
                seller["quality_score"] = value
    except Exception:
        pass
    return seller


# ---------- application/ld+json (schema.org Product) extraction ----------

LD_JSON_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)
OG_URL_RE = re.compile(r'<meta property="og:url" content="([^"]+)"')


def extract_ld_product(html):
    m = LD_JSON_RE.search(html)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item
        return data[0] if data and isinstance(data[0], dict) else {}
    return data if isinstance(data, dict) else {}


def extract_pid_lid(html):
    m = OG_URL_RE.search(html)
    if not m:
        return None, None
    url = html_module.unescape(m.group(1))
    query = parse_qs(urlparse(url).query)
    pid = (query.get("pid") or [None])[0]
    lid = (query.get("lid") or [None])[0]
    return pid, lid


def build_product(html):
    ld = extract_ld_product(html)
    pid, lid = extract_pid_lid(html)

    offers = ld.get("offers", {}) or {}
    rating = ld.get("aggregateRating", {}) or {}
    brand = ld.get("brand", {}) or {}

    return {
        "product_id": ld.get("sku") or pid,
        "listing_id": lid,
        "title": ld.get("name"),
        "description": ld.get("description"),
        "brand": brand.get("name"),
        "category": ld.get("category"),
        "images": ld.get("image") or [],
        "pricing": {
            "currency": offers.get("priceCurrency"),
            "price": offers.get("price"),
            "availability": offers.get("availability"),
        },
        "rating_summary": {
            "average_rating": rating.get("ratingValue"),
            "review_count": rating.get("reviewCount"),
            "rating_count": rating.get("ratingCount"),
        },
    }


# ---------- review page parsing ----------

def find_review_cards(html):
    soup = BeautifulSoup(html, "html.parser")
    vp_nodes = soup.find_all(string=lambda s: s and "Verified Purchase" in s)
    cards = []
    for vp_node in vp_nodes:
        node = vp_node.parent
        while node.parent is not None:
            if node.parent.get_text().count("Verified Purchase") > 1:
                break
            node = node.parent
        cards.append(node)
    return cards


def raw_month_year(text):
    m = MONTH_YEAR_RE.search(text)
    if not m:
        return None
    month, year = m.groups()
    return f"{month[:3]}, {year}"


def parse_review_card(card):
    segs = [s for s in card.get_text(separator="|", strip=True).split("|") if s]

    verified = any(s == "Verified Purchase" for s in segs)
    segs = [s for s in segs if s != "Verified Purchase"]

    date = None
    date_idx = None
    for i, s in enumerate(segs):
        if s.startswith("·"):
            date = raw_month_year(s) or (RELATIVE_DATE_RE.search(s) or [None])[0] or s.lstrip("· ").strip()
            date_idx = i
            break
    if date_idx is not None:
        segs.pop(date_idx)

    helpful_votes = 0
    total_votes = None
    helpful_idx = next((i for i, s in enumerate(segs) if s == "Helpful" or s.startswith("Helpful for")), None)
    if helpful_idx is not None:
        m = re.search(r"Helpful for (\d+)", segs[helpful_idx])
        if m:
            helpful_votes = int(m.group(1))
        remove_idx = [helpful_idx]
        if helpful_idx + 1 < len(segs) and re.match(r"^\d+$", segs[helpful_idx + 1]):
            total_votes = int(segs[helpful_idx + 1])
            remove_idx.append(helpful_idx + 1)
        for i in sorted(remove_idx, reverse=True):
            segs.pop(i)

    location = None
    loc_idx = next((i for i, s in enumerate(segs) if s.startswith(",")), None)
    if loc_idx is not None:
        location = segs.pop(loc_idx).lstrip(", ").strip() or None

    rating = None
    if segs and re.match(r"^\d+(\.\d+)?$", segs[0]):
        rating = to_float(segs.pop(0))
    if segs and segs[0] == "•":
        segs.pop(0)

    title = None
    if segs and not segs[0].startswith("Review for:"):
        title = segs.pop(0) or None

    variant = None
    if segs and segs[0].startswith("Review for:"):
        variant = segs.pop(0)[len("Review for:"):].strip() or None

    name = segs.pop() if segs else None
    text = "|".join(segs).strip()[:1000] or None

    images_count = len(card.find_all("img")) or None

    return {
        "reviewer_name": name,
        "reviewer_location": location,
        "rating": rating,
        "review_title": title,
        "review_text": text,
        "review_date": date,
        "verified_purchase": verified,
        "helpful_votes": helpful_votes,
        "total_votes": total_votes,
        "variant": variant,
        "images_count": images_count,
    }


def parse_reviews(html):
    cards = find_review_cards(html)
    return [row for card in cards if (row := parse_review_card(card))]
