"""解析质量门禁（L1→L2 升级 + L4 硬失败）的单元测试。

事故背景（回归目标）：扫描件 `1000178611.jpg` 解析后 `parties` 为空，
系统既不报错也不产生 warning，下游企业核验静默跳过、返回 summary 全 0 的
"正常"报告。本文件的用例锁死这条链路必须显式失败。

约定：不经过 registry、不调真实 API —— 升级目标 LLMStructurer 被打桩，
避免 .env 里配了 pangu 时测试打到真实接口。
"""

from __future__ import annotations

import pytest

from app.core.providers.base import ProviderNotReadyError
from app.modules.contract_parser import gate, service
from app.modules.contract_parser.pdf_reader import PdfText
from app.modules.contract_parser.schema import (
    ARB_AGREED,
    ARB_CONFLICT,
    ARB_MISSING,
    ARB_SINGLE,
    GATE_BLOCKED,
    GATE_DEGRADED,
    GATE_OK,
    ContractField,
    FieldArbitration,
    Party,
    StructuredContract,
)
from app.modules.contract_parser.structurer import LLMStructurer, RuleBasedStructurer

GOOD_TEXT = """订单农业合同

合同编号：DDNY-2026-0918

甲方（收购方）：明光市丰谷粮油有限公司
乙方（种植方）：明光市绿野家庭农场

第一条 订单标的
乙方按甲方订单要求种植优质水稻品种南粳46。

第二条 数量与金额
合同总金额人民币486,000元。

第三条 交货期限
交货时间为2026年11月1日至2026年11月30日。

第四条 签订日期
签订日期：2026年09月18日
"""


def _contract(**overrides) -> StructuredContract:
    base = dict(
        source_file="x.pdf",
        title="订单农业合同",
        parties=[Party(role="甲方", name="明光市丰谷粮油有限公司")],
        amount="486,000 元",
        sign_date="2026-09-18",
        delivery_deadline="2026-11-30",
        char_count=120,
        raw_text_preview=GOOD_TEXT[:100],
        fields=[ContractField(key="amount", label="合同金额", value="486,000 元")],
    )
    base.update(overrides)
    return StructuredContract(**base)


# ---------------- L4：必备字段判定 ----------------


def test_gate_ok_on_complete_contract() -> None:
    result = gate.evaluate(_contract())
    assert result.level == GATE_OK
    assert result.failures == []
    assert not result.blocked


def test_gate_blocked_when_parties_empty() -> None:
    """主体全缺是 blocking：下游企业核验整条链路会失效。"""
    result = gate.evaluate(_contract(parties=[]))
    assert result.level == GATE_BLOCKED
    assert result.blocked
    assert "合同主体" in result.missing_labels()
    # 主体缺失的说明必须点出下游后果，而不是干巴巴一句"字段为空"
    detail = next(f.detail for f in result.failures if f.key == "parties")
    assert "企业核验" in detail


def test_gate_blocked_when_no_text() -> None:
    result = gate.evaluate(_contract(char_count=0, raw_text_preview=""))
    assert result.level == GATE_BLOCKED
    assert "合同正文" in result.missing_labels()


def test_gate_degraded_when_trade_terms_missing() -> None:
    """个别必备字段缺失只降级不阻断：下游可继续，但必须携带标注。"""
    result = gate.evaluate(_contract(amount="", sign_date=""))
    assert result.level == GATE_DEGRADED
    assert not result.blocked
    assert set(result.missing_labels()) == {"合同金额", "签订日期"}


def test_gate_degraded_beats_ok_on_whitespace_only_value() -> None:
    """只有空白字符不算抽到——避免上游写入 " " 骗过门禁。"""
    result = gate.evaluate(_contract(amount="   "))
    assert result.level == GATE_DEGRADED


# ---------------- L1 → L2：升级触发 ----------------


def test_no_escalation_for_clean_electronic_contract() -> None:
    should, reason = gate.needs_escalation(_contract())
    assert should is False
    assert reason == ""


