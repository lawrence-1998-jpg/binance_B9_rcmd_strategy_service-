---
name: b9-litellm-gateway-blocked
description: B9服务的LiteLLM网关使用现状——VM连不通(内网专用)，Mac挂公司VPN能连通，本地enrich worker已切过去且撞到30req/min硬限
metadata: 
  node_type: memory
  type: project
  originSessionId: 9716f1b0-9634-4604-a10f-f29599cbc285
  modified: 2026-07-28T11:22:52.857Z
---

2026-07-28 Lawrence 申请到公司 LiteLLM 网关 key（`https://litellm.devfdg.net/v1`，
39个模型可选，$1000额度，2026-08-03到期）。分两步落地，现状如下：

## VM 侧（生产 pipeline）：连不通，已回退，不要重复尝试

网关是 Binance 内网专用服务：域名解析到 172.21.x.x 私网 IP（内部 ELB
`internal-k8s-backend-litellmi-...`），只有公司内网/VPN 上的机器能连通。B9 生产
pipeline 跑在 GCP 公网 VM 上，DNS 都解析不出来，不是防火墙规则、无法绕过。除非
网关方对这个 VM 网段开白名单，或把 pipeline 迁到能连内网的机器上跑，否则无法
使用。生产环境仍在用个人 OpenAI 账号（`config/.env` 里网关 key 是注释状态，
随时可用）。

`claude-opus-4-8`（网关上唯一非bedrock前缀的Claude）不支持 strict json
schema：实测报错 `output_config.format: Extra inputs are not permitted`。B9
全部 LLM 调用点都依赖这个模式，换用 opus-4-8 需要先把调用点改造成
tool-calling 形式的结构化输出，是独立的工程改动。gpt-5.4/5.4-mini/5.6三个
变体、embeddings（text-embedding-3-small, dimensions=256）都验证过兼容。

## Mac 侧（本地 enrich worker）：能连通，已切换生效

Lawrence 的 Mac 挂公司 VPN，能连通同一个网关。`scripts/local_enrich_worker.py`
已从本地 `claude -p` CLI 改成直接调网关（模型 gpt-5.4，strict json schema），
不再吃 Claude Max 订阅额度，费用走网关的 1000 美元额度。

**实测撞到网关对这把 key 的硬限：30 请求/分钟**（429 响应体里"Current limit:
30"）。已加线程安全滑动窗口限流器（`GATEWAY_RPM=25`，留 5 个余量），429 不在
同轮重试、直接放弃留给下次唤醒（15分钟后），按 25/min 吞吐上限 375条/次唤醒
远超 BATCH_SIZE=100，不构成数据丢失。任何未来再接这个网关的调用（不管是
Mac 还是别的内网机器）都要考虑到这个 30/min 的限速，不要素朴地并发爆发式调用。

详见 WORKLOG #59、#60，[[b9-project-shape]]。
