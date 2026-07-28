"""
评测工具 API —— Tab 4「评测工具」的后端 Blueprint。

2026-07-26 更新：Tab 4 从独立页面（web/eval.html，/eval 路由跳转）合并进
web/index.html 的同页 tab 结构，本文件的 API 端点本身不受影响（前端改动
不改变任何请求路径）；同时新增第三个子工具 AB 对比。

包含三个独立子工具：
  1. Duplicate Tester   POST /api/tools/dedup-test    —— 多图上传，视觉提取标题 + embedding 去重
  2. LLM 评测室         POST /api/tools/persona-eval   —— 单条新闻，多 persona 结构化评测
  3. AB 对比            POST /api/tools/ab-compare     —— 两组内容（数据库/文本/图片）做重合度、
                                                          质量、GSB（Good/Same/Bad）对比

## 注册方式（本文件不会自己挂到主 app 上，需要在 api/server.py 里手动加两行）：

    from eval_tools import eval_bp
    app.register_blueprint(eval_bp)

  （server.py 是用 `python3 api/server.py` 启动的，运行时 sys.path[0] 是 api/ 目录本身，
  所以是同目录的 `from eval_tools import eval_bp` 而不是 `from api.eval_tools import ...`；
  本文件已经自行把仓库根目录塞进 sys.path，`from crawler import storage` 那一行不受这个影响。）

## 设计要点 / 踩过的坑

- 视觉模型：直接用 gpt-5.4（跟 crawler/pipeline.py 里结构化用的是同一个模型），
  chat.completions.create 的 messages content 传 image_url（base64 data URI）即可，
  已经用 materials/screenshots 里的真实截图实测过，中文标题提取准确。
  唯一的坑：这个模型只认 `max_completion_tokens`，传 `max_tokens` 会 400。
- 去重阈值：COSINE_THRESHOLD 直接从 crawler.dedup 导入，不在这里重新定义——
  0.82 是仓库里已经用真实数据标定过的数字，见 dedup.py 头部注释。并查集同理复用
  crawler.dedup._UnionFind，没有重新发明。
- 成本：价格表复用 crawler.usage_tracker.PRICING_USD_PER_MILLION_TOKENS，同一个理由，
  不在这里重新抄一遍价格（会随官方调价而跟仓库其他地方一起漂移，抄一份必然滞后）。
- OpenAI client 显式设置了 timeout/max_retries——crawler.pipeline.get_openai_client()
  用的是 SDK 默认（600s 超时、2 次重试），批处理脚本等得起，但这里是同步 HTTP 请求处理器，
  一个挂起的上游调用会把 Flask worker 卡死，所以这里的 client 用更短的超时 + 更少重试，
  上游确实超时也能快速给用户一个明确的错误而不是转圈到天荒地老。
"""
import base64
import concurrent.futures as cf
import csv
import io
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from functools import wraps

from flask import Blueprint, jsonify, request
from openai import OpenAI

# repo 根目录塞进 sys.path，这样不管本文件被谁 import（server.py 同目录导入，
# 还是本文件自己被当脚本跑去做 Blueprint 单测），`from crawler import ...` 都能找到包。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from crawler.dedup import (  # noqa: E402
    COSINE_THRESHOLD, blob_to_embedding, cosine, embed_texts, _UnionFind,
)
from crawler.usage_tracker import PRICING_USD_PER_MILLION_TOKENS, UsageTracker  # noqa: E402
from crawler import storage  # noqa: E402  （只读用，见 persona-eval 的 event_id 便捷参数）
from crawler.timeutil import now_local

# persona 人设与评测留档的数据层。刻意是一个无 Flask 依赖的共享模块而不是
# 直接 import persona_tools 那个 blueprint——见 persona_store.py 头部说明。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import persona_store  # noqa: E402

logger = logging.getLogger(__name__)

eval_bp = Blueprint("eval_tools", __name__)

# ── 鉴权 ─────────────────────────────────────────────────────────────
#
# 2026-07-26 补充：这个文件之前完全没有鉴权检查——Duplicate Tester/LLM评测室/
# AB对比这几个接口每次调用都会产生真实 OpenAI 费用，没有鉴权意味着任何能访问到
# 这台机器的人都能白嫖调用、白花钱。跟其它 blueprint（lab_tools.py/
# sector_insight.py/history_tools.py）保持同一套独立实现的鉴权模式。
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "***REMOVED***")
API_TOKENS = {
    "lawrence":  os.environ.get("API_TOKEN_LAWRENCE",  "***REMOVED***"),
    "team-a":    os.environ.get("API_TOKEN_TEAM_A",    "***REMOVED***"),
    "team-b":    os.environ.get("API_TOKEN_TEAM_B",    "***REMOVED***"),
    "partner-1": os.environ.get("API_TOKEN_PARTNER1",  "***REMOVED***"),
    "partner-2": os.environ.get("API_TOKEN_PARTNER2",  "***REMOVED***"),
    "web":       os.environ.get("API_TOKEN_WEB",       "***REMOVED***"),
}
VALID_API_KEYS = {API_SECRET_KEY, *API_TOKENS.values()}


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not key:
            key = request.args.get("token", "")
        if key not in VALID_API_KEYS:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ── 常量 ─────────────────────────────────────────────────────────────
MODEL = "gpt-5.4"                     # 视觉 + 文本结构化统一用这一个模型（同厂商同型号原生支持图片输入，实测过）
MAX_IMAGES_PER_REQUEST = 20            # 单次 dedup-test 最多处理的图片数，超过直接拒绝
MAX_IMAGE_BYTES = 8 * 1024 * 1024      # 单张图 8MB 上限，防止异常大文件拖垮请求
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}


def _load_env_fallback():
    """兜底：如果直接用 `python3 api/eval_tools.py` 或独立测试跑本文件（没经过
    run_api.sh / systemd 的 EnvironmentFile 注入），手动把 config/.env 读进 os.environ。
    正常通过 server.py 起服务时环境变量已经有了，这里只是不覆盖已存在的值。
    """
    env_file = os.path.join(_REPO_ROOT, "config", ".env")
    if not os.path.exists(env_file):
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env_fallback()

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        kwargs = {"timeout": 45, "max_retries": 1}
        if api_key := os.environ.get("OPENAI_API_KEY"):
            kwargs["api_key"] = api_key
        if base_url := (os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL")):
            kwargs["base_url"] = base_url
        _client = OpenAI(**kwargs)
    return _client


def _chat_cost_usd(tracker: UsageTracker) -> float:
    """跟 UsageTracker.estimated_cost_usd 逻辑一致，但只在这里独立调用，
    因为 tracker 本身价格表也是复用同一份常量，snapshot() 已经算好了，直接用。"""
    return tracker.snapshot()["estimated_cost_usd"]


# ── embedding 失败必须显式报错，不能沿用生产流水线的静默降级 ─────────────
#
# crawler/dedup.py 的 embed_texts 在整批调用失败时会吞掉异常、返回零矩阵。
# 那个降级对生产去重流水线是对的（零向量之间余弦为 0，不会误归簇，等于退回
# 只靠 DC-1/DC-2 去重，批处理不该因为一次 embedding 抖动就整轮挂掉）；但对
# 本文件这两个评测工具，同一个降级是有毒的：
#   - dedup-test：相似度全 0 → 一个都不聚簇 → 照常返回"重复组数 0"。用户读到
#     的结论是"这批新闻确实不重复"，真相却是"这一步根本没算出来"。评测工具
#     给出一个假的"没问题"，比直接报错危险得多。
#   - ab-compare：全零相似度矩阵 → 重合度恒为 0、最近邻 argmax 退化成恒取 B 组
#     第 0 条，然后照常把这些无意义的配对送去烧 GSB 的 LLM 调用，最后产出一份
#     基于全零相似度的垃圾结论，钱花了、结论还不能用。
# 所以这里把"算不出来"和"结果是 0"分开：调用方要么拿到有效向量，要么拿到一个
# 明确的失败，由路由翻译成 502。
class EmbeddingUnavailable(RuntimeError):
    """embedding 没有真正算出来（上游调用失败，被 embed_texts 静默降级成零向量）。"""


def _embed_or_fail(texts: list[str], tracker: UsageTracker) -> np.ndarray:
    """embed_texts + 结果校验，拿不到有效向量就抛 EmbeddingUnavailable。

    只能靠结果特征判断失败，不能靠捕获异常——embed_texts 内部已经把异常
    catch 掉了，外面 try/except 永远等不到。判据是模长：embed_texts 返回的是
    L2 归一化后的矩阵，正常向量模长恒为 1，被降级填充的零向量归一化后仍是 0，
    两者之间没有中间地带，取 0.5 做门限即可。
    逐行检查而不是只看整批，是因为 embed_texts 按 EMBED_BATCH=128 分批，
    部分批次失败时只有那一段是零向量——这种"部分失败"同样会让重复被漏报，
    一样得报错，不能只挑整批失败的情况处理。
    """
    vectors = embed_texts(texts, get_client(), tracker)
    if vectors.shape[0] != len(texts):
        raise EmbeddingUnavailable(
            f"embedding 返回条数不匹配（期望 {len(texts)} 条，实际 {vectors.shape[0]} 条）"
        )
    if texts:
        n_failed = int((np.linalg.norm(vectors, axis=1) < 0.5).sum())
        if n_failed:
            raise EmbeddingUnavailable(
                f"{len(texts)} 条文本里有 {n_failed} 条没能取到 embedding 向量"
                "（上游 embeddings 调用失败）"
            )
    return vectors


# ══════════════════════════════════════════════════════════════════════
# 子 Tab 1: Duplicate Tester
# ══════════════════════════════════════════════════════════════════════

_HEADLINE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "extracted_headlines",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "headlines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "source": {"type": "string"},
                            "date": {"type": "string"},
                        },
                        "required": ["title", "source", "date"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["headlines"],
            "additionalProperties": False,
        },
    },
}

