# B9 新闻数据 API — 下游接入文档

> 最后更新：2026-07-27 ｜ 状态：**已上线，公网可用**（全部端点实测 200）

---

## 一、基本信息

| 项 | 值 |
|---|---|
| Base URL（HTTPS，推荐分享用） | `https://final-terms-beatles-waiting.trycloudflare.com` |
| Base URL（HTTP 直连，稳定不变） | `http://127.0.0.1:8080`（临时：Mac 本地，原 GCP VM 已宕机） |
| 协议 | HTTPS 走 Cloudflare Tunnel（证书有效，任何人可直接打开）；HTTP 为 VM 直连 |
| 鉴权 | HTTP Header：`Authorization: Bearer <你的 token>`；也支持 `?token=<你的 token>` 查询参数，见下方「鉴权」 |
| 响应格式 | JSON，UTF-8 |
| 实测延迟 | 约 0.55s（含跨境网络往返） |
| 数据更新频率 | **每 12 小时**（每天 08:00 / 20:00 UTC+8 触发，单轮约 19 分钟；免费信源另有 2 小时级高频存档，处理仍按 12h 批量） |

无鉴权或 token 错误返回 `401 {"error": "Unauthorized"}`。

> **HTTPS 地址说明（2026-07-26）**：GCP 防火墙只放行了 8080 端口（VM 的服务账号
> 无权改防火墙规则），Let's Encrypt 无法验证 80/443，所以 HTTPS 走 Cloudflare
> quick tunnel（VM 上的 `b9-https-tunnel` systemd 服务，纯出站连接，开机自启）。
> 代价：**隧道进程重启后子域名会变**。取当前有效地址：
> `ssh manus-vm "sudo journalctl -u b9-https-tunnel | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1"`
> 要固定的自定义域名（如 lawrence-b9-strategy-hub.xxx），两条升级路径见
> OPEN_QUESTIONS —— 需要 Lawrence 二选一。

### 鉴权

**当前有 6 个等效的有效 token**（`api/server.py` 的 `VALID_API_KEYS`）：1 个早期的
`API_SECRET_KEY`（就是本文档示例里用的那个，为向下兼容保留），加 2026-07-26 新发的
5 个分发用 token（`lawrence` / `team-a` / `team-b` / `partner-1` / `partner-2`），
每个对接方各持一个，出问题时可以**单独吊销一个而不影响其他人**。请使用发给你的那个
token，不要转用文档示例里的那个。全部 token 都可以用环境变量覆盖（改
`config/.env` 后重启服务即可轮换）。

> ⚠️ 这 6 个 token **权限完全相同**，只是身份标签不同，没有做分级授权与速率限制。

传 token 有两种方式，服务端等价（先看 Header，为空才看查询参数）：

**方式 1：请求头（程序化调用一律用这个）**

```bash
curl -s "http://34.138.247.158:8080/api/news?limit=5" \
  -H "Authorization: Bearer <你的 token>"
```

**方式 2：`?token=` 查询参数（只为"浏览器里直接点开就能看数据"这一个场景存在）**

```
http://34.138.247.158:8080/api/news?limit=5&token=<你的 token>
```

浏览器地址栏发不出自定义请求头，非技术同事要看数据只能走这条路。**代价是 token
会被完整记录进浏览器历史、服务器访问日志、以及任何中间代理的日志里**，还容易随手
复制粘贴到聊天工具里扩散出去。因此：

- 仅限**内部可信网络**内的人工临时查看；
- 不要把带 token 的 URL 写进代码、脚本、书签同步或工单系统；
- 程序化接入一律用方式 1；
- 如果某个 `?token=` 链接已经外泄，直接轮换对应的那一个 token 即可，其他对接方不受影响。

### 最小验证

```bash
curl -s "http://34.138.247.158:8080/health"
```

`/health` 无需鉴权，返回 `{"status":"ok","news_count":<事件总数>,"time":"<UTC>"}`，可直接用作存活探针。

---

## 二、端点清单

### 1. `GET /api/news` — 事件列表（主接口）

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `limit` | int | 20 | 每页条数，**上限 100** |
| `offset` | int | 0 | 翻页偏移 |
| `sort` | string | `importance` | `importance` 按重要性分降序；`date` 按抓取时间降序 |
| `sector` | string | — | 板块精确筛选，取值见板块枚举 |
| `source` | string | — | 信源筛选，中文需 URL 编码。支持前缀通配：`X*` 匹配全部 X KOL |
| `news_type` | string | — | `market` / `policy` / `security` / `project` / `macro` / `other` |
| `event_tier` | string | — | `S` / `A` / `B` / `C` / `D` |
| `is_rumor` | string | — | `1`/`true` 只看谣言，`0`/`false` 排除谣言 |
| `date_from` | date | — | `YYYY-MM-DD`，含当天 |
| `date_to` | date | — | `YYYY-MM-DD`，含当天 |
| `run_at` | datetime | — | 只取某一轮生产采集的事件，取值见 `GET /api/run-nodes` 返回的 `run_at`；半开区间 `[run_at, run_at+12h)` |

