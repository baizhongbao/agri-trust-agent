"""合同事实的确定性一致性自检（"怀疑者"角色）。

**为什么需要这一层**：`facts` 逐项抽取，每一项单看都"抽到了"，
但它们彼此之间必须自洽——签订日期不该晚于生效日期，交货期不该早于签订日，
定金不该超过主合同标的额的 20%。这类矛盾是**抽取错误最可靠的信号**，
而且只能靠交叉比对发现，单看任何一个字段都看不出来。

**与 `simulation/calculator.py` 的分工**：
    calculator 的 checks 校验的是"计算输入"（数量×单价 vs 合同总额）；
    本模块校验的是"合同事实本身的内部一致性"，与履约情景无关，
    所以放在解析层，任何消费 facts 的模块都能受益。

**全部为纯函数，不调用大模型**——与「数值不交给 LLM」同源。
判不了就不判：日期不是绝对日期（如「签字盖章之日起」）时对应规则**不适用**，
不产生结论，而不是硬给一个 pass。
"""

from __future__ import annotations

from app.modules.contract_parser.schema import ConsistencyCheck, ContractFacts

# 《中华人民共和国民法典》第五百八十六条：定金数额不得超过主合同标的额的百分之二十，
# 超过部分不产生定金的效力。
DEPOSIT_LIMIT_RATIO = 0.20
DEPOSIT_LEGAL_BASIS = (
    "《中华人民共和国民法典》第五百八十六条：定金数额不得超过主合同标的额的百分之二十，"
    "超过部分不产生定金的效力"
)

# 《中华人民共和国民法典》第五百八十五条：约定违约金过分高于造成的损失的，
# 可以请求适当减少。司法实践通常以超过损失 30% 为"过分高于"的参考线。
PENALTY_REVIEW_RATIO = 0.30
PENALTY_LEGAL_BASIS = (
    "《中华人民共和国民法典》第五百八十五条：约定的违约金过分高于造成的损失的，"
    "可以请求人民法院或者仲裁机构予以适当减少（司法实践常以超过损失 30% 为参考线）"
)


def _check(
    code: str,
    status: str,
    detail: str,
    *,
    evidence: str = "",
    legal_basis: str = "",
) -> ConsistencyCheck:
    return ConsistencyCheck(
        code=code,
        status=status,
        detail=detail,
        evidence=evidence,
        legal_basis=legal_basis,
    )


def _absolute(contract_date) -> str:
    """取绝对日期（ISO）；非绝对日期返回空串——相对表达无从比较。"""
    if contract_date is None or contract_date.kind != "absolute":
        return ""
    return (contract_date.start or "").strip()


def check_dates(facts: ContractFacts) -> list[ConsistencyCheck]:
    """日期先后关系自检：签订 ≤ 生效，签订 ≤ 交货，生效 ≤ 交货。

    只对**绝对日期**判定。合同里大量日期是相对表达（「自双方签字盖章之日起生效」），
    那不是抽取失败而是合同的真实形态，可比性不存在，故不做结论。
    """
    sign = _absolute(facts.sign_date)
    if not sign:  # 没有签订日期这个基准，任何先后判断都无从谈起
        return []

    checks: list[ConsistencyCheck] = []
    effective = _absolute(facts.effective_date)
    delivery = _absolute(facts.delivery)

    if effective:
        bad = effective < sign
        checks.append(
            _check(
                "effective_date_before_sign_date" if bad else "date_order_effective_after_sign",
                "warning" if bad else "ok",
                (
                    f"生效日期 {effective} 早于签订日期 {sign}——合同不可能在签订前生效，"
                    "两个日期至少有一项抽取有误，需人工核对"
                    if bad
                    else f"签订日期 {sign} 不晚于生效日期 {effective}，先后关系成立"
                ),
                evidence=facts.evidences.get("sign_date", "")
                or facts.evidences.get("effective_date", ""),
            )
        )

    if delivery:
        bad = delivery < sign
        checks.append(
            _check(
                "delivery_before_sign_date" if bad else "date_order_delivery_after_sign",
                "warning" if bad else "ok",
                (
                    f"交货期限 {delivery} 早于签订日期 {sign}——签约时交货期已过，"
                    "两个日期至少有一项抽取有误，需人工核对"
                    if bad
                    else f"交货期限 {delivery} 不早于签订日期 {sign}，先后关系成立"
                ),
                evidence=facts.evidences.get("delivery", "")
                or facts.evidences.get("sign_date", ""),
            )
        )
        if effective:
            bad = delivery < effective
            checks.append(
                _check(
                    "delivery_before_effective_date" if bad else "date_order_delivery_after_effective",
                    "warning" if bad else "ok",
                    (
                        f"交货期限 {delivery} 早于生效日期 {effective}，"
                        "履约窗口与生效时点矛盾，需人工核对"
                        if bad
                        else f"交货期限 {delivery} 不早于生效日期 {effective}，先后关系成立"
                    ),
                    evidence=facts.evidences.get("delivery", ""),
                )
            )

    return checks


