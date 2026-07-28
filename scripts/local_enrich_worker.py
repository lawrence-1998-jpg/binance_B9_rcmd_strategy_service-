#!/usr/bin/env python3
"""
本地预处理 worker —— 跑在 Lawrence 的 Mac 上，不是 VM 上。

做什么：闲时从 VM 领取 staging 里还没处理的新闻条目，按 VM 下发的同一份
prompt/schema 做结构化，结果回传 VM 的 llm_enrich_cache 表。VM 的 pipeline
跑到 LLM 环节时先查这张表，命中的条目不再消耗 VM 侧 OpenAI 直连账号的额度。

结构化后端：2026-07-28 起改为公司 LiteLLM 网关（OpenAI 兼容 chat.completions
+ strict json_schema），此前是本地 `claude -p` CLI（Claude Max 订阅）。原因：
Lawrence 明确要求不再消耗本机 Claude 订阅额度，且这台 Mac 挂公司 VPN 能连通
网关（VM 侧连不通——网关是内网专用地址，见 crawler/pipeline.py 的
LLM_MODEL 注释）。省钱账本也相应变化：以前是零边际成本（订阅费固定），
现在结构化费用走网关那 1000 美元额度，不再是个人 OpenAI 直连账号出钱——
仍然省钱，只是从"免费"变成"钱换了个账户出"，见 main() 里的日志措辞。

为什么是 pull 模式：这台 Mac 是工作机，不保证开机、没有公网入口。所以只能
Mac 主动拉（HTTP 出站），VM 永远不依赖 Mac 在线——Mac 关机/网关不可达的
唯一后果是缓存 miss，pipeline 照常全量走 VM 自己的 OpenAI 直连账号，效果零
损失，只是没省到钱。

调度：launchd 每 15 分钟唤醒一次（config/com.lawrence.b9-enrich-worker.plist）。
单次最多处理 BATCH_SIZE 条；staging 每天新增约 900 条，96 次唤醒 × 100 条/次
的吞吐上限远超需求，Mac 每天在线几个小时就足够清空积压。

纯标准库实现（urllib），Mac 上不需要 pip install 任何东西。
兼容到 python3.8（Mac 系统自带 python3 往往不是 3.10+，`X | None` 注解会在
运行时求值爆掉，用 future import 把注解全部字符串化绕开）。
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

# ── 配置 ─────────────────────────────────────────────────────────────
API_BASE = os.environ.get("B9_API_BASE", "http://34.138.247.158:8080")
API_TOKEN = os.environ.get("B9_API_TOKEN", "***REMOVED***")
# 2026-07-26 提速（40→100、4→6、唤醒间隔 30→15 分钟，见 plist）：OpenAI credit
# 只剩 $40，Lawrence 要求"尽量使用 claude 本机来跑"。Mac 在线的每一小时都要
# 尽可能多清 staging 积压，让 12h 一次的 pipeline 到点时命中率最大化。
# 单次唤醒 100 条 × 并发 6 约 4-5 分钟跑完，对日常使用无感。
BATCH_SIZE = int(os.environ.get("B9_BATCH", "100"))
CONCURRENCY = int(os.environ.get("B9_CONCURRENCY", "6"))
# 公司 LiteLLM 网关配置。key 直接给默认值是沿用本文件 API_TOKEN 那一行已有的
# 做法（私有仓库，Mac 本地脚本，同一套安全模型），不为这一个值单独破例。
# gpt-5.4 是实测过支持 strict json_schema 的模型（见 crawler/pipeline.py 的
# LLM_MODEL 注释）——网关上的 claude-opus-4-8 经 Bedrock 通道不支持这个模式，
# 换模型前必须先拿真实 schema 测过。
GATEWAY_BASE = os.environ.get("B9_GATEWAY_BASE", "https://litellm.devfdg.net/v1")
GATEWAY_KEY = os.environ.get("B9_GATEWAY_KEY", "***REMOVED***")
GATEWAY_MODEL = os.environ.get("B9_GATEWAY_MODEL", "gpt-5.4")
GATEWAY_TIMEOUT_S = 90
# 2026-07-28 实测踩到的硬限：这把 key 被网关限 30 req/min（429 body 里的
# "Current limit: 30"，"Limit resets at" 与请求时刻相差约 1 分钟，判定是
# 滚动 60s 窗口）。CONCURRENCY=6 的线程池不加约束会在几秒内打满 30 个请求，
# 剩下的条目全部 429——这不是"重试就好"的瞬时抖动，是稳定触发的硬顶，必须
# 从源头限速，而不是指望重试穿过去。留 5 个余量按 25/min 走。
GATEWAY_RPM = int(os.environ.get("B9_GATEWAY_RPM", "25"))
LOCK_FILE = "/tmp/b9-enrich-worker.lock"
LOCK_STALE_S = 2 * 3600

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("enrich-worker")


class RateLimiter:
    """滑动窗口限流，线程安全。ThreadPoolExecutor 的每个 worker 线程发请求前
    先 acquire()——一旦最近 period_s 秒内已有 max_calls 次调用，阻塞到最早
    那次调用滑出窗口为止。用来让并发线程从源头上"排队"而不是一拥而上撞 429。
    """

    def __init__(self, max_calls: int, period_s: float):
        self.max_calls = max_calls
        self.period_s = period_s
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.time()
                self._calls = [t for t in self._calls if now - t < self.period_s]
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                wait = self.period_s - (now - self._calls[0]) + 0.05
            time.sleep(max(0.05, wait))


_rate_limiter = RateLimiter(GATEWAY_RPM, 60.0)


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


def enrich_with_gateway(spec: dict, item: dict) -> dict | None:
    """单条结构化，走公司 LiteLLM 网关。失败重试一次，再失败返回 None
    （该条自然落回 VM 的 OpenAI 直连账号，无害）。

    直接复用 VM 侧同一份 response_format（{"type":"json_schema","strict":true,
    "schema":...}）——网关是 OpenAI 协议兼容端点，strict schema 保证返回的
    content 就是一个合法 JSON 字符串，不像 claude -p 那样需要从自由文本里
    抠 JSON。extract_json() 仍留作兜底（防御网关/模型任何未预期的包装），
    不是主路径。
    """
    user_content = (
        f"Source: {item.get('source', '')}\n"
        f"Title: {item.get('title', '')}\n"
        f"Summary: {(item.get('summary') or '')[:600]}\n"
        f"URL: {item.get('url', '')}\n"
        f"Published: {item.get('published_at', '')}"
    )
    body = json.dumps({
        "model": GATEWAY_MODEL,
        "messages": [
            {"role": "system", "content": spec["system_prompt"]},
            {"role": "user", "content": user_content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "news_event", "strict": True, "schema": spec["schema"]},
        },
    }).encode()

    for attempt in range(2):
        _rate_limiter.acquire()   # 从源头限速，见 GATEWAY_RPM 注释——不是靠 429 后重试穿过去
        try:
            req = urllib.request.Request(
                f"{GATEWAY_BASE}/chat/completions", data=body,
                headers={"Content-Type": "application/json",
                        "Authorization": f"Bearer {GATEWAY_KEY}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=GATEWAY_TIMEOUT_S) as resp:
                wrapper = json.loads(resp.read().decode())
            content = wrapper["choices"][0]["message"]["content"]
            try:
                enriched = json.loads(content)
            except ValueError:
                enriched = extract_json(content)   # 兜底，正常路径不会走到这
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
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", "replace")[:200]
            if e.code == 429:
                # 限流器把这个进程自己的请求压到了 GATEWAY_RPM/min，仍然撞到 429
                # 大概率是这一分钟的配额被别的调用方（比如我手动测试）占用了。
                # 同一轮里立刻重试大概率还是 429，纯粹浪费一个线程的时间——直接
                # 放弃这条，下一次唤醒（15 分钟后）会重新从 /api/enrich/pending
                # 领到它。这不算数据丢失：按 GATEWAY_RPM=25 换算，一次唤醒理论上
                # 能处理 25×15=375 条，远超 BATCH_SIZE=100，吞吐有充足冗余。
                log.info(f"rate limited, will retry next wake: {item.get('url', '')[:60]}")
                return None
            log.warning(f"gateway HTTP {e.code} for {item.get('url', '')[:60]}: {body_text}")
            if e.code in (401, 402, 403):
                break   # key 失效/欠费，重试也没用，直接放弃这条（下轮唤醒还会再试）
        except urllib.error.URLError as e:
            log.warning(f"gateway unreachable for {item.get('url', '')[:60]}: {e}")
        except (ValueError, KeyError, TimeoutError) as e:
            log.warning(f"gateway call failed: {e}")
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
                 f"(prompt {spec['prompt_hash']}, model {GATEWAY_MODEL} via gateway, "
                 f"concurrency {CONCURRENCY})")

        t0 = time.time()
        results = []
        progress = Progress(len(items))

        def run_one(it):
            """包一层只为测单条耗时并驱动进度显示。"""
            started = time.time()
            enriched = enrich_with_gateway(spec, it)
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
                                    "model": f"litellm-gateway/{GATEWAY_MODEL}"})
        progress.finish()

        spent = time.time() - t0
        # 单条成本估算按 OpenAI 官方 gpt-5.4 单价（run 12 实测约 $0.0093/条）——
        # 网关代理的也是同一个模型，价格数量级应该一致，但账真正走的是网关的
        # 1000 美元额度，不是"省下"而是"换了个账户花"，措辞如实反映这一点。
        log.info(f"enriched {len(results)}/{len(items)} in {spent:.0f}s "
                 f"（单条均 {spent / max(1, len(items)):.1f}s，"
                 f"约合 ${len(results) * 0.0093:.2f}，走网关额度而非 VM 直连账号）")
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
