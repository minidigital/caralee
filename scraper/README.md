# Renogy Amazon EAN Scraper

Scrapes **EAN** (European Article Number) codes for **Renogy**-branded products listed on Amazon.

**Default source:** [Renogy brand store](https://www.amazon.com.au/stores/Renogy/page/027078F8-DAAC-4849-888A-CDFBA339F29E) on Amazon Australia. The store page lists far more products than Amazon search (100+ vs ~9).

Uses [Playwright](https://playwright.dev/python/) to crawl the Renogy store and product pages, then extracts barcodes from product details (EAN, GTIN, or UPC).

## Requirements

- Python 3.10+
- Chromium (installed via Playwright)

## Setup

```bash
cd scraper
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Usage

Search Amazon Australia for Renogy products and save results to JSON:

```bash
python renogy_amazon_scraper.py --output renogy_eans_au.json
```

Common options:

| Flag | Default | Description |
|------|---------|-------------|
| `--marketplace` | `au` | Amazon region (`au`, `us`, `uk`, `de`, `fr`, `it`, `es`, `ca`) |
| `--query` | `Renogy` | Search term |
| `--max-pages` | `3` | Search result pages to crawl |
| `--max-products` | `0` | Cap number of products (0 = all found) |
| `--delay` | `2.0` | Seconds between page loads |
| `--output` | `renogy_eans_au.json` | Output path (`.json` or `.csv`) |
| `--use-search` | — | Use Amazon search instead of the Renogy brand store |
| `--store-url` | AU Renogy store | Brand store URL to crawl |
| `--max-store-pages` | `25` | Brand store sub-pages to crawl |
| `--no-brand-filter` | — | Skip Amazon brand filter (`p_4:Renogy`) on search |
| `--asin` | — | Scrape specific ASIN(s) instead of searching |
| `--headed` | — | Show the browser window (debugging) |

### Examples

Australian marketplace (default), first 10 products, CSV output:

```bash
python renogy_amazon_scraper.py --max-products 10 --output renogy_eans_au.csv
```

US marketplace:

```bash
python renogy_amazon_scraper.py --marketplace us --output renogy_eans_us.json
```

Single Australian ASIN:

```bash
python renogy_amazon_scraper.py --asin B08XYZ1234 --output single.json
```

## Output fields

Each record includes:

- `asin` — Amazon Standard Identification Number (marketplace-specific)
- `title` — Product title
- `brand` — Brand name
- `marketplace` — Marketplace code (e.g. `au` for amazon.com.au)
- `ean` — Best available 13-digit EAN (derived from EAN/GTIN/UPC when needed)
- `model_number` — Manufacturer model / part number from product details
- `upc`, `gtin` — Raw identifiers when present
- `price`, `url`
- `scrape_error` — Set when a product could not be fully scraped

## Notes

- The Renogy brand store on amazon.com.au is the recommended source for AU listings. Amazon search only returns ~9 Renogy products; the store has 100+.
- Amazon may block or throttle automated access. The scraper retries blocked pages and uses realistic browser settings; increase `--delay` if you see captchas or empty results.
- Not every listing exposes an EAN on the product page; some only show UPC (converted to EAN when possible).
- Respect [Amazon's Terms of Service](https://www.amazon.com.au/gp/help/customer/display.html) and applicable robots policies for your use case.
- For production or high-volume catalog sync, consider the [Amazon Product Advertising API](https://webservices.amazon.com/paapi5/documentation/) or a licensed data provider.
