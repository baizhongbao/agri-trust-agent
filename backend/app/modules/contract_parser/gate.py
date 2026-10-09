"""解析质量门禁：L1→L2 升级判定 与 L4 硬失败检查。

**这个模块的存在源于一次真实事故**：扫描件 `1000178611.jpg` 解析后
`parties` 为空，但系统既不报错也不产生任何 warning。下游企业核验拿到
空主体后**静默跳过** L1/L2/L3，返回一份 `summary` 全 0 的报告——
使用者只看到「pass/warning/fail 都是 0」，很容易读成「已核验、无风险」，
而真相是「一次工商查询都没发出」。

链路被拆成三个显式动作：

    L1（便宜：OCR + 规则抽取）
        │  needs_escalation() 命中触发条件
        ▼
    L2（昂贵：LLM 重解析）
        │  completeness() 择优 —— 只在更完整时才采纳，
        ▼  绝不用更差的结果覆盖更好的（mock 占位结构是典型反例）
    L4 evaluate() 硬失败门禁：必备字段仍缺失 → 结构化 gate + 显式 warning

设计原则沿用 AGENTS.md 第 4 节第 5 条：**失败必须可见**。
空结果比报错难排查十倍。

本模块刻意不 import `settings`——升级开关由 service 层决定，
这样门禁本身是纯函数，容易单测。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.modules.contract_parser.schema import (
    GATE_BLOCKED,
    GATE_DEGRADED,
    GATE_OK,
    GateFailure,
    ParseGate,
    StructuredContract,
)

logger = logging.getLogger(__name__)

# 缺失严重度
SEVERITY_BLOCKING = "blocking"
SEVERITY_DEGRADED = "degraded"

# 升级结果
ESCALATION_ADOPTED = "adopted"
ESCALATION_REJECTED = "rejected"
ESCALATION_UNAVAILABLE = "unavailable"
ESCALATION_SKIPPED = "skipped"

_OUTCOME_TEXT = {
    ESCALATION_ADOPTED: "已采纳 L2（LLM）结果",
    ESCALATION_REJECTED: "L2 结果未优于 L1，保留原结果",
    ESCALATION_UNAVAILABLE: "L2 不可用",
    ESCALATION_SKIPPED: "已跳过 L2",
}


@dataclass(frozen=True)
class RequiredItem:
    """一项必备解析结果。

    severity 决定缺失的后果：
      blocking —— 下游无法得出可信结论（如主体全缺，企业核验无从下手）
      degraded —— 下游可继续，但必须携带标注（如缺金额，模拟算不了数）
    """

    key: str
    label: str
    severity: str
    missing_detail: str


REQUIRED_ITEMS: tuple[RequiredItem, ...] = (
    RequiredItem(
        key="text",
        label="合同正文",
        severity=SEVERITY_BLOCKING,
        missing_detail="未抽取到任何文本（OCR 未启用或识别失败），结构化无从谈起",
    ),
    RequiredItem(
        key="parties",
        label="合同主体",
        severity=SEVERITY_BLOCKING,
        missing_detail="未识别到任何合同主体，企业核验（L1/L2/L3）无法执行",
    ),
    RequiredItem(
        key="amount",
        label="合同金额",
        severity=SEVERITY_DEGRADED,
        missing_detail="履约模拟的价格波动情景与违约金数额均无法计算",
    ),
    RequiredItem(
        key="sign_date",
        label="签订日期",
        severity=SEVERITY_DEGRADED,
        missing_detail="无法比对主体成立日期与签约时点，也无法推算履约窗口",
    ),
    RequiredItem(
        key="delivery_deadline",
        label="交货期限",
        severity=SEVERITY_DEGRADED,
        missing_detail="逾期交货风险无法推演",
    ),
    RequiredItem(
        key="title",
        label="合同名称",
        severity=SEVERITY_DEGRADED,
        missing_detail="无法确认文件类型与适用标准集",
    ),
)

# 升级触发所需的最少缺失关键字段数（金额/签订日期/交货期限）
_TRADE_TERM_KEYS = ("amount", "sign_date", "delivery_deadline")
_TRADE_TERM_MISSING_THRESHOLD = 2


def _present(contract: StructuredContract, key: str) -> bool:
    """某个必备项是否有值。"""
    if key == "text":
        return contract.char_count > 0 and bool((contract.raw_text_preview or "").strip())
    if key == "parties":
        return any(p.name.strip() for p in contract.parties)
    return bool((getattr(contract, key, "") or "").strip())


def completeness(contract: StructuredContract) -> tuple[int, int, int]:
    """结果完整度，用于在 L1 / L2 之间择优。

    排序优先级刻意把**主体**放在最前：主体是唯一会让下游整条链路
    失效的 blocking 项，主体识别不出来时，字段抽得再全也没用。
    """
    parties = sum(1 for p in contract.parties if p.name.strip())
    required_hits = sum(1 for item in REQUIRED_ITEMS if _present(contract, item.key))
    field_hits = sum(1 for f in contract.fields if f.value)
    return (parties, required_hits, field_hits)


def evaluate(
    contract: StructuredContract,
    *,
    escalated: bool = False,
    escalation_reason: str = "",
    escalation_outcome: str = "",
    escalation_note: str = "",
) -> ParseGate:
    """执行 L4 门禁检查，产出结构化结论。"""
    failures = [
        GateFailure(
            key=item.key,
            label=item.label,
            severity=item.severity,
            detail=item.missing_detail,
        )
        for item in REQUIRED_ITEMS
        if not _present(contract, item.key)
    ]

    if any(f.severity == SEVERITY_BLOCKING for f in failures):
        level = GATE_BLOCKED
    elif failures:
        level = GATE_DEGRADED
    else:
        level = GATE_OK

    if level == GATE_OK:
        summary = "解析结果完备：必备字段全部齐备，下游模块可正常推理"
    else:
        head = "解析结果不可用" if level == GATE_BLOCKED else "解析结果不完整"
        summary = f"{head}：缺失 {'、'.join(f.label for f in failures)}"

    if escalated:
        summary += f"；{_OUTCOME_TEXT.get(escalation_outcome, '已尝试 L2 升级')}"

    return ParseGate(
        level=level,
        failures=failures,
        summary=summary,
        escalated=escalated,
        escalation_reason=escalation_reason,
        escalation_outcome=escalation_outcome,
        escalation_note=escalation_note,
    )


def needs_escalation(contract: StructuredContract) -> tuple[bool, str]:
    """判断是否应把 L1 结果升级到 L2 重解析。

    触发条件是「宁可多花一次调用，也不要静默丢字段」：
      1. 主体全缺 —— 下游整条链路会失效
      2. 文档经 OCR 识别（图片 / 扫描件）—— 版面含表格、印章、手写，
         规则抽取最脆弱的场景，正是本项目踩坑的那类文件
      3. 关键交易要素大面积缺失 —— 规则大概率没匹配上真实表述

    没有文本时不升级：L2 的输入也是文本，无米下锅。
    """
    if not _present(contract, "text"):
        return False, "未抽取到文本，L2 重解析同样无输入"

    reasons: list[str] = []
    if not _present(contract, "parties"):
        reasons.append("未识别到任何合同主体")
    if contract.used_ocr:
        reasons.append("文档经 OCR 识别（图片/扫描件），含表格与印章，规则抽取易漏")
    missing_terms = [k for k in _TRADE_TERM_KEYS if not _present(contract, k)]
    if len(missing_terms) >= _TRADE_TERM_MISSING_THRESHOLD:
        labels = "、".join(
            item.label for item in REQUIRED_ITEMS if item.key in missing_terms
        )
        reasons.append(f"关键交易要素大面积缺失（{labels}）")

    return (True, "；".join(reasons)) if reasons else (False, "")


def choose_better(
    l1: StructuredContract,
    l2: StructuredContract,
) -> tuple[StructuredContract, str, str]:
    """在 L1 / L2 结果间择优。

    返回 (采用的结果, outcome, note)。

    **绝不用更差的结果覆盖更好的**：`LLM_PROVIDER=mock` 时 L2 返回的是
    占位空壳，直接采纳会把一份本来可用的解析结果清空。
    """
    l1_score, l2_score = completeness(l1), completeness(l2)
    if l2_score > l1_score:
        return (
            l2,
            ESCALATION_ADOPTED,
            f"L2 结果更完整（主体 {l2_score[0]} vs {l1_score[0]}，"
            f"必备项 {l2_score[1]} vs {l1_score[1]}），已采用",
        )
    return (
        l1,
        ESCALATION_REJECTED,
        f"L2 结果未优于 L1（主体 {l2_score[0]} vs {l1_score[0]}，"
        f"必备项 {l2_score[1]} vs {l1_score[1]}），保留 L1 结果",
    )


def warning_line(gate: ParseGate) -> str:
    """把门禁结论压成一行 warning，让既有消费者（前端 / 冒烟测试）也能看见。

    比 gate.summary 多写两件事：**升级的触发原因**与**下游该怎么做**——
    只说"缺字段"而不说后果，很容易被当成例行提示跳过。
    """
    line = f"[门禁/{gate.level}] {gate.summary}"
    if gate.escalated and gate.escalation_reason:
        line += f"（L1→L2 升级触发：{gate.escalation_reason}）"
    if gate.level == GATE_BLOCKED:
        line += "　下游企业核验 / 履约模拟的结论不可信，须先修复解析或人工补录主体"
    elif gate.level == GATE_DEGRADED:
        line += "　下游结论必须附带该缺失标注，不得当作完整结论使用"
    return line
