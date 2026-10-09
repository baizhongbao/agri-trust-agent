"""提供者工厂。

业务模块一律通过这里拿实例，不直接 import 具体实现。
这样更换供应商（盘古 → 其他模型、哈希向量 → bge-m3）时，
改动被限制在本文件的映射表里。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

from app.core.config import settings
from app.core.providers.base import (
    EmbeddingProvider,
    EnterpriseProvider,
    LLMProvider,
    OCRProvider,
    ProviderNotReadyError,
    RerankProvider,
)
from app.core.providers.embedding import (
    CloudEmbeddingProvider,
    HashingEmbeddingProvider,
    LocalEmbeddingProvider,
)
from app.core.providers.enterprise import (
    FixtureEnterpriseProvider,
    QccEnterpriseProvider,
)
from app.core.providers.llm import MockLLMProvider, PanguLLMProvider
from app.core.providers.ocr import (
    CloudOCRProvider,
    DisabledOCRProvider,
    HuaweiOCRProvider,
)
from app.core.providers.rerank import CloudRerankProvider, DisabledRerankProvider
from app.core.providers.search import DisabledSearchProvider, TavilySearchProvider

_LLM: dict[str, Callable[[], LLMProvider]] = {
    "pangu": PanguLLMProvider,
    "mock": MockLLMProvider,
}

_OCR: dict[str, Callable[[], OCRProvider]] = {
    "huawei": HuaweiOCRProvider,
    "cloud": CloudOCRProvider,
    "disabled": DisabledOCRProvider,
}

_EMBEDDING: dict[str, Callable[[], EmbeddingProvider]] = {
    "cloud": CloudEmbeddingProvider,
    "local": LocalEmbeddingProvider,
    "hashing": lambda: HashingEmbeddingProvider(settings.embedding_dim_hashing),
}

_RERANK: dict[str, Callable[[], RerankProvider]] = {
    "cloud": CloudRerankProvider,
    "disabled": DisabledRerankProvider,
}

_ENTERPRISE: dict[str, Callable[[], EnterpriseProvider]] = {
    "fixture": FixtureEnterpriseProvider,
    "qcc": QccEnterpriseProvider,
}

_SEARCH: dict[str, Callable[[], SearchProvider]] = {
    "tavily": TavilySearchProvider,
    "disabled": DisabledSearchProvider,
}


def _pick(mapping: dict[str, Callable[[], Any]], key: str, kind: str) -> Any:
    factory = mapping.get(key.lower())
    if factory is None:
        raise ValueError(f"未知的 {kind}: {key!r}，可选值 {sorted(mapping)}")
    return factory()


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    return _pick(_LLM, settings.llm_provider, "LLM_PROVIDER")


@lru_cache(maxsize=1)
def get_ocr_provider() -> OCRProvider:
    return _pick(_OCR, settings.ocr_provider, "OCR_PROVIDER")


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    return _pick(_EMBEDDING, settings.embedding_provider, "EMBEDDING_PROVIDER")


@lru_cache(maxsize=1)
def get_rerank_provider() -> RerankProvider:
    return _pick(_RERANK, settings.rerank_provider, "RERANK_PROVIDER")


@lru_cache(maxsize=1)
def get_enterprise_provider() -> EnterpriseProvider:
    # 未配置时默认 fixture（离线演示兜底），显式配置则按配置走
    key = (settings.enterprise_api_provider or "").strip().lower() or "fixture"
    return _pick(_ENTERPRISE, key, "ENTERPRISE_API_PROVIDER")


@lru_cache(maxsize=1)
def get_search_provider() -> SearchProvider:
    key = (settings.search_provider or "").strip().lower() or "disabled"
    return _pick(_SEARCH, key, "SEARCH_PROVIDER")


def require(provider: Any, purpose: str) -> None:
    """断言提供者就绪，否则抛出可读的错误。

    把"未配置"变成明确的启动期/调用期错误，
    而不是让一个空结果一路流到前端才被发现。
    """
    if not provider.is_ready():
        raise ProviderNotReadyError(
            f"{purpose} 所需的能力未就绪（当前实现：{provider.name}），"
            "请检查 .env 中的提供者开关与凭证配置"
        )


def describe_providers() -> dict[str, dict[str, Any]]:
    """汇总各提供者状态，供 /health 与前端展示。"""
    return {
        "llm": get_llm_provider().describe(),
        "ocr": get_ocr_provider().describe(),
        "embedding": get_embedding_provider().describe(),
        "rerank": get_rerank_provider().describe(),
        "enterprise": get_enterprise_provider().describe(),
        "search": get_search_provider().describe(),
    }


def reset_cache() -> None:
    """清空工厂缓存。配置热更新或测试时使用。"""
    get_llm_provider.cache_clear()
    get_ocr_provider.cache_clear()
    get_embedding_provider.cache_clear()
    get_rerank_provider.cache_clear()
    get_enterprise_provider.cache_clear()
    get_search_provider.cache_clear()
