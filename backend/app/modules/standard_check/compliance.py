"""合同约定值与标准限值的数值比对。

为什么这是「校验」的最后一块：
    标准条款匹配只能告诉你"这条合同条款像 GB/T 1354 第 5.2 条"（相似度 0.99），
    却回答不了"合同写的 14.5% 到底合不合规"。
    要给出合规结论，必须把合同值与标准限值放进同一个坐标系里比大小。
    做完这一步，「标准校验」才真正从"检索"变成"校验"。

比对的两侧：
    合同侧：StructuredContract.facts —— 已由 facts.py 抽成数值 + 比较符
    标准侧：标准库 clause.limits —— 人工整理的限值，带适用范围

只对「双方都有的指标」下结论。
    合同没约定的指标不在这里报——那属于"缺失"，由 checklist 负责。
    一件事只有一个责任人，报告才不会自相矛盾。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.modules.standard_check import loader

logger = logging.getLogger(__name__)

# 比例类指标的合同侧名称：由 facts.penalty.rate 换算而来
PENALTY_METRIC = "违约金比例"

_DISCLAIMER = (
    "比对基于标准库中已结构化的限值。同一指标在不同品类下限值不同"
    "（如籼稻谷与粳稻谷的水分要求），请结合 applies_to 与标准原文判断适用性。"
)

_OP_ALIASES = {"≤": "<=", "≥": ">=", "＜": "<", "＞": ">"}


@dataclass(frozen=True)
class Limit:
    """标准侧的一条限值。"""

    metric: str
    op: str  # <= | >= | range
    value: float
    unit: str = ""
    upper: float | None = None  # 仅 range
    applies_to: str = ""


@dataclass(frozen=True)
class LimitSource:
    """限值及其出处——结论必须能指回具体标准条款。"""

    standard_code: str
    standard_title: str
    clause_no: str
    clause_title: str
    limit: Limit


@lru_cache(maxsize=1)
def load_limits() -> tuple[LimitSource, ...]:
    """从标准库摊平出全部限值。"""
    sources: list[LimitSource] = []

    for item in loader.load_items():
        for raw in item.get("limits") or []:
            try:
                limit = Limit(
                    metric=str(raw.get("metric", "") or "").strip(),
                    op=_normalize_op(str(raw.get("op", "") or "")),
                    value=float(raw["value"]),
                    unit=str(raw.get("unit", "") or ""),
                    upper=float(raw["upper"]) if raw.get("upper") is not None else None,
                    applies_to=str(raw.get("applies_to", "") or ""),
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("标准限值定义非法，已跳过：%s（%s）", exc, raw)
                continue

            if not limit.metric or limit.op not in {"<=", ">=", "range"}:
                continue

            sources.append(
                LimitSource(
                    standard_code=str(item.get("standard_code", "")),
                    standard_title=str(item.get("standard_title", "")),
                    clause_no=str(item.get("clause_no", "")),
                    clause_title=str(item.get("clause_title", "")),
                    limit=limit,
                )
            )

    logger.info("标准限值加载完成：%d 条", len(sources))
    return tuple(sources)


def _normalize_op(op: str) -> str:
    op = (op or "").strip()
    return _OP_ALIASES.get(op, op)


def contract_values(contract: Any) -> dict[str, tuple[str, float, str]]:
    """把结构化事实换算成 {指标名: (比较符, 值, 单位)}。

    只有带数值的事实才参与比对——抽不到值的不猜。
    """
    values: dict[str, tuple[str, float, str]] = {}

    facts = getattr(contract, "facts", None)
    if facts is None:
        return values

    for metric in getattr(facts, "quality_metrics", []) or []:
        if metric.value is None or not metric.name:
            continue
        values[metric.name] = (
            _normalize_op(metric.op or "="),
            float(metric.value),
            metric.unit or "",
        )

    penalty = getattr(facts, "penalty", None)
    if penalty is not None and penalty.rate is not None:
        # facts 里存的是小数（0.10），标准里写的是百分数（30%）
        values[PENALTY_METRIC] = ("<=", round(penalty.rate * 100, 4), "%")

    return values


def _match_metric(contract_metric: str, limit_metric: str) -> bool:
    """指标名匹配，允许一方包含另一方。

    合同写「碎米」而标准写「碎米总量」，指的是同一件事；
    但过短的词（1 个字）不参与包含匹配，否则「水」会匹配一切。
    """
    left = (contract_metric or "").strip()
    right = (limit_metric or "").strip()
    if not left or not right:
        return False
    if left == right:
        return True
    if min(len(left), len(right)) < 2:
        return False
    return left in right or right in left


def _fmt(value: float, unit: str) -> str:
    number = f"{value:g}"
    return f"{number}{unit}" if unit else number


def compare(
    contract_op: str,
    contract_value: float,
    contract_unit: str,
    limit: Limit,
) -> tuple[str, str]:
    """比对单个指标，返回 (status, reason)。

    status: compliant | violation | review
        review 用于"系统无法判断"的情形（单位不一致、约束方向冲突），
        这类必须显式暴露出来，而不是硬给一个合规结论。
    """
    if limit.unit and contract_unit and limit.unit != contract_unit:
        return "review", f"单位不一致（合同 {contract_unit} / 标准 {limit.unit}），需人工核对"

    if limit.op == "range":
        if limit.upper is None:
            return "review", "标准限值区间不完整，需人工核对"
        if contract_op in {"<=", ">="}:
            return (
                "review",
                f"合同为单边约定（{_fmt(contract_value, contract_unit)} 以下/以上），"
                f"标准为区间要求 {_fmt(limit.value, limit.unit)}~{_fmt(limit.upper, limit.unit)}，需人工核对",
            )
        if limit.value <= contract_value <= limit.upper:
            return (
                "compliant",
                f"合同值 {_fmt(contract_value, contract_unit)} "
                f"落在标准区间 {_fmt(limit.value, limit.unit)}~{_fmt(limit.upper, limit.unit)} 内",
            )
        return (
            "violation",
            f"合同值 {_fmt(contract_value, contract_unit)} "
            f"超出标准区间 {_fmt(limit.value, limit.unit)}~{_fmt(limit.upper, limit.unit)}",
        )

    if contract_op != limit.op:
        return (
            "review",
            f"约束方向不同（合同 {contract_op} / 标准 {limit.op}），需人工核对",
        )

    if limit.op == "<=":
        if contract_value <= limit.value:
            return (
                "compliant",
                f"合同上限 {_fmt(contract_value, contract_unit)} "
                f"未超出标准上限 {_fmt(limit.value, limit.unit)}",
            )
        return (
            "violation",
            f"合同上限 {_fmt(contract_value, contract_unit)} "
            f"宽于标准上限 {_fmt(limit.value, limit.unit)}",
        )

    # >=
    if contract_value >= limit.value:
        return (
            "compliant",
            f"合同下限 {_fmt(contract_value, contract_unit)} "
            f"不低于标准下限 {_fmt(limit.value, limit.unit)}",
        )
    return (
        "violation",
        f"合同下限 {_fmt(contract_value, contract_unit)} "
        f"低于标准下限 {_fmt(limit.value, limit.unit)}",
    )


def check_compliance(contract: Any) -> dict[str, Any]:
    """逐项比对合同约定值与标准限值。"""
    sources = load_limits()
    values = contract_values(contract)

    if not values:
        return {
            "total": 0,
            "compliant_count": 0,
            "violation_count": 0,
            "review_count": 0,
            "violations": [],
            "items": [],
            "summary": "合同中未抽到可量化的约定值，无法比对",
            "disclaimer": _DISCLAIMER,
        }

    grouped: dict[tuple, dict[str, Any]] = {}

    for source in sources:
        matched = next(
            (name for name in values if _match_metric(name, source.limit.metric)), None
        )
        if matched is None:
            continue  # 合同没有约定这个指标，缺失由 checklist 报告

        # 同一标准条款下数值相同的限值合并（如籼米与晚籼米同为 14.5%）
        key = (
            source.standard_code,
            source.clause_no,
            source.limit.metric,
            source.limit.op,
            source.limit.value,
            source.limit.upper,
        )
        if key in grouped:
            if source.limit.applies_to and source.limit.applies_to not in grouped[key]["applies_to"]:
                grouped[key]["applies_to"].append(source.limit.applies_to)
            continue

        contract_op, contract_value, contract_unit = values[matched]
        status, reason = compare(contract_op, contract_value, contract_unit, source.limit)

        grouped[key] = {
            "metric": source.limit.metric,
            "contract_metric": matched,
            "contract_op": contract_op,
            "contract_value": contract_value,
            "contract_unit": contract_unit,
            "standard_value": source.limit.value,
            "standard_upper": source.limit.upper,
            "standard_op": source.limit.op,
            "standard_unit": source.limit.unit,
            "standard_code": source.standard_code,
            "standard_title": source.standard_title,
            "clause_no": source.clause_no,
            "clause_title": source.clause_title,
            "applies_to": [source.limit.applies_to] if source.limit.applies_to else [],
            "status": status,
            "reason": reason,
        }

    items = list(grouped.values())
    # 违规排最前，其次待人工核对，合规最后——先看要紧的
    order = {"violation": 0, "review": 1, "compliant": 2}
    items.sort(key=lambda item: order.get(item["status"], 3))

    violations = [item for item in items if item["status"] == "violation"]
    reviews = [item for item in items if item["status"] == "review"]
    compliant = [item for item in items if item["status"] == "compliant"]

    return {
        "total": len(items),
        "compliant_count": len(compliant),
        "violation_count": len(violations),
        "review_count": len(reviews),
        "violations": violations,
        "reviews": reviews,
        "items": items,
        "summary": (
            f"可比对指标 {len(items)} 项：合规 {len(compliant)} 项、"
            f"超出标准 {len(violations)} 项、待人工核对 {len(reviews)} 项"
        ),
        "disclaimer": _DISCLAIMER,
    }
