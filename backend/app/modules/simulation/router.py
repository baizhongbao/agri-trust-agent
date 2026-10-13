"""履约模拟 HTTP 接口。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.modules.simulation import rulebook, service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simulate", tags=["履约模拟"])


class SimulateRequest(BaseModel):
    doc_id: str = Field(
        default="",
        description="以路径参数为准，body 中可省略",
    )
    scenarios: list[str] | None = Field(
        default=None,
        description="要跑的情景子集：price_fluctuation | natural_disaster | party_breach；缺省全部",
    )
    params: dict = Field(
        default_factory=dict,
        description="情景参数，按情景分组，如 {\"price_fluctuation\": {\"price_change_pct\": -15}}",
    )


@router.post("/{doc_id}", summary="对某份合同执行履约模拟（三情景）")
def simulate(doc_id: str, payload: SimulateRequest | None = None) -> dict:
    body = payload or SimulateRequest()
    try:
        report = service.simulate(
            doc_id,
            scenarios=body.scenarios,
            params=body.params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if report is None:
        raise HTTPException(status_code=404, detail=f"未找到合同 {doc_id}")
    return report.model_dump()


@router.get("/rules", summary="裁判规则库状态")
def rules_status() -> dict:
    return {
        "total": len(rulebook.load_rules()),
        "source": str(rulebook.summary_path()),
        "scenarios": {
            key: len([r for r in rulebook.load_rules() if r["scenario"] == key])
            for key in rulebook.SCENARIOS
        },
    }
