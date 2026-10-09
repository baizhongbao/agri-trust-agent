"""联网搜索提供者实现。

- TavilySearchProvider：调 Tavily API（https://api.tavily.com/search），
  含中英文网页检索。供 Agent「加深」时获取外部证据（企业违法/判例/政策风险等）
- DisabledSearchProvider：离线降级。返回空结果 + 说明，不伪造内容

与 OpenCode 的 tavily 插件共用同一把 key（已存入 ~/.tavily/config.json），
但 Agent 服务端不读该文件——key 通过 .env 的 TAVILY_API_KEY 注入，
保持「凭证只进 .env / 环境变量」的项目约定。
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.core.providers.base import (
    ProviderNotReadyError,
    SearchProvider,
    SearchResult,
    SearchResultItem,
)

logger = logging.getLogger(__name__)

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilySearchProvider(SearchProvider):
    """Tavily 网页搜索（真实联网）。"""

    name = "tavily"

    def is_ready(self) -> bool:
        return bool(settings.tavily_api_key)

    def search(self, query: str, max_results: int | None = None, topic: str = "general") -> SearchResult:
        if not self.is_ready():
            raise ProviderNotReadyError(
                "Tavily 搜索未就绪：请在 .env 中配置 TAVILY_API_KEY"
            )
        query = (query or "").strip()
        if not query:
            return SearchResult(query=query, items=[], provider=self.name, note="查询关键字为空")

        limit = max_results or settings.tavily_max_results
        limit = max(1, min(20, limit))

        try:
            response = httpx.post(
                _TAVILY_SEARCH_URL,
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": limit,
                    "search_depth": "basic",
                    "topic": topic,
                },
                timeout=settings.tavily_timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Tavily 搜索失败 query=%s：%s", query, exc)
            return SearchResult(
                query=query,
                items=[],
                provider=self.name,
                note=f"搜索请求失败：{exc}",
            )

        items = []
        for raw in payload.get("results", []) or []:
            url = str(raw.get("url", "") or "").strip()
            if not url:
                continue
            items.append(
                SearchResultItem(
                    title=str(raw.get("title", "") or "").strip(),
                    url=url,
                    snippet=str(raw.get("content", "") or "").strip(),
                    score=raw.get("score"),
                )
            )
        return SearchResult(query=query, items=items, provider=self.name)

    def describe(self) -> dict:
        return {
            "name": self.name,
            "ready": self.is_ready(),
            "max_results": settings.tavily_max_results,
        }


class DisabledSearchProvider(SearchProvider):
    """离线降级：不联网，明确告知未配置。"""

    name = "disabled"

    def is_ready(self) -> bool:
        return False

    def search(self, query: str, max_results: int | None = None, topic: str = "general") -> SearchResult:
        return SearchResult(
            query=(query or "").strip(),
            items=[],
            provider=self.name,
            note="联网搜索未启用（SEARCH_PROVIDER=disabled）。如需外部证据，"
            "请将 TAVILY_API_KEY 配置到 .env 并把 SEARCH_PROVIDER 设为 tavily。",
        )

    def describe(self) -> dict:
        return {"name": self.name, "ready": False}