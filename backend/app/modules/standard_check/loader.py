"""标准库语料加载。

把 data/standards/*.json 摊平成"一条条款一个条目"，
并把标准号与标准名拼进检索文本——用户查询往往只说"水分"，
而条款原文里可能是"大米水分含量应符合"，把标准号一并放入能显著提升召回。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def standard_files() -> list[Path]:
    directory = settings.standards_path
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def load_items() -> list[dict[str, Any]]:
    """加载并摊平全部标准条款。"""
    items: list[dict[str, Any]] = []

    for path in standard_files():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("标准库文件读取失败 %s：%s", path.name, exc)
            continue

        for standard in payload.get("standards", []):
            code = str(standard.get("code", ""))
            title = str(standard.get("title", ""))
            category = str(standard.get("category", ""))

            for clause in standard.get("clauses", []):
                no = str(clause.get("no", ""))
                clause_title = str(clause.get("title", ""))
                body = str(clause.get("text", ""))
                if not body:
                    continue

                items.append(
                    {
                        "id": f"{code}|{no}|{clause_title}",
                        "standard_code": code,
                        "standard_title": title,
                        "category": category,
                        "clause_no": no,
                        "clause_title": clause_title,
                        "text": f"{code}《{title}》{no} {clause_title}：{body}",
                        "body": body,
                        # 结构化限值：供「合同值 vs 标准阈值」的数值比对使用。
                        # 定性要求的条款不带 limits，比对时自然跳过。
                        "limits": clause.get("limits") or [],
                        "source_file": path.name,
                    }
                )

    logger.info("标准库加载完成：%d 条条款，来自 %d 个文件", len(items), len(standard_files()))
    return items


def summarize_library() -> list[dict[str, Any]]:
    """按标准汇总，供前端展示标准库目录。"""
    grouped: dict[str, dict[str, Any]] = {}
    for item in load_items():
        key = item["standard_code"]
        entry = grouped.setdefault(
            key,
            {
                "standard_code": item["standard_code"],
                "standard_title": item["standard_title"],
                "category": item["category"],
                "clause_count": 0,
            },
        )
        entry["clause_count"] += 1
    return list(grouped.values())
