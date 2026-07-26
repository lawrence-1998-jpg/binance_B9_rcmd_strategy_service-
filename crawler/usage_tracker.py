"""
OpenAI 用量与成本追踪。

起因：官方 usage/costs API（`/v1/organization/usage/completions`、
`/v1/organization/costs`）实测返回 403，当前 key 缺 `api.usage.read` scope；
`/v1/dashboard/billing/usage` 需要 session key，API key 用不了；
`/v1/usage`（旧版）返回 200 但数据为空。**这几条路都走不通**，所以改为
在应用层自己统计——每次 OpenAI 调用的响应里都带 `usage` 字段，直接读出来
累加，不依赖账号权限。

用法：`enrich_one()` / `embed_texts()` 内部调用 `record_chat()` / `record_embedding()`
把每次调用的 token 数记下来；一轮 pipeline 跑完后 `snapshot()` 拿汇总，写进
`pipeline_runs` 表；`scripts/usage_monitor.py` 从表里读历史趋势做成本预估。

线程安全：`enrich_batch` 用线程池并发调用 LLM，累加器必须加锁。
"""
import logging
import threading

logger = logging.getLogger(__name__)

# ── 价格表 ───────────────────────────────────────────────────────────
#
# 来源：2026-07-26 通过 WebSearch 查证的 OpenAI 官方定价页数据，非账单推算。
# **务必在实际扣费出现明显偏差时重新核对 https://openai.com/api/pricing/ 并更新此表**
# ——OpenAI 会调价，这里不会自动同步。
PRICING_USD_PER_MILLION_TOKENS = {
    "gpt-5.4": {"input": 2.50, "output": 15.00, "cached_input": 0.25},
    # 2026-07-26 新增：pipeline.py 把 market_signal/calendar 这类模板化条目路由
    # 到这个降级模型（见 pipeline.LLM_MODEL_LITE），定价同样查证自官方定价页。
    "gpt-5.4-nano": {"input": 0.20, "output": 1.25, "cached_input": 0.02},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0, "cached_input": 0.02},
}
_DEFAULT_CHAT_MODEL = "gpt-5.4"


class UsageTracker:
    """单轮 pipeline 内的用量累加器。跨线程安全。"""

    def __init__(self):
        # 必须是 RLock 而非 Lock：snapshot() 持锁期间会调用同样要持锁的
        # estimated_cost_usd()，用不可重入的 Lock 会自死锁 —— 实测
        # `UsageTracker().snapshot()` 直接永久挂起，而 run_pipeline() 结尾的
        # tracker.log_summary() / storage.record_run(usage=tracker.snapshot())
        # 正好走这条路径，会把整轮 pipeline 卡在最后一步。
        self._lock = threading.RLock()
        self.chat_calls = 0
        self.chat_input_tokens = 0
        self.chat_output_tokens = 0
        self.chat_cached_tokens = 0
        self.embedding_calls = 0
        self.embedding_tokens = 0
        # 按模型分桶，是精确计价的前提——多模型混跑之后，"总 token 数 ×
        # 单一价格"会算错账。旧调用方（api/eval_tools.py、
        # crawler/sector_relevance.py）不传 model，落进默认桶，行为不变。
        self._by_model: dict[str, dict[str, int]] = {}

    def record_chat(self, usage, model: str = _DEFAULT_CHAT_MODEL) -> None:
        """记一次 chat.completions 调用。`usage` 是响应对象的 `.usage` 属性。"""
        if usage is None:
            return
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        completion = getattr(usage, "completion_tokens", 0) or 0
        with self._lock:
            self.chat_calls += 1
            self.chat_input_tokens += prompt
            self.chat_output_tokens += completion
            self.chat_cached_tokens += cached
            bucket = self._by_model.setdefault(
                model, {"calls": 0, "input": 0, "output": 0, "cached": 0}
            )
            bucket["calls"] += 1
            bucket["input"] += prompt
            bucket["output"] += completion
            bucket["cached"] += cached

    def record_embedding(self, usage) -> None:
        """记一次 embeddings 调用。"""
        if usage is None:
            return
        with self._lock:
            self.embedding_calls += 1
            self.embedding_tokens += getattr(usage, "total_tokens", 0) or 0

    def estimated_cost_usd(self) -> float:
        """按价格表估算本轮总花费，逐模型分别计价后求和。"""
        with self._lock:
            embed_price = PRICING_USD_PER_MILLION_TOKENS["text-embedding-3-small"]
            chat_cost = 0.0
            for model, bucket in self._by_model.items():
                price = PRICING_USD_PER_MILLION_TOKENS.get(
                    model, PRICING_USD_PER_MILLION_TOKENS[_DEFAULT_CHAT_MODEL]
                )
                uncached_input = max(0, bucket["input"] - bucket["cached"])
                chat_cost += (
                    uncached_input * price["input"]
                    + bucket["cached"] * price["cached_input"]
                    + bucket["output"] * price["output"]
                ) / 1_000_000
            embed_cost = self.embedding_tokens * embed_price["input"] / 1_000_000
            return round(chat_cost + embed_cost, 6)

    def snapshot(self) -> dict:
        """导出汇总，供写库和日志使用。"""
        with self._lock:
            return {
                "chat_calls": self.chat_calls,
                "chat_input_tokens": self.chat_input_tokens,
                "chat_output_tokens": self.chat_output_tokens,
                "chat_cached_tokens": self.chat_cached_tokens,
                "embedding_calls": self.embedding_calls,
                "embedding_tokens": self.embedding_tokens,
                "estimated_cost_usd": self.estimated_cost_usd(),
                "by_model": {m: dict(b) for m, b in self._by_model.items()},
            }

    def log_summary(self) -> None:
        s = self.snapshot()
        logger.info(
            f"OpenAI usage this run: {s['chat_calls']} chat calls "
            f"({s['chat_input_tokens']:,} in / {s['chat_output_tokens']:,} out / "
            f"{s['chat_cached_tokens']:,} cached), {s['embedding_calls']} embedding calls "
            f"({s['embedding_tokens']:,} tokens) → est. ${s['estimated_cost_usd']:.4f}"
        )


# 一轮 pipeline 一个 tracker 实例，由 pipeline.run_pipeline() 创建并贯穿传递。
# 模块级单例仅作兜底：直接调用 enrich_one()/embed_texts() 做单元测试时，
# 不传 tracker 也不会报错，只是不计费。
_default_tracker = UsageTracker()


def get_default_tracker() -> UsageTracker:
    return _default_tracker
