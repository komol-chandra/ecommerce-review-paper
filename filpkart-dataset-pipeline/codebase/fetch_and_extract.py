#!/usr/bin/env python3
"""
fetch_and_extract.py

Chunked, resumable worker that fetches live Flipkart product + review pages
listed in database/product_list.csv (built by build_product_list.py) and
writes one JSON file per product into database/products/<pid>.json.

Designed to be run repeatedly — progress is checkpointed after every review
page fetch in database/progress.json, so an interrupted run (or one stopped
by --batch-size / --time-budget-minutes / a detected block) picks back up
where it left off next time:

    .venv/bin/python codebase/fetch_and_extract.py --batch-size 5
    .venv/bin/python codebase/fetch_and_extract.py --pids SHTGWS2HJW3QYVYJ,CRGHNG3WPNHRYGCN

A product is "done" once a review page comes back with no new reviews (either
zero parsed cards, or its first card duplicates the previous page's — Flipkart
clamps past-the-end page numbers to the last real page rather than erroring).
If a response looks like Flipkart's reCAPTCHA interstitial, the whole run
stops immediately (further requests would just hit the same wall) — re-run
later once unblocked.

Fetches go through a real headless Chromium (Playwright), not a bare HTTP
client — Flipkart returns 403 to plain `requests` calls even with browser-like
headers (confirmed: a real browser on the same network/IP loads the same URL
fine), so this drives an actual browser page instead.
"""

import argparse
import csv
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from flipkart_common import (
    build_product,
    extract_seller_best_effort,
    looks_blocked,
    parse_reviews,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRODUCT_LIST_PATH = PROJECT_ROOT / "database" / "product_list.csv"
PROGRESS_PATH = PROJECT_ROOT / "database" / "progress.json"
PRODUCTS_DIR = PROJECT_ROOT / "database" / "products"
FAILED_LOG_PATH = PROJECT_ROOT / "database" / "failed_log.csv"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_MS = 30000


class Blocked(Exception):
    pass


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_product_list():
    with open(PRODUCT_LIST_PATH, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_progress():
    if PROGRESS_PATH.is_file():
        return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    return {}


def save_progress(progress):
    PROGRESS_PATH.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")


def load_product_json(pid):
    path = PRODUCTS_DIR / f"{pid}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_product_json(pid, data):
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PRODUCTS_DIR / f"{pid}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def log_failure(pid, url, reason):
    is_new = not FAILED_LOG_PATH.is_file()
    with open(FAILED_LOG_PATH, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "pid", "url", "reason"])
        writer.writerow([now_iso(), pid, url, reason])


def fetch(page, url, delay_min, delay_max):
    """Navigate a real browser page to url, with retry/backoff. Every attempt
    — first try, retry, success, or failure — sleeps a jittered delay first,
    so a run's request rate stays even no matter which path it takes.

    Raises Blocked on a CAPTCHA-looking response or an HTTP 403. Returns
    (None, reason) after exhausting retries on other failures."""
    delay = 2.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        time.sleep(random.uniform(delay_min, delay_max))
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT_MS)
        except PlaywrightError as exc:
            if attempt == MAX_ATTEMPTS:
                return None, str(exc).splitlines()[0]
            time.sleep(delay)
            delay *= 2
            continue

        status = resp.status if resp is not None else None

        if status == 200:
            html = page.content()
            if looks_blocked(html):
                raise Blocked(url)
            return html, None

        if status == 403:
            raise Blocked(url)

        if status in (429, 500, 502, 503, 504) and attempt < MAX_ATTEMPTS:
            time.sleep(delay)
            delay *= 2
            continue

        return None, f"HTTP {status}"

    return None, "exhausted retries"


def review_signature(review):
    return (review.get("reviewer_name"), review.get("review_text"), review.get("review_date"))


def renumber_review_ids(reviews):
    for i, review in enumerate(reviews, start=1):
        review["review_id"] = f"REV-{i:03d}"


