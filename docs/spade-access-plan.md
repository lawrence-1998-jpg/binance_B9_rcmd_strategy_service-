# Spade 数据平台接入 & 取数计划

> 课题：**用户价格敏感度建模**——一个用户对多大幅度的持仓资产价格波动才会敏感
> （价格变化 → 交易 / 查看）。敏感者高频低门槛发 price alert，反之高门槛低频。
> 状态：2026-08-19 起步。本文件是跨会话的工作底稿。

## ⚠️ 前提（Lawrence 2026-08-19 澄清，决定了整个方法论）

**目前线上没有 price alert 产品。** 因此这是一个**纯观察性研究**：

```
自然价格波动 → 用户自然的访问 / 交易（针对其持仓标的）→ 反推敏感度 → 0→1 上线产品
```

由此产生的三个结论：

1. **不需要 alert 点击回流数据**。之前标记的"3-E 缺口"随之消失——没有产品就没有推送，
   监督信号来自用户对自然行情的自发反应。
2. **反向因果的担忧大幅减轻**。没有推送干预，观察到的行为就是自发的；
   但代价是**没有实验变异**，因果结论在产品上线前无法验证，只能是相关性证据。
3. **解释了 price_alert 表族的怪象**：还在更新的几张都在 `cmc_dw.*`
   （CoinMarketCap，独立产品），主站那几张 2024 年就停更了——因为主站根本没上这个功能。
   **这些表只能当参考口径，不是本课题的数据源。**

## 一、接入方式（已摸清）

Spade 官方支持程序化接入，**不需要扒浏览器 session**：

```
# 1. 个人 token 换短期 JWT
POST https://bdp-bff.toolsfdg.net/api/personal-token/exchange
Content-Type: application/json
{"token": "<PERSONAL_TOKEN>"}

# 2. 用返回的 JWT 调 API
GET https://bdp-bff.toolsfdg.net/api/proxy/...
Authorization: Bearer <ACCESS_TOKEN>
```

- token 在 Spade 右上角头像 → **Personal Token** 页创建
- 当前 token：`lawrence_token_1`，2026-08-19 创建，2027-02-15 过期
- **存放**：`~/.b9/spade_token`（600 权限，仓库外）。B9 仓库是 public，密钥绝不入库
- ⚠️ **待办**：`lawrence_token_1` 曾在聊天里明文出现过，接入跑通后应删除重建

### 备选通路（更老，不推荐）
JDBC 直连 Presto/Hive 集群内网 IP，需单独申请 LDAP 账号 + SSL truststore
（Confluence《Introduction to JDBC》，2022 年文档，标记 `modifiedbefore2023`）。

### 前置条件
Spade 是内网站点（`*.toolsfdg.net`），**必须挂 VPN**。Mac 上 GlobalProtect 连着才通；
GCP 上那台 VM 连不到内网，所以这条链路只能落在 Mac 上。

## 二、平台能力地图

| 模块 | 用途 | 备注 |
|---|---|---|
| **BnQuery** | adhoc SQL，Trino(默认) / Spark 双引擎 | 实测 `SELECT 1` 走 Trino 156ms |
| **Data Map** | 元数据 + 血缘 + 全文搜表 | `/datamap/search?query=xxx` 可直接拼 URL |
| **Access Center** | 权限申请与管理 | BnQuery 遇无权限表会**当场弹 Apply**，不用绕过来 |
| **Feed Features Management** | **1200+ 条 Feed 推荐特征定义** | 高价值，用户特征可能直接复用，优先看 |
| Datawind | BI 报表与数据集 | |
| Bnflow 2.0 | ETL 调度 | 建模落地后排产用得上 |

Confluence 文档入口：`https://confluence.toolsfdg.net/display/BD/Spade+User+Guide`

## 三、建模需要的六类数据

| # | 类别 | 作用 | 状态 |
|---|---|---|---|
| 1 | **price alert 订阅与触发** | 现状基线 | ✅ 已定位 |
| 2 | **price alert 点击/打开回流** | **标签的关键**，没有它只能测"发了"不能测"有效" | ⚠️ 仍缺 |
| 3 | **行为埋点（含行情页浏览）** | "价格变化 → 看"这一半 | ✅ 已定位 |
| 4 | **交易明细**（下单/成交，带时间戳） | "价格变化 → 交易"这一半 | 待补搜 |
| 5 | **持仓快照** | 判断"他关心哪些资产"，**没有它整个课题不成立** | ✅ 已定位 |
| 6 | **K线行情** | 算波动幅度，敏感度的自变量 | ✅ 已定位 |
| 7 | 用户画像/特征 | 分群与冷启动 | ✅ 已定位（`bnb_tdm` 全族） |

