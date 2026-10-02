"""合同值与标准限值数值比对的单元测试。"""

from __future__ import annotations

import pytest

from app.modules.contract_parser.facts import extract_facts
from app.modules.contract_parser.schema import StructuredContract
from app.modules.standard_check import compliance

SAMPLE_TEXT = """
质量标准执行GB/T 1354-2018大米国家标准，水分含量不高于14.5%，杂质含量不高于1.0%，
整精米率不低于55%。
任何一方违约，应向对方支付合同总金额10%的违约金。
"""


def _contract(text: str = SAMPLE_TEXT) -> StructuredContract:
    return StructuredContract(title="测试合同", facts=extract_facts(text))


def _find(report: dict, clause_no: str, applies_to: str | None = None) -> dict:
    for item in report["items"]:
        if item["clause_no"] != clause_no:
            continue
        if applies_to and applies_to not in item["applies_to"]:
            continue
        return item
    raise AssertionError(f"未找到条款 {clause_no}（适用范围 {applies_to}）")


# ============================================================
#  比对单元
# ============================================================


def test_same_direction_smaller_limit_is_compliant() -> None:
    limit = compliance.Limit(metric="水分", op="<=", value=14.5, unit="%")
    assert compliance.compare("<=", 14.0, "%", limit)[0] == "compliant"
    assert compliance.compare("<=", 14.5, "%", limit)[0] == "compliant"


def test_contract_looser_than_standard_is_violation() -> None:
    limit = compliance.Limit(metric="杂质", op="<=", value=0.25, unit="%")
    status, reason = compliance.compare("<=", 1.0, "%", limit)
    assert status == "violation"
    assert "宽于" in reason


def test_lower_bound_violation() -> None:
    limit = compliance.Limit(metric="整精米率", op=">=", value=60.0, unit="%")
    assert compliance.compare(">=", 55.0, "%", limit)[0] == "violation"
    assert compliance.compare(">=", 62.0, "%", limit)[0] == "compliant"


def test_opposite_direction_needs_review() -> None:
    """方向冲突时不能硬给结论，必须暴露给人看。"""
    limit = compliance.Limit(metric="整精米率", op=">=", value=50.0, unit="%")
    status, reason = compliance.compare("<=", 55.0, "%", limit)
    assert status == "review"
    assert "方向" in reason


def test_unit_mismatch_needs_review() -> None:
    limit = compliance.Limit(metric="镉", op="<=", value=0.2, unit="mg/kg")
    status, reason = compliance.compare("<=", 0.1, "%", limit)
    assert status == "review"
    assert "单位" in reason


def test_range_limit() -> None:
    limit = compliance.Limit(
        metric="直链淀粉含量", op="range", value=13.0, upper=18.0, unit="%"
    )
    assert compliance.compare("=", 15.0, "%", limit)[0] == "compliant"
    assert compliance.compare("=", 20.0, "%", limit)[0] == "violation"
    # 合同是单边约定时，区间要求无法直接判定
    assert compliance.compare("<=", 18.0, "%", limit)[0] == "review"


@pytest.mark.parametrize(
    ("contract_metric", "limit_metric", "expected"),
    [
        ("水分", "水分", True),
        ("碎米", "碎米总量", True),
        ("碎米总量", "碎米", True),
        ("水", "水分", False),  # 单字不参与包含匹配，否则会命中一切
        ("杂质", "镉", False),
    ],
)
def test_metric_name_matching(contract_metric: str, limit_metric: str, expected: bool) -> None:
    assert compliance._match_metric(contract_metric, limit_metric) is expected


# ============================================================
#  端到端
# ============================================================


def test_limits_are_loaded_from_standard_library() -> None:
    limits = compliance.load_limits()
    assert len(limits) > 10

    metrics = {source.limit.metric for source in limits}
    assert {"水分", "杂质", "整精米率", "违约金比例"} <= metrics


def test_sample_contract_compliance() -> None:
    report = compliance.check_compliance(_contract())

    # 水分 14.5%：符合大米（籼米）限值，但宽于优质籼稻谷的 13.5%
    assert _find(report, "5.2", "籼米")["status"] == "compliant"
    assert _find(report, "4.7", "籼稻谷")["status"] == "violation"

    # 杂质 1.0% 明显宽于 GB/T 1354 的 0.25%
    assert _find(report, "5.3", "大米")["status"] == "violation"

    # 整精米率 55%：达到优质籼稻谷（≥50%），未达优质粳稻谷（≥60%）
    assert _find(report, "4.3", "优质籼稻谷")["status"] == "compliant"
    assert _find(report, "4.3", "优质粳稻谷")["status"] == "violation"

    # 违约金 10% 未超过示范条款的 30% 上限
    assert _find(report, "示范3.5")["status"] == "compliant"

    assert report["violation_count"] == len(report["violations"])
    assert report["violation_count"] > 0


def test_violation_item_carries_source_and_reason() -> None:
    """违规结论必须能指回具体标准条款，否则不可复核。"""
    report = compliance.check_compliance(_contract())
    item = report["violations"][0]

    assert item["standard_code"]
    assert item["clause_no"]
    assert item["contract_value"] is not None
    assert item["standard_value"] is not None
    assert item["reason"]


def test_contract_without_quantified_values() -> None:
    report = compliance.check_compliance(_contract("本合同未约定任何量化指标。"))
    assert report["total"] == 0
    assert report["items"] == []


def test_penalty_rate_converted_to_percentage() -> None:
    """facts 里存的是小数 0.10，标准里写的是 30%，换算必须正确。"""
    contract = _contract("任何一方违约，应支付合同总金额10%的违约金。")
    item = _find(compliance.check_compliance(contract), "示范3.5")
    assert item["contract_value"] == pytest.approx(10.0)
    assert item["status"] == "compliant"