def test_escalate_when_parties_empty() -> None:
    should, reason = gate.needs_escalation(_contract(parties=[]))
    assert should is True
    assert "未识别到任何合同主体" in reason


def test_escalate_for_ocr_sourced_document() -> None:
    """图片/扫描件是规则抽取最脆弱的场景，即使字段看着齐全也升级复核。"""
    should, reason = gate.needs_escalation(_contract(used_ocr=True))
    assert should is True
    assert "OCR" in reason


def test_escalate_when_trade_terms_broadly_missing() -> None:
    should, reason = gate.needs_escalation(
        _contract(amount="", sign_date="", delivery_deadline="")
    )
    assert should is True
    assert "关键交易要素大面积缺失" in reason


def test_no_escalation_without_text() -> None:
    """无文本时 L2 也没有输入，不该白白多打一次模型。"""
    should, reason = gate.needs_escalation(_contract(char_count=0, raw_text_preview=""))
    assert should is False
    assert "无输入" in reason


# ---------------- 字段级仲裁：合并而不是整份二选一 ----------------


def _fields(**pairs: str) -> list[ContractField]:
    return [ContractField(key=key, label=key, value=value) for key, value in pairs.items()]


def _value_of(contract: StructuredContract, key: str) -> str:
    return next((f.value for f in contract.fields if f.key == key), "")


def test_choose_better_adopts_richer_l2() -> None:
    l1 = _contract(parties=[], amount="")
    l2 = _contract(parties=[Party(role="供方", name="某某材料有限公司")], amount="384,000 元")
    chosen, outcome, _ = gate.choose_better(l1, l2)
    assert outcome == gate.ESCALATION_ADOPTED
    # 旧行为是 `chosen is l2`（整份采用 L2）。现在改为字段级合并：
    # 主体由 L2 补入，同时**保住 L1 自己的字段**——整份采用会丢掉它们。
    assert [p.name for p in chosen.parties] == ["某某材料有限公司"]
    assert chosen is not l1
    assert _value_of(chosen, "amount") == "486,000 元"
    assert _value_of(chosen, "sign_date") == "2026-09-18"


def test_choose_better_merges_disjoint_field_hits() -> None:
    """核心回归：两侧各命中**不同**字段时必须合并。

    旧行为：`completeness` 三元组相等 → 判定平手 → 保留 L1 →
    L2 唯一抽对的那个字段被白白丢掉（纯损失，没有任何取舍理由）。
    """
    l1 = _contract(
        fields=_fields(amount="486,000 元"), amount="486,000 元", delivery_deadline=""
    )
    l2 = _contract(
        fields=_fields(delivery_deadline="2026年11月30日"),
        amount="",
        delivery_deadline="2026年11月30日",
    )
    chosen, outcome, note = gate.choose_better(l1, l2)

    assert outcome == gate.ESCALATION_ADOPTED
    assert _value_of(chosen, "amount") == "486,000 元"  # L1 的没丢
    assert _value_of(chosen, "delivery_deadline") == "2026年11月30日"  # L2 的补进来
    assert "补充 1 项" in note


def test_choose_better_conflict_keeps_rule_value_and_records_alternative() -> None:
    """两侧都有值但不一致：保留确定性规则的值，另一侧留档，**不假装知道谁对**。"""
    l1 = _contract(fields=_fields(amount="486,000 元"), amount="486,000 元")
    l2 = _contract(fields=_fields(amount="384,000 元"), amount="384,000 元")

    chosen, outcome, note = gate.choose_better(l1, l2)

    assert outcome == gate.ESCALATION_MERGED  # L2 没补充字段，但提供了交叉验证
    assert "冲突" in note
    field = next(f for f in chosen.fields if f.key == "amount")
    assert field.value == "486,000 元"
    assert field.alternative == "384,000 元"
    assert field.agreement == ARB_CONFLICT
    assert field.confidence == pytest.approx(0.45)


