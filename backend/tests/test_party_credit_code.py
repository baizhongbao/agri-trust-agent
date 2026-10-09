"""主体与统一社会信用代码的关联测试（A3 回归）。

事故：`_extract_parties` 曾用 `zip(parties, findall(codes))` 按出现顺序硬配对。
当只有一个主体带码、或代码顺序与主体顺序不一致、或正文混入其他 18 位串时，
会把甲的代码挂到乙身上，且**静默**污染下游 L1 校验位与 L3 交叉校验。
现改为按「就近原则」一对一归属。
"""

from __future__ import annotations

from app.modules.contract_parser.pdf_reader import PdfText
from app.modules.contract_parser.structurer import RuleBasedStructurer

CODE_A = "913411826123456782"
CODE_B = "91341182687654321U"


def _parties(text: str):
    contract = RuleBasedStructurer().structure(
        PdfText(text=text, page_count=1, char_count=len(text))
    )
    return {party.role: party for party in contract.parties}, contract.warnings


def test_code_maps_to_its_own_party() -> None:
    """标准版式：每个主体名称下一行就是自己的代码，各归各位。"""
    text = (
        "甲方（收购方）：明光市丰谷粮油有限公司\n"
        f"统一社会信用代码：{CODE_A}\n"
        "乙方（种植方）：明光市绿野家庭农场\n"
        f"统一社会信用代码：{CODE_B}\n"
    )
    by_role, warnings = _parties(text)
    assert by_role["甲方"].credit_code == CODE_A
    assert by_role["乙方"].credit_code == CODE_B
    assert not any("未能归属" in w for w in warnings)


def test_single_code_not_misassigned_to_other_party() -> None:
    """只有乙方带码时，代码必须归乙方；甲方不得被硬塞上乙方的代码。"""
    text = (
        "甲方（收购方）：明光市丰谷粮油有限公司\n"
        "乙方（种植方）：明光市绿野家庭农场\n"
        f"统一社会信用代码：{CODE_B}\n"
    )
    by_role, _ = _parties(text)
    assert by_role["乙方"].credit_code == CODE_B
    assert by_role["甲方"].credit_code == ""


def test_unattributable_code_emits_warning() -> None:
    """距离过远、无法归属的代码必须留下 warning，而不是静默丢弃或乱塞。"""
    text = (
        "甲方（收购方）：明光市丰谷粮油有限公司\n"
        "第一条 订单标的\n"
        + "为明确双方权利义务，" * 12
        + "\n"
        f"备注：资产编号 {CODE_A}\n"
    )
    by_role, warnings = _parties(text)
    assert by_role["甲方"].credit_code == ""
    assert any("未能归属" in w for w in warnings)
