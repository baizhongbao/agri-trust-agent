"""MCP 工具层上下文压缩与 doc_id 唯一性的回归测试。

两类真实缺陷的回归锁：

1. `check_standard` 原先直接 `_compact(result)`，而结果里体量巨大的 `results`
   排在 `required_clauses` / `compliance` 之前，4000 字上限会把关键结论整段截掉，
   使 Pi（主 Agent）看不到「缺了哪些必备条款 / 数值哪里不合规」。
2. `new_doc_id()` 原先只有秒级时间戳，同一秒上传两份合同会互相覆盖。
"""

from __future__ import annotations

import json
import time

from app.mcp import agri_server
from app.modules.contract_parser import storage

_PAD = "填充内容用于放大体积" * 12


def _fake_standard_result() -> dict:
    """构造一份体积接近真实 check_contract 返回的结果。"""
    match = {
        "standard_code": "GB/T 1354-2018",
        "standard_title": "大米",
        "clause_no": "5.2",
        "clause_title": "质量要求",
        "rule_strength": "recommended",
        "score": 0.9,
        "body": _PAD,
        "text": _PAD,
        "limits": [{"metric": "水分", "op": "<=", "value": 14.5}],
        "supersedes": [],
        "data_note": "",
    }
    return {
        "doc_id": "doc-test",
        "contract_title": "订单农业合同",
        "total_clauses": 20,
        "matched_clauses": 20,
        "coverage": 0.5,
        "clause_match_rate": 1.0,
        "unmatched_clauses": [],
        "results": [
            {
                "clause_index": i,
                "clause_title": f"第{i}条",
                "clause_excerpt": _PAD,
                "matches": [dict(match) for _ in range(3)],
            }
            for i in range(1, 21)
        ],
        "required_clauses": {
            "required_total": 11,
            "required_covered": 8,
            "missing_required": [
                {
                    "key": "force_majeure",
                    "name": "不可抗力与自然灾害免责",
                    "level": "required",
                    "risk": "high",
                    "advice": _PAD,
                    "source": "《订单农业合同规范指引》第十二条",
                }
            ],
            "missing_recommended": [],
            "risk_level": "中风险",
            "summary": "必备条款 11 项，已覆盖 8 项，缺失 3 项",
        },
        "compliance": {
            "total": 8,
            "compliant_count": 5,
            "violation_count": 3,
            "mandatory_violation_count": 1,
            "review_count": 0,
            "violations": [
                {
                    "metric": "水分",
                    "contract_metric": "水分",
                    "contract_value": 14.5,
                    "contract_unit": "%",
                    "standard_value": 13.5,
                    "standard_unit": "%",
                    "standard_op": "<=",
                    "standard_code": "GB/T 1354-2018",
                    "clause_no": "5.2",
                    "rule_strength": "mandatory",
                    "status": "violation",
                    "reason": _PAD,
                }
            ],
            "reviews": [],
            "timeliness": [],
            "summary": "可比对指标 8 项：一致 5 项、偏离依据 3 项",
        },
        "index": {"documents": 48},
        "disclaimer": "仅供参考",
    }


def test_check_standard_slim_fits_and_keeps_signals() -> None:
    """压缩后必须不触发 4000 字截断，且关键结论完整保留。"""
    raw = json.dumps(_fake_standard_result(), ensure_ascii=False, default=str)
    slim = agri_server._slim_standard_result(_fake_standard_result())
    out = agri_server._compact(slim)

    assert len(raw) > 4000  # 原始结果确实超预算（否则测试无意义）
    assert len(out) <= 4000
    assert not out.endswith("…")  # 未被截断 → 是合法 JSON

    payload = json.loads(out)
    assert payload["coverage"] == 0.5
    assert payload["required_clauses"]["missing_required"][0]["name"] == "不可抗力与自然灾害免责"
    assert payload["compliance"]["violation_count"] == 3
    assert payload["compliance"]["violations"][0]["metric"] == "水分"


def test_new_doc_id_unique_within_same_second() -> None:
    """同一秒内连续生成必须唯一（秒级时间戳会撞车、互相覆盖）。"""
    ids = [storage.new_doc_id() for _ in range(2000)]
    assert len(set(ids)) == len(ids)


def test_new_doc_id_lexical_order_matches_time_order() -> None:
    """时间戳在前的字典序必须等价于时间序（list_contracts 依赖倒排取最近）。"""
    first = storage.new_doc_id()
    time.sleep(0.003)
    second = storage.new_doc_id()
    assert first < second
