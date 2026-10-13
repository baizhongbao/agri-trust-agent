"""汇总判定层的编排逻辑。

本模块是「上层编排」：它是唯一允许同时 import 四个业务模块的地方——
其余模块彼此不直接 import（见 AGENTS.md 架构铁律第 7 条）。

`build_verdict` 是纯函数：喂四个模块的结果，吐一份 OverallVerdict，
不联网、不调 LLM，可脱离整条流水线单元测试。
`run_verdict` 负责取数：读合同 + 依次跑标准校验 / 企业核验 / 履约模拟，
任何单个模块失败都不允许让汇总层崩掉，只把该维度标成「不可评」。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.modules.contract_parser import service as contract_service
from app.modules.enterprise_verify import service as enterprise_service
from app.modules.simulation import service as simulation_service
from app.modules.standard_check import service as standard_service
from app.modules.verdict.schema import (
    GRADE_ATTENTION,
    GRADE_HIGH,
    GRADE_MOSTLY,
    GRADE_RANK,
    GRADE_TRUSTED,
    GRADE_UNDETERMINED,
    Blocker,
    DimensionVerdict,
    OverallVerdict,
)

logger = logging.getLogger(__name__)

_DISCLAIMER = (
    "汇总结论由各模块既有判定归并而成，等级用于提示复核优先级，"
    "不构成法律或投资意见。任一分项标注「不可评」时，不得把缺失读成「无风险」。"
)

# 维度键（同时用于错误映射与缺项追踪）
_DIM_COMPLETENESS = "completeness"
_DIM_CLAUSES = "clauses"
_DIM_PARTIES = "parties"
_DIM_PERFORMANCE = "performance"

_DIM_LABELS = {
    _DIM_COMPLETENESS: "信息完备性",
    _DIM_CLAUSES: "条款合规",
    _DIM_PARTIES: "主体可信",
    _DIM_PERFORMANCE: "履约风险",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


# ---------------------------------------------------------------- 维度 A

def _completeness_dim(contract: Any, blockers: list[Blocker]) -> DimensionVerdict:
    gate = getattr(contract, "gate", None)
    if gate is None:
        return DimensionVerdict(
            key=_DIM_COMPLETENESS,
            label=_DIM_LABELS[_DIM_COMPLETENESS],
            level=GRADE_UNDETERMINED,
            summary="缺少解析门禁信息",
            notice="解析结果未附带 gate，无法判断必备字段是否齐备",
        )

    findings: list[str] = []
    summary = _text(getattr(gate, "summary", ""))
    for failure in getattr(gate, "failures", []) or []:
        detail = _text(getattr(failure, "detail", ""))
        label = _text(getattr(failure, "label", "")) or getattr(failure, "key", "")
        if label or detail:
            findings.append(f"{label}：{detail}".strip("："))

    level = getattr(gate, "level", "") or ""
    if level == "blocked":
        blockers.append(
            Blocker(
                key="parse_blocked",
                label="解析结果不可用（门禁阻断）",
                detail=summary or "主体或正文缺失",
                dimension=_DIM_COMPLETENESS,
            )
        )
        return DimensionVerdict(
            key=_DIM_COMPLETENESS,
            label=_DIM_LABELS[_DIM_COMPLETENESS],
            level=GRADE_UNDETERMINED,
            score=0,
            summary=summary or "解析被门禁阻断，下游结论不可信",
            notice="主体或正文缺失，必须补全后重新解析",
            findings=findings,
        )
    if level == "degraded":
        return DimensionVerdict(
            key=_DIM_COMPLETENESS,
            label=_DIM_LABELS[_DIM_COMPLETENESS],
            level=GRADE_ATTENTION,
            score=60,
            summary=summary or "部分必备字段缺失，下游结论需携带该标注",
            findings=findings,
        )
    return DimensionVerdict(
        key=_DIM_COMPLETENESS,
        label=_DIM_LABELS[_DIM_COMPLETENESS],
        level=GRADE_TRUSTED,
        score=100,
        summary=summary or "必备字段齐备",
        findings=findings,
    )


# ---------------------------------------------------------------- 维度 B

def _clauses_dim(standard: dict | None, blockers: list[Blocker]) -> DimensionVerdict:
    dim = DimensionVerdict(key=_DIM_CLAUSES, label=_DIM_LABELS[_DIM_CLAUSES])
    if not standard:
        dim.notice = "标准校验未执行或不可用"
        dim.summary = "未拿到标准校验结果"
        return dim

    req = standard.get("required_clauses") or {}
    comp = standard.get("compliance") or {}

    required_total = int(req.get("required_total") or 0)
    covered = int(req.get("required_covered") or 0)
    coverage = (covered / required_total) if required_total else 0.0
    missing_required = req.get("missing_required") or []
    high_risk_missing = [m for m in missing_required if m.get("risk") == "high"]
    violations = int(comp.get("violation_count") or 0)
    mandatory = int(comp.get("mandatory_violation_count") or 0)

    findings: list[str] = []
    if _text(req.get("summary")):
        findings.append(_text(req["summary"]))
    if _text(comp.get("summary")):
        findings.append(_text(comp["summary"]))
    for item in missing_required[:5]:
        findings.append(
            f"缺失必备条款：{item.get('name', '')}（风险 {item.get('risk', '')}）"
        )

    if mandatory > 0:
        first = (comp.get("mandatory_violations") or comp.get("violations") or [{}])[0]
        blockers.append(
            Blocker(
                key="mandatory_violation",
                label="违反强制性依据",
                detail=_text(comp.get("summary")),
                evidence=_text(first.get("reason")) or _text(first.get("metric")),
                dimension=_DIM_CLAUSES,
            )
        )
        level = GRADE_HIGH
    elif coverage >= 1.0 and violations == 0:
        level = GRADE_TRUSTED
    elif coverage >= 0.8 and not high_risk_missing:
        level = GRADE_MOSTLY
    else:
        level = GRADE_ATTENTION

    score = round(coverage * 100)
    if mandatory:
        score = min(score, 30)
    elif high_risk_missing:
        score = min(score, 55)

    dim.level = level
    dim.score = score
    dim.summary = _text(req.get("summary")) or f"必备条款覆盖 {covered}/{required_total}"
    dim.findings = findings
    return dim


# ---------------------------------------------------------------- 维度 C

def _parties_dim(verify: Any, blockers: list[Blocker]) -> DimensionVerdict:
    dim = DimensionVerdict(key=_DIM_PARTIES, label=_DIM_LABELS[_DIM_PARTIES])
    if verify is None:
        dim.notice = "企业核验未执行或不可用"
        dim.summary = "未拿到企业核验结果"
        return dim

    parties = getattr(verify, "parties", None) or []
    notice = _text(getattr(verify, "notice", ""))
    if not parties:
        dim.notice = notice or "合同未识别到可核验主体"
        dim.summary = "没有主体可供核验，主体可信度无法判定"
        return dim

    findings: list[str] = []
    statuses: list[str] = []
    for party in parties:
        status = getattr(party, "overall", "") or "review"
        statuses.append(status)
        role = getattr(party, "role", "")
        name = getattr(party, "name", "")
        l2 = getattr(party, "l2_status", "")
        findings.append(f"{role} {name}：{status}（工商查询 {l2 or '未执行'}）")
        if status == "fail":
            blockers.append(
                Blocker(
                    key=f"party_fail_{role}",
                    label=f"主体核验不通过：{name or role}",
                    detail=_text(getattr(party, "l2_note", "")),
                    evidence=getattr(party, "credit_code", ""),
                    dimension=_DIM_PARTIES,
                )
            )

    if "fail" in statuses:
        level = GRADE_HIGH
    elif "review" in statuses:
        level = GRADE_ATTENTION
    elif "warning" in statuses:
        level = GRADE_MOSTLY
    else:
        level = GRADE_TRUSTED

    # 核验没跑全（有 notice）时不能宣称「可信」
    if notice and GRADE_RANK[level] > GRADE_RANK[GRADE_ATTENTION]:
        level = GRADE_ATTENTION

    dim.level = level
    dim.score = 100 if level == GRADE_TRUSTED else (70 if level == GRADE_MOSTLY else 40)
    dim.summary = f"共 {len(parties)} 个主体，综合判定：" + "、".join(
        f"{s}×{statuses.count(s)}" for s in dict.fromkeys(statuses)
    )
    dim.notice = notice
    dim.findings = findings
    return dim


# ---------------------------------------------------------------- 维度 D

def _performance_dim(simulation: Any) -> DimensionVerdict:
    dim = DimensionVerdict(key=_DIM_PERFORMANCE, label=_DIM_LABELS[_DIM_PERFORMANCE])
    if simulation is None:
        dim.notice = "履约模拟未执行或不可用"
        dim.summary = "未拿到履约模拟结果"
        return dim

    scenarios = getattr(simulation, "scenarios", None) or []
    notice = _text(getattr(simulation, "notice", ""))
    computable = [s for s in scenarios if getattr(s, "computable", False)]

    findings = []
    for scenario in scenarios:
        label = getattr(scenario, "label", "") or getattr(scenario, "scenario", "")
        summary_text = _text(getattr(scenario, "summary", ""))
        if summary_text:
            findings.append(f"{label}：{summary_text}")

    if not scenarios or not computable:
        dim.level = GRADE_UNDETERMINED
        dim.notice = notice or "所有情景均无法量化（合同缺少金额/数量等事实）"
        dim.summary = "三情景均未算出数值，履约风险无法量化"
        dim.findings = findings
        return dim

    dim.level = GRADE_TRUSTED if len(computable) == len(scenarios) else GRADE_ATTENTION
    dim.score = 100 if dim.level == GRADE_TRUSTED else 60
    dim.summary = f"{len(computable)}/{len(scenarios)} 个情景完成数值量化"
    if len(computable) != len(scenarios):
        dim.notice = notice or "部分情景无法量化"
    dim.findings = findings
    return dim


# ---------------------------------------------------------------- 归并

def _combine(
    dimensions: list[DimensionVerdict], blockers: list[Blocker]
) -> tuple[str, str]:
    by_key = {d.key: d for d in dimensions}
    completeness = by_key.get(_DIM_COMPLETENESS)

    # 信息完备性是地基：挡在门禁外，后面三个维度算得再漂亮也不可信
    if completeness and completeness.level == GRADE_UNDETERMINED:
        return GRADE_UNDETERMINED, "合同解析未通过门禁，主体或正文缺失，无法给出可信结论"

    if blockers:
        top = blockers[0]
        return GRADE_HIGH, f"存在否决项：{top.label}"

    worst = min(dimensions, key=lambda d: GRADE_RANK.get(d.level, 0))
    if worst.level == GRADE_UNDETERMINED:
        return GRADE_ATTENTION, f"「{worst.label}」未完整评估，不足以给出更高等级"
    if worst.level == GRADE_TRUSTED:
        return GRADE_TRUSTED, "四个维度均无否决项且评估完整"
    return worst.level, f"受最弱维度「{worst.label}」限制"


def _build_narrative(verdict: OverallVerdict) -> str:
    """模板版结论摘要。阶段②会换成 LLM，数值与等级仍由本层给定。"""
    lines = [f"总体判定：{verdict.grade}（{verdict.grade_reason}）。"]
    for dim in verdict.dimensions:
        lines.append(f"{dim.label}：{dim.level}——{dim.summary}")
    if verdict.missing_dimensions:
        lines.append("未评估维度：" + "、".join(verdict.missing_dimensions) + "。")
    return " ".join(lines)


def build_verdict(
    contract: Any,
    standard: dict | None,
    verify: Any,
    simulation: Any,
    errors: dict[str, str] | None = None,
    doc_id: str = "",
) -> OverallVerdict:
    """把四个模块的结果归并成汇总结论（纯函数，不联网）。"""
    errors = errors or {}
    blockers: list[Blocker] = []

    dimensions = [
        _completeness_dim(contract, blockers),
        _clauses_dim(standard, blockers),
        _parties_dim(verify, blockers),
        _performance_dim(simulation),
    ]

    missing_dimensions = [
        dim.label
        for dim in dimensions
        if dim.level == GRADE_UNDETERMINED and dim.key != _DIM_COMPLETENESS
    ]
    notices = [f"{dim.label}：{dim.notice}" for dim in dimensions if dim.notice]
    for key, message in errors.items():
        label = _DIM_LABELS.get(key, key)
        notices.append(f"{label}执行异常：{message}")

    grade, reason = _combine(dimensions, blockers)

    verdict = OverallVerdict(
        doc_id=doc_id or getattr(contract, "doc_id", "") or "",
        contract_title=getattr(contract, "title", "") or "",
        grade=grade,
        grade_reason=reason,
        blockers=blockers,
        dimensions=dimensions,
        missing_dimensions=missing_dimensions,
        notices=notices,
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        disclaimer=_DISCLAIMER,
    )
    verdict.narrative = _build_narrative(verdict)
    return verdict


def collect(doc_id: str) -> tuple[Any, dict | None, Any, Any, dict[str, str]] | None:
    """读合同并依次跑其余三模块，返回 (contract, standard, verify, simulation, errors)。

    单个模块失败不抛出，只记进 errors——汇总层与报告导出共用这套取数逻辑，
    避免重复调用工商接口 / LLM。合同本身读不到才返回 None。
    """
    contract = contract_service.get_contract(doc_id)
    if contract is None:
        return None

    errors: dict[str, str] = {}

    try:
        standard = standard_service.check_contract(doc_id)
    except Exception as exc:  # noqa: BLE001 —— 汇总层必须兜住任何单模块异常
        logger.warning("汇总判定：标准校验失败 doc_id=%s：%s", doc_id, exc)
        standard = None
        errors[_DIM_CLAUSES] = str(exc)

    try:
        verify = enterprise_service.verify_contract(doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("汇总判定：企业核验失败 doc_id=%s：%s", doc_id, exc)
        verify = None
        errors[_DIM_PARTIES] = str(exc)

    try:
        simulation = simulation_service.simulate(doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("汇总判定：履约模拟失败 doc_id=%s：%s", doc_id, exc)
        simulation = None
        errors[_DIM_PERFORMANCE] = str(exc)

    return contract, standard, verify, simulation, errors


def run_verdict(doc_id: str) -> OverallVerdict | None:
    """取数并归并：读合同 → 标准校验 / 企业核验 / 履约模拟 → build_verdict。"""
    collected = collect(doc_id)
    if collected is None:
        return None
    contract, standard, verify, simulation, errors = collected
    return build_verdict(contract, standard, verify, simulation, errors=errors, doc_id=doc_id)
