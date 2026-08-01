"""
事件去重与聚合。

实现 skill 文档《Macro Insight v1》第三章「超重去重」的四层管线：

    DC-1  标题归一化后精确匹配      —— 去标点/信源前缀/大小写差异
    DC-2  事件三元组无条件归簇      —— (主体, 动作, 事件日期) 一致即同事件
    DC-3  embedding 语义聚类        —— cosine >= COSINE_THRESHOLD(实测标定 0.82)，48h 时间窗
    DC-4  跨轮归并                  —— 写库前与库中近期事件比对（见 storage.py）

修复背景（2026-07-26）：
此前 DC-1 / DC-2 / DC-4 三层完全没有实现，DC-3 用 TF-IDF **词频**相似度冒充语义
向量。TF-IDF 对同义改写天然失效——"Robinhood CEO 账号被黑推广骗局币" 和
"Robinhood CEO 社媒遭黑客发币" 讲的是同一件事，词面重合度却很低。结果事件库
841 条里有 149 条是重复（17.7%），单个事件最多占了 7 行。

三层的分工：DC-2 靠 LLM 抽取的结构化三元组做精确匹配，快且准，但依赖 LLM 每次
都吐出一致的 slug；DC-3 用语义向量兜底，抓 LLM slug 写法漂移的漏网之鱼。两张网
叠加，任一层命中即归簇。
"""
import hashlib
import logging
import math
import re
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)

# ── 可调参数 ─────────────────────────────────────────────────────────
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 256          # 降维：256 维足够判同事件，存库仅 1KB/条（默认 1536 维要 6KB）
EMBED_BATCH = 128        # 单次 embeddings 请求条数

# 语义归簇阈值。skill 文档写的是 0.65，但那个数字在真实数据上会严重过度合并——
# 2026-07-26 在 855 条真实事件（28 万配对）上做过分档抽样标定：
#
#     >= 0.95   全部真重复（"完成5250万美元WLD募资" vs "…融资"）
#     0.85-0.95 真重复（"BitMEX将于9月23日关闭" vs "…2026年9月23日关停"）
#     0.75-0.80 开始混入不同事件（"Dango 8月13日关闭" vs "Dango 7月29日停交易"）
#     0.65-0.70 基本都是不同事件（"AI开支担忧压制科技股" vs "特斯拉周跌18%"）
#
# 13 组人工标注配对上，"应合并"最低 0.859、"应分开"最高 0.761，中间有 0.098 的
# 干净空隙；0.78~0.85 区间错误率均为 0。取 0.82 居中，略偏精度一侧。
#
# 偏精度是有意的：DC-2 指纹层做的是精确匹配、不受阈值影响，召回已有保障；此时
# 向量层再往低调只会增加"把两件事当成一件"的风险——漏一条重复只是体验瑕疵，
# 错合并会让一个真实事件从库里彻底消失。两层互补，不该同时往召回方向调。
COSINE_THRESHOLD = 0.82

TIME_WINDOW_HOURS = 48   # 同簇要求事件时间差 <= 48h，防止"同主体不同事件"被误合并


# ── 标题归一化（DC-1）────────────────────────────────────────────────

# 中文媒体习惯在标题前加"XX 消息，"。同一事件经不同媒体转述，差别往往只在这个前缀。
_SOURCE_PREFIX_RE = re.compile(
    r"^(blockbeats|chaincatcher|panews|odaily|foresight|marsbit|金色财经|吴说|深潮|"
    r"律动|星球日报|链捕手)\s*(消息|讯|报道|newsflash)?\s*[,，:：]\s*",
    re.IGNORECASE,
)

# 归一化时剥掉的字符：空白、各类标点、emoji 区段。
# 注意不含 < >：数字归一化会用 <数值> 作为定界符，剥掉定界符会让
# "1" + "23" 和 "123" 归一成同一串，反而制造误归簇。
_NOISE_RE = re.compile(
    r"[\s\-—–~·|/\\_+*#@\"'`^&%$"
    r".,;:!?()\[\]{}"
    r"。，、；：！？（）【】《》「」『』“”‘’…"
    r"\U0001F300-\U0001FAFF☀-➿]+"
)

# 数字单位归一：把"3.11亿美元"/"$310.6M"/"310,600,000" 拉到同一量纲后再比较，
# 避免同一笔金额因写法不同而逃逸归簇。
_NUM_UNIT = {
    "亿": 1e8, "万": 1e4, "千": 1e3,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "m": 1e6, "mn": 1e6, "million": 1e6,
    "k": 1e3, "thousand": 1e3,
}
_NUM_RE = re.compile(
    r"(\d[\d,]*\.?\d*)\s*(亿|万|千|billion|million|thousand|bn|mn|b|m|k)?",
    re.IGNORECASE,
)