def test_choose_better_agreement_raises_confidence() -> None:
    """双源一致才是有信息量的可信信号——置信度由一致度导出，不再写死。"""
    l1 = _contract(fields=_fields(amount="486,000 元"), amount="486,000 元")
    l2 = _contract(fields=_fields(amount="486,000 元"), amount="486,000 元")

    chosen, outcome, note = gate.choose_better(l1, l2)

    assert outcome == gate.ESCALATION_MERGED
    field = next(f for f in chosen.fields if f.key == "amount")
    assert field.agreement == ARB_AGREED
    assert field.confidence == pytest.approx(0.95)
    assert "双源一致" in note


def test_choose_better_does_not_fabricate_parties_on_disjoint_role_schemes() -> None:
    """L1 用「供方/需方」、L2 用「甲方/乙方」描述同一对当事人时，不能取并集。

    按角色取并集会凭空造出 4 个主体，直接带偏主体数与下游企业核验。
    """
    l1 = _contract(
        parties=[Party(role="供方", name="甲公司"), Party(role="需方", name="乙合作社")]
    )
    l2 = _contract(
        parties=[Party(role="甲方", name="甲公司"), Party(role="乙方", name="乙合作社")]
    )

    chosen, _, _ = gate.choose_better(l1, l2)

    assert len(chosen.parties) == 2  # 不是 4
    roles = {a.key: a for a in chosen.arbitration}
    assert roles["parties.roles"].status == ARB_CONFLICT
    assert roles["parties.roles"].l1_value == "供方、需方"
    assert roles["parties.roles"].l2_value == "甲方、乙方"


def test_choose_better_rejects_placeholder_l2() -> None:
    """mock LLM 返回空壳：既无补充也无一致/冲突项 → 原样返回 L1，绝不覆盖。"""
    l1 = _contract()
    l2 = _contract(
        title="", parties=[], amount="", sign_date="", delivery_deadline="", fields=[]
    )
    chosen, outcome, note = gate.choose_better(l1, l2)
    assert outcome == gate.ESCALATION_REJECTED
    assert chosen is l1
    assert "保留 L1" in note


def test_completeness_prioritizes_parties_over_fields() -> None:
    """主体是唯一 blocking 项，优先级必须高于字段数量。"""
    no_party_many_fields = _contract(
        parties=[], fields=[ContractField(key=f"k{i}", label=f"l{i}", value="v") for i in range(8)]
    )
    one_party_no_fields = _contract(fields=[])
    assert gate.completeness(one_party_no_fields) > gate.completeness(no_party_many_fields)


def test_rule_structurer_marks_single_source() -> None:
    """单源时 agreement 必须是 single：没有第二个抽取器可比，confidence 只是静态先验。"""
    contract = RuleBasedStructurer().structure(
        PdfText(text=GOOD_TEXT, page_count=1, char_count=len(GOOD_TEXT), used_ocr=False)
    )
    assert contract.fields
    assert {f.agreement for f in contract.fields} == {ARB_SINGLE}
    assert contract.arbitration == []


# ---------------- 双源冲突进入门禁 ----------------


def _conflict(key: str, label: str) -> FieldArbitration:
    return FieldArbitration(
        key=key,
        label=label,
        status=ARB_CONFLICT,
        l1_value="甲",
        l2_value="乙",
        chosen_value="甲",
        chosen_from="l1",
        confidence=0.45,
    )


def test_gate_degrades_on_required_field_conflict() -> None:
    """值抽到了但两侧不一致 → 必须降级送人工核对，不能当成"抽到了就没问题"。"""
    contract = _contract(arbitration=[_conflict("amount", "合同金额")])
    result = gate.evaluate(contract)

    assert result.level == GATE_DEGRADED
    assert result.failures == []  # 不是"缺失"，是"冲突"——两者分开存
    assert result.conflict_labels() == ["合同金额"]
    assert "双源冲突" in result.summary


def test_gate_degrades_on_party_conflict() -> None:
    """主体名称两侧不一致会直接带偏企业核验，必须降级。"""
    contract = _contract(arbitration=[_conflict("party.甲方.name", "甲方名称")])
    result = gate.evaluate(contract)
    assert result.level == GATE_DEGRADED
    assert result.conflict_labels() == ["甲方名称"]


