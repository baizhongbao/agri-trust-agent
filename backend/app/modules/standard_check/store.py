"""轻量检索层：向量 + BM25 混合召回，可选 cross-encoder 重排。

为什么暂时不用 FAISS / Chroma：
    Demo 阶段语料只有几十到几百条，纯 Python 完全够用，
    而且 Windows 开发机上不需要任何额外二进制依赖。
    接口刻意做成和向量库一致的 build / search 形态，
    因此在 Linux 主力机上换成 chroma 时，上层代码不需要改动。

两级排序的动机：
    第一级（召回）：向量抓语义、BM25 抓关键词，两者加权，
        在中文小语料上明显比任一单独方案稳，但都属"粗排"。
    第二级（精排）：由 RerankProvider 对候选逐条打分。
        重排模型是跨编码器，query 与文档同时进模型，能显著提升首条命中率，
        这正是"标准校验"最看重的一点。
    重排是可选增强：未启用或调用失败时，静默退回第一级排序，不影响可用性。
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from app.core.providers.base import EmbeddingProvider, RerankProvider

logger = logging.getLogger(__name__)

# 单字 + 双字组合，避免引入 jieba 这类词典依赖
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fa5]")

# BM25 参数：业界常用取值
_BM25_K1 = 1.5
_BM25_B = 0.75

# 向量分与 BM25 分的权重
_W_VECTOR = 0.5
_W_BM25 = 0.5

# 重排候选规模：召回要刻意"多取一些"再精排，否则重排无从发挥
_RERANK_CANDIDATE_MULTIPLIER = 4
_RERANK_MIN_CANDIDATES = 10


def tokenize(text: str) -> list[str]:
    """中文按字组成 bigram，英文数字按词切分。"""
    tokens: list[str] = []
    cjk: list[str] = []

    def flush() -> None:
        if cjk:
            tokens.extend(cjk)
            tokens.extend(a + b for a, b in zip(cjk, cjk[1:]))
            cjk.clear()

    for match in _TOKEN_RE.finditer((text or "").lower()):
        piece = match.group(0)
        if len(piece) == 1 and not piece.isascii():
            cjk.append(piece)
        else:
            flush()
            tokens.append(piece)
    flush()
    return tokens


@dataclass
class SearchHit:
    """一条检索结果。

    三个分数都保留，是为了让排序过程可复核：
    vector/bm25 说明召回阶段怎么看，rerank 说明精排阶段怎么看。
    """

    item: dict[str, Any]
    score: float
    vector_score: float
    bm25_score: float
    rerank_score: float | None = None
    reranked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.item,
            "score": self.score,
            "vector_score": self.vector_score,
            "bm25_score": self.bm25_score,
            "rerank_score": self.rerank_score,
            "reranked": self.reranked,
        }


class SimpleVectorStore:
    """内存向量库，支持混合排序。"""

    def __init__(self) -> None:
        self._embedder: EmbeddingProvider | None = None
        self._reranker: RerankProvider | None = None
        self._items: list[dict[str, Any]] = []
        self._vectors: list[list[float]] = []
        self._token_counts: list[Counter[str]] = []
        self._doc_freq: Counter[str] = Counter()
        self._avg_len: float = 0.0
        self._ready = False

    @property
    def size(self) -> int:
        return len(self._items)

    @property
    def ready(self) -> bool:
        return self._ready

    # ---------------- 建库 ----------------

    def build(
        self,
        items: Iterable[dict[str, Any]],
        embedder: EmbeddingProvider,
        reranker: RerankProvider | None = None,
    ) -> None:
        self._embedder = embedder
        # 只有"声称就绪"的重排实现才挂上去，避免每次检索都白跑一次判定
        self._reranker = reranker if reranker is not None and reranker.is_ready() else None
        self._items = [dict(item) for item in items]
        texts = [str(item.get("text", "")) for item in self._items]

        self._vectors = embedder.embed(texts).vectors if texts else []

        self._token_counts = [Counter(tokenize(t)) for t in texts]
        self._doc_freq = Counter()
        for counts in self._token_counts:
            self._doc_freq.update(counts.keys())

        total = sum(sum(c.values()) for c in self._token_counts)
        self._avg_len = total / len(self._token_counts) if self._token_counts else 0.0

        self._ready = bool(self._items) and len(self._vectors) == len(self._items)
        logger.info(
            "检索库建成：%d 条，向量维度 %d，提供者 %s，重排 %s",
            len(self._items),
            embedder.dim,
            embedder.name,
            self._reranker.model if self._reranker else "未启用",
        )

    # ---------------- 打分 ----------------

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        # 向量均已 L2 归一化，点积即余弦相似度
        return sum(x * y for x, y in zip(a, b))

    def _bm25(self, query_tokens: list[str], index: int) -> float:
        counts = self._token_counts[index]
        if not counts:
            return 0.0

        doc_len = sum(counts.values())
        total_docs = len(self._token_counts)
        avg_len = self._avg_len or 1.0

        score = 0.0
        for token in query_tokens:
            freq = counts.get(token, 0)
            if not freq:
                continue
            doc_freq = self._doc_freq.get(token, 0)
            idf = math.log(1 + (total_docs - doc_freq + 0.5) / (doc_freq + 0.5))
            denominator = freq + _BM25_K1 * (1 - _BM25_B + _BM25_B * doc_len / avg_len)
            score += idf * (freq * (_BM25_K1 + 1)) / denominator
        return score

    # ---------------- 精排 ----------------

    def _rerank(self, query: str, hits: list[SearchHit], top_k: int) -> list[SearchHit]:
        """对召回结果做 cross-encoder 精排。

        任何异常都只降级、不抛出：重排是增强项，
        不能因为第三方接口抖动就让整条校验链路失败。
        """
        if not self._reranker or not hits:
            return hits

        candidate_count = min(
            len(hits), max(top_k * _RERANK_CANDIDATE_MULTIPLIER, _RERANK_MIN_CANDIDATES)
        )
        candidates = hits[:candidate_count]
        documents = [str(hit.item.get("text", "")) for hit in candidates]

        try:
            result = self._reranker.rerank(query, documents, top_n=candidate_count)
        except Exception as exc:  # noqa: BLE001 —— 降级路径必须吞掉所有异常
            logger.warning("重排失败，保留混合召回排序：%s", exc)
            return hits

        scores = {hit.index: hit.score for hit in result.hits}
        for position, hit in enumerate(candidates):
            if position not in scores:
                continue
            hit.rerank_score = round(scores[position], 4)
            hit.score = hit.rerank_score
            hit.reranked = True

        # 未被重排打分的候选排在最后（理论上不会发生，接口返回的是全量子集）
        candidates.sort(
            key=lambda hit: hit.rerank_score if hit.rerank_score is not None else -1.0,
            reverse=True,
        )
        return candidates + hits[candidate_count:]

    # ---------------- 检索 ----------------

    def search(self, query: str, top_k: int = 5, min_score: float = 0.0) -> list[SearchHit]:
        if not self._ready or not self._embedder or not query.strip():
            return []

        query_vector = self._embedder.embed([query]).vectors[0]
        query_tokens = tokenize(query)

        scored: list[tuple[int, float, float]] = []
        for index in range(len(self._items)):
            vector_score = self._cosine(query_vector, self._vectors[index])
            bm25 = self._bm25(query_tokens, index)
            scored.append((index, vector_score, bm25))

        max_bm25 = max((b for _, _, b in scored), default=0.0) or 1.0

        hits: list[SearchHit] = []
        for index, vector_score, bm25 in scored:
            normalized_bm25 = bm25 / max_bm25
            score = _W_VECTOR * max(vector_score, 0.0) + _W_BM25 * normalized_bm25
            if score < min_score:
                continue
            hits.append(
                SearchHit(
                    item=self._items[index],
                    score=round(score, 4),
                    vector_score=round(vector_score, 4),
                    bm25_score=round(bm25, 4),
                )
            )

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return self._rerank(query, hits, top_k)[:top_k]
