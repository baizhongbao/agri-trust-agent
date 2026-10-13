"""大模型提供者实现。

- PanguLLMProvider：华为云盘古 / ModelArts Studio（MaaS）
- MockLLMProvider：无凭证时的确定性桩实现，用于打通链路与联调
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.core.config import settings
from app.core.providers.base import LLMProvider, LLMResult, ProviderNotReadyError

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(content: str) -> dict[str, Any]:
    """从模型输出中稳健地取出 JSON。

    模型经常会附带 markdown 代码围栏或前后说明文字，这里逐级降级处理，
    避免因为格式噪音导致整条链路失败。
    """
    text = _FENCE_RE.sub("", content.strip()).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _openai_chat(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    provider_name: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> LLMResult:
    """OpenAI 兼容 /chat/completions 的公共调用。

    盘古与 deepseek-flash 走的是同一套协议，差异只在 base_url / key / model，
    因此把请求体拼装与响应解析收敛到这里，换供应商不动业务代码。
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=settings.llm_timeout) as client:
        response = client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    return LLMResult(
        content=data["choices"][0]["message"]["content"],
        provider=provider_name,
        model=model,
        usage=data.get("usage", {}) or {},
    )


def _openai_messages(prompt: str, system: str | None) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


class PanguLLMProvider(LLMProvider):
    """华为云盘古大模型（MaaS 的 OpenAI 兼容接口）。

    不引入厂商 SDK，直接按 /chat/completions 协议调用，
    既降低依赖体积，也保证 Windows / Linux 行为一致。
    """

    name = "pangu"

    @property
    def model(self) -> str:  # type: ignore[override]
        return settings.pangu_model or "pangu"

    def is_ready(self) -> bool:
        return bool(settings.pangu_base_url and settings.pangu_api_key and settings.pangu_model)

    def _endpoint(self) -> str:
        # PANGU_BASE_URL 需包含版本路径，例如 https://xxx/v1
        return settings.pangu_base_url.rstrip("/") + "/chat/completions"

    def _chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResult:
        if not self.is_ready():
            raise ProviderNotReadyError(
                "盘古大模型未就绪：请在 .env 中配置 PANGU_BASE_URL / PANGU_API_KEY / PANGU_MODEL"
            )
        return _openai_chat(
            endpoint=self._endpoint(),
            api_key=settings.pangu_api_key,
            model=self.model,
            provider_name=self.name,
            messages=messages,
            temperature=settings.llm_temperature if temperature is None else temperature,
            max_tokens=settings.llm_max_tokens if max_tokens is None else max_tokens,
            json_mode=json_mode,
        )

    def complete(self, prompt: str, system: str | None = None) -> LLMResult:
        return self._chat(_openai_messages(prompt, system))

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        messages = _openai_messages(prompt, system)
        try:
            result = self._chat(messages, temperature=0.0, json_mode=True)
            return extract_json(result.content)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
            # 部分部署不支持 response_format，降级为普通模式再试一次
            logger.warning("JSON 模式调用失败，降级重试：%s", exc)
            result = self._chat(messages, temperature=0.0)
            return extract_json(result.content)


class DeepSeekLLMProvider(LLMProvider):
    """deepseek-flash（OpenAI 兼容 · tokenrhythm）。

    与 PanguLLMProvider 协议一致，只是换了 base_url / key / model。
    当前用于**替换盘古**作为项目的默认真实 LLM。
    """

    name = "deepseek"

    @property
    def model(self) -> str:  # type: ignore[override]
        return settings.deepseek_model or "deepseek-flash"

    def is_ready(self) -> bool:
        return bool(
            settings.deepseek_base_url
            and settings.deepseek_api_key
            and settings.deepseek_model
        )

    def _endpoint(self) -> str:
        # DEEPSEEK_BASE_URL 需包含版本路径，例如 https://xxx/v1
        return settings.deepseek_base_url.rstrip("/") + "/chat/completions"

    def _chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResult:
        if not self.is_ready():
            raise ProviderNotReadyError(
                "deepseek-flash 未就绪：请在 .env 中配置 DEEPSEEK_BASE_URL / DEEPSEEK_API_KEY / DEEPSEEK_MODEL"
            )
        return _openai_chat(
            endpoint=self._endpoint(),
            api_key=settings.deepseek_api_key,
            model=self.model,
            provider_name=self.name,
            messages=messages,
            temperature=settings.llm_temperature if temperature is None else temperature,
            max_tokens=settings.llm_max_tokens if max_tokens is None else max_tokens,
            json_mode=json_mode,
        )

    def complete(self, prompt: str, system: str | None = None) -> LLMResult:
        return self._chat(_openai_messages(prompt, system))

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        messages = _openai_messages(prompt, system)
        try:
            result = self._chat(messages, temperature=0.0, json_mode=True)
            return extract_json(result.content)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
            # 部分部署不支持 response_format，降级为普通模式再试一次
            logger.warning("JSON 模式调用失败，降级重试：%s", exc)
            result = self._chat(messages, temperature=0.0)
            return extract_json(result.content)


class MockLLMProvider(LLMProvider):
    """确定性桩实现。

    存在的意义：在没有华为云凭证时让整条链路可以先跑通、可测试、可演示，
    而不是等到凭证下来才发现代码有问题。
    """

    name = "mock"
    model = "mock-llm"

    def is_ready(self) -> bool:
        return True

    def complete(self, prompt: str, system: str | None = None) -> LLMResult:
        return LLMResult(
            content="【mock 输出】未配置真实大模型，此处为占位内容。",
            provider=self.name,
            model=self.model,
            usage={"prompt_tokens": len(prompt), "completion_tokens": 0},
        )

    def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        """返回一个结构合法的空壳，让调用方的解析逻辑得到验证。"""
        return {
            "_mock": True,
            "_note": "未配置真实大模型，以下为占位结构",
            "_prompt_chars": len(prompt),
        }