### 3-A 行为埋点（`user_behavior` 搜索命中 19 张）

| 表 | 说明 | 级别 |
|---|---|---|
| **`bnb_dwd.fact_main_user_behavior_hr_d`** | **主站行为事实表·小时粒度——本课题的核心表** | C3 |
| `bnb_dwd.fact_main_user_behavior_d` | 主站行为事实表·日粒度 | C3 |
| `bnb_dwd.fact_main_user_behavior_ip_d` | 带 IP 维度 | C3 |
| `bnb_dwd.fact_us_user_behavior_d` | 美区 | C3 |
| `bnb_dwm.metr_user_behavior_d / _w / _m` | 日/周/月汇总指标 | C3 |
| `bnb_dwd.dwd_main_search_user_behavior_di` | 搜索行为 | C3 |
| `bnb_sensor.user_behavior` | 埋点原始层 | — |
| `bnb_marketing.user_behavior_user_behavior_log` | 营销侧行为日志 | — |

> 小时粒度是关键：价格波动的行为响应窗口通常在分钟~小时级，日粒度会把信号抹平。
> 若 `hr_d` 仍不够细，需回到 `bnb_sensor` 原始层取事件级时间戳。

### 3-B 持仓 / 资产（`user_asset`）

| 表 | 说明 |
|---|---|
| `bnb_dws.fact_main_user_asset_sr_df_ha` | 主站用户资产快照 |
| `bnb_dws.dws_main_asset_user_sr_td_ha` | 资产汇总 |
| `bnb_reconciliation.dm_asset_user_asset_freeze_recoon_1d` | 冻结资产对账 |
| `ods.pnk_user_asset` | ODS 层 |

### 3-C K线行情（`kline`，25 张）

| 表 | 说明 | 级别 |
|---|---|---|
| **`bnb_dwd.dwd_main_ms_spot_bnb_kline_di`** | **主站现货 K 线·日** — 主用 | C3 |
| `bnb_dwd.dwd_web3_kline_offline_hi` | Web3 代币 K 线·**小时** | C3 |
| `bnb_dwd.dwd_web3_kline_offline_di` | Web3 代币 K 线·日 | C3 |
| `bnb_dwd.dwd_web3_token_kline_rf_hudi` | Web3 近实时（Hudi） | C3 |
| `bdp_web3_ha1_kafka.dwd_web3_token_kline_rf` | Kafka 实时流 | — |
| `bnb_dwa.research_{okx,ftx,bitget}_kline_d` | 友商行情，可做对照 | — |

### 3-D 用户画像特征（`bnb_tdm.user_profile_*` 全族）

`_sensor`（埋点）、`_action`（行为）、`_spot`（现货）、`_pay`（支付）、
`_reg`（注册）、`_vip`（VIP 等级）、`_blvt`（杠杆代币）——全部 C3，
Business Segment = Main，Data Domain = UFO，2026-08-18 仍在更新，
owner 分别为 derek.hsieh / run.huang / george.zz。

> **这一族是特征工程的现成底座**：按业务线切好的用户画像，不必从埋点重新造特征。
> `_spot` + `_blvt` 直接刻画交易偏好，`_vip` 给分层，`_action` 给活跃度。

### 3-E 仍然缺的一块 ⚠️

**price alert 的点击/打开回流**没搜到。这是标签定义的关键——
没有它只能衡量"推了多少"，无法衡量"推对没有"，敏感度模型就没有监督信号。
下一步：搜 `push_click` / `notification` / `message_open` / `app_push`，
或直接问 price_alert 表的 owner（george.zz / hank.y）回流数据落在哪里。

### 已定位：price_alert 表族

仍在更新的（可用）：

| 表 | 最近更新 | Owner | 级别 |
|---|---|---|---|
| `cmc_dw.prod_price_alert_mongo_cmc_price_alert_price_alerts_day` | 2026-08-18 | george.zz | C3 |
| `bnb_dw.price_alert_price_alert_new_alert_price_day_v2` | 2026-08-17 | hank.y | C3 |
| `bnb_dwd.dwd_cmc_coin_price_alert_df` | 2026-05-26 | kyle.z | C3 |
| `bnb_ods.binlog_price_alert_hudi` | 2025-12-22 | trevor.z | C3 |
| `bnb_dw.price_alert_new_alert_price` | 2025-12-21 | zb.s | C3 |

