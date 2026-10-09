"""无「第X条」标题、标签:值 行流合同的条款切分与主体识别回归测试。

覆盖：整份文档揉成一条 clauses 的 bug（页眉/签名区逐页重复捞取）、
供方/需方 主体识别、同行「单位名称:」标签剥离。
"""

from __future__ import annotations

from app.modules.contract_parser.structurer import RuleBasedStructurer, split_clauses
from app.modules.contract_parser.pdf_reader import PdfText

SIGNATURE_TEXT = (
    "供方:四川光亚新材料科技有限公司:需方:单位名称:李姜伟\n"
    + "法定代表人或授权代表签字/盖章:谭小东\n"
    + "法定代表人或授权代表签字/盖章:李姜伟\n"
    + "法人代表:李姜伟\n"
) * 5  # 模拟逐页重复捞取签名区


def _structure(text: str):
    return RuleBasedStructurer().structure(PdfText(text=text, page_count=1, char_count=len(text)))


def test_signature_only_block_keeps_heading_and_dedupes() -> None:
    """只有签名区时，应保留一行首部（带签字痕迹）而非整块丢弃或揉成一条。"""
    contract = _structure(SIGNATURE_TEXT)
    assert len(contract.clauses) == 1
    assert contract.clauses[0].title == "合同首部"
    # 重复的「法人代表:李姜伟」被折叠，只保留首个签名行
    assert contract.clauses[0].content.count("法定代表人或授权代表签字/盖章") == 1


def test_signature_lines_not_inflated_to_full_block() -> None:
    """重复签名行不能被算成多行正文。"""
    clauses = split_clauses(SIGNATURE_TEXT)
    assert len(clauses) >= 1
    for clause in clauses:
        assert clause.content.count("法人代表:李姜伟") <= 1


def test_party_rules_handle_supply_and_demand_roles() -> None:
    """「供方/需方」应被识别，且「需方:单位名称:李姜伟」不吞后半行。"""
    contract = _structure(SIGNATURE_TEXT)
    roles = {p.role for p in contract.parties}
    assert "供方" in roles
    assert "需方" in roles
    by_role = {p.role: p.name for p in contract.parties}
    assert by_role["供方"] == "四川光亚新材料科技有限公司"
    assert by_role["需方"] == "李姜伟"


def test_party_rules_trailing_attribute_cut() -> None:
    """标签:值 行流中姓名后粘连其他字段时只取姓名部分。"""
    contract = _structure(
        "供方:四川光亚新材料科技有限公司 法定代表人:王五 需方:单位名称:李姜伟 联系电话:13800000000\n"
        + SIGNATURE_TEXT
    )
    by_role = {p.role: p.name for p in contract.parties}
    assert by_role["供方"] == "四川光亚新材料科技有限公司"
    assert by_role["需方"] == "李姜伟"