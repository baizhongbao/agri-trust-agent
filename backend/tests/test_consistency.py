"""事实确定性自检（consistency.py）与计算一致性校验的结构化原因码。

两条契约：
1. **不适用的规则不产生条目**——"没检查"与"检查通过"必须能区分；
2. 校验没通过必须留下**机器可读的原因码**，而不是只躺在中文里。
   原来 `calculator` 里 `consistent` 这个布尔值算完就丢，正是反例。
"""

from __future__ import annotations

from app.modules.contract_parser import consistency
from app.modules.contract_parser.schema import (
    ContractFacts,
    DateValue,
    Money,
    Quantity,
    Ratio,
)
from app.modules.simulation import calculator


def _codes(checks) -> list[str]:
    return [c.code for c in checks]


def _status(checks, code: str) -> str:
    return next(c.status for c in checks if c.code == code)


# ---------------- 日期先后 ----------------


def test_delivery_before_sign_date_is_flagged() -> None:
    facts = ContractFacts(
        sign_date=DateValue(kind="absolute", start="2026-09-18"),
        delivery=DateValue(kind="absolute", start="2026-08-01"),
    )
    checks = consistency.check_dates(facts)
    assert _status(checks, "delivery_before_sign_date") == "warning"
    assert "早于签订日期" in next(
        c.detail for c in checks if c.code == "delivery_before_sign_date"
    )


def test_effective_before_sign_date_is_flagged() -> None:
    facts = ContractFacts(
        sign_date=DateValue(kind="absolute", start="2026-09-18"),
        effective_date=DateValue(kind="absolute", start="2026-01-01"),
    )
    checks = consistency.check_dates(facts)
    assert _status(checks, "effective_date_before_sign_date") == "warning"


def test_correct_date_order_passes_with_reason_code() -> None:
    facts = ContractFacts(
        sign_date=DateValue(kind="absolute", start="2026-09-18"),
        effective_date=DateValue(kind="absolute", start="2026-09-20"),
        delivery=DateValue(kind="absolute", start="2026-11-01"),
    )
    checks = consistency.check_dates(facts)
    assert checks  # 规则适用 → 必须留下"检查通过"的痕迹
    assert {c.status for c in checks} == {"ok"}


def test_relative_dates_produce_no_checks() -> None:
    """「自双方签字盖章之日起生效」是合同的真实形态，不是抽取失败，无从比较先后。"""
    facts = ContractFacts(
        sign_date=DateValue(kind="absolute", start="2026-09-18"),
        effective_date=DateValue(kind="relative", expr="双方签字盖章之日起"),
        delivery=DateValue(kind="range", start="2026-11-01", end="2026-11-30"),
    )
    assert consistency.check_dates(facts) == []


def test_no_sign_date_means_no_date_checks() -> None:
    """没有签订日期这个基准，任何先后判断都无从谈起——不是给 pass，是不产生条目。"""
    facts = ContractFacts(delivery=DateValue(kind="absolute", start="2026-08-01"))
    assert consistency.check_dates(facts) == []


# ---------------- 定金 / 违约金 ----------------


def test_deposit_over_20_percent_is_flagged_with_legal_basis() -> None:
    facts = ContractFacts(deposit=Ratio(rate=0.30, base="定金", kind="ratio"))
    (check,) = consistency.check_deposit(facts)
    assert check.code == "deposit_ratio_over_20_percent"
    assert check.status == "warning"
    assert "第五百八十六条" in check.legal_basis


def test_deposit_within_limit_passes() -> None:
    facts = ContractFacts(deposit=Ratio(rate=0.10, base="定金", kind="ratio"))
    (check,) = consistency.check_deposit(facts)
    assert check.code == "deposit_ratio_within_limit"
    assert check.status == "ok"


def test_absent_deposit_produces_no_check() -> None:
    assert consistency.check_deposit(ContractFacts()) == []


def test_high_penalty_is_review_not_violation() -> None:
    """违约金是否"过分高于损失"取决于**实际损失**，合同里没有，系统不能宣称违规。"""
    facts = ContractFacts(penalty=Ratio(rate=0.50, base="合同总金额", kind="ratio"))
    (check,) = consistency.check_penalty(facts)
    assert check.code == "penalty_ratio_requires_review"
    assert check.status == "review"  # 不是 warning
    assert "实际损失不在合同内" in check.detail
    assert "第五百八十五条" in check.legal_basis


def test_per_day_penalty_not_judged_by_ratio() -> None:
    """按日计的违约金与"合同总额的百分之几"不可比，不该套用比例参考线。"""
    facts = ContractFacts(penalty=Ratio(rate=0.50, base="未履行部分", kind="per_day"))
    assert consistency.check_penalty(facts) == []


def test_problems_filters_out_ok() -> None:
    facts = ContractFacts(
        deposit=Ratio(rate=0.10, base="定金", kind="ratio"),
        penalty=Ratio(rate=0.50, base="合同总金额", kind="ratio"),
    )
    problems = consistency.problems(consistency.check_facts(facts))
    assert [p.code for p in problems] == ["penalty_ratio_requires_review"]


def test_check_facts_on_empty_facts_is_empty() -> None:
    assert consistency.check_facts(ContractFacts()) == []


# ---------------- 计算一致性校验：布尔值 → 原因码 ----------------


def test_calculator_flags_amount_unit_price_mismatch() -> None:
    """数量×单价 = 500 而合同总额 = 1000 → 至少有一项抽错，必须留下原因码。

    原来这个判断只被拼进一句中文，`consistent` 布尔值算完即丢，
    既不进 verdict、也不触发复核。
    """
    facts = ContractFacts(
        amount=Money(value=1000.0),
        unit_price=Money(value=10.0),
        quantity=Quantity(name="收购量", op="=", value=50.0, unit="吨"),
    )
    result = calculator.simulate_price_fluctuation(facts, price_change_pct=0.0)

    assert result["computable"]
    (check,) = result["checks"]
    assert check["code"] == "amount_unit_price_quantity_mismatch"
    assert check["status"] == "warning"
    assert check["expected"] == 500.0
    assert check["actual"] == 1000.0
    assert check["deviation_pct"] == 50.0
    # 数值仍按更可信的一侧（合同总额）计算，不因校验失败而拒算
    assert result["contract_amount"] == 1000.0


def test_calculator_passes_when_amount_is_consistent() -> None:
    facts = ContractFacts(
        amount=Money(value=500.0),
        unit_price=Money(value=10.0),
        quantity=Quantity(name="收购量", op="=", value=50.0, unit="吨"),
    )
    result = calculator.simulate_price_fluctuation(facts, price_change_pct=0.0)
    (check,) = result["checks"]
    assert check["code"] == "amount_consistency"
    assert check["status"] == "ok"


def test_calculator_skips_check_when_nothing_to_cross_check() -> None:
    """缺单价或数量时无从交叉比对——不产生条目，也不假装通过。"""
    facts = ContractFacts(
        amount=Money(value=500.0),
        quantity=Quantity(name="收购量", op="=", value=50.0, unit="吨"),
    )
    result = calculator.simulate_price_fluctuation(facts, price_change_pct=0.0)
    assert result["checks"] == []


def test_calculator_derived_amount_has_no_consistency_check() -> None:
    """总额本来就是单价×数量推出来的，再拿它俩互校是同义反复。"""
    facts = ContractFacts(
        unit_price=Money(value=10.0),
        quantity=Quantity(name="收购量", op="=", value=50.0, unit="吨"),
    )
    result = calculator.simulate_price_fluctuation(facts, price_change_pct=0.0)
    assert result["contract_amount"] == 500.0
    assert result["checks"] == []