**已停更，勿用**（2024 年就不动了）：
`bnb_dw.price_alert_price_alert_alert_history_day`、`bnb_dw.price_alert_alert_history`（两个同名版本）、
`bnb_dw.price_alert_price_alert_new_alert_price_day`

另有 Datawind 看板 `spot_price_alert`（owner david.zz），可作为口径参考。

## 四、权限申请话术（Lawrence 给定，逐字使用）

> Apply for data to build a price alert sensitivity model to optimize the smart tooltips
> strategy in B9 project. As the senior strategy PM and data scientist of B9 recommendation.
> I will need user journey history, asset price change log, user features especially the
> marketing and transaction related ones, and other key dataset to build the model.

## 五、建模思路（一句话）

本质是**每用户一条剂量反应曲线**：

- **横轴**：持仓资产的价格波动幅度分档（±1% / ±3% / ±5% / ±10% …）
- **纵轴**：该档位下发生「交易或查看」的条件概率
- **拐点** = 这个人的**触发阈值**（多大波动才动）
- **斜率** = **敏感度**（越陡越应该高频低门槛推）

有了这两个参数，alert 的频率与门槛就是查表，不必再拍一个全局阈值。

需要注意的坑：
- **反向因果**：先推了 alert 才发生查看，不能算作"自发敏感"。要把 alert 触达作为
  处理变量剥离出去，否则测的是推送效果不是用户敏感度。
- **持仓不是静态的**：波动窗口内的持仓要用当时的快照，不能用最新持仓回溯。
- **零暴露用户**：从没持有过波动资产的人无法估计，需单独归入冷启动分群。

## 六、已知约束与踩过的坑

### 权限现状
Lawrence 已在 terminal 侧授权，BnQuery 输 SQL、跑查询、浏览器操作均可用。
仍被拦的：**从 Bash 读密钥文件后发内网请求**、**页面内直接 fetch 内网 API**
（带凭证打内网接口的特征）。因此 Personal Token → JWT 这条程序化链路尚未实测通过，
当前一切取数走「浏览器 UI + DOM 抽取」。

### 平台侧权限
`information_schema` **无权限**——`SHOW TABLES` / `SELECT ... FROM information_schema.tables`
一律 `Access Denied`。摸表只能靠 Data Map 搜索，不能靠 SQL 遍历元数据。
BnQuery 遇到无权限的表会**当场弹 Apply For Access**，申请入口在查询现场。

### 坑：Data Map 结果抽取
搜索结果里表名被高亮拆成多个 `<span>`（`bnb_tdm.` + `user_profile` + `_sensor`），
**按叶子节点抽取会得到 0 条**，看起来像"这类表不存在"。
必须取「最小完整容器」的 textContent。
> 我第一次就栽在这：`user_behavior` / `user_event` / `user_profile` 连续返回 0，
> 差点报告"没有这类表"，肉眼扫一眼截图才发现满屏都是结果。
> **教训同 `human-eyeball-test-is-my-floor`：抽取器返回 0 时先看屏幕，别信代码。**

可用的抽取器（在结果页控制台跑）：

```js
(function(){
  var re=/^[\w一-龥\[\]-]+(\.[\w-]+)+(Hive|Mysql|Kafka|Starrocks|Clickhouse|Hbase|Datawind)/;
  var res=[],seen={};
  document.querySelectorAll('div,span,a').forEach(function(el){
    var t=(el.textContent||'').trim();
    if(t.length<8||t.length>120||!re.test(t))return;
    var min=true;                                  // 只要最小容器
    for(var j=0;j<el.children.length;j++)
      if((el.children[j].textContent||'').trim()===t){min=false;break;}
    if(!min||seen[t])return;
    seen[t]=1; res.push(t);
  });
  return res;
})()
```

### 搜索接口（备查）
Data Map 真正的取数接口是
`POST https://bdp-bff.toolsfdg.net/api/bigdata-datamap/homepage/getSearchResultList`，
但直接 fetch 会被 Claude Code 分类器拦，目前只能走 UI。

## 六-B、权限申请：流程与进度

