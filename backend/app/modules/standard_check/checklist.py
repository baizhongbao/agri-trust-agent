"""必备条款清单与覆盖检测。

思路来源：
    CUAD（Contract Understanding Atticus Dataset）的 41 类律师标注条款体系。
    按「保留通用 / 裁掉美国商事特有 / 补充订单农业特有」三步裁剪，
    收敛到 18 项（11 项必备 + 7 项建议）——清单越长，缺失检测的噪音越大。
    必备条款缺失是"必须补"，建议条款缺失只是"可以考虑补"，两者分开报告。

与「标准条款匹配」的分工：
    匹配回答的是"这条合同条款像哪条标准"（相似度）；
    覆盖检测回答的是"该有的条款，这份合同有没有"（判定）。
    后者才是"校验"，也才是能给出结论的那一半。

为什么用关键词而不是纯语义判定：
    关键词判定可解释——每一项都会回传命中的条款序号与原文片段，人能复核。
    纯语义判断更"聪明"，但给不出可复核的依据，
    这与本项目「抽取值必须带 evidence」的原则相悖。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)

CHECKLIST_FILENAME = "required_clauses.json"
_EXCERPT_CHARS = 120

_FALLBACK_WEIGHTS: dict[str, dict[str, int]] = {
    "required": {"high": 15, "medium": 8, "low": 4},
    "recommended": {"high": 6, "medium": 4, "low": 2},
}
_FALLBACK_LEVELS: dict[str, int] = {"low_risk_min": 80, "medium_risk_min": 55}


class RequiredClause(BaseModel):
    """一条必备 / 建议条款的定义。"""

    key: str
    name: str
    level: str = "required"  # required | recommended
    risk: str = "medium"  # high | medium | low
    keywords: list[str] = Field(default_factory=list)
    advice: str = ""
    source: str = ""


@dataclass(frozen=True)
class Checklist:
    """清单本体与评分配置。"""

    rules: tuple[RequiredClause, ...] = ()
    weights: dict[str, dict[str, int]] = field(default_factory=lambda: _FALLBACK_WEIGHTS)
    levels: dict[str, int] = field(default_factory=lambda: _FALLBACK_LEVELS)


def checklist_file() -> Path:
    return settings.standards_path / CHECKLIST_FILENAME


@lru_cache(maxsize=1)
def load_checklist() -> Checklist:
    """加载清单。文件缺失或损坏时退化为空清单，不让整条链路挂掉。"""
    path = checklist_file()
    if not path.exists():
        logger.warning("必备条款清单不存在：%s", path)
        return Checklist()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("必备条款清单读取失败 %s：%s", path.name, exc)
        return Checklist()

    rules: list[RequiredClause] = []
    for group in ("required_clauses", "recommended_clauses"):
        for item in payload.get(group) or []:
            try:
                rules.append(RequiredClause.model_validate(item))
            except Exception as exc:  # noqa: BLE001 —— 单条非法不应影响整份清单
                logger.warning("条款定义非法，已跳过：%s", exc)

    config = payload.get("risk_weights") or {}
    weights = {
        "required": {**_FALLBACK_WEIGHTS["required"], **(config.get("required") or {})},
        "recommended": {
            **_FALLBACK_WEIGHTS["recommended"],
            **(config.get("recommended") or {}),
        },
    }
    levels = {**_FALLBACK_LEVELS, **(config.get("levels") or {})}

    logger.info("必备条款清单加载完成：%d 项", len(rules))
    return Checklist(rules=tuple(rules), weights=weights, levels=levels)


def _excerpt(text: str, limit: int = _EXCERPT_CHARS) -> str:
    compact = " ".join((text or "").split())
    return compact[:limit] + ("…" if len(compact) > limit else "")


def _locate(clauses: list[Any], keywords: list[str]) -> tuple[int, str, str, str] | None:
    """在合同条款里定位第一个命中的关键词。

    按合同条款顺序查找，返回最先出现的那一处，
    这样报告里的条款序号与合同的阅读顺序一致，便于人工核对。
    """
    for clause in clauses:
        content = getattr(clause, "content", "") or ""
        for keyword in keywords:
            if keyword and keyword in content:
                return (
                    getattr(clause, "index", 0),
                    getattr(clause, "title", "") or "",
                    keyword,
                    _excerpt(content),
                )
    return None


def _risk_level(score: int, levels: dict[str, int]) -> str:
    if score >= levels.get("low_risk_min", 80):
        return "低风险"
    if score >= levels.get("medium_risk_min", 55):
        return "中风险"
    return "高风险"


def check_coverage(contract: Any) -> dict[str, Any]:
    """逐项检测合同是否覆盖了必备条款。

    返回结构刻意区分 required / recommended：
    必备条款缺失是"必须补"，建议条款缺失只是"可以考虑补"，
    混在一起会淹没真正要紧的问题。
    """
    checklist = load_checklist()
    clauses = list(getattr(contract, "clauses", []) or [])

    items: list[dict[str, Any]] = []
    for rule in checklist.rules:
        hit = _locate(clauses, rule.keywords)
        items.append(
            {
                "key": rule.key,
                "name": rule.name,
                "level": rule.level,
                "risk": rule.risk,
                "status": "covered" if hit else "missing",
                "clause_index": hit[0] if hit else None,
                "clause_title": hit[1] if hit else "",
                "matched_keyword": hit[2] if hit else "",
                "evidence": hit[3] if hit else "",
                "advice": "" if hit else rule.advice,
                "source": rule.source,
            }
        )

    missing_required = [
        item for item in items if item["status"] == "missing" and item["level"] == "required"
    ]
    missing_recommended = [
        item
        for item in items
        if item["status"] == "missing" and item["level"] == "recommended"
    ]
    required_items = [item for item in items if item["level"] == "required"]
    covered_required = len(required_items) - len(missing_required)

    # 风险分：从满分 100 起，按缺失项的等级与权重扣分
    penalty = sum(
        checklist.weights.get(item["level"], {}).get(item["risk"], 0)
        for item in missing_required + missing_recommended
    )
    score = max(0, 100 - penalty)

    return {
        "total": len(items),
        "covered_count": sum(1 for item in items if item["status"] == "covered"),
        "required_total": len(required_items),
        "required_covered": covered_required,
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "items": items,
        "risk_score": score,
        "risk_level": _risk_level(score, checklist.levels),
        "summary": (
            f"必备条款 {len(required_items)} 项，已覆盖 {covered_required} 项，"
            f"缺失 {len(missing_required)} 项；建议条款缺失 {len(missing_recommended)} 项"
        ),
        "checklist_source": "CUAD 条款体系裁剪 + 订单农业补充",
        "disclaimer": (
            "缺失判定基于关键词匹配，仅提示「值得复核」而非「一定违法」；"
            "某条款是否为必需，仍需结合交易实际情况与专业意见判断。"
        ),
    }
