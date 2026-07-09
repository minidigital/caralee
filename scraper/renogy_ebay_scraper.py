"""Scrape Renogy products from the eBay Australia store."""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, Page, sync_playwright

from renogy_amazon_scraper import (
    BROWSER_ARGS,
    STEALTH_INIT_SCRIPT,
    barcode_candidate_score,
    classify_barcode,
    normalize_barcode_to_ean,
    normalize_whitespace,
    split_barcode_values,
)

DEFAULT_EBAY_BASE = "https://www.ebay.com.au"
DEFAULT_EBAY_STORE = f"{DEFAULT_EBAY_BASE}/str/renogysolarau"

EBAY_ITEM_PATTERN = re.compile(r"/itm/(\d+)")
EBAY_BLOCKED_MARKERS = (
    "please verify yourself",
    "error page | ebay",
    "something went wrong on our end",
    "security measure | ebay",
)

IDENTIFIER_KEYS = (
    "upc",
    "ean",
    "gtin",
    "global trade item number",
    "global trade identification number",
    "barcode",
)

MODEL_KEYS = ("mpn", "manufacturer part number", "model", "model number", "part number")


@dataclass
class EbayListingHit:
    item_id: str
    title: str
    url: str
    price: str | None = None


@dataclass
class EbayProductRecord:
    item_id: str
    title: str
    brand: str
    url: str
    ean: str | None = None
    model_number: str | None = None
    upc: str | None = None
    gtin: str | None = None
    price: str | None = None
    item_specifics: dict[str, str] = field(default_factory=dict)
    barcode_source: str = "ebay"
    scrape_error: str | None = None


def create_ebay_context(browser: Browser):
    context = browser.new_context(
        locale="en-AU",
        timezone_id="Australia/Sydney",
        geolocation={"longitude": 151.2093, "latitude": -33.8688},
        permissions=["geolocation"],
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 900},
        extra_http_headers={
            "Accept-Language": "en-AU,en;q=0.9",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
        },
    )
    context.add_init_script(STEALTH_INIT_SCRIPT)
    return context


def is_ebay_blocked(html: str, title: str = "") -> bool:
    lowered = f"{title} {html[:8000]}".lower()
    if len(html) < 5_000:
        return True
    return any(marker in lowered for marker in EBAY_BLOCKED_MARKERS)


def dismiss_ebay_consent(page: Page) -> None:
    selectors = [
        "#gdpr-banner-accept",
        "button#consent-accept",
        "button:has-text('Accept')",
    ]
    for selector in selectors:
        try:
            if page.locator(selector).count():
                page.locator(selector).first.click(timeout=2_000)
                time.sleep(0.5)
                return
        except Exception:
            continue


def fetch_ebay_page(page: Page, url: str, delay: float, retries: int = 3) -> str:
    last_html = ""
    for attempt in range(1, retries + 1):
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        dismiss_ebay_consent(page)
        time.sleep(delay)

        for _ in range(4):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.4)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.3)

        last_html = page.content()
        if not is_ebay_blocked(last_html, page.title()):
            return last_html

        print(f"  eBay blocked or empty page (attempt {attempt}/{retries})", file=sys.stderr)
        time.sleep(delay * attempt)

    return last_html


def add_page_param(url: str, page_num: int) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    params["_pgn"] = [str(page_num)]
    query = urlencode({key: values[0] for key, values in params.items()})
    return urlunparse(parsed._replace(query=query))


