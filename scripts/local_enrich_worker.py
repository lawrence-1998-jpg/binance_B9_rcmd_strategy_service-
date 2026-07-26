#!/usr/bin/env python3
"""
本地 Claude 预处理 worker —— 跑在 Lawrence 的 Mac 上，不是 VM 上。

做什么：闲时从 VM 领取 staging 里还没处理的新闻条目，用本地 `claude` CLI
（Claude Max 订阅，不产生 OpenAI API 费用）按 VM 下发的同一份 prompt 做
结构化，结果回传 VM 的 llm_enrich_cache 表。VM 的 pipeline 跑到 LLM 环节时
先查这张表，命中的条目零成本。

为什么是 pull 模式：这台 Mac 是工作机，不保证开机、没有公网入口。所以只能
Mac 主动拉（HTTP 出站），VM 永远不依赖 Mac 在线——Mac 关机的唯一后果是
缓存 miss，pipeline 照常全量走 OpenAI，效果零损失，只是没省到钱。

调度：launchd 每 30 分钟唤醒一次（config/com.lawrence.b9-enrich-worker.plist）。
单次最多处理 BATCH_SIZE 条；staging 每天新增约 900 条，48 次唤醒 × 40 条/次
的吞吐上限远超需求，Mac 每天在线几个小时就足够清空积压。

纯标准库实现（urllib/subprocess），Mac 上不需要 pip install 任何东西。
兼容到 python3.8（Mac 系统自带 python3 往往不是 3.10+，`X | None` 注解会在
运行时求值爆掉，用 future import 把注解全部字符串化绕开）。
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

# ── 配置 ─────────────────────────────────────────────────────────────
API_BASE = os.environ.get("B9_API_BASE", "http://34.138.247.158:8080")
API_TOKEN = os.environ.get("B9_API_TOKEN", "***REMOVED***")
BATCH_SIZE = int(os.environ.get("B9_BATCH", "40"))
CONCURRENCY = int(os.environ.get("B9_CONCURRENCY", "4"))
CLAUDE_MODEL = os.environ.get("B9_CLAUDE_MODEL", "sonnet")
CLAUDE_TIMEOUT_S = 240
LOCK_FILE = "/tmp/b9-enrich-worker.lock"
LOCK_STALE_S = 2 * 3600

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("enrich-worker")


class Progress:
    """并发批次的实时进度显示。

    交互式跑（stdout 是 TTY）时画进度条 + 每条完成一行明细；被 launchd 拉起
    写日志文件时自动退化成纯行式输出（进度条的 \\r 覆写在日志里是乱码）。
    线程安全：4 个 worker 线程会并发调用 done()。
    """

    BAR_WIDTH = 24

    def __init__(self, total: int):
        self.total = total
        self.done_n = 0
        self.ok = 0
        self.fail = 0
        self.t0 = time.time()
        self._lock = threading.Lock()
        self.tty = sys.stdout.isatty()

    @staticmethod
    def _fmt(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s:02d}s" if m else f"{s}s"

    def done(self, ok: bool, elapsed: float, tier: str = "", title: str = "") -> None:
        with self._lock:
            self.done_n += 1
            self.ok += 1 if ok else 0
            self.fail += 0 if ok else 1
            n, total = self.done_n, self.total
            spent = time.time() - self.t0
            eta = (spent / n) * (total - n) if n else 0

            mark = "✓" if ok else "✗"
            line = (f"[{n:>3}/{total}] {mark} {elapsed:5.1f}s  "
                    f"{(tier or '-'):1}  {title[:42]}")
            if self.tty:
                # 先清掉进度条那一行，打印明细，再把进度条重画到底部
                sys.stdout.write("\r\033[K" + line + "\n")
                filled = int(self.BAR_WIDTH * n / total) if total else 0
                bar = "█" * filled + "░" * (self.BAR_WIDTH - filled)
                sys.stdout.write(
                    f"\033[K▕{bar}▏ {n}/{total} {100 * n // total:>3}%  "
                    f"已用 {self._fmt(spent)}  预计还需 {self._fmt(eta)}  "
                    f"成功 {self.ok} 失败 {self.fail}")
                sys.stdout.flush()
            else:
                log.info(line)

    def finish(self) -> None:
        if self.tty:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()


def find_claude() -> str:
    """launchd 环境的 PATH 极简，得自己找 claude 可执行文件。"""
    candidates = [
        shutil.which("claude"),
        os.path.expanduser("~/.claude/local/claude"),
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
        os.path.expanduser("~/.local/bin/claude"),
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise FileNotFoundError("claude CLI not found — worker cannot run")


def api(path: str, payload: dict | None = None) -> dict:
    url = f"{API_BASE}{path}{'&' if '?' in path else '?'}token={API_TOKEN}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def extract_json(text: str) -> dict | None:
    """从模型输出里抠出第一个完整 JSON 对象（容忍代码围栏/前后闲话）。"""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(),
                  flags=re.MULTILINE)
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    return None
    return None


def enrich_with_claude(claude_bin: str, spec: dict, item: dict) -> dict | None:
    """单条结构化。失败重试一次，再失败返回 None（该条自然落回 OpenAI，无害）。"""
    user_content = (
        f"Source: {item.get('source', '')}\n"
        f"Title: {item.get('title', '')}\n"
        f"Summary: {(item.get('summary') or '')[:600]}\n"
        f"URL: {item.get('url', '')}\n"
        f"Published: {item.get('published_at', '')}"
    )
    prompt = (
        spec["system_prompt"]
        + "\n\n## OUTPUT FORMAT (STRICT)\n"
        + "Respond with ONE JSON object only — no prose, no markdown fences. "
        + "It MUST contain ALL of these keys with correct types: "
        + ", ".join(spec["required_keys"])
        + ". Follow this JSON schema exactly:\n"
        + json.dumps(spec["schema"], ensure_ascii=False)
        + "\n\n## INPUT\n" + user_content
    )
    for attempt in range(2):
        try:
            proc = subprocess.run(
                [claude_bin, "-p", prompt,
                 "--output-format", "json", "--model", CLAUDE_MODEL],
                capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_S,
                cwd=os.path.expanduser("~"),  # 中性目录，避免带入任何项目上下文
            )
            if proc.returncode != 0:
                log.warning(f"claude exit {proc.returncode}: {proc.stderr[:200]}")
                continue
            wrapper = json.loads(proc.stdout)
            enriched = extract_json(wrapper.get("result", ""))
            if enriched is None:
                log.warning(f"unparseable output (attempt {attempt + 1}) "
                            f"for {item.get('url', '')[:60]}")
                continue
            missing = set(spec["required_keys"]) - set(enriched.keys())
            if missing:
                log.warning(f"missing keys {sorted(missing)[:5]} "
                            f"for {item.get('url', '')[:60]}")
                continue
            if enriched.get("event_tier") not in ("S", "A", "B", "C", "D"):
                continue
            return enriched
        except subprocess.TimeoutExpired:
            log.warning(f"claude timeout for {item.get('url', '')[:60]}")
        except (ValueError, OSError) as e:
            log.warning(f"claude call failed: {e}")
    return None


def acquire_lock() -> bool:
    """防止上一轮还没跑完就被 launchd 再次唤醒叠加。"""
    if os.path.exists(LOCK_FILE):
        if time.time() - os.path.getmtime(LOCK_FILE) < LOCK_STALE_S:
            log.info("previous run still active (lock fresh), skipping this wake")
            return False
        log.warning("stale lock found, taking over")
        os.unlink(LOCK_FILE)
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def main() -> int:
    if not acquire_lock():
        return 0
    try:
        claude_bin = find_claude()
        spec = api("/api/enrich/prompt")
        pending = api(f"/api/enrich/pending?limit={BATCH_SIZE}")
        items = pending.get("items") or []
        if not items:
            log.info("no pending items — nothing to do")
            return 0
        if pending.get("prompt_hash") != spec.get("prompt_hash"):
            log.warning("prompt changed between calls, aborting this wake")
            return 0
        log.info(f"processing {len(items)} items "
                 f"(prompt {spec['prompt_hash']}, model {CLAUDE_MODEL}, "
                 f"concurrency {CONCURRENCY})")

        t0 = time.time()
        results = []
        progress = Progress(len(items))

        def run_one(it):
            """包一层只为测单条耗时并驱动进度显示。"""
            started = time.time()
            enriched = enrich_with_claude(claude_bin, spec, it)
            progress.done(
                ok=enriched is not None,
                elapsed=time.time() - started,
                tier=(enriched or {}).get("event_tier", ""),
                title=(enriched or {}).get("title_zh") or it.get("title", ""),
            )
            return it, enriched

        with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            for fut in cf.as_completed([pool.submit(run_one, it) for it in items]):
                item, enriched = fut.result()
                if enriched is not None:
                    results.append({"url_hash": item["url_hash"],
                                    "enriched": enriched,
                                    "model": f"claude-local/{CLAUDE_MODEL}"})
        progress.finish()

        spent = time.time() - t0
        # 省下的钱按 OpenAI 侧实测单价估：gpt-5.4 单条约 $0.0093（run 12 实测）
        log.info(f"enriched {len(results)}/{len(items)} in {spent:.0f}s "
                 f"（单条均 {spent / max(1, len(items)):.1f}s，"
                 f"约省 ${len(results) * 0.0093:.2f} OpenAI 费用）")
        submitted = 0
        for i in range(0, len(results), 20):
            chunk = results[i:i + 20]
            resp = api("/api/enrich/submit",
                       {"prompt_hash": spec["prompt_hash"], "results": chunk})
            submitted += resp.get("accepted", 0)
            if resp.get("rejected"):
                log.warning(f"server rejected {len(resp['rejected'])} entries")
        log.info(f"submitted {submitted} cache entries — done")
        return 0
    except urllib.error.URLError as e:
        # VM 不可达（网络/服务重启中）：静默退出，下一次唤醒再试
        log.info(f"VM unreachable, will retry next wake: {e}")
        return 0
    finally:
        try:
            os.unlink(LOCK_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
