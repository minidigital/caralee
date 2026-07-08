#!/usr/bin/env python3
"""Scrape EAN codes for Renogy-branded products from Amazon."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, Page, sync_playwright

DEFAULT_MARKETPLACES: dict[str, str] = {
    "us": "https://www.amazon.com",
    "uk": "https://www.amazon.co.uk",
    "de": "https://www.amazon.de",
    "fr": "https://www.amazon.fr",
    "it": "https://www.amazon.it",
    "es": "https://www.amazon.es",
    "ca": "https://www.amazon.ca",
    "au": "https://www.amazon.com.au",
}

ASIN_PATTERN = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")
EAN_PATTERN = re.compile(r"\b(\d{13})\b")
UPC_TO_EAN_PATTERN = re.compile(r"\b0?(\d{12})\b")

IDENTIFIER_LABELS = (
    "ean",
    "gtin",
    "global trade identification number",
    "european article number",
    "upc",
    "universal product code",
)


@dataclass
class ProductRecord:
    asin: str
    title: str
    brand: str
    url: str
    ean: str | None = None
    model_number: str | None = None
    upc: str | None = None
    gtin: str | None = None
    price: str | None = None
    identifiers: dict[str, str] = field(default_factory=dict)
    scrape_error: str | None = None


MODEL_NUMBER_KEYS = (
    "item model number",
    "model number",
    "model name",
    "manufacturer part number",
    "part number",
    "mpn",
)


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def asin_from_url(url: str) -> str | None:
    match = ASIN_PATTERN.search(url)
    return match.group(1) if match else None


def upc_to_ean(upc: str) -> str | None:
    digits = re.sub(r"\D", "", upc)
    if len(digits) == 12:
        return f"0{digits}"
    if len(digits) == 13:
        return digits
    return None


def choose_best_ean(record: ProductRecord) -> str | None:
    if record.ean:
        return record.ean
    if record.gtin and len(re.sub(r"\D", "", record.gtin)) == 13:
        return re.sub(r"\D", "", record.gtin)
    if record.upc:
        return upc_to_ean(record.upc)
    for key in ("ean", "gtin", "upc"):
        value = record.identifiers.get(key)
        if not value:
            continue
        digits = re.sub(r"\D", "", value)
        if len(digits) == 13:
            return digits
        if len(digits) == 12:
            return f"0{digits}"
    return None


def is_renogy_brand(brand: str, title: str) -> bool:
    combined = f"{brand} {title}".lower()
    return "renogy" in combined


def build_search_url(base_url: str, query: str, page: int, brand: str | None = "Renogy") -> str:
    params: dict[str, str] = {"k": query, "page": str(page)}
    if brand:
        params["rh"] = f"p_4:{brand}"
    return f"{base_url}/s?{urlencode(params)}"


def wait_for_results(page: Page) -> None:
    page.wait_for_load_state("domcontentloaded")
    try:
        page.wait_for_selector(
            "[data-component-type='s-search-result'][data-asin]:not([data-asin=''])",
            timeout=20_000,
        )
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass
    time.sleep(2.0)


def parse_search_results(
    html: str,
    base_url: str,
    *,
    require_renogy_in_listing: bool = True,
) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, str]] = []
    seen_asins: set[str] = set()

    for item in soup.select("[data-component-type='s-search-result'], .s-result-item[data-asin]"):
        asin = item.get("data-asin", "").strip()
        if not asin or asin in seen_asins:
            continue

        title_el = item.select_one(
            "a.a-link-normal .a-text-normal, h2 a.a-link-normal span, .a-text-normal"
        )
        title = normalize_whitespace(title_el.get_text()) if title_el else ""

        brand_el = item.select_one(
            ".a-size-base.a-color-secondary:not(:empty), "
            "[data-cy='title-recipe-brand'] .a-size-base"
        )
        brand = normalize_whitespace(brand_el.get_text()) if brand_el else ""
        if any(
            phrase in brand.lower()
            for phrase in (
                "amazon's choice",
                "best seller",
                "bought in past month",
                "bought in past week",
                "new on amazon",
            )
        ):
            brand = ""

        link_el = item.select_one("h2 a[href]")
        href = link_el.get("href", "") if link_el else ""
        url = f"{base_url}{href}" if href.startswith("/") else href
        if not url:
            url = f"{base_url}/dp/{asin}"

        if require_renogy_in_listing and not is_renogy_brand(brand, title):
            continue

        seen_asins.add(asin)
        results.append({"asin": asin, "title": title, "brand": brand, "url": url})

    return results


def extract_key_value_pairs(soup: BeautifulSoup) -> dict[str, str]:
    pairs: dict[str, str] = {}

    selectors = [
        "#detailBullets_feature_div li",
        "#productDetails_detailBullets_sections1 tr",
        "#productDetails_techSpec_section_1 tr",
        "#productDetails_techSpec_section_2 tr",
        ".prodDetTable tr",
        "#poExpander tr",
    ]
    for selector in selectors:
        for row in soup.select(selector):
            if row.name == "li":
                text = normalize_whitespace(row.get_text(" ", strip=True))
                if ":" in text:
                    key, value = text.split(":", 1)
                    pairs[normalize_whitespace(key).lower()] = normalize_whitespace(value)
                continue

            th = row.select_one("th")
            td = row.select_one("td")
            if not th or not td:
                continue
            key = normalize_whitespace(th.get_text()).lower()
            value = normalize_whitespace(td.get_text(" ", strip=True))
            if key and value:
                pairs[key] = value

    for block in soup.select("#detailBullets_feature_div, #productDetails_db_sections"):
        text = block.get_text("\n", strip=True)
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = normalize_whitespace(key).lower()
            value = normalize_whitespace(value)
            if key and value and key not in pairs:
                pairs[key] = value

    return pairs


def extract_identifiers_from_pairs(pairs: dict[str, str]) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    for key, value in pairs.items():
        normalized_key = key.lower()
        if any(label in normalized_key for label in IDENTIFIER_LABELS):
            clean = re.sub(r"\D", "", value)
            if clean:
                if "upc" in normalized_key:
                    identifiers["upc"] = clean
                elif "ean" in normalized_key:
                    identifiers["ean"] = clean
                elif "gtin" in normalized_key:
                    identifiers["gtin"] = clean
                else:
                    identifiers[normalized_key] = clean
    return identifiers


def extract_model_number(pairs: dict[str, str], soup: BeautifulSoup) -> str | None:
    for key in MODEL_NUMBER_KEYS:
        value = pairs.get(key)
        if value:
            return value

    for selector in (
        "tr.po-model_number span.po-break-word",
        "#productOverview_feature_div tr.po-model_number td",
        "span.po-model_number .po-break-word",
    ):
        element = soup.select_one(selector)
        if element:
            value = normalize_whitespace(element.get_text())
            if value:
                return value

    return None


def extract_product_record(
    html: str,
    asin: str,
    url: str,
    search_title: str = "",
    search_brand: str = "",
) -> ProductRecord:
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one("#productTitle")
    title = normalize_whitespace(title_el.get_text()) if title_el else search_title

    brand_el = soup.select_one(
        "#bylineInfo, .po-brand .a-span9 span, tr.po-brand span.po-break-word"
    )
    brand = normalize_whitespace(brand_el.get_text()) if brand_el else search_brand
    brand = re.sub(
        r"^Visit the\s+|\s+Store$|^Brand:\s*",
        "",
        brand,
        flags=re.IGNORECASE,
    ).strip()

    price_el = soup.select_one(".a-price .a-offscreen, #priceblock_ourprice, #priceblock_dealprice")
    price = normalize_whitespace(price_el.get_text()) if price_el else None

    pairs = extract_key_value_pairs(soup)
    identifiers = extract_identifiers_from_pairs(pairs)

    if not brand:
        brand = pairs.get("brand", search_brand)

    record = ProductRecord(
        asin=asin,
        title=title,
        brand=brand,
        url=url,
        price=price,
        model_number=extract_model_number(pairs, soup),
        identifiers=identifiers,
        ean=identifiers.get("ean"),
        upc=identifiers.get("upc"),
        gtin=identifiers.get("gtin"),
    )

    if not record.ean:
        page_text = soup.get_text(" ", strip=True)
        for match in EAN_PATTERN.finditer(page_text):
            candidate = match.group(1)
            if candidate.startswith("978"):
                continue
            record.ean = candidate
            break

    if not record.ean and record.upc:
        record.ean = upc_to_ean(record.upc)

    record.ean = choose_best_ean(record)
    return record


def dismiss_cookie_banner(page: Page) -> None:
    selectors = [
        "#sp-cc-accept",
        "input#sp-cc-accept",
        "button[data-action='a-popover-close']",
    ]
    for selector in selectors:
        try:
            if page.locator(selector).count():
                page.locator(selector).first.click(timeout=2_000)
                time.sleep(0.5)
                return
        except Exception:
            continue


STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
"""

BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


def create_browser_context(browser: Browser):
    context = browser.new_context(
        locale="en-US",
        timezone_id="America/New_York",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 900},
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
        },
    )
    context.add_init_script(STEALTH_INIT_SCRIPT)
    return context


def is_blocked_page(html: str, title: str = "") -> bool:
    lowered = f"{title} {html[:5000]}".lower()
    if len(html) < 10_000:
        return True
    blocked_markers = (
        "sorry! something went wrong",
        "enter the characters you see below",
        "type the characters you see in this image",
        "robot check",
        "automated access",
    )
    return any(marker in lowered for marker in blocked_markers)


def fetch_page_html(page: Page, url: str, delay: float, retries: int = 3) -> str:
    last_html = ""
    for attempt in range(1, retries + 1):
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        dismiss_cookie_banner(page)
        time.sleep(delay)

        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            time.sleep(0.4)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.3)

        last_html = page.content()
        if not is_blocked_page(last_html, page.title()):
            return last_html

        print(
            f"  Blocked or empty page (attempt {attempt}/{retries}), retrying...",
            file=sys.stderr,
        )
        time.sleep(delay * attempt)

    return last_html


def scrape_search_pages(
    page: Page,
    base_url: str,
    query: str,
    max_pages: int,
    delay: float,
    brand_filter: str | None = "Renogy",
) -> list[dict[str, str]]:
    all_results: list[dict[str, str]] = []
    seen_asins: set[str] = set()

    for page_num in range(1, max_pages + 1):
        search_url = build_search_url(base_url, query, page_num, brand=brand_filter)
        print(f"Searching page {page_num}: {search_url}", file=sys.stderr)
        page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
        dismiss_cookie_banner(page)
        wait_for_results(page)

        html = page.content()
        if is_blocked_page(html, page.title()):
            print("  Search page blocked, retrying once...", file=sys.stderr)
            time.sleep(delay * 2)
            page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
            dismiss_cookie_banner(page)
            wait_for_results(page)
            html = page.content()
        page_results = parse_search_results(
            html,
            base_url,
            require_renogy_in_listing=brand_filter is None,
        )
        new_items = [item for item in page_results if item["asin"] not in seen_asins]
        for item in new_items:
            seen_asins.add(item["asin"])
        all_results.extend(new_items)

        print(f"  Found {len(new_items)} Renogy products on page {page_num}", file=sys.stderr)
        if not new_items and page_num > 1:
            break
        time.sleep(delay)

    return all_results