响应：

```json
{
  "data": [ { /* 事件对象，字段见第三节 */ } ],
  "meta": { "total": 855, "limit": 20, "offset": 0 }
}
```

`meta.total` 是**符合筛选条件的总数**（非本页条数），可据此翻页。

### 2. `GET /api/news/<event_id>` — 单事件详情

返回单个事件对象；不存在返回 `404 {"error": "Not found"}`。

### 3. `GET /api/news/<event_id>/x-sources` — 该事件的 X 原始推文

返回支撑该事件的 KOL 推文列表，按点赞数降序。用于前端展示「来源推文」。

### 4. `GET /api/sources` — 信源分布

```json
{ "data": [ { "source": "吴说区块链", "event_count": 50 }, ... ] }
```

按事件数降序，可直接用作前端筛选下拉框的数据源。

### 5. `GET /api/x-posts` — X KOL 推文查询

| 参数 | 说明 |
|---|---|
| `limit` | 默认 20，上限 100 |
| `kol` | 按 KOL 用户名筛选，如 `lookonchain` |
| `sort` | `date`（默认）/ `likes` / `impressions` |

### 6. `GET /api/runs` — Pipeline 运行记录

返回最近 20 轮的水位数据（raw / deduped / enriched / events / 耗时 / 状态）。**运维监控用**，下游业务一般不需要。

健康判据：`enriched_count == deduped_count`（零丢失铁律）且 `status == "success"`。

### 7. `GET /api/run-nodes` — 生产轮次节点

| 参数 | 说明 |
|---|---|
| `limit` | 默认 20，上限 60 |

按每天 08:00 / 20:00（UTC+8）两个调度节点给事件分桶，返回每个节点的 `run_at`
（`YYYY-MM-DD HH:MM:SS`）与该轮 `event_count`。这里的 `run_at` 直接喂给
`GET /api/news` 的 `run_at` 参数使用。

### 8. `GET /api/source-catalog` — 信源目录

无参数，一次返回全部信源（约 380 个：注册表 ~64 个 + 搜索召回长尾 ~316 个）。
每条包含：`name`（信源名）、`channel`（接入方式：RSS 直连/自建 RSSHub/HTML 解析/
X KOL 时间线/X 全网搜索/搜索引擎）、`lang`、`authority`（人工权威分 1–5，
仅注册信源有值）、`tier`（校验分层：official/top_media/established/secondary/
unknown/anonymous，与真实性校验同一套口径）、`tier_weight`、`event_count`
（该信源真实产出的事件数，0 表示配了但没用上）、`url`。**运维/选品用**，
下游业务一般不需要。

---

## 三、事件对象字段

### 内容字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 事件唯一 ID，**由事件指纹派生，跨轮稳定**——同一事件重复抓到不会产生新 ID，可安全用作前端 key |
| `title_zh` / `title_en` | string | 双语标题，LLM 重写为可独立理解的一句话（中文 ≤25 字） |
| `description_short_zh` / `_en` | string | 短摘要（中文 50-100 字），含具体数字 |
| `description_long_zh` | string | 长摘要，**只产中文**（2026-07-26 起，省成本+提速），长度按事件重要性分档：S/A 档 ≤300 字完整背景，B 档 ≤160 字，C/D 档 ≤80 字只给结论 |
| `description_long_en` | string | **已废弃，新数据恒为空**。仅历史行（该时间点之前入库）可能有值，新代码不要依赖这个字段 |
| `date` | string | 事件日期 |
| `time_event` | datetime | 事件真实发生时间（ISO8601） |
| `time_get_data` | datetime | 本系统抓取时间 |
| `language_origin` | string | 原始信源语言 |

### 分类字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `sectors` | array | 板块标签，见下方枚举。已按相关度阈值（≥0.55）过滤，"真相关才打" |
| `sector_relevance` | array of object | 板块判定明细，每个含 `sector`/`relevance`/`anchor`（本条新闻里支撑该标签的具体锚点，如成分币/机制名）。低于阈值未进 `sectors` 的候选也留在这里，供复盘 |
| `coins` | array | 相关币种 ticker，如 `["BTC","ETH"]` |
| `entities` | array of object | 结构化实体，每个含 `name`/`type`（`person`/`organization`/`project`/`chain`/`region`/`product`） |
| `sentiment` | string | `bullish`/`bearish`/`neutral`，**对加密市场的方向性影响**，不是原文语气 |
| `sentiment_score` | number | -1（极度利空）~ +1（极度利多），符号与 `sentiment` 一致 |
| `impact_horizon` | string | `immediate`/`short_term`/`medium_term`/`long_term`，影响生效的时间尺度 |
| `news_type` | string | `market`/`policy`/`security`/`project`/`macro`/`other` |
| `event_tier` | string | S/A/B/C/D 五级，S 最重要 |

