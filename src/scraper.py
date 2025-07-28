#!/usr/bin/env python3
"""
collect_news.py  –  Autonomous news/blog collector for a single company.

▶ Usage:
    python collect_news.py --company "NVIDIA" --ticker NVDA --max 15
"""

from __future__ import annotations
import os, csv, time, argparse, pathlib, json
from datetime import datetime
from slugify import slugify

from serpapi import GoogleSearch
from newspaper import Article

DATA_ROOT = pathlib.Path("data")

def serpapi_news_links(query: str, api_key: str, max_results: int = 20) -> list[str]:
    """Return up to `max_results` news URLs from Google News via SerpAPI."""
    search = GoogleSearch({
        "q": query,
        "tbm": "nws",
        "num": max_results,
        "api_key": api_key
    })
    result = search.get_dict()
    news = result.get("news_results", [])
    return [item["link"] for item in news][:max_results]

def scrape_article(url: str) -> dict | None:
    """Download & parse an article. Returns dict or None on failure."""
    try:
        art = Article(url, language="en")
        art.download()
        art.parse()
        return {
            "url": url,
            "title": art.title or "Untitled",
            "publish_date": art.publish_date.isoformat() if art.publish_date else "",
            "text": art.text
        }
    except Exception as e:
        print(f"[warn] could not scrape {url}: {e}")
        return None

def load_seen(set_path: pathlib.Path) -> set[str]:
    if set_path.exists():
        with open(set_path, newline="") as f:
            return {row["url"] for row in csv.DictReader(f)}
    return set()

def append_index(set_path: pathlib.Path, row: dict):
    newfile = not set_path.exists()
    with open(set_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "file"])
        if newfile:
            writer.writeheader()
        writer.writerow(row)

def save_article_md(base_dir: pathlib.Path, meta: dict):
    ts = datetime.utcnow().strftime("%Y-%m-%d-%H%M%S")
    fname = f"{ts}_{slugify(meta['title'][:60])}.md"
    file_path = base_dir / fname
    md = (
        f"---\n"
        f"title: \"{meta['title']}\"\n"
        f"source_url: {meta['url']}\n"
        f"publish_date: {meta['publish_date']}\n"
        f"---\n\n"
        f"{meta['text']}\n"
    )
    file_path.write_text(md, encoding="utf-8")
    return file_path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True, help="Company name, e.g. NVIDIA")
    parser.add_argument("--ticker", required=True, help="Ticker, e.g. NVDA")
    parser.add_argument("--max", type=int, default=20, help="Max URLs per run")
    args = parser.parse_args()

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise RuntimeError("Set SERPAPI_API_KEY environment variable first.")

    query = f"{args.company} stock news"
    urls = serpapi_news_links(query, api_key, max_results=args.max)

    # Prepare storage
    comp_dir = DATA_ROOT / args.ticker.upper()
    comp_dir.mkdir(parents=True, exist_ok=True)
    index_csv = comp_dir / "articles_index.csv"
    seen = load_seen(index_csv)

    print(f"[info] fetched {len(urls)} candidate URLs, {len(seen)} already seen.")

    for url in urls:
        if url in seen:
            continue
        meta = scrape_article(url)
        if not meta:  # failed scrape
            continue
        md_file = save_article_md(comp_dir, meta)
        append_index(index_csv, {"url": url, "file": md_file.name})
        seen.add(url)
        print(f"[saved] {md_file}")
        time.sleep(1)  # be polite to servers

if __name__ == "__main__":
    main()