def test_gate_stays_ok_on_non_required_conflict() -> None:
    """非下游依赖的展示字段有措辞差异只留痕，不该把整份合同判成"不完整"。"""
    contract = _contract(arbitration=[_conflict("quality_standard", "质量标准")])
    result = gate.evaluate(contract)

    assert result.level == GATE_OK
    assert result.failures == []
    assert result.conflict_labels() == ["质量标准"]  # 仍然留痕可见
    assert "双源冲突" in result.summary


def test_warning_line_surfaces_conflicts() -> None:
    contract = _contract(arbitration=[_conflict("amount", "合同金额")])
    line = gate.warning_line(gate.evaluate(contract))
    assert "双源冲突" in line
    assert "人工核对" in line


def test_gate_summary_does_not_repeat_critical_conflicts() -> None:
    """关键冲突已经在结论里点过名，不该再被"另有 N 项"重复念一遍。"""
    contract = _contract(arbitration=[_conflict("amount", "合同金额")])
    summary = gate.evaluate(contract).summary
    assert summary.count("合同金额") == 1
    assert "另有" not in summary


def test_non_required_conflict_reported_separately() -> None:
    """关键冲突降级 + 非关键冲突只留痕，两类要能分开读出来。"""
    contract = _contract(
        arbitration=[
            _conflict("amount", "合同金额"),
            _conflict("quality_standard", "质量标准"),
        ]
    )
    result = gate.evaluate(contract)

    assert result.level == GATE_DEGRADED
    assert "另有 1 项非必备字段双源冲突" in result.summary
    assert "质量标准" in result.summary
    assert len(result.disagreements) == 2  # 两条都留痕


# ---------------- warning 行 ----------------


def test_warning_line_mentions_level_and_escalation() -> None:
    result = gate.evaluate(
        _contract(parties=[]),
        escalated=True,
        escalation_reason="未识别到任何合同主体",
        escalation_outcome=gate.ESCALATION_UNAVAILABLE,
        escalation_note="L2 未就绪：未配置盘古大模型",
    )
    line = gate.warning_line(result)
    assert "[门禁/blocked]" in line
    assert "合同主体" in line
    assert "L1→L2" in line


# ---------------- 服务层编排（打桩，不调真实模型） ----------------


class _StubStructurer:
    """可控的结构化器，用于验证 service 的升级编排。"""

    name = "stub"

    def __init__(self, contract: StructuredContract) -> None:
        self._contract = contract
        self.calls = 0

    def structure(self, pdf_text, filename: str) -> StructuredContract:
        self.calls += 1
        return self._contract.model_copy(deep=True)


def _patch_pipeline(monkeypatch, l1: _StubStructurer, l2_factory) -> list[tuple]:
    """把 service 的读取 / L1 / L2 / 落盘全部打桩，记录落盘的那份结果。"""
    saved: list[tuple] = []

    monkeypatch.setattr(
        "app.modules.contract_parser.service.read_document",
        lambda data, name: PdfText(
            text=GOOD_TEXT, page_count=1, char_count=len(GOOD_TEXT), used_ocr=False
        ),
    )
    monkeypatch.setattr(
        "app.modules.contract_parser.service.get_structurer", lambda: l1
    )
    monkeypatch.setattr(
        "app.modules.contract_parser.service._l2_structurer", l2_factory
    )
    monkeypatch.setattr(
        "app.modules.contract_parser.service.storage.save_contract",
        lambda doc_id, data, name, contract: saved.append((doc_id, contract)),
    )
    monkeypatch.setattr(
        "app.modules.contract_parser.service.storage.new_doc_id", lambda: "doc-test"
    )
    return saved


def test_service_escalates_and_adopts_better_l2(monkeypatch) -> None:
    l1 = _StubStructurer(_contract(parties=[], used_ocr=True))
    richer = _contract(
        parties=[Party(role="供方", name="四川光亚新材料科技有限公司")],
        used_ocr=True,
    )
    saved = _patch_pipeline(monkeypatch, l1, lambda: _StubStructurer(richer))

    _, contract = service.parse_contract(b"%PDF-fake", "scan.pdf")

    assert contract.gate.escalated is True
    assert contract.gate.escalation_outcome == gate.ESCALATION_ADOPTED
    assert contract.parties[0].name == "四川光亚新材料科技有限公司"
    assert saved[0][1] is contract