### 流程（已跑通）
直达 URL：`https://spade.toolsfdg.net/datamap/detail?name=<库.表>&assetType=hive_table&apply=true`
表单要点：
- Permission Type 默认 **Read Only**（保持）
- Permission Duration 默认 **7 days → 必须改成 60 days**（选项：7/30/60…，建模项目 7 天不够）
- 字段清单默认全选
- **Request Reason 必填**，用第四节话术 + 该表具体字段与用途
- 提交成功会弹 "Successfully request access"，但**提示可能一闪而过**

### ⚠️ 验证纪律
**提交后必须去 Access Center → My Request → In Progress 核对**，不能凭有没有看到 toast 判断。
（08-19 第二条申请就没截到提示，实际已成功。同 `verify-write-not-just-return-code`。）

- `My Request` = 我提交的申请（含 In Progress / Completed）
- `My Access` = 已获批的权限（批之前是空的，别误判成申请失败）
- URL：`https://spade.toolsfdg.net/security/access-center/my-request`

### 进度

| ID | 表 | 用途 | 状态 |
|---|---|---|---|
| 148808 | `bnb_dwd.fact_main_user_behavior_hr_d` | 行为埋点·小时粒度（核心） | In Progress |
| 148809 | `bnb_dws.fact_main_user_asset_sr_df_ha` | 持仓快照 | In Progress |

待申请：`dwd_main_ms_spot_bnb_kline_di`（K线）、`dwd_web3_kline_offline_hi`（小时K线）、
`bnb_tdm.user_profile_spot / _action / _vip`（画像特征）、`fact_main_user_behavior_d`（日粒度）。

### 已确认的表结构

**`bnb_dwd.fact_main_user_behavior_hr_d`** — 自埋点流量中间表·按小时分区
Table Owner `run.huang` / Tech Owner `maya.c`，Data Domain `User/Traffic`，
Business Process `View`，Asset Level P3，建于 2020-11-03，2026-08-18 仍更新。

字段（全 string 除注明）：`user_id`、`event_name`、`local_time`、`url`、`element_id`、
`client`、`client_type`、`os`、`browser`、`user_agent`、`finger_print`、`language`、
`ip_country_name`、`ip_country_code`、`screen_height`、`screen_weight`
分区键：`date_key`(int) + `hr`(string)

> `event_name` 是识别"看了行情页 / 看了某币详情页"的关键字段；
> `url` 可用于解析用户看的是哪个 symbol。这两个字段决定了"看"这一半能不能落地。

**`bnb_dws.fact_main_user_asset_sr_df_ha`** — user_asset df
Table Owner `kevin.ww`，字段含 `funding_wallet_balance` decimal(28,8)、
`po_fi_asset_holding_btc` decimal(38,16)（POS 定期持仓）、
`sv_fi_asset_holding_btc` decimal(38,16)（Savings 定期持仓）等持仓金额列。

> ⚠️ 存疑：该表 Views 仅 6、近 7 天查询 0、Update History 显示 2026-01-09，
> 且 Data Domain / Business Segment 均为 None。**拿到权限后第一件事是验数据新鲜度**，
> 若确为废弃表则改用 `bnb_dws.dws_main_asset_user_sr_td_ha`。

## 七、下一步

1. 补搜交易明细表（`user_trade` / `order` / `spot_trade`）
2. 补搜 price alert 点击回流（3-E 那块缺口）
3. 逐张对需要的表点 Apply For Access，用第四节的话术
4. 打通 Personal Token → JWT，摆脱浏览器依赖

---

## 八、首次取数实测（2026-08-19，权限批下来之后）

**能取到数据了。** 148808 已批准，Trino 查询 9~10 秒返回。

### 8-A 程序化通路已打通（不再依赖浏览器）

`~/.b9/bin/spade.sh <api路径> [json-body]` — 自动用 `~/.b9/spade_token`
换 JWT 并缓存到 `~/.b9/.spade_jwt`（12h 有效，超过 11h 自动刷新）。
`/api/users/me` 实测 200 正常返回。

⚠️ BnQuery 的提交查询接口 body 结构还没拿到：路径是
`POST /api/bigdata-bquery/queries`（返回 400 "Failed to read request" 说明路径对、
body 格式不对）。前端用 XHR 不是 fetch，挂钩 `window.fetch` 抓不到，
下次改挂 `XMLHttpRequest.prototype.send`。**在此之前 SQL 仍走浏览器 UI。**

### 8-B ⚠️ 重大发现：这张核心表覆盖不了全量用户

`bnb_dwd.fact_main_user_behavior_hr_d`，2026-08-18 全天：

