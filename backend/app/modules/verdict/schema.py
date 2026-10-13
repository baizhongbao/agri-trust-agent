"""汇总判定层的数据模型。

四个模块各自给出分项结论（解析 / 条款 / 主体 / 履约），本层把它们归并成
一份「这份合同整体到底可不可信」的判断。三条原则：

- **一票否决 + 就低不就高**：客观硬伤（解析被门禁阻断 / 主体核验 fail /
  违反强制性依据）直接把总等级压到「高风险」；其余情况取四维中最差者，
  不存在「功过相抵」。
- **失败必须可见**：任一模块没跑成，对应维度标「不可评」并附 notice，
  绝不用「0 分」冒充「没问题」（这是本项目最容易误读的坑）。
- **不做过早加权总分**：先出分项，总等级用离散等级表达；
  维度上的 `score` 只是启发式展示值，不参与最终判定。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

GRADE_TRUSTED = "可信"
GRADE_MOSTLY = "基本可信"
GRADE_ATTENTION = "需关注"
GRADE_HIGH = "高风险"
GRADE_UNDETERMINED = "不可评"

# rank 越大越好，用于「就低不就高」的比较
GRADE_RANK = {
    GRADE_UNDETERMINED: 0,
    GRADE_HIGH: 1,
    GRADE_ATTENTION: 2,
    GRADE_MOSTLY: 3,
    GRADE_TRUSTED: 4,
}


class DimensionVerdict(BaseModel):
    """单个维度的判定。"""

    key: str = Field(description="completeness | clauses | parties | performance")
    label: str = ""
    level: str = Field(default=GRADE_UNDETERMINED, description="五档等级之一")
    score: int = Field(default=0, ge=0, le=100, description="启发式分数，仅供展示，不作依据")
    summary: str = ""
    notice: str = Field(default="", description="非空表示该维度未完整评估")
    findings: list[str] = Field(default_factory=list, description="关键发现，逐条可回溯")


class Blocker(BaseModel):
    """一票否决项（客观硬伤）。"""

    key: str
    label: str
    detail: str = ""
    evidence: str = ""
    dimension: str = ""


class OverallVerdict(BaseModel):
    """一份合同的汇总结论。"""

    doc_id: str
    contract_title: str = ""
    grade: str = GRADE_UNDETERMINED
    grade_reason: str = ""
    blockers: list[Blocker] = Field(default_factory=list)
    dimensions: list[DimensionVerdict] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(
        default_factory=list, description="未执行 / 不可用的模块，其结论不可信"
    )
    narrative: str = Field(default="", description="结论摘要（阶段②接 LLM，当前为模板）")
    notices: list[str] = Field(default_factory=list)
    generated_at: str = ""
    disclaimer: str = ""