def _canonical_numbers(text: str) -> str:
    """把文本里的数字统一换算成整数量级表示，消除单位写法差异。"""
    def repl(match: re.Match) -> str:
        raw, unit = match.group(1), (match.group(2) or "").lower()
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            return match.group(0)
        return f"<{int(value * _NUM_UNIT.get(unit, 1))}>"
    return _NUM_RE.sub(repl, text)


def normalize_title(title: str) -> str:
    """DC-1 标题归一化：小写 → 去信源前缀 → 数字归一 → 去标点空白。

    >>> normalize_title("BlockBeats 消息，美国现货 BTC ETF 净流出 3.11 亿美元")
    '美国现货btcetf净流出<311000000>美元'
    """
    if not title:
        return ""
    text = title.strip().lower()
    text = _SOURCE_PREFIX_RE.sub("", text)
    text = _canonical_numbers(text)
    return _NOISE_RE.sub("", text)


# ── 事件指纹（DC-2）──────────────────────────────────────────────────

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    """把 LLM 输出的主体/动作压成稳定 slug，容忍大小写、空格、连字符差异。"""
    return _SLUG_RE.sub("_", (text or "").strip().lower()).strip("_")


def build_fingerprint(subject: str, action: str, event_date: str) -> str:
    """事件指纹 = sha256(主体|动作|事件日期)[:16]，同时用作 news_events.id。

    这是本次重构的关键：旧实现拿 LLM 改写后的 title_en 做 hash，同一事件每轮重写
    措辞不同 → id 不同 → ON DUPLICATE KEY UPDATE 形同虚设，直接插新行。改用三元组
    后，只要 LLM 认出的是同一件事，跨轮 id 就稳定，重复写入天然收敛成一次更新。

    主体或动作缺失时回退到 title_en，保证 id 永远非空（回退路径只影响该条自身的
    跨轮归并能力，由 DC-3 语义层兜底）。
    """
    subject_slug, action_slug = _slug(subject), _slug(action)
    if not subject_slug or not action_slug:
        return ""
    raw = f"{subject_slug}|{action_slug}|{(event_date or '')[:10]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def fallback_id(title_en: str, date_str: str) -> str:
    """LLM 没给出可用三元组时的兜底 id（等价于旧实现）。"""
    raw = f"{(title_en or '').lower().strip()}_{date_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Embedding（DC-3）─────────────────────────────────────────────────

def embed_texts(texts: list[str], client, tracker=None) -> np.ndarray:
    """批量取 embedding，返回 L2 归一化后的 (n, EMBED_DIM) 矩阵。

    已归一化，因此后续算余弦相似度只需矩阵乘法。整批失败时返回零矩阵——零向量
    之间余弦为 0，不会误归簇，等于自动降级为「只靠 DC-1/DC-2 去重」。

    `tracker`（crawler.usage_tracker.UsageTracker）不传则不计费统计，只影响
    成本监控，不影响去重功能本身。
    """
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)

    # client=None 是**成本闸关闭**时的显式约定（ADR-002）：没有可用的付费通道，
    # 直接退化为零向量，效果等同于"整批 embedding 失败"——零向量之间余弦为 0，
    # 不会误归簇，只是语义层不再贡献归并，DC-1/DC-2 规则去重照常工作。
    # 写成显式分支而不是让 None 掉进下面的 try/except：靠异常兜住能跑，
    # 但把"设计内的降级"和"真的出故障了"混成同一条日志，事后没法区分。
    if client is None:
        logger.info(f"embedding 通道不可用（成本闸关闭），{len(texts)} 条退化为零向量")
        return np.zeros((len(texts), EMBED_DIM), dtype=np.float32)

    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = [t[:8000] or " " for t in texts[start:start + EMBED_BATCH]]
        try:
            resp = client.embeddings.create(
                model=EMBED_MODEL, input=batch, dimensions=EMBED_DIM
            )
            vectors.extend(item.embedding for item in resp.data)
            if tracker is not None:
                tracker.record_embedding(getattr(resp, "usage", None))
        except Exception as e:
            logger.warning(f"Embedding batch @{start} failed: {e}")
            vectors.extend([0.0] * EMBED_DIM for _ in batch)

    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-9)


