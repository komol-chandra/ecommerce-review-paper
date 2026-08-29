# filpkart-dataset-pipeline

Scrapes live Flipkart product + review pages listed in `Flipkart.xlsx` (two
sheets, "Chinmoy" and "Komol", each row: review count / product details link
/ product review link) and writes one flattened review-level CSV.

This is a **long-running, resumable, chunked** scrape — some products have
100k-500k+ reviews, so a single run is never expected to finish everything.
Run `fetch_and_extract.py` repeatedly (a cron job, `/loop`, or just re-running
it by hand) until `database/progress.json` shows every product `"done"`.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

Fetches go through a real headless Chromium (Playwright), not a bare HTTP
client — Flipkart returns HTTP 403 to plain `requests` calls even with
browser-like headers, confirmed by the fact that a real browser on the same
network loads the same URL fine. `playwright install chromium` downloads the
browser binary (~300MB) into `~/.cache/ms-playwright`; only needs to run once
per machine.

## 1. Build the product list

Reads both worksheets, dedupes by Flipkart `pid` (several rows repeat the
same product):

```bash
.venv/bin/python codebase/build_product_list.py
# -> database/product_list.csv
```

## 2. Fetch + extract (run this repeatedly)

```bash
.venv/bin/python codebase/fetch_and_extract.py --batch-size 5
```

- Touches up to `--batch-size` not-yet-`done` products per run (default 5).
- Per product, paginates its review page (`&page=N`) until a page adds no new
  reviews (Flipkart clamps past-the-end page numbers to the last real page
  rather than erroring) — that's when it's marked `done`.
- `--max-pages-per-product` (default 200) caps pages fetched per product
  *per run*, so one huge product doesn't eat an entire run by itself; it
  stays `in_progress` and picks up from where it left off next run.
- `--time-budget-minutes` stops starting new fetches after N minutes.
- `--pids A,B,C` restricts to specific product ids (useful for retrying a
  `failed` product, or testing).
- Every page fetch is checkpointed immediately to `database/progress.json`
  and `database/products/<pid>.json` — safe to Ctrl-C or kill at any time.
- If a response is an HTTP 403 or looks like Flipkart's reCAPTCHA
  interstitial, the run stops immediately (further requests would just hit
  the same wall) and exits non-zero — wait a while before re-running.
- Fetch failures (timeouts, non-200s) are logged to `database/failed_log.csv`
  and don't block the rest of the batch; re-run with `--pids` to retry them.

Check overall progress:

```bash
python3 -c "
import json, collections
p = json.load(open('database/progress.json'))
print(collections.Counter(v['status'] for v in p.values()))
"
```

## 3. Generate the flattened CSV

Safe to re-run any time, even mid-scrape, to get a fresh snapshot of
everything collected so far:

```bash
.venv/bin/python codebase/generate_review_summaries.py
# -> database/all_product_review_summaries.csv (+ .json)
```

## Known limitation

`parse_review_card` (ported from `dataset-pipeline/codebase/flipkart/extract_to_json.py`)
classifies a review card's text segments with a positional heuristic (date,
helpful-votes, location, rating, title, then "last remaining segment = reviewer
name"). On the rare card with an extra trailing number in the DOM text (e.g. a
stray helpfulness count not preceded by literal "Helpful" text), the reviewer
name and review text can end up misassigned. This is a pre-existing heuristic
limitation shared with the old pipeline, not new to this one — worth a spot
check on a data sample before treating the CSV as fully clean for the paper.
