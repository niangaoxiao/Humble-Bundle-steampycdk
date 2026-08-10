# Notes from reverse-engineering SteamPY pricing

Public technical notes only. No accounts, tokens, or personal purchase history.

## SteamPY

- Site: https://steampy.com  
- API prefix: `/xboot`  
- Authenticated calls need header `accessToken` (from browser `localStorage` after login).  
- Unauthenticated search typically returns `401` / 「您还未登录」.

### Correct price chain (CDKey market)

1. Search by full name (same as page 「游戏全称搜索」):  
   `GET /xboot/steamGame/keyByName?...&gameName=...`  
2. Load listings sorted by price:  
   `GET /xboot/steamKeySale/listSale?...&sort=keyPrice&order=asc&gameId={id}`  

### Field meanings (do not mix)

| UI | Example | Field | Notes |
|----|---------|-------|--------|
| Platform low on card | ￥13.88 | `keyTxAmt` | Card big number |
| Steam / list original | ￥118 | `oriPrice` | Strike-through |
| **Seller listing low** | ￥13.79 | `listSale[].keyPrice` min | **Use this as “在售最低”** |
| Do not use for low | ￥11 | summary `keyPrice` | Can disagree with listing table |

## Humble Bundle extract

- Games come from embedded page JSON (`userOptions` / `bundleData`), not from the visual DOM alone.  
- HB HTML changes will break `extract_hb_bundle.py`.  
- **Tier prices** live in `tier_pricing_data.*.price|money` (usually USD).  
- **CNY display** uses top-level `exchangeRates["CNY|decimal"]` (CNY per 1 USD).  
  Example: full tier $12 × 6.75… ≈ **¥81** (matches on-site RMB), not a fixed 7.2 guess.  
- Classic bundles often **omit** `start_time`; `end_time|datetime` is reliable.  
- CDK expire text is usually in `description` (“Keys expire… redeem before …”).  
- User can still override with `--paid` if they paid a custom PWYW amount.

## Humble Choice (monthly)

- `/membership/home` redirects to **login** when logged out.  
- Public marketing: `/membership` → `webpack-choice-marketing-data`  
  (`activeContentMachineName`, `navbarOptions.activeContentEndDate|datetime`).  
- Month page: `/membership/august-2026` → `webpack-monthly-product-data`  
  - Games: `contentChoiceOptions.contentChoiceData.game_data` + `display_order`  
  - Start: `payEarlyOptions.activeContentStart|datetime`  
  - Per-key expire: `tpkds[].expiration_date|datetime`  
  - Sub price: `baseSubscriptionPrice|money` × same CNY rate  
- Skip non-games (e.g. `ignplus_choicecoupon_*`).
## Matching

- Prefer exact English name; keep a small alias / AppID table for CN titles and HB typos (`Anomoly Agent`).  
- Reject weak scores to avoid sequels / chicken-named clones.

## Favorites automation

- No reliable public 「收藏」 control found on the CDKey list UI during exploration.  
- `add_favorites.py` is experimental; selectors need maintenance if the site changes.

## Fee

- Default after-fee = sum × 0.97 (`--fee 0.03`). Override if platform rates change.
