# 协作上下文（Context Memory）

这些是 AI 助手在开发过程中沉淀的**项目上下文记忆**，同步到仓库供协同者使用。
内容是"从代码里读不出来的东西"——踩过的坑、实测标定的参数依据、用户明确的
偏好约定。

与其它文档的分工：

| 文档 | 讲什么 |
|---|---|
| `docs/PROJECT_PLAN.md` | 项目要做什么、分几步、为什么 |
| `docs/WORKLOG.md` | 每项需求跟进到哪了 |
| `docs/background.md` | 产品背景与推荐策略设计 |
| **`docs/context/`（本目录）** | **踩坑记录、参数标定依据、协作约定** |

## 索引

| 文件 | 一句话 |
|---|---|
| `b9-project-shape.md` | 项目整体形态：两个推荐场景 + 五步走 |
| `b9-vm-access.md` | 代码跑在 GCP VM 上，怎么连、常用检查命令 |
| `b9-dedup-gap.md` | 去重曾有 48.7% 冗余；**语义阈值文档写 0.65 是错的，实测该取 0.82** |
| `b9-x-api-capacity.md` | X API 的 search/recent 端点 450 req/15min，此前完全闲置 |
| `parallel-agents-ssh-limit.md` | 并行 agent 同时 SSH 会打爆 sshd 连接槽位，已配 ControlMaster |
| `no-security-hardening.md` | 用户明确要求不主动改动服务器安全配置 |

> 注：这些文件由 AI 助手维护，代码变更时会同步更新。如果你手工改了其中内容，
> 请一并更新 `MEMORY.md` 索引里的一句话描述。