def process_product(browser_page, row, progress, delay_min, delay_max, max_pages_this_run):
    pid = row["pid"]
    entry = progress.setdefault(pid, {
        "status": "pending",
        "last_page_completed": 0,
        "reviews_collected": 0,
        "review_count_expected": int(row["review_count_expected"] or 0),
    })

    data = load_product_json(pid) or {
        "product": {},
        "seller": {},
        "customer_reviews": {
            "product_id": pid,
            "total_reviews": entry["review_count_expected"],
            "average_rating": None,
            "status": None,
            "reviews": [],
        },
        "meta": {
            "source": "flipkart.com",
            "source_pid": pid,
            "assignees": row["assignees"],
            "product_url": row["product_url"],
            "review_url": row["review_url"],
            "scraped_at": now_iso(),
            "pages_fetched": 0,
        },
    }

    if not data["product"]:
        html, err = fetch(browser_page, row["product_url"], delay_min, delay_max)
        if html is None:
            print(f"  [{pid}] product page fetch failed: {err}")
            log_failure(pid, row["product_url"], err)
            entry["status"] = "failed"
            return 0
        data["product"] = build_product(html)
        data["seller"] = extract_seller_best_effort(html)
        rating = data["product"].get("rating_summary") or {}
        if rating.get("review_count"):
            data["customer_reviews"]["total_reviews"] = rating["review_count"]
            entry["review_count_expected"] = rating["review_count"]
        if rating.get("average_rating"):
            data["customer_reviews"]["average_rating"] = rating["average_rating"]
        save_product_json(pid, data)

    entry["status"] = "in_progress"
    existing_reviews = data["customer_reviews"]["reviews"]
    seen_signatures = {review_signature(r) for r in existing_reviews}

    pages_done_this_run = 0
    page = entry["last_page_completed"] + 1
    new_reviews_total = 0

    while max_pages_this_run is None or pages_done_this_run < max_pages_this_run:
        sep = "&" if "?" in row["review_url"] else "?"
        page_url = f"{row['review_url']}{sep}page={page}"
        html, err = fetch(browser_page, page_url, delay_min, delay_max)
        if html is None:
            print(f"  [{pid}] page {page} fetch failed: {err}")
            log_failure(pid, page_url, err)
            entry["status"] = "failed"
            break

        page_reviews = parse_reviews(html)
        pages_done_this_run += 1
        data["meta"]["pages_fetched"] = data["meta"].get("pages_fetched", 0) + 1

        if not page_reviews:
            entry["status"] = "done"
            break

        added = 0
        for review in page_reviews:
            sig = review_signature(review)
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)
            existing_reviews.append(review)
            added += 1

        if added == 0:
            # Every review on this page was already collected — Flipkart
            # clamped past-the-end page numbers to the last real page.
            entry["status"] = "done"
            break

        new_reviews_total += added
        entry["last_page_completed"] = page
        entry["reviews_collected"] = len(existing_reviews)
        renumber_review_ids(existing_reviews)
        save_product_json(pid, data)
        save_progress(progress)

        page += 1

    renumber_review_ids(existing_reviews)
    entry["reviews_collected"] = len(existing_reviews)
    entry["updated_at"] = now_iso()
    save_product_json(pid, data)
    return new_reviews_total


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch-size", type=int, default=5, help="max not-yet-done products to touch this run")
    parser.add_argument("--max-pages-per-product", type=int, default=200,
                         help="cap review pages fetched per product per run, so one huge product doesn't monopolize the batch")
    parser.add_argument("--time-budget-minutes", type=float, default=None, help="stop starting new page fetches after this many minutes")
    parser.add_argument("--delay-min", type=float, default=1.5)
    parser.add_argument("--delay-max", type=float, default=3.5)
    parser.add_argument("--pids", default=None, help="comma-separated pids to restrict to (for testing)")
    args = parser.parse_args()

    if not PRODUCT_LIST_PATH.is_file():
        print(f"error: {PRODUCT_LIST_PATH} not found; run build_product_list.py first", file=sys.stderr)
        sys.exit(1)

    rows = load_product_list()
    if args.pids:
        wanted = set(args.pids.split(","))
        rows = [r for r in rows if r["pid"] in wanted]

    progress = load_progress()

    def is_done(pid):
        return progress.get(pid, {}).get("status") == "done"

    candidates = [r for r in rows if not is_done(r["pid"])]
    batch = candidates[: args.batch_size]

    if not batch:
        print("nothing to do — all selected products are already done")
        return

    start_time = time.time()
    products_touched = 0
    total_new_reviews = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-US")
        browser_page = context.new_page()
        try:
            for row in batch:
                if args.time_budget_minutes is not None and (time.time() - start_time) / 60 >= args.time_budget_minutes:
                    print("time budget reached, stopping")
                    break

                pid = row["pid"]
                print(f"[{pid}] {row['product_url'][:80]}")
                try:
                    added = process_product(browser_page, row, progress, args.delay_min, args.delay_max, args.max_pages_per_product)
                except Blocked as exc:
                    print(f"BLOCKED at {exc} — stopping run, re-run later", file=sys.stderr)
                    progress.setdefault(pid, {})["status"] = "blocked"
                    save_progress(progress)
                    print(f"products touched: {products_touched}, new reviews this run: {total_new_reviews}")
                    sys.exit(2)

                products_touched += 1
                total_new_reviews += added
                status = progress.get(pid, {}).get("status")
                print(f"  -> {added} new review(s), status={status}, total collected={progress[pid]['reviews_collected']}")
                save_progress(progress)
        finally:
            browser.close()

    remaining = sum(1 for r in rows if not is_done(r["pid"]))
    print(f"\nrun complete: {products_touched} product(s) touched, {total_new_reviews} new review(s), {remaining} product(s) still not done")


if __name__ == "__main__":
    main()
