"""必备条款覆盖检测的单元测试。"""

from __future__ import annotations

import pytest

from app.modules.contract_parser.schema import Clause, StructuredContract
from app.modules.standard_check import checklist

# 一条把全部必备条款都覆盖到的"理想合同"文本
FULL_TEXT = (
    "本合同标的为优质水稻，数量180吨，种植面积320亩；"
    "质量标准执行GB/T 1354-2018，水分含量不高于14.5%；"
    "合同金额486,000元，甲方验收后15个工作日内支付货款；"
    "任何一方违约应向对方赔偿损失并承担违约金；"
    "因台风、洪水等不可抗力或自然灾害导致无法履行的，双方互不承担责任；"
    "对质量有异议的，应在7日内提出并申请复检；"
    "争议协商不成提交法院诉讼解决；"
    "本合同自双方签字盖章之日起生效。"
)


def _contract(*clauses: tuple[str, str]) -> StructuredContract:
    return StructuredContract(
        title="测试合同",
        clauses=[
            Clause(index=index, title=title, content=content)
            for index, (title, content) in enumerate(clauses, start=1)
        ],
    )


def test_checklist_loads_from_data_file() -> None:
    loaded = checklist.load_checklist()
    required = [rule for rule in loaded.rules if rule.level == "required"]
    recommended = [rule for rule in loaded.rules if rule.level == "recommended"]

    assert len(required) == 9
    assert len(recommended) == 5

    keys = {rule.key for rule in loaded.rules}
    assert {"force_majeure", "quality_objection", "price_adjustment"} <= keys


def test_missing_required_clauses_are_reported() -> None:
    """缺了不可抗力与质量异议期，必须被点出来——这正是这份样例合同的真实缺陷。"""
    contract = _contract(
        ("订单标的", "乙方按甲方要求种植水稻，种植面积320亩。"),
        ("质量标准", "质量标准执行GB/T 1354-2018，水分含量不高于14.5%。"),
        ("违约责任", "任何一方违约，应支付合同总金额10%的违约金。"),
    )

    report = checklist.check_coverage(contract)
    missing = {item["key"] for item in report["missing_required"]}

    assert "force_majeure" in missing
    assert "quality_objection" in missing
    # 已经写了的不能误报为缺失
    assert "quality_standard" not in missing
    assert "breach_liability" not in missing


def test_covered_item_carries_evidence() -> None:
    """覆盖判定必须给出条款序号、命中关键词与原文片段，否则无法复核。"""
    contract = _contract(("免责条款", "发生台风、洪水等不可抗力时，双方互不承担违约责任。"))

    report = checklist.check_coverage(contract)
    item = next(i for i in report["items"] if i["key"] == "force_majeure")

    assert item["status"] == "covered"
    assert item["clause_index"] == 1
    assert item["matched_keyword"] in {"不可抗力", "台风", "洪水"}
    assert item["evidence"]
    assert item["advice"] == ""


def test_missing_item_carries_advice() -> None:
    report = checklist.check_coverage(_contract(("标的", "水稻180吨。")))
    item = next(i for i in report["items"] if i["key"] == "force_majeure")

    assert item["status"] == "missing"
    assert item["clause_index"] is None
    assert item["advice"]


def test_full_text_covers_every_required_clause() -> None:
    report = checklist.check_coverage(_contract(("全部条款", FULL_TEXT)))

    assert report["required_covered"] == report["required_total"]
    assert report["missing_required"] == []
    assert report["risk_level"] in {"低风险", "中风险"}


def test_empty_contract_scores_zero() -> None:
    report = checklist.check_coverage(_contract())

    assert report["required_covered"] == 0
    assert report["risk_score"] == 0
    assert report["risk_level"] == "高风险"
    assert len(report["missing_required"]) == report["required_total"]


@pytest.mark.parametrize(
    ("score", "expected"),
    [(100, "低风险"), (80, "低风险"), (79, "中风险"), (55, "中风险"), (54, "高风险"), (0, "高风险")],
)
def test_risk_level_thresholds(score: int, expected: str) -> None:
    assert checklist._risk_level(score, {}) == expected


def test_risk_score_is_between_0_and_100() -> None:
    report = checklist.check_coverage(_contract(("标的", "水稻180吨，金额100元。")))
    assert 0 <= report["risk_score"] <= 100