### 币种市值标签（2026-07-26 新增，`crawler/market_cap.py`，纯查表零 LLM 成本）

| 字段 | 说明 |
|---|---|
| `coin_metrics` | array of object，事件涉及的每个币各一条，含 `symbol`/`status`（`ok`/`ambiguous`/`equity`/`unknown`）/`market_cap_usd`/`btc_ratio`/`cap_tier`/`asset_class`。**`status` 不是 `ok` 时其余字段可能为空**——匹配不到明确的币不会瞎猜，宁可空着 |
| `primary_coin` | string，事件里市值最大的已匹配币（下面三个字段都是它的） |
| `primary_coin_market_cap` | number，市值 USD |
| `primary_coin_btc_ratio` | number，**相对 BTC 的市值倍数**（BTC 自己 = 1.0，如 0.05 即"BTC 市值的 5%"） |
| `coin_cap_tier` | string，`mega`/`large`/`mid`/`small`/`micro` 市值档位 |

### 真实性校验字段（2026-07-26 新增，`crawler/verification.py`，五个客观信号零 LLM 成本）

| 字段 | 说明 |
|---|---|
| `verification_status` | `VERIFIED`/`PROBABLE`/`UNVERIFIED`/`DISPUTED`。基于按机构去重的多源交叉验证、信源可信度分层、时间一致性、矛盾检测综合判定，**不依赖 LLM 主观判断** |
| `verification_score` | 0-1，校验综合分 |
| `verification_reason` | string，人类可读的判定依据 |
| `verification_flags` | array，触发的具体异常码（如 `TIME_STALE`/`LLM_RUMOR`/`SINGLE_LOW_TRUST_SOURCE`） |
| `independent_source_count` | int，按**机构**去重后的独立信源数（比 `source_count` 更严格——同一机构的多个 feed/账号只算一个） |

### 打分字段（Macro Insight v1）

| 字段 | 范围 | 说明 |
|---|---|---|
| `importance_score` | 0-1 | **综合重要性分，排序主键** |
| `score_market_impact` | 0-1 | M 影响面，权重 0.35 |
| `score_timeliness` | 0-1 | T 时效，权重 0.20（24h 半衰期指数衰减） |
| `score_hotness` | 0-1 | H 热度，权重 0.15 |
| `score_authority` | 0-1 | A 权威，权重 0.15（谣言打 7 折） |
| `score_quality` | 0-1 | Q 信噪质量，权重 0.15 |

`importance_score = 0.35M + 0.20T + 0.15H + 0.15A + 0.15Q`

> **时区约定（2026-07-26 起）**：项目所有时间统一为 **UTC+8**（VM 系统时区、
> MySQL、cron、日志均已切换）。切换时点之前入库的历史行时间戳按 UTC 记录，
> 显示上会比真实北京时间早 8 小时，随数据老化自然淘汰，不做回填。

**注意 T 因子随时间衰减**：同一事件的 `importance_score` 会随着变旧而下降，每轮 pipeline 会刷新。下游若做缓存，建议 TTL 不超过一轮（当前节奏 12 小时）。

### 信源与可信度字段

| 字段 | 说明 |
|---|---|
| `source_names` | array，报道该事件的全部信源名。可用于前端展示「N 家媒体报道」 |
| `sources` | array of object，每个含 `name`/`url`/`type`/`authority`/`published_at`/`x_tweet_id`。**原文链接从这里取** |
| `source_count` | int，独立信源数（按主域名去重） |
| `is_verified` | bool，`source_count >= 2` 即多源交叉验证 |
| `merged_sources_count` | int，被归并的报道条数 |
| `credibility_score` | 0-1，可信度 |
| `is_rumor` / `rumor_reason` | 谣言标记与原因。**谣言不会被删除，只降权**，下游可自行决定是否展示 |
| `social_interactions` | int，关联 X 推文的互动总量（赞+转+评+引） |
| `x_posts` | array of object，该事件关联的 **X 原贴完整信息**（2026-07-26 新增）。每个含 `tweet_id`/`kol_username`/`kol_display_name`/`kol_verified`/`kol_followers_count`/`tweet_body`/`tweet_url`/`tweet_lang`/`like_count`/`retweet_count`/`reply_count`/`quote_count`/`impression_count`/`published_at`。非 X 来源的事件此字段为空数组 `[]`。`/api/news` 和 `/api/news/<id>` 都会带上，不需要再调 `/api/news/<id>/x-sources` 单独请求 |