def _embeddings_with_cache(items: list[dict], client, tracker=None) -> np.ndarray:
    """组装向量矩阵：自带的直接用，缺的批量补算。

    2026-08-02（ADR-002 A4）加。此前每轮都把全部条目重新 embed 一遍，走的是
    VM 侧个人 key；现在 Mac 侧算 enrich 时顺手把向量一起算了（公司额度），
    这里只需要拼装。缺失的部分若拿不到 client（成本闸关闭）就留零向量，
    行为与从前的"整批失败"一致——不误归簇，只是不贡献语义信号。
    """
    n = len(items)
    matrix = np.zeros((n, EMBED_DIM), dtype=np.float32)
    missing_idx, missing_txt = [], []
    reused = 0
    for i, item in enumerate(items):
        vec = item.get("_embedding")
        if vec is not None and getattr(vec, "size", 0) == EMBED_DIM:
            matrix[i] = vec
            reused += 1
        else:
            missing_idx.append(i)
            missing_txt.append(embedding_text(item))

    if missing_txt:
        if client is None:
            # 只有"确实缺向量、又确实没有通道"时才是真降级，这时才该警告。
            logger.warning(
                f"语义去重降级：{len(missing_txt)}/{n} 条无向量且无可用 embedding "
                f"通道，这部分只靠 DC-1/DC-2 规则去重（同事件可能重复出现）。"
                f"通常意味着这批条目没经过 Mac 桥——检查桥是否在线。")
        fresh = embed_texts(missing_txt, client, tracker)
        for slot, i in enumerate(missing_idx):
            if slot < fresh.shape[0]:
                matrix[i] = fresh[slot]

    if reused:
        logger.info(f"Embedding: {reused}/{n} 复用缓存向量（公司额度算好的），"
                    f"{len(missing_idx)} 条需现算")
    # 复用的向量入库前已归一化，现算的 embed_texts 也归一化过，这里不重复归一
    return matrix


def embedding_text(item: dict) -> str:
    """构造送去做 embedding 的文本。

    统一用英文字段：LLM 已把中英文源都翻译成 title_en/description_short_en，
    在英文侧比对天然实现了文档要求的「跨语言归并」。
    """
    return f"{item.get('title_en', '')}. {item.get('description_short_en', '')}"[:1000]


# ── 工具：并查集 & 时间 ──────────────────────────────────────────────

