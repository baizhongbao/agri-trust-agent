"""图片上传链路的单元测试（不调真实 API）。

覆盖：文件头嗅探、图片 → OCR 分发、OCR 未就绪/失败降级、不支持类型的报错。
识别质量靠端到端实测（把示例合同首页渲染成 PNG 后走真实云 OCR 全链路）。
"""

from __future__ import annotations

import pytest

from app.core.providers.base import OCRProvider, OCRResult
from app.core.providers.ocr import DisabledOCRProvider
from app.modules.contract_parser import service
from app.modules.contract_parser.pdf_reader import (
    PdfReadError,
    read_document,
    sniff_kind,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPG_MAGIC = b"\xff\xd8\xff\xe0"


class _FakeReadyOCR(OCRProvider):
    name = "fake-ocr"

    def is_ready(self) -> bool:
        return True

    def recognize(self, image_bytes: bytes) -> OCRResult:
        return OCRResult(
            text="合同编号：DDNY-2026-0918\n甲方：某某粮食收储有限公司",
            page_count=1,
            provider=self.name,
        )


class _FakeBrokenOCR(OCRProvider):
    name = "broken-ocr"

    def is_ready(self) -> bool:
        return True

    def recognize(self, image_bytes: bytes) -> OCRResult:
        raise RuntimeError("网络超时")


def _use_ocr(monkeypatch, provider: OCRProvider) -> None:
    monkeypatch.setattr(
        "app.modules.contract_parser.pdf_reader.get_ocr_provider",
        lambda: provider,
    )


# ---------------- 文件头嗅探 ----------------


def test_sniff_kind_recognizes_supported_types() -> None:
    assert sniff_kind(b"%PDF-1.7 rest") == "pdf"
    assert sniff_kind(_PNG_MAGIC + b"image-data") == "png"
    assert sniff_kind(_JPG_MAGIC + b"image-data") == "jpg"


def test_sniff_kind_rejects_unknown_and_empty() -> None:
    assert sniff_kind(b"plain text") == "unknown"
    assert sniff_kind(b"") == "unknown"


# ---------------- 图片 → OCR 分发 ----------------


def test_read_document_dispatches_image_to_ocr(monkeypatch) -> None:
    _use_ocr(monkeypatch, _FakeReadyOCR())
    result = read_document(_PNG_MAGIC + b"data", "photo.png")
    assert result.used_ocr is True
    assert result.needs_ocr is True
    assert result.page_count == 1
    assert "DDNY-2026-0918" in result.text


def test_read_document_dispatches_jpeg_too(monkeypatch) -> None:
    _use_ocr(monkeypatch, _FakeReadyOCR())
    result = read_document(_JPG_MAGIC + b"data", "photo.jpg")
    assert result.used_ocr is True


def test_read_document_pdf_header_still_goes_to_pdf_path() -> None:
    """PDF 魔数必须走原 PDF 链路（坏 PDF 抛 PdfReadError 而非送 OCR）。"""
    with pytest.raises(PdfReadError):
        read_document(b"%PDF-broken", "bad.pdf")


# ---------------- 降级行为 ----------------


def test_read_image_ocr_not_ready_returns_warning(monkeypatch) -> None:
    _use_ocr(monkeypatch, DisabledOCRProvider())
    result = read_document(_JPG_MAGIC + b"data", "photo.jpg")
    assert result.used_ocr is False
    assert result.text == ""
    assert any("OCR" in w for w in result.warnings)


def test_read_image_ocr_failure_returns_warning(monkeypatch) -> None:
    _use_ocr(monkeypatch, _FakeBrokenOCR())
    result = read_document(_PNG_MAGIC + b"data", "photo.png")
    assert result.used_ocr is False
    assert any("OCR 失败" in w for w in result.warnings)


# ---------------- 服务层校验 ----------------


def test_parse_contract_rejects_unsupported_type() -> None:
    with pytest.raises(service.ContractParseError, match="不支持的文件类型"):
        service.parse_contract(b"just some plain text", "note.txt")


def test_parse_contract_rejects_empty_file() -> None:
    with pytest.raises(service.ContractParseError, match="文件为空"):
        service.parse_contract(b"", "empty.png")
