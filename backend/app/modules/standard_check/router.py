"""标准校验 HTTP 接口。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.modules.standard_check import loader, service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/standards", tags=["标准校验"])


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="检索文本，例如某条合同条款")
    top_k: int | None = Field(default=None, ge=1, le=50)


class CheckRequest(BaseModel):
    doc_id: str = Field(..., description="合同解析返回的文档 ID")
    top_k: int | None = Field(default=None, ge=1, le=50)
    clause_limit: int = Field(default=20, ge=1, le=200)


@router.get("", summary="标准库目录")
def library() -> dict:
    items = loader.summarize_library()
    return {"total": len(items), "items": items}


@router.get("/stats", summary="检索库状态")
def stats() -> dict:
    return service.index_info()


@router.post("/reindex", summary="重建检索库")
def reindex() -> dict:
    return service.reindex()


@router.post("/search", summary="按文本检索标准条款")
def search(payload: SearchRequest) -> dict:
    hits = service.search(payload.query, top_k=payload.top_k)
    return {
        "query": payload.query,
        "total": len(hits),
        "matches": [hit.to_dict() for hit in hits],
    }


@router.post("/check", summary="校验合同条款与标准的对应关系")
def check(payload: CheckRequest) -> dict:
    report = service.check_contract(
        payload.doc_id,
        top_k=payload.top_k,
        clause_limit=payload.clause_limit,
    )
    if report is None:
        raise HTTPException(status_code=404, detail=f"未找到合同 {payload.doc_id}")
    return report