def scrape_products(
    browser: Browser,
    base_url: str,
    search_hits: list[dict[str, str]],
    delay: float,
    headless: bool,
) -> list[ProductRecord]:
    context = create_browser_context(browser)
    page = context.new_page()
    records: list[ProductRecord] = []

    for index, hit in enumerate(search_hits, start=1):
        asin = hit["asin"]
        product_url = f"{base_url}/dp/{asin}"
        print(f"[{index}/{len(search_hits)}] Scraping {asin}: {hit.get('title', '')[:70]}", file=sys.stderr)

        try:
            html = fetch_page_html(page, product_url, delay)
            record = extract_product_record(
                html,
                asin=asin,
                url=product_url,
                search_title=hit.get("title", ""),
                search_brand=hit.get("brand", ""),
            )

            if not is_renogy_brand(record.brand, record.title):
                print(f"  Skipping non-Renogy listing: brand={record.brand!r}", file=sys.stderr)
                continue

            if not record.ean:
                record.scrape_error = "EAN not found on product page"
                print("  Warning: EAN not found", file=sys.stderr)
            else:
                print(f"  EAN: {record.ean}", file=sys.stderr)

            if record.model_number:
                print(f"  Model: {record.model_number}", file=sys.stderr)

            records.append(record)
        except Exception as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            records.append(
                ProductRecord(
                    asin=asin,
                    title=hit.get("title", ""),
                    brand=hit.get("brand", ""),
                    url=product_url,
                    scrape_error=str(exc),
                )
            )

        time.sleep(delay)

    context.close()
    return records


