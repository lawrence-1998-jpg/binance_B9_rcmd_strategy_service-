---
name: verify-recall-by-url-not-keyword
description: "核对\"这条新闻抓到没有\"必须用原文URL精确回查，不能用译文关键词搜索"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-29T01:47:27.209Z
---

验证"某条新闻是否被系统召回/处理过"时，必须用**原文 URL**去数据库里精确匹配
（如 `JSON_SEARCH(sources,'one','%url片段%')`），不能靠"猜译文里的关键词"去
反查。

**Why:** 2026-07-29 在 B9 项目里，用中文关键词（"谷歌%""亚马逊%"）反查
LLM 处理后的库内记录，把 CNBC 的召回率报成 45%、FT 报成 36%。用户追问"剩下
一半去哪了"后倒查，发现真因是 LLM 把英文标题**意译**成中文——"Amazon, Meta
and Microsoft face skeptical investors" 被写成"AI支出挤压科技巨头现金流"，
字面根本不含任何公司名。关键词搜索因此系统性漏判，不是这些新闻真的没被抓到。
改用原文 URL 精确回查后，CNBC 真实值是 70%、FT 接近 100%——两次报告差了
25-64 个百分点，全部是测量方法的锅，不是系统的锅。

**How to apply:** 任何"验证内容是否被下游处理过"的场景，只要下游会做翻译/
改写/摘要（LLM 结构化、跨语言聚合、标题重写等），都不能靠关键词反查原文
是否命中——存在一个稳定的锚点（URL、原文 ID、指纹）时必须用锚点做精确匹配，
关键词法只能当补充，不能当结论。得出"漏了一半"这种结论前，先问自己："我是
在查真实缺失，还是在查我自己的搜索词没覆盖到？"

相关：[[verify-metric-matches-claim]]（同一类"测量口径想当然"的错误）、
[[keyword-blocklist-unreliable]]（关键词法本身脆弱这一点在别处也踩过）
