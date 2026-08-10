# -*- coding: utf-8 -*-
"""
Extract Humble Choice (monthly membership) game list + subscription CNY price.

Public pages (no login):
  https://www.humblebundle.com/membership              → current month marketing
  https://www.humblebundle.com/membership/august-2026  → specific month
  https://www.humblebundle.com/membership/home         → login wall; we resolve current month instead

Logged-in-only /membership/home is treated as “current active Choice”.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any
from urllib.parse import urlparse

from extract_hb_bundle import (
    USER_AGENT,
    money_amount,
    parse_exchange_rates,
    to_cny,
)

# Non-game extras often listed alongside Choice games
SKIP_NAME_HINTS = (
    "ign plus",
    "coupon",
    "off ",
    "% off",
    "discount",
)


def fetch_html(url: str) -> tuple[str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        final = resp.geturl()
        html = resp.read().decode("utf-8", errors="replace")
        return final, html


def parse_script_json_by_id(html: str, script_id: str) -> dict[str, Any] | None:
    m = re.search(
        rf'id="{re.escape(script_id)}"[^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    )
    if not m:
        return None
    body = m.group(1).strip()
    if not body:
        return None
    return json.loads(body)


def machine_name_to_path(machine_name: str) -> str:
    """august_2026_choice → august-2026"""
    s = machine_name.strip()
    if s.endswith("_choice"):
        s = s[: -len("_choice")]
    m = re.match(r"([a-z]+)_(\d{4})$", s, re.I)
    if m:
        return f"{m.group(1).lower()}-{m.group(2)}"
    return s.replace("_", "-")


def resolve_current_choice_meta() -> dict[str, Any]:
    """From /membership marketing blob: active month machine name + end date."""
    _, html = fetch_html("https://www.humblebundle.com/membership")
    data = parse_script_json_by_id(html, "webpack-choice-marketing-data")
    if not data:
        raise RuntimeError("Could not parse Choice marketing page (webpack-choice-marketing-data)")
    active = data.get("activeContentMachineName")
    if not active:
        raise RuntimeError("No activeContentMachineName on /membership")
    nav = data.get("navbarOptions") or {}
    return {
        "product_machine_name": active,
        "product_url_path": machine_name_to_path(str(active)),
        "name": nav.get("productHumanName") or active,
        "end_time_utc": nav.get("activeContentEndDate|datetime"),
        "base_subscription_price": data.get("baseSubscriptionPrice|money"),
        "exchange_rates_raw": data,
    }


def is_game_entry(machine_name: str, title: str) -> bool:
    mn = (machine_name or "").lower()
    t = (title or "").lower()
    if "coupon" in mn or "ignplus" in mn:
        return False
    for h in SKIP_NAME_HINTS:
        if h in t:
            return False
    return bool(title)


def extract_choice_month(url: str) -> dict[str, Any]:
    final, html = fetch_html(url)
    if "login" in urlparse(final).path.lower() and "membership" not in urlparse(final).path.lower():
        # redirected to login — caller should resolve current
        raise RuntimeError(f"Page requires login: {final}")

    data = parse_script_json_by_id(html, "webpack-monthly-product-data")
    if not data:
        raise RuntimeError(
            "No webpack-monthly-product-data on page. "
            "Use a month URL like /membership/august-2026 or /membership."
        )

    rates = parse_exchange_rates(data)
    cco = data.get("contentChoiceOptions") or {}
    ccd = cco.get("contentChoiceData") or {}
    game_data = ccd.get("game_data") or {}
    order = ccd.get("display_order") or list(game_data.keys())
    pay_early = data.get("payEarlyOptions") or {}

    games: list[dict[str, Any]] = []
    key_expires: list[str] = []
    for mid in order:
        info = game_data.get(mid) or {}
        title = info.get("title") or info.get("human_name")
        if not title:
            # try tpkd human_name
            tpkds = info.get("tpkds") or []
            if tpkds:
                title = tpkds[0].get("human_name")
        if not is_game_entry(mid, title or ""):
            continue
        expire = None
        for tp in info.get("tpkds") or []:
            exp = tp.get("expiration_date|datetime")
            if exp:
                key_expires.append(str(exp))
                if not expire:
                    expire = exp
        games.append(
            {
                "machine_name": mid,
                "hb_name": title,
                "name": title,
                "search_queries": [title],
                "key_expire_utc": expire,
                "msrp_usd": money_amount(info.get("msrp|money"))[0],
            }
        )

    # Common CDK expiry = most frequent / first game expire
    key_expire_utc = key_expires[0] if key_expires else None
    if key_expires:
        # prefer max identical; else earliest
        from collections import Counter

        common, _ = Counter(key_expires).most_common(1)[0]
        key_expire_utc = common

    sub_amt, sub_cur = money_amount(data.get("baseSubscriptionPrice|money"))
    sub_cny = to_cny(sub_amt, sub_cur or "USD", rates)

    path = cco.get("productUrlPath") or urlparse(final).path.rstrip("/").split("/")[-1]
    start = pay_early.get("activeContentStart|datetime")
    # End date not always on month page; leave None here (filled when resolved from marketing)
    name = cco.get("title")
    if name and "humble choice" not in name.lower():
        display_name = f"{name} Humble Choice"
    else:
        display_name = name or path

    return {
        "source": "humblebundle",
        "product_type": "choice",
        "source_url": final.split("?")[0],
        "name": display_name,
        "machine_name": cco.get("productMachineName"),
        "product_url_path": path,
        "start_time_utc": start,
        "end_time_utc": None,
        "key_expire_hint": None,
        "key_expire_utc": key_expire_utc,
        "currency_page": sub_cur or "USD",
        "exchange_rate_cny_per_usd": rates.get("CNY"),
        "tiers": [
            {
                "id": "subscription",
                "header": "Humble Choice subscription (month-to-month)",
                "identifier": "subscription",
                "is_initial": True,
                "price_usd": sub_amt if (sub_cur or "USD").upper() == "USD" else None,
                "price_amount": sub_amt,
                "price_currency": sub_cur or "USD",
                "price_cny": sub_cny,
                "games_count": len(games),
            }
        ],
        "full_tier_id": "subscription",
        "full_tier_price_usd": sub_amt,
        "full_tier_price_cny": sub_cny,
        "suggested_paid_cny": sub_cny,
        "short_blurb": "Humble Choice monthly",
        "games_count": len(games),
        "games": games,
        "product_is_choiceless": data.get("productIsChoiceless"),
    }


def extract_choice(url: str) -> dict[str, Any]:
    """
    Accept:
      - /membership/home (login) → current month
      - /membership → current month
      - /membership/<month-slug> → that month
    """
    path = urlparse(url).path.rstrip("/") or "/"
    parts = [p for p in path.split("/") if p]

    # /membership or /membership/home → current
    if parts == ["membership"] or parts == ["membership", "home"] or parts == ["subscription", "home"]:
        meta = resolve_current_choice_meta()
        month_url = f"https://www.humblebundle.com/membership/{meta['product_url_path']}"
        data = extract_choice_month(month_url)
        if not data.get("end_time_utc"):
            data["end_time_utc"] = meta.get("end_time_utc")
        if not data.get("name") or data["name"] == data.get("product_url_path"):
            data["name"] = meta.get("name") or data.get("name")
        data["resolved_from"] = url.split("?")[0]
        return data

    # /membership/<slug>
    if len(parts) >= 2 and parts[0] in ("membership", "subscription"):
        return extract_choice_month(url)

    # fallback try as month page
    return extract_choice_month(url)
