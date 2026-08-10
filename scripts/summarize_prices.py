# -*- coding: utf-8 -*-
"""
Compare a purchase cost vs SteamPY CDKey lowest listing prices.

Inputs (first positional argument):
  - Humble Bundle URL          (auto-extract games)
  - JSON from extract / manual
  - Text file: one game name per line

Usage:
  python scripts/summarize_prices.py "https://www.humblebundle.com/games/xxx" --paid 86
  python scripts/summarize_prices.py examples/short_games_showcase_bundle.json --paid 86
  python scripts/summarize_prices.py examples/games_list.example.txt --paid 100 --title "My list"
  python scripts/summarize_prices.py games.json --paid 50 --token "$STEAMPY_ACCESS_TOKEN"

Token:
  Login at https://steampy.com , open DevTools → Application → Local Storage → accessToken
  Then:  set STEAMPY_ACCESS_TOKEN=...   (do NOT commit the token)

Without token: still writes a report shell; price columns stay empty.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))

from aliases import appid_for, queries_for  # noqa: E402
from load_source import load_source  # noqa: E402

API_BASE = "https://steampy.com/xboot"


def api_get(path: str, params: dict[str, Any], token: str) -> dict[str, Any]:
    qs = urllib.parse.urlencode(params)
    url = f"{API_BASE}{path}?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://steampy.com/",
            "Origin": "https://steampy.com",
            "accessToken": token or "",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def score_candidate(item: dict[str, Any], hb_name: str, appid: int | None) -> int:
    """Name / AppID scoring to avoid Biped → Bipedal Chickens style mismatches."""
    name = (item.get("gameName") or "").strip()
    cn = (item.get("gameNameCn") or "").strip()
    aid = str(item.get("appId") or "")
    hb = hb_name.strip()
    sc = 0
    if name.lower() == hb.lower():
        sc += 100
    if cn and cn == hb:
        sc += 90
    if aid and appid and aid == str(appid):
        sc += 40
    if hb.lower() in name.lower() and name.lower() != hb.lower():
        sc += 10
        sc -= max(0, len(name) - len(hb))
    if name.lower().startswith(hb.lower() + " "):
        sc -= 30
    if "2" in name and "2" not in hb:
        sc -= 20
    if item.get("keyPrice") is None:
        sc -= 5
    return sc


def pick_from_content(
    content: list[dict[str, Any]], hb_name: str, appid: int | None
) -> dict[str, Any] | None:
    if not content:
        return None
    ranked = sorted(
        content, key=lambda c: score_candidate(c, hb_name, appid), reverse=True
    )
    best = ranked[0]
    if score_candidate(best, hb_name, appid) < 30:
        return None
    return best


def fetch_price_for_game(
    name: str, token: str, appid: int | None = None
) -> dict[str, Any]:
    """CDKey market: keyByName → listSale min keyPrice (actual listing low)."""
    row: dict[str, Any] = {
        "query": name,
        "min_price": None,
        "status": "unknown",
        "raw_message": None,
    }
    if not token:
        row["status"] = "no_token"
        return row

    try:
        data = api_get(
            "/steamGame/keyByName",
            {
                "pageNumber": 1,
                "pageSize": 30,
                "sort": "keyTx",
                "order": "asc",
                "startDate": "",
                "endDate": "",
                "gameName": name,
                "gameUrl": "",
            },
            token,
        )
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        row["status"] = f"http_{e.code}"
        row["raw_message"] = body[:200]
        return row
    except Exception as e:
        row["status"] = "error"
        row["raw_message"] = str(e)
        return row

    if not data.get("success"):
        msg = data.get("message") or ""
        row["raw_message"] = msg
        if data.get("code") == 401 or "登录" in msg:
            row["status"] = "need_login"
        else:
            row["status"] = "api_fail"
        return row

    res = data.get("result") or {}
    content = res.get("content") if isinstance(res, dict) else res
    if not isinstance(content, list) or not content:
        row["status"] = "no_match"
        return row

    hit = pick_from_content(content, name, appid)
    if not hit:
        row["status"] = "no_match"
        row["raw_message"] = json.dumps(
            [
                (c.get("appId"), c.get("gameName"), c.get("keyTxAmt"), c.get("keyPrice"))
                for c in content[:6]
            ],
            ensure_ascii=False,
        )
        return row

    # Listing low ≠ summary keyPrice field (that one can be wrong / stale)
    row["matched_name"] = hit.get("gameName")
    row["matched_appId"] = hit.get("appId")
    row["gameId"] = hit.get("id")
    row["api"] = "/steamKeySale/listSale"
    row["oriPrice"] = hit.get("oriPrice")
    try:
        d2 = api_get(
            "/steamKeySale/listSale",
            {
                "pageNumber": 1,
                "pageSize": 20,
                "sort": "keyPrice",
                "order": "asc",
                "startDate": "",
                "endDate": "",
                "gameId": hit.get("id"),
            },
            token,
        )
        sales = (d2.get("result") or {}).get("content") or []
        prices = [float(s["keyPrice"]) for s in sales if s.get("keyPrice") is not None]
        if not prices:
            row["status"] = "no_listing"
            return row
        row["min_price"] = min(prices)
        row["status"] = "ok"
        return row
    except Exception as e:
        row["status"] = "list_sale_error"
        row["raw_message"] = str(e)
        return row


def build_report(
    bundle: dict[str, Any],
    paid: float,
    fee: float,
    token: str,
) -> dict[str, Any]:
    games = bundle.get("games") or []
    lines: list[dict[str, Any]] = []
    priced_sum = 0.0
    priced_n = 0

    for g in games:
        name = g.get("hb_name") or g.get("name") or ""
        qs = queries_for(name)
        appid = appid_for(name)
        price_info: dict[str, Any] = {"status": "skipped", "min_price": None}
        used_q = qs[0] if qs else name
        if token:
            for q in qs:
                price_info = fetch_price_for_game(q, token, appid=appid)
                used_q = q
                if price_info.get("status") in ("ok", "no_listing"):
                    break
                if price_info.get("status") == "need_login":
                    break
        else:
            price_info = {"status": "no_token", "min_price": None, "query": used_q}

        min_p = price_info.get("min_price")
        after = round(min_p * (1 - fee), 2) if isinstance(min_p, (int, float)) else None
        if after is not None:
            priced_sum += float(min_p)
            priced_n += 1

        lines.append(
            {
                "name": name,
                "hb_name": name,
                "steam_appid": appid,
                "matched_name": price_info.get("matched_name"),
                "matched_appId": price_info.get("matched_appId"),
                "search_query": used_q,
                "min_price": min_p,
                "after_fee": after,
                "status": price_info.get("status"),
                "detail": price_info.get("raw_message"),
            }
        )

    after_sum = round(priced_sum * (1 - fee), 2)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bundle_name": bundle.get("name"),
        "source": bundle.get("source"),
        "bundle_url": bundle.get("source_url"),
        "paid": paid,
        "hb_paid": paid,  # backward-compatible key
        "fee_rate": fee,
        "game_count": len(games),
        "priced_count": priced_n,
        "sum_min_price": round(priced_sum, 2),
        "sum_after_fee": after_sum,
        "delta_after_fee_minus_paid": round(after_sum - paid, 2) if priced_n else None,
        "games": lines,
        "notes": [
            "Paid amount is user input, not scraped from the store page.",
            f"After-fee formula: sum(min listing) × (1 - {fee}).",
            "Without STEAMPY_ACCESS_TOKEN, prices stay empty.",
            "Min price = lowest seller CDKey listing (listSale.keyPrice), not summary cards.",
        ],
    }
    return report


def to_markdown(report: dict[str, Any]) -> str:
    paid = report.get("paid") if report.get("paid") is not None else report.get("hb_paid")
    lines = [
        f"# {report.get('bundle_name') or 'Game list'} · SteamPY lowest listings",
        "",
        f"- Generated (UTC): {report.get('generated_at')}",
        f"- Source: {report.get('bundle_url') or report.get('source') or '-'}",
        f"- Rule: **lowest = min seller CDKey unit price** (listing table)",
        f"- **You paid**: ¥{paid}",
        f"- Games: {report.get('game_count')} (priced {report.get('priced_count')})",
        "",
        "## Totals",
        "",
        "| Item | Amount |",
        "|------|--------|",
        f"| **Sum of lowest listings** | **¥{report.get('sum_min_price')}** |",
        f"| **After {float(report.get('fee_rate') or 0)*100:.0f}% fee** | **¥{report.get('sum_after_fee')}** |",
    ]
    delta = report.get("delta_after_fee_minus_paid")
    if delta is None:
        delta = report.get("delta_after_fee_minus_hb")
    if delta is not None:
        sign = "+" if delta >= 0 else ""
        lines.append(f"| After fee − paid | **{sign}¥{delta}** |")
    lines += [
        "",
        "## Detail (per-game fee not listed)",
        "",
        "| # | Game | Matched | AppID | Lowest |",
        "|---|------|---------|-------|--------|",
    ]
    for i, g in enumerate(report.get("games") or [], 1):
        mp = g.get("min_price")
        lines.append(
            "| {i} | {name} | {m} | {app} | {mp} |".format(
                i=i,
                name=(g.get("name") or g.get("hb_name") or "").replace("|", "/"),
                m=(g.get("matched_name") or "-").replace("|", "/"),
                app=g.get("matched_appId") or g.get("steam_appid") or "-",
                mp=f"¥{mp}" if mp is not None else "-",
            )
        )
    lines += ["", "## Notes", ""]
    for n in report.get("notes") or []:
        lines.append(f"- {n}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="SteamPY lowest CDKey prices for a HB URL, JSON, or name list"
    )
    ap.add_argument(
        "source",
        help="Humble Bundle URL, or path to .json / .txt game list",
    )
    ap.add_argument(
        "--paid",
        "--hb-paid",
        dest="paid",
        type=float,
        required=True,
        help="What you actually paid (CNY). Not scraped from the page.",
    )
    ap.add_argument("--fee", type=float, default=0.03, help="Fee rate, default 0.03")
    ap.add_argument(
        "--token",
        default=os.environ.get("STEAMPY_ACCESS_TOKEN", ""),
        help="SteamPY accessToken; or env STEAMPY_ACCESS_TOKEN",
    )
    ap.add_argument("--title", default=None, help="Override list title")
    ap.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=ROOT / "output",
        help="Report output directory (default: ./output)",
    )
    ap.add_argument(
        "--save-bundle",
        type=Path,
        default=None,
        help="Also write normalized game list JSON here",
    )
    args = ap.parse_args()

    try:
        bundle = load_source(args.source, title=args.title)
    except Exception as e:
        print(f"Failed to load source: {e}", file=sys.stderr)
        return 1

    if args.save_bundle:
        args.save_bundle.parent.mkdir(parents=True, exist_ok=True)
        args.save_bundle.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Saved game list: {args.save_bundle}")

    report = build_report(
        bundle, paid=args.paid, fee=args.fee, token=args.token or ""
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in (bundle.get("name") or "list")
    )[:40]
    json_path = args.out_dir / f"report_{safe}_{stamp}.json"
    md_path = args.out_dir / f"report_{safe}_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = to_markdown(report)
    md_path.write_text(md, encoding="utf-8")

    print(md)
    print(f"\nWrote:\n  {json_path}\n  {md_path}")
    if not args.token:
        print(
            "\nHint: no token → empty prices. Login at steampy.com, copy localStorage "
            "accessToken, set STEAMPY_ACCESS_TOKEN, re-run.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
