"""合同解析结果的落盘与读取。

刻意用"文件夹 + JSON"而不是数据库：Demo 阶段数据量小，
零依赖、可直接用编辑器查看、搬迁方便。
后续要换 PostgreSQL 或 MinIO 时，只需替换本文件的实现。
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.modules.contract_parser.schema import StructuredContract

logger = logging.getLogger(__name__)

_UNSAFE_FILENAME_RE = re.compile(r"[^\w\u4e00-\u9fa5.\-]+")


def contracts_dir() -> Path:
    path = settings.data_dir / "contracts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(filename: str) -> str:
    name = _UNSAFE_FILENAME_RE.sub("_", filename or "contract.pdf")
    return name[-80:] if len(name) > 80 else name


def new_doc_id() -> str:
    """生成文档 ID，形如 ``20261007153000123456-a3f1``。

    纯秒级时间戳（``%Y%m%d%H%M%S``）在同一秒上传两份合同时会撞车，
    后者直接覆盖前者（docs/下一步必做事项.md 已记录该复现）。
    时间戳在前的字典序仍等价于时间序（``list_contracts`` 依赖倒排取最近），
    微秒精度 + 短随机后缀保证同一时刻唯一。
    """
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"{stamp}-{secrets.token_hex(2)}"


def save_contract(
    doc_id: str,
    pdf_bytes: bytes,
    filename: str,
    contract: StructuredContract,
) -> None:
    """保存原件与解析结果。"""
    settings.ensure_dirs()
    directory = contracts_dir()

    (directory / f"{doc_id}.pdf").write_bytes(pdf_bytes)
    payload = {
        "doc_id": doc_id,
        "filename": filename,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "contract": contract.model_dump(),
    }
    (directory / f"{doc_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 同时留一份可读副本，方便赛后复盘
    (settings.upload_dir / f"{doc_id}__{_safe_name(filename)}").write_bytes(pdf_bytes)


def load_contract(doc_id: str) -> StructuredContract | None:
    path = contracts_dir() / f"{doc_id}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return StructuredContract.model_validate(payload["contract"])
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("读取解析结果失败 doc_id=%s：%s", doc_id, exc)
        return None


def load_record(doc_id: str) -> dict | None:
    path = contracts_dir() / f"{doc_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def list_contracts(limit: int = 50) -> list[dict]:
    """按时间倒序列出已解析的合同。"""
    records: list[dict] = []
    for path in sorted(contracts_dir().glob("*.json"), reverse=True)[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        contract = payload.get("contract") or {}
        records.append(
            {
                "doc_id": payload.get("doc_id", path.stem),
                "filename": payload.get("filename", ""),
                "saved_at": payload.get("saved_at", ""),
                "title": contract.get("title", ""),
                "amount": contract.get("amount", ""),
                "parties": contract.get("parties", []),
                "extractor": contract.get("extractor", ""),
                "char_count": contract.get("char_count", 0),
            }
        )
    return records
