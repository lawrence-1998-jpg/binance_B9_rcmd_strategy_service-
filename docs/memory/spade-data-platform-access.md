---
name: spade-data-platform-access
description: 币安Spade大数据平台怎么进、怎么查表、怎么申请权限，以及三个会坑人的地方
metadata: 
  node_type: memory
  type: reference
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-08-18T19:33:24.678Z
---

**https://spade.toolsfdg.net** — 币安大数据平台（内网，**必须挂 VPN**）。
Okta SSO 静默登录。跑 SQL 用 BnQuery（Trino 默认 / Spark 可选）。

**程序化接入**：右上角头像 → Personal Token → 建 token →
`POST https://bdp-bff.toolsfdg.net/api/personal-token/exchange` 换短期 JWT →
`Authorization: Bearer <JWT>` 调 `/api/proxy/...`。token 存 `~/.b9/spade_token`(600)。

**申请表权限**：直达
`https://spade.toolsfdg.net/datamap/detail?name=<库.表>&assetType=hive_table&apply=true`
Duration **默认 7 天，必须手动改 60 天**；Request Reason 必填。

**Why:** 这三个坑各浪费过我一轮：

1. **`information_schema` 无权限** —— `SHOW TABLES` / 查元数据表一律 Access Denied。
   摸表只能用 Data Map 搜索（`/datamap/search?query=xxx`），不能用 SQL 遍历。
2. **Data Map 搜索结果的表名被高亮拆成多个 `<span>`**（`bnb_tdm.`+`user_profile`+`_sensor`），
   按叶子节点抽取会得到 **0 条**，看起来像"这类表不存在"。必须取最小完整容器的 textContent。
   我差点据此报告"没有这类表"，是肉眼看截图才发现满屏都是结果（见 [[human-eyeball-test-is-my-floor]]）。
3. **提交申请的成功提示会一闪而过** —— 必须去
   `/security/access-center/my-request` 的 In Progress 核对。
   注意 `My Access` 是"已获批"，批之前是空的，别误判成申请失败。

**How to apply:** 摸表走 Data Map + DOM 最小容器抽取；抽取返回 0 先看屏幕再下结论；
任何提交动作完成后去列表页核实（见 [[verify-write-not-just-return-code]]）。
数仓命名：`bnb_ods`原始 / `bnb_dwd`明细事实 / `bnb_dws`汇总 / `bnb_dwm`指标 /
`bnb_dwa`应用 / `bnb_tdm`用户画像标签。
