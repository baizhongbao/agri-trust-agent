"""履约模拟模块的数据模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """一条裁判规则引用。"""

    scenario: str = ""
    case_no: str = ""
    court: str = ""
    title: str = ""
    signal: str = ""
    ruling: str = ""
    lesson: str = ""
    keyword_hits: int = 0


class ScenarioResult(BaseModel):
    """单个情景的推演结果。"""

    scenario: str
    label: str = ""
    computable: bool = False
    reason: str = ""
    params: dict = Field(default_factory=dict)
    calc_steps: list[dict] = Field(default_factory=list, description="计算过程，逐项公式与结果，可复核")
    checks: list[dict] = Field(
        default_factory=list,
        description="确定性一致性校验的结构化结论（code / status / detail）。"
        "status != ok 表示输入事实之间存在矛盾，数值虽已算出但需人工核对；"
        "空列表表示该情景没有可自动校验的约束",
    )
    summary: str = ""
    legal_note: str = ""
    analysis: str = Field(default="", description="LLM 定性分析（引用裁判规则的解释文字）")
    citations: list[Citation] = Field(default_factory=list, description="裁判规则引用")
    analysis_provider: str = Field(default="", description="定性分析由哪个 LLM 生成（mock 时标注）")


class SimulationReport(BaseModel):
    """一份合同的履约模拟报告。"""

    doc_id: str
    contract_title: str = ""
    notice: str = Field(
        default="",
        description="模拟未完整执行的显式说明（如合同事实缺失导致 computable=false）。"
        "为空表示所有情景均正常算出了数值",
    )
    scenarios: list[ScenarioResult] = Field(default_factory=list)
    rulebook_total: int = Field(default=0, description="裁判规则库规模（条）")
    disclaimer: str = ""
