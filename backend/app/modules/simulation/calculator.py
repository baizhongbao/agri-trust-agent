"""履约模拟的数值计算层。

铁律：**数值计算必须由 Python 完成，LLM 只负责理解情景与解释结论**。
    每个数字都可复核：输入来自 facts（带 evidence），
    计算过程写成 `calc_steps`，输出值逐项列出公式与操作数。

三情景：
    price_fluctuation  价格波动 —— 市场价偏离合同价时的双方损益与毁约诱因
    natural_disaster   自然灾害 —— 减产比例下的交付缺口与损失分担
    party_breach       一方违约 —— 违约金计算与实际损失估算
"""

from __future__ import annotations

from typing import Any

from app.modules.contract_parser.schema import ContractFacts


def _amount_value(facts: ContractFacts) -> float | None:
    value = facts.amount.value if facts.amount else None
    return value if value is not None else None


def _fmt(value: float | None, suffix: str = "") -> str:
    return "—" if value is None else f"{value:,.2f}{suffix}".rstrip("0").rstrip(".")


def _step(formula: str, result: float | None) -> dict[str, Any]:
    return {"formula": formula, "result": result}


# 价格波动情景的敏感性区间档位（改进 4）
_PRICE_TIERS_PCT = (20.0, 0.0, -20.0)
# 自然灾害情景的敏感性区间档位
_DISASTER_TIERS_PCT = (10.0, 30.0, 50.0)


def simulate_price_fluctuation(
    facts: ContractFacts,
    price_change_pct: float,
) -> dict[str, Any]:
    """价格波动情景。

    输入：price_change_pct —— 市场价相对合同价的涨跌幅（% ，正=涨）。
    计算：
        基准交易额 = 合同总额 facts.amount
                    （总额缺失、但单价×数量齐备时，用「单价×数量」推算）
        市场价下的交易额 = 基准交易额 × (1 + 涨跌幅)
        偏离额 = 市场价交易额 − 基准交易额
        种植方毁约诱因 = 涨幅时贱卖损失（即偏离额）
        收购方毁约诱因 = 跌幅时贵买损失（即偏离额绝对值）

    另输出 tiers：±20% / 0 三档的敏感性区间，一眼看清最坏/基准/最好。
    """
    amount = _amount_value(facts)
    quantity = facts.quantity.value if facts.quantity and facts.quantity.value else None
    unit_price = facts.unit_price.value if facts.unit_price and facts.unit_price.value else None

    derived = False
    if amount is None and unit_price is not None and quantity is not None:
        amount = round(unit_price * quantity, 2)
        derived = True

    if amount is None:
        return {
            "computable": False,
            "reason": "合同未载明金额（facts.amount 为空），且无单价×数量可推算，无法进行价格损益计算",
            "calc_steps": [],
        }

    change = float(price_change_pct) / 100.0

    steps: list[dict[str, Any]] = []
    if derived:
        steps.append(_step(f"合同无总额，按单价×数量推算 = {unit_price:,.2f} × {quantity:,.2f}", amount))
    elif unit_price is not None and quantity is not None:
        check = round(unit_price * quantity, 2)
        consistent = abs(check - amount) / amount < 0.02 if amount else False
        steps.append(
            _step(
                f"一致性校验：数量×单价 = {unit_price:,.2f} × {quantity:,.2f} = {check:,.2f}"
                f"（合同总额 {amount:,.2f}，{'一致' if consistent else '存在偏差，以合同总额为准'}）",
                check,
            )
        )

    market_value = amount * (1 + change)
    deviation = market_value - amount

    # 谁有毁约诱因：涨价时种植方倾向毁约（外卖更高价），跌价时收购方倾向毁约（外购更便宜）
    if change > 0:
        breach_party = "种植/供应方（外卖可多赚，倾向弃单）"
        incentive = deviation
    elif change < 0:
        breach_party = "收购方（外购更便宜，倾向弃单）"
        incentive = -deviation
    else:
        breach_party = "无明显诱因"
        incentive = 0.0

    steps += [
        _step(
            f"基准交易额 = {'单价×数量推算' if derived else '合同总金额'} {amount:,.2f} 元",
            amount,
        ),
        _step(
            f"市场价下交易额 = {amount:,.2f} × (1 + ({price_change_pct}% / 100))",
            round(market_value, 2),
        ),
        _step(f"偏离额 = {market_value:,.2f} − {amount:,.2f}", round(deviation, 2)),
        _step(f"毁约诱因金额 = |偏离额|（{breach_party}）", round(incentive, 2)),
    ]

    return {
        "computable": True,
        "params": {"price_change_pct": price_change_pct},
        "contract_amount": amount,
        "amount_source": "单价×数量推算" if derived else "合同总金额",
        "market_value": round(market_value, 2),
        "deviation": round(deviation, 2),
        "breach_incentive_party": breach_party,
        "breach_incentive_value": round(incentive, 2),
        "tiers": [_price_tier(amount, pct) for pct in _PRICE_TIERS_PCT],
        "calc_steps": steps,
        "summary": (
            f"市场价较合同价{'上涨' if change > 0 else '下跌'} {abs(price_change_pct)}%，"
            f"同等数量下市场交易额为 {_fmt(market_value)} 元，与合同金额偏离 {_fmt(deviation)} 元；"
            f"该价差构成 {breach_party} 的毁约诱因（约 {_fmt(incentive)} 元）。"
        ),
    }