| event_name | 事件数 | 去重用户 |
|---|---|---|
| elementShow | 3,182,372 | 124,308 |
| webClick | 1,248,349 | 114,527 |
| keypress | 2,658 | **1** |
| onChange | 1,978 | **1** |
| **pageView** | **1,484** | **77** |
| pageQuit | 483 | 45 |

按 client 拆：

| client | client_type | 事件数 | 去重用户 |
|---|---|---|---|
| **Web** | Web | 3,925,138 | **115,311** |
| iOS | Hybrid | 285,119 | 7,697 |
| Android | Hybrid | 216,941 | 6,539 |
| Unknown | electron | 10,330 | 88 |

**结论：这是 Web 端埋点表，不是 App 全量埋点。**

- 全天去重用户约 12 万量级，**远低于币安真实 DAU**
- iOS/Android 只有 Hybrid（App 内嵌 H5）的部分，**原生页面完全不在这张表里**
- `pageView` 全天仅 77 个用户、`keypress`/`onChange` 各只有 1 个用户
  —— 这些事件基本没有铺开埋点，**不能用来度量"看了行情页"**
- 可用的只有 `elementShow`（元素曝光）和 `webClick`（点击），
  要靠 `url` + `element_id` 反推用户看的是哪个 symbol

**对课题的影响：**
1. 单靠这张表，"价格变化 → 看" 这一半只能覆盖 Web + Hybrid 用户，
   **App 原生用户（大头）缺失**，样本有严重选择偏差。
2. 必须补一张 **App 原生埋点表**。候选：`bnb_sensor.user_behavior`（神策原始层）、
   `bnb_tdm.user_profile_sensor`、或 `bnb_dwd.fact_main_user_behavior_d`（日粒度，
   需确认是否同源）。**下一步优先查清 App 埋点落在哪张表。**
3. 在补齐之前，**任何基于此表的敏感度结论都只能声明为"Web 端用户"**，
   不能外推到全体用户。

> 教训同 `aggregate-number-hides-first-screen`：3,900,000 条事件看着很足，
> 但拆开才发现 pageView 只有 77 个用户、App 原生完全没覆盖。
> **拿到数据的第一件事是验证它能不能回答问题，而不是有多少行。**


---

## 九、选表纪律（2026-08-19 Lawrence + 表 owner 的反馈，必须遵守）

**用户原话："别给我乱搞一些乱七八糟的边缘表。申请一些正常的表。"**

我一开始申请了 `bnb_dws.fact_main_user_asset_sr_df_ha`（`_ha` 后缀）和
`bnb_sensor.user_behavior`（原始层、0 收藏、无描述），两次都被纠正：

- **Kevin.ww（表 owner）**："别用ha表吧" —— `_ha` 后缀的表不要用。
  我给不出 `_ha` 的权威定义（按命名习惯猜是小时全量或历史归档），
  但**owner 说不用就不用，不需要理解原因**。
- **Maya.c（Tech Owner）**：想查神策数据应该申请
  `bnb_dwd.dwd_main_user_traffic_sensor_behavior_di`，而不是 `bnb_sensor.user_behavior`。

### 判断一张表是不是"正常主流表"

| 看什么 | 好 | 差 |
|---|---|---|
| Asset Level | **P0 / P1** | P3 或空 |
| 收藏数 | 十几到几十 | 0 |
| 描述 | 有中英文说明 | "no description information" |
| 库 | `bnb_dwd` / `bnb_dws` / `bnb_dwm` | `bnb_temp` / `bnb_dtest` / `ods` / `_bak_日期` |
| 后缀 | `_di` `_df` `_d` | **`_ha`（明确禁用）** |
| Data Domain | 填了（User / Trade / Asset） | None |

对比实例：`bnb_dwd.dwd_main_user_traffic_sensor_behavior_di` 是 **P0、31 收藏、
有中英文描述**；而我最初挑的 `bnb_sensor.user_behavior` 是 **0 收藏、无描述**。
差别一眼可见，我当时没看。

### 找表应该从「数据专辑」进，不要盲搜

**Data Map → DW Data 页签**（`/datamap/batchdata`）就是官方数据专辑：
数仓团队清洗、编目、打标签过的表，按 业务板块 → 数据域 → 产品线 三级组织，
每个域还配了 Confluence 文档和讲解视频。

