# -*- coding: utf-8 -*-
"""
Compare HB / Choice purchase cost (CNY) vs SteamPY CDKey lowest listings.

Inputs:
  - Humble Bundle games URL
  - Humble Choice: /membership, /membership/home, /membership/august-2026
  - JSON / text game list

Usage:
  python scripts/summarize_prices.py "https://www.humblebundle.com/games/short-games-showcase-bundle"
  python scripts/summarize_prices.py "https://www.humblebundle.com/membership/home"
  python scripts/summarize_prices.py URL --paid 81.03   # override auto CNY
  python scripts/summarize_prices.py URL --token $STEAMPY_ACCESS_TOKEN
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

    row["matched_name"] = hit.get("gameName")
    row["matched_appId"] = hit.get("appId")
    row["gameId"] = hit.get("id")
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


def resolve_paid(bundle: dict[str, Any], paid_arg: float | None) -> tuple[float, str]:
    """Return (paid_cny, how). Prefer --paid; else HB suggested full-tier / sub CNY."""
    if paid_arg is not None:
        return float(paid_arg), "user --paid"
    suggested = bundle.get("suggested_paid_cny")
    if suggested is not None:
        kind = bundle.get("product_type") or "bundle"
        if kind == "choice":
            return float(suggested), "HB Choice subscription × page CNY rate"
        return float(suggested), "HB full-tier price × page CNY rate"
    raise SystemExit(
        "No --paid and no suggested_paid_cny from the page. "
        "Pass --paid <CNY amount>."
    )


def build_report(
    bundle: dict[str, Any],
    paid: float,
    paid_source: str,
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
                "key_expire_utc": g.get("key_expire_utc"),
            }
        )

    after_sum = round(priced_sum * (1 - fee), 2)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bundle_name": bundle.get("name"),
        "product_type": bundle.get("product_type"),
        "source": bundle.get("source"),
        "bundle_url": bundle.get("source_url"),
        "resolved_from": bundle.get("resolved_from"),
        "start_time_utc": bundle.get("start_time_utc"),
        "end_time_utc": bundle.get("end_time_utc"),
        "key_expire_hint": bundle.get("key_expire_hint"),
        "key_expire_utc": bundle.get("key_expire_utc"),
        "exchange_rate_cny_per_usd": bundle.get("exchange_rate_cny_per_usd"),
        "tiers": bundle.get("tiers"),
        "full_tier_price_usd": bundle.get("full_tier_price_usd"),
        "full_tier_price_cny": bundle.get("full_tier_price_cny"),
        "paid": paid,
        "paid_source": paid_source,
        "hb_paid": paid,
        "fee_rate": fee,
        "game_count": len(games),
        "priced_count": priced_n,
        "sum_min_price": round(priced_sum, 2),
        "sum_after_fee": after_sum,
        "delta_after_fee_minus_paid": round(after_sum - paid, 2) if priced_n else None,
        "games": lines,
        "notes": [
            "HB 买价默认用页面档位美元价 × 页面 exchangeRates.CNY（与站内人民币展示一致）。",
            "可用 --paid 覆盖为你的真实付款。",
            f"扣费公式: 在售最低合计 × (1 - {fee})。",
            "在售最低 = SteamPY 卖家挂单 listSale.keyPrice 最低值。",
            "无 STEAMPY_ACCESS_TOKEN 时价格为空。",
        ],
    }
    return report


def fmt_time(v: Any) -> str:
    if not v:
        return "-"
    return str(v)


def to_markdown(report: dict[str, Any]) -> str:
    paid = report.get("paid") if report.get("paid") is not None else report.get("hb_paid")
    rate = report.get("exchange_rate_cny_per_usd")
    rate_s = f"{rate:.6f}" if isinstance(rate, float) else (str(rate) if rate else "-")
    lines = [
        f"# {report.get('bundle_name') or 'Game list'} · SteamPY 在售最低",
        "",
        f"- 生成时间 (UTC): {report.get('generated_at')}",
        f"- 类型: {report.get('product_type') or '-'}",
        f"- 来源: {report.get('bundle_url') or report.get('source') or '-'}",
    ]
    if report.get("resolved_from"):
        lines.append(f"- 由链接解析: {report.get('resolved_from')}")
    lines += [
        f"- **发售/上架 (UTC)**: {fmt_time(report.get('start_time_utc'))}",
        f"- **结束 (UTC)**: {fmt_time(report.get('end_time_utc'))}",
        f"- **CDK 过期**: {fmt_time(report.get('key_expire_utc') or report.get('key_expire_hint'))}",
        f"- HB 汇率 CNY/USD: {rate_s}",
        f"- 规则: 在售最低 = 卖家 CDkey 挂单最低价",
        f"- **HB 买价 (CNY)**: **¥{paid}** （{report.get('paid_source') or '-'}）",
    ]
    if report.get("full_tier_price_usd") is not None:
        lines.append(
            f"- 页面全档/订阅: "
            f"USD {report.get('full_tier_price_usd')} → ¥{report.get('full_tier_price_cny')}"
        )
    lines += [
        f"- 游戏数: {report.get('game_count')}（有价 {report.get('priced_count')}）",
        "",
    ]

    tiers = report.get("tiers") or []
    if tiers:
        lines += [
            "## HB 档位价格（页面汇率）",
            "",
            "| 档位 | 标价 | 人民币 | 说明 |",
            "|------|------|--------|------|",
        ]
        for t in tiers:
            usd = t.get("price_usd")
            if usd is None:
                usd = t.get("price_amount")
            cur = t.get("price_currency") or "USD"
            cny = t.get("price_cny")
            lines.append(
                f"| {t.get('id')} | {cur} {usd} | ¥{cny} | "
                f"{(t.get('header') or '').replace('|', '/')} |"
            )
        lines.append("")

    lines += [
        "## 合计",
        "",
        "| 项目 | 金额 |",
        "|------|------|",
        f"| **HB 买价** | **¥{paid}** |",
        f"| **SteamPY 在售最低合计** | **¥{report.get('sum_min_price')}** |",
        f"| **扣 {float(report.get('fee_rate') or 0)*100:.0f}% 后** | **¥{report.get('sum_after_fee')}** |",
    ]
    delta = report.get("delta_after_fee_minus_paid")
    if delta is not None:
        sign = "+" if delta >= 0 else ""
        lines.append(f"| 扣费后 − HB 买价 | **{sign}¥{delta}** |")
    lines += [
        "",
        "## 明细",
        "",
        "| # | 游戏 | 匹配 | AppID | 在售最低 | CDK过期 |",
        "|---|------|------|-------|----------|--------|",
    ]
    for i, g in enumerate(report.get("games") or [], 1):
        mp = g.get("min_price")
        exp = g.get("key_expire_utc") or report.get("key_expire_utc") or report.get("key_expire_hint") or "-"
        if isinstance(exp, str) and "T" in exp:
            exp = exp.split("T")[0]
        lines.append(
            "| {i} | {name} | {m} | {app} | {mp} | {exp} |".format(
                i=i,
                name=(g.get("name") or g.get("hb_name") or "").replace("|", "/"),
                m=(g.get("matched_name") or "-").replace("|", "/"),
                app=g.get("matched_appId") or g.get("steam_appid") or "-",
                mp=f"¥{mp}" if mp is not None else "-",
                exp=str(exp).replace("|", "/"),
            )
        )
    lines += ["", "## 备注", ""]
    for n in report.get("notes") or []:
        lines.append(f"- {n}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="HB/Choice vs SteamPY lowest CDKey prices (CNY)"
    )
    ap.add_argument(
        "source",
        help="HB games URL, Choice/membership URL, or .json/.txt list",
    )
    ap.add_argument(
        "--paid",
        "--hb-paid",
        dest="paid",
        type=float,
        default=None,
        help="你实际付款（人民币）。默认用页面全档/月费 × HB 汇率转 CNY",
    )
    ap.add_argument("--fee", type=float, default=0.03, help="手续费比例，默认 0.03")
    ap.add_argument(
        "--token",
        default=os.environ.get("STEAMPY_ACCESS_TOKEN", ""),
        help="SteamPY accessToken；或环境变量 STEAMPY_ACCESS_TOKEN",
    )
    ap.add_argument("--title", default=None, help="覆盖列表标题")
    ap.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=ROOT / "output",
        help="报告输出目录",
    )
    ap.add_argument(
        "--save-bundle",
        type=Path,
        default=None,
        help="同时写出规范化游戏列表 JSON",
    )
    args = ap.parse_args()

    try:
        bundle = load_source(args.source, title=args.title)
    except Exception as e:
        print(f"Failed to load source: {e}", file=sys.stderr)
        return 1

    paid, paid_source = resolve_paid(bundle, args.paid)

    if args.save_bundle:
        args.save_bundle.parent.mkdir(parents=True, exist_ok=True)
        args.save_bundle.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Saved game list: {args.save_bundle}")

    report = build_report(
        bundle,
        paid=paid,
        paid_source=paid_source,
        fee=args.fee,
        token=args.token or "",
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
            "\nHint: no token → empty SteamPY prices. "
            "Set STEAMPY_ACCESS_TOKEN after logging into steampy.com.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
