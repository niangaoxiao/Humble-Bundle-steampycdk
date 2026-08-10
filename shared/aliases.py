# -*- coding: utf-8 -*-
"""Common name aliases (English / Chinese) and known Steam AppIDs.

Used when searching SteamPY to reduce false matches (sequels, soundtracks, etc.).
Extend this table as you hit more games.
"""

from __future__ import annotations

# source name -> search query candidates (earlier = preferred)
KNOWN_ALIASES: dict[str, list[str]] = {
    "Biped": ["Biped", "只只大冒险"],
    "Anomaly Agent": ["Anomaly Agent", "时空叛客"],
    "Anomoly Agent": ["Anomaly Agent", "时空叛客"],  # HB typo
    "Botany Manor": ["Botany Manor", "波坦尼庄园"],
    "Old Man's Journey": ["Old Man's Journey", "老人之旅"],
    "Scanner Sombre": ["Scanner Sombre", "幽暗扫描"],
    "Astro Prospector": ["Astro Prospector", "咖啡星矿工"],
    "Knightica": ["Knightica", "斗阵骑士"],
    "NanoApostle": ["NanoApostle", "奈米使徒计划"],
    "Monster Prom 2: Monster Camp": [
        "Monster Prom 2: Monster Camp",
        "魔物学园2：怪物营地",
    ],
    "Teacup": ["Teacup"],
    "A Juggler's Tale": ["A Juggler's Tale"],
    "A Tiny Sticker Tale": ["A Tiny Sticker Tale"],
    "Fill Up The Hole": ["Fill Up The Hole"],
    "The Dark Queen of Mortholme": ["The Dark Queen of Mortholme"],
}

KNOWN_APPIDS: dict[str, int] = {
    "Biped": 1071870,
    "Anomaly Agent": 2378620,
    "Anomoly Agent": 2378620,
    "Botany Manor": 1425350,
    "Old Man's Journey": 581270,
    "Scanner Sombre": 475190,
    "Astro Prospector": 3503440,
    "Knightica": 3093400,
    "NanoApostle": 2400640,
    "Monster Prom 2: Monster Camp": 1140270,
    "Teacup": 1444300,
    "A Juggler's Tale": 1252830,
    "A Tiny Sticker Tale": 2322180,
    "Fill Up The Hole": 3343160,
    "The Dark Queen of Mortholme": 3587610,
}


def queries_for(name: str) -> list[str]:
    qs = list(KNOWN_ALIASES.get(name) or [])
    if name not in qs:
        qs.insert(0, name)
    seen: set[str] = set()
    out: list[str] = []
    for q in qs:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def appid_for(name: str) -> int | None:
    return KNOWN_APPIDS.get(name)
