"""企业核验 HTTP 接口。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.modules.enterprise_verify import service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/enterprise", tags=["企业核验"])


class VerifyRequest(BaseModel):
    doc_id: str = Field(..., description="合同解析返回的文档 ID")


class LookupRequest(BaseModel):
    search_key: str = Field(
        ...,
        min_length=2,
        description="企业名称或统一社会信用代码",
    )


@router.post("/verify", summary="核验某份合同的全部主体（L1+L2+L3）")
def verify(payload: VerifyRequest) -> dict:
    report = service.verify_contract(payload.doc_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"未找到合同 {payload.doc_id}")
    return report.model_dump()


@router.post("/lookup", summary="直接查询单个企业（本地校验 + 工商信息）")
def lookup(payload: LookupRequest) -> dict:
    return service.lookup(payload.search_key)
