"""企业核验模块的单元测试（L2 fixture / L3 交叉校验 / 服务编排）。

约定：测试全部使用 FixtureEnterpriseProvider 显式注入，
不经过 registry——避免 .env 里配置了 qcc 时测试打到真实接口。
"""

from __future__ import annotations

from app.core.providers.base import RegistrationInfo
from app.core.providers.enterprise import FixtureEnterpriseProvider
from app.modules.contract_parser.schema import ContractFacts, DateValue, Party
from app.modules.enterprise_verify import cross_check, service
from app.modules.enterprise_verify.schema import combine_status

PROVIDER = FixtureEnterpriseProvider()

PARTY_A = Party(
    role="甲方（收购方）",
    name="明光市丰谷粮油有限公司",
    credit_code="913411826123456782",
)
PARTY_B = Party(
    role="乙方（种植方）",
    name="明光市绿野家庭农场",
    credit_code="91341182687654321U",
)


def _facts_with_sign_date(date: str) -> ContractFacts:
    return ContractFacts(sign_date=DateValue(kind="absolute", start=date, raw=date))


def _reg(**overrides) -> RegistrationInfo:
    base = dict(
        name="明光市丰谷粮油有限公司",
        credit_code="913411826123456782",
        founding_date="2015-06-18",
        status="存续",
        business_scope="粮食收购、销售；农产品初加工",
    )
    base.update(overrides)
    return RegistrationInfo(**base)


# ---------------- L2 fixture ----------------


def test_fixture_lookup_by_code() -> None:
    result = PROVIDER.lookup("913411826123456782")
    assert result.found
    assert result.registration is not None
    assert result.registration.name == "明光市丰谷粮油有限公司"
    assert result.registration.status == "存续"


def test_fixture_lookup_by_name() -> None:
    result = PROVIDER.lookup("明光市金穗米业有限公司")
    assert result.found
    assert result.registration is not None
    assert result.registration.status == "注销"


def test_fixture_lookup_unknown_returns_not_found() -> None:
    result = PROVIDER.lookup("不存在的公司")
    assert not result.found
    assert "fixture" in result.note


def test_fixture_all_codes_have_valid_checksum() -> None:
    """演示纪律：fixture 里每条信用代码都必须能通过 GB 32100 校验位验算。"""
    from app.modules.enterprise_verify.credit_code import validate_checksum

    for name, code in (
        ("明光市丰谷粮油有限公司", "913411826123456782"),
        ("明光市绿野家庭农场", "91341182687654321U"),
        ("明光市恒昌商贸有限公司", "91341182MA2T7QKX9E"),
        ("明光市金穗米业有限公司", "91341182MA2W7L9XKW"),
    ):
        assert validate_checksum(code), name


# ---------------- L3 交叉校验 ----------------


def test_l3_all_pass_for_normal_party() -> None:
    items = {item.key: item for item in cross_check.run_l3_checks(PARTY_A, _reg(), _facts_with_sign_date("2026-09-18"))}
    assert items["name_match"].status == "pass"
    assert items["code_match"].status == "pass"
    assert items["founding_vs_sign"].status == "pass"
    assert items["registration_status"].status == "pass"
    assert items["scope_match"].status == "pass"


def test_l3_founding_after_sign_date_fails() -> None:
    items = cross_check.run_l3_checks(
        PARTY_A, _reg(founding_date="2026-10-01"), _facts_with_sign_date("2026-09-18")
    )
    check = next(item for item in items if item.key == "founding_vs_sign")
    assert check.status == "fail"
    assert "尚不存在" in check.detail


def test_l3_cancelled_status_fails() -> None:
    items = {item.key: item for item in cross_check.run_l3_checks(
        PARTY_A, _reg(status="注销"), _facts_with_sign_date("2026-09-18")
    )}
    assert items["registration_status"].status == "fail"
    assert "履约能力" in items["registration_status"].detail


def test_l3_name_mismatch_fails() -> None:
    items = {item.key: item for item in cross_check.run_l3_checks(
        Party(role="甲方", name="李鬼贸易有限公司", credit_code="913411826123456782"),
        _reg(),
        _facts_with_sign_date("2026-09-18"),
    )}
    assert items["name_match"].status == "fail"


def test_l3_scope_without_purchase_warns() -> None:
    items = {item.key: item for item in cross_check.run_l3_checks(
        PARTY_A, _reg(business_scope="服装鞋帽、日用百货销售"), _facts_with_sign_date("2026-09-18")
    )}
    assert items["scope_match"].status == "warning"


def test_l3_relative_sign_date_skips_date_check() -> None:
    facts = ContractFacts(
        sign_date=DateValue(kind="relative", expr="双方签字盖章之日起")
    )
    items = {item.key: item for item in cross_check.run_l3_checks(PARTY_A, _reg(), facts)}
    assert items["founding_vs_sign"].status == "skip"


