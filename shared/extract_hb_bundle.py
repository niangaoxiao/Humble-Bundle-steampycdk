# -*- coding: utf-8 -*-
"""
Extract game list + CNY tier prices + times from Humble Bundle product pages.

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
from html import unescape
from pathlib import Path
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

SKIP_ITEMS = {"comicrelief"}


def fetch_html(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_page_json(html: str) -> dict[str, Any]:
    """Classic bundle pages embed a large {\"userOptions\":...} JSON in a script tag."""
    m = re.search(r"<script[^>]*>\s*(\{\"userOptions\".*?\})\s*</script>", html, re.S)
    if m:
        return json.loads(m.group(1))
    # Fallback: raw_decode first object that contains bundleData
    for m in re.finditer(r"<script[^>]*>\s*(\{)", html, re.S):
        start = m.start(1)
        try:
            obj, _ = json.JSONDecoder().raw_decode(html[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "bundleData" in obj:
            return obj
    raise RuntimeError(
        "No bundle JSON found. Not a classic HB games bundle page, or HTML changed."
    )


def money_amount(obj: Any) -> tuple[float | None, str | None]:
    if not isinstance(obj, dict):
        return None, None
    amt = obj.get("amount")
    cur = obj.get("currency")
    try:
        return (float(amt) if amt is not None else None), (str(cur) if cur else None)
    except (TypeError, ValueError):
        return None, None


def parse_exchange_rates(raw: dict[str, Any]) -> dict[str, float]:
    """HB embeds rates as {'CNY|decimal': 6.74..., 'USD|decimal': 1.0, ...} vs USD."""
    rates_in = raw.get("exchangeRates") or {}
    out: dict[str, float] = {}
    if not isinstance(rates_in, dict):
        return out
    for k, v in rates_in.items():
        code = str(k).split("|", 1)[0].upper()
        try:
            out[code] = float(v)
        except (TypeError, ValueError):
            continue
    if "USD" not in out:
        out["USD"] = 1.0
    return out


def to_cny(amount: float | None, currency: str | None, rates: dict[str, float]) -> float | None:
    """Convert money to CNY using HB page exchangeRates (quoted vs USD)."""
    if amount is None:
        return None
    cur = (currency or "USD").upper()
    cny_per_usd = rates.get("CNY")
    if cny_per_usd is None:
        return None
    if cur == "CNY":
        return round(amount, 2)
    if cur == "USD":
        return round(amount * cny_per_usd, 2)
    # amount in CUR → USD → CNY. rates[CUR] is CUR per 1 USD.
    per_usd = rates.get(cur)
    if not per_usd:
        return None
    usd = amount / per_usd
    return round(usd * cny_per_usd, 2)


def extract_key_expire_hint(text: str | None) -> str | None:
    if not text:
        return None
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = unescape(re.sub(r"\s+", " ", plain)).strip()
    m = re.search(
        r"(?:redeem before|Keys expire[^.]{0,40}?before)\s+"
        r"([A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?,?\s*\d{4})",
        plain,
        re.I,
    )
    if m:
        return m.group(1)
    m = re.search(
        r"Keys expire[^.]*?(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})",
        plain,
        re.I,
    )
    if m:
        return m.group(1)
    return None


def extract_bundle(url: str) -> dict[str, Any]:
    html = fetch_html(url)
    raw = parse_page_json(html)
    rates = parse_exchange_rates(raw)
    bd = raw["bundleData"]
    basic = bd.get("basic_data") or {}
    items = bd.get("tier_item_data") or {}
    tier_display = bd.get("tier_display_data") or {}
    tier_order = bd.get("tier_order") or list(tier_display.keys())
    tier_pricing = bd.get("tier_pricing_data") or {}

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

    tiers_out: list[dict[str, Any]] = []
    for tid in tier_order:
        disp = tier_display.get(tid) or {}
        pricing = tier_pricing.get(tid) or {}
        price_m = pricing.get("price|money")
        usd_amt, cur = money_amount(price_m)
        if usd_amt is None:
            continue
        cur = cur or "USD"
        cny = to_cny(usd_amt, cur, rates)
        mids = [
            m
            for m in (disp.get("tier_item_machine_names") or [])
            if m not in SKIP_ITEMS and item_name(m)
        ]
        tiers_out.append(
            {
                "id": tid,
                "header": disp.get("header"),
                "identifier": disp.get("identifier") or tid,
                "is_initial": bool(pricing.get("is_initial_tier")),
                "price_usd": usd_amt if (cur or "").upper() == "USD" else None,
                "price_amount": usd_amt,
                "price_currency": cur,
                "price_cny": cny,
                "games_count": len(mids),
                "games": [item_name(m) for m in mids],
            }
        )

    # Full unlock = highest priced tier (usually last / non-initial)
    full_tier = None
    if tiers_out:
        full_tier = max(
            tiers_out,
            key=lambda t: (t.get("price_cny") is not None, t.get("price_cny") or t.get("price_amount") or 0),
        )

    desc = basic.get("description") or basic.get("detailed_marketing_blurb") or ""
    key_expire = extract_key_expire_hint(desc)

    return {
        "source": "humblebundle",
        "product_type": "bundle",
        "source_url": url.split("?")[0],
        "name": basic.get("human_name"),
        "machine_name": bd.get("machine_name"),
        "start_time_utc": basic.get("start_time|datetime"),  # often missing on classic bundles
        "end_time_utc": basic.get("end_time|datetime"),
        "key_expire_hint": key_expire,
        "key_expire_utc": None,
        "currency_page": basic.get("currency"),
        "exchange_rate_cny_per_usd": rates.get("CNY"),
        "tiers": tiers_out,
        "full_tier_id": (full_tier or {}).get("id"),
        "full_tier_price_usd": (full_tier or {}).get("price_usd")
        or (full_tier or {}).get("price_amount"),
        "full_tier_price_cny": (full_tier or {}).get("price_cny"),
        # Default “buy price” for SteamPY compare = full unlock CNY
        "suggested_paid_cny": (full_tier or {}).get("price_cny"),
        "short_blurb": basic.get("short_marketing_blurb"),
        "games_count": len(games_ordered),
        "games": games_ordered,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract games + CNY prices from a Humble Bundle URL")
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
        # Route choice/membership to choice extractor when needed
        from load_source import is_humble_choice_url  # local import avoid cycle at module load

        if is_humble_choice_url(args.url):
            from extract_hb_choice import extract_choice

            data = extract_choice(args.url)
        else:
            data = extract_bundle(args.url)
    except Exception as e:
        print(f"Extract failed: {e}", file=sys.stderr)
        return 1

    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Name: {data.get('name')}")
    print(f"Type: {data.get('product_type')}")
    print(f"Start (UTC): {data.get('start_time_utc')}")
    print(f"End (UTC): {data.get('end_time_utc')}")
    print(f"Key expire: {data.get('key_expire_hint') or data.get('key_expire_utc')}")
    if data.get("exchange_rate_cny_per_usd"):
        print(f"HB rate CNY/USD: {data.get('exchange_rate_cny_per_usd')}")
    if data.get("suggested_paid_cny") is not None:
        print(
            f"Suggested paid (CNY): ¥{data.get('suggested_paid_cny')} "
            f"(USD {data.get('full_tier_price_usd')})"
        )
    for t in data.get("tiers") or []:
        print(
            f"  tier {t.get('id')}: "
            f"${t.get('price_usd') or t.get('price_amount')} "
            f"→ ¥{t.get('price_cny')}  ({t.get('header')})"
        )
    print(f"Games: {data.get('games_count')}")
    for i, g in enumerate(data.get("games") or [], 1):
        print(f"  {i:02d}. {g.get('hb_name') or g.get('name')}")
    print(f"Wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
