"""云端 OCR 提供者的单元测试（不调真实 API）。

就绪判断与降级行为是重点；识别质量靠端到端实测
（data/samples/订单农业合同_扫描件.pdf 全链路 8/8 命中）。
"""

from __future__ import annotations

import pytest

from app.core.providers.base import OCRProvider, ProviderNotReadyError
from app.core.providers.ocr import CloudOCRProvider, DisabledOCRProvider
from app.core.providers import registry


def test_cloud_ocr_not_ready_without_credentials(monkeypatch) -> None:
    provider = CloudOCRProvider()
    monkeypatch.setattr(
        "app.core.config.settings.cloud_api_key", "", raising=False
    )
    monkeypatch.setattr(
        "app.core.config.settings.ocr_cloud_model", "", raising=False
    )
    assert not provider.is_ready()
    with pytest.raises(ProviderNotReadyError):
        provider.recognize(b"png-bytes")


def test_cloud_ocr_ready_with_credentials(monkeypatch) -> None:
    provider = CloudOCRProvider()
    monkeypatch.setattr(
        "app.core.config.settings.cloud_api_key", "sk-test", raising=False
    )
    monkeypatch.setattr(
        "app.core.config.settings.cloud_api_base_url",
        "https://api.example.com/v1",
        raising=False,
    )
    monkeypatch.setattr(
        "app.core.config.settings.ocr_cloud_model",
        "PaddlePaddle/PaddleOCR-VL-1.5",
        raising=False,
    )
    assert provider.is_ready()
    assert provider.describe()["name"] == "cloud"


def test_disabled_ocr_always_raises() -> None:
    provider = DisabledOCRProvider()
    assert not provider.is_ready()
    with pytest.raises(ProviderNotReadyError, match="OCR 未启用"):
        provider.recognize(b"png-bytes")


def test_registry_ocr_cloud_mapping(monkeypatch) -> None:
    """OCR_PROVIDER=cloud 应注册到工厂并可通过工厂拿到。"""
    monkeypatch.setattr(
        "app.core.config.settings.ocr_provider", "cloud", raising=False
    )
    registry.reset_cache()
    try:
        provider = registry.get_ocr_provider()
        assert isinstance(provider, CloudOCRProvider)
    finally:
        registry.reset_cache()


def test_registry_unknown_ocr_provider_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.ocr_provider", "paddle", raising=False
    )
    registry.reset_cache()
    try:
        with pytest.raises(ValueError, match="OCR_PROVIDER"):
            registry.get_ocr_provider()
    finally:
        registry.reset_cache()