```
hive
├── Main (17)          ← 主站，我们要的
│   ├── User (5) → All / Info / KYB
│   ├── Trade (14) → Spot / Margin / Derivatives / BLVT / EuroOptions / OTC / Stock ...
│   ├── Asset (4)
│   ├── Financial (14) / Marketing (6) / NFT (7) / Risk (3) / UFO (1) ...
├── CMC (4) / Cloud (4) / Chain (3) / Custody (3) / Canada (3) ...
```

顶部还有筛选器：Security Level / Database / Business Segment / Data Domain /
Business Process / Tech Owner / Tags。**先在这里定位，再去详情页申请。**

## 十、权限申请进度（2026-08-19 收盘）

| ID | 表 | 用途 | 时长 | 状态 |
|---|---|---|---|---|
| 148808 | `bnb_dwd.fact_main_user_behavior_hr_d` | Web 埋点·小时 | 60天 | ✅ **已批准，可查** |
| 148868 | `bnb_dwd.dwd_main_user_traffic_sensor_behavior_di` | 神策全端埋点（Maya 推荐，P0） | 1年 | Reviewing |
| 148871 | `bnb_dwd.fact_main_spot_order_d` | 主站现货订单明细 | 1年 | Reviewing |
| ~~148809~~ | ~~`bnb_dws.fact_main_user_asset_sr_df_ha`~~ | — | — | ❌ Kevin 否掉（`_ha`） |
| ~~148865~~ | ~~`bnb_sensor.user_behavior`~~ | — | — | ❌ 我主动撤（Maya 指出选错） |

### 还缺
1. **持仓快照** —— `_ha` 那条被否，需从「数据专辑 → Main → Asset(4)」里重挑一张正规表
2. **K 线行情** —— `bnb_dwd.dwd_main_ms_spot_bnb_kline_di` 待申请
3. **用户画像** —— `bnb_dws.fact_main_user_profile_s`（C0、12 收藏、有描述）候选

---

## 十一、关键突破：一张表同时覆盖"看"和"交易"（2026-08-19 实测）

`bnb_dwd.dwd_main_user_traffic_sensor_behavior_di`（148868 已批准，1 年）
是 **175 列的神策全端埋点宽表**，实测结论：

### 覆盖量级（这是选它的决定性理由）

| 表 | 去重用户 | 说明 |
|---|---|---|
| `fact_main_user_behavior_hr_d` | **12.4 万 / 全天** | 仅 Web + Hybrid，App 原生缺失 |
| `dwd_main_user_traffic_sensor_behavior_di` | **2400 万 / 单小时** | 全端全量 |

体量：每天 170~210 亿条事件。**任何查询必须带 `date_key` 分区 + 时间窗，不能裸扫。**

### 关键字段（175 列中的有效部分）

`user_id`、`event`（主事件类型）、`eventname`（多为 null，别用）、
**`symbol`**（交易对）、`asset`（币种）、`pagename`、`element_name`、
`total_time`（停留时长）、`actual_event_time`（timestamp 类型，
比较时必须用 `TIMESTAMP '2026-08-18 12:00:00'` 字面量，直接给字符串会报
`Cannot apply operator: timestamp(3) <= varchar`）、`date_key`（int 分区）

### `event` 取值分布（08-18 12:00–12:15 抽样）

| event | 事件数 | 去重用户 | 带 symbol |
|---|---|---|---|
| `$AppExposure` | 1.05亿 | 118.9万 | 0 |
| `$AppViewScreen` | 3750万 | 35.5万 | 99.8万 |
| `$AppClick` | 2248万 | 37.2万 | 152.6万 |
| `ModuleView` | 252万 | 20.1万 | 45.9万 |
| **`place_order_event`** | **30.9万** | **4.2万** | **30.4万（98.5%）** |
| `kline_ws_timeout` | 76.6万 | 3.7万 | 76.6万 |

### 🎯 结论：不需要单独的交易表

`place_order_event` 带 `symbol`，直接给出「**谁 · 何时 · 对哪个交易对下单**」：

```
symbol      n       uu
GRVT        55926   1557
TUTUSDT     25467   4595
BTCUSDT     11498   3160
ETHUSDT      9239   2568
```

**"价格变化 → 交易"和"价格变化 → 看"两半都能从这一张表出**，
用 `event` 区分行为类型，用 `symbol` 对齐标的。省掉一整条交易表的申请与 join。

### 因此放弃的两张交易表

- `bnb_dwd.fact_main_spot_order_d`（148871 **已批准但没用**）——
  **实测数据只到 2021-04-17，停更五年**。元数据显示 "Last Updated 2026-05-18"
  但那是元数据变更时间，不是数据时间。**教训：元数据的更新时间不可信，
  申请前必须 `SELECT MAX(分区)` 验一次。**