_HEADLINE_EXTRACT_PROMPT = (
    "This is a screenshot of a crypto news feed (from a mobile app or website). "
    "Extract EVERY distinct news headline visible in the image, top to bottom, transcribed "
    "EXACTLY as shown (do not translate or paraphrase). For each headline also capture the "
    "source/outlet name and the date, if legible near that headline (empty string if not). "
    "If the very first or very last headline is cut off / faded / only partially visible at "
    "the edge of the screenshot, OMIT it entirely rather than guessing or truncating it — "
    "a partial title would poison downstream duplicate detection. Only include headlines "
    "you can read in full."
)


def _extract_headlines_from_image(image_bytes: bytes, mime: str, tracker: UsageTracker) -> list[dict]:
    """单张图片 -> 视觉模型 -> 标题列表。每张图只调这一次 API（成本控制的核心约束）。"""
    b64 = base64.b64encode(image_bytes).decode()
    resp = get_client().chat.completions.create(
        model=MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": _HEADLINE_EXTRACT_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        response_format=_HEADLINE_SCHEMA,
        max_completion_tokens=2000,
    )
    tracker.record_chat(getattr(resp, "usage", None))
    data = json.loads(resp.choices[0].message.content)
    return data.get("headlines", [])


def _build_tsv(rows: list[dict]) -> str:
    """生成可直接粘贴进 Excel 的 TSV（制表符分隔——Excel/Google Sheets 粘贴时能按列自动分列，
    比 CSV 更不容易被中文标题里偶尔出现的逗号搞乱列）。"""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
    writer.writerow(["组编号", "图片序号", "文件名", "来源", "提取标题", "组内相似度", "是否重复"])
    for r in rows:
        writer.writerow([
            r["group_id"], r["image_index"], r["image_name"], r["source"],
            r["title"], f"{r['similarity_to_group']:.3f}", "是" if r["is_duplicate"] else "否",
        ])
    return buf.getvalue()


@eval_bp.route("/api/tools/dedup-test", methods=["POST"])
@require_api_key
def dedup_test():
    files = request.files.getlist("images")
    if not files:
        return jsonify({"error": "未收到图片，请用 multipart/form-data 的 'images' 字段上传"}), 400
    if len(files) > MAX_IMAGES_PER_REQUEST:
        return jsonify({
            "error": f"单次最多处理 {MAX_IMAGES_PER_REQUEST} 张图片，本次收到 {len(files)} 张，请分批上传"
        }), 400

    images = []  # (index, filename, bytes, mime)
    for idx, f in enumerate(files):
        mime = f.mimetype or ""
        if mime not in ALLOWED_IMAGE_TYPES:
            return jsonify({"error": f"第 {idx+1} 张图片格式不支持（{mime}），仅支持 png/jpg/webp/gif"}), 400
        content = f.read()
        if len(content) > MAX_IMAGE_BYTES:
            return jsonify({"error": f"第 {idx+1} 张图片超过 {MAX_IMAGE_BYTES // (1024*1024)}MB 上限"}), 400
        images.append((idx, f.filename or f"image_{idx}", content, mime))

    tracker = UsageTracker()

    # 每张图一次视觉调用，并发做（互不依赖），但不重复调用任何一张图
    def _process(item):
        idx, name, content, mime = item
        try:
            headlines = _extract_headlines_from_image(content, mime, tracker)
            return idx, name, headlines, None
        except Exception as e:
            logger.warning(f"Vision extraction failed for image {idx} ({name}): {e}")
            return idx, name, [], str(e)

    with cf.ThreadPoolExecutor(max_workers=min(8, len(images))) as pool:
        extraction_results = list(pool.map(_process, images))
    extraction_results.sort(key=lambda x: x[0])

    all_items = []  # dict: image_index, image_name, title, source, date
    image_errors = {}
    for idx, name, headlines, err in extraction_results:
        if err:
            image_errors[idx] = err
        for h in headlines:
            title = (h.get("title") or "").strip()
            if not title:
                continue
            all_items.append({
                "image_index": idx, "image_name": name,
                "title": title, "source": h.get("source", ""), "date": h.get("date", ""),
            })

    if not all_items:
        return jsonify({
            "error": "所有图片都没有提取到有效标题，请检查图片是否为新闻列表截图",
            "image_errors": image_errors,
            "cost_usd": _chat_cost_usd(tracker),
            "images_processed": len(images),
        }), 422

    # embedding + 并查集聚类 —— 完全复用 crawler/dedup.py 里已标定过的逻辑，不发明新阈值
    titles = [it["title"] for it in all_items]
    try:
        vectors = _embed_or_fail(titles, tracker)
    except EmbeddingUnavailable as e:
        # 这一步失败绝不能继续往下走：往下走的结果是"重复组数 0"，而这个 0 会被
        # 用户读成"这批新闻没有重复"（见 _embed_or_fail 上面的说明）。视觉提取的
        # 钱已经花掉了，如实把成本和已提取的标题数一起返回，但整个请求判定为失败。
        logger.error(f"dedup-test embedding unavailable: {e}")
        return jsonify({
            "error": f"向量计算失败，无法判断是否重复：{e}",
            "hint": "这不等于「没有检测到重复」——是去重这一步根本没算出来。请稍后重试；"
                    "持续失败请检查 OPENAI_API_KEY 与 embeddings 上游是否可用。",
            "total_headlines_extracted": len(titles),
            "cost_usd": _chat_cost_usd(tracker),
            "cost_breakdown": tracker.snapshot(),
            "images_processed": len(images),
            "image_errors": image_errors,
        }), 502
    n = len(titles)
    uf = _UnionFind(n)
    sim = vectors @ vectors.T
    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= COSINE_THRESHOLD:
                uf.union(i, j)

    cluster_map: dict[int, list[int]] = {}
    for i in range(n):
        cluster_map.setdefault(uf.find(i), []).append(i)
    # 组编号按组内最小 index 排序，保证输出顺序稳定可复现
    ordered_roots = sorted(cluster_map.keys(), key=lambda r: min(cluster_map[r]))

    groups_out = []
    table_rows = []
    for gi, root in enumerate(ordered_roots, start=1):
        members = cluster_map[root]
        group_items = []
        for m in members:
            others = [k for k in members if k != m]
            if others:
                sim_to_group = float(np.mean([sim[m, k] for k in others]))
            else:
                sim_to_group = 1.0
            entry = {
                "image_index": all_items[m]["image_index"],
                "image_name": all_items[m]["image_name"],
                "title": all_items[m]["title"],
                "source": all_items[m]["source"],
                "similarity_to_group": round(sim_to_group, 4),
            }
            group_items.append(entry)
            table_rows.append({
                "group_id": gi, "image_index": entry["image_index"], "image_name": entry["image_name"],
                "source": entry["source"], "title": entry["title"],
                "similarity_to_group": sim_to_group, "is_duplicate": len(members) > 1,
            })
        groups_out.append({
            "group_id": gi,
            "size": len(members),
            "is_duplicate_group": len(members) > 1,
            "items": group_items,
        })

    return jsonify({
        "groups": groups_out,
        "duplicate_group_count": sum(1 for g in groups_out if g["is_duplicate_group"]),
        "total_headlines_extracted": n,
        "table_csv": _build_tsv(table_rows),
        "cost_usd": _chat_cost_usd(tracker),
        "cost_breakdown": tracker.snapshot(),
        "images_processed": len(images),
        "image_errors": image_errors,
        "cosine_threshold_used": COSINE_THRESHOLD,
        "model": MODEL,
    })


