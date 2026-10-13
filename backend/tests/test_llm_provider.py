"""LLM Provider 层回归测试（不联网）。

只验证「工厂映射、就绪判定、JSON 解析」——真实调用由人工冒烟验证。
"""

from __future__ import annotations

from app.core.config import settings
from app.core.providers import registry
from app.core.providers.llm import (
    DeepSeekLLMProvider,
    MockLLMProvider,
    PanguLLMProvider,
    extract_json,
)


def test_registry_maps_llm_keys(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    registry.reset_cache()
    provider = registry.get_llm_provider()
    assert isinstance(provider, DeepSeekLLMProvider)
    assert provider.name == "deepseek"

    monkeypatch.setattr(settings, "llm_provider", "pangu")
    registry.reset_cache()
    assert isinstance(registry.get_llm_provider(), PanguLLMProvider)

    monkeypatch.setattr(settings, "llm_provider", "mock")
    registry.reset_cache()
    assert isinstance(registry.get_llm_provider(), MockLLMProvider)

    registry.reset_cache()


def test_deepseek_readiness_follows_credentials(monkeypatch) -> None:
    monkeypatch.setattr(settings, "deepseek_base_url", "https://example/v1")
    monkeypatch.setattr(settings, "deepseek_model", "deepseek-flash")

    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    assert DeepSeekLLMProvider().is_ready() is True

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    assert DeepSeekLLMProvider().is_ready() is False


def test_deepseek_default_base_url() -> None:
    assert settings.deepseek_base_url.startswith("https://")
    assert settings.deepseek_model


def test_extract_json_strips_markdown_fence() -> None:
    assert extract_json('```json\n{"status": "ok"}\n```') == {"status": "ok"}
    assert extract_json('说明文字 {"a": 1} 结尾') == {"a": 1}


def test_mock_provider_returns_stub_shell() -> None:
    mock = MockLLMProvider()
    assert mock.is_ready() is True
    assert mock.complete_json("任意")["_mock"] is True
