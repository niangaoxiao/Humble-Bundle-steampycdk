# -*- coding: utf-8 -*-
"""
Experimental: open SteamPY in a browser and try to favorite games.

Status: selectors are placeholders — CDKey market may not expose a clear
「收藏」button. Prefer manual favorites; use this only as a starting point.

Requires: pip install playwright && python -m playwright install chromium

Usage:
  python scripts/add_favorites.py examples/short_games_showcase_bundle.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))

from aliases import queries_for  # noqa: E402
from load_source import load_source  # noqa: E402


def default_profile() -> str:
    return os.path.join(
        os.environ.get("TEMP", os.environ.get("TMP", ".")), "steampy_pw_profile"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="SteamPY bulk favorite (experimental)")
    ap.add_argument("source", help="HB URL / JSON / text game list")
    ap.add_argument("--profile", default=default_profile())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()

    try:
        bundle = load_source(args.source)
    except Exception as e:
        print(f"Failed to load source: {e}", file=sys.stderr)
        return 1

    games = bundle.get("games") or []
    print(f"List: {bundle.get('name')} | {len(games)} games")
    for i, g in enumerate(games, 1):
        name = g.get("hb_name") or g.get("name") or ""
        print(f"  {i:02d}. {name}  queries: {queries_for(name)}")

    if args.dry_run:
        print("dry-run done. Re-run without --dry-run to open a browser.")
        return 0

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Install: pip install playwright && python -m playwright install chromium",
            file=sys.stderr,
        )
        return 1

    SEL = {
        "search_input": 'input[type="text"], input[placeholder*="搜索"], input[placeholder*="游戏"]',
        "first_result": "a[href*='game'], .game-item, .ivu-list-item",
        "favorite_btn": 'button:has-text("收藏"), text=收藏, text=已收藏',
    }

    results: list[dict[str, Any]] = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=args.profile,
            channel="chrome",
            headless=False,
            locale="zh-CN",
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
            no_viewport=True,
            ignore_default_args=["--enable-automation"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://steampy.com/", wait_until="domcontentloaded", timeout=90000)
        print("Log in to SteamPY in the opened window if needed. Waiting 60s…")
        time.sleep(60)

        for i, g in enumerate(games, 1):
            name = g.get("hb_name") or g.get("name") or ""
            q = queries_for(name)[0]
            print(f"=== [{i}/{len(games)}] {name} ({q}) ===")
            row: dict[str, Any] = {"name": name, "query": q, "status": "todo"}
            try:
                page.goto(
                    "https://steampy.com/", wait_until="domcontentloaded", timeout=60000
                )
                time.sleep(1)
                inp = page.locator(SEL["search_input"]).first
                if inp.count() == 0:
                    row["status"] = "no_search_input"
                    results.append(row)
                    continue
                inp.click(force=True)
                inp.fill("")
                inp.type(q, delay=30)
                page.keyboard.press("Enter")
                time.sleep(2)
                res = page.locator(SEL["first_result"]).first
                if res.count():
                    res.click(force=True, timeout=5000)
                    time.sleep(2)
                else:
                    row["status"] = "no_result"
                    results.append(row)
                    continue
                fav = page.locator(SEL["favorite_btn"]).first
                if fav.count() == 0:
                    row["status"] = "no_favorite_button"
                    out_dir = ROOT / "output"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(out_dir / f"debug_fav_{i}.png"))
                else:
                    txt = fav.inner_text(timeout=2000)
                    if "已收藏" in txt:
                        row["status"] = "already"
                    else:
                        fav.click(force=True)
                        time.sleep(1)
                        row["status"] = "clicked"
                print(" ", row["status"])
            except Exception as e:
                row["status"] = "error"
                row["error"] = str(e)
                print("  error", e)
            results.append(row)
            time.sleep(args.delay)

        out = ROOT / "output" / "favorites_result.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Results: {out}")
        print("Browser stays open for manual check. Ctrl+C to exit.")
        try:
            while True:
                time.sleep(120)
                page.title()
        except KeyboardInterrupt:
            pass
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