# ══════════════════════════════════════════════════════════════════════
# 子 Tab 2: LLM 评测室
# ══════════════════════════════════════════════════════════════════════

# ── persona 来源：数据库（api/persona_store.py） ───────────────────────
#
# 2026-07-28 之前这里是一段硬编码的 5 个 persona 常量：改一次人设要改代码 + 重启
# 服务，也没法让用户自己增删改。现在人设住在 eval_personas 表里，本文件只负责
# "取出来 -> 拼 prompt -> 调模型 -> 落结果"。
#
# 兜底：数据库读不到时（迁移没跑 / MySQL 抖动）回落到 persona_store.BUILTIN_PERSONAS
# 那三个内置人设，让评测室仍然可用。但**必须**在响应里如实标注 persona_source，
# 不能让用户以为自己刚改的人设生效了、实际跑的是内置默认值——那种静默降级正是
# 本文件头部注释里反复强调要避免的那类"假装成功"。
def load_personas() -> tuple[list[dict], str]:
    """返回 (personas, source)。source ∈ {"db", "builtin_fallback"}。"""
    try:
        persona_store.ensure_seeded()
        rows = persona_store.list_personas(active_only=True)
        if rows:
            return rows, "db"
        # 表存在但一个启用的 persona 都没有：这是用户把人全停用/删光了，不是故障。
        # 此时不该拿内置人设顶上——那等于无视用户的操作。
        return [], "db"
    except Exception as e:
        logger.warning(f"从数据库读取 persona 失败，回落到内置默认人设：{e}")
        return [dict(p, version=1) for p in persona_store.BUILTIN_PERSONAS], "builtin_fallback"

_EVAL_INSTRUCTION_SUFFIX = (
    "\n\n下面会给你一条加密货币新闻的完整文本（标题+摘要/正文）。请你完全代入上面描述的人设，"
    "给出以下结构化评测结果：\n"
    "1. score：这个人设看到这条新闻会打几分，1-10 的整数，10 分表示对我极有价值/非常感兴趣，"
    "1 分表示完全无关/看不下去。\n"
    "2. qualitative_assessment：这个人设读完新闻后的真实反应，50-120 字，第一人称，要体现出人设"
    "的语言习惯和关注点，不要写成客观中立的第三方点评。\n"
    "3. is_understandable + understandable_reason：这个人设是否能看懂新闻在说什么（不是问是否感"
    "兴趣，是问是否理解内容本身，包括术语、数字、背景）。understandable_reason 用一两句话说明"
    "具体原因。\n"
    "4. improvement_suggestion：如果要让这个人设更满意，新闻应该怎么改，20-60 字，给出具体可执行"
    "的建议，而不是空泛的\"写得更好\"。\n\n"
    "务必保持人设的真实性和差异化——专业机构投资者和刚入圈的新手看同一条新闻应该有完全不同的"
    "反应，不要写成千篇一律的标准评测语气。"
)

_PERSONA_EVAL_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "persona_evaluation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "score": {"type": "integer"},
                "qualitative_assessment": {"type": "string"},
                "is_understandable": {"type": "boolean"},
                "understandable_reason": {"type": "string"},
                "improvement_suggestion": {"type": "string"},
            },
            "required": [
                "score", "qualitative_assessment", "is_understandable",
                "understandable_reason", "improvement_suggestion",
            ],
            "additionalProperties": False,
        },
    },
}

_IMAGE_TO_TEXT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "news_text_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body_text": {"type": "string"},
            },
            "required": ["title", "body_text"],
            "additionalProperties": False,
        },
    },
}


def _news_text_from_image(image_bytes: bytes, mime: str, tracker: UsageTracker) -> str:
    """单张新闻截图 -> 完整文本（标题+正文）。只调一次视觉 API。"""
    b64 = base64.b64encode(image_bytes).decode()
    resp = get_client().chat.completions.create(
        model=MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "This is a screenshot containing a single crypto news article or a detail "
                    "view. Transcribe the headline and all visible body text exactly as shown, "
                    "without translating or summarizing."
                )},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        response_format=_IMAGE_TO_TEXT_SCHEMA,
        max_completion_tokens=1500,
    )
    tracker.record_chat(getattr(resp, "usage", None))
    data = json.loads(resp.choices[0].message.content)
    return f"{data.get('title', '')}\n{data.get('body_text', '')}".strip()


