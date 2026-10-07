"""履约模拟模块的单元测试。

核心断言：数值计算精确相等（不是"大概对"），
规则引用必须来自真实规则库，mock LLM 降级不炸链路。
"""

from __future__ import annotations

from app.modules.contract_parser.schema import (
    ContractFacts,
    DateValue,
    Money,
    Quantity,
    Ratio,
    StructuredContract,
)
from app.modules.simulation import calculator, rulebook, service

# 与示例合同一致的 facts
FACTS = ContractFacts(
    amount=Money(value=486000.0, currency="CNY", raw="486,000元"),
    quantity=Quantity(name="稻谷", op="=", value=180.0, unit="吨", raw="180吨"),
    penalty=Ratio(rate=0.10, base="合同总金额", kind="ratio", raw="10%"),
    sign_date=DateValue(kind="absolute", start="2026-09-18", raw="2026年9月18日"),
)


def _contract(facts: ContractFacts | None = None) -> StructuredContract:
    return StructuredContract(
        title="测试合同",
        facts=facts if facts is not None else FACTS,
    )


# ---------------- 数值计算：价格波动 ----------------


def test_price_up_breeds_seller_incentive() -> None:
    result = calculator.simulate_price_fluctuation(FACTS, price_change_pct=20.0)
    assert result["computable"]
    assert result["market_value"] == 583200.0  # 486000 × 1.2
    assert result["deviation"] == 97200.0
    assert "供应方" in result["breach_incentive_party"]
    assert result["breach_incentive_value"] == 97200.0
    assert len(result["calc_steps"]) == 4


def test_price_down_breeds_buyer_incentive() -> None:
    result = calculator.simulate_price_fluctuation(FACTS, price_change_pct=-15.0)
    assert result["market_value"] == 413100.0  # 486000 × 0.85
    assert result["deviation"] == -72900.0
    assert "收购方" in result["breach_incentive_party"]
    assert result["breach_incentive_value"] == 72900.0


def test_price_missing_amount_not_computable() -> None:
    result = calculator.simulate_price_fluctuation(ContractFacts(), price_change_pct=10.0)
    assert not result["computable"]
    assert "金额" in result["reason"]


# ---------------- 数值计算：自然灾害 ----------------


def test_disaster_loss_calculation() -> None:
    result = calculator.simulate_natural_disaster(FACTS, loss_ratio_pct=30.0)
    assert result["computable"]
    assert result["deliverable_quantity"] == 126.0  # 180 × 0.7
    assert result["shortfall_quantity"] == 54.0
    assert result["loss_amount"] == 145800.0  # 486000 × 0.3
    assert "不可抗力" in result["summary"] or "民法典" in result["summary"]


def test_disaster_ratio_is_clamped() -> None:
    result = calculator.simulate_natural_disaster(FACTS, loss_ratio_pct=150.0)
    assert result["computable"]
    assert result["deliverable_quantity"] == 0.0  # 超界按 100% 截断
    assert result["loss_amount"] == 486000.0


def test_disaster_missing_all_not_computable() -> None:
    result = calculator.simulate_natural_disaster(ContractFacts(), loss_ratio_pct=30.0)
    assert not result["computable"]


# ---------------- 数值计算：一方违约 ----------------


def test_breach_penalty_ratio() -> None:
    result = calculator.simulate_party_breach(FACTS)
    assert result["computable"]
    assert result["penalty_value"] == 48600.0  # 486000 × 10%
    assert result["penalty_rate"] == 0.10
    assert "五万八千" not in result["summary"]  # 确保是数字不是大写
    assert "五百八十五条" in result["legal_note"]


def test_breach_fixed_penalty() -> None:
    facts = ContractFacts(
        penalty=Ratio(rate=50000.0, kind="fixed", raw="5万元")
    )
    result = calculator.simulate_party_breach(facts)
    assert result["computable"]
    assert result["penalty_value"] == 50000.0