def check_deposit(facts: ContractFacts) -> list[ConsistencyCheck]:
    """定金比例上限自检（民法典 586 条，20%）。"""
    deposit = facts.deposit
    if deposit is None or deposit.rate is None:
        return []

    over = deposit.rate > DEPOSIT_LIMIT_RATIO
    return [
        _check(
            "deposit_ratio_over_20_percent" if over else "deposit_ratio_within_limit",
            "warning" if over else "ok",
            (
                f"约定定金比例 {deposit.rate:.2%}（基数：{deposit.base or '未载明'}）"
                f"超过主合同标的额 {DEPOSIT_LIMIT_RATIO:.0%} 的法定上限，"
                "超过部分不产生定金效力"
                if over
                else f"约定定金比例 {deposit.rate:.2%}，未超过 {DEPOSIT_LIMIT_RATIO:.0%} 的法定上限"
            ),
            evidence=facts.evidences.get("deposit", ""),
            legal_basis=DEPOSIT_LEGAL_BASIS,
        )
    ]


def check_penalty(facts: ContractFacts) -> list[ConsistencyCheck]:
    """违约金比例过高提示。

    刻意给 `review` 而不是 `warning`：违约金是否"过分高于损失"取决于**实际损失**，
    而实际损失不在合同里，系统无从判断。所以只提示需要复核，不宣称违规。
    """
    penalty = facts.penalty
    if penalty is None or penalty.rate is None or (penalty.kind or "ratio") != "ratio":
        return []

    high = penalty.rate > PENALTY_REVIEW_RATIO
    return [
        _check(
            "penalty_ratio_requires_review" if high else "penalty_ratio_within_reference",
            "review" if high else "ok",
            (
                f"约定违约金为合同总额的 {penalty.rate:.2%}（基数：{penalty.base or '未载明'}），"
                f"高于通常参考线 {PENALTY_REVIEW_RATIO:.0%}。是否可请求酌减取决于实际损失，"
                "实际损失不在合同内、系统无从判断，请人工复核"
                if high
                else f"约定违约金为合同总额的 {penalty.rate:.2%}，未超过 {PENALTY_REVIEW_RATIO:.0%} 的参考线"
            ),
            evidence=facts.evidences.get("penalty", ""),
            legal_basis=PENALTY_LEGAL_BASIS,
        )
    ]


def check_facts(facts: ContractFacts) -> list[ConsistencyCheck]:
    """跑全部确定性自检，返回逐条结论（含 ok）。

    不适用的规则**不产生条目**，而不是产生一个 pass——"没检查"和"检查通过"
    是两件事，混淆它们正是本项目反复踩的坑。
    """
    if facts is None:
        return []
    return [*check_dates(facts), *check_deposit(facts), *check_penalty(facts)]


def problems(checks: list[ConsistencyCheck]) -> list[ConsistencyCheck]:
    """筛出未通过的条目（warning / review）。"""
    return [c for c in checks if c.status != "ok"]