def _fetch_event_full(event_id: str) -> dict | None:
    """只读查询 news_events，一次取够 persona-eval 需要的全部字段：

    展示文本用的 title_zh/description_*，以及 Momentum/Novelty 参考指标要用的
    event_subject/social_interactions/time_event/time_get_data/embedding。

    momentum/novelty 只在 event_id 这条输入路径下能算——它们依赖 news_events
    表里已经落库的这几个字段，纯文本粘贴或截图上传的新闻没有这些字段可用，
    见 persona_eval() 里 reference_metrics 的降级处理。
    """
    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            # importance_score 是 2026-07-28 加的：批量评测要把它和 persona 主观评分
            # 一起落库，用来算「排序模型 vs 真实人群感受」的相关性（外部效度）。
            "SELECT id, title_zh, description_long_zh, description_short_zh, "
            "event_subject, social_interactions, time_event, time_get_data, embedding, "
            "importance_score "
            "FROM news_events WHERE id = %s", (event_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        return row
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# 参考指标：Momentum（动量）+ Novelty（叙事新鲜感）
# 设计与取舍见 docs/design-additional-metrics.md（含放弃掉的「舆论分歧度」
# 「交易可操作性」两个维度及原因）。这两个值只在 LLM 评测室（persona-eval）
# 里作为参考字段展示，不参与任何评分逻辑，也不改动生产 crawler/scoring.py
# 的排序公式——这是用户明确要求的边界。
# ══════════════════════════════════════════════════════════════════════

# 新鲜感回看窗口。比 dedup.py 的 48h 归并时间窗宽得多——归并判断的是"是不是
# 同一件事"，这里判断的是"是不是同一条叙事脉络在近期被反复报道"，两者语义
# 不同，用的窗口自然也不同。
NOVELTY_LOOKBACK_DAYS = 30


def _compute_momentum(meta: dict) -> dict:
    """Momentum ≈ 互动量 / 发布至今小时数，热度的"速度近似"。

    简化版实现：docs/design-additional-metrics.md 里提到的更精细方案
    （跨轮记录上一次互动量、算真实增量）需要 storage.py 在归并时多存一个
    "上次看到时的互动量"字段，属于后续可做的精细化，本轮先用能立刻算出来
    的近似值，如实标注 is_approximation=True，不假装是精确的增量。
    """
    social = max(0, int(meta.get("social_interactions") or 0))
    published = meta.get("time_event") or meta.get("time_get_data")

    hours_since = None
    if published is not None and hasattr(published, "isoformat"):
        pub_dt = published if published.tzinfo else published.replace(tzinfo=timezone.utc)
        hours_since = max(0.0, (now_local() - pub_dt).total_seconds() / 3600)

    denom = max(1.0, hours_since if hours_since is not None else 1.0)
    value = social / denom

    return {
        "value": round(value, 4),
        "social_interactions": social,
        "hours_since_published": round(hours_since, 2) if hours_since is not None else None,
        "is_approximation": True,
        "note": "简化版：social_interactions / max(1, 发布至今小时数) 的速度近似，"
                "不是「跨轮记录上一次互动量算真实增量」的精细版本（后者尚未实现）。",
    }


def _compute_novelty(meta: dict) -> dict:
    """Novelty = 1 − 该事件与「同 event_subject、过去 N 天内」历史事件的最大 embedding 相似度。

    完全复用 crawler/dedup.py 已有的向量比对逻辑（blob_to_embedding + cosine），
    不重新发明相似度算法；直接读 news_events.embedding 这一存量列，不再调一次
    embeddings API，成本为零。

    阈值/口径未做 dedup.py COSINE_THRESHOLD 那样的统计标定（那是"判断是否为
    同一事件"的归并阈值，语义不同，不能直接照抄）——这里只是抽样验证了几个
    真实的"同一叙事被反复报道 3-5 次"的案例，看数字是否符合直觉，属于用户
    原话"不用建立完整的统计标定流程"的参考性指标。
    """
    subject = meta.get("event_subject")
    self_id = meta.get("id")
    self_vec = blob_to_embedding(meta.get("embedding"))

    if not subject or self_vec is None:
        return {
            "value": None,
            "note": "该事件缺少 event_subject 或 embedding，无法计算新鲜感"
                    "（通常是较早入库、当时还没有这两个字段的历史数据）。",
        }

    # 时间窗两端都锚在「这条事件自己入库的时刻」上，而不是锚在 now 上。
    #
    # 原来的写法是 time_get_data >= now-30d，只有下界、没有上界，等于把比该事件
    # 更晚才入库的报道也算成了它的"历史"——同一条叙事只要后续被反复报道，就会
    # 反过来把这条老事件的新鲜感压下去，越老的事件被压得越狠，是系统性低估；
    # 而且窗口锚在 now 上还有第二个问题：一条 40 天前的事件，[now-30d, ...] 这个
    # 区间里根本不包含它自己的时间点，取到的"历史"全是它之后的东西。
    # 新鲜感问的是"这条叙事在它出现之前是不是已经被反复报道过了"，只有它之前的
    # 报道才算数，所以窗口是 [事件时刻-30d, 事件时刻)。
    #
    # 锚点和过滤都用 time_get_data（入库时刻）这同一列，比较的口径才一致；
    # 老数据可能没有 time_get_data，退回 time_event，两者都缺才退回 now
    # （退回 now 就等于恢复成旧行为，但这类数据本来也大多没有 embedding，
    # 上面的 self_vec is None 分支已经先拦掉了）。
    anchor = meta.get("time_get_data") or meta.get("time_event")
    if anchor is not None and hasattr(anchor, "isoformat"):
        anchor_dt = anchor if anchor.tzinfo else anchor.replace(tzinfo=timezone.utc)
    else:
        anchor_dt = now_local()
    since = (anchor_dt - timedelta(days=NOVELTY_LOOKBACK_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    until = anchor_dt.strftime("%Y-%m-%d %H:%M:%S")
    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, embedding FROM news_events "
            "WHERE event_subject = %s AND id != %s "
            "AND time_get_data >= %s AND time_get_data < %s",
            (subject, self_id, since, until),
        )
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    sims = []
    for r in rows:
        vec = blob_to_embedding(r.get("embedding"))
        if vec is not None:
            sims.append(cosine(self_vec, vec))

    max_sim = max(sims) if sims else 0.0
    novelty = 1.0 - max_sim
    return {
        "value": round(novelty, 4),
        "max_similarity_to_history": round(max_sim, 4),
        "similar_history_count": len(sims),
        "lookback_days": NOVELTY_LOOKBACK_DAYS,
        "window_start": since,      # 比对窗口两端都返回，方便核对"到底跟哪一段历史比的"
        "window_end": until,
        "note": f"同一 event_subject（{subject}）在该事件之前 {NOVELTY_LOOKBACK_DAYS} 天内"
                f"（{since} ~ {until}）找到 {len(sims)} 条历史事件参与比对；只回看该事件"
                "之前的报道，之后的报道不算历史。阈值未做统计标定，只抽样验证过方向正确"
                "（同一叙事反复报道时新鲜感应明显走低）。",
    }


def _evaluate_one_persona(persona: dict, news_text: str, tracker: UsageTracker) -> dict:
    # system prompt 由五要素 + 校准记忆现拼（persona_store.compose_system_prompt），
    # 不再是人设字典里的一个固定字段——用户在管理页改完人设、或者提交完一条校准，
    # 下一次评测立刻生效，中间没有缓存层。
    resp = get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system",
             "content": persona_store.compose_system_prompt(persona) + _EVAL_INSTRUCTION_SUFFIX},
            {"role": "user", "content": f"新闻内容：\n{news_text}"},
        ],
        response_format=_PERSONA_EVAL_SCHEMA,
        max_completion_tokens=800,
    )
    tracker.record_chat(getattr(resp, "usage", None))
    result = json.loads(resp.choices[0].message.content)
    return {
        "persona_id": persona["id"],
        "name": persona["name"],
        "emoji": persona.get("emoji") or "🙂",
        "tagline": persona.get("tagline") or "",
        # 记下这条结果是拿哪一版人设跑出来的。没有它就没法做校准前后对比——
        # 人设改过之后历史结果会被误当成新人设的表现。
        "persona_version": int(persona.get("version") or 1),
        **result,
    }


def _run_personas(personas: list[dict], news_text: str, tracker: UsageTracker):
    """并发跑一组 persona，返回 (成功列表, 失败列表)。批量评测复用同一个函数。"""
    def _one(persona):
        try:
            return _evaluate_one_persona(persona, news_text, tracker), None
        except Exception as e:
            logger.warning(f"Persona eval failed for {persona['id']}: {e}")
            return None, {"persona_id": persona["id"], "name": persona.get("name"),
                          "persona_version": int(persona.get("version") or 1),
                          "error": str(e)}

    with cf.ThreadPoolExecutor(max_workers=max(1, len(personas))) as pool:
        results = list(pool.map(_one, personas))
    return ([r for r, err in results if r is not None],
            [err for r, err in results if err is not None])


