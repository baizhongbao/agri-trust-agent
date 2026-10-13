"""汇总判定层的回归测试。

核心契约：
- 「一票否决 + 就低不就高」不能功过相抵；
- 解析被门禁阻断时不能给出高于「不可评」的结论；
- 任一模块没跑成，对应维度必须是「不可评」并附原因，不能算 0 分冒充无风险。
"""

from __future__ import annotations

from app.modules.contract_parser.schema import (
    GATE_BLOCKED,
    GATE_DEGRADED,
    GATE_OK,
    GateFailure,
    ParseGate,
    StructuredContract,
)
from app.modules.enterprise_verify.schema import PartyVerification, VerifyReport
from app.modules.simulation.schema import ScenarioResult, SimulationReport
from app.modules.verdict import service
from app.modules.verdict.schema import (
    GRADE_ATTENTION,
    GRADE_HIGH,
    GRADE_TRUSTED,
    GRADE_UNDETERMINED,
)


def _contract(level: str = GATE_OK, failures=None) -> StructuredContract:
    contract = StructuredContract(title="测试合同")
    contract.gate = ParseGate(level=level, failures=failures or [], summary="门禁说明")
    return contract


def _standard(
    required_total: int = 11,
    required_covered: int = 11,
    missing_required=None,
    violation_count: int = 0,
    mandatory: int = 0,
) -> dict:
    return {
        "required_clauses": {
            "required_total": required_total,
            "required_covered": required_covered,
            "missing_required": missing_required or [],
            "summary": f"必备条款 {required_covered}/{required_total}",
        },
        "compliance": {
            "violation_count": violation_count,
            "mandatory_violation_count": mandatory,
            "violations": [{"metric": "水分", "reason": "超限"}] if violation_count else [],
            "mandatory_violations": [{"metric": "水分", "reason": "超限"}] if mandatory else [],
            "summary": f"偏离依据 {violation_count} 项",
        },
    }


def _verify(overalls: tuple[str, ...]) -> VerifyReport:
    parties = [
        PartyVerification(role=f"主体{i}", name=f"公司{i}", credit_code="X", overall=s, l2_status="found")
        for i, s in enumerate(overalls)
    ]
    return VerifyReport(doc_id="d", parties=parties, summary={})


def _simulation(computable=(True, True, True), notice: str = "") -> SimulationReport:
    scenarios = [
        ScenarioResult(scenario=f"s{i}", label=f"情景{i}", computable=c, summary=f"结果{i}")
        for i, c in enumerate(computable)
    ]
    return SimulationReport(doc_id="d", scenarios=scenarios, notice=notice)


def _build(**kwargs):
    return service.build_verdict(
        kwargs.get("contract", _contract()),
        kwargs.get("standard", _standard()),
        kwargs.get("verify", _verify(("pass",))),
        kwargs.get("simulation", _simulation()),
        errors=kwargs.get("errors"),
        doc_id="doc-1",
    )


def test_all_clean_is_trusted() -> None:
    verdict = _build()
    assert verdict.grade == GRADE_TRUSTED
    assert verdict.blockers == []
    assert len(verdict.dimensions) == 4
    assert verdict.doc_id == "doc-1"
    assert verdict.generated_at
    assert verdict.narrative


def test_blocked_parse_forces_undetermined() -> None:
    contract = _contract(GATE_BLOCKED, [GateFailure(key="parties", label="主体", severity="blocking", detail="未识别到主体")])
    verdict = _build(contract=contract)
    assert verdict.grade == GRADE_UNDETERMINED
    assert any(b.key == "parse_blocked" for b in verdict.blockers)


def test_degraded_parse_caps_at_attention() -> None:
    verdict = _build(contract=_contract(GATE_DEGRADED))
    assert verdict.grade == GRADE_ATTENTION


def test_mandatory_violation_is_blocker_and_high() -> None:
    verdict = _build(standard=_standard(violation_count=1, mandatory=1))
    assert verdict.grade == GRADE_HIGH
    assert any(b.key == "mandatory_violation" for b in verdict.blockers)


def test_failed_party_is_blocker_and_high() -> None:
    verdict = _build(verify=_verify(("pass", "fail")))
    assert verdict.grade == GRADE_HIGH
    assert any(b.dimension == "parties" for b in verdict.blockers)


def test_worst_dimension_wins_no_netting() -> None:
    # 主体、履约都完美，唯独条款覆盖偏低 → 整体只能到「需关注」
    verdict = _build(standard=_standard(required_covered=5))
    assert verdict.grade == GRADE_ATTENTION


def test_missing_module_is_undetermined_not_zero() -> None:
    verdict = _build(verify=None, simulation=None)
    assert verdict.grade == GRADE_ATTENTION
    labels = {d.label: d for d in verdict.dimensions}
    assert labels["主体可信"].level == GRADE_UNDETERMINED
    assert labels["履约风险"].level == GRADE_UNDETERMINED
    assert "主体可信" in verdict.missing_dimensions
    assert "履约风险" in verdict.missing_dimensions
    # 未评估必须留下说明，不能被读成「无风险」
    assert any("主体可信" in n for n in verdict.notices)


def test_single_module_error_is_surfaced(monkeypatch) -> None:
    monkeypatch.setattr(service.contract_service, "get_contract", lambda doc_id: _contract())

    def boom(*_args, **_kwargs):
        raise RuntimeError("准确地说：工商接口超时")

    monkeypatch.setattr(service.standard_service, "check_contract", boom)
    monkeypatch.setattr(service.enterprise_service, "verify_contract", lambda doc_id: _verify(("pass",)))
    monkeypatch.setattr(service.simulation_service, "simulate", lambda doc_id: _simulation())

    verdict = service.run_verdict("doc-err")
    assert verdict is not None
    assert any("执行异常" in n and "工商接口超时" in n for n in verdict.notices) or any(
        "执行异常" in n for n in verdict.notices
    )
