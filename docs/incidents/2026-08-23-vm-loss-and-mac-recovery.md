# 事故：GCP VM 整机失联与 Mac 应急恢复（2026-08-23）

> 状态：**服务已在 Mac 上应急恢复**，公网可访问。VM 判定为不可恢复（Manus 代管资源疑被回收）。
> 本文既是事故记录，也是**重建 runbook**——照第五节任何人可在一台新机器上完整复活本服务。

## 一、时间线

| 时间 | 事件 |
|---|---|
| 08-20 白天 | VM 一切正常（当天还实测过 API 与 cron） |
| 08-20 晚 ~ 08-23 | VM 失联（确切时刻不明，期间无人访问） |
| 08-23 03:30 | 用户报告 HTTPS 域名打不开；排查发现不是隧道死，是**整机不可达**：SSH 22 超时、HTTP 8080 超时、ping 100% 丢包 |
| 08-23 03:40 | 确认本机无 gcloud 凭证，无法远程拉起；用户确认该 VM 由 **Manus 平台代管**，非自有 GCP 账号 |
| 08-23 03:45~04:05 | Mac 应急重建（详见第五节），公网恢复 |

## 二、根因

VM `34.138.247.158` 是 Manus（AI agent 平台）当初代为创建的资源，不在我们自己的
GCP 账号下。Manus 的环境有生命周期，长期不活跃会被平台回收。**最可能的根因：平台回收，
整机连同磁盘销毁。** 我们既无控制台权限确认，也无从申诉。

## 三、损失清单

| 项 | 状态 |
|---|---|
| 代码 | ✅ 零损失（GitHub 全量） |
| 事件数据 2026-07-26 前 | ✅ 本地备份救回（1,057 条） |
| **事件数据 07-26 → 08-22（约 4.2 万条增量）** | ❌ **大概率永久丢失**——每日备份存在 VM 自己磁盘上，机器没了备份也没了 |
| 定时任务/系统配置 | ✅ 全部在 repo（systemd unit、crontab 记录在 docs） |
| 密钥 | ✅ 本机 `config/.env` 与 `~/.b9/` 均在（密钥从不进库） |

## 四、结构性教训（三条，都已付过学费）

1. **备份必须离开产生它的机器。** 每日 mysqldump 很勤快，但全落在同一块盘上——机器级故障
   时形同虚设。修复：备份任务必须加一步推到异地（GitHub private / S3 / 本地 Mac 拉取）。
2. **别把生产押在代管/临时资源上。** Manus VM、trycloudflare 域名，两者都是"临时的东西
   被当成了永久的用"。已经连续付出两次代价（域名死、整机死）。
3. **单点清单要维护。** 本次事故前的单点：VM（无异地备份）、Mac（enrich worker）、
   quick tunnel 域名。事故后单点反而集中到了 Mac——见第六节风险。

## 五、重建 Runbook（在任何新机器上复活服务）

前提：macOS/Linux + Homebrew 或 apt + 本 repo + 密钥文件（见 README「密钥清单」）。
以下即 08-23 在 Mac 上实际执行并验证过的步骤：

```bash
# 1. 基础设施
brew install mysql cloudflared python@3.12        # apt: mysql-server cloudflared python3.12
brew services start mysql

# 2. 建库 + 恢复最近备份 + 跑全部 migrations（22 个，幂等）
mysql -uroot -e "CREATE DATABASE IF NOT EXISTS crypto_news CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
gunzip -c backups/news_events_full_*.sql.gz | mysql -uroot crypto_news
for f in config/migrations/*.sql; do mysql -uroot crypto_news < "$f"; done
# root 密码需与 config/.env 的 MYSQL_PASSWORD 一致：
mysql -uroot -e "ALTER USER 'root'@'localhost' IDENTIFIED BY '<MYSQL_PASSWORD>'"

# 3. Python 环境（必须 3.10+，3.9 会在 x_search.py 的 `str | None` 上炸）
python3.12 -m venv .venv-mac && ./.venv-mac/bin/pip install -r requirements.txt

# 4. 起 API（8080）
nohup ./.venv-mac/bin/python api/server.py > /tmp/b9_api.log 2>&1 &
curl -s "http://127.0.0.1:8080/api/news?limit=1&max_age_days=0&token=<WEB_TOKEN>"
#   ⚠️ 数据老于 5 天时必须带 max_age_days=0，否则返回空——是新鲜度闸不是故障

# 5. 公网隧道（临时方案；域名重启即变）
nohup cloudflared tunnel --url http://127.0.0.1:8080 > /tmp/cf_tunnel.log 2>&1 &
grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf_tunnel.log | head -1

# 6. 恢复生产（RSS 抓取 + enrich worker）
B9_PIPELINE_BATCH=300 nohup ./.venv-mac/bin/python run_pipeline.py > /tmp/b9_pipeline.log 2>&1 &
B9_API_BASE=http://127.0.0.1:8080 B9_API_TOKEN=<API_TOKEN_LAWRENCE> \
  nohup ./.venv-mac/bin/python scripts/local_enrich_worker.py > /tmp/b9_worker.log 2>&1 &
```

### 重建时的已知坑（都踩过）
- **8080 被占**：旧进程残留会让新 server 静默起不来，`lsof -iTCP:8080` 先查
- **worker 401**：`B9_API_TOKEN` 必须用 `.env` 里的有效 token（如 API_TOKEN_LAWRENCE）
- **worker 指错端**：默认连老 VM IP，必须传 `B9_API_BASE=http://127.0.0.1:8080`
- **LLM 网关**：`litellm.devfdg.net` 是公司内网域名，需 VPN 对应 zone；DNS 解析失败
  说明 VPN 没覆盖 devfdg zone（toolsfdg zone 通不代表它通）

## 六、当前架构与遗留风险（2026-08-23）

```
[Mac] MySQL 9.7 + Flask API :8080 + RSS 抓取 + enrich worker
  └── cloudflared quick tunnel → https://final-terms-beatles-waiting.trycloudflare.com
```

| 风险 | 等级 | 备注 |
|---|---|---|
| **Mac 成唯一单点**：合盖/重启即全停 | 🔴 | 历史三次停摆的根因如今变成唯一服务器 |
| 隧道域名随进程重启改变 | 🟡 | 老问题，固定域名方案见 OPEN_QUESTIONS #8 |
| LLM 网关不通 → 新事件生产暂停 | 🟡 | RSS 队列在安全积压（defer-not-consume），通了自动追 |
| 27 天数据缺口 | 已定损 | 无法恢复，前端叙事需注明 |

**出路（等用户拍板）**：公司内网 EC2（申请流程已调研，见 WORKLOG）/ Oracle 免费层 / 付费 VPS。
