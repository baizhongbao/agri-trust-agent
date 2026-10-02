"""重排提供者实现。

- CloudRerankProvider：云端 API（SiliconFlow，OpenAI 兼容 /rerank），
  默认模型 BAAI/bge-reranker-v2-m3
- DisabledRerankProvider：不启用重排，明确报错而不是静默跳过

为什么需要 cross-encoder 重排：
    向量检索把 query 和文档分别编码，两者从不"见面"，
    因此只能粗排。重排模型把 query 与候选文档拼在一起打分，
    能显著提升首条命中率——这正是"标准校验"最需要的。
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.core.providers.base import (
    ProviderNotReadyError,
    RerankHit,
    RerankProvider,
    RerankResult,
)

logger = logging.getLogger(__name__)


class CloudRerankProvider(RerankProvider):
    """云端重排（SiliconFlow，OpenAI 兼容 /rerank）。

    与云端向量化共用同一份 CLOUD_API_BASE_URL / CLOUD_API_KEY，
    换供应商时只需改这两个值。
    """

    name = "cloud"

    @property
    def model(self) -> str:  # type: ignore[override]
        return settings.rerank_model

    def is_ready(self) -> bool:
        return bool(
            settings.cloud_api_base_url
            and settings.cloud_api_key
            and settings.rerank_model
        )

    def _endpoint(self) -> str:
        return settings.cloud_api_base_url.rstrip("/") + "/rerank"

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> RerankResult:
        if not self.is_ready():
            raise ProviderNotReadyError(
                "云端重排未就绪：请在 .env 中配置 CLOUD_API_BASE_URL 与 CLOUD_API_KEY"
            )
        if not documents:
            return RerankResult(hits=[], provider=self.name, model=self.model)

        payload: dict[str, object] = {
            "model": self.model,
            "query": query,
            "documents": [text if text and text.strip() else " " for text in documents],
            "return_documents": False,
        }
        if top_n is not None:
            # top_n 必须落在 [1, len(documents)] 内，否则接口直接报参数错误
            payload["top_n"] = max(1, min(top_n, len(documents)))

        with httpx.Client(timeout=settings.cloud_timeout) as client:
            response = client.post(
                self._endpoint(),
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.cloud_api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()

        hits = [
            RerankHit(index=int(item["index"]), score=float(item["relevance_score"]))
            for item in (data.get("results") or [])
            if "index" in item and "relevance_score" in item
        ]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return RerankResult(hits=hits, provider=self.name, model=self.model)


class DisabledRerankProvider(RerankProvider):
    """关闭重排。

    调用即报错，而不是返回空结果——空结果会让"没重排"和
    "重排后没有相关文档"混为一谈，排查起来代价很大。
    """

    name = "disabled"
    model = ""

    def is_ready(self) -> bool:
        return False

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> RerankResult:
        raise ProviderNotReadyError(
            "重排未启用：如需启用请在 .env 中设置 RERANK_PROVIDER=cloud"
        )
