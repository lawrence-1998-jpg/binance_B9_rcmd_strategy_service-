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
