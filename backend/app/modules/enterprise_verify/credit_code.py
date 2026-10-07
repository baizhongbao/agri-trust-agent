"""统一社会信用代码本地校验（L1）。

依据 GB 32100-2015《法人和其他组织统一社会信用代码编码规则》：
- 18 位字符：登记管理部门 + 机构类别 + 行政区划 + 主体标识码 + 校验码
- 字符集 31 个：数字 + 大写字母（剔除 I / O / S / V / Z，避免与 0 / 1 / 5 / 2 混淆）
- 校验码 = (31 - Σ(前 17 位字符值 × 权重) mod 31) mod 31

这一层完全本地计算：零依赖、零成本、可离线，
不调用任何外部接口即可发现「代码抄错 / 造假」这类硬伤。
"""

from __future__ import annotations

from app.modules.enterprise_verify.schema import CheckItem

CHARSET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)
ILLEGAL_LETTERS = frozenset("IOSVZ")


def normalize(code: str) -> str:
    """清理常见录入噪音：首尾空白、全角字符、分隔符。"""
    return (code or "").strip().upper().replace(" ", "").replace("　", "")


def compute_check_char(prefix17: str) -> str | None:
    """由前 17 位计算校验位。输入不合法时返回 None，绝不猜。"""
    if len(prefix17) != 17:
        return None
    total = 0
    for char, weight in zip(prefix17, WEIGHTS):
        index = CHARSET.find(char)
        if index < 0:
            return None
        total += index * weight
    return CHARSET[(31 - total % 31) % 31]


def validate_checksum(code: str) -> bool:
    """整码校验：前 17 位加权求和 + 校验位 ≡ 0 (mod 31)。"""
    if len(code) != 18:
        return False
    expected = compute_check_char(code[:17])
    return expected is not None and code[17] == expected


def run_l1_checks(raw_code: str) -> list[CheckItem]:
    """对合同里抄录的信用代码跑 L1 检查，产出可读的判定项。"""
    code = normalize(raw_code)

    if not code:
        return [
            CheckItem(
                key="credit_code_present",
                label="信用代码载明",
                layer="L1",
                status="warning",
                detail="合同未载明该主体的统一社会信用代码，无法进行本地校验与精确核验",
                evidence="（合同原文中未找到该主体的信用代码）",
            )
        ]

    items: list[CheckItem] = []

    if len(code) != 18:
        items.append(
            CheckItem(
                key="code_format",
                label="代码格式",
                layer="L1",
                status="fail",
                detail=f"长度为 {len(code)} 位，应为 18 位（GB 32100-2015）",
                evidence=code,
            )
        )
        return items

    illegal = sorted({c for c in code if c in ILLEGAL_LETTERS})
    if illegal:
        items.append(
            CheckItem(
                key="code_format",
                label="代码格式",
                layer="L1",
                status="fail",
                detail=(
                    "含非法字符 "
                    f"{'、'.join(illegal)}（编码字符集不含 I / O / S / V / Z，"
                    "GB 32100-2015 为避免与数字混淆已将其剔除）"
                ),
                evidence=code,
            )
        )
        return items

    items.append(
        CheckItem(
            key="code_format",
            label="代码格式",
            layer="L1",
            status="pass",
            detail="18 位、字符集合法",
            evidence=code,
        )
    )

    expected = compute_check_char(code[:17])
    if code[17] == expected:
        items.append(
            CheckItem(
                key="code_checksum",
                label="校验位验算",
                layer="L1",
                status="pass",
                detail=f"按 GB 32100-2015 加权算法验算通过（校验位应为 {expected}，实际为 {code[17]}）",
                evidence=code,
            )
        )
    else:
        items.append(
            CheckItem(
                key="code_checksum",
                label="校验位验算",
                layer="L1",
                status="fail",
                detail=(
                    f"校验位不匹配：按 GB 32100-2015 加权算法应为 {expected}，"
                    f"合同载明为 {code[17]}。代码可能抄录有误或系伪造"
                ),
                evidence=code,
            )
        )

    return items
