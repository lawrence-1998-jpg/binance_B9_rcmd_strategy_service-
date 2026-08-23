# 经验教训档案（49 篇）

这些不是文档，是**踩过的坑**。每篇一个教训，绝大多数来自真实事故——
写下来是为了不再犯第二次。原始来源是 Claude Code 的长期记忆目录，此处为快照备份。

## 怎么读

按主题分组如下。**如果只读三篇**，读加粗的那三篇——它们是被违反次数最多、
代价最大的。

### 交付纪律（最贵的教训都在这里）
- **[完工标准 = 用户界面上验证过](definition-of-done-user-surface.md)** — 六次事故换来：
  落表≠交付、部署后浏览器过全站、界面正常≠数据对
- **[人眼/一搜能看出的问题是我的底线](human-eyeball-test-is-my-floor.md)** — 一天被抓三次：
  QA 全绿≠没问题，交付前必须肉眼扫首屏
- **[报数字前先对齐口径](verify-metric-matches-claim.md)** — 把"SQL 取到 400 行"当成
  "缓存可用 400 条"报成果，实际可用 0 条
- [交付前按角色走完整旅程](walk-each-role-journey-before-ship.md) — 机制测试 13 项全绿，
  仍漏了"审批人看不到申请内容"
- [控件加了监听 ≠ 它能用](control-shipped-but-never-fired.md) — 三种静默失效
- [加列后务必验证写库真的成功](verify-write-not-just-return-code.md) — 占位符少一个，
  全部写入静默失败，只打 warning 返回 0
- [文件存在 ≠ agent 完成](agent-file-exists-not-agent-done.md) — 曾把中途写入态当终稿发出

### 数据正确性
- [缺失数据绝不填默认值](never-default-missing-data.md) — 无日期当成"现在"，2024 年新闻
  顶着今天日期上前端
- [聚合数字会掩盖首屏](aggregate-number-hides-first-screen.md) — 报"覆盖率涨 18 倍"
  而首屏 0/10 有标签
- [聚合器时间戳不可信](aggregator-timestamps-untrusted.md)
- [验证召回用 URL 不用关键词](verify-recall-by-url-not-keyword.md)
- [改公式必查存量版本一致性](verify-formula-version-consistency.md) — 曾 87% 的分是旧公式
- [审计结论写报告前要重新核实](stale-audit-finding-reverify-before-report.md)

### 规则 vs LLM（同一个教训的三次复现）
- [语义判断该交给 LLM 而非规则表](semantic-judgment-needs-llm-not-rules.md) — 补到第三轮
  词表就该停手；实测规则误判 60%，LLM 12/12
- [关键词黑名单靠不住](keyword-blocklist-unreliable.md)
- [关键词正则判语义有结构性天花板](punch-regex-structural-ceiling.md)

### 架构与成本
- [做成本开关先收敛付费闸口](cost-gate-needs-single-chokepoint.md) — 9 个付费点散在 4 处
  就不可能加总开关
- [全库改写三护栏](mass-rewrite-guardrails.md) — 预演 + 快照 + 差异门 + 互斥锁
- [批量回填的三重坑](backfill-three-traps.md)
- [实验工具必须与生产同公式同取数轴](lab-prod-must-share-formula.md)
- [功能优化必须覆盖全部消费面](feature-must-cover-all-surfaces.md)
- [配置必须渲染进 prompt](config-must-render-into-prompt.md) — 两处手写必然漂移且不报错
- [加列会打破按 * 复制的备份脚本](schema-drift-breaks-star-select.md)
- [导出副本会盖住线上的缺陷](export-copy-can-mask-defects.md)

### 运维事故
- [定时任务装完必须验证真跑过](scheduled-job-never-ran.md) — launchd 读不了 ~/Desktop，
  软链永远 EPERM，"按设计延后"与"下游死了"日志长得一样
- [并行 agent 会打爆 SSH 连接槽位](parallel-agents-ssh-limit.md)
- [Flask 直接跑文件时 sys.path 不含项目根](flask-blueprint-syspath-gotcha.md)
- [B9 每个 blueprint 各自复制鉴权表](b9-blueprint-auth-duplication.md) — 改 token 五处一起改

### 项目上下文（B9 特有）
- [项目形态与分期](b9-project-shape.md) · [运行环境在云主机](b9-vm-access.md)
- [去重重构与阈值标定](b9-dedup-gap.md) · [X API 按推文条数计费](b9-x-api-capacity.md)
- [评测 Agent 系统的设计取舍](b9-eval-agent-system.md) · [策略已上线 + 指标体系](b9-strategy-live-metrics.md)
- [扩展到全球市场新闻](b9-market-expansion.md) · [本地 Claude 预处理桥](b9-enrich-bridge.md)
- [LiteLLM 网关现状](b9-litellm-gateway-blocked.md) · [成本统计不用较真](b9-estimates-good-enough.md)
- **[新课题：用户价格敏感度建模](b9-price-sensitivity-study.md)**
- [Spade 大数据平台怎么用](spade-data-platform-access.md)

### 协作偏好（用户明确表达过的）
- [不要主动搞安全加固](no-security-hardening.md) · [能并行就并行](parallelize-when-possible.md)
- [能用 Claude 做的坚决不调 OpenAI API](prefer-claude-over-openai-api.md)
- [重活优先用公司 API 省 token](prefer-company-api-for-heavy-compute.md)
- [模型切换：需要 Opus 时要主动说](model-switch-preference.md)
- [任务跟踪与记录纪律](task-tracking-discipline.md) · [短需求也必须落 TODO 和留痕](short-requests-need-tracking.md)
- [跨项目 playbook（B9 复盘）](project-playbook-retrospective.md) — 12 条降本增效 checklist