@eval_bp.route("/api/tools/persona-eval", methods=["POST"])
@require_api_key
def persona_eval():
    news_text = None
    event_meta = None   # 只有 event_id 输入路径会填充，供 Momentum/Novelty 参考指标使用
    tracker = UsageTracker()

    # 请求体解析：原来这里是 request.json.get(...)，Content-Type 标了 application/json
    # 但 body 是畸形 JSON 时，request.json 会让 Flask 直接抛 BadRequest，返回的是
    # Flask 默认那张 HTML 400 错误页。全站其它入口（lab_tools.py 的 reweight/compare、
    # history_tools.py）都是 silent 解析 + JSON 错误体，前端也统一按 JSON 解析响应，
    # 拿到 HTML 只会解析失败、把真正的原因吞掉。这里统一成 silent 解析。
    body = request.get_json(silent=True)
    if request.is_json and not isinstance(body, dict):
        return jsonify({"error": "请求体不是合法的 JSON 对象，请检查 JSON 格式"}), 400
    if not isinstance(body, dict):
        body = {}   # 非 JSON 请求（multipart/form-data 等）走 form/files 分支

    # 三种输入方式，按优先级取：直接文本 > 图片 > event_id（便于用库里真实新闻测试）
    text_input = request.form.get("text") or body.get("text")
    event_id = request.form.get("event_id") or body.get("event_id")
    image_file = request.files.get("image")

    try:
        if text_input and text_input.strip():
            news_text = text_input.strip()
        elif image_file:
            mime = image_file.mimetype or ""
            if mime not in ALLOWED_IMAGE_TYPES:
                return jsonify({"error": f"图片格式不支持（{mime}）"}), 400
            content = image_file.read()
            if len(content) > MAX_IMAGE_BYTES:
                return jsonify({"error": "图片超过 8MB 上限"}), 400
            news_text = _news_text_from_image(content, mime, tracker)
        elif event_id:
            event_meta = _fetch_event_full(event_id.strip())
            if event_meta is None:
                return jsonify({"error": f"news_events 里找不到 id={event_id}"}), 404
            body_text = event_meta.get("description_long_zh") or event_meta.get("description_short_zh") or ""
            news_text = f"{event_meta['title_zh']}\n{body_text}".strip()
        else:
            return jsonify({"error": "请提供 text（新闻文本）、image（新闻截图）或 event_id 三者之一"}), 400
    except Exception as e:
        logger.exception("persona_eval input processing failed")
        return jsonify({"error": f"输入处理失败：{e}"}), 502

    if not news_text:
        return jsonify({"error": "未能获取到有效新闻文本"}), 422

    active_personas, persona_source = load_personas()
    if not active_personas:
        return jsonify({"error": "当前没有任何启用的评测 Agent。请到「Persona 管理」"
                                 "新建一个，或把已停用的重新启用。"}), 409

    personas_out, errors = _run_personas(active_personas, news_text, tracker)

    # 自动留档。刻意 try 住：评测本身已经花了钱、结果已经算出来了，落库失败不该
    # 让整个请求返 500 把用户的结果吞掉。落库失败时 run_uid 为 None，前端据此
    # 隐藏"写校准"入口（没有 result_id 可挂），但结果照常展示。
    run_uid = None
    try:
        run_uid = persona_store.record_run(
            input_mode=("text" if text_input else ("image" if image_file else "event_id")),
            news_text=news_text, results=personas_out, errors=errors,
            event_id=(event_id.strip() if event_id else None),
            importance_score=(event_meta or {}).get("importance_score"),
            cost_usd=_chat_cost_usd(tracker), model=MODEL,
        )
    except Exception:
        logger.exception("评测结果落库失败（不影响本次返回的评测结果）")

    # 把落库后拿到的 result_id 回填进每个 persona 结果——前端要靠它把
    # 「写校准」和「人工标注分」挂到具体某一条上。
    if run_uid:
        try:
            saved = persona_store.get_run(run_uid) or {}
            by_pid = {r["persona_id"]: r["id"] for r in saved.get("results", [])
                      if r.get("error") is None}
            for r in personas_out:
                r["result_id"] = by_pid.get(r["persona_id"])
        except Exception:
            logger.exception("回填 result_id 失败（评测结果本身不受影响）")

    if event_meta is not None:
        reference_metrics = {
            "available": True,
            "momentum": _compute_momentum(event_meta),
            "novelty": _compute_novelty(event_meta),
        }
    else:
        reference_metrics = {
            "available": False,
            "reason": "Momentum/Novelty 依赖 news_events 库里已落库的 social_interactions/"
                      "event_subject/embedding 字段，只有通过 event_id 输入时才能计算；"
                      "文本粘贴或截图上传的新闻没有这些字段可用。",
        }

    return jsonify({
        "news_text": news_text,
        "personas": personas_out,
        "persona_errors": errors,
        "cost_usd": _chat_cost_usd(tracker),
        "cost_breakdown": tracker.snapshot(),
        "model": MODEL,
        "reference_metrics": reference_metrics,
        "run_uid": run_uid,
        # 如实告诉前端这批人设是从库里读的还是兜底的内置默认值。用户刚在管理页
        # 改完人设，如果因为数据库故障实际跑的是内置人设，必须让他看得见。
        "persona_source": persona_source,
    })


# ══════════════════════════════════════════════════════════════════════
# 批量评测：N 条新闻 × M 个 Agent
# ══════════════════════════════════════════════════════════════════════
#
# 单条评测只能看个别案例，回答不了产品问题。真正有用的是「某一轮次的 top 20 事件，
# 三档资产人群分别怎么看」——这才看得出排序策略对不同人群的覆盖差异，也才能跟
# 「对比 baseline 评估召回率」那条业务线接上。
#
# 成本刹车：条数 × persona 数就是 LLM 调用次数，很容易失控。所以硬上限 30 条，
# 且请求里必须显式带 confirm_cost=true —— 不给"手滑点一下花掉几十刀"的机会。
MAX_BATCH_EVENTS = 30


@eval_bp.route("/api/tools/persona-eval-batch", methods=["POST"])
@require_api_key
def persona_eval_batch():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "请求体必须是 JSON 对象"}), 400

    event_ids = body.get("event_ids") or []
    if not isinstance(event_ids, list) or not event_ids:
        return jsonify({"error": "event_ids 必填，且必须是非空数组"}), 400
    if len(event_ids) > MAX_BATCH_EVENTS:
        return jsonify({"error": f"单次批量评测最多 {MAX_BATCH_EVENTS} 条，"
                                 f"当前 {len(event_ids)} 条"}), 400
    if not body.get("confirm_cost"):
        return jsonify({"error": "批量评测会产生真实费用，请带 confirm_cost=true 再调用"}), 400

    active_personas, persona_source = load_personas()
    if not active_personas:
        return jsonify({"error": "当前没有任何启用的评测 Agent"}), 409

    only = body.get("persona_ids")
    if isinstance(only, list) and only:
        active_personas = [p for p in active_personas if p["id"] in set(only)]
        if not active_personas:
            return jsonify({"error": "persona_ids 里没有一个是当前启用的 Agent"}), 400

    tracker = UsageTracker()
    batch_uid = str(uuid.uuid4())
    rows, failed = [], []

    # 串行跑各条新闻、每条新闻内部并发跑各 persona。不做二维全并发是刻意的：
    # 30 条 × 3 个 persona = 90 个并发请求会直接撞上 OpenAI 的速率限制，
    # 拿回一堆 429 比慢一点糟糕得多。
    for eid in event_ids:
        eid = str(eid).strip()
        meta = _fetch_event_full(eid)
        if meta is None:
            failed.append({"event_id": eid, "error": "news_events 里找不到这个 id"})
            continue
        body_text = meta.get("description_long_zh") or meta.get("description_short_zh") or ""
        news_text = f"{meta['title_zh']}\n{body_text}".strip()

        ok, errs = _run_personas(active_personas, news_text, tracker)
        run_uid = None
        try:
            run_uid = persona_store.record_run(
                input_mode="event_id", news_text=news_text, results=ok, errors=errs,
                event_id=eid, batch_uid=batch_uid,
                importance_score=meta.get("importance_score"),
                cost_usd=0,   # 单条不摊成本，总成本记在响应里；摊派会引入无意义的舍入误差
                model=MODEL,
            )
        except Exception:
            logger.exception(f"批量评测落库失败 event_id={eid}")

        rows.append({
            "event_id": eid, "run_uid": run_uid,
            "title": meta.get("title_zh"),
            "importance_score": (float(meta["importance_score"])
                                 if meta.get("importance_score") is not None else None),
            "scores": {r["persona_id"]: r["score"] for r in ok},
            "results": ok, "errors": errs,
        })

    # 每个 agent 在这一批里的均分——批量评测最直接的产出就是这个横向对比
    summary = []
    for p in active_personas:
        vals = [r["scores"][p["id"]] for r in rows if p["id"] in r["scores"]]
        summary.append({
            "persona_id": p["id"], "name": p["name"], "emoji": p.get("emoji"),
            "evaluated": len(vals),
            "avg_score": round(sum(vals) / len(vals), 2) if vals else None,
        })

    return jsonify({
        "batch_uid": batch_uid,
        "rows": rows,
        "failed": failed,
        "summary": summary,
        "personas": [{"id": p["id"], "name": p["name"], "emoji": p.get("emoji"),
                      "tagline": p.get("tagline")} for p in active_personas],
        "cost_usd": _chat_cost_usd(tracker),
        "model": MODEL,
        "persona_source": persona_source,
    })


# ══════════════════════════════════════════════════════════════════════
# 子 Tab 3: AB 对比 —— A/B 两组内容做重合度、质量、GSB（Good/Same/Bad）对比
# ══════════════════════════════════════════════════════════════════════
#
# 设计要点 / 成本控制（这个功能最容易失控地打大量 LLM 调用，尤其 GSB 逐条对比
# 如果写成 for 循环 + 单条调用会是 O(n) 次请求）：
#
#   - 每组硬上限 MAX_AB_ITEMS_PER_GROUP 条，超过直接 400 拒绝，不做静默截断
#     （静默截断会让用户以为对比了全部内容，实际只看了一部分，更危险）。
#   - 质量评估：数据库来源直接读库里已经打好的 importance_score/credibility_score/
#     is_rumor，零 LLM 成本；文本/图片来源才需要 LLM 估计，但整组 N 条打包进
#     一次 chat.completions 调用（结构化输出返回数组），不是每条一次。
#   - GSB 对比：同样是整组 pair 打包进一次调用，返回每条的 verdict + 总体结论，
#     不管 A 组有多少条都只有 1 次这个调用。
#   - Embedding：A 组 + B 组的标题一起送一次 embeddings 请求（复用 dedup.py 的
#     embed_texts，单批最多 128 条，两组各 30 条上限下天然落在一批内）。
#
#   一次完整的 ab-compare 请求，LLM/embedding 调用次数上限 =
#     (A组图片数 + B组图片数，如果是图片输入) + (0~2 次质量评估) + 1 次 embedding + 1 次 GSB
#   不随条数 N 线性增长调用次数，只有单次调用内的 token 数会随 N 增长。

