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
        │  choose_better() **字段级仲裁并合并**：
        ▼  逐项定状态（一致 / 仅规则 / 仅大模型 / 冲突），绝不整份丢弃一侧
    L4 evaluate() 硬失败门禁：必备字段仍缺失 或 必备项双源冲突
        → 结构化 gate + 显式 warning

关于"冲突"这一状态，见 `schema.py` 里 `ARB_*` 的说明：两个**失败模式独立**的
抽取器给出同一个值时，"一致"才算得上证据；给出不同值时，系统**不判断谁对**，
只把它标成必须人工核对——这与本模块"失败必须可见"是同一条原则的两个面。

设计原则沿用 AGENTS.md 第 4 节第 5 条：**失败必须可见**。
空结果比报错难排查十倍。

本模块刻意不 import `settings`——升级开关由 service 层决定，
这样门禁本身是纯函数，容易单测。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.modules.contract_parser.schema import (
    ARB_AGREED,
    ARB_CONFLICT,
    ARB_L1_ONLY,
    ARB_L2_ONLY,
    ARB_MISSING,
    ARB_SINGLE,
    GATE_BLOCKED,
    GATE_DEGRADED,
    GATE_OK,
    ContractField,
    FieldArbitration,
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
ESCALATION_MERGED = "merged"
ESCALATION_REJECTED = "rejected"
ESCALATION_UNAVAILABLE = "unavailable"
ESCALATION_SKIPPED = "skipped"

_OUTCOME_TEXT = {
    ESCALATION_ADOPTED: "已用 L2 补充缺失字段",
    ESCALATION_MERGED: "已按字段合并（L2 未补充新字段，但提供了交叉验证）",
    ESCALATION_REJECTED: "L2 未提供可用信息，保留 L1 结果",
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
    """结果完整度 (主体数, 必备项命中, 字段命中)。

    排序优先级刻意把**主体**放在最前：主体是唯一会让下游整条链路
    失效的 blocking 项，主体识别不出来时，字段抽得再全也没用。

    注意：这**不再**是 L1 / L2 的采纳依据（原来是整份二选一，会连带丢弃
    另一侧唯一抽对的字段）。现在仅用于诊断与回归测试——`choose_better()`
    走的是字段级仲裁。
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
    """执行 L4 门禁检查，产出结构化结论。

    除了"必备项缺失"，这里还处理第二类失败：**值抽到了但两个抽取器不一致**
    （`FieldArbitration.status == conflict`）。这属于"必须人工核对"，
    不是"没抽到"——两者的处置完全不同，所以 `disagreements` 与 `failures` 分开存。

    降级规则：冲突落在**下游直接依赖的键**（金额 / 签订日期 / 交货期限 / 合同名称 /
    主体）上时，把 ok 压成 degraded；落在其余展示字段（合同编号、质量标准、付款方式、
    违约责任）上只留痕、不降级——否则任何一处措辞差异都会把整份合同判成"不完整"。
    """
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

    disagreements = [
        item for item in (contract.arbitration or []) if item.status == ARB_CONFLICT
    ]
    critical_disagreements = [
        item for item in disagreements if _is_critical_key(item.key)
    ]

    blocking = any(f.severity == SEVERITY_BLOCKING for f in failures)
    if blocking:
        level = GATE_BLOCKED
    elif failures or critical_disagreements:
        level = GATE_DEGRADED
    else:
        level = GATE_OK

    if level == GATE_OK:
        summary = "解析结果完备：必备字段全部齐备，下游模块可正常推理"
    else:
        if level == GATE_BLOCKED:
            head = "解析结果不可用"
        elif failures:
            head = "解析结果不完整"
        else:
            head = "解析结果需人工核对"
        reasons: list[str] = []
        if failures:
            reasons.append(f"缺失 {'、'.join(f.label for f in failures)}")
        if critical_disagreements:
            reasons.append(
                f"双源冲突 {'、'.join(a.label for a in critical_disagreements)}"
            )
        summary = f"{head}：{'；'.join(reasons)}"

    # 非必备字段的冲突只留痕、不降级，但要单独报出来——
    # 上面已经把"关键冲突"写进结论了，这里不能重复念一遍。
    extra = [a for a in disagreements if not _is_critical_key(a.key)]
    if extra:
        shown = "、".join(a.label for a in extra[:4])
        more = "等" if len(extra) > 4 else ""
        summary += f"；另有 {len(extra)} 项非必备字段双源冲突（{shown}{more}）"

    if escalated:
        summary += f"；{_OUTCOME_TEXT.get(escalation_outcome, '已尝试 L2 升级')}"

    return ParseGate(
        level=level,
        failures=failures,
        disagreements=disagreements,
        summary=summary,
        escalated=escalated,
        escalation_reason=escalation_reason,
        escalation_outcome=escalation_outcome,
        escalation_note=escalation_note,
    )


def _is_critical_key(key: str) -> bool:
    """该键上的冲突是否必须让门禁降级。"""
    return key in _REQUIRED_CONFLICT_KEYS or key.startswith("party.")



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
    """字段级仲裁并合并 L1 / L2。

    返回 (仲裁后的结果, outcome, note)。

    **为什么不再是"整份二选一"**：`completeness()` 是整份结果上的三个计数，
    两个抽取器各命中 7/8 但命中的是不同的 7 个时它判定为平手，于是整份丢掉一侧，
    连那一侧唯一抽对的字段一起丢——这是纯损失，没有任何取舍上的理由。

    **为什么不会用更差的结果覆盖更好的**（原契约，必须保住）：
    `LLM_PROVIDER=mock` 时 L2 返回空壳。合并只在 L2 **额外提供**了值（l2_only）
    时采纳，L2 没提供任何东西就原样返回 `l1` 本身（连拷贝都不做）。

    **冲突怎么办**：两侧都给了值但不一致时，保留**规则抽取**的值——
    它贴合原文、可解释、且与本项目「数值不交给大模型」的铁律一致——
    同时把另一侧的值记进 `ContractField.alternative`、状态标 `conflict`，
    由门禁升级为"必须人工核对"。**不假装知道哪个对。**
    """
    items, parties = _arbitrate(l1, l2)
    gained = [a for a in items if a.status == ARB_L2_ONLY]
    conflicts = [a for a in items if a.status == ARB_CONFLICT]
    agreed = [a for a in items if a.status == ARB_AGREED]

    # L2 什么也没说：既没补充、也没有一致或冲突项（mock 占位结构就是这种）
    # → 原样返回 L1，连拷贝都不做
    if not gained and not conflicts and not agreed:
        return (
            l1,
            ESCALATION_REJECTED,
            "L2 未提供任何可用信息（既无补充字段，也无一致/冲突项），保留 L1 结果",
        )

    merged = _apply(l1, l2, items, parties)

    parts: list[str] = []
    if gained:
        parts.append(f"补充 {len(gained)} 项（{'、'.join(a.label for a in gained)}）")
    if agreed:
        parts.append(f"双源一致 {len(agreed)} 项")
    if conflicts:
        parts.append(
            f"双源冲突 {len(conflicts)} 项（{'、'.join(a.label for a in conflicts)}）"
            "，已按确定性规则取值并标记待人工核对"
        )
    note = "；".join(parts)

    if gained:
        outcome = ESCALATION_ADOPTED
    elif conflicts or agreed:
        outcome = ESCALATION_MERGED
    else:  # pragma: no cover —— 上面的早返回已覆盖"什么都没有"的情形
        outcome = ESCALATION_REJECTED
    return merged, outcome, note


# ============================================================
#  字段级仲裁
# ============================================================

# 必需项里"取值型"的键（text / parties 不是取值型字段，单独处理）
_SCALAR_KEYS: tuple[str, ...] = tuple(
    item.key for item in REQUIRED_ITEMS if item.key not in ("text", "parties")
)

# 冲突落在这些键上时，门禁必须降级（值不可靠，且下游直接依赖）
_REQUIRED_CONFLICT_KEYS: frozenset[str] = frozenset(_SCALAR_KEYS) | {"parties.roles"}

# 状态 → 由"双源是否一致"导出的置信度
_ARB_CONFIDENCE: dict[str, float] = {
    ARB_AGREED: 0.95,
    ARB_CONFLICT: 0.45,
    ARB_L2_ONLY: 0.85,
    ARB_L1_ONLY: 0.7,
    ARB_MISSING: 0.0,
}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _field_of(contract: StructuredContract, key: str) -> ContractField | None:
    for item in contract.fields:
        if item.key == key:
            return item
    return None


def _value_of(contract: StructuredContract, key: str) -> str:
    """某个键在某个候选结果里的取值：字段值优先，回落到同名标量。

    两者不一致时以 `fields` 为准——它是展示层的权威来源，
    标量只是 `structurer` 写下的镜像（测试夹具里两者可能只有其一，故需回落）。
    """
    if key == "title":
        return _text(getattr(contract, "title", ""))
    item = _field_of(contract, key)
    if item is not None and _text(item.value):
        return _text(item.value)
    return _text(getattr(contract, key, ""))


def _evidence_of(contract: StructuredContract, key: str) -> str:
    item = _field_of(contract, key)
    return _text(item.evidence) if item is not None else ""


def _prior_of(contract: StructuredContract, key: str) -> float:
    """某个候选对某字段的静态先验置信度（单源时直接沿用）。"""
    item = _field_of(contract, key)
    if item is not None and item.confidence:
        return float(item.confidence)
    return 0.8


def _arbitrate_value(
    key: str, label: str, l1_value: str, l2_value: str, l1_conf: float
) -> FieldArbitration:
    """单值仲裁。冲突时保留 L1（确定性规则），另一侧存进 l2_value 供人工比对。"""
    if l1_value and l2_value:
        if l1_value == l2_value:
            return FieldArbitration(
                key=key,
                label=label,
                status=ARB_AGREED,
                l1_value=l1_value,
                l2_value=l2_value,
                chosen_value=l1_value,
                chosen_from="both",
                confidence=_ARB_CONFIDENCE[ARB_AGREED],
            )
        return FieldArbitration(
            key=key,
            label=label,
            status=ARB_CONFLICT,
            l1_value=l1_value,
            l2_value=l2_value,
            chosen_value=l1_value,
            chosen_from="l1",
            confidence=_ARB_CONFIDENCE[ARB_CONFLICT],
        )
    if l1_value:
        return FieldArbitration(
            key=key,
            label=label,
            status=ARB_L1_ONLY,
            l1_value=l1_value,
            chosen_value=l1_value,
            chosen_from="l1",
            confidence=l1_conf or _ARB_CONFIDENCE[ARB_L1_ONLY],
        )
    if l2_value:
        return FieldArbitration(
            key=key,
            label=label,
            status=ARB_L2_ONLY,
            l2_value=l2_value,
            chosen_value=l2_value,
            chosen_from="l2",
            confidence=_ARB_CONFIDENCE[ARB_L2_ONLY],
        )
    return FieldArbitration(key=key, label=label, status=ARB_MISSING, confidence=0.0)


def _field_keys(l1: StructuredContract, l2: StructuredContract) -> list[str]:
    """参与仲裁的键：两侧 fields 的并集，再补上取值型必备项与合同名称。"""
    keys: list[str] = []
    for contract in (l1, l2):
        for item in contract.fields:
            if item.key and item.key not in keys:
                keys.append(item.key)
    for key in ("title", *_SCALAR_KEYS):
        if key not in keys:
            keys.append(key)
    return keys


def _field_label(l1: StructuredContract, l2: StructuredContract, key: str) -> str:
    if key == "title":
        return "合同名称"
    for contract in (l1, l2):
        item = _field_of(contract, key)
        if item is not None and _text(item.label):
            return _text(item.label)
    return key


def _named_parties(contract: StructuredContract) -> dict[str, object]:
    """按角色归纳**有名字的**主体（无名主体下游用不了，不参与仲裁）。"""
    out: dict[str, object] = {}
    for party in contract.parties:
        role = _text(getattr(party, "role", "")) or "未标注角色"
        if _text(getattr(party, "name", "")) and role not in out:
            out[role] = party
    return out


def _single_side_party_entries(
    role: str, side: object, status: str, other: dict[str, object]
) -> tuple[list[FieldArbitration], object]:
    """只有一个抽取器识别出该角色时的记录：逐属性留痕，值照抄该侧。"""
    entries: list[FieldArbitration] = []
    for attr, label in (("name", "名称"), ("credit_code", "统一社会信用代码")):
        value = _text(getattr(side, attr, ""))
        counterpart = other.get(role)
        # 对侧没有这个角色，故另一侧的值必然为空——这正是 l1_only / l2_only 的含义
        alternate = (
            _text(getattr(counterpart, attr, "")) if counterpart is not None else ""
        )
        entries.append(
            FieldArbitration(
                key=f"party.{role}.{attr}",
                label=f"{role}{label}",
                status=status if value else ARB_MISSING,
                l1_value=value if status == ARB_L1_ONLY else alternate,
                l2_value=value if status == ARB_L2_ONLY else alternate,
                chosen_value=value,
                chosen_from="l1" if status == ARB_L1_ONLY else "l2",
                confidence=_ARB_CONFIDENCE[status] if value else 0.0,
            )
        )
    return entries, side.model_copy(deep=True)


def _arbitrate_parties(
    l1: StructuredContract, l2: StructuredContract, items: list[FieldArbitration]
) -> list:
    """主体仲裁，返回合并后的主体列表，并把逐项记录追加进 `items`。

    同名角色逐属性合并；角色命名方案完全不同时整侧取主体更多的一方。
    后者是必须的兜底：L1 用「供方/需方」而 L2 用「甲方/乙方」描述**同一对当事人**，
    此时按角色取并集会凭空造出 4 个主体，直接把主体数与下游企业核验带偏。
    """
    l1_roles, l2_roles = _named_parties(l1), _named_parties(l2)

    if l1_roles and l2_roles and not (set(l1_roles) & set(l2_roles)):
        take_l1 = len(l1_roles) >= len(l2_roles)
        source = l1 if take_l1 else l2
        items.append(
            FieldArbitration(
                key="parties.roles",
                label="主体角色命名",
                status=ARB_CONFLICT,
                l1_value="、".join(l1_roles),
                l2_value="、".join(l2_roles),
                chosen_value="、".join(_named_parties(source)),
                chosen_from="l1" if take_l1 else "l2",
                confidence=_ARB_CONFIDENCE[ARB_CONFLICT],
            )
        )
        return [party.model_copy(deep=True) for party in source.parties]

    merged: list = []
    roles = [*l1_roles, *(r for r in l2_roles if r not in l1_roles)]
    for role in roles:
        p1, p2 = l1_roles.get(role), l2_roles.get(role)

        if p1 is None or p2 is None:
            if p1 is not None:
                entries, party = _single_side_party_entries(role, p1, ARB_L1_ONLY, l2_roles)
            else:
                entries, party = _single_side_party_entries(role, p2, ARB_L2_ONLY, l1_roles)
            items.extend(entries)
            merged.append(party)
            continue

        name = _arbitrate_value(
            f"party.{role}.name", f"{role}名称", _text(p1.name), _text(p2.name), 0.75
        )
        code = _arbitrate_value(
            f"party.{role}.credit_code",
            f"{role}统一社会信用代码",
            _text(p1.credit_code),
            _text(p2.credit_code),
            0.75,
        )
        items.extend((name, code))
        merged.append(
            p1.model_copy(
                update={
                    "name": name.chosen_value,
                    "credit_code": code.chosen_value,
                    "contact": _text(p1.contact) or _text(p2.contact),
                    "address": _text(p1.address) or _text(p2.address),
                }
            )
        )
    return merged


def _arbitrate(
    l1: StructuredContract, l2: StructuredContract
) -> tuple[list[FieldArbitration], list]:
    """对一份合同做完整的双源仲裁，返回 (逐项记录, 合并后的主体列表)。"""
    items: list[FieldArbitration] = []
    for key in _field_keys(l1, l2):
        items.append(
            _arbitrate_value(
                key,
                _field_label(l1, l2, key),
                _value_of(l1, key),
                _value_of(l2, key),
                _prior_of(l1, key),
            )
        )
    parties = _arbitrate_parties(l1, l2, items)
    return items, parties


def _apply(
    l1: StructuredContract,
    l2: StructuredContract,
    items: list[FieldArbitration],
    parties: list,
) -> StructuredContract:
    """把仲裁结果落到一份新的结构化合同上（以 L1 为底，只覆盖被判定的部分）。"""
    merged = l1.model_copy(deep=True)
    merged.extractor = f"{l1.extractor}+{l2.extractor}"
    merged.arbitration = items
    merged.parties = parties

    by_key = {a.key: a for a in items}

    title = by_key.get("title")
    if title is not None:
        merged.title = title.chosen_value

    order = {f.key: i for i, f in enumerate(l1.fields)}
    for key in _field_keys(l1, l2):
        if key == "title":
            continue
        arb = by_key.get(key)
        if arb is None:
            continue
        # 证据取自"值真正来自哪一侧"；一致时优先 L1，L1 没有再用 L2
        if arb.chosen_from == "l2":
            evidence = _evidence_of(l2, key) or _evidence_of(l1, key)
        else:
            evidence = _evidence_of(l1, key) or _evidence_of(l2, key)
        merged.fields = [f for f in merged.fields if f.key != key]
        merged.fields.append(
            ContractField(
                key=key,
                label=arb.label,
                value=arb.chosen_value,
                confidence=arb.confidence,
                evidence=evidence,
                agreement=arb.status,
                alternative=arb.l2_value if arb.status == ARB_CONFLICT else "",
                source={"both": "both", "l1": "rule", "l2": "llm"}.get(
                    arb.chosen_from, ""
                ),
            )
        )
        if hasattr(merged, key):
            setattr(merged, key, arb.chosen_value)

    # 字段顺序对齐 L1 的原有顺序，避免仲裁后展示顺序漂移
    merged.fields.sort(key=lambda f: order.get(f.key, len(order)))

    for warning in l2.warnings:
        if warning not in merged.warnings:
            merged.warnings.append(warning)
    return merged


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
        if gate.failures:
            line += "　下游结论必须附带该缺失标注，不得当作完整结论使用"
        else:
            line += "　冲突字段的值不可直接采信，下游结论必须携带该标注"
    if gate.disagreements:
        line += (
            f"　门禁记录 {len(gate.disagreements)} 项双源冲突"
            f"（{'、'.join(gate.conflict_labels())}），系统不判断哪一侧正确，请人工核对原文"
        )
    return line