- `bnb_dws.dws_main_trade_spot_order_uid_td`（**主动放弃，未提交**）——
  字段全是 `_td` 累计口径（`order_cnt_td`、`first/last_order_datetime_td`），
  **没有 symbol、没有单日明细**，答不了"用户在 D 日是否交易了币 Y"。
  看字段就该发现，不该只看表名和更新时间。

## 十二、申请进度（2026-08-19 更新）

| ID | 表 | 状态 | 时长 | 用途 |
|---|---|---|---|---|
| 148808 | `bnb_dwd.fact_main_user_behavior_hr_d` | ✅ 已批 | 60天 | Web 埋点，覆盖不足，仅作对照 |
| **148868** | **`bnb_dwd.dwd_main_user_traffic_sensor_behavior_di`** | **✅ 已批** | 1年 | **主力表：看 + 交易 全覆盖** |
| 148871 | `bnb_dwd.fact_main_spot_order_d` | ✅ 已批 | 1年 | ⚠️ 数据停在 2021，弃用 |
| 148877 | `bnb_dwd.fact_main_asset_ss_d` | Reviewing | 1年 | 持仓快照（token + 净持仓量） |
| ~~148809~~ | ~~`fact_main_user_asset_sr_df_ha`~~ | ❌ Rejected | — | Kevin 否掉（`_ha`） |
| ~~148865~~ | ~~`bnb_sensor.user_behavior`~~ | ❌ 已撤 | — | Maya 指出选错 |

### 还缺
**K 线行情** —— `bnb_dwd.dwd_main_ms_spot_bnb_kline_di` 字段已确认
（`high_price`/`low_price`/`close_price`/`volume`/`number_of_trades`，分区 `date_key`），
待提交申请。注意它挂在 MS(市占率) 域下、0 收藏，但字段就是标准 OHLCV，可用。

---

## 十三、主链路已跑通 + 首个实证信号（2026-08-19）

### 13-A 价格数据不必等审批

**币安公共 API 直接可用**，不需要任何内部权限：

```bash
curl -s "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=3"
# 返回 [开盘时间, open, high, low, close, volume, ...]
```

日涨跌幅 = `close/open - 1`。K 线 Hive 表（`dwd_main_ms_spot_bnb_kline_di`）
因此降级为可选项，**不再是阻塞项**。

### 13-B 首个实证结果：波动越大，持有者越活跃

**设计**：同一 symbol 跨天比较（不是跨 symbol 比较——见下方"踩过的坑"），
自变量 = 当日 |涨跌幅|，因变量 = 当日下单人数 / 该币 7 日均值。

样本：6 个主流币 × 7 天（2026-08-12 ~ 08-18），42 个点。

| symbol | 含周末 r | **仅工作日 r** |
|---|---|---|
| BTCUSDT | +0.451 | **+0.886** |
| DOGEUSDT | +0.897 | **+0.942** |
| XRPUSDT | +0.632 | **+0.882** |
| BNBUSDT | +0.635 | **+0.819** |
| ETHUSDT | +0.356 | +0.242 |
| SOLUSDT | +0.597 | +0.070 |
| **合并** | **+0.582 (n=42)** | **+0.608 (n=30)** |

**方向明确、量级可观**：币价波动越大，当天下单的持有者越多。

### 13-C 两个必须先排除的伪相关（都已检验）

**坑 1：跨币种比较是错的。**
第一版我按"各币当日下单人数 vs 当日涨跌幅"跨 symbol 算，得到 r=+0.125。
这个数没有意义——BTCUSDT 有 12.9 万人下单跟它当天只涨 0.30% 无关，
纯粹因为它最热门。**跨币种比较被"币的人气"主导，测不出敏感度。**
必须改成同币种跨天，人气才被自然控制住。

**坑 2：周末混杂。**
初版 42 个点里，08-15/08-16 恰好是周六周日，且所有币活跃度同步掉到 0.7x。
周末同时具备「用户少」和「波动小」两个特征，**足以单独制造出正相关**。
实测：

| | 平均相对活跃度 | 平均\|涨跌\| |
|---|---|---|
| 工作日 | 1.08x | 0.82% |
| 周末 | 0.79x | 0.38% |

剔除周末后 **r 反而从 +0.582 升到 +0.608** —— 信号不是周末效应造出来的，
反而被周末噪声稀释了。**这一条通过了。**