MAX_AB_ITEMS_PER_GROUP = 30      # 每组最多条数（GSB 是信息量最大的一环，卡在这里）
MAX_AB_IMAGES_PER_GROUP = 10     # 图片输入每组最多张数，每张一次视觉调用

AB_DB_COLUMNS = (
    "id, title_zh, title_en, description_short_zh, sectors, "
    "importance_score, credibility_score, is_rumor, event_tier, "
    "date, time_event, source_names"
)


def _parse_ab_text(raw: str) -> list[dict]:
    """把粘贴的新闻文本切成条目列表。

    兼容两种最常见的粘贴习惯：
      1. 结构化分块：条与条之间用空行分隔，每块第一行是标题，其余行是摘要/正文。
      2. 纯标题列表：一行一条，中间没有空行——这种情况下整段文本会被 split
         成单个 block，此时退化为按行拆分，每条只有标题、无摘要。
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", raw) if b.strip()]
    if len(blocks) <= 1:
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if len(lines) > 1:
            return [{"title": ln, "summary": ""} for ln in lines]
        blocks = [raw]
    items = []
    for b in blocks:
        lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
        if not lines:
            continue
        items.append({"title": lines[0], "summary": " ".join(lines[1:])})
    return items


def _fetch_ab_items_from_db(sector: str, limit: int, sort: str,
                             date_from: str | None, date_to: str | None) -> list[dict]:
    """一键填充：查 news_events，返回带真实 importance/credibility/is_rumor 的条目。

    查询写法与 api/server.py 的 get_news() 保持一致（JSON_CONTAINS 做板块过滤），
    但本文件按约定不 import server.py（避免循环耦合），独立实现一份等价逻辑。
    """
    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor(dictionary=True)
        where = ["1=1"]
        params: list = []
        if sector and sector not in ("__all__", "all"):
            where.append("JSON_CONTAINS(sectors, %s)")
            params.append(json.dumps(sector))
        if date_from:
            where.append("date >= %s")
            params.append(date_from)
        if date_to:
            where.append("date <= %s")
            params.append(date_to)
        order = "importance_score DESC" if sort != "date" else "time_get_data DESC"
        sql = (f"SELECT {AB_DB_COLUMNS} FROM news_events WHERE {' AND '.join(where)} "
               f"ORDER BY {order} LIMIT %s")
        params.append(limit)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    items = []
    for r in rows:
        try:
            source_names = json.loads(r["source_names"]) if r.get("source_names") else []
        except Exception:
            source_names = []
        items.append({
            "title": r.get("title_zh") or r.get("title_en") or "",
            "summary": r.get("description_short_zh") or "",
            "source": ", ".join(source_names[:2]),
            "importance_score": float(r["importance_score"]) if r.get("importance_score") is not None else None,
            "credibility_score": float(r["credibility_score"]) if r.get("credibility_score") is not None else None,
            "is_rumor": bool(r["is_rumor"]) if r.get("is_rumor") is not None else None,
            "event_tier": r.get("event_tier"),
            "date": str(r.get("date") or ""),
            "event_id": r.get("id"),
        })
    return items


def _ab_items_from_images(files, tracker: UsageTracker) -> tuple[list[dict], dict]:
    """AB 对比的图片输入：完全复用 Duplicate Tester 已验证过的视觉提取逻辑，每张图一次调用。"""
    if len(files) > MAX_AB_IMAGES_PER_GROUP:
        raise ValueError(f"单组最多上传 {MAX_AB_IMAGES_PER_GROUP} 张图片，本次收到 {len(files)} 张")

    images = []
    for idx, f in enumerate(files):
        mime = f.mimetype or ""
        if mime not in ALLOWED_IMAGE_TYPES:
            raise ValueError(f"第 {idx+1} 张图片格式不支持（{mime}），仅支持 png/jpg/webp/gif")
        content = f.read()
        if len(content) > MAX_IMAGE_BYTES:
            raise ValueError(f"第 {idx+1} 张图片超过 {MAX_IMAGE_BYTES // (1024*1024)}MB 上限")
        images.append((idx, f.filename or f"image_{idx}", content, mime))

    errors: dict = {}
    items: list[dict] = []

    def _process(item):
        idx, name, content, mime = item
        try:
            return idx, _extract_headlines_from_image(content, mime, tracker), None
        except Exception as e:
            logger.warning(f"AB compare image extraction failed for image {idx} ({name}): {e}")
            return idx, [], str(e)

    with cf.ThreadPoolExecutor(max_workers=min(8, len(images))) as pool:
        results = list(pool.map(_process, images))
    results.sort(key=lambda x: x[0])

    for idx, headlines, err in results:
        if err:
            errors[idx] = err
        for h in headlines:
            title = (h.get("title") or "").strip()
            if not title:
                continue
            items.append({"title": title, "summary": "", "source": h.get("source", "")})
    return items, errors


def _resolve_ab_group(prefix: str, tracker: UsageTracker) -> tuple[list[dict], str, dict]:
    """按 `group_a_*` / `group_b_*` 表单字段前缀解析出一组标准化条目。

    返回 (items, source_mode, meta)：source_mode 是 "db"/"text"/"image"，决定
    下游质量对比是直接读库字段还是要调 LLM 估计；meta 目前只装图片处理的部分失败信息。
    """
    # 必须显式声明 mode。原来这里是 `or "db"` 兜底，后果很实在：一个空请求
    # （JSON body 而非 FormData、前端 bug、误发的 curl）会被静默当成"数据库
    # 一键填充"，拉 20 条最新事件跑完整的 embedding + GSB，白花约 $0.024，
    # 还返回一份没人要的"对比结果"。2026-07-26 QA 套件实测抓到（当时真扣了钱）。
    # 前端一直显式发 group_x_mode（web/index.html buildAbFormDataForGroup），
    # 所以要求显式声明不影响正常流程。
    raw_mode = (request.form.get(f"{prefix}_mode") or "").strip().lower()
    if not raw_mode:
        raise ValueError(
            f"{prefix}：缺少 {prefix}_mode 参数，无法判断数据来源。"
            f"请显式指定 db / text / image —— 拒绝默认执行是为了避免误发的请求"
            f"白白产生 LLM 费用")
    if raw_mode not in ("db", "text", "image"):
        raise ValueError(f"{prefix}：不支持的 {prefix}_mode='{raw_mode}'，"
                         f"只接受 db / text / image")
    mode = raw_mode
    meta: dict = {}

    if mode == "text":
        items = _parse_ab_text(request.form.get(f"{prefix}_text") or "")
    elif mode == "image":
        files = request.files.getlist(f"{prefix}_images")
        if not files:
            raise ValueError(f"{prefix}：选择了「上传截图」但未附带任何图片")
        items, errors = _ab_items_from_images(files, tracker)
        if errors:
            meta["image_errors"] = errors
    else:   # mode == "db"
        sector = (request.form.get(f"{prefix}_sector") or "").strip()
        try:
            limit = min(int(request.form.get(f"{prefix}_limit") or 20), MAX_AB_ITEMS_PER_GROUP)
        except ValueError:
            limit = 20
        limit = max(1, limit)
        sort = request.form.get(f"{prefix}_sort") or "importance"
        date_from = request.form.get(f"{prefix}_date_from") or None
        date_to = request.form.get(f"{prefix}_date_to") or None
        items = _fetch_ab_items_from_db(sector, limit, sort, date_from, date_to)

    if len(items) > MAX_AB_ITEMS_PER_GROUP:
        raise ValueError(
            f"{prefix} 组解析出 {len(items)} 条，超过单组上限 {MAX_AB_ITEMS_PER_GROUP} 条，"
            f"请裁剪内容或缩小数据库筛选范围后重试"
        )
    return items, mode, meta


def _ab_embedding_text(item: dict) -> str:
    return f"{item.get('title', '')}. {item.get('summary', '')}"[:1000]


_AB_QUALITY_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "ab_quality_assessment",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "importance_score": {"type": "number"},
                            "credibility_score": {"type": "number"},
                            "is_rumor": {"type": "boolean"},
                        },
                        "required": ["index", "importance_score", "credibility_score", "is_rumor"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    },
}

_AB_QUALITY_PROMPT = (
    "You are evaluating a list of crypto/macro news headlines (with optional short summaries), "
    "using the same rubric as our production scoring pipeline:\n"
    "- importance_score: 0.0 (trivial noise / routine PR / tiny-cap gossip) to 1.0 (market-moving "
    "major event with broad impact).\n"
    "- credibility_score: 0.0 (unverifiable single anonymous-source claim or rumor) to 1.0 (officially "
    "confirmed by an authoritative source, or cross-confirmed by multiple independent outlets).\n"
    "- is_rumor: true if the item reads as an unconfirmed rumor / allegation / \"sources say\" style "
    "claim without official confirmation; false otherwise.\n\n"
    "Score EVERY item below independently and return one object per item, in the same order given, "
    "with the matching zero-based `index`. Items:\n\n"
)


def _assess_ab_quality(items: list[dict], tracker: UsageTracker) -> None:
    """给非数据库来源的一组条目补上 importance/credibility/is_rumor 的 LLM 估计值。

    只调一次 API（把整组条目打包进一个 prompt），不随条数线性增长调用次数——
    这是本功能成本控制的核心手段之一。原地修改 items，不返回新列表。
    """
    if not items:
        return
    lines = [f"[{i}] {(it.get('title','') + ' ' + it.get('summary','')).strip()[:400]}"
             for i, it in enumerate(items)]
    prompt = _AB_QUALITY_PROMPT + "\n".join(lines)

    resp = get_client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=_AB_QUALITY_SCHEMA,
        max_completion_tokens=min(4000, 200 + 60 * len(items)),
    )
    tracker.record_chat(getattr(resp, "usage", None))
    data = json.loads(resp.choices[0].message.content)
    by_index = {r["index"]: r for r in data.get("items", [])}
    for i, it in enumerate(items):
        r = by_index.get(i)
        if r:
            it["importance_score"] = float(r["importance_score"])
            it["credibility_score"] = float(r["credibility_score"])
            it["is_rumor"] = bool(r["is_rumor"])
        else:
            it.setdefault("importance_score", None)
            it.setdefault("credibility_score", None)
            it.setdefault("is_rumor", None)


def _quality_summary(items: list[dict]) -> dict:
    scored = [it["importance_score"] for it in items if it.get("importance_score") is not None]
    cred = [it["credibility_score"] for it in items if it.get("credibility_score") is not None]
    rumor = [it["is_rumor"] for it in items if it.get("is_rumor") is not None]
    return {
        "n": len(items),
        "avg_importance_score": round(sum(scored) / len(scored), 4) if scored else None,
        "avg_credibility_score": round(sum(cred) / len(cred), 4) if cred else None,
        "rumor_rate": round(sum(1 for r in rumor if r) / len(rumor), 4) if rumor else None,
    }


_AB_GSB_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "gsb_comparison",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "judgments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "a_index": {"type": "integer"},
                            "verdict": {"type": "string", "enum": ["good", "same", "bad"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["a_index", "verdict", "reason"],
                        "additionalProperties": False,
                    },
                },
                "overall_conclusion": {"type": "string"},
                "a_strengths": {"type": "string"},
                "b_strengths": {"type": "string"},
            },
            "required": ["judgments", "overall_conclusion", "a_strengths", "b_strengths"],
            "additionalProperties": False,
        },
    },
}

# GSB（Good/Same/Bad）：搜索/推荐排序质量评估的标准方法论，Lawrence 提供的两份原始
# 产品方案文档（[0806][RCMD]深度解析widget L2 系列）里 Macro Insight 一份的 A/B 对比
# 表格中，评测列本身就叫「GSB对比」，与 docs/PROJECT_PLAN.md 第四节记录的
# "人工 + AI 双重评测"一脉相承。本实现把逐条判定交给 LLM（而非人工），
# 判定对象是"A 组每条 vs 它在 B 组里 embedding 最相似的对应内容"——不受重合度
# 判定用的 0.82 阈值限制（那个阈值是"是否为同一事件"，这里只是"找最接近的参照物"）。
_AB_GSB_PROMPT_HEAD = (
    "You are running a GSB (Good / Same / Bad) side-by-side evaluation — the standard methodology "
    "used in search and recommendation ranking quality evaluation, comparing two ranked/curated lists "
    "drawn from the same underlying content pool. This is for a Binance B9 crypto news recommendation "
    "feed.\n\n"
    "Below is a list of paired items: each A-group item is paired with its closest counterpart from "
    "the B-group (matched by title/content embedding similarity — the pairing itself is already done "
    "for you; you only judge quality). For EACH pair, decide, from the perspective of a crypto news "
    "feed reader, whether the A item is:\n"
    "  - \"good\": A is clearly BETTER than its B counterpart (more timely, more important, more "
    "authoritative/credible, less redundant/noisy — or the B counterpart is a poor/irrelevant match, "
    "meaning A covers something valuable that B's list is missing)\n"
    "  - \"same\": A and its B counterpart are roughly equivalent in value to a reader\n"
    "  - \"bad\": A is clearly WORSE than its B counterpart (less important, less credible, more "
    "rumor-like, redundant, or lower overall quality)\n\n"
    "Judge every pair independently and in order, referencing its a_index, with a short one-sentence "
    "reason. Then ALSO give an overall verdict comparing the two groups as a whole based on the "
    "aggregate pattern across all pairs (not just one example): overall_conclusion (2-3 sentences on "
    "which group is generally stronger and why — e.g. 'A组在时效性上更强，B组在权威性上更强'-style "
    "conclusions are exactly what's wanted), a_strengths (short phrase: what A group does better), "
    "b_strengths (short phrase: what B group does better).\n\n"
    "Pairs:\n\n"
)


def _run_ab_gsb(pairs: list[dict], tracker: UsageTracker) -> dict:
    """批量 GSB 对比：所有 pair 打包进同一个 prompt 一次性判断，不逐条调用。"""
    if not pairs:
        return {"judgments": [], "overall_conclusion": "", "a_strengths": "", "b_strengths": ""}

    lines = [
        f"Pair a_index={p['a_index']} (embedding similarity to its closest B match: "
        f"{p['similarity']:.3f}):\n  A: {p['a_text'][:300]}\n  B (closest match): {p['b_text'][:300]}"
        for p in pairs
    ]
    prompt = _AB_GSB_PROMPT_HEAD + "\n\n".join(lines)

    resp = get_client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=_AB_GSB_SCHEMA,
        max_completion_tokens=min(8000, 500 + 150 * len(pairs)),
    )
    tracker.record_chat(getattr(resp, "usage", None))
    return json.loads(resp.choices[0].message.content)


def _greedy_match(sim: np.ndarray, n_a: int, n_b: int, threshold: float) -> list[tuple[int, int, float]]:
    """重合度判定：把相似度 >= threshold 的 (a,b) 候选对按相似度从高到低贪心一对一匹配，
    避免同一个 B 条目被多个 A 条目重复认领而虚增重合度。"""
    candidates = [
        (float(sim[i, j]), i, j)
        for i in range(n_a) for j in range(n_b)
        if sim[i, j] >= threshold
    ]
    candidates.sort(key=lambda x: -x[0])
    used_a, used_b, matched = set(), set(), []
    for s, i, j in candidates:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        matched.append((i, j, s))
    return matched


def _build_ab_tsv(pairs_out: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
    # "是否重合"是 A 条目自身的判定（与上面 overlap.matched_count 同一份结果），
    # 和"B序号(最相似)"不是同一个口径，所以额外导出一列重合判定实际配上的 B 序号，
    # 避免读表的人看到"重合=是、但 B 序号是另一条"时以为哪里算错了。
    writer.writerow(["A序号", "A标题", "B序号(最相似)", "B标题", "相似度",
                     "A是否与B组重合", "重合配对B序号", "GSB判定", "判定理由"])
    for p in pairs_out:
        ob = p.get("overlap_b_index")
        writer.writerow([
            p["a_index"], p["a_title"], p["b_index"], p["b_title"],
            f"{p['similarity']:.3f}", "是" if p["is_overlap"] else "否",
            "" if ob is None else ob,
            p["verdict"], p["reason"],
        ])
    return buf.getvalue()


@eval_bp.route("/api/tools/ab-compare", methods=["POST"])
@require_api_key
def ab_compare():
    tracker = UsageTracker()

    try:
        items_a, mode_a, meta_a = _resolve_ab_group("group_a", tracker)
        items_b, mode_b, meta_b = _resolve_ab_group("group_b", tracker)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("ab_compare input resolution failed")
        return jsonify({"error": f"输入处理失败：{e}"}), 502

    if not items_a or not items_b:
        return jsonify({"error": "A、B 两组都需要至少 1 条内容才能对比"}), 400

    # ── 质量：db 来源直接用库里真实字段（零成本）；非 db 来源批量调 1 次 LLM 补齐 ──
    try:
        if mode_a != "db":
            _assess_ab_quality(items_a, tracker)
        if mode_b != "db":
            _assess_ab_quality(items_b, tracker)
    except Exception as e:
        logger.exception("ab_compare quality assessment failed")
        return jsonify({"error": f"质量评估失败：{e}"}), 502

    # ── Embedding：A+B 合并成一批一次调用 ──
    # 这一步是整个 ab-compare 的地基：重合度、GSB 的配对全都建立在这个相似度矩阵上。
    # 算不出来就必须当场中止——继续往下走会拿一个全零矩阵去配对，然后照常烧掉后面
    # GSB 那次 LLM 调用（本请求里最贵的一次），产出的结论完全无意义（见 _embed_or_fail
    # 上面的说明）。宁可让用户重试，也不要花钱买一份垃圾结论。
    try:
        texts = [_ab_embedding_text(it) for it in items_a] + [_ab_embedding_text(it) for it in items_b]
        vectors = _embed_or_fail(texts, tracker)
    except EmbeddingUnavailable as e:
        logger.error(f"ab_compare embedding unavailable, aborting before GSB: {e}")
        return jsonify({
            "error": f"向量计算失败，已中止本次对比：{e}",
            "hint": "重合度与 GSB 配对都依赖这一步的相似度矩阵，算不出来就不会继续调用 "
                    "GSB（避免白花钱得到一份无意义的结论）。请稍后重试；持续失败请检查 "
                    "OPENAI_API_KEY 与 embeddings 上游是否可用。",
            "cost_usd": _chat_cost_usd(tracker),      # 此前的视觉/质量评估已经花掉的钱，如实报出
            "cost_breakdown": tracker.snapshot(),
        }), 502
    except Exception as e:
        logger.exception("ab_compare embedding failed")
        return jsonify({"error": f"向量计算失败：{e}"}), 502

    n_a, n_b = len(items_a), len(items_b)
    va, vb = vectors[:n_a], vectors[n_a:]
    sim = va @ vb.T  # n_a x n_b，向量已归一化，点积即余弦

    # ── 重合度：贪心一对一匹配，>= COSINE_THRESHOLD（复用 dedup.py 标定值）判为同一事件 ──
    matched = _greedy_match(sim, n_a, n_b, COSINE_THRESHOLD)
    matched_map = {i: j for i, j, s in matched}
    denom = n_a + n_b - len(matched)
    overlap = {
        "matched_count": len(matched),
        "overlap_rate_a": round(len(matched) / n_a, 4) if n_a else 0.0,
        "overlap_rate_b": round(len(matched) / n_b, 4) if n_b else 0.0,
        "jaccard": round(len(matched) / denom, 4) if denom > 0 else 0.0,
        "a_only_count": n_a - len(matched),
        "b_only_count": n_b - len(matched),
        "cosine_threshold_used": COSINE_THRESHOLD,
    }

    # ── GSB：每条 A 找 B 里最相似的对应项（最近邻，不受阈值限制），批量一次调用判定 ──
    gsb_pairs_input = [
        {
            "a_index": i, "b_index": int(np.argmax(sim[i])), "similarity": float(np.max(sim[i])),
            "a_text": _ab_embedding_text(items_a[i]),
            "b_text": _ab_embedding_text(items_b[int(np.argmax(sim[i]))]),
        }
        for i in range(n_a)
    ]

    try:
        gsb_raw = _run_ab_gsb(gsb_pairs_input, tracker)
    except Exception as e:
        logger.exception("ab_compare GSB judgment failed")
        return jsonify({"error": f"GSB 对比失败：{e}"}), 502

    verdict_by_a = {j["a_index"]: j for j in gsb_raw.get("judgments", [])}
    counts = {"good": 0, "same": 0, "bad": 0}
    pairs_out = []
    for p in gsb_pairs_input:
        v = verdict_by_a.get(p["a_index"])
        verdict = v["verdict"] if v and v.get("verdict") in counts else "same"
        reason = v["reason"] if v else "（LLM 未返回该条判定，按 same 兜底）"
        counts[verdict] += 1
        # is_overlap 必须直接取重合度那一步的判定结果，不能拿贪心匹配的结果去和
        # 最近邻比对。两者本来就不是一回事：重合度用的是贪心一对一匹配（同一个 B
        # 只能被一个 A 认领），GSB 用的是不受阈值限制的最近邻。当 A_i 被贪心匹配
        # 给了 B_j、但它的最近邻是另一条 B_k 时，旧写法（matched_map.get(i) == b_index）
        # 会在这一行显示"否"，而上面的 overlap.matched_count 已经把 A_i 算成重合了
        # ——同一个事实在同一份响应里自相矛盾。现在统一成"这条 A 是否被判为与 B 组
        # 重合"这一个判定，配对是哪一条另外用 overlap_b_index 说明。
        overlap_b = matched_map.get(p["a_index"])
        pairs_out.append({
            "a_index": p["a_index"], "a_title": items_a[p["a_index"]]["title"],
            "b_index": p["b_index"], "b_title": items_b[p["b_index"]]["title"],
            "similarity": round(p["similarity"], 4),
            "is_overlap": overlap_b is not None,
            # 重合判定实际配上的 B 序号；正常就等于 b_index（最近邻），
            # 只有"最近邻已被别的 A 认领"这种情况才会不同，None 表示未判为重合。
            "overlap_b_index": overlap_b,
            "verdict": verdict, "reason": reason,
        })
    total_judged = sum(counts.values()) or 1
    gsb = {
        "pairs": pairs_out,
        "counts": counts,
        "rates": {k: round(v / total_judged, 4) for k, v in counts.items()},
        "overall_conclusion": gsb_raw.get("overall_conclusion", ""),
        "a_strengths": gsb_raw.get("a_strengths", ""),
        "b_strengths": gsb_raw.get("b_strengths", ""),
    }

    quality = {
        "group_a": _quality_summary(items_a),
        "group_b": _quality_summary(items_b),
        "source": {"group_a": mode_a, "group_b": mode_b},
    }

    warnings = []
    if meta_a.get("image_errors"):
        warnings.append({"group": "a", "image_errors": meta_a["image_errors"]})
    if meta_b.get("image_errors"):
        warnings.append({"group": "b", "image_errors": meta_b["image_errors"]})

    return jsonify({
        "group_a": {"source_mode": mode_a, "count": n_a, "items": items_a},
        "group_b": {"source_mode": mode_b, "count": n_b, "items": items_b},
        "overlap": overlap,
        "quality": quality,
        "gsb": gsb,
        "table_csv": _build_ab_tsv(pairs_out),
        "warnings": warnings,
        "cost_usd": _chat_cost_usd(tracker),
        "cost_breakdown": tracker.snapshot(),
        "model": MODEL,
        "cosine_threshold_used": COSINE_THRESHOLD,
        "max_items_per_group": MAX_AB_ITEMS_PER_GROUP,
    })