def _price_tier(base_amount: float, pct: float) -> dict[str, Any]:
    """单个价格敏感性档位的计算。"""
    change = pct / 100.0
    market_value = base_amount * (1 + change)
    deviation = market_value - base_amount
    if change > 0:
        party = "种植/供应方"
        incentive = deviation
    elif change < 0:
        party = "收购方"
        incentive = -deviation
    else:
        party = "无明显诱因"
        incentive = 0.0
    return {
        "label": f"{pct:+.0f}%",
        "pct": pct,
        "market_value": round(market_value, 2),
        "deviation": round(deviation, 2),
        "incentive_party": party,
        "incentive_value": round(incentive, 2),
    }


def simulate_natural_disaster(
    facts: ContractFacts,
    loss_ratio_pct: float,
) -> dict[str, Any]:
    """自然灾害情景。

    输入：loss_ratio_pct —— 减产比例（%，0~100）。
    计算：
        可交付量 = facts.quantity × (1 − 减产比例)
        交付缺口 = facts.quantity − 可交付量
        缺口对应金额 = 合同金额 × 减产比例（按比例折算）
    法定背景：《民法典》第五百九十条，不可抗力部分或全部免责，
    但迟延履行后发生不可抗力的不免责——定性结论交给 LLM/人工，这里只算数。
    """
    loss = max(0.0, min(100.0, float(loss_ratio_pct))) / 100.0
    amount = _amount_value(facts)
    quantity = facts.quantity.value if facts.quantity and facts.quantity.value else None

    if quantity is None and amount is None:
        return {
            "computable": False,
            "reason": "合同未载明数量与金额，无法计算减产损失",
            "calc_steps": [],
        }

    steps: list[dict[str, Any]] = []
    deliverable: float | None = None
    shortfall: float | None = None
    if quantity is not None:
        deliverable = quantity * (1 - loss)
        shortfall = quantity - deliverable
        steps.append(_step(f"合同数量 = {quantity:,.2f} {facts.quantity.unit}", quantity))
        steps.append(
            _step(
                f"可交付量 = {quantity:,.2f} × (1 − {loss_ratio_pct}%) = {deliverable:,.2f} {facts.quantity.unit}",
                round(deliverable, 2),
            )
        )
        steps.append(_step(f"交付缺口 = {quantity:,.2f} − {deliverable:,.2f}", round(shortfall, 2)))

    loss_amount: float | None = None
    if amount is not None:
        loss_amount = amount * loss
        steps.append(_step(f"合同总金额 = {amount:,.2f} 元", amount))
        steps.append(
            _step(
                f"缺口对应金额（按比例折算）= {amount:,.2f} × {loss_ratio_pct}% = {loss_amount:,.2f} 元",
                round(loss_amount, 2),
            )
        )

    parts = []
    if shortfall is not None:
        parts.append(f"减产 {loss_ratio_pct}% 后可交付 {_fmt(deliverable)}（缺口 {_fmt(shortfall)}）")
    if loss_amount is not None:
        parts.append(f"缺口对应货值约 {_fmt(loss_amount)} 元")
    summary = "；".join(parts) + "。是否免责取决于不可抗力认定与通知义务履行（《民法典》第五百九十条），建议核对合同不可抗力条款。"

    return {
        "computable": True,
        "params": {"loss_ratio_pct": loss_ratio_pct},
        "contract_amount": amount,
        "contract_quantity": quantity,
        "deliverable_quantity": round(deliverable, 2) if deliverable is not None else None,
        "shortfall_quantity": round(shortfall, 2) if shortfall is not None else None,
        "loss_amount": round(loss_amount, 2) if loss_amount is not None else None,
        "tiers": _disaster_tiers(facts),
        "calc_steps": steps,
        "summary": summary,
    }


