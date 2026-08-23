# Spade 取数脚本

从命令行直接查币安大数据平台（Spade）的 Hive 表，不用开浏览器。

## 前置

1. **挂 VPN**（Spade 是内网站点 `*.toolsfdg.net`）
2. 在 Spade 右上角头像 → **Personal Token** 建一个 token
3. 凭据落本机（**不入库**）：

```bash
mkdir -p ~/.b9 && chmod 700 ~/.b9
printf '<你的 Personal Token>' > ~/.b9/spade_token && chmod 600 ~/.b9/spade_token
printf '<你的 Okta UID>'       > ~/.b9/okta_uid    && chmod 600 ~/.b9/okta_uid
```

> Okta UID 形如 `00u...`，在 Spade 任一查询请求的 `userId` 字段里能看到。
> 也可用环境变量 `B9_OKTA_UID` 代替文件。

## 用法

```bash
# TSV 输出（首行列名）
./spq.sh "SELECT COUNT(*) AS c FROM hive.bnb_dwd.fact_main_user_behavior_hr_d WHERE date_key=20260818"

# JSON 输出
./spq.sh "SELECT ..." 1000 -j

# 长 SQL 从 stdin
echo "SELECT ..." | ./spq.sh - 5000
```

失败会**退出码 1 + stderr 打印真实原因**（如 `Unauthorized :: [database]=x, [table]=y`），
不会把空结果伪装成成功。

## 注意

- **必须带分区过滤**。神策表每天 170~210 亿条，裸扫会跑很久甚至打爆集群。
- `actual_event_time` 是 timestamp 类型，比较要用 `TIMESTAMP '2026-08-18 12:00:00'` 字面量，
  直接给字符串报 `Cannot apply operator: timestamp(3) <= varchar`。
- 无 `information_schema` 权限，摸表用平台 Data Map / 数据专辑，不能 `SHOW TABLES`。
- JWT 缓存在 `~/.b9/.spade_jwt`，12h 有效，超过 11h 自动刷新。

坑的完整清单见 [`../../docs/memory/spade-data-platform-access.md`](../../docs/memory/spade-data-platform-access.md)。
