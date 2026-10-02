"""合同解析 HTTP 接口。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.modules.contract_parser import service
from app.modules.contract_parser.schema import StructuredContract

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contracts", tags=["合同解析"])


class ParseResponse(BaseModel):
    doc_id: str
    contract: StructuredContract


@router.post("/parse", response_model=ParseResponse, summary="上传 PDF 合同并解析")
async def parse(file: UploadFile = File(..., description="PDF 合同文件")):
    data = await file.read()
    try:
        doc_id, contract = service.parse_contract(data, file.filename or "contract.pdf")
    except service.ContractParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ParseResponse(doc_id=doc_id, contract=contract)


@router.get("", summary="已解析合同列表")
def list_contracts(limit: int = 50) -> dict:
    items = service.list_contracts(limit=limit)
    return {"total": len(items), "items": items}


@router.get("/{doc_id}", response_model=StructuredContract, summary="读取解析结果")
def get_contract(doc_id: str) -> StructuredContract:
    contract = service.get_contract(doc_id)
    if contract is None:
        raise HTTPException(status_code=404, detail=f"未找到合同 {doc_id}")
    return contract