def _disaster_tiers(facts: ContractFacts) -> list[dict[str, Any]]:
    """自然灾害情景的敏感性三档：减产 10% / 30% / 50%。"""
    tiers: list[dict[str, Any]] = []
    amount = _amount_value(facts)
    quantity = facts.quantity.value if facts.quantity and facts.quantity.value else None
    for pct in _DISASTER_TIERS_PCT:
        loss = pct / 100.0
        tier: dict[str, Any] = {"label": f"{pct:.0f}%", "pct": pct}
        if quantity is not None:
            deliverable = round(quantity * (1 - loss), 2)
            tier["deliverable_quantity"] = deliverable
            tier["shortfall_quantity"] = round(quantity - deliverable, 2)
        if amount is not None:
            tier["loss_amount"] = round(amount * loss, 2)
        tiers.append(tier)
    return tiers


def simulate_party_breach(
    facts: ContractFacts,
    breach_party: str = "unspecified",
) -> dict[str, Any]:
    """一方违约情景：违约金计算。

    违约金形态（facts.penalty.kind）：
        ratio   —— 按基数百分比：违约金 = 合同金额 × rate
        fixed   —— 固定金额（rate 视为元）
        per_day —— 按日计（需要天数参数，缺省提示 review）
    依据背景：《民法典》第五百八十五条，约定违约金低于/过分高于损失可请求调整——
    这是 LLM 定性分析的引用点，数值只管算。
    """
    amount = _amount_value(facts)
    penalty = facts.penalty

    if penalty is None or (penalty.rate is None and not penalty.raw):
        return {
            "computable": False,
            "reason": "合同未载明违约金约定（facts.penalty 为空），无法计算；实际损失可另行主张",
            "calc_steps": [],
            "legal_note": "《民法典》第五百八十四条：损失赔偿额应相当于因违约所造成的损失。",
        }

    kind = penalty.kind or "ratio"
    steps: list[dict[str, Any]] = []

    if kind == "ratio" and penalty.rate is not None:
        if amount is None:
            return {
                "computable": False,
                "reason": "违约金为比例约定但合同金额缺失，无法计算具体数额",
                "calc_steps": [ _step(f"违约金比例 = {penalty.rate:.2%}（基数：{penalty.base or '未载明'}）", None) ],
                "legal_note": "《民法典》第五百八十五条：违约金过分高于/低于实际损失可请求法院调整。",
            }
        penalty_value = amount * penalty.rate
        steps.append(_step(f"合同总金额 = {amount:,.2f} 元", amount))
        steps.append(
            _step(
                f"违约金 = {amount:,.2f} × {penalty.rate:.2%}（基数：{penalty.base or '合同总金额'}）",
                round(penalty_value, 2),
            )
        )
        summary = (
            f"违约方需支付违约金约 {_fmt(penalty_value)} 元"
            f"（合同总金额的 {penalty.rate:.2%}）。"
            "该金额低于实际损失可请求增加，过分高于损失（司法实践通常以 30% 为界）可请求酌减。"
        )
        penalty_out: float | None = round(penalty_value, 2)

    elif kind == "fixed" and penalty.rate is not None:
        penalty_out = round(penalty.rate, 2)
        steps.append(_step(f"违约金（固定金额约定）= {penalty_out:,.2f} 元", penalty_out))
        summary = f"合同约定固定违约金 {_fmt(penalty_out)} 元。"

    else:
        return {
            "computable": False,
            "reason": f"违约金为「{penalty.raw or kind}」形态，需人工核对计算方式（如按日计需约定期数）",
            "calc_steps": [ _step(f"违约金约定原文：{penalty.raw}", None) ],
            "legal_note": "《民法典》第五百八十五条：违约金过分高于/低于实际损失可请求法院调整。",
        }

    return {
        "computable": True,
        "params": {"breach_party": breach_party},
        "contract_amount": amount,
        "penalty_rate": penalty.rate,
        "penalty_base": penalty.base,
        "penalty_value": penalty_out,
        "calc_steps": steps,
        "summary": summary,
        "legal_note": "《民法典》第五百八十五条：约定违约金低于/过分高于损失的，可请求法院或仲裁机构调整。",
    }


SIMULATORS = {
    "price_fluctuation": simulate_price_fluctuation,
    "natural_disaster": simulate_natural_disaster,
    "party_breach": simulate_party_breach,
}

SCENARIO_LABELS = {
    "price_fluctuation": "价格波动",
    "natural_disaster": "自然灾害",
    "party_breach": "一方违约",
}