def write_json(path: Path, records: list[ProductRecord]) -> None:
    payload = [asdict(record) for record in records]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, records: list[ProductRecord]) -> None:
    fieldnames = [
        "asin",
        "title",
        "brand",
        "ean",
        "model_number",
        "upc",
        "gtin",
        "price",
        "url",
        "scrape_error",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({key: getattr(record, key) for key in fieldnames})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape EAN codes for Renogy-branded products from Amazon.",
    )
    parser.add_argument(
        "--marketplace",
        choices=sorted(DEFAULT_MARKETPLACES),
        default="us",
        help="Amazon marketplace to scrape (default: us).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override marketplace base URL (e.g. https://www.amazon.com).",
    )
    parser.add_argument(
        "--query",
        default="Renogy",
        help="Search query used on Amazon (default: Renogy).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Maximum search result pages to crawl (default: 3).",
    )
    parser.add_argument(
        "--max-products",
        type=int,
        default=0,
        help="Maximum products to scrape after search (0 = no limit).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay in seconds between requests (default: 2.0).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("renogy_eans.json"),
        help="Output file path (.json or .csv).",
    )
    parser.add_argument(
        "--no-brand-filter",
        action="store_true",
        help="Do not apply Amazon's brand filter (p_4) on search.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed mode (useful for debugging).",
    )
    parser.add_argument(
        "--asin",
        action="append",
        default=[],
        help="Scrape specific ASIN(s) instead of running search. Can be repeated.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base_url = args.base_url or DEFAULT_MARKETPLACES[args.marketplace]
    headless = not args.headed

    print(f"Marketplace: {base_url}", file=sys.stderr)
    print(f"Output: {args.output}", file=sys.stderr)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=headless,
            args=BROWSER_ARGS,
        )

        if args.asin:
            search_hits = [
                {"asin": asin, "title": "", "brand": "Renogy", "url": f"{base_url}/dp/{asin}"}
                for asin in args.asin
            ]
        else:
            context = create_browser_context(browser)
            page = context.new_page()
            search_hits = scrape_search_pages(
                page=page,
                base_url=base_url,
                query=args.query,
                max_pages=args.max_pages,
                delay=args.delay,
                brand_filter=None if args.no_brand_filter else "Renogy",
            )
            context.close()

        if args.max_products > 0:
            search_hits = search_hits[: args.max_products]

        print(f"Scraping {len(search_hits)} product(s)...", file=sys.stderr)
        records = scrape_products(
            browser=browser,
            base_url=base_url,
            search_hits=search_hits,
            delay=args.delay,
            headless=headless,
        )
        browser.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix.lower() == ".csv":
        write_csv(args.output, records)
    else:
        write_json(args.output, records)

    with_ean = sum(1 for record in records if record.ean)
    print(
        f"Done. {with_ean}/{len(records)} products have an EAN. Wrote {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
