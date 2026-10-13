"""MCP（Model Context Protocol）服务端。

把项目四大模块 + 联网搜索包装成 MCP tools，供 Pi（或任何 MCP 客户端）作为
「主 Agent」自主调度：

    list_contracts       列出已解析合同，拿到 doc_id
    get_contract         读取该 doc_id 的结构化字段 + facts
    check_standard       标准校验（必备条款 + 数值合规）
    verify_enterprise    企业核验（L1+L2+L3）
    simulate             履约模拟（价格 / 灾害 / 违约）
    overall_verdict      汇总判定：串起四模块，给出总体可信度等级
    export_report        导出可信性评估报告（pdf / docx）到 data/reports/
    search_web           联网搜索（Tavily，Agent 加深时取外部证据）

无上传入口：文件解析只能走 REST /api/v1/contracts/parse 或预先放好样本，
Agent 先 list_contracts 取 doc_id，再串后续工具。

运行：python backend/app/mcp/agri_server.py
Pi 接入：pi mcp add -l agri -- python backend/app/mcp/agri_server.py
（stdio 传输，Pi 的默认 MCP 接法）
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.providers.base import SearchResult, SearchResultItem
from app.core.providers.registry import get_search_provider
from app.modules.contract_parser import service as contract_service
from app.modules.enterprise_verify import service as enterprise_service
from app.modules.simulation import service as simulate_service
from app.modules.standard_check import service as standard_service
from app.modules.verdict import exporter as report_exporter
from app.modules.verdict import service as verdict_service

mcp = FastMCP("agri-trust-agent")


def _compact(obj: Any) -> str:
    """把大结果压缩成可控上下文。"""
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return text[:4000] + ("…" if len(text) > 4000 else "")


def _prioritized(data: dict, first: tuple[str, ...]) -> dict:
    """把关键字段提到最前。

    `_compact` 只保前 4000 字符，JSON 输出又按插入顺序——
    若不提权，`gate` / `warnings` 这类“必须先被看到的失败信号”
    会被 `clauses` 正文挤掉（实际就踩过这个坑）。
    """
    out = {key: data.pop(key) for key in first if key in data}
    out.update(data)
    return out


def _shorten_clauses(data: dict, limit: int = 160) -> dict:
    """截短条款正文，把上下文留给结构化字段。

    条款全文由 check_standard 直接读落盘文件，不依赖本工具的返回值。
    """
    for clause in data.get("clauses", []):
        content = clause.get("content") or ""
        if len(content) > limit:
            clause["content"] = content[:limit] + "…"
    return data


# check_standard 的压缩参数。实测结论体（required_clauses + compliance）本身就有
# 1.3 万字符，远超 _compact 的 4000 字上限，不压缩会让 compliance 整段丢失。
_STD_RESULT_CLAUSE_LIMIT = 3
_STD_MATCHES_PER_CLAUSE = 1
_STD_BODY_CHARS = 40
_STD_ADVICE_CHARS = 60
_STD_REASON_CHARS = 160


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text[:limit] + ("…" if len(text) > limit else "")


def _slim_standard_result(data: dict) -> dict:
    """压缩标准校验结果，并保证 coverage / required_clauses / compliance 置于最前。

    与 `_prioritized` 的区别：check_standard 的结果不仅顺序不对，
    体量本身也超出 4000 字预算（实测 1.3 万+），仅提权仍会把 compliance 截掉，
    因此这里做结构性裁剪：

    - 判定信号完整保留：缺失必备条款、违约/待核对项、时效提示；
    - 只裁剪"已覆盖 / 已合规"的明细、命中正文与条款摘要；
    - `index`（检索库状态）属运维元信息，不参与可信性判断，直接省略。
    """
    req = data.get("required_clauses") or {}
    comp = data.get("compliance") or {}

    def slim_missing(item: dict) -> dict:
        return {
            "key": item.get("key"),
            "name": item.get("name"),
            "level": item.get("level"),
            "risk": item.get("risk"),
            "advice": _clip(item.get("advice"), _STD_ADVICE_CHARS),
            "source": item.get("source"),
        }

    def slim_compliance_item(item: dict) -> dict:
        return {
            "metric": item.get("metric"),
            "contract_metric": item.get("contract_metric"),
            "contract_value": item.get("contract_value"),
            "contract_unit": item.get("contract_unit"),
            "standard_value": item.get("standard_value"),
            "standard_unit": item.get("standard_unit"),
            "standard_op": item.get("standard_op"),
            "standard_code": item.get("standard_code"),
            "clause_no": item.get("clause_no"),
            "rule_strength": item.get("rule_strength"),
            "status": item.get("status"),
            "reason": _clip(item.get("reason"), _STD_REASON_CHARS),
        }

    results = []
    for entry in (data.get("results") or [])[:_STD_RESULT_CLAUSE_LIMIT]:
        matches = [
            {
                "standard_code": match.get("standard_code"),
                "standard_title": match.get("standard_title"),
                "clause_no": match.get("clause_no"),
                "clause_title": match.get("clause_title"),
                "rule_strength": match.get("rule_strength"),
                "score": match.get("score"),
                "body": _clip(match.get("body") or match.get("text"), _STD_BODY_CHARS),
            }
            for match in (entry.get("matches") or [])[:_STD_MATCHES_PER_CLAUSE]
        ]
        results.append(
            {
                "clause_index": entry.get("clause_index"),
                "clause_title": entry.get("clause_title"),
                "matches": matches,
            }
        )

    return {
        "doc_id": data.get("doc_id"),
        "contract_title": data.get("contract_title"),
        "coverage": data.get("coverage"),
        "required_clauses": {
            "required_total": req.get("required_total"),
            "required_covered": req.get("required_covered"),
            "missing_required": [slim_missing(i) for i in req.get("missing_required") or []],
            "missing_recommended": [slim_missing(i) for i in req.get("missing_recommended") or []],
            "risk_level": req.get("risk_level"),
            "summary": req.get("summary"),
        },
        "compliance": {
            "total": comp.get("total"),
            "compliant_count": comp.get("compliant_count"),
            "violation_count": comp.get("violation_count"),
            "mandatory_violation_count": comp.get("mandatory_violation_count"),
            "review_count": comp.get("review_count"),
            "violations": [slim_compliance_item(i) for i in comp.get("violations") or []],
            "reviews": [slim_compliance_item(i) for i in comp.get("reviews") or []],
            "timeliness": comp.get("timeliness") or [],
            "summary": comp.get("summary"),
        },
        "total_clauses": data.get("total_clauses"),
        "matched_clauses": data.get("matched_clauses"),
        "clause_match_rate": data.get("clause_match_rate"),
        "unmatched_clauses": data.get("unmatched_clauses") or [],
        "results": results,
        "disclaimer": data.get("disclaimer"),
    }


# ---------------- 搜索（Tavily） ----------------

@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """联网搜索网页（Tavily），返回标题/URL/摘要。用于获取企业违法记录、订单农业政策、判例等外部证据。"""
    provider = get_search_provider()
    if not provider.is_ready():
        return json.dumps(
            {"ok": False, "note": "搜索未就绪：请配置 TAVILY_API_KEY 且 SEARCH_PROVIDER=tavily", "items": []},
            ensure_ascii=False,
        )
    result = provider.search(query, max_results=max_results)
    items = [
        {"title": it.title, "url": it.url, "snippet": it.snippet}
        for it in result.items
    ]
    return _compact({"ok": True, "provider": provider.name, "query": query, "items": items, "note": result.note})


# ---------------- 合同解析 ----------------

@mcp.tool()
def list_contracts(limit: int = 10) -> str:
    """列出已解析合同（含 doc_id / 文件名 / 标题）。"""
    contracts = contract_service.list_contracts(limit=limit)
    return _compact(contracts)


@mcp.tool()
def get_contract(doc_id: str) -> str:
    """按 doc_id 读取单份已解析合同（gate 解析门禁 + warnings + fields + facts + clauses）。

    请**先看 gate**：level=blocked 表示主体缺失、下游结论不可信；
    level=degraded 表示有必备字段缺失，各模块的结论需附带该标注。
    """
    contract = contract_service.get_contract(doc_id)
    if contract is None:
        return json.dumps({"ok": False, "note": f"未找到合同 {doc_id}"}, ensure_ascii=False)
    data = _shorten_clauses(contract.model_dump())
    return _compact(_prioritized(data, ("doc_id", "gate", "warnings", "parties")))


@mcp.tool()
def check_standard(doc_id: str, top_k: int = 3, clause_limit: int = 20) -> str:
    """标准校验：必备条款覆盖 + 数值合规比对，返回命中标准与依据。"""
    result = standard_service.check_contract(doc_id, top_k=top_k, clause_limit=clause_limit)
    if result is None:
        return json.dumps({"ok": False, "note": f"未找到合同 {doc_id}"}, ensure_ascii=False)
    return _compact(_slim_standard_result(result))


@mcp.tool()
def verify_enterprise(doc_id: str) -> str:
    """企业核验：L1 信用代码校验位 + L2 工商查询 + L3 交叉校验，返回每个主体判定。

    **先看 notice**：非空表示核验未完整执行（例如合同没抽出主体，一次查询都没发出），
    此时 summary 全 0 是『没查』而不是『没问题』。
    """
    report = enterprise_service.verify_contract(doc_id)
    if report is None:
        return json.dumps({"ok": False, "note": f"未找到合同 {doc_id}"}, ensure_ascii=False)
    return _compact(_prioritized(report.model_dump(), ("doc_id", "notice", "summary")))


@mcp.tool()
def simulate(doc_id: str, scenarios: str | None = None, price_change_pct: float | None = None,
             loss_ratio_pct: float | None = None, breach_party: str = "unspecified") -> str:
    """履约模拟：三情景（价格波动/自然灾害/一方违约），返回数值计算步骤 + 判例引用 + 风险分析。

    **先看 notice 与每个情景的 computable**：notice 非空或 computable=false 表示
    算不了数（如合同未载明金额），空结果不等于无风险。
    """
    scenario_keys = scenarios.split(",") if scenarios else None
    params: dict[str, dict[str, Any]] = {}
    if price_change_pct is not None:
        params["price_fluctuation"] = {"price_change_pct": price_change_pct}
    if loss_ratio_pct is not None:
        params["natural_disaster"] = {"loss_ratio_pct": loss_ratio_pct}
    # breach_party 独立追加——不能挂在 if/elif 上，否则「只传 breach_party」时
    # 会被前面的分支吞掉，违约方参数静默失效。
    if breach_party != "unspecified":
        params["party_breach"] = {"breach_party": breach_party}
    try:
        report = simulate_service.simulate(
            doc_id, scenarios=scenario_keys, params=params
        )
    except ValueError as exc:
        return json.dumps({"ok": False, "note": str(exc)}, ensure_ascii=False)
    if report is None:
        return json.dumps({"ok": False, "note": f"未找到合同 {doc_id}"}, ensure_ascii=False)
    return _compact(_prioritized(report.model_dump(), ("doc_id", "notice")))


@mcp.tool()
def overall_verdict(doc_id: str) -> str:
    """汇总判定：串起合同解析/标准校验/企业核验/履约模拟，给出总体可信度等级 + 否决项 + 各维度分项。

    **先看 grade 与 blockers**：grade=不可评表示信息不完备，无法下结论；
    blockers 非空表示存在客观硬伤（解析阻断/主体 fail/违反强制性依据），此时不要采信分项高分。
    """
    verdict = verdict_service.run_verdict(doc_id)
    if verdict is None:
        return json.dumps({"ok": False, "note": f"未找到合同 {doc_id}"}, ensure_ascii=False)
    data = verdict.model_dump()
    return _compact(
        _prioritized(data, ("doc_id", "grade", "grade_reason", "blockers", "notices", "missing_dimensions"))
    )


@mcp.tool()
def export_report(doc_id: str, format: str = "pdf") -> str:
    """生成可信性评估报告文件（pdf / docx），保存到 data/reports/ 并返回可访问路径。"""
    fmt = (format or "pdf").lower()
    if fmt not in ("pdf", "docx"):
        return json.dumps({"ok": False, "note": "format 仅支持 pdf / docx"}, ensure_ascii=False)
    result = report_exporter.export_to_file(doc_id, fmt=fmt)
    if result is None:
        return json.dumps({"ok": False, "note": f"未找到合同 {doc_id}"}, ensure_ascii=False)
    path, size = result
    return json.dumps(
        {"ok": True, "format": fmt, "path": str(path), "bytes": size}, ensure_ascii=False
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")