def test_service_keeps_l1_when_l2_not_ready(monkeypatch) -> None:
    """L2 未就绪不是静默失败：原因必须落到 gate 上，L1 结果照常返回。"""

    def _boom():
        raise ProviderNotReadyError("盘古大模型未就绪")

    l1 = _StubStructurer(_contract(parties=[], used_ocr=True))
    _patch_pipeline(monkeypatch, l1, _boom)

    _, contract = service.parse_contract(b"%PDF-fake", "scan.pdf")

    assert contract.gate.escalation_outcome == gate.ESCALATION_UNAVAILABLE
    assert "未就绪" in contract.gate.escalation_note
    assert contract.gate.level == GATE_BLOCKED  # 主体仍缺 → 门禁照常阻断


def test_service_skips_escalation_when_already_llm(monkeypatch) -> None:
    """L1 本身就是 LLM 时不再升级自己，避免无意义重复调用。"""

    class _StubLlm(LLMStructurer):
        def __init__(self, contract: StructuredContract) -> None:
            self._contract = contract

        def structure(self, pdf_text, filename: str = "") -> StructuredContract:
            return self._contract.model_copy(deep=True)

    l1 = _StubLlm(_contract(parties=[]))
    saved = _patch_pipeline(monkeypatch, l1, lambda: _StubStructurer(_contract()))

    _, contract = service.parse_contract(b"%PDF-fake", "scan.pdf")

    assert contract.gate.escalation_outcome == gate.ESCALATION_SKIPPED
    assert "已是 LLM" in contract.gate.escalation_note
    assert saved  # 仍然落盘


def test_service_escalation_can_be_disabled(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "contract_escalation", "off", raising=False)
    l1 = _StubStructurer(_contract(parties=[]))
    _patch_pipeline(
        monkeypatch,
        l1,
        lambda: (_ for _ in ()).throw(AssertionError("关闭开关后不应调用 L2")),
    )

    _, contract = service.parse_contract(b"%PDF-fake", "scan.pdf")

    assert contract.gate.escalation_outcome == gate.ESCALATION_SKIPPED
    assert "off" in contract.gate.escalation_note


def test_service_appends_gate_warning(monkeypatch) -> None:
    l1 = _StubStructurer(_contract(parties=[]))
    _patch_pipeline(monkeypatch, l1, lambda: _StubStructurer(_contract()))

    _, contract = service.parse_contract(b"%PDF-fake", "scan.pdf")

    assert any(w.startswith("[门禁/") for w in contract.warnings)


def test_incident_shape_is_blocked_not_silent() -> None:
    """事故形态回归：无主体标签的文本 → 主体为空 → 门禁必须 blocked。

    旧行为：parties=[] 且零 warning，下游静默跳过整套核验。
    新行为：gate.level=blocked + 显式 warning 行。
    """
    text = PdfText(
        text="货物名称 数量 单价\nPC树脂 32吨 12000\n备注:不含税\n",
        page_count=1,
        char_count=40,
        used_ocr=True,
    )
    contract = RuleBasedStructurer().structure(text, "scan.jpg")
    assert contract.parties == []

    should, reason = gate.needs_escalation(contract)
    assert should is True

    result = gate.evaluate(
        contract,
        escalated=True,
        escalation_reason=reason,
        escalation_outcome=gate.ESCALATION_REJECTED,
        escalation_note="L2 结果未优于 L1",
    )
    assert result.level == GATE_BLOCKED
    assert "[门禁/blocked]" in gate.warning_line(result)


def test_parse_contract_still_rejects_unsupported_type() -> None:
    with pytest.raises(service.ContractParseError, match="不支持的文件类型"):
        service.parse_contract(b"plain text", "note.txt")