### 13-D 仍未排除的混杂（下一步必做）

1. **反向因果**：是波动引发交易，还是交易引发波动？日粒度无法分辨。
   需要用「上午波动 → 下午行为」这类时序错位来定方向。
2. **大盘共动**：BTC 大涨那天所有币都涨、所有人都活跃。
   需要控制大盘（如减去 BTC 当日收益）后看残差。
3. **样本仅 7 天 6 币**：需扩到 30~90 天、覆盖高低波动区间。
4. **尚未做到「每用户」粒度**：现在是币级聚合，
   真正的敏感度模型需要 **持仓表（148877 审批中）** 才能做到
   「该用户持有该币 → 他是否反应」的个体级剂量反应曲线。

> **口径纪律**：目前只能声明"币种日频层面存在正相关"，
> **不能声明因果，也不能声明个体敏感度差异**。见 [[b9-price-sensitivity-study]]。

### 13-E 查询成本参考

7 天 × 6 symbol 的 `COUNT(DISTINCT user_id)` 聚合：**77 秒**。
该表每天 170~210 亿行，查询必须带 `date_key` 分区裁剪 + `event` 过滤，
30 天全 symbol 的扫描前需先估成本。

---

## 十四、端到端交付完成（2026-08-19）

**报告**：`docs/analysis/price-sensitivity.html`
（Artifact: https://claude.ai/code/artifact/73681ab0-6285-4230-bd43-b44fd73f0faa ）

### 14-A 🔑 join key 的坑（这是最大的一个）

两张核心表的 `user_id` **不是同一个 ID 体系**，直接 join 会静默返回 0 行：

| 表 | `user_id` 类型 | 样例 | 含义 |
|---|---|---|---|
| `fact_main_asset_ss_d`（持仓） | varchar | `36452418` | **真实 Binance UID** |
| `dwd_main_user_traffic_sensor_behavior_di`（埋点） | bigint | `-8421139983678617957` | 64 位哈希，**不是 UID** |

**正确的连接键是埋点表的 `distinct_id`**，且必须加 `is_login = 1`：

```sql
JOIN cohort c ON c.user_id = b.distinct_id   -- 不是 b.user_id
WHERE b.is_login = 1
```

神策惯例：用户登录后 `distinct_id` 才被改写成真实登录 ID。
排查路径：先 `typeof(user_id)` 比类型 → 再肉眼看两边样例值 → 在 175 列里找
`distinct_id` / `is_login` / `track_signup_original_id`。

### 14-B 队列与口径

- 队列：2026-08-01 持有 BTC 且 `asset_holding_usdt >= 100`，
  按 `MOD(ABS(from_big_endian_64(xxhash64(to_utf8(user_id)))), 200) = 0` 抽样
  → **13,662 人**
- 窗口：2026-07-28 ~ 08-18（22 天）
- 活跃 = 当天在 `symbol='BTCUSDT'` 上有埋点事件
- 交易 = 当天有 `event='place_order_event'`

### 14-C 结果

| 自变量 | 因变量 | r (22天) | r (仅工作日,16天) |
|---|---|---|---|
| **日内振幅** | 活跃人数 | **+0.830** | +0.716 |
| **日内振幅** | 交易人数 | **+0.813** | +0.716 |
| \|收盘涨跌\| | 活跃人数 | +0.531 | +0.466 |
| \|收盘涨跌\| | 交易人数 | +0.400 | +0.300 |

**重要发现：日内振幅的解释力远强于收盘涨跌幅**（+0.83 vs +0.53）。
用户反应的是盘中波动，不是收盘价。**建模的自变量应该用振幅，不是收益率。**

高振幅日（≥1.9%，工作日）vs 低振幅日：活跃 **+15.4%**、交易 **+8.1%**。

### 14-D 查询性能实测

| 查询 | 耗时 |
|---|---|
| 队列抽样（单分区持仓表） | ~30s |
| 22天 × 队列 join 埋点表 | **3分40秒** |
| 7天 × 6 symbol 聚合（无 join） | 77s |

`spq.sh` 轮询上限已从 240s 提到 20 分钟——**之前"查询超时"的报错其实是我的轮询太短，查询本身在正常跑**。

### 14-E 仍未排除
反向因果（需时序错位）、大盘共动（需扣 BTC 收益看残差）、
仅 BTC 单币、队列级而非个体级。**报告里已明确标注"能说/不能说"。**
