"""结构化事实抽取的单元测试。

验收口径比「字段命中率 8/8」严格一个量级：
不判断"抽到了没有"，而是断言**数值精确相等**——
因为下游的合规比对要直接拿这些数值算，差一点都是错的。
"""

from __future__ import annotations

import pytest

from app.modules.contract_parser.facts import (
    cn_to_number,
    extract_facts,
    parse_date,
    parse_money,
)

SAMPLE = """订单农业合同

合同编号：DDNY-2026-0918

甲方（收购方）：明光市丰谷粮油有限公司
统一社会信用代码：91341182612345678X

乙方（种植方）：明光市绿野家庭农场
统一社会信用代码：91341182687654321Y

第一条 订单标的
乙方按甲方订单要求种植优质水稻品种南粳46，种植面积320亩，甲方提供种子及技术指导。

第二条 数量与金额
甲方收购乙方全部符合质量标准的稻谷，预计收购量180吨，合同总金额人民币486,000元。

第三条 质量标准
质量标准执行GB/T 1354-2018大米国家标准，水分含量不高于14.5%，杂质含量不高于1.0%，
整精米率不低于55%。

第四条 交货期限
交货时间为2026年11月1日至2026年11月30日，乙方负责将货物运送至甲方指定仓库，
运输费用由甲方承担。

第五条 付款方式
甲方在收到货物并验收合格后15个工作日内，通过银行转账方式支付货款。

第六条 违约责任
任何一方违约，应向对方支付合同总金额10%的违约金；因乙方原因导致质量标准不达标的，
甲方有权拒收并要求赔偿实际损失。

第七条 争议解决
因本合同发生的争议，双方应友好协商解决；协商不成的，提交明光市人民法院诉讼解决。

第八条 生效日期
本合同自双方签字盖章之日起生效，签订日期：2026年9月18日。
"""


# ============================================================
#  中文数字
# ============================================================


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("肆拾捌万陆仟", 486000),
        ("贰拾万", 200000),
        ("二十", 20),
        ("十五", 15),
        ("一百零五", 105),
        ("叁仟贰佰", 3200),
    ],
)
def test_cn_to_number(text: str, expected: float) -> None:
    assert cn_to_number(text) == expected


def test_cn_to_number_returns_none_for_non_number() -> None:
    assert cn_to_number("合同") is None
    assert cn_to_number("") is None


# ============================================================
#  金额
# ============================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("合同总金额人民币486,000元", 486000.0),
        ("48.6万元", 486000.0),
        ("人民币贰拾万元整", 200000.0),
    ],
)
def test_parse_money(raw: str, expected: float) -> None:
    assert parse_money(raw).value == expected


def test_missing_amount_stays_none() -> None:
    """抽不到就是空——绝不用 0 代替，「没写」与「写了 0」是两回事。"""
    facts = extract_facts("本合同未约定金额，双方另行协商。")
    assert facts.amount.value is None


# ============================================================
#  日期
# ============================================================


def test_parse_date_absolute() -> None:
    result = parse_date("签订日期：2026年9月18日")
    assert result.kind == "absolute"
    assert result.start == "2026-09-18"


def test_parse_date_range() -> None:
    result = parse_date("交货时间为2026年11月1日至2026年11月30日")
    assert result.kind == "range"
    assert (result.start, result.end) == ("2026-11-01", "2026-11-30")


def test_relative_effective_date_not_swallowed_by_trailing_date() -> None:
    """相对生效日期不能被同句尾部的签订日期吞掉。

    「自签字盖章之日起」本身是风险信号（生效时点取决于实际签署），
    若被判成 absolute 就丢失了这个信息。
    """
    result = parse_date("本合同自双方签字盖章之日起生效，签订日期：2026年9月18日")
    assert result.kind == "relative"
    assert result.expr == "双方签字盖章之日起"


# ============================================================
#  端到端：示例合同
# ============================================================


def test_extract_facts_from_sample_contract() -> None:
    facts = extract_facts(SAMPLE)

    assert facts.amount.value == 486000.0
    assert facts.amount.currency == "CNY"

    assert facts.sign_date.kind == "absolute"
    assert facts.sign_date.start == "2026-09-18"

    assert facts.effective_date.kind == "relative"
    assert facts.effective_date.expr == "双方签字盖章之日起"

    assert facts.delivery.kind == "range"
    assert (facts.delivery.start, facts.delivery.end) == ("2026-11-01", "2026-11-30")

    assert facts.quantity.value == 180.0
    assert facts.quantity.unit == "吨"

    assert facts.planted_area.value == 320.0
    assert facts.planted_area.unit == "亩"

    assert facts.penalty.rate == 0.10
    assert facts.penalty.base == "合同总金额"

    assert facts.payment_days == 15
    assert facts.payment_trigger == "验收合格后"

    # 合同未载明单价与定金，应保持空缺
    assert facts.unit_price.value is None
    assert facts.deposit.rate is None


def test_sample_quality_metrics() -> None:
    facts = extract_facts(SAMPLE)
    extracted = {(m.name, m.op, m.value, m.unit) for m in facts.quality_metrics}

    assert extracted == {
        ("水分", "<=", 14.5, "%"),
        ("杂质", "<=", 1.0, "%"),
        ("整精米率", ">=", 55.0, "%"),
    }

    water = facts.metric("水分")
    assert water is not None
    assert water.op == "<="
    assert water.value == 14.5


def test_penalty_percent_is_not_a_quality_metric() -> None:
    """违约金比例不能被误当成质量指标——否则会得出错误的合规结论。"""
    facts = extract_facts(
        "任何一方违约，应向对方支付合同总金额10%的违约金；"
        "质量标准执行GB/T 1354-2018，水分含量不高于14.5%。"
    )
    assert facts.penalty.rate == 0.10
    assert [m.name for m in facts.quality_metrics] == ["水分"]


def test_empty_text_yields_empty_facts() -> None:
    facts = extract_facts("")
    assert facts.amount.value is None
    assert facts.quality_metrics == []
    assert facts.evidences == {}


def test_evidences_are_recorded() -> None:
    """结构化值同样要能回溯原文——这是「可信」的底线。"""
    facts = extract_facts(SAMPLE)
    for key in ("amount", "sign_date", "delivery", "penalty", "payment_days"):
        assert facts.evidences.get(key), f"缺少 {key} 的原文依据"

    assert "486,000元" in facts.evidences["amount"]
