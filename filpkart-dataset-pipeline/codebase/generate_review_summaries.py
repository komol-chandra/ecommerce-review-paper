#!/usr/bin/env python3
"""
generate_review_summaries.py

Flattens every database/products/<pid>.json (written by fetch_and_extract.py)
into one row per review, product/seller context repeated on every row.
Safe to re-run at any point — even mid-scrape — to get a fresh snapshot of
everything collected so far:

    .venv/bin/python codebase/generate_review_summaries.py
"""

import csv
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_DIR = PROJECT_ROOT / "database" / "products"
JSON_OUTPUT_PATH = PROJECT_ROOT / "database" / "all_product_review_summaries.json"
CSV_OUTPUT_PATH = PROJECT_ROOT / "database" / "all_product_review_summaries.csv"

COLUMNS = [
    # product context
    "product_id",
    "product_title",
    "product_category_breadcrumb",
    "product_brand",
    "product_price_currency",
    "product_price",
    "product_availability",
    "product_listing_id",
    # seller context
    "seller_company_name",
    "seller_average_rating",
    "seller_products_sold",
    "seller_quality_score",
    # review details
    "review_id",
    "reviewer_name",
    "reviewer_location",
    "review_rating",
    "review_title",
    "review_text",
    "review_date",
    "review_verified_purchase",
    "review_helpful_votes",
    "review_total_votes",
    "review_variant",
    "review_images_count",
    # meta
    "assignees",
    "product_url",
    "review_url",
    "scraped_at",
]


def build_product_context(product):
    pricing = product.get("pricing") or {}
    return {
        "product_id": product.get("product_id"),
        "product_title": product.get("title"),
        "product_category_breadcrumb": product.get("category"),
        "product_brand": product.get("brand"),
        "product_price_currency": pricing.get("currency"),
        "product_price": pricing.get("price"),
        "product_availability": pricing.get("availability"),
        "product_listing_id": product.get("listing_id"),
    }


def build_seller_context(seller):
    seller = seller or {}
    return {
        "seller_company_name": seller.get("company_name"),
        "seller_average_rating": seller.get("average_rating"),
        "seller_products_sold": seller.get("products_sold"),
        "seller_quality_score": seller.get("quality_score"),
    }


def flatten_review(review):
    review = review or {}
    return {
        "review_id": review.get("review_id"),
        "reviewer_name": review.get("reviewer_name"),
        "reviewer_location": review.get("reviewer_location"),
        "review_rating": review.get("rating"),
        "review_title": review.get("review_title"),
        "review_text": review.get("review_text"),
        "review_date": review.get("review_date"),
        "review_verified_purchase": review.get("verified_purchase"),
        "review_helpful_votes": review.get("helpful_votes"),
        "review_total_votes": review.get("total_votes"),
        "review_variant": review.get("variant"),
        "review_images_count": review.get("images_count"),
    }


def build_rows():
    rows = []
    for path in sorted(PRODUCTS_DIR.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        product_context = build_product_context(record.get("product") or {})
        seller_context = build_seller_context(record.get("seller"))
        meta = record.get("meta") or {}
        meta_context = {
            "assignees": meta.get("assignees"),
            "product_url": meta.get("product_url"),
            "review_url": meta.get("review_url"),
            "scraped_at": meta.get("scraped_at"),
        }

        reviews = (record.get("customer_reviews") or {}).get("reviews") or []
        for review in reviews:
            rows.append({
                **product_context,
                **seller_context,
                **flatten_review(review),
                **meta_context,
            })

    return rows


def main():
    if not PRODUCTS_DIR.is_dir():
        print(f"error: {PRODUCTS_DIR} not found; run fetch_and_extract.py first")
        return

    rows = build_rows()

    with open(JSON_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    with open(CSV_OUTPUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    num_products = len(list(PRODUCTS_DIR.glob("*.json")))
    print(f"wrote {len(rows)} review row(s) from {num_products} product file(s)")
    print(f"  {JSON_OUTPUT_PATH}")
    print(f"  {CSV_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
