#!/usr/bin/env python3
"""公司 LLM 网关 key 管理 —— 跑在 Lawrence 的 Mac 上（ADR-002 A2）。

## 为什么 key 存在 Mac 而不是 VM

公司网关是**内网专用地址**，VM 连不通，只有挂着公司 VPN 的这台 Mac 用得上。
把一个只有 Mac 能用的秘密复制进"挂着公网隧道的 VM"，纯粹白扩大暴露面、零收益。
所以：**密钥留在本机 ~/.b9/credentials.json（600），VM 只存元数据**
（还剩几天到期、上次成功调用、连续失败几次），用于监控看板与到期预警。

## 为什么要有这个命令

公司 key 每 7 天轮换一次。轮换如果意味着"改代码 → 部署 → 重启"，那它就会
拖延、会漏改、会在深夜救火时出错。这个命令把轮换压缩成一行，且**落盘前先拿
新 key 打一次真实网关调用**——填错了当场就知道，而不是等下一轮 pipeline
静默失败之后才发现（本项目已经吃过太多次"配置错了但不报错"的亏）。

## 用法

    python3 scripts/b9key.py add --key sk-xxx --expires 2026-08-09   # 加新 key 并设为当前
    python3 scripts/b9key.py list                                     # 看都有哪些、还剩几天
    python3 scripts/b9key.py test                                     # 测当前 key 是否还活着
    python3 scripts/b9key.py sync                                     # 把元数据同步给 VM 看板

worker（scripts/local_enrich_worker.py）启动时读同一个文件，所以换完 key
下一次唤醒自动生效，不用重启任何东西。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

CRED_DIR = Path.home() / ".b9"
CRED_FILE = CRED_DIR / "credentials.json"
DEFAULT_BASE = "https://litellm.devfdg.net/v1"
DEFAULT_MODEL = "gpt-5.4"

# VM 侧元数据同步（只发元数据，永不发 key）
API_BASE = os.environ.get("B9_API_BASE", "http://34.138.247.158:8080")
API_TOKEN = os.environ.get("B9_API_TOKEN", "***REMOVED***")

WARN_DAYS = 2      # 剩余天数 ≤ 这个值就告警


# ── 存储 ─────────────────────────────────────────────────────────────

def _load() -> dict:
    if not CRED_FILE.exists():
        return {"active": None, "keys": {}}
    try:
        return json.loads(CRED_FILE.read_text())
    except (ValueError, OSError) as e:
        print(f"⚠️  凭据文件损坏（{e}）。为避免覆盖掉可能还有用的内容，"
              f"这里不自动重建——请人工检查 {CRED_FILE}")
        sys.exit(2)


def _save(data: dict) -> None:
    CRED_DIR.mkdir(mode=0o700, exist_ok=True)
    tmp = CRED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.chmod(0o600)          # 先改权限再改名，避免出现"短暂可读"的窗口
    tmp.replace(CRED_FILE)


def active_credential() -> dict | None:
    """给 worker 用：返回当前生效的凭据（含 key）。过期的一律不返回。

    worker 拿不到就应该停下来等，而不是回落到别的付费通道——
    "断供时宁可不跑也不花个人账号的钱"是本次架构升级的核心约束。
    """
    data = _load()
    name = data.get("active")
    if not name:
        return None
    cred = (data.get("keys") or {}).get(name)
    if not cred:
        return None
    exp = cred.get("expires_at")
    if exp and date.fromisoformat(exp) < date.today():
        return None
    return dict(cred, name=name)


# ── 网关连通性校验 ───────────────────────────────────────────────────

def probe(key: str, base_url: str = DEFAULT_BASE, model: str = DEFAULT_MODEL) -> tuple:
    """拿 key 打一次真实调用。返回 (是否可用, 说明)。

    刻意用最小请求（max_tokens=5）——目的是验证凭据本身，不是压测。
    落盘前必过这一关：填错 key 当场报错，好过一周后发现缓存一直没更新。
    """
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps({"model": model,
                         "messages": [{"role": "user", "content": "ping"}],
                         "max_tokens": 5}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
            got = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, f"HTTP {resp.status}，模型回了 {got!r}"
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode(errors="replace")
        return False, f"HTTP {e.code}: {detail}"
    except Exception as e:
        # 连不通通常不是 key 的问题，而是 VPN 没挂——这个区分很重要，
        # 否则会把"忘了连 VPN"误判成"公司把 key 停了"，白白去找同事要新 key。
        return False, f"连不通（{e}）。先确认公司 VPN 是否已连接。"


# ── 命令 ─────────────────────────────────────────────────────────────

def cmd_add(args) -> int:
    key = args.key.strip()
    if not key:
        print("✗ key 不能为空")
        return 1

    print(f"→ 先验证这把 key 能不能真的调通网关（{args.base}）...")
    ok, detail = probe(key, args.base, args.model)
    if not ok:
        print(f"✗ 验证失败：{detail}")
        print("  没有落盘。修好再试——宁可现在报错，也不要让一把坏 key 悄悄躺进配置里。")
        return 1
    print(f"✓ 验证通过：{detail}")

    data = _load()
    name = args.name or f"company-{args.expires or date.today().isoformat()}"
    # 旧的当前 key 标记为 replaced，保留在文件里备查（万一新 key 有问题要回退）
    if data.get("active") and data["active"] != name:
        old = data["keys"].get(data["active"])
        if old:
            old["status"] = "replaced"
            old["replaced_at"] = datetime.now().isoformat(timespec="seconds")

    data.setdefault("keys", {})[name] = {
        "key": key,
        "base_url": args.base,
        "model": args.model,
        "expires_at": args.expires,
        "added_at": datetime.now().isoformat(timespec="seconds"),
        "status": "active",
    }
    data["active"] = name
    _save(data)
    print(f"✓ 已保存并设为当前：{name}"
          + (f"（{args.expires} 到期）" if args.expires else "（未设到期日）"))
    print(f"  文件：{CRED_FILE}（权限 600）")
    print("  worker 下次唤醒（≤15 分钟）自动生效，无需重启任何服务。")
    _sync_meta(quiet=True)
    return 0


def cmd_list(args) -> int:
    data = _load()
    keys = data.get("keys") or {}
    if not keys:
        print("还没有任何 key。用 b9key.py add --key sk-xxx --expires YYYY-MM-DD 添加。")
        return 0
    print(f"{'当前':^4} {'名称':<24} {'状态':<10} {'到期':<12} {'剩余'}")
    print("-" * 68)
    for name, c in sorted(keys.items()):
        cur = "→" if name == data.get("active") else ""
        exp = c.get("expires_at") or "-"
        if c.get("expires_at"):
            left = (date.fromisoformat(c["expires_at"]) - date.today()).days
            left_s = f"{left} 天" if left >= 0 else f"已过期 {-left} 天"
            if 0 <= left <= WARN_DAYS:
                left_s += "  ⚠️ 该换了"
        else:
            left_s = "-"
        print(f"{cur:^4} {name:<24} {c.get('status','?'):<10} {exp:<12} {left_s}")
    return 0


def cmd_test(args) -> int:
    cred = active_credential()
    if not cred:
        data = _load()
        if data.get("active"):
            print(f"✗ 当前 key「{data['active']}」已过期，worker 会停止处理并把条目留在队列里。")
            print("  这是设计内行为（断供不花个人账号的钱）。给新 key 后会自动回补。")
        else:
            print("✗ 没有设置当前 key。")
        return 1
    ok, detail = probe(cred["key"], cred.get("base_url", DEFAULT_BASE),
                       cred.get("model", DEFAULT_MODEL))
    print(("✓ " if ok else "✗ ") + f"{cred['name']}：{detail}")
    _sync_meta(quiet=True, ok=ok, error=None if ok else detail)
    return 0 if ok else 1


def _sync_meta(quiet: bool = False, ok: bool | None = None,
               error: str | None = None) -> None:
    """把**元数据**推给 VM（永远不含 key 本身），供看板与到期预警使用。"""
    data = _load()
    name = data.get("active")
    if not name:
        return
    cred = data["keys"][name]
    payload = {
        "name": name,
        "provider": "litellm-gateway",
        "status": cred.get("status", "active"),
        "expires_at": cred.get("expires_at"),
        "ok": ok,
        "error": (error or "")[:500],
    }
    req = urllib.request.Request(
        f"{API_BASE}/api/enrich/credential-meta?token={API_TOKEN}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if not quiet:
                print(f"✓ 元数据已同步到 VM（HTTP {resp.status}）")
    except Exception as e:
        # 同步失败不该让轮换失败——key 已经在本机生效了，看板晚一点更新无所谓。
        if not quiet:
            print(f"⚠️  元数据同步失败（{e}）。key 本身已生效，仅看板不同步。")


def cmd_sync(args) -> int:
    _sync_meta(quiet=False)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="B9 公司网关 key 管理（本机存储）")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="添加新 key 并设为当前（落盘前先验证）")
    a.add_argument("--key", required=True)
    a.add_argument("--expires", help="到期日 YYYY-MM-DD（公司 key 一般 7 天）")
    a.add_argument("--name", help="别名，默认按到期日生成")
    a.add_argument("--base", default=DEFAULT_BASE)
    a.add_argument("--model", default=DEFAULT_MODEL)
    a.set_defaults(func=cmd_add)

    sub.add_parser("list", help="列出所有 key 与剩余天数").set_defaults(func=cmd_list)
    sub.add_parser("test", help="测当前 key 是否还能调通").set_defaults(func=cmd_test)
    sub.add_parser("sync", help="把元数据同步到 VM 看板").set_defaults(func=cmd_sync)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