def test_breach_missing_penalty_not_computable() -> None:
    result = calculator.simulate_party_breach(ContractFacts())
    assert not result["computable"]
    assert "违约金" in result["reason"]


def test_breach_ratio_without_amount_not_computable() -> None:
    facts = ContractFacts(
        penalty=Ratio(rate=0.10, base="合同总金额", kind="ratio", raw="10%")
    )
    result = calculator.simulate_party_breach(facts)
    assert not result["computable"]
    assert "金额缺失" in result["reason"]


# ---------------- 规则库检索 ----------------


def test_rulebook_loads_real_data() -> None:
    rules = rulebook.load_rules()
    assert len(rules) >= 150, "规则库应加载 194 条左右"
    scenarios = {r["scenario"] for r in rules}
    assert {"价格波动", "自然灾害", "拖欠款项"} <= scenarios
    # 每条都有案号与法院（可追溯性）
    assert all(r["case_no"] for r in rules)
    assert all(r["court"] for r in rules)


def test_rulebook_cite_for_price_scenario() -> None:
    cited = rulebook.cite_rules("price_fluctuation", keywords=["保底价", "随行就市"])
    assert cited["total"] >= 1
    assert all(c["case_no"] for c in cited["citations"])
    assert all(c["ruling"] for c in cited["citations"])


def test_rulebook_cite_unknown_scenario_returns_empty_scenarios() -> None:
    cited = rulebook.cite_rules("party_breach")
    assert set(cited["matched_scenarios"]) == {
        "拖欠款项", "擅自处分", "主体不适格", "合同解除",
    }


def test_rulebook_search_no_duplicate_case() -> None:
    hits = rulebook.search_rules("拖欠款项", limit=3)
    case_nos = [h["case_no"] for h in hits]
    assert len(case_nos) == len(set(case_nos))


# ---------------- 服务编排（mock LLM 降级） ----------------


class _MockLLM:
    name = "mock"
    model = "mock-llm"

    def complete(self, prompt, system=None):
        from app.core.providers.base import LLMResult

        return LLMResult(content="mock", provider="mock", model="mock-llm")


def test_service_full_simulation(monkeypatch) -> None:
    contract = _contract()
    monkeypatch.setattr(service.contract_service, "get_contract", lambda doc_id: contract)

    report = service.simulate(
        "test-doc",
        scenarios=None,  # 全部三情景
        params={"price_fluctuation": {"price_change_pct": 10.0}},
        llm=_MockLLM(),
    )
    assert report is not None
    assert len(report.scenarios) == 3
    by_key = {s.scenario: s for s in report.scenarios}

    price = by_key["price_fluctuation"]
    assert price.computable
    assert price.params["deviation"] == 48600.0
    assert price.analysis_provider == "mock"
    assert "模板分析" in price.analysis

    breach = by_key["party_breach"]
    assert breach.computable
    assert breach.params["penalty_value"] == 48600.0
    assert breach.legal_note

    disaster = by_key["natural_disaster"]
    assert disaster.computable
    assert disaster.params["loss_ratio_pct"] == 0.0  # 未传参数时默认无减产
    assert disaster.params["loss_amount"] == 0.0

    # 引用判例：至少一个情景带上了真实案号
    assert any(s.citations for s in report.scenarios)


def test_service_unknown_scenario_raises(monkeypatch) -> None:
    contract = _contract()
    monkeypatch.setattr(service.contract_service, "get_contract", lambda doc_id: contract)
    try:
        service.simulate("test-doc", scenarios=["alien_invasion"], llm=_MockLLM())
        raise AssertionError("应当抛 ValueError")
    except ValueError as exc:
        assert "未知的模拟情景" in str(exc)


def test_service_missing_contract_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(service.contract_service, "get_contract", lambda doc_id: None)
    assert service.simulate("no-such-doc", llm=_MockLLM()) is None
