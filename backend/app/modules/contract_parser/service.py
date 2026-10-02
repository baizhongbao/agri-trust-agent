"""合同解析服务：编排「读取 → 结构化 → 落盘」三步。"""

from __future__ import annotations

import logging

from app.modules.contract_parser import storage
from app.modules.contract_parser.pdf_reader import PdfReadError, read_pdf
from app.modules.contract_parser.schema import StructuredContract
from app.modules.contract_parser.structurer import get_structurer

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 20 * 1024 * 1024


class ContractParseError(RuntimeError):
    """合同解析失败，消息可直接展示给用户。"""


def parse_contract(pdf_bytes: bytes, filename: str) -> tuple[str, StructuredContract]:
    """解析 PDF 合同，返回 (文档ID, 结构化结果)。"""
    if not pdf_bytes:
        raise ContractParseError("上传的文件为空")

    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ContractParseError(f"文件超过 {MAX_PDF_BYTES // 1024 // 1024}MB 上限")

    # 先验一次文件头，避免把非 PDF 文件送进解析器后抛出难以理解的底层异常
    if not pdf_bytes.startswith(b"%PDF"):
        raise ContractParseError("文件不是有效的 PDF（缺少 %PDF 文件头）")

    try:
        pdf_text = read_pdf(pdf_bytes, filename)
    except PdfReadError as exc:
        raise ContractParseError(str(exc)) from exc

    structurer = get_structurer()
    contract = structurer.structure(pdf_text, filename)

    doc_id = storage.new_doc_id()
    storage.save_contract(doc_id, pdf_bytes, filename, contract)

    logger.info(
        "合同解析完成 doc_id=%s file=%s extractor=%s 字段命中=%d/%d",
        doc_id,
        filename,
        contract.extractor,
        sum(1 for f in contract.fields if f.value),
        len(contract.fields),
    )
    return doc_id, contract


def get_contract(doc_id: str) -> StructuredContract | None:
    return storage.load_contract(doc_id)


def list_contracts(limit: int = 50) -> list[dict]:
    return storage.list_contracts(limit=limit)
