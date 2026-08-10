# hb-steampy

Compare **what you paid** for a game list against **SteamPY CDKey lowest seller listings**.

Typical use: paste a **Humble Bundle** link → pull game names → query SteamPY → markdown/JSON report (sum, optional fee, delta vs paid).

No AI required. Pure Python + your own SteamPY login token.

> Not affiliated with Humble Bundle or SteamPY. Personal research tool; respect site ToS and rate limits.

---

## What inputs work?

| Input | Auto game detect? | How |
|--------|-------------------|-----|
| **Humble Bundle URL** | Yes | Parses embedded page JSON |
| **JSON game list** | You provide names | From extract or hand-written |
| **Text file** (one name / line) | You provide names | Fanatical / wishlist / any source |
| Arbitrary store URL (Fanatical, Steam, …) | **No** | Export names to `.txt` / `.json` first |

**Pricing never depends on HB.** Once you have names, SteamPY lookup is the same.

```
                    ┌─ HB URL ──────────────► auto extract ─┐
Any source ─────────┼─ games.txt / .json ───► name list ────┼─► SteamPY prices ─► report
                    └─ (other sites) ───────► manual list ──┘
```

---

## Quick start

```bash
git clone https://github.com/<you>/hb-steampy.git
cd hb-steampy

# optional venv
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate

# core path needs no pip packages
# favorites helper only:
#   pip install -r requirements.txt && python -m playwright install chromium
```

### 1) Get a SteamPY token (required for live prices)

1. Log in at [steampy.com](https://steampy.com)  
2. DevTools → Application → Local Storage → copy `accessToken`  
3. Export for this shell only (never commit):

```powershell
# Windows PowerShell
$env:STEAMPY_ACCESS_TOKEN = "paste_here"
```

```bash
# bash
export STEAMPY_ACCESS_TOKEN=paste_here
```

### 2) Run

```bash
# A) One shot: Humble Bundle URL + what you paid (CNY)
python scripts/summarize_prices.py "https://www.humblebundle.com/games/short-games-showcase-bundle" --paid 86

# B) Offline example JSON (no network for extract)
python scripts/summarize_prices.py examples/short_games_showcase_bundle.json --paid 86

# C) Any games — not from HB
python scripts/summarize_prices.py examples/games_list.example.txt --paid 100 --title "My picks"

# Extract only
python scripts/extract_hb_bundle.py "https://www.humblebundle.com/games/xxx" -o examples/my_bundle.json
```

Reports go to `output/report_*.md` and `output/report_*.json` (gitignored).

Formula (default):

```text
sum_min      = Σ lowest CDKey listing per game
after_fee    = sum_min × (1 - fee)     # default fee=0.03
delta        = after_fee - paid
```

Override fee: `--fee 0.03`.

---

## Project layout

```text
hb-steampy/
  scripts/
    extract_hb_bundle.py   # HB URL → JSON
    summarize_prices.py    # main CLI (URL / JSON / txt)
    add_favorites.py       # experimental browser helper
  shared/
    extract_hb_bundle.py
    load_source.py         # unified loader
    aliases.py             # CN/EN aliases + AppIDs
  examples/                # public sample data only
  docs/LESSONS.md          # field notes (price fields, pitfalls)
  output/                  # local reports (ignored)
```

---

## Manual JSON schema (minimal)

```json
{
  "name": "My bundle",
  "games": [
    { "name": "Botany Manor" },
    { "name": "Biped" }
  ]
}
```

Or a plain string array: `["Hades", "Celeste"]`.

---

## Privacy & safety

- **Do not commit** `STEAMPY_ACCESS_TOKEN`, browser profiles, or personal `output/` reports.  
- `.gitignore` already excludes reports, xlsx, tokens, profiles.  
- This repo ships **no** third-party posting automation (no 小黑盒).  
- Unofficial use of SteamPY HTTP APIs may break or violate their terms — use at your own risk, keep request volume low.

---

## Limitations

- Auto-parse: **Humble Bundle product pages only**.  
- Name matching is heuristic; extend `shared/aliases.py` when wrong titles match.  
- No stock / region / key-type guarantees; listings change every minute.  
- Favorites script is incomplete (UI may have no stable favorite control).

---

## License

MIT — see [LICENSE](LICENSE).
