# Renogy Product Barcode Scraper

Scrapes **EAN / UPC / GTIN** barcodes for **Renogy** products.

## Scrapers

| Script | Source | Use case |
|--------|--------|----------|
| `renogy_scraper.py` | **eBay primary**, Amazon fallback | Recommended — starts from the Renogy eBay AU store |
| `renogy_amazon_scraper.py` | Amazon only | Direct Amazon AU store scrape |

### Recommended: eBay primary + Amazon fallback

```bash
python renogy_scraper.py --output renogy_eans_ebay_primary.csv
```

Flow:

1. Crawl the [Renogy eBay AU store](https://www.ebay.com.au/str/renogysolarau) (categories + pagination)
2. Visit each `/itm/` listing and extract **UPC / EAN / GTIN** from Item specifics
3. Normalize all barcodes into the `ean` column
4. For listings missing a barcode, fall back to **Amazon AU** matched by model number or title
5. Uses `renogy_eans_au_all.csv` as Amazon cache if present (skips re-scraping Amazon)

### Options (`renogy_scraper.py`)

| Flag | Default | Description |
|------|---------|-------------|
| `--ebay-store-url` | Renogy eBay AU store | eBay store to crawl |
| `--amazon-cache` | `renogy_eans_au_all.csv` | Cached Amazon data for fallback |
| `--skip-amazon-scrape` | — | Only use Amazon cache, don't scrape Amazon |
| `--max-ebay-pages` | `10` | Pages per eBay store category |
| `--max-products` | `0` | Cap listings (0 = all) |
| `--delay` | `2.0` | Seconds between requests |
| `--ebay-item` | — | Scrape specific eBay item ID(s) |
| `--output` | `renogy_eans_ebay_primary.csv` | Output path (`.csv` or `.json`) |

### Examples

Full scrape with cached Amazon fallback:

```bash
python renogy_scraper.py --amazon-cache renogy_eans_au_all.csv --skip-amazon-scrape
```

Scrape specific eBay listings:

```bash
python renogy_scraper.py --ebay-item 296524321538 --ebay-item 296928240163 --skip-amazon-scrape
```

---

## Amazon-only scraper

**Default source:** [Renogy brand store](https://www.amazon.com.au/stores/Renogy/page/027078F8-DAAC-4849-888A-CDFBA339F29E) on Amazon Australia.

```bash
python renogy_amazon_scraper.py --output renogy_eans_au.csv
```

See `renogy_amazon_scraper.py --help` for Amazon-specific flags (`--use-search`, `--store-url`, etc.).

## Setup

```bash
cd scraper
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Output fields (unified scraper)

- `ean` — Normalized barcode (from eBay UPC/EAN/GTIN, or Amazon fallback)
- `model_number` — MPN / model from eBay or Amazon
- `ebay_item_id`, `ebay_url`, `ebay_price` — eBay listing data
- `asin`, `amazon_url`, `amazon_price` — Amazon match when found
- `barcode_source` — `ebay` or `amazon`
- `match_score` — Amazon title/model match confidence (0–1)
- `upc`, `gtin` — Raw identifiers when available

## Notes

- eBay Item specifics often include **MPN** but not always **UPC** — Amazon fallback covers those gaps.
- eBay may show a verification page for automated browsers. Increase `--delay` or run with `--headed` if blocked.
- Amazon may also throttle automated access; the Amazon scraper includes retry logic.
- Respect eBay and Amazon Terms of Service for your use case.