def discover_store_category_urls(html: str, base_url: str, store_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    categories: list[str] = []
    seen: set[str] = set()
    store_path = urlparse(store_url).path.rstrip("/")

    for link in soup.select("a[href]"):
        href = link.get("href", "")
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if store_path not in parsed.path:
            continue
        if not parsed.path.endswith("/_i.html") and "/_i.html" not in parsed.path:
            continue
        normalized = urlunparse(parsed._replace(query="", fragment=""))
        if normalized not in seen:
            seen.add(normalized)
            categories.append(normalized)

    if not categories:
        fallback_paths = (
            "Solar-Panels",
            "Charge-Controllers",
            "Battery-Chargers",
            "Inverters",
            "Accessories-Wiring",
            "Solar-Kits",
            "Deep-Cycle-Batteries",
        )
        for path in fallback_paths:
            categories.append(f"{base_url}{store_path}/{path}/_i.html")

    all_items = f"{base_url}{store_path}/_i.html"
    if all_items not in categories:
        categories.insert(0, all_items)

    return categories


def parse_store_listings(html: str, base_url: str) -> list[EbayListingHit]:
    soup = BeautifulSoup(html, "html.parser")
    hits: dict[str, EbayListingHit] = {}

    for link in soup.select("a[href*='/itm/']"):
        href = link.get("href", "")
        match = EBAY_ITEM_PATTERN.search(href)
        if not match:
            continue
        item_id = match.group(1)
        title = normalize_whitespace(link.get_text())
        if not title or title.lower() in {"shop on ebay", "new listing"}:
            title_el = link.select_one(".s-item__title, .str-item-card__title, .str-card-title")
            if title_el:
                title = normalize_whitespace(title_el.get_text())
        url = urljoin(base_url, href.split("?")[0])
        price = None
        card = link.find_parent(class_=re.compile("s-item|str-item|item-card"))
        if card:
            price_el = card.select_one(".s-item__price, .str-item-card__price, .str-card-price")
            if price_el:
                price = normalize_whitespace(price_el.get_text())
        hits[item_id] = EbayListingHit(item_id=item_id, title=title, url=url, price=price)

    for match in EBAY_ITEM_PATTERN.finditer(html):
        item_id = match.group(1)
        if item_id not in hits:
            hits[item_id] = EbayListingHit(
                item_id=item_id,
                title="",
                url=f"{base_url}/itm/{item_id}",
            )

    return list(hits.values())


def extract_item_specifics(soup: BeautifulSoup) -> dict[str, str]:
    specifics: dict[str, str] = {}

    for block in soup.select("div.ux-labels-values"):
        labels = block.select(
            ".ux-labels-values__labels-content, .ux-labels-values__labels, dt"
        )
        values = block.select(
            ".ux-labels-values__values-content, .ux-labels-values__values, dd"
        )
        for label_el, value_el in zip(labels, values):
            key = normalize_whitespace(label_el.get_text()).lower()
            value = normalize_whitespace(value_el.get_text())
            if key and value and value.lower() not in {"does not apply", "n/a"}:
                specifics[key] = value

    for row in soup.select("div.ux-layout-section-module-attributes tr, .item-specifics tr"):
        cells = row.select("td, th")
        if len(cells) >= 2:
            key = normalize_whitespace(cells[0].get_text()).lower()
            value = normalize_whitespace(cells[1].get_text())
            if key and value and value.lower() not in {"does not apply", "n/a"}:
                specifics[key] = value

    for dt in soup.select("dl dt"):
        key = normalize_whitespace(dt.get_text()).lower()
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        value = normalize_whitespace(dd.get_text())
        if key and value and value.lower() not in {"does not apply", "n/a"}:
            specifics[key] = value

    return specifics


def identifiers_from_specifics(specifics: dict[str, str]) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    typed: dict[str, str] = {}

    for key, value in specifics.items():
        if not any(label in key for label in IDENTIFIER_KEYS):
            continue
        identifiers[key] = value
        for digits in split_barcode_values(value):
            ean, upc, gtin = classify_barcode(digits)
            if ean and "ean" not in typed:
                typed["ean"] = ean
            if upc and "upc" not in typed:
                typed["upc"] = upc
            if gtin and "gtin" not in typed:
                typed["gtin"] = gtin

    typed.update(identifiers)
    return typed


def extract_model_number(specifics: dict[str, str]) -> str | None:
    for key in MODEL_KEYS:
        value = specifics.get(key)
        if value:
            return value
    return None


def extract_ebay_product_record(html: str, item_id: str, url: str) -> EbayProductRecord:
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one("h1.x-item-title__mainTitle, h1.it-ttl, #itemTitle, h1")
    title = normalize_whitespace(title_el.get_text()) if title_el else ""

    price_el = soup.select_one(
        ".x-price-primary .ux-textspans, #prcIsum, .x-bin-price__content .ux-textspans"
    )
    price = normalize_whitespace(price_el.get_text()) if price_el else None

    specifics = extract_item_specifics(soup)
    identifiers = identifiers_from_specifics(specifics)
    brand = specifics.get("brand", "Renogy")
    model_number = extract_model_number(specifics)

    record = EbayProductRecord(
        item_id=item_id,
        title=title,
        brand=brand,
        url=url,
        price=price,
        model_number=model_number,
        item_specifics={k: v for k, v in specifics.items() if k not in identifiers},
        ean=identifiers.get("ean"),
        upc=identifiers.get("upc"),
        gtin=identifiers.get("gtin"),
        barcode_source="ebay",
    )

    if not record.ean:
        detail_text = " ".join(specifics.values())
        for digits in split_barcode_values(detail_text):
            ean = normalize_barcode_to_ean(digits)
            if ean:
                record.ean = ean
                break

    if not record.ean:
        candidates: list[str] = []
        for value in (record.ean, record.upc, record.gtin):
            if value:
                candidates.extend(split_barcode_values(value))
        for value in identifiers.values():
            candidates.extend(split_barcode_values(value))

        best_ean: str | None = None
        best_score = -1
        seen: set[str] = set()
        for digits in candidates:
            if digits in seen:
                continue
            seen.add(digits)
            score = barcode_candidate_score(digits)
            ean = normalize_barcode_to_ean(digits)
            if ean and score > best_score:
                best_score = score
                best_ean = ean
        record.ean = best_ean

    if record.ean and not record.upc:
        upc_match = re.search(r"(\d{12})$", record.ean)
        if upc_match:
            record.upc = upc_match.group(1)
    if record.ean and not record.gtin:
        record.gtin = record.ean

    return record


def scrape_store_listings(
    page: Page,
    base_url: str,
    store_url: str,
    delay: float,
    max_pages_per_category: int,
) -> list[EbayListingHit]:
    html = fetch_ebay_page(page, store_url, delay)
    if is_ebay_blocked(html, page.title()):
        print("eBay store blocked during discovery", file=sys.stderr)
        return []

    categories = discover_store_category_urls(html, base_url, store_url)
    print(f"Discovered {len(categories)} eBay store categories", file=sys.stderr)

    all_hits: list[EbayListingHit] = []
    seen_ids: set[str] = set()

    for category_url in categories:
        print(f"Category: {category_url}", file=sys.stderr)
        for page_num in range(1, max_pages_per_category + 1):
            page_url = add_page_param(category_url, page_num)
            html = fetch_ebay_page(page, page_url, delay)
            page_hits = parse_store_listings(html, base_url)
            new_hits = [hit for hit in page_hits if hit.item_id not in seen_ids]
            for hit in new_hits:
                seen_ids.add(hit.item_id)
            all_hits.extend(new_hits)
            print(
                f"  Page {page_num}: {len(new_hits)} new listings ({len(all_hits)} total)",
                file=sys.stderr,
            )
            if not new_hits and page_num > 1:
                break
            time.sleep(delay)

    return all_hits


def scrape_ebay_products(
    browser: Browser,
    base_url: str,
    listing_hits: list[EbayListingHit],
    delay: float,
) -> list[EbayProductRecord]:
    context = create_ebay_context(browser)
    page = context.new_page()
    records: list[EbayProductRecord] = []

    for index, hit in enumerate(listing_hits, start=1):
        print(
            f"[{index}/{len(listing_hits)}] eBay {hit.item_id}: {hit.title[:70]}",
            file=sys.stderr,
        )
        try:
            html = fetch_ebay_page(page, hit.url, delay)
            record = extract_ebay_product_record(html, hit.item_id, hit.url)
            if not record.title:
                record.title = hit.title
            if not record.price:
                record.price = hit.price
            if not record.ean:
                record.scrape_error = "EAN/UPC/GTIN not found on eBay listing"
                print("  Warning: no barcode on eBay", file=sys.stderr)
            else:
                print(f"  EAN: {record.ean}", file=sys.stderr)
            if record.model_number:
                print(f"  Model: {record.model_number}", file=sys.stderr)
            records.append(record)
        except Exception as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            records.append(
                EbayProductRecord(
                    item_id=hit.item_id,
                    title=hit.title,
                    brand="Renogy",
                    url=hit.url,
                    price=hit.price,
                    scrape_error=str(exc),
                )
            )
        time.sleep(delay)

    context.close()
    return records
