#!/usr/bin/env python3
"""Scrape Renogy product barcodes: eBay primary, Amazon secondary fallback."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from playwright.sync_api import sync_playwright

from renogy_amazon_scraper import (
    BROWSER_ARGS,
    DEFAULT_AU_RENOGY_STORE,
    DEFAULT_MARKETPLACES,
    ProductRecord,
    create_browser_context,
    scrape_products,
    scrape_store_pages,
)
from renogy_ebay_scraper import (
    DEFAULT_EBAY_BASE,
    DEFAULT_EBAY_STORE,
    EbayListingHit,
    EbayProductRecord,
    create_ebay_context,
    scrape_ebay_products,
    scrape_store_listings,
)


@dataclass
class UnifiedProductRecord:
    title: str
    brand: str
    ean: str | None = None
    model_number: str | None = None
    upc: str | None = None
    gtin: str | None = None
    ebay_item_id: str | None = None
    ebay_url: str | None = None
    ebay_price: str | None = None
    asin: str | None = None
    amazon_url: str | None = None
    amazon_price: str | None = None
    barcode_source: str = "ebay"
    scrape_error: str | None = None
    match_score: float | None = None


def normalize_model_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def title_similarity(left: str, right: str) -> float:
    left_norm = normalize_whitespace(left).lower()
    right_norm = normalize_whitespace(right).lower()
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def load_amazon_cache(path: Path) -> list[ProductRecord]:
    if not path.exists():
        return []

    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        records: list[ProductRecord] = []
        for row in payload:
            records.append(
                ProductRecord(
                    asin=row.get("asin", ""),
                    title=row.get("title", ""),
                    brand=row.get("brand", "Renogy"),
                    url=row.get("url", ""),
                    marketplace=row.get("marketplace", "au"),
                    ean=row.get("ean") or None,
                    model_number=row.get("model_number") or None,
                    upc=row.get("upc") or None,
                    gtin=row.get("gtin") or None,
                    price=row.get("price") or None,
                    scrape_error=row.get("scrape_error") or None,
                )
            )
        return records

    records = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            records.append(
                ProductRecord(
                    asin=row.get("asin", ""),
                    title=row.get("title", ""),
                    brand=row.get("brand", "Renogy"),
                    url=row.get("url", ""),
                    marketplace=row.get("marketplace", "au"),
                    ean=row.get("ean") or None,
                    model_number=row.get("model_number") or None,
                    upc=row.get("upc") or None,
                    gtin=row.get("gtin") or None,
                    price=row.get("price") or None,
                    scrape_error=row.get("scrape_error") or None,
                )
            )
    return records


def build_amazon_index(records: list[ProductRecord]) -> dict[str, list[ProductRecord]]:
    index: dict[str, list[ProductRecord]] = {}
    for record in records:
        if record.model_number:
            key = normalize_model_key(record.model_number)
            index.setdefault(key, []).append(record)
    return index


def find_amazon_match(
    ebay_record: EbayProductRecord,
    amazon_records: list[ProductRecord],
    amazon_index: dict[str, list[ProductRecord]],
) -> tuple[ProductRecord | None, float]:
    if ebay_record.model_number:
        key = normalize_model_key(ebay_record.model_number)
        candidates = amazon_index.get(key, [])
        if len(candidates) == 1:
            return candidates[0], 1.0
        if candidates:
            best = max(candidates, key=lambda record: title_similarity(ebay_record.title, record.title))
            return best, title_similarity(ebay_record.title, best.title)

    best_record: ProductRecord | None = None
    best_score = 0.0
    for amazon_record in amazon_records:
        if not amazon_record.ean:
            continue
        score = title_similarity(ebay_record.title, amazon_record.title)
        if ebay_record.model_number and amazon_record.model_number:
            if normalize_model_key(ebay_record.model_number) == normalize_model_key(
                amazon_record.model_number
            ):
                score = max(score, 0.95)
        if score > best_score:
            best_score = score
            best_record = amazon_record

    if best_record and best_score >= 0.55:
        return best_record, best_score
    return None, 0.0


def merge_records(
    ebay_record: EbayProductRecord,
    amazon_record: ProductRecord | None,
    match_score: float,
) -> UnifiedProductRecord:
    unified = UnifiedProductRecord(
        title=ebay_record.title,
        brand=ebay_record.brand or "Renogy",
        ebay_item_id=ebay_record.item_id,
        ebay_url=ebay_record.url,
        ebay_price=ebay_record.price,
        model_number=ebay_record.model_number,
        barcode_source="ebay",
        scrape_error=ebay_record.scrape_error,
        match_score=match_score if amazon_record else None,
    )

    if ebay_record.ean:
        unified.ean = ebay_record.ean
        unified.upc = ebay_record.upc
        unified.gtin = ebay_record.gtin
        unified.barcode_source = "ebay"
    elif amazon_record and amazon_record.ean:
        unified.ean = amazon_record.ean
        unified.upc = amazon_record.upc
        unified.gtin = amazon_record.gtin
        unified.barcode_source = "amazon"
        unified.scrape_error = None
    else:
        unified.scrape_error = unified.scrape_error or "EAN/UPC/GTIN not found on eBay or Amazon"

    if amazon_record:
        unified.asin = amazon_record.asin
        unified.amazon_url = amazon_record.url
        unified.amazon_price = amazon_record.price
        if not unified.model_number:
            unified.model_number = amazon_record.model_number

    return unified


def scrape_amazon_catalog(
    browser,
    base_url: str,
    marketplace: str,
    store_url: str,
    delay: float,
    max_store_pages: int,
) -> list[ProductRecord]:
    context = create_browser_context(browser, marketplace=marketplace)
    page = context.new_page()
    search_hits = scrape_store_pages(
        page=page,
        base_url=base_url,
        store_url=store_url,
        delay=delay,
        max_store_pages=max_store_pages,
    )
    context.close()
    return scrape_products(
        browser=browser,
        base_url=base_url,
        marketplace=marketplace,
        search_hits=search_hits,
        delay=delay,
        headless=True,
    )


def write_json(path: Path, records: list[UnifiedProductRecord]) -> None:
    path.write_text(
        json.dumps([asdict(record) for record in records], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, records: list[UnifiedProductRecord]) -> None:
    fieldnames = [
        "title",
        "brand",
        "ean",
        "model_number",
        "upc",
        "gtin",
        "ebay_item_id",
        "ebay_url",
        "ebay_price",
        "asin",
        "amazon_url",
        "amazon_price",
        "barcode_source",
        "match_score",
        "scrape_error",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({key: getattr(record, key) for key in fieldnames})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Renogy products from eBay (primary) with Amazon fallback.",
    )
    parser.add_argument("--ebay-store-url", default=DEFAULT_EBAY_STORE)
    parser.add_argument("--ebay-base-url", default=DEFAULT_EBAY_BASE)
    parser.add_argument("--amazon-store-url", default=DEFAULT_AU_RENOGY_STORE)
    parser.add_argument("--amazon-marketplace", default="au", choices=sorted(DEFAULT_MARKETPLACES))
    parser.add_argument("--amazon-cache", type=Path, default=Path("renogy_eans_au_all.csv"))
    parser.add_argument("--skip-amazon-scrape", action="store_true")
    parser.add_argument("--max-ebay-pages", type=int, default=10)
    parser.add_argument("--max-amazon-store-pages", type=int, default=25)
    parser.add_argument("--max-products", type=int, default=0)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--output", type=Path, default=Path("renogy_eans_ebay_primary.csv"))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--ebay-item",
        action="append",
        default=[],
        help="Scrape specific eBay item ID(s) instead of crawling the store.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    headless = not args.headed
    amazon_base = DEFAULT_MARKETPLACES[args.amazon_marketplace]

    print(f"eBay store: {args.ebay_store_url}", file=sys.stderr)
    print(f"Amazon fallback: {amazon_base}", file=sys.stderr)
    print(f"Output: {args.output}", file=sys.stderr)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, args=BROWSER_ARGS)

        if args.ebay_item:
            listing_hits = [
                EbayListingHit(
                    item_id=item_id,
                    title="",
                    url=f"{args.ebay_base_url}/itm/{item_id}",
                )
                for item_id in args.ebay_item
            ]
        else:
            context = create_ebay_context(browser)
            page = context.new_page()
            listing_hits = scrape_store_listings(
                page=page,
                base_url=args.ebay_base_url,
                store_url=args.ebay_store_url,
                delay=args.delay,
                max_pages_per_category=args.max_ebay_pages,
            )
            context.close()

        if args.max_products > 0:
            listing_hits = listing_hits[: args.max_products]

        print(f"Scraping {len(listing_hits)} eBay listing(s)...", file=sys.stderr)
        ebay_records = scrape_ebay_products(
            browser=browser,
            base_url=args.ebay_base_url,
            listing_hits=listing_hits,
            delay=args.delay,
        )

        amazon_records = load_amazon_cache(args.amazon_cache)
        if not amazon_records and not args.skip_amazon_scrape:
            print("Loading Amazon catalog for fallback...", file=sys.stderr)
            amazon_records = scrape_amazon_catalog(
                browser=browser,
                base_url=amazon_base,
                marketplace=args.amazon_marketplace,
                store_url=args.amazon_store_url,
                delay=args.delay,
                max_store_pages=args.max_amazon_store_pages,
            )
        elif amazon_records:
            print(f"Loaded {len(amazon_records)} Amazon records from cache", file=sys.stderr)

        browser.close()

    amazon_index = build_amazon_index(amazon_records)
    unified_records: list[UnifiedProductRecord] = []

    for ebay_record in ebay_records:
        amazon_match, score = find_amazon_match(ebay_record, amazon_records, amazon_index)
        unified = merge_records(ebay_record, amazon_match, score)
        unified_records.append(unified)
        if unified.barcode_source == "amazon":
            print(
                f"  Amazon fallback for {ebay_record.item_id}: EAN {unified.ean} "
                f"(match score {score:.2f})",
                file=sys.stderr,
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix.lower() == ".json":
        write_json(args.output, unified_records)
    else:
        write_csv(args.output, unified_records)

    with_ean = sum(1 for record in unified_records if record.ean)
    ebay_ean = sum(1 for record in unified_records if record.barcode_source == "ebay" and record.ean)
    amazon_ean = sum(1 for record in unified_records if record.barcode_source == "amazon" and record.ean)
    print(
        f"Done. {with_ean}/{len(unified_records)} products have an EAN "
        f"({ebay_ean} from eBay, {amazon_ean} from Amazon fallback). "
        f"Wrote {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
