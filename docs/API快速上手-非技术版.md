# B9 新闻数据 API — 快速上手（非技术版）

> 这份文档面向**不写代码的同事**。你只需要会点链接、会复制粘贴。
> 需要写程序对接的工程师请看 [api-integration-guide.md](api-integration-guide.md)。

---

## 一、最快的用法：直接点链接

把下面的链接复制到浏览器地址栏，回车，就能看到数据。

### 看最新最重要的 20 条新闻

```
http://34.138.247.158:8080/api/news?limit=20&token=YOUR_API_SECRET
```

### 只看最重大的事件（S 级和 A 级）

```
http://34.138.247.158:8080/api/news?event_tier=S&limit=20&token=YOUR_API_SECRET
```

```
http://34.138.247.158:8080/api/news?event_tier=A&limit=20&token=YOUR_API_SECRET
```

### 看某个板块的新闻（比如 DeFi）

```
http://34.138.247.158:8080/api/news?sector=DeFi&limit=20&token=YOUR_API_SECRET
```

### 排除谣言，只看已核实的

```
http://34.138.247.158:8080/api/news?is_rumor=0&limit=20&token=YOUR_API_SECRET
```

### 看系统运行是否正常

```
http://34.138.247.158:8080/health
```

正常会显示 `"status": "ok"` 和当前的新闻总条数。

---

## 二、页面上一堆花括号，怎么看得懂？

浏览器直接打开会显示 JSON 格式（一堆 `{` `}` 和引号），确实不好读。三个办法：

**办法一（推荐）**：用 Chrome 浏览器，装一个免费插件 **JSON Viewer**，装完后
再点上面的链接，数据会自动排版成漂亮的折叠列表。

**办法二**：把整个页面内容复制下来，粘贴到 https://jsonformatter.org/ 这类
在线格式化网站，点 Format 就排版好了。

**办法三**：直接把内容发给 AI 助手（ChatGPT / Claude），说"帮我把这些新闻整理成表格"。

---

## 三、链接怎么改？（拼装规则）

链接的结构是这样的：

```
http://34.138.247.158:8080/api/news  ?  参数1=值  &  参数2=值  &  token=YOUR_API_SECRET
└──────────── 固定不变 ────────────┘   └──── 你可以自由组合 ────┘   └── 必须带上 ──┘
```

**规则**：
- 第一个参数前面用 `?`，后面每加一个参数用 `&` 连接
- `token=YOUR_API_SECRET` 是通行证，**每个链接都必须带**，不带会提示 Unauthorized

### 常用参数对照表

| 想要什么 | 加这段 | 例子 |
|---|---|---|
| 控制条数 | `limit=数字` | `limit=50`（最多 100） |
| 按重要性排序 | `sort=importance` | 默认就是这个 |
| 按时间排序 | `sort=date` | 最新的排最前 |
| 只看某个级别 | `event_tier=级别` | `event_tier=S`（S最重大，然后 A/B/C/D） |
| 只看某个板块 | `sector=板块名` | `sector=MEME`、`sector=DeFi` |
| 只看某类新闻 | `news_type=类型` | `news_type=security`（安全事故） |
| 排除谣言 | `is_rumor=0` | |
| 只看谣言 | `is_rumor=1` | |
| 指定日期范围 | `date_from=日期&date_to=日期` | `date_from=2026-07-20&date_to=2026-07-25` |
| 翻页 | `offset=数字` | `limit=20&offset=20` 就是第 2 页 |

### 板块名可选值

```
MEME        DeFi        AI          Gaming      NFT
RWA         Solana      BSC         Payments    Launchpool
Launchpad   Megadrop    Seed        bStocks     Infrastructure
Layer1/Layer2           New Listing Monitoring  Fan Token   tCommodities
```

### 新闻类型可选值

| 值 | 含义 |
|---|---|
| `market` | 行情市场 |
| `policy` | 政策监管 |
| `security` | 安全事故 |
| `project` | 项目动态 |
| `macro` | 宏观经济 |
| `other` | 其它 |

### 自己拼一个试试

想看"MEME 板块、排除谣言、最重要的 10 条"：

```
http://34.138.247.158:8080/api/news?sector=MEME&is_rumor=0&limit=10&token=YOUR_API_SECRET
```

---

## 四、返回的数据里都有什么？

每条新闻长这样（挑重要的说）：

| 字段名 | 是什么 | 例子 |
|---|---|---|
| `title_zh` | **中文标题** | 美国比特币以太坊现货ETF净流出3.11亿美元 |
| `title_en` | 英文标题 | US Spot Bitcoin, Ether ETFs See $310.6M Net Outflows |
| `description_short_zh` | **中文短摘要**（50-100字） | 带具体数字的要点概括 |
| `description_long_zh` | 中文详细说明（几百字） | 完整背景 + 市场影响分析 |
| `event_tier` | **重要性级别** | `S` 最重大 → `A` → `B` → `C` → `D` 最次要 |
| `importance_score` | **综合重要性打分** | 0 到 1，越大越重要，列表默认按这个排序 |
| `sectors` | 涉及板块 | `["DeFi", "Layer1/Layer2"]` |
| `coins` | 涉及币种 | `["BTC", "ETH"]` |
| `source_names` | **哪些媒体报道了** | `["CoinDesk", "TheBlock", "吴说区块链"]` |
| `source_count` | **几家独立媒体报道** | `5`（数字越大越可信） |
| `x_posts` | **如果这条新闻来自 X（推特），这里是原贴的完整内容** | 含发推人、原文、点赞/转发数、发布时间。不是 X 来源的新闻这里是空的 |
| `is_rumor` | 是否谣言 | `0` 不是 / `1` 是 |
| `time_event` | 事件发生时间 | |
| `date` | 日期 | |

### 怎么判断一条新闻靠不靠谱？

看两个字段组合判断：
- **`source_count` 越大越可信** —— 5 家媒体都在报道的事，比只有 1 家报道的可信得多
- **`is_rumor` 是 1** —— 系统识别出这是未经证实的传闻，谨慎对待（我们不删除谣言，
  只是标记出来并降低排序，因为有些重大消息最初就是以传闻形式出现的）

---

## 五、常见问题

**Q：显示 `{"error": "Unauthorized"}` 怎么办？**
链接末尾漏了 `&token=YOUR_API_SECRET`，或者拼写有误。注意第一个参数前
用 `?`，后面的用 `&`。

**Q：数据多久更新一次？**
每天 2 次，北京时间早上 8 点和晚上 8 点各跑一次，每次约 20 分钟完成。

**Q：为什么有些新闻看起来是好几天前的？**
默认按**重要性**排序而不是时间，重大事件即使过了一两天也会排在前面。想看最新的，
把链接里的排序改成 `sort=date`。

**Q：最多能一次拿多少条？**
单次最多 100 条。要更多就用 `offset` 翻页：第一页 `limit=100`，
第二页 `limit=100&offset=100`，以此类推。

**Q：这个链接能发给别人吗？**
可以，但链接里包含通行证（token），拿到的人就能访问全部数据。**只在公司内部分享**。

**Q：能导出成 Excel 吗？**
可以让技术同事帮忙导，或者把 JSON 数据发给 AI 助手让它转成表格。
仓库里 `materials/exports/` 目录下也有定期导出的 Excel 文件。

---

## 六、需要注意的

- 这个服务目前是 **HTTP 明文传输**，且只有一个固定通行证，**仅限公司内部使用**，
  不要对外公开链接
- 服务跑在单台服务器上，没有做高可用，偶尔可能短暂不可用，刷新重试即可
- 数据仅供参考，重大决策请以官方渠道信息为准
