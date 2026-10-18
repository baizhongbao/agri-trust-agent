"""履约模拟服务：数值计算 + 裁判规则引用 + LLM 定性分析。

职责分工（铁律「数值不交给 LLM」）：
    calculator  算数 —— 输入 facts（带 evidence），输出公式化计算步骤
    rulebook    找依据 —— 从真实判例中检索可引用的裁判规则
    LLM         说人话 —— 把数字与判例组织成风险解释，禁止自行计算

mock LLM 的降级策略：定性分析退化为「计算摘要 + 引用判例列表」的模板拼接，
保证无凭证时整条链路依然可用、可演示。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.providers.base import LLMProvider
from app.core.providers.registry import get_llm_provider
from app.modules.contract_parser import service as contract_service
from app.modules.simulation import calculator, rulebook
from app.modules.simulation.schema import Citation, ScenarioResult, SimulationReport

logger = logging.getLogger(__name__)

_DISCLAIMER = (
    "推演结果由规则计算与判例检索自动生成：数值部分可按 calc_steps 复核；"
    "判例引用来自公开裁判文书的知识提炼（data/knowledge/cases_summary.json，经脚本提炼），"
    "仅供风险提示，不构成法律意见；正式决策请咨询专业律师并以裁判文书原文为准。"
)

_ANALYSIS_SYSTEM = """你是订单农业合同风险分析师。你会收到三部分材料：
1. 一份合同的履约模拟情景（含已由程序精确计算好的数值与计算步骤）
2. 从真实裁判文书中检索到的可引用判例
3. 合同的结构化事实摘要

