# -*- coding: utf-8 -*-
"""
Load a game list from several input types.

Supported:
  1. Humble Bundle classic URL   → auto-parse games + CNY tier prices
  2. Humble Choice / membership  → /membership, /membership/home, /membership/august-2026
  3. Bundle / list JSON
  4. Plain text file (one game name per line)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from extract_hb_bundle import extract_bundle
from extract_hb_choice import extract_choice


def is_url(s: str) -> bool:
    try:
        p = urlparse(s)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def is_humble_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("humblebundle.com")


def is_humble_choice_url(url: str) -> bool:
    if not is_humble_url(url):
        return False
    path = (urlparse(url).path or "").lower()
    return (
        path.startswith("/membership")
        or path.startswith("/subscription")
        or "/choice" in path
    )


def games_from_names(
    names: list[str],
    *,
    title: str | None = None,
    source: str = "manual",
    source_url: str | None = None,
) -> dict[str, Any]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for n in names:
        n = (n or "").strip()
        if not n or n.startswith("#"):
            continue
        if n not in seen:
            seen.add(n)
            cleaned.append(n)
    games = [{"hb_name": n, "name": n, "search_queries": [n]} for n in cleaned]
    return {
        "source": source,
        "product_type": "manual",
        "source_url": source_url,
        "name": title or "Game list",
        "games_count": len(games),
        "games": games,
        "suggested_paid_cny": None,
    }


def load_text_file(path: Path, *, title: str | None = None) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    names = [ln.strip() for ln in text.splitlines()]
    return games_from_names(
        names,
        title=title or path.stem,
        source="text",
        source_url=str(path.resolve()),
    )


def _normalize_bundle_dict(data: dict[str, Any], source_hint: str | None = None) -> dict[str, Any]:
    if "games" in data and isinstance(data["games"], list):
        games: list[dict[str, Any]] = []
        for g in data["games"]:
            if isinstance(g, str):
                games.append({"hb_name": g, "name": g, "search_queries": [g]})
            elif isinstance(g, dict):
                name = g.get("hb_name") or g.get("name") or g.get("title") or ""
                if not name:
                    continue
                row = dict(g)
                row.setdefault("hb_name", name)
                row.setdefault("name", name)
                games.append(row)
            else:
                continue
        out = dict(data)
        out["games"] = games
        out["games_count"] = len(games)
        out.setdefault("source", source_hint or "json")
        out.setdefault("name", out.get("name") or "Game list")
        return out

    for key in ("names", "games", "titles"):
        if (
            key in data
            and isinstance(data[key], list)
            and data[key]
            and isinstance(data[key][0], str)
        ):
            return games_from_names(
                list(data[key]),
                title=data.get("name") or data.get("title"),
                source=source_hint or "json",
                source_url=data.get("source_url"),
            )

    raise ValueError(
        "JSON must contain games[] (objects or strings) or names[] string list."
    )


def load_json_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        if isinstance(data, list):
            return games_from_names(
                [str(x) for x in data],
                title=path.stem,
                source="json",
                source_url=str(path.resolve()),
            )
        raise ValueError("JSON root must be an object or a string array")
    out = _normalize_bundle_dict(data, source_hint="json")
    if not out.get("source_url"):
        out["source_url"] = str(path.resolve())
    return out


def load_source(
    source: str,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    s = source.strip()
    if is_url(s):
        if not is_humble_url(s):
            raise ValueError(
                f"Auto-parse only supports Humble Bundle URLs right now.\n"
                f"  Got: {s}\n"
                f"  Workaround: put game names in a .txt (one per line) or JSON."
            )
        if is_humble_choice_url(s):
            data = extract_choice(s)
        else:
            data = extract_bundle(s)
        if title:
            data["name"] = title
        return data

    path = Path(s)
    if not path.exists():
        raise FileNotFoundError(f"Not a URL and file not found: {s}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        data = load_json_file(path)
        if title:
            data["name"] = title
        return data
    if suffix in (".txt", ".md", ".list", ".csv"):
        if suffix == ".csv":
            names: list[str] = []
            for ln in path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                names.append(re.split(r"[,;\t]", ln, maxsplit=1)[0].strip().strip('"'))
            return games_from_names(
                names,
                title=title or path.stem,
                source="csv",
                source_url=str(path.resolve()),
            )
        return load_text_file(path, title=title)

    try:
        return load_json_file(path)
    except json.JSONDecodeError:
        return load_text_file(path, title=title)
