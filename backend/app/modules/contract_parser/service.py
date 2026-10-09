"""合同解析服务：编排「读取 → L1 结构化 →（必要时）L2 重解析 → 门禁 → 落盘」。

**为什么解析要分两级**（对应 gate.py 的设计说明）：
    L1 = OCR + 规则抽取。便宜、确定、可解释，绝大多数规整合同它够了。
    L2 = LLM 重解析。贵，但能兜住排版混乱、标签口语化的合同。
    只有 L1 触发条件（主体全缺 / OCR 来源 / 关键要素大面积缺失）时才上 L2，
    并且**只在更完整时才采纳**——避免 mock 占位结果把好结果冲掉。
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.core.providers.base import ProviderNotReadyError
from app.modules.contract_parser import gate, storage
from app.modules.contract_parser.pdf_reader import PdfReadError, read_document, sniff_kind
from app.modules.contract_parser.schema import StructuredContract
from app.modules.contract_parser.structurer import (
    LLMStructurer,
    get_structurer,
)

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 20 * 1024 * 1024


class ContractParseError(RuntimeError):
    """合同解析失败，消息可直接展示给用户。"""


def _escalation_enabled() -> bool:
    return (settings.contract_escalation or "").strip().lower() != "off"


def _l2_structurer() -> LLMStructurer:
    """L2（LLM 重解析）实例工厂。

    单独抽出来有两个好处：测试可以打桩而不用去改 `LLMStructurer` 这个类本身
    （替换类会连带影响 `isinstance` 判断），也把"L2 到底是什么"这个边界写明白了。
    """
    return LLMStructurer()


def _try_escalate(
    pdf_text,
    filename: str,
    primary: object,
    l1: StructuredContract,
) -> tuple[StructuredContract, str, str]:
    """执行 L1 → L2 升级，返回 (采用的结果, outcome, note)。

    L2 的任何失败（未就绪 / 网络 / 格式）都不抛出：L1 结果仍然有价值，
    但失败原因必须写进 gate，不能悄悄咽掉。
    """
    if isinstance(primary, LLMStructurer):
        return (
            l1,
            gate.ESCALATION_SKIPPED,
            "当前抽取器已是 LLM（L2），无需再升级",
        )

    try:
        l2 = _l2_structurer().structure(pdf_text, filename)
    except ProviderNotReadyError as exc:
        logger.info("L1→L2 升级未就绪：%s", exc)
        return l1, gate.ESCALATION_UNAVAILABLE, f"L2 未就绪：{exc}"
    except Exception as exc:  # 外部故障一律降级，不阻断解析
        logger.warning("L1→L2 升级失败：%s", exc)
        return l1, gate.ESCALATION_UNAVAILABLE, f"L2 执行失败：{exc}"

    return gate.choose_better(l1, l2)


def parse_contract(file_bytes: bytes, filename: str) -> tuple[str, StructuredContract]:
    """解析合同文件（PDF 或图片），返回 (文档ID, 结构化结果)。"""
    if not file_bytes:
        raise ContractParseError("上传的文件为空")

    if len(file_bytes) > MAX_FILE_BYTES:
        raise ContractParseError(f"文件超过 {MAX_FILE_BYTES // 1024 // 1024}MB 上限")

    # 先验一次文件头：PDF 走文本层直抽（扫描件内部自动降级 OCR），
    # 图片（PNG/JPG）走 OCR，其余类型拒绝——
    # 避免把不支持的文件送进解析器后抛出难以理解的底层异常
    if sniff_kind(file_bytes) == "unknown":
        raise ContractParseError(
            "不支持的文件类型：仅支持 PDF（电子版/扫描件）或图片（PNG/JPG）"
        )

    try:
        pdf_text = read_document(file_bytes, filename)
    except PdfReadError as exc:
        raise ContractParseError(str(exc)) from exc

    # ---- L1：便宜的规则抽取 ----
    structurer = get_structurer()
    contract = structurer.structure(pdf_text, filename)

    # ---- L1 → L2：命中触发条件才升级，且只在更完整时采纳 ----
    escalated = False
    escalation_reason = escalation_outcome = escalation_note = ""
    should, escalation_reason = gate.needs_escalation(contract)
    if should and _escalation_enabled():
        escalated = True
        contract, escalation_outcome, escalation_note = _try_escalate(
            pdf_text, filename, structurer, contract
        )
        logger.info(
            "L1→L2 升级 doc=%s 触发=%s 结果=%s（%s）",
            filename,
            escalation_reason,
            escalation_outcome,
            escalation_note,
        )
    elif should:
        escalated = True
        escalation_outcome = gate.ESCALATION_SKIPPED
        escalation_note = "CONTRACT_ESCALATION=off，已关闭自动升级"

    # ---- L4：硬失败门禁。必备字段仍缺失时必须显式暴露，不得静默通过 ----
    contract.gate = gate.evaluate(
        contract,
        escalated=escalated,
        escalation_reason=escalation_reason,
        escalation_outcome=escalation_outcome,
        escalation_note=escalation_note,
    )
    contract.warnings.append(gate.warning_line(contract.gate))

    doc_id = storage.new_doc_id()
    storage.save_contract(doc_id, file_bytes, filename, contract)

    logger.info(
        "合同解析完成 doc_id=%s file=%s extractor=%s 字段命中=%d/%d 门禁=%s",
        doc_id,
        filename,
        contract.extractor,
        sum(1 for f in contract.fields if f.value),
        len(contract.fields),
        contract.gate.level,
    )
    return doc_id, contract


def get_contract(doc_id: str) -> StructuredContract | None:
    return storage.load_contract(doc_id)


def list_contracts(limit: int = 50) -> list[dict]:
    return storage.list_contracts(limit=limit)
