"""标准校验服务。

把合同条款逐条送进检索库，返回最相关的标准条款及匹配分数。
分数与命中依据一并返回，让"为什么这条合同条款对应这个标准"可被复核——
这是"可信性"的落点。
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.core.providers.embedding import HashingEmbeddingProvider
from app.core.providers.registry import get_embedding_provider, get_rerank_provider
from app.modules.contract_parser import service as contract_service
from app.modules.standard_check import checklist, compliance, loader
from app.modules.standard_check.store import SearchHit, SimpleVectorStore

logger = logging.getLogger(__name__)

_EXCERPT_CHARS = 140


@lru_cache(maxsize=1)
def _store() -> SimpleVectorStore:
    """构建检索库（进程内单例）。

    若配置的向量化实现不可用（例如 EMBEDDING_PROVIDER=local 但没装 torch，
    或 cloud 但缺凭证），自动降级到零依赖的哈希向量，保证服务仍能启动、可演示。
    """
    embedder = get_embedding_provider()
    if not embedder.is_ready():
        logger.warning(
            "向量化实现 %s 未就绪（缺少依赖、模型或凭证），本次降级为 hashing",
            embedder.name,
        )
        embedder = HashingEmbeddingProvider(settings.embedding_dim_hashing)

    reranker = None
    if settings.rerank_enabled:
        candidate = get_rerank_provider()
        if candidate.is_ready():
            reranker = candidate
        elif candidate.name != "disabled":
            logger.warning(
                "重排实现 %s 未就绪（缺少凭证），本次不启用重排",
                candidate.name,
            )

    store = SimpleVectorStore()
    store.build(loader.load_items(), embedder, reranker)
    return store


def index_info() -> dict[str, Any]:
    store = _store()
    reranker = get_rerank_provider()
    return {
        "documents": store.size,
        "ready": store.ready,
        "vector_store_backend": settings.vector_store_backend,
        "standards_dir": str(settings.standards_path),
        "min_score": settings.retrieval_min_score,
        "top_k": settings.retrieval_top_k,
        "embedding": get_embedding_provider().describe(),
        "rerank": {
            "enabled": settings.rerank_enabled,
            **reranker.describe(),
        },
        "checklist": {
            "rules": len(checklist.load_checklist().rules),
            "file": checklist.checklist_file().name,
        },
        "standard_limits": len(compliance.load_limits()),
    }


def reindex() -> dict[str, Any]:
    """重建检索库。

    清单与标准限值都放在标准库目录里，重建时一并重读，
    避免改了语料还要重启进程才生效。
    """
    _store.cache_clear()
    checklist.load_checklist.cache_clear()
    compliance.load_limits.cache_clear()
    return index_info()


def search(query: str, top_k: int | None = None) -> list[SearchHit]:
    return _store().search(
        query,
        top_k=top_k or settings.retrieval_top_k,
        min_score=settings.retrieval_min_score,
    )


def _excerpt(text: str, limit: int = _EXCERPT_CHARS) -> str:
    compact = " ".join((text or "").split())
    return compact[:limit] + ("…" if len(compact) > limit else "")


def check_contract(
    doc_id: str,
    top_k: int | None = None,
    clause_limit: int = 20,
) -> dict[str, Any] | None:
    """逐条校验合同条款与标准库的对应关系。"""
    contract = contract_service.get_contract(doc_id)
    if contract is None:
        return None

    results: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for clause in contract.clauses[:clause_limit]:
        hits = search(clause.content, top_k=top_k)
        entry = {
            "clause_index": clause.index,
            "clause_title": clause.title,
            "clause_excerpt": _excerpt(clause.content),
            "matches": [hit.to_dict() for hit in hits],
        }
        results.append(entry)
        if not hits:
            unmatched.append(
                {
                    "clause_index": clause.index,
                    "clause_title": clause.title,
                    "clause_excerpt": entry["clause_excerpt"],
                }
            )

    total = len(results)
    matched = total - len(unmatched)

    return {
        "doc_id": doc_id,
        "contract_title": contract.title,
        "total_clauses": total,
        "matched_clauses": matched,
        "coverage": round(matched / total, 4) if total else 0.0,
        "unmatched_clauses": unmatched,
        "results": results,
        # 与上面的「条款 → 标准」匹配互补：这里回答"该有的条款有没有"
        "required_clauses": checklist.check_coverage(contract),
        # 再把合同值与标准限值比大小：回答"写进去的数字合不合规"
        "compliance": compliance.check_compliance(contract),
        "index": index_info(),
        "disclaimer": "匹配结果由检索模型给出，仅供参考，正式判定请以标准原文及专业机构结论为准。",
    }
