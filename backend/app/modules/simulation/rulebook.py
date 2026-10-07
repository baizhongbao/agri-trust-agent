"""裁判规则库：从提炼好的案例知识中检索可引用的裁判依据。

数据来源：data/knowledge/cases_summary.json
（由 scripts/extract_knowledge.py 用 LLM 从 50 份裁判文书提炼，经人工复核后使用）

与标准校验的分工：
    标准校验回答「合同约定是否符合标准」（事前审查）；
    裁判规则库回答「这种情形闹上法院会怎么判」（事后推演）。
    后者服务于履约模拟：每一条推演结论都要能引用真实判例，
    而不是模型编的"可能也许大概"。

检索策略：场景（scenario）优先 + 关键词匹配排序。
语料仅几十条，纯 Python 足够，不引入向量库依赖。
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# 与提炼脚本约定的场景枚举保持一致
SCENARIOS = (
    "价格波动",
    "自然灾害",
    "质量争议",
    "拖欠款项",
    "擅自处分",
    "主体不适格",
    "合同解除",
    "其他",
)

# 模拟情景 → 应检索的裁判场景（多对多）
SCENARIO_TO_QUERY_SCENARIOS: dict[str, tuple[str, ...]] = {
    "price_fluctuation": ("价格波动", "合同解除", "其他"),
    "natural_disaster": ("自然灾害", "质量争议"),
    "party_breach": ("拖欠款项", "擅自处分", "主体不适格", "合同解除"),
}

_RELEVANCE_ORDER = {"high": 0, "medium": 1, "low": 2}
_MAX_PER_SCENARIO = 3


def summary_path():
    return settings.path_of(settings.simulation_rules_path)


@lru_cache(maxsize=1)
def load_rules() -> tuple[dict[str, Any], ...]:
    """加载规则库（扁平化为 (案例, 规则) 元组）。文件缺失时退化为空库。"""
    path = summary_path()
    if not path.exists():
        logger.warning("裁判规则库不存在：%s（可运行 scripts/extract_knowledge.py 生成）", path)
        return ()

    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("裁判规则库读取失败：%s", exc)
        return ()

    rules: list[dict[str, Any]] = []
    for case in payload.get("cases", []):
        for rule in case.get("risk_rules", []):
            rules.append(
                {
                    "case_no": case.get("case_no", ""),
                    "title": case.get("title", ""),
                    "court": case.get("court", ""),
                    "category": case.get("category", ""),
                    "contract_type": case.get("contract_type", ""),
                    "holding": case.get("holding", ""),
                    "relevance": case.get("relevance", "low"),
                    "scenario": rule.get("scenario", "其他"),
                    "signal": rule.get("signal", ""),
                    "ruling": rule.get("ruling", ""),
                    "lesson": rule.get("lesson", ""),
                    "key_excerpt": case.get("key_excerpt", ""),
                }
            )
    logger.info("裁判规则库已加载：%d 条规则", len(rules))
    return tuple(rules)


def reload_rules() -> int:
    load_rules.cache_clear()
    return len(load_rules())


def _score(rule: dict[str, Any], keywords: list[str]) -> int:
    """简单可解释的关键词计分：命中一个关键词 +1。"""
    haystack = " ".join(
        str(rule.get(k, "")) for k in ("signal", "ruling", "lesson", "contract_type", "holding")
    )
    return sum(1 for kw in keywords if kw and kw in haystack)


def search_rules(
    scenario: str,
    keywords: list[str] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """按裁判场景检索规则，关键词参与排序，返回带匹配分的引用条目。"""
    rules = load_rules()
    matched = [r for r in rules if r["scenario"] == scenario]
    if not matched:
        return []

    keywords = keywords or []
    scored = sorted(
        ((r, _score(r, keywords)) for r in matched),
        key=lambda pair: (-pair[1], _RELEVANCE_ORDER.get(pair[0]["relevance"], 3)),
    )

    results: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    for rule, score in scored:
        if len(results) >= limit:
            break
        if rule["case_no"] in seen_cases:
            continue  # 同一案例只引一条，避免报告被单一判例刷屏
        seen_cases.add(rule["case_no"])
        results.append({**rule, "keyword_hits": score})
    return results


def cite_rules(simulation_scenario: str, keywords: list[str] | None = None) -> dict[str, Any]:
    """把某个模拟情景映射到裁判场景并检索引用。

    返回结构含 matched_scenarios（实际命中的场景），
    检索不到时引用列表为空——不编造，宁可少引。
    """
    query_scenarios = SCENARIO_TO_QUERY_SCENARIOS.get(simulation_scenario, ("其他",))
    citations: list[dict[str, Any]] = []
    for scenario in query_scenarios:
        hits = search_rules(scenario, keywords=keywords, limit=_MAX_PER_SCENARIO)
        for hit in hits:
            citations.append(
                {
                    "scenario": hit["scenario"],
                    "case_no": hit["case_no"],
                    "court": hit["court"],
                    "title": hit["title"],
                    "signal": hit["signal"],
                    "ruling": hit["ruling"],
                    "lesson": hit["lesson"],
                    "keyword_hits": hit["keyword_hits"],
                }
            )
    return {
        "matched_scenarios": list(query_scenarios),
        "total": len(citations),
        "citations": citations[: _MAX_PER_SCENARIO * 2],
    }
