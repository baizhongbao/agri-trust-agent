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

    # 标的品类抽到「大米」，据此过滤掉不适用的稻谷限值
    assert report["subject_category"] == "大米"

    # 水分 14.5%：符合籼米 / 粳米限值；籼稻谷 / 粳稻谷限值已按品类过滤
    assert _find(report, "5.2", "籼米")["status"] == "compliant"
    assert _find(report, "5.2", "粳米")["status"] == "compliant"
    assert not any("籼稻谷" in item["applies_to"] for item in report["items"])

    # 杂质 1.0% 明显宽于 GB/T 1354 的 0.25%
    assert _find(report, "5.3", "大米")["status"] == "violation"

    # 整精米率属稻谷标准（GB/T 17891），对大米合同整体过滤
    assert not any(item["metric"] == "整精米率" for item in report["items"])

    # 违约金 10% 未超过示范条款的 30% 上限
    assert _find(report, "示范3.5")["status"] == "compliant"

    assert report["filtered_out_count"] > 0
    assert report["violation_count"] == len(report["violations"])
    assert report["violation_count"] > 0


def test_subject_category_filters_water_to_single_category() -> None:
    """含「籼稻谷」的合同：水分只对籼稻谷（≤13.5%）报偏离，不再出现籼米一致。"""
    report = compliance.check_compliance(_contract("标的为籼稻谷，水分含量不高于14.5%。"))

    assert report["subject_category"] == "籼稻谷"
    water = [item for item in report["items"] if item["metric"] == "水分"]
    assert [item["applies_to"] for item in water] == [["籼稻谷"]]
    assert water[0]["status"] == "violation"


def test_empty_subject_category_keeps_previous_behaviour() -> None:
    """抽不到品类时不启用过滤，结果与改动前一致（向后兼容、不静默改动）。"""
    report = compliance.check_compliance(_contract("水分含量不高于14.5%。"))

    assert report["subject_category"] == ""
    assert report["filtered_out_count"] == 0
    water_scopes = {
        tuple(item["applies_to"]) for item in report["items"] if item["metric"] == "水分"
    }
    # 未过滤时，水分同时列出籼米 / 粳米 / 籼稻谷 / 粳稻谷（旧行为）
    assert ("籼米",) in water_scopes
    assert ("粳稻谷",) in water_scopes


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


# ============================================================
#  规则强度分级（v2.0 新增）
# ============================================================


def test_rule_strength_governs_verdict_wording() -> None:
    """强制性依据不满足才算「违规」；推荐性、指导性只能称「偏离」。"""
    water = compliance.Limit(metric="水分", op="<=", value=14.5, unit="%")
    penalty = compliance.Limit(metric="违约金比例", op="<=", value=30.0, unit="%")

    _, mandatory_reason = compliance.compare("<=", 20.0, "%", water, "mandatory")
    _, recommended_reason = compliance.compare("<=", 20.0, "%", water, "recommended")
    _, advisory_reason = compliance.compare("<=", 40.0, "%", penalty, "advisory")

    assert "违规" in mandatory_reason
    assert "低于推荐标准" in recommended_reason
    assert "偏离建议" in advisory_reason


def test_deposit_limit_is_mandatory_hard_rule() -> None:
    """定金不得超过主合同标的额 20%（民法典 586 条）——这是硬性规定。"""
    contract = _contract("甲方向乙方支付定金，定金为合同总金额的30%。")
    report = compliance.check_compliance(contract)

    item = _find(report, "第五百八十六条")
    assert item["status"] == "violation"
    assert item["severity"] == "high"
    assert item["basis"] == "强制性依据"
    assert item in report["mandatory_violations"]
    assert report["mandatory_violation_count"] >= 1


def test_penalty_rule_is_advisory_not_hard() -> None:
    """示范文本的 30% 是指导性建议，超出也不应算「违规」性质的问题。"""
    contract = _contract("任何一方违约，应支付合同总金额50%的违约金。")
    item = _find(compliance.check_compliance(contract), "示范3.5")

    assert item["status"] == "violation"
    assert item["basis"] == "指导性文件"
    assert item["severity"] == "low"


# ============================================================
#  时效性（v2.0 新增）
# ============================================================


def test_timeliness_notice_when_contract_predates_standard() -> None:
    """2025 年签订的合同用 2026 年才生效的依据比对，必须提示版本可能不适配。"""
    contract = _contract("签订日期：2025年6月1日。水分含量不高于14.0%。")
    report = compliance.check_compliance(contract)

    codes = {notice["standard_code"] for notice in report["timeliness"]}
    assert "GB 2763-2026" in codes
    assert "订单农业合同规范指引" in codes

    notice = next(n for n in report["timeliness"] if n["standard_code"] == "GB 2763-2026")
    assert notice["effective_date"] == "2026-03-01"
    assert notice["contract_sign_date"] == "2025-06-01"


def test_no_timeliness_notice_for_current_contract() -> None:
    """签订日期晚于依据生效日时不应产生时效提示。"""
    contract = _contract("签订日期：2026年9月18日。水分含量不高于14.0%。")
    assert compliance.check_compliance(contract)["timeliness"] == []
