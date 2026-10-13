"""汇总判定 HTTP 接口（含报告导出）。"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.modules.verdict import exporter, service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/verdict", tags=["汇总判定"])

_MEDIA = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class VerdictRequest(BaseModel):
    doc_id: str = Field(..., description="合同解析返回的文档 ID")


@router.post("/evaluate", summary="串起四模块，输出总体可信度结论")
def evaluate(payload: VerdictRequest) -> dict:
    verdict = service.run_verdict(payload.doc_id)
    if verdict is None:
        raise HTTPException(status_code=404, detail=f"未找到合同 {payload.doc_id}")
    return verdict.model_dump()


@router.get("/{doc_id}/report", summary="导出可信性评估报告（pdf / docx）")
def export_report(doc_id: str, format: str = "pdf") -> Response:
    fmt = (format or "pdf").lower()
    if fmt not in _MEDIA:
        raise HTTPException(status_code=400, detail="format 仅支持 pdf / docx")
    model = exporter.build_report(doc_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"未找到合同 {doc_id}")

    data = exporter.render_docx(model) if fmt == "docx" else exporter.render_pdf(model)
    filename = f"可信性评估报告_{doc_id}.{fmt}"
    disposition = (
        f'attachment; filename="report_{doc_id}.{fmt}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=data,
        media_type=_MEDIA[fmt],
        headers={"Content-Disposition": disposition},
    )