def test_l3_chinese_date_is_parsed() -> None:
    items = {item.key: item for item in cross_check.run_l3_checks(
        PARTY_A, _reg(founding_date="2015年6月18日"), _facts_with_sign_date("2026-09-18")
    )}
    assert items["founding_vs_sign"].status == "pass"


def test_role_detection() -> None:
    assert cross_check.detect_role(PARTY_A) == "buyer"
    assert cross_check.detect_role(PARTY_B) == "producer"
    assert cross_check.detect_role(Party(role="甲方", name="某某公司")) == "buyer"
    assert cross_check.detect_role(Party(role="乙方", name="某某公司")) == "producer"
    assert cross_check.detect_role(Party(role="丙方", name="某某机构")) == "unknown"


def test_combine_status_precedence() -> None:
    assert combine_status(["pass", "fail", "warning"]) == "fail"
    assert combine_status(["pass", "warning"]) == "warning"
    assert combine_status(["pass", "review", "warning"]) == "review"
    assert combine_status(["pass", "skip"]) == "pass"
    assert combine_status([]) == "review"


# ---------------- 服务编排 ----------------


def _verify_parties(contract, monkeypatch) -> list:
    monkeypatch.setattr(service.contract_service, "get_contract", lambda doc_id: contract)
    report = service.verify_contract("test-doc", provider=PROVIDER)
    return report.parties


def test_service_overall_pass_for_sample_parties(monkeypatch) -> None:
    from app.modules.contract_parser.schema import StructuredContract

    contract = StructuredContract(
        title="测试合同",
        parties=[PARTY_A, PARTY_B],
        facts=_facts_with_sign_date("2026-09-18"),
    )
    parties = _verify_parties(contract, monkeypatch)
    assert len(parties) == 2
    assert all(p.overall == "pass" for p in parties)
    assert all(p.l2_status == "found" for p in parties)


def test_service_l1_fail_for_fake_code(monkeypatch) -> None:
    from app.modules.contract_parser.schema import StructuredContract

    contract = StructuredContract(
        title="测试合同",
        parties=[Party(role="甲方（收购方）", name="明光市丰谷粮油有限公司", credit_code="91341182612345678X")],
        facts=_facts_with_sign_date("2026-09-18"),
    )
    parties = _verify_parties(contract, monkeypatch)
    assert parties[0].overall == "fail"
    l1 = {item.key: item for item in parties[0].l1}
    assert l1["code_checksum"].status == "fail"


def test_service_l3_fail_for_cancelled_company(monkeypatch) -> None:
    from app.modules.contract_parser.schema import StructuredContract

    contract = StructuredContract(
        title="测试合同",
        parties=[Party(role="甲方（收购方）", name="明光市金穗米业有限公司", credit_code="91341182MA2W7L9XKW")],
        facts=_facts_with_sign_date("2026-09-18"),
    )
    parties = _verify_parties(contract, monkeypatch)
    assert parties[0].overall == "fail"
    l3 = {item.key: item for item in parties[0].l3}
    assert l3["registration_status"].status == "fail"


def test_service_l3_fail_for_late_founding(monkeypatch) -> None:
    from app.modules.contract_parser.schema import StructuredContract

    contract = StructuredContract(
        title="测试合同",
        parties=[Party(role="甲方（收购方）", name="明光市恒昌商贸有限公司", credit_code="91341182MA2T7QKX9E")],
        facts=_facts_with_sign_date("2026-09-18"),
    )
    parties = _verify_parties(contract, monkeypatch)
    l3 = {item.key: item for item in parties[0].l3}
    assert l3["founding_vs_sign"].status == "fail"
    assert l3["scope_match"].status == "warning"


def test_service_unknown_party_reports_not_found(monkeypatch) -> None:
    from app.modules.contract_parser.schema import StructuredContract

    contract = StructuredContract(
        title="测试合同",
        parties=[Party(role="甲方（收购方）", name="火星贸易集团", credit_code="91440300192317458F")],
        facts=_facts_with_sign_date("2026-09-18"),
    )
    parties = _verify_parties(contract, monkeypatch)
    assert parties[0].l2_status == "not_found"
    l3 = {item.key: item for item in parties[0].l3}
    assert l3["l2_lookup"].status == "review"


def test_service_lookup_endpoint_logic() -> None:
    result = service.lookup("明光市绿野家庭农场", provider=PROVIDER)
    assert result["l2_status"] == "found"
    assert result["provider"] == "fixture"
    assert result["l2"]["name"] == "明光市绿野家庭农场"

    result = service.lookup("913411826123456782", provider=PROVIDER)
    assert result["l1"], "18 位代码应触发 L1 校验"
    assert all(item["status"] == "pass" for item in result["l1"])


def test_service_lookup_short_name_skips_l1() -> None:
    result = service.lookup("比亚迪", provider=PROVIDER)
    assert result["l1"] == []
    assert result["l2_status"] == "not_found"
