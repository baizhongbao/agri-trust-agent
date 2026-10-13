"""合同约定值与依据限值的数值比对。

为什么这是「校验」的最后一块：
    标准条款匹配只能告诉你"这条合同条款像 GB/T 1354 第 5.2 条"（相似度 0.99），
    却回答不了"合同写的 14.5% 到底合不合规"。
    要给出合规结论，必须把合同值与依据限值放进同一个坐标系里比大小。

比对的两侧：
    合同侧：StructuredContract.facts —— 已由 facts.py 抽成数值 + 比较符
    依据侧：标准库 clause.limits —— 人工整理的限值，带适用范围与规则强度

三个必须守住的边界：
    1. 只对「双方都有的指标」下结论。合同没约定的指标不在此处报——
       那属于"缺失"，由 checklist 负责。一件事只有一个责任人。
    2. 判不了就返回 review，不硬给结论（单位不一致 / 方向冲突 / 区间对单边）。
    3. **规则强度决定判定性质**：强制性依据（食品安全标准、法律）不满足才算"违规"；
       推荐性标准（GB/T）只有被合同约定采用才成为义务，只能称"低于推荐标准"；
       指导性文件（示范文本、行政指导）不具约束力，只能称"偏离建议"。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.modules.standard_check import loader

logger = logging.getLogger(__name__)

# 合同侧参与比对的"比例类"指标：由 facts 换算而来
PENALTY_METRIC = "违约金比例"
DEPOSIT_METRIC = "定金比例"

_OP_ALIASES = {"≤": "<=", "≥": ">=", "＜": "<", "＞": ">"}

# 规则强度 → 业务含义与严重程度
_STRENGTH_LABEL = {
    "mandatory": "强制性依据",
    "recommended": "推荐性标准",
    "advisory": "指导性文件",
}
_STRENGTH_SEVERITY = {
    "mandatory": "high",
    "recommended": "medium",
    "advisory": "low",
}
# 违反时的判定措辞：强制性才算"违规"，其余只是"偏离"
_STRENGTH_VERDICT = {
    "mandatory": "违规",
    "recommended": "低于推荐标准",
    "advisory": "偏离建议",
}

_DISCLAIMER = (
    "比对基于依据库中已结构化的限值。同一指标在不同品类下限值不同"
    "（如籼稻谷与粳稻谷的水分要求），请结合 applies_to 与原文判断适用性。"
    "推荐性标准与指导性文件不具强制约束力，相关提示仅供完善合同参考。"
)


@dataclass(frozen=True)
class Limit:
    """依据侧的一条限值。"""

    metric: str
    op: str  # <= | >= | range
    value: float
    unit: str = ""
    upper: float | None = None  # 仅 range
    applies_to: str = ""


@dataclass(frozen=True)
class LimitSource:
    """限值及其出处——结论必须能指回具体依据条款。"""

    standard_code: str
    standard_title: str
    clause_no: str
    clause_title: str
    limit: Limit
    rule_strength: str = ""
    standard_type: str = ""
    effective_date: str | None = None


@lru_cache(maxsize=1)
def load_limits() -> tuple[LimitSource, ...]:
    """从依据库摊平出全部限值。"""
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
                logger.warning("依据限值定义非法，已跳过：%s（%s）", exc, raw)
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
                    rule_strength=str(item.get("rule_strength", "") or ""),
                    standard_type=str(item.get("standard_type", "") or ""),
                    effective_date=item.get("effective_date"),
                )
            )

    logger.info("依据限值加载完成：%d 条", len(sources))
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

    # facts 里存小数（0.10），依据里写百分数（20%），此处统一换算成百分数
    penalty = getattr(facts, "penalty", None)
    if penalty is not None and penalty.rate is not None:
        values[PENALTY_METRIC] = ("<=", round(penalty.rate * 100, 4), "%")

    deposit = getattr(facts, "deposit", None)
    if deposit is not None and deposit.rate is not None:
        values[DEPOSIT_METRIC] = ("<=", round(deposit.rate * 100, 4), "%")

    return values


# 品类约束：applies_to 里出现这些词，才说明该限值与「标的品类」相关；
# 像「合同总金额」「主合同标的额」「精碾」这类非品类约束不参与过滤。
_SUBJECT_TERMS = ("稻谷", "大米", "籼米", "粳米", "糯米", "糙米")
# 通用品类 → 其下更具体的品类，避免「大米」合同丢掉籼米 / 粳米的共同限值
_GENERIC_SUBJECT_EXPANSION = {
    "大米": ("籼米", "粳米"),
    "稻谷": ("籼稻谷", "粳稻谷"),
}


def _is_subject_constraint(applies_to: str) -> bool:
    return any(term in (applies_to or "") for term in _SUBJECT_TERMS)


def applies_to_subject(subject: str, applies_to: str) -> bool:
    """判断某条限值的适用范围是否适用于该合同标的品类。

    适用范围为空、或非品类约束（如「合同总金额」）→ 一律适用；
    未抽到品类（subject 为空）→ 不过滤，与改动前完全一致（向后兼容）；
    否则按包含关系匹配，并支持「通用品类 → 更具体品类」展开
    （「大米」合同仍适用于籼米 / 粳米的共同限值）。
    """
    scope = (applies_to or "").strip()
    if not scope or not _is_subject_constraint(scope):
        return True
    if not subject:
        return True

    tokens = [t.strip() for t in re.split(r"[、,，/]", scope) if t.strip()]
    expansions = _GENERIC_SUBJECT_EXPANSION.get(subject, ())
    return any(
        token == subject or token in subject or subject in token or token in expansions
        for token in tokens
    )


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


def _verdict(strength: str) -> str:
    return _STRENGTH_VERDICT.get(strength, "偏离依据")


def _direction_phrase(op: str) -> str:
    return "上限" if op == "<=" else "下限"


def compare(
    contract_op: str,
    contract_value: float,
    contract_unit: str,
    limit: Limit,
    strength: str = "mandatory",
) -> tuple[str, str]:
    """比对单个指标，返回 (status, reason)。

    status: compliant | violation | review
        violation 的**性质**由 strength 决定：
        强制性依据违反 → 违规；推荐性标准 → 低于推荐标准；指导性文件 → 偏离建议。
        review 用于"系统无法判断"的情形，必须显式暴露，而不是硬给结论。
    """
    if limit.unit and contract_unit and limit.unit != contract_unit:
        return "review", f"单位不一致（合同 {contract_unit} / 依据 {limit.unit}），需人工核对"

    if limit.op == "range":
        if limit.upper is None:
            return "review", "依据限值区间不完整，需人工核对"
        if contract_op in {"<=", ">="}:
            return (
                "review",
                f"合同为单边约定（{_fmt(contract_value, contract_unit)} 以下/以上），"
                f"依据为区间要求 {_fmt(limit.value, limit.unit)}~{_fmt(limit.upper, limit.unit)}，需人工核对",
            )
        if limit.value <= contract_value <= limit.upper:
            return (
                "compliant",
                f"合同值 {_fmt(contract_value, contract_unit)} "
                f"落在依据区间 {_fmt(limit.value, limit.unit)}~{_fmt(limit.upper, limit.unit)} 内",
            )
        return (
            "violation",
            f"合同值 {_fmt(contract_value, contract_unit)} "
            f"超出依据区间 {_fmt(limit.value, limit.unit)}~{_fmt(limit.upper, limit.unit)}",
        )

    if contract_op != limit.op:
        return (
            "review",
            f"约束方向不同（合同 {contract_op} / 依据 {limit.op}），需人工核对",
        )

    if limit.op == "<=":
        if contract_value <= limit.value:
            return (
                "compliant",
                f"合同上限 {_fmt(contract_value, contract_unit)} "
                f"未超出依据上限 {_fmt(limit.value, limit.unit)}",
            )
        return (
            "violation",
            f"{_verdict(strength)}：合同上限 {_fmt(contract_value, contract_unit)} "
            f"宽于{_STRENGTH_LABEL.get(strength, '依据')}上限 {_fmt(limit.value, limit.unit)}",
        )

    # >=
    if contract_value >= limit.value:
        return (
            "compliant",
            f"合同下限 {_fmt(contract_value, contract_unit)} "
            f"不低于依据下限 {_fmt(limit.value, limit.unit)}",
        )
    return (
        "violation",
        f"{_verdict(strength)}：合同下限 {_fmt(contract_value, contract_unit)} "
        f"低于{_STRENGTH_LABEL.get(strength, '依据')}下限 {_fmt(limit.value, limit.unit)}",
    )


def _timeliness(contract: Any) -> list[dict[str, Any]]:
    """检查合同签订日期与依据生效日期的关系。

    标准会换版。一份 2025 年签订的合同，不应该用 2026 年才生效的版本去评判，
    至少要把这个时间差提示出来——这正是「版本化依据库」的价值所在。

    这里基于**全部标准**而非仅含限值的标准，因为像《订单农业合同规范指引》
    这类没有量化限值但有时效性的依据，同样需要提示。
    """
    facts = getattr(contract, "facts", None)
    sign_date = getattr(facts, "sign_date", None) if facts is not None else None
    sign_iso = getattr(sign_date, "start", None) if sign_date is not None else None
    if not sign_iso:
        return []

    notices: list[dict[str, Any]] = []

    for entry in loader.summarize_library():
        code = str(entry.get("standard_code", ""))
        effective = entry.get("effective_date")
        if not code or not effective or sign_iso >= str(effective):
            continue
        notices.append(
            {
                "standard_code": code,
                "standard_title": entry.get("standard_title", ""),
                "effective_date": effective,
                "contract_sign_date": sign_iso,
                "message": (
                    f"合同签订日（{sign_iso}）早于 {code} 的生效日（{effective}），"
                    "本次比对依据为现行版本，订立时适用的版本可能不同，建议核对历史版本"
                ),
            }
        )

    return notices


def check_compliance(contract: Any) -> dict[str, Any]:
    """逐项比对合同约定值与依据限值。"""
    sources = load_limits()
    values = contract_values(contract)
    timeliness = _timeliness(contract)

    facts = getattr(contract, "facts", None)
    subject = str(getattr(facts, "subject_category", "") or "") if facts is not None else ""

    if not values:
        return {
            "total": 0,
            "compliant_count": 0,
            "violation_count": 0,
            "mandatory_violation_count": 0,
            "review_count": 0,
            "violations": [],
            "mandatory_violations": [],
            "reviews": [],
            "items": [],
            "timeliness": timeliness,
            "subject_category": subject,
            "filtered_out_count": 0,
            "summary": "合同中未抽到可量化的约定值，无法比对",
            "disclaimer": _DISCLAIMER,
        }

    grouped: dict[tuple, dict[str, Any]] = {}
    filtered_out = 0

    for source in sources:
        matched = next(
            (name for name in values if _match_metric(name, source.limit.metric)), None
        )
        if matched is None:
            continue  # 合同没有约定这个指标，缺失由 checklist 报告

        # 标的品类适配性：合同标的是籼稻谷，就不该拿大米 / 粳稻谷的限值下结论
        if not applies_to_subject(subject, source.limit.applies_to):
            filtered_out += 1
            continue

        # 同一依据条款下数值相同的限值合并（如籼米与晚籼米同为 14.5%）
        key = (
            source.standard_code,
            source.clause_no,
            source.limit.metric,
            source.limit.op,
            source.limit.value,
            source.limit.upper,
        )
        if key in grouped:
            existing = grouped[key]
            if source.limit.applies_to and source.limit.applies_to not in existing["applies_to"]:
                existing["applies_to"].append(source.limit.applies_to)
            continue

        contract_op, contract_value, contract_unit = values[matched]
        status, reason = compare(
            contract_op, contract_value, contract_unit, source.limit, source.rule_strength
        )

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
            "rule_strength": source.rule_strength,
            "basis": _STRENGTH_LABEL.get(source.rule_strength, "依据"),
            "basis_type": source.standard_type,
            "severity": (
                _STRENGTH_SEVERITY.get(source.rule_strength, "medium")
                if status == "violation"
                else None
            ),
            "status": status,
            "reason": reason,
        }

    items = list(grouped.values())
    # 严重程度优先：强制性问题 > 其他偏离 > 待人工核对 > 合规
    order = {"violation": 0, "review": 1, "compliant": 2}
    severity_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(
        key=lambda item: (
            order.get(item["status"], 3),
            severity_order.get(item["severity"] or "low", 3),
        )
    )

    violations = [item for item in items if item["status"] == "violation"]
    mandatory_violations = [item for item in violations if item["severity"] == "high"]
    reviews = [item for item in items if item["status"] == "review"]
    compliant = [item for item in items if item["status"] == "compliant"]

    summary = (
        f"可比对指标 {len(items)} 项：一致 {len(compliant)} 项、"
        f"偏离依据 {len(violations)} 项（其中违反强制性依据 {len(mandatory_violations)} 项）、"
        f"待人工核对 {len(reviews)} 项"
    )
    if subject:
        summary += f"；标的品类「{subject}」"
    if filtered_out:
        summary += f"，已按品类过滤 {filtered_out} 条不适用限值"

    return {
        "total": len(items),
        "compliant_count": len(compliant),
        "violation_count": len(violations),
        "mandatory_violation_count": len(mandatory_violations),
        "review_count": len(reviews),
        "violations": violations,
        "mandatory_violations": mandatory_violations,
        "reviews": reviews,
        "items": items,
        "timeliness": timeliness,
        "subject_category": subject,
        "filtered_out_count": filtered_out,
        "summary": summary,
        "disclaimer": _DISCLAIMER,
    }
