# hb-steampy

把 **Humble Bundle / Humble Choice** 的游戏列表拉下来，对照 **SteamPY CDKey 在售最低价**，用人民币算是否划算。

- **不需要 AI**，纯 Python  
- HB **买价**默认用页面美元档位 × 页面自带 `exchangeRates.CNY`（与站内人民币展示一致，例如 $12 → 约 ¥81）  
- 报告带 **发售/上架时间、结束时间、CDK 过期**

> 与 Humble Bundle / SteamPY 均无官方关系。请遵守网站条款，控制请求频率。

---

## 支持的输入

| 输入 | 自动识别游戏 | 说明 |
|------|--------------|------|
| **HB 捆绑包** `/games/...` | ✅ | 档位价 + 汇率转 CNY + Key 过期文案 |
| **月订 Choice** `/membership`、`/membership/home`、`/membership/august-2026` | ✅ | `/home` 需登录时会改解析当月公开页 |
| JSON / 文本游戏列表 | 你提供名字 | 任意来源备用 |

```bash
# 普通捆绑（默认买价 = 全档 CNY，无需手算汇率）
python scripts/summarize_prices.py "https://www.humblebundle.com/games/short-games-showcase-bundle"

# 月订：测试链接 /membership/home 会解析为当月 Choice
python scripts/summarize_prices.py "https://www.humblebundle.com/membership/home"

# 指定月份
python scripts/summarize_prices.py "https://www.humblebundle.com/membership/august-2026"

# 覆盖为你的真实付款
python scripts/summarize_prices.py "HB链接" --paid 81.03
```

---

## 快速开始

```bash
cd hb-steampy
# 核心路径仅用标准库，无需 pip
```

### SteamPY token（查价需要）

1. 登录 [steampy.com](https://steampy.com)  
2. DevTools → Application → Local Storage → `accessToken`  
3. 当前终端：

```powershell
$env:STEAMPY_ACCESS_TOKEN = "粘贴token"
python scripts/summarize_prices.py "https://www.humblebundle.com/games/short-games-showcase-bundle"
```

只解析不查价：

```bash
python scripts/extract_hb_bundle.py "https://www.humblebundle.com/games/xxx" -o examples/out.json
python scripts/extract_hb_bundle.py "https://www.humblebundle.com/membership/home" -o examples/choice.json
```

报告输出到 `output/report_*.md` / `.json`（已 gitignore）。

### 计算公式

```text
HB 买价(CNY) = 全档美元价 × 页面 exchangeRates.CNY
               （Choice = 月费 $14.99 × 同汇率；可用 --paid 覆盖）
SteamPY 合计 = Σ 每款在售最低挂单
扣费后       = 合计 × (1 - fee)     # 默认 fee=0.03
差额         = 扣费后 − HB 买价
```

---

## 报告里会写什么

- 发售/上架时间（Choice 月包有；经典捆绑页经常没有 start）  
- 结束时间  
- CDK 过期（捆绑从文案解析；Choice 从 key 的 `expiration_date`）  
- 各档位 USD → CNY  
- 与 SteamPY 最低价对比  

---

## 目录

```text
hb-steampy/
  scripts/
    extract_hb_bundle.py   # 解析 CLI（捆绑 + 月订）
    summarize_prices.py    # 主流程
    add_favorites.py       # 实验性收藏
  shared/
    extract_hb_bundle.py   # 经典捆绑
    extract_hb_choice.py   # Humble Choice
    load_source.py
    aliases.py
  examples/
  docs/LESSONS.md
  output/
```

---

## 安全说明

请勿提交：

- `STEAMPY_ACCESS_TOKEN` 等访问令牌；
- 浏览器配置目录（可能包含 Cookie 或登录状态）；
- `output/` 下的个人报告。

---

## 限制

- 自动解析仅 **Humble Bundle / Choice**  
- 名称匹配靠规则 + 别名表，可能误匹配  
- 页面改版会导致解析失效  
- SteamPY 非官方接口，可能 401 / 变更  

---

## License

MIT — see [LICENSE](LICENSE).
