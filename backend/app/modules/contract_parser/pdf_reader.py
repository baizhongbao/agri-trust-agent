"""文档文本抽取（PDF / 图片）。

策略（先便宜后昂贵）：
    1. PDF：先用 PyMuPDF 直接读文本层——电子版合同走这条，快、准、零成本
    2. PDF 文本层过少时判定为扫描件，渲染成图片后才交给 OCR
    3. 图片（PNG/JPG）：没有文本层可用，直接整图送 OCR——手机拍照的合同走这条

这样绝大多数演示用合同都不会消耗 OCR 调用量，
也让 Demo 在没有 OCR 凭证时依然可用（电子版 PDF 不需要 OCR）。
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

_PDF_MAGIC = b"%PDF"
_IMAGE_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
)


def sniff_kind(data: bytes) -> str:
    """按文件头判断类型：pdf | png | jpg | unknown。

    不依赖文件名与 Content-Type——前端传来的两者都不可信，
    而路由层只负责转发字节。真正的分发依据只有魔数。
    """
    if data.startswith(_PDF_MAGIC):
        return "pdf"
    for magic, name in _IMAGE_MAGICS:
        if data.startswith(magic):
            return name
    return "unknown"


@dataclass
class PdfText:
    """文档抽取结果（PDF 与图片共用——两者都产出「纯文本 + 元信息」）。"""

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
            "如需处理扫描件，请设置 OCR_PROVIDER=cloud（配 CLOUD_API_KEY）"
            "或 OCR_PROVIDER=huawei（配华为云 AK/SK）。"
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


def read_image(image_bytes: bytes, filename: str = "") -> PdfText:
    """读取单页图片（PNG/JPG）：整图送 OCR。

    与扫描件 PDF 的区别只有入口——扫描件是「PyMuPDF 渲染出图片再 OCR」，
    图片上传则是「用户直接给图片」，之后共用同一个 Provider 与告警逻辑。
    """
    result = PdfText(page_count=1, needs_ocr=True)
    provider = get_ocr_provider()

    if not provider.is_ready():
        result.warnings.append(
            "图片必须经过 OCR 才能提取文本，但 OCR 未启用。"
            "请设置 OCR_PROVIDER=cloud（配 CLOUD_API_KEY）"
            "或 OCR_PROVIDER=huawei（配华为云 AK/SK）。"
        )
        logger.info("收到图片但 OCR 未就绪，文件名=%s", filename or "<unknown>")
        return result

    try:
        ocr_result = provider.recognize(image_bytes)
    except Exception as exc:  # 单次失败不抛出，降级为带告警的空结果
        logger.warning("图片 OCR 失败：%s", exc)
        result.warnings.append(f"图片 OCR 失败：{exc}")
        return result

    text = (ocr_result.text or "").strip()
    if text:
        result.text = text
        result.char_count = len(text)
        result.used_ocr = True
    else:
        result.warnings.append("OCR 未返回可用文本")
    return result


def read_document(file_bytes: bytes, filename: str = "") -> PdfText:
    """统一入口：按文件头把字节分发到 PDF 或图片读取。"""
    kind = sniff_kind(file_bytes)
    if kind in ("png", "jpg"):
        return read_image(file_bytes, filename)
    return read_pdf(file_bytes, filename)
