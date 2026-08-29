#!/usr/bin/env python3
"""
build_product_list.py

Reads ../Flipkart.xlsx (every worksheet — currently "Chinmoy" and "Komol",
one row per product: review count / product details link / product review
link) and writes database/product_list.csv: one deduped row per Flipkart
`pid`, tagged with which sheet(s) it came from.

    .venv/bin/python codebase/build_product_list.py
"""

import csv
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import openpyxl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = PROJECT_ROOT / "Flipkart.xlsx"
OUT_PATH = PROJECT_ROOT / "database" / "product_list.csv"

COLUMNS = ["pid", "assignees", "review_count_expected", "product_url", "review_url"]


def get_pid(url):
    query = parse_qs(urlparse(url).query)
    return (query.get("pid") or [None])[0]


def to_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def read_rows(ws):
    header = None
    rows = []
    for row in ws.iter_rows(values_only=True):
        if header is None:
            header = [str(c).strip().lower() if c else "" for c in row]
            continue
        values = dict(zip(header, row))
        review_count = to_int(values.get("review count"))
        product_url = values.get("product dettails link") or values.get("product details link")
        review_url = values.get("product review link")
        if not product_url or not review_url:
            continue
        rows.append((review_count, product_url.strip(), review_url.strip()))
    return rows


def main():
    if not XLSX_PATH.is_file():
        print(f"error: {XLSX_PATH} not found", file=sys.stderr)
        sys.exit(1)

    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)

    products = {}  # pid -> dict
    skipped = 0
    for ws in wb.worksheets:
        for review_count, product_url, review_url in read_rows(ws):
            pid = get_pid(product_url)
            if not pid:
                skipped += 1
                continue
            entry = products.get(pid)
            if entry is None:
                products[pid] = {
                    "pid": pid,
                    "assignees": {ws.title},
                    "review_count_expected": review_count,
                    "product_url": product_url,
                    "review_url": review_url,
                }
            else:
                entry["assignees"].add(ws.title)
                if review_count is not None and (
                    entry["review_count_expected"] is None
                    or review_count > entry["review_count_expected"]
                ):
                    entry["review_count_expected"] = review_count

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for entry in sorted(products.values(), key=lambda e: e["pid"]):
            writer.writerow(
                {
                    "pid": entry["pid"],
                    "assignees": "|".join(sorted(entry["assignees"])),
                    "review_count_expected": entry["review_count_expected"],
                    "product_url": entry["product_url"],
                    "review_url": entry["review_url"],
                }
            )

    print(f"wrote {len(products)} deduped product(s) -> {OUT_PATH}")
    if skipped:
        print(f"skipped {skipped} row(s) with no parseable pid", file=sys.stderr)


if __name__ == "__main__":
    main()
