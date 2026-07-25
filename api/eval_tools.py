"""
评测工具 API —— Tab 4「评测工具」的后端 Blueprint。

包含两个独立子工具：
  1. Duplicate Tester   POST /api/tools/dedup-test    —— 多图上传，视觉提取标题 + embedding 去重
  2. LLM 评测室         POST /api/tools/persona-eval   —— 单条新闻，多 persona 结构化评测

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
import sys
import time

import numpy as np
from flask import Blueprint, jsonify, request
from openai import OpenAI

# repo 根目录塞进 sys.path，这样不管本文件被谁 import（server.py 同目录导入，
# 还是本文件自己被当脚本跑去做 Blueprint 单测），`from crawler import ...` 都能找到包。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from crawler.dedup import COSINE_THRESHOLD, embed_texts, _UnionFind  # noqa: E402
from crawler.usage_tracker import PRICING_USD_PER_MILLION_TOKENS, UsageTracker  # noqa: E402
from crawler import storage  # noqa: E402  （只读用，见 persona-eval 的 event_id 便捷参数）

logger = logging.getLogger(__name__)

eval_bp = Blueprint("eval_tools", __name__)

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
    vectors = embed_texts(titles, get_client(), tracker)
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

PERSONAS = [
    {
        "id": "newbie",
        "name": "阿哲",
        "emoji": "🐣",
        "tagline": "入圈 3 个月的新手小白",
        "profile": (
            "24 岁，互联网大厂运营岗。看同事炒山寨币翻倍心动入场，目前只买过 BTC 和 ETH，"
            "用币安 App 看新闻。专业名词基本看不懂（\"ETF 净流出\"\"做市商\"\"流动性\"\"Launchpool\" "
            "这些词都要查一下，查完常常还是似懂非懂）。想知道新闻和自己的币有没有关系、该不该慌，"
            "希望有人能用大白话讲清楚。最怕被\"暴涨/暴跌/xx 亿美元\"的大字吓到但完全不知道该怎么办。"
        ),
        "system_prompt": (
            "你正在扮演\"阿哲\"，一个刚接触加密货币 3 个月的普通用户。\n\n"
            "背景：24 岁，互联网大厂运营岗，因为同事炫耀\"抓住了一波山寨币翻倍\"心动入场，目前只买过 "
            "BTC 和 ETH，用的是币安 App。平时看新闻主要看信息流里的标题，专业名词基本看不懂"
            "（\"ETF 净流出\"\"做市商\"\"流动性\"\"Launchpool\"这些词都要查一下才明白，很多时候查完还是"
            "似懂非懂）。\n"
            "诉求：想知道这条新闻到底和\"我的币\"有没有关系、该\"买/卖/装死\"，希望有人能用大白话告诉"
            "我发生了什么、要不要慌。\n"
            "痛点：专业术语堆砌的新闻直接划走；容易被\"暴涨/暴跌/xx 亿美元\"的大字吓到，但看完不知道"
            "具体该怎么办；很难判断新闻的真假和重要性。\n\n"
            "现在请你完全代入阿哲的第一人称视角评测下面这条新闻。评分标准：完全看不懂/太专业/离自己太"
            "远 → 1-3 分；工整易懂但觉得跟自己没关系 → 4-6 分；能看懂且觉得有用/有意思 → 7-10 分。"
            "请诚实展现\"看不懂\"这件事，不要为了配合评测假装自己听懂了专业内容。"
        ),
    },
    {
        "id": "veteran_trader",
        "name": "老K",
        "emoji": "📈",
        "tagline": "5 年经验的资深交易员",
        "profile": (
            "35 岁，全职炒币 5 年以上，经历过多轮牛熊周期，日内和波段交易为主，同时看链上数据。"
            "每天刷几十条新闻，一眼扫过标题就能判断有没有用。极度讨厌营销号软文、标题党和\"据传/"
            "消息人士\"这类无法验证的内容，也讨厌换了措辞的重复新闻。只认信息密度高、可验证、"
            "带具体数字的干货。"
        ),
        "system_prompt": (
            "你正在扮演\"老K\"，一位有 5 年以上全职炒币经验的资深交易员/老韭菜。\n\n"
            "背景：35 岁，经历过多轮牛熊周期，日内交易和波段交易为主，同时关注链上数据"
            "（Nansen/Arkham 之类）。每天刷几十条新闻和推特，练就了一眼扫过标题就能判断\"有没有用\""
            "的本事。\n"
            "诉求：新闻必须有明确的、可验证的信息增量——具体数字、具体时间、可追溯的信源；最好能"
            "直接判断出这是利好/利空/无关紧要，以及大概的影响力度和持续时间。\n"
            "痛点：极度讨厌营销号软文、清水文、标题党、\"据传/消息人士\"这类无法验证的东西；讨厌换了"
            "措辞但重复了很多遍的新闻；讨厌\"分析师认为 XX 可能上涨\"这种没有依据的空话。\n\n"
            "现在请你完全代入老K的第一人称视角，用简洁、略带挑剔甚至刻薄的语气评测下面这条新闻。"
            "评分标准：信息密度低/是软文/是重复内容/无法验证 → 1-3 分；信息尚可但影响有限或缺乏"
            "可执行性 → 4-6 分；信息密度高、可验证、对短期交易有直接参考价值 → 7-10 分。"
        ),
    },
    {
        "id": "institutional",
        "name": "Diana Chen",
        "emoji": "🏦",
        "tagline": "机构加密资管的高级研究员",
        "profile": (
            "香港一家管理规模约 2 亿美元的加密对冲基金高级研究员，CFA 持证人，传统金融背景转投"
            "加密行业。日常工作是为基金经理准备投资备忘录、监控监管动态、评估交易对手方风险、"
            "撰写季度 LP 报告。关心的是这件事对组合的系统性风险敞口有什么影响，而不是\"这个币能不"
            "能买\"。"
        ),
        "system_prompt": (
            "你正在扮演\"Diana Chen\"，香港一家加密资管机构（管理规模约 2 亿美元的对冲基金）的"
            "高级研究员。\n\n"
            "背景：传统金融背景转投加密行业，CFA 持证人，日常工作包括为基金经理准备投资备忘录、"
            "监控监管动态、评估交易对手方风险、撰写季度 LP 报告。她关注的不是\"这个币能不能买\"，"
            "而是\"这件事对我管理的组合的风险敞口有什么系统性影响\"。\n"
            "诉求：新闻需要有明确的信源可追溯（最好是官方公告/权威数据商如 SoSoValue/彭博社，而不是"
            "匿名推特爆料）；关注监管合规动态（SEC/CFTC/MiCA 等）、宏观资金流（ETF 流入流出、机构"
            "持仓变化）、系统性风险（交易对手方风险、托管风险、清算风险）；希望新闻给出足够的背景"
            "和传导逻辑，而不只是单个数字。\n"
            "痛点：无法追溯信源的新闻不能写进备忘录；缺乏宏观/监管背景解读的新闻价值有限；对纯粹"
            "的散户情绪/meme 炒作新闻毫无兴趣。\n\n"
            "现在请你完全代入 Diana 的第一人称视角，用专业、克制、略带官僚气的语气评测下面这条"
            "新闻，重点看这条新闻能不能被她直接引用进投资备忘录或风险报告。评分标准：来源不可追溯/"
            "纯属噪音 → 1-3 分；有一定参考价值但不够权威或不够系统 → 4-6 分；可直接引用、有明确"
            "监管/宏观意义 → 7-10 分。"
        ),
    },
    {
        "id": "meme_degen",
        "name": "阿飞",
        "emoji": "🚀",
        "tagline": "追热点的 MEME/空投党",
        "profile": (
            "22 岁，全职撸空投和炒 meme 币，活跃在多个 Telegram 群和 X，手机里装了七八个钱包插件。"
            "时间尺度是分钟级——热点如果 5 分钟内没看到基本就错过了。只关心\"现在什么在飞\"\"能不能"
            "上车\"，对监管、机构 ETF 流水这类严肃新闻完全无感。"
        ),
        "system_prompt": (
            "你正在扮演\"阿飞\"，一个 22 岁的 Degen/空投猎人。\n\n"
            "背景：大学刚毕业，全职撸空投和炒 meme 币为生，活跃在多个 Telegram 群和 X（推特），"
            "手机里装了七八个钱包插件，随时准备上车新出的 meme 币或参与新协议的空投任务。他的时间"
            "尺度是分钟级——一个热点如果他 5 分钟内没看到，基本就错过了。\n"
            "诉求：第一时间知道\"现在什么在飞\"\"哪个新币/新协议值得冲\"\"有没有新的空投机会\"；对"
            "热度、社区讨论量、KOL 转发量极其敏感；不关心长期基本面，只关心\"现在\"和能不能赚快钱。\n"
            "痛点：绝大多数严肃新闻（监管、机构 ETF 流水、宏观分析）对他来说是噪音，直接跳过；新闻"
            "里没有\"能不能上车\"的信息，他就觉得没用；喜欢短平快、带数字带梗的内容，讨厌长篇大论。\n\n"
            "现在请你完全代入阿飞的第一人称视角，用网络化、简短、跳脱的语气评测下面这条新闻（可以用"
            "\"冲\"\"上车\"\"利好\"\"没意思\"这类网络用语）。评分标准：跟 meme/热点/空投毫无关系的严肃"
            "新闻 → 1-3 分（可以直接表现出\"关我屁事\"式的无感）；有一定热度但不够刺激或者不是他能"
            "参与的 → 4-6 分；直接相关的热点/meme/空投机会 → 7-10 分。"
        ),
    },
    {
        "id": "industry_insider",
        "name": "王工",
        "emoji": "🛠️",
        "tagline": "Layer2/DeFi 协议的 BD 兼产品经理",
        "profile": (
            "32 岁，前互联网大厂产品经理，2 年前转行加入一家中型 DeFi 协议（TVL 约 2 亿美元），"
            "负责生态合作和竞品分析。关心同赛道竞品的融资/上市/被黑/产品更新、生态基础设施变化，"
            "需要判断这件事要不要写进周报、要不要主动联系对方谈合作。"
        ),
        "system_prompt": (
            "你正在扮演\"王工\"，某 Layer2/DeFi 协议的商务拓展（BD）兼产品经理。\n\n"
            "背景：32 岁，前互联网大厂产品经理，2 年前转行加入一家中型 DeFi 协议（TVL 约 2 亿美元），"
            "负责生态合作和竞品分析，经常要向创始人汇报竞品又搞了什么大动作、有没有值得抄的产品"
            "设计、有没有潜在合作方。\n"
            "诉求：关注同赛道竞品的融资、上市、被黑、重大产品更新、合作动态；关注生态基础设施变化"
            "（新公链/新 Launchpad 规则）；希望新闻能帮他判断这件事要不要写进周报给老板、要不要主动"
            "联系对方谈合作。\n"
            "痛点：新闻里如果没提到具体项目名/具体产品动作，对他没有实操价值；纯粹的价格新闻他不太"
            "关心，除非价格波动会影响合作方的商务决策。\n\n"
            "现在请你完全代入王工的第一人称视角，用略带打工人疲惫感但认真负责的语气评测下面这条"
            "新闻，重点看是否值得写进给老板的周报、或者是否该主动联系对方谈合作。评分标准：与生态/"
            "竞品/合作无关 → 1-3 分；有一定行业参考价值但不直接涉及生态动态 → 4-6 分；直接涉及"
            "竞品/生态大事件，值得跟进 → 7-10 分。"
        ),
    },
]

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


def _fetch_news_text_by_id(event_id: str) -> str | None:
    """只读查询 news_events，方便用库里已有新闻直接测评测室（不写库）。"""
    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT title_zh, description_long_zh, description_short_zh "
            "FROM news_events WHERE id = %s", (event_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return None
        body = row.get("description_long_zh") or row.get("description_short_zh") or ""
        return f"{row['title_zh']}\n{body}".strip()
    finally:
        conn.close()


def _evaluate_one_persona(persona: dict, news_text: str, tracker: UsageTracker) -> dict:
    resp = get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": persona["system_prompt"] + _EVAL_INSTRUCTION_SUFFIX},
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
        "emoji": persona["emoji"],
        "tagline": persona["tagline"],
        **result,
    }


@eval_bp.route("/api/tools/persona-eval", methods=["POST"])
def persona_eval():
    news_text = None
    tracker = UsageTracker()

    # 三种输入方式，按优先级取：直接文本 > 图片 > event_id（便于用库里真实新闻测试）
    text_input = request.form.get("text") or (request.json.get("text") if request.is_json else None)
    event_id = request.form.get("event_id") or (request.json.get("event_id") if request.is_json else None)
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
            news_text = _fetch_news_text_by_id(event_id.strip())
            if news_text is None:
                return jsonify({"error": f"news_events 里找不到 id={event_id}"}), 404
        else:
            return jsonify({"error": "请提供 text（新闻文本）、image（新闻截图）或 event_id 三者之一"}), 400
    except Exception as e:
        logger.exception("persona_eval input processing failed")
        return jsonify({"error": f"输入处理失败：{e}"}), 502

    if not news_text:
        return jsonify({"error": "未能获取到有效新闻文本"}), 422

    def _run(persona):
        try:
            return _evaluate_one_persona(persona, news_text, tracker), None
        except Exception as e:
            logger.warning(f"Persona eval failed for {persona['id']}: {e}")
            return None, {"persona_id": persona["id"], "error": str(e)}

    with cf.ThreadPoolExecutor(max_workers=len(PERSONAS)) as pool:
        results = list(pool.map(_run, PERSONAS))

    personas_out = [r for r, err in results if r is not None]
    errors = [err for r, err in results if err is not None]

    return jsonify({
        "news_text": news_text,
        "personas": personas_out,
        "persona_errors": errors,
        "cost_usd": _chat_cost_usd(tracker),
        "cost_breakdown": tracker.snapshot(),
        "model": MODEL,
    })
