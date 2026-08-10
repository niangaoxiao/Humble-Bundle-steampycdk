# -*- coding: utf-8 -*-
"""
Extract game list + metadata from a Humble Bundle product page.

Only works for humblebundle.com bundle pages (parses embedded page JSON).
Other stores: use a hand-written JSON or a plain text name list instead.

Usage:
  python scripts/extract_hb_bundle.py "https://www.humblebundle.com/games/xxx"
  python scripts/extract_hb_bundle.py URL -o examples/my_bundle.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Non-game machine_name entries sometimes present on HB pages
SKIP_ITEMS = {"comicrelief"}


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_bundle_json(html: str) -> dict[str, Any]:
    m = re.search(
        r"<script[^>]*>\s*(\{\"userOptions\".*?\})\s*</script>", html, re.S
    )
    if not m:
        raise RuntimeError(
            "No bundle JSON (userOptions/bundleData) found. "
            "This URL may not be a Humble Bundle page, or HB changed their HTML."
        )
    return json.loads(m.group(1))


def extract_key_expire_hint(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(
        r"(?:redeem before|Keys expire[^.]{0,40}?before)\s+"
        r"([A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?,?\s*\d{4})",
        text,
        re.I,
    )
    if m:
        return m.group(1)
    m = re.search(r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})", text)
    if m and ("expire" in text.lower() or "过期" in text or "redeem" in text.lower()):
        return m.group(1)
    return None


def extract_bundle(url: str) -> dict[str, Any]:
    html = fetch_html(url)
    raw = parse_bundle_json(html)
    bd = raw["bundleData"]
    basic = bd.get("basic_data") or {}
    items = bd.get("tier_item_data") or {}
    tier_display = bd.get("tier_display_data") or {}
    tier_order = bd.get("tier_order") or list(tier_display.keys())

    # Prefer the longest tier list as full-bundle order
    full_order_ids: list[str] = []
    for tid in tier_order:
        t = tier_display.get(tid) or {}
        names = t.get("tier_item_machine_names") or []
        if len(names) > len(full_order_ids):
            full_order_ids = list(names)

    def item_name(mid: str) -> str | None:
        if mid in SKIP_ITEMS:
            return None
        info = items.get(mid) or {}
        return info.get("human_name")

    games_ordered: list[dict[str, Any]] = []
    for mid in full_order_ids:
        name = item_name(mid)
        if not name:
            continue
        games_ordered.append(
            {
                "machine_name": mid,
                "hb_name": name,
                "name": name,
                "search_queries": [name],
            }
        )

    tiers: dict[str, Any] = {}
    for tid in tier_order:
        t = tier_display.get(tid) or {}
        mids = [
            m
            for m in (t.get("tier_item_machine_names") or [])
            if m not in SKIP_ITEMS
        ]
        tiers[tid] = {
            "header": t.get("header"),
            "identifier": t.get("identifier") or tid,
            "games": [item_name(m) for m in mids if item_name(m)],
        }

    desc = basic.get("description") or basic.get("detailed_marketing_blurb") or ""
    key_expire = extract_key_expire_hint(desc)

    return {
        "source": "humblebundle",
        "source_url": url.split("?")[0],
        "name": basic.get("human_name"),
        "machine_name": bd.get("machine_name"),
        "end_time_utc": basic.get("end_time|datetime"),
        "start_time_utc": None,
        "key_expire_hint": key_expire,
        "currency": basic.get("currency"),
        "short_blurb": basic.get("short_marketing_blurb"),
        "tiers": tiers,
        "tier_order": tier_order,
        "games_count": len(games_ordered),
        "games": games_ordered,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract games from a Humble Bundle URL")
    ap.add_argument("url", help="Humble Bundle product URL")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (default: examples/last_bundle.json)",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    out = args.output or (root / "examples" / "last_bundle.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        data = extract_bundle(args.url)
    except Exception as e:
        print(f"Extract failed: {e}", file=sys.stderr)
        return 1

    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Name: {data.get('name')}")
    print(f"Ends (UTC): {data.get('end_time_utc')}")
    print(f"Key hint: {data.get('key_expire_hint')}")
    print(f"Games: {data.get('games_count')}")
    for i, g in enumerate(data.get("games") or [], 1):
        print(f"  {i:02d}. {g.get('hb_name') or g.get('name')}")
    print(f"Wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