### 去重字段

| 字段 | 说明 |
|---|---|
| `event_subject` / `event_action` | 规范化事件三元组的主体与动作 slug |
| `event_fingerprint` | 事件指纹，等于 `id` |
| `cluster_id` | 归并簇 ID |

> `embedding` 列（256 维向量）**不对外暴露**，它只服务于服务端去重。

### 板块枚举（`sectors` 取值）

```
New Listing, bStocks, Seed, tCommodities, BSC, DeFi, Gaming, NFT,
Layer1/Layer2, Launchpad, Payments, Monitoring, RWA, Solana,
Fan Token, Infrastructure, AI, Launchpool, Megadrop, MEME
```

---

## 四、典型调用

**取全市场 Top 20 重要新闻（Macro Insight 主流）**

```bash
curl -s "http://34.138.247.158:8080/api/news?limit=20&sort=importance" \
  -H "Authorization: Bearer YOUR_API_SECRET"
```

**取 DeFi 板块新闻，排除谣言**

```bash
curl -s "http://34.138.247.158:8080/api/news?sector=DeFi&is_rumor=0&limit=10" \
  -H "Authorization: Bearer YOUR_API_SECRET"
```

**只看 S/A 级重大事件（需分两次请求，暂不支持多值）**

```bash
curl -s "http://34.138.247.158:8080/api/news?event_tier=S&limit=20" \
  -H "Authorization: Bearer YOUR_API_SECRET"
```

**按中文信源筛选（注意 URL 编码）**

```bash
curl -s -G "http://34.138.247.158:8080/api/news" \
  --data-urlencode "source=吴说区块链" --data-urlencode "limit=10" \
  -H "Authorization: Bearer YOUR_API_SECRET"
```

**Python 接入示例**

```python
import requests

BASE = "http://34.138.247.158:8080"
HEADERS = {"Authorization": "Bearer YOUR_API_SECRET"}

def fetch_macro_feed(limit=20):
    r = requests.get(f"{BASE}/api/news",
                     params={"limit": limit, "sort": "importance", "is_rumor": 0},
                     headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()["data"]

for event in fetch_macro_feed(10):
    sources = "、".join(event["source_names"])
    print(f"[{event['event_tier']}] {event['importance_score']:.3f} {event['title_zh']}")
    print(f"    {event['description_short_zh']}")
    print(f"    {sources}（{event['source_count']} 家）")
```

---

## 五、已知限制

1. **HTTP 明文，无 TLS**。token 与响应内容在传输中可被窃听。生产接入前建议加 HTTPS（Caddy/Nginx 反代 + Let's Encrypt）。
2. **静态 token，无分级权限、无速率限制**。当前 6 个 token（1 个 legacy + 5 个分发用，见「一、基本信息 § 鉴权」）权限完全相同，任何拿到其中任意一个的人都可读取全部数据；区别只在于可以单独吊销。另外支持 `?token=` 查询参数传值，方便浏览器直接打开，但 token 会落进浏览器历史与访问日志，仅供内部可信网络使用。
3. **单实例无高可用**，systemd 管理（`crypto-news-api.service`）。VM 重启后 RSSHub 容器偶尔不自启，需 `docker start rsshub`。
4. **`event_tier` 与 `sector` 只支持单值**，多值筛选需多次请求后自行合并。
5. **无 WebSocket / 推送**，只能轮询。数据每 12 小时更新一次，轮询频率高于此没有意义。
6. **Sector Insight 策略接口已上线**（2026-07-26）：`GET /api/recommend/sector?sector=<板块>` 返回真实相关性打分（Rel 硬门 0.5 + `Rel^1.5 × (0.25T+0.25H+0.20A+0.30M)`、板块内去重 0.75、宁缺毋滥 Top≤3，附逐条 reason 与被过滤事件的落选原因）。`/api/news?sector=` 仍是简单标签筛选，两者语义不同，推荐场景请用前者。

---

## 六、运维备注

- 服务：`systemctl status crypto-news-api`，日志 `journalctl -u crypto-news-api -f`
- Pipeline 日志：`~/crypto-news-crawler/logs/pipeline.log`
- **改 schema 后必须重启 API 服务**：`api/server.py` 用显式列清单 `EVENT_COLUMNS` 而非 `SELECT *`，加列后若不重启，旧代码可能因取到无法 JSON 序列化的列而 500