class _UnionFind:
    """传递闭包成簇：A~B 相似、B~C 相似 → A/B/C 同簇。"""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # 路径压缩
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def parse_dt(value: str | None) -> datetime | None:
    """宽松解析 ISO8601，失败返回 None。"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _within_time_window(a: str | None, b: str | None) -> bool:
    """两条内容是否落在同一时间窗内。时间缺失时不阻断归簇（交给语义层判断）。"""
    ta, tb = parse_dt(a), parse_dt(b)
    if ta is None or tb is None:
        return True
    return abs((ta - tb).total_seconds()) <= TIME_WINDOW_HOURS * 3600


# ── 轮内聚合主流程 ───────────────────────────────────────────────────

def cluster_items(items: list[dict], embeddings: np.ndarray) -> list[list[int]]:
    """对本轮 enriched 条目分簇，返回每簇的下标列表。

    三层依次执行，任一层命中即 union：
      DC-1  归一化标题相同
      DC-2  事件指纹相同
      DC-3  余弦 >= COSINE_THRESHOLD（0.82，实测标定）且事件时间差 <= 48h
    """
    n = len(items)
    if n <= 1:
        return [[0]] if n == 1 else []

    uf = _UnionFind(n)

    # DC-1 + DC-2：用哈希桶做精确匹配，O(n)
    by_title: dict[str, int] = {}
    by_fingerprint: dict[str, int] = {}
    for i, item in enumerate(items):
        title_key = normalize_title(item.get("title_en", ""))
        if title_key:
            if title_key in by_title:
                uf.union(by_title[title_key], i)
            else:
                by_title[title_key] = i

        fp = item.get("event_fingerprint", "")
        if fp:
            if fp in by_fingerprint:
                uf.union(by_fingerprint[fp], i)
            else:
                by_fingerprint[fp] = i

    # DC-3：语义相似度。向量已归一化，点积即余弦
    if embeddings.shape[0] == n:
        sim = embeddings @ embeddings.T
        rows, cols = np.where(np.triu(sim, k=1) >= COSINE_THRESHOLD)
        for i, j in zip(rows.tolist(), cols.tolist()):
            if _within_time_window(items[i].get("published_at"),
                                   items[j].get("published_at")):
                uf.union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)
    return list(clusters.values())


def merge_cluster(group_items: list[dict], embeddings: list[np.ndarray]) -> dict:
    """把一簇合并成单个事件。

    代表条按文档「簇内保留规则」选取：权威最高 → 同权威取信息最完整者。
    其余条目的信源全部并入 sources / source_names，供前端展示「N 家报道」。
    """
    primary = max(
        group_items,
        key=lambda x: (x.get("authority", 0), len(x.get("description_short_en", ""))),
    )

    sources, seen_urls = [], set()
    for item in group_items:
        url = item.get("url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append({
            "name": item.get("source", ""),
            "url": url,
            "type": item.get("type", "rss"),
            "authority": item.get("authority", 3),
            "published_at": item.get("published_at", ""),
            "x_tweet_id": item.get("tweet_id"),
        })

    event = {**primary}
    # 编辑部 ticker 取全簇并集：同一件事的不同报道标注的 ticker 未必一样
    # （比如一家只标 MSFT、另一家标 MSFT+SPX），只取代表条会漏。
    all_symbols = []
    for item in group_items:
        for sym in (item.get("matched_symbols") or "").split(","):
            sym = sym.strip()
            if sym and sym not in all_symbols:
                all_symbols.append(sym)
    event["matched_symbols"] = ",".join(all_symbols)
    # 事件身份就是它的指纹——这是本次重构的核心：id 不再来自 LLM 改写的标题，
    # 所以同一事件跨轮重复抓到时 id 保持稳定，写库会走 UPDATE 而非 INSERT。
    # 跨轮归并若在库里找到既有行，会在 storage 层用既有 id 覆盖这里的值。
    event["id"] = primary.get("event_fingerprint") or fallback_id(
        primary.get("title_en", ""), (primary.get("published_at") or "")[:10]
    )
    event["cluster_id"] = event["id"]
    event["sources"] = sources
    # 独立信源数按主域名去重（X/lookonchain 和 X/EmberCN 算两个独立信源，
    # 但 BlockBeats快讯 和 BlockBeats文章 算一个）
    event["source_count"] = len({s["name"].split("/")[0] for s in sources})
    event["source_names"] = sorted({s["name"] for s in sources})
    event["is_verified"] = event["source_count"] >= 2
    event["merged_sources_count"] = len(group_items)

    # 簇向量取成员均值再归一化，比单取代表条更稳，供跨轮比对使用
    if embeddings:
        centroid = np.mean(np.stack(embeddings), axis=0)
        norm = float(np.linalg.norm(centroid))
        event["embedding"] = (centroid / norm if norm > 1e-9 else centroid).astype(np.float32)
    else:
        event["embedding"] = np.zeros(EMBED_DIM, dtype=np.float32)

    return event


def aggregate_events(items: list[dict], client, tracker=None) -> list[dict]:
    """本轮 enriched 条目 → 去重后的事件列表（DC-1 ~ DC-3）。"""
    if not items:
        return []

    # 优先用条目自带的向量（Mac 经公司网关随 enrich 算好的，ADR-002 A4）；
    # 只有缺的才需要现算。全部命中时 client 为 None 也无所谓——这正是
    # "成本闸关闭但语义去重照常工作"的关键：通道换了，语义没换（同模型同维度）。
    embeddings = _embeddings_with_cache(items, client, tracker)
    clusters = cluster_items(items, embeddings)

    events = []
    for group in clusters:
        group_items = [items[i] for i in group]
        group_vecs = [embeddings[i] for i in group] if embeddings.shape[0] == len(items) else []
        events.append(merge_cluster(group_items, group_vecs))

    logger.info(
        f"Aggregate: {len(items)} items → {len(events)} events "
        f"(folded {len(items) - len(events)})"
    )
    return events


# ── 向量存取（跨轮归并用，DC-4 见 storage.py）────────────────────────

def embedding_to_blob(vector) -> bytes | None:
    """np 向量 → BLOB（float32 紧凑存储，256 维 = 1024 字节）。"""
    if vector is None:
        return None
    array = np.asarray(vector, dtype=np.float32)
    return array.tobytes() if array.size == EMBED_DIM else None


def blob_to_embedding(blob: bytes | None) -> np.ndarray | None:
    """BLOB → np 向量，长度不符时返回 None（视为无向量，不参与语义归并）。"""
    if not blob:
        return None
    array = np.frombuffer(blob, dtype=np.float32)
    return array if array.size == EMBED_DIM else None


def cosine(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """余弦相似度。任一向量缺失或为零向量时返回 0（即「不相似」）。"""
    if a is None or b is None:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-9:
        return 0.0
    return float(np.dot(a, b) / denom)


def hours_between(a: str | None, b: str | None) -> float:
    """两个时间戳相差多少小时，无法解析时返回 inf。"""
    ta, tb = parse_dt(a), parse_dt(b)
    if ta is None or tb is None:
        return math.inf
    return abs((ta - tb).total_seconds()) / 3600
