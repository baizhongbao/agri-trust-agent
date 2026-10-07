"""统一社会信用代码 L1 校验的单元测试。

校验位算法以真实登记代码（比亚迪股份有限公司）为基准验证，
再用「改最后一位必须失败」守住算法本身。
"""

from __future__ import annotations

from app.modules.enterprise_verify import credit_code

# 真实登记代码（已通过企查查核验存在）
REAL_BYD_CODE = "91440300192317458F"
# 示例合同两家主体（校验位由 GB 32100-2015 算法计算得出）
PARTY_A = "913411826123456782"
PARTY_B = "91341182687654321U"
# 演示库中的两家虚构主体
FIXTURE_HENGCHANG = "91341182MA2T7QKX9E"
FIXTURE_JINSUI = "91341182MA2W7L9XKW"


def test_real_world_code_passes_checksum() -> None:
    assert credit_code.validate_checksum(REAL_BYD_CODE)


def test_fixture_codes_pass_checksum() -> None:
    for code in (PARTY_A, PARTY_B, FIXTURE_HENGCHANG, FIXTURE_JINSUI):
        assert credit_code.validate_checksum(code), code


def test_tampered_check_digit_fails() -> None:
    assert not credit_code.validate_checksum("91341182612345678X")
    assert not credit_code.validate_checksum("91341182687654321Y")
    assert not credit_code.validate_checksum(REAL_BYD_CODE[:-1] + "0")


def test_compute_check_char_roundtrip() -> None:
    for code in (REAL_BYD_CODE, PARTY_A, PARTY_B):
        assert credit_code.compute_check_char(code[:17]) == code[17]


def test_wrong_length_fails() -> None:
    assert not credit_code.validate_checksum("9134118261234567")
    assert not credit_code.validate_checksum("9134118261234567822")


def test_illegal_letters_fail() -> None:
    # I / O / S / V / Z 不在编码字符集内
    for illegal in ("9134118261234567I8"[0:18], "9134118261234567O8", "9134118261234567S8"):
        assert not credit_code.validate_checksum(illegal)


def test_normalize_strips_noise() -> None:
    assert credit_code.normalize(" 913411826123456782 ") == PARTY_A
    assert credit_code.normalize("913411826123456782".lower()) == PARTY_A


def test_run_l1_checks_pass() -> None:
    items = {item.key: item for item in credit_code.run_l1_checks(PARTY_A)}
    assert items["code_format"].status == "pass"
    assert items["code_checksum"].status == "pass"


def test_run_l1_checks_bad_checksum() -> None:
    items = {item.key: item for item in credit_code.run_l1_checks("91341182612345678X")}
    assert items["code_checksum"].status == "fail"
    assert "校验位不匹配" in items["code_checksum"].detail


def test_run_l1_checks_missing_code() -> None:
    items = credit_code.run_l1_checks("")
    assert len(items) == 1
    assert items[0].status == "warning"


def test_run_l1_checks_short_code() -> None:
    items = credit_code.run_l1_checks("913411826")
    assert items[0].key == "code_format"
    assert items[0].status == "fail"
    assert "长度" in items[0].detail