你的任务：写一段 150~250 字的定性风险分析，说明该情景下双方的风险点与应对建议。
铁律：
- 数值一律照抄材料里的计算结果，禁止自行计算或改写数字
- 引用判例时注明案号
- 不确定的表述留给人工（如"需结合不可抗力条款具体判断"）
- 只输出分析正文，不要任何前后缀、不要 markdown 标题"""


def _facts_brief(contract) -> str:
    facts = contract.facts
    lines = []
    if facts.amount.value is not None:
        lines.append(f"合同金额：{facts.amount.value:,.2f} 元")
    if facts.quantity.value is not None:
        lines.append(f"标的数量：{facts.quantity.value} {facts.quantity.unit}")
    if facts.penalty.rate is not None:
        lines.append(f"违约金：{facts.penalty.rate:.2%}（基数：{facts.penalty.base or '未载明'}）")
    if facts.sign_date.kind == "absolute":
        lines.append(f"签订日期：{facts.sign_date.start}")
    if facts.delivery.start:
        lines.append(f"交货期：{facts.delivery.start} ~ {facts.delivery.end or facts.delivery.start}")
    if facts.quality_metrics:
        metrics = "、".join(f"{m.name}{m.op}{m.value}{m.unit}" for m in facts.quality_metrics)
        lines.append(f"质量指标：{metrics}")
    return "\n".join(lines) or "（合同事实抽取为空）"


def _mock_analysis(scenario: ScenarioResult) -> str:
    """无 LLM 凭证时的模板拼接：保证链路可用，并明确标注非模型输出。"""
    parts = [f"【模板分析（未接入真实大模型）】{scenario.summary}"]
    if scenario.citations:
        parts.append("相关判例提示：")
        for citation in scenario.citations:
            parts.append(f"- {citation.case_no}（{citation.court}）：{citation.ruling[:100]}…")
    if scenario.legal_note:
        parts.append(f"法律依据：{scenario.legal_note}")
    return "\n".join(parts)


def _generate_analysis(
    llm: LLMProvider,
    scenario: ScenarioResult,
    contract,
) -> tuple[str, str]:
    """生成定性分析，返回 (分析文本, provider 名)。失败时降级为模板拼接。"""
    if llm.name == "mock":
        return _mock_analysis(scenario), "mock"

    citations_text = "\n".join(
        f"- {c.case_no}（{c.court}）信号：{c.signal}\n  裁判：{c.ruling}"
        for c in scenario.citations
    ) or "（未检索到直接相关判例）"

    prompt = (
        f"【模拟情景】{scenario.label}\n"
        f"【计算结果】{scenario.summary}\n"
        f"【计算步骤】{json.dumps(scenario.calc_steps, ensure_ascii=False)}\n"
        f"【可引用判例】\n{citations_text}\n"
        f"【合同事实】\n{_facts_brief(contract)}"
    )
    try:
        result = llm.complete(prompt, system=_ANALYSIS_SYSTEM)
        return result.content.strip(), llm.name
    except Exception as exc:  # 未就绪 / 网络 / 格式等一切故障都降级为模板
        logger.warning("定性分析生成失败，降级为模板：%s", exc)
        return _mock_analysis(scenario), "mock-fallback"


def run_scenario(
    contract,
    scenario_key: str,
    params: dict[str, Any],
    llm: LLMProvider | None = None,
) -> ScenarioResult:
    """执行单个情景：计算 → 引用 → 定性分析。"""
    if llm is None:
        llm = get_llm_provider()

    # 1. 数值计算（纯 Python）
    simulator = calculator.SIMULATORS[scenario_key]
    if scenario_key == "price_fluctuation":
        calc = simulator(contract.facts, params.get("price_change_pct", 0.0))
    elif scenario_key == "natural_disaster":
        calc = simulator(contract.facts, params.get("loss_ratio_pct", 0.0))
    else:
        calc = simulator(contract.facts, params.get("breach_party", "unspecified"))

    # 2. 裁判规则引用（关键词取合同事实，提高相关性）
    keywords = [contract.title, *(_facts_brief(contract).splitlines())]
    keywords = [k[:30] for k in keywords if k]
    cited = rulebook.cite_rules(scenario_key, keywords=keywords)

    # 3. 组装
    result = ScenarioResult(
        scenario=scenario_key,
        label=calculator.SCENARIO_LABELS.get(scenario_key, scenario_key),
        computable=calc.get("computable", False),
        reason=calc.get("reason", ""),
        params=calc.get("params", {}),
        calc_steps=calc.get("calc_steps", []),
        checks=calc.get("checks", []),
        summary=calc.get("summary", ""),
        legal_note=calc.get("legal_note", ""),
        citations=[Citation(**c) for c in cited.get("citations", [])],
    )

    # 4. LLM 定性分析（可降级）
    if result.computable:
        analysis, provider = _generate_analysis(llm, result, contract)
        result.analysis = analysis
        result.analysis_provider = provider
    else:
        result.analysis = result.reason
        result.analysis_provider = "n/a"

    # 数值字段提升到顶层便于前端展示
    for key in (
        "contract_amount",
        "market_value",
        "deviation",
        "breach_incentive_party",
        "breach_incentive_value",
        "contract_quantity",
        "deliverable_quantity",
        "shortfall_quantity",
        "loss_amount",
        "penalty_rate",
        "penalty_base",
        "penalty_value",
        "tiers",
    ):
        if key in calc:
            result.params[key] = calc[key]

    return result


def simulate(
    doc_id: str,
    scenarios: list[str] | None = None,
    params: dict[str, Any] | None = None,
    llm: LLMProvider | None = None,
) -> SimulationReport | None:
    """对一份合同执行履约模拟。scenarios 缺省跑全部三情景。"""
    contract = contract_service.get_contract(doc_id)
    if contract is None:
        return None

    scenario_keys = scenarios or list(calculator.SIMULATORS)
    unknown = [s for s in scenario_keys if s not in calculator.SIMULATORS]
    if unknown:
        raise ValueError(f"未知的模拟情景：{unknown}，可选 {list(calculator.SIMULATORS)}")

    params = params or {}
    results = [
        run_scenario(contract, key, params.get(key, {}), llm=llm)
        for key in scenario_keys
    ]

    return SimulationReport(
        doc_id=doc_id,
        contract_title=contract.title,
        notice=_skipped_notice(contract, results),
        scenarios=results,
        rulebook_total=len(rulebook.load_rules()),
        disclaimer=_DISCLAIMER,
    )


def _skipped_notice(contract, results: list[ScenarioResult]) -> str:
    """情景算不出数值时的显式说明。

    `computable: false` 藏在每个 scenario 里，报告级没提示的话，
    前端很容易把一张空表展示成“无风险”（L4 门禁的下游半段）。
    """
    blocked = [r for r in results if not r.computable]
    if not blocked:
        return ""
    labels = "、".join(r.label or r.scenario for r in blocked)
    reason = blocked[0].reason or "合同事实缺失"
    note = f"下列情景未能计算：{labels}。原因：{reason}。"
    if contract.gate.level != "ok":
        note += f"合同解析门禁：{contract.gate.summary}。"
    note += "此处为空表示『算不了』，不表示『无风险』。"
    return note
