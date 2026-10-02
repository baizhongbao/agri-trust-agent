"""PDF 文本抽取。

策略（先便宜后昂贵）：
    1. 先用 PyMuPDF 直接读文本层——电子版合同走这条，快、准、零成本
    2. 文本层过少时判定为扫描件，才交给华为云 OCR

这样绝大多数演示用合同都不会消耗 OCR 调用量，
也让 Demo 在没有 OCR 凭证时依然可用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.providers.registry import get_ocr_provider

logger = logging.getLogger(__name__)

# 每页平均字符数低于该阈值，判定为扫描件
_SCANNED_PAGE_CHAR_THRESHOLD = 20

# OCR 渲染分辨率：200 DPI 是识别率与传输体积的平衡点
_OCR_RENDER_DPI = 200


@dataclass
class PdfText:
    """PDF 抽取结果。"""

    text: str = ""
    page_count: int = 0
    char_count: int = 0
    needs_ocr: bool = False
    used_ocr: bool = False
    warnings: list[str] = field(default_factory=list)


class PdfReadError(RuntimeError):
    """PDF 无法解析。"""


def _open(pdf_bytes: bytes):
    # PyMuPDF >= 1.24 推荐 import pymupdf；旧版仅有 fitz 模块名
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError as exc:  # pragma: no cover - 依赖缺失时的兜底
            raise PdfReadError("未安装 PyMuPDF，请执行 pip install pymupdf") from exc

    try:
        return fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise PdfReadError(f"PDF 打开失败：{exc}") from exc


def _extract_pages_text(pdf_bytes: bytes) -> list[str]:
    with _open(pdf_bytes) as doc:
        return [page.get_text("text") or "" for page in doc]


def _render_pages_png(pdf_bytes: bytes, dpi: int = _OCR_RENDER_DPI) -> list[bytes]:
    images: list[bytes] = []
    with _open(pdf_bytes) as doc:
        for page in doc:
            pixmap = page.get_pixmap(dpi=dpi)
            images.append(pixmap.tobytes("png"))
    return images


def read_pdf(pdf_bytes: bytes, filename: str = "") -> PdfText:
    """抽取 PDF 文本，必要时自动降级到 OCR。"""
    try:
        pages = _extract_pages_text(pdf_bytes)
    except PdfReadError:
        raise
    except Exception as exc:  # pragma: no cover
        raise PdfReadError(f"PDF 文本抽取失败：{exc}") from exc

    page_count = len(pages)
    text = "\n".join(p.strip() for p in pages if p and p.strip()).strip()

    result = PdfText(text=text, page_count=page_count, char_count=len(text))

    if page_count == 0:
        result.warnings.append("PDF 中未发现任何页面，文件可能已损坏")
        return result

    if result.char_count / page_count >= _SCANNED_PAGE_CHAR_THRESHOLD:
        return result

    # ---- 文本层不足，判定为扫描件 ----
    result.needs_ocr = True
    provider = get_ocr_provider()

    if not provider.is_ready():
        result.warnings.append(
            "疑似扫描件（每页文本量过少），但 OCR 未启用。"
            "如需处理扫描件，请设置 OCR_PROVIDER=huawei 并配置华为云 AK/SK。"
        )
        logger.info("判定为扫描件但 OCR 未就绪，文件名=%s", filename or "<unknown>")
        return result

    ocr_chunks: list[str] = []
    for index, png in enumerate(_render_pages_png(pdf_bytes)):
        try:
            ocr_chunks.append(provider.recognize(png).text)
        except Exception as exc:  # 单页失败不影响整份文件
            logger.warning("第 %d 页 OCR 失败：%s", index + 1, exc)
            result.warnings.append(f"第 {index + 1} 页 OCR 失败：{exc}")

    merged = "\n".join(chunk.strip() for chunk in ocr_chunks if chunk and chunk.strip()).strip()
    if merged:
        result.text = merged
        result.char_count = len(merged)
        result.used_ocr = True
    else:
        result.warnings.append("OCR 未返回可用文本")

    return result
