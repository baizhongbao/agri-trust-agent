"""结构化合同的数据模型。

设计要点：每个抽取字段都带 `evidence`（原文片段）和 `confidence`。
订单农业的核心诉求是"可信"，所以结果必须可回溯到合同原文，
而不是只给一个孤零零的结论——这直接对应需求里的"可信性"。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Party(BaseModel):
    """合同当事人。"""

    role: str = Field(default="", description="角色，如 甲方 / 乙方 / 丙方")
    name: str = ""
    credit_code: str = Field(default="", description="统一社会信用代码")
    contact: str = ""
    address: str = ""


class Clause(BaseModel):
    """合同条款。"""

    index: int = 0
    title: str = ""
    content: str = ""


# ============================================================
#  解析质量门禁（L4）
#
#  等级语义：
#    blocked  —— 主体缺失 / 无文本。下游结论不可信，必须显式拒绝或标注，
#                绝不允许静默跳过（例如企业核验拿到空主体后返回一份
#                "summary 全 0" 的报告，会被读成"已核验、无风险"）
#    degraded —— 个别必备字段缺失。下游可继续，但必须携带该标注
#    ok       —— 必备字段齐备
# ============================================================

GATE_OK = "ok"
GATE_DEGRADED = "degraded"
GATE_BLOCKED = "blocked"


# ============================================================
#  双源仲裁（L1 规则 vs L2 大模型）
#
#  背景：`choose_better` 原来按 `completeness()` 的 (主体数, 必备项命中, 字段命中)
#  三元组**整份二选一**。当两个抽取器各命中 7/8 个字段、但命中的是不同的 7 个时，
#  三元组相等 → 保留 L1 → **L2 已经抽对的那个字段被白白丢掉**。
#
#  这与「可信性」直接冲突：`confidence` 原本是写死的先验（规则 0.65~0.8、
#  大模型一律 0.9），不携带任何信息。两个**失败模式独立**的抽取器对同一字段
#  给出相同值，才是一个真正有信息量的可信信号；给出不同值，则是最该送人工核对的情形。
#
#  因此改成字段级仲裁：逐项定状态、逐项定置信度、冲突项显式留痕。
# ============================================================

ARB_AGREED = "agreed"  # 两个抽取器都给了值且完全一致
ARB_L1_ONLY = "l1_only"  # 只有规则抽取给了值
ARB_L2_ONLY = "l2_only"  # 只有大模型给了值（合并时补入）
ARB_CONFLICT = "conflict"  # 两个都给了值但不一致 —— 必须人工核对
ARB_MISSING = "missing"  # 两边都没抽到
ARB_SINGLE = "single"  # 只跑了一个抽取器，无从交叉验证

ARB_LABELS = {
    ARB_AGREED: "双源一致",
    ARB_L1_ONLY: "仅规则",
    ARB_L2_ONLY: "仅大模型",
    ARB_CONFLICT: "双源冲突",
    ARB_MISSING: "未抽到",
    ARB_SINGLE: "单源",
}


class FieldArbitration(BaseModel):
    """一个字段（或主体属性）在 L1 / L2 之间的仲裁记录。

    这是字段级仲裁的**权威记录**，覆盖 8 个展示字段、合同名称与主体属性；
    `ContractField.agreement` 只是给前端/报告用的同源镜像（由同一处代码写入）。
    """

    key: str
    label: str = ""
    status: str = ARB_MISSING
    l1_value: str = ""
    l2_value: str = ""
    chosen_value: str = ""
    chosen_from: str = Field(default="", description="both | l1 | l2 | 空")
    confidence: float = 0.0

    @property
    def is_conflict(self) -> bool:
        return self.status == ARB_CONFLICT


class GateFailure(BaseModel):
    """一条门禁未通过项。"""

    key: str
    label: str
    severity: str = Field(default="degraded", description="blocking 阻断 | degraded 降级")
    detail: str = ""


class ParseGate(BaseModel):
    """解析质量门禁结果，随解析结果一同落盘。

    它与 `warnings` 的分工：`warnings` 是给人看的自由文本流水，
    `gate` 是给程序判断的结构化结论——下游据此决定"能不能继续算"。
    """

    level: str = Field(default=GATE_OK, description="ok | degraded | blocked")
    failures: list[GateFailure] = Field(default_factory=list)
    summary: str = Field(default="", description="一句话结论，可直接展示")

    # ---- 字段级双源分歧：值抽到了，但两个抽取器不一致，属于"必须人工核对" ----
    disagreements: list[FieldArbitration] = Field(default_factory=list)

    # ---- L1 → L2 升级痕迹：必须留档，否则"为什么这份用 LLM 抽的"无从追溯 ----
    escalated: bool = False
    escalation_reason: str = ""
    escalation_outcome: str = Field(
        default="",
        description="adopted 用 L2 补充了字段 | merged 按字段合并并取得交叉验证 | "
        "rejected L2 没提供可用信息已丢弃 | unavailable L2 不可用 | skipped 已跳过",
    )
    escalation_note: str = ""

    @property
    def blocked(self) -> bool:
        return self.level == GATE_BLOCKED

    def missing_labels(self) -> list[str]:
        return [f.label for f in self.failures]

    def conflict_labels(self) -> list[str]:
        return [d.label for d in self.disagreements]


class ContractField(BaseModel):
    """单个抽取字段及其依据。

    `confidence` 的含义随来源而变，前端不要一概当成"模型置信度"：
      - `agreement == ARB_SINGLE`（只跑了一个抽取器）时，它是该抽取器的**静态先验**
        （规则按正则的保守程度写死 0.65~0.8，大模型一律 0.9），**不携带证据**；
      - 跑过双源仲裁时，它由**两个抽取器是否一致**导出（一致 0.95 / 冲突 0.45），
        这才是一个有信息量的信号。
    """

    key: str
    label: str
    value: str = ""
    confidence: float = 0.0
    evidence: str = Field(default="", description="支撑该字段的合同原文片段")
    agreement: str = Field(default="", description="双源一致性，取值见 schema.ARB_* 常量")
    alternative: str = Field(
        default="", description="另一抽取器给出的**不同**值（冲突时填写，供人工比对）"
    )
    source: str = Field(default="", description="取值来源：both | rule | llm | 空")


# ============================================================
#  可推理的结构化事实
#
#  上面那套（fields）面向「展示」：值是原文片段，人看得懂，
#  但机器推理不了——「486,000元」没法参与计算，「2026年9月18日」没法比大小。
#  下面这套（facts）面向「推理」：金额是数值、日期是 ISO、
#  质量指标是 (名称, 比较符, 阈值) 三元组。
#
#  两者都必须带 evidence：结构化值同样要能回溯原文，否则"可信"就断了。
# ============================================================


class Money(BaseModel):
    """金额。

    value 为 None 表示合同未载明——不要用 0 代替，
    「没写」和「写了 0」在风险判定上是两回事。
    """

    value: float | None = None
    currency: str = "CNY"
    raw: str = ""


class DateValue(BaseModel):
    """日期。

    kind 的取值决定了下游能做什么推理：
      - absolute  绝对日期。可以比较先后、算间隔
      - relative  相对/条件表达，如「签字盖章之日起」「验收合格后 15 个工作日内」。
                  这不是抽取失败，而是合同的真实形态，本身就是风险信号
                  （生效时点不确定、回款挂在验收上）
      - range     区间，如「2026年11月1日至11月30日」
      - none      未载明
    """

    kind: str = "none"
    start: str | None = None  # ISO 日期
    end: str | None = None  # 仅 range 使用
    expr: str = ""  # 相对表达的原文
    raw: str = ""


class Quantity(BaseModel):
    """带比较符的数值，用于质量指标、标的数量、面积。

    op 取值：<= | >= | = | range（range 时 value 为下限、upper 为上限）
    """

    name: str = ""
    op: str = ""
    value: float | None = None
    upper: float | None = None
    unit: str = ""
    raw: str = ""


class Ratio(BaseModel):
    """比例类约定（违约金、定金）。

    kind：ratio（按基数百分比）| per_day（按日计）| fixed（固定金额）
    """

    rate: float | None = None
    base: str = ""
    kind: str = "ratio"
    raw: str = ""


# ============================================================
#  事实之间的确定性自检（见 consistency.py）
#
#  单项"抽到了"不等于整体自洽：签订日期不该晚于生效日期、定金不该超过 20%。
#  这类矛盾只能靠交叉比对发现，且必须带机器可读的原因码，
#  否则"校验没通过"就只能躺在中文里，程序与测试都读不出来。
# ============================================================

CHECK_OK = "ok"
CHECK_WARNING = "warning"
CHECK_REVIEW = "review"


class ConsistencyCheck(BaseModel):
    """一条确定性一致性校验的结论。"""

    code: str = Field(description="机器可读的原因码，如 delivery_before_sign_date")
    status: str = Field(
        default=CHECK_OK,
        description="ok 通过 | warning 发现矛盾 | review 需人工复核（如是否过分高于损失）",
    )
    detail: str = ""
    evidence: str = Field(default="", description="支撑该结论的合同原文片段")
    legal_basis: str = Field(default="", description="如涉及法定上限，注明法条原文")


class ContractFacts(BaseModel):
    """面向推理的结构化事实。

    抽取原则：**抽不到就留空，绝不用 0 或猜测值填充**。
    宁可空缺，不可编造——这与 evidence 是同一条原则。
    """

    amount: Money = Field(default_factory=Money)
    unit_price: Money = Field(default_factory=Money)
    # 标的品类（如「籼稻谷」/「大米」）。合规比对靠它做限值适用性过滤，
    # 否则同一份合同的水分指标会同时对多个品类下结论、互相矛盾。
    subject_category: str = ""
    sign_date: DateValue = Field(default_factory=DateValue)
    effective_date: DateValue = Field(default_factory=DateValue)
    delivery: DateValue = Field(default_factory=DateValue)
    quantity: Quantity = Field(default_factory=Quantity)
    planted_area: Quantity = Field(default_factory=Quantity)
    deposit: Ratio = Field(default_factory=Ratio)
    penalty: Ratio = Field(default_factory=Ratio)
    payment_days: int | None = None
    payment_trigger: str = ""
    quality_metrics: list[Quantity] = Field(default_factory=list)
    evidences: dict[str, str] = Field(
        default_factory=dict, description="各事实对应的合同原文片段"
    )

    def metric(self, name: str) -> Quantity | None:
        """按名称取质量指标，供标准校验做阈值比对。"""
        for item in self.quality_metrics:
            if item.name == name:
                return item
        return None


class StructuredContract(BaseModel):
    """合同解析结果。"""

    contract_no: str = ""
    title: str = ""
    parties: list[Party] = Field(default_factory=list)

    amount: str = ""
    sign_date: str = ""
    effective_date: str = ""
    delivery_deadline: str = ""
    quality_standard: str = ""
    payment_terms: str = ""
    breach_terms: str = ""

    clauses: list[Clause] = Field(default_factory=list)
    fields: list[ContractField] = Field(default_factory=list)
    # 字段级双源仲裁记录（权威来源）；只有跑过 L1→L2 升级才有内容。
    # 为空表示"只跑了一个抽取器，无从交叉验证"，此时各字段 agreement 为 single。
    arbitration: list[FieldArbitration] = Field(default_factory=list)
    # fields 供人看（原文片段），facts 供机器算（数值 / ISO 日期 / 带比较符的指标）
    facts: ContractFacts = Field(default_factory=ContractFacts)
    # facts 之间的确定性自检结论（日期先后 / 定金上限 / 违约金复核）。
    # 不适用的规则不产生条目——"没检查"与"检查通过"必须能区分。
    checks: list[ConsistencyCheck] = Field(default_factory=list)

    # ---- 元信息，用于说明"这份结果是怎么来的" ----
    source_file: str = ""
    page_count: int = 0
    char_count: int = 0
    extractor: str = "unknown"
    used_ocr: bool = False
    warnings: list[str] = Field(default_factory=list)
    # 解析质量门禁：必备字段是否齐备 + L1→L2 升级痕迹（见 gate.py）
    gate: ParseGate = Field(default_factory=ParseGate)
    raw_text_preview: str = ""

    def field_map(self) -> dict[str, str]:
        """字段字典，便于后续标准校验按 key 取值。"""
        return {f.key: f.value for f in self.fields if f.value}
