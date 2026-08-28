# Flipkart Low-Rating Review Dataset — Data Collection Process

## Overview

This project collects raw HTML data from Flipkart for products with **poor
customer ratings (1★–3★ reviews)**. The goal is to build a labeled dataset of
500 products, each with its product-details page and review page saved
locally, plus a master index in Google Sheets for tracking and reference.

---

## 1. Data Sourcing

**Source site:** https://www.flipkart.com/

**Target criteria:** Products whose customer reviews skew negative — focus on
listings showing predominantly **1, 2, or 3 star** ratings. These are the
"worst case" reviewed products for this dataset.

---

## 2. Google Sheet — Master Index

Create a Google Sheet to track every product collected. It must have exactly
these three columns:

| Column | Description |
|---|---|
| `Product Name` | Full product title as shown on Flipkart |
| `Product Details Link` | URL of the product's details/description page |
| `Product Review Link` | URL of the product's review listing page |

**Target:** 500 rows (500 products) before moving to the download phase.

> Tip: Keep the sheet as the single source of truth. Every folder created in
> Step 3 should correspond to exactly one row here, and the folder name should
> match `Product Name` exactly (see naming convention below).

---

## 3. HTML File Collection

Once the sheet has product entries, download the raw HTML for each product.

### Folder Structure

For every product, create a parent folder named **exactly** after the
`Product Name` value from the sheet, containing two subfolders:

```
Data Html File Download Dir/
└── <Product Name>/
    ├── product/   → product details page HTML
    └── review/    → product reviews page HTML
```

**Example:**

```
Data Html File Download Dir/
└── Casado Branded Bracelet | Gold Plated | Diamond Studded | 3D Cut Glass | Day and Date Analog Watch - For Men 632-GOLD-GOLD-BRACELET/
    ├── product/
    │   └── product.html
    └── review/
        └── review.html
```

### Per-Product Steps

1. **Open the product details page** (from the `Product Details Link`
   column), e.g.:
   ```
   https://www.flipkart.com/casado-branded-bracelet-gold-plated-diamond-studded-3d-cut-glass-day-date-analog-watch-men/p/itme704daf454150?pid=WATGW3ZY7YKSXVPK&lid=LSTWATGW3ZY7YKSXVPKZN5VLE...
   ```
   Save the fully rendered page HTML into that product's `product/` folder.

2. **Open the corresponding reviews page** (same product/listing IDs, but the
   `/p/` path segment becomes `/product-reviews/`), e.g.:
   ```
   https://www.flipkart.com/casado-branded-bracelet-gold-plated-diamond-studded-3d-cut-glass-day-date-analog-watch-men/product-reviews/itme704daf454150?pid=WATGW3ZY7YKSXVPK&lid=LSTWATGW3ZY7YKSXVPKZN5VLE&marketplace=FLIPKART
   ```
   Save the fully rendered page HTML into that product's `review/` folder.

3. **Repeat** for all 500 products listed in the Google Sheet.

### URL Pattern Reference

| Page Type | URL Pattern |
|---|---|
| Product Details | `.../p/<itemId>?pid=<pid>&lid=<lid>&marketplace=FLIPKART...` |
| Product Reviews | `.../product-reviews/<itemId>?pid=<pid>&lid=<lid>&marketplace=FLIPKART` |

The `product-reviews` URL is derived from the details URL by swapping `/p/`
for `/product-reviews/` and keeping the same `pid` and `lid` query params.

---

## 4. Naming & Consistency Rules

- Folder names must match the sheet's `Product Name` column **verbatim**,
  including punctuation and casing, so files can be traced back to their sheet
  row programmatically.
- Keep one `product/` and one `review/` HTML file per product folder — avoid
  saving duplicate or partial page loads.
- If a product name contains characters invalid for folder names on your OS
  (e.g. `/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`), sanitize consistently
  (e.g. replace with `-`) and keep a mapping if the sheet needs the original
  name preserved.

---

## 5. Suggested Workflow Order

1. Browse Flipkart, identify low-rated products → add rows to the Google
   Sheet (`Product Name`, `Product Details Link`, `Product Review Link`).
2. Once the sheet reaches 500 entries, batch through it top to bottom.
3. For each row: create the product folder, save `product/` HTML, save
   `review/` HTML.
4. Spot-check a sample of saved files to confirm both pages loaded fully
   (not partial/loading-state HTML) before moving to the next product.

---

## Notes

- Only publicly accessible pages should be collected, and collection should
  stay within Flipkart's terms of service and applicable data-use laws —
  worth a quick review before scaling this beyond manual, ad-hoc collection.
- Consider adding a `Status` column (e.g. `Pending` / `Downloaded` /
  `Verified`) to the sheet to track progress across the 500 items.
