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


class ContractField(BaseModel):
    """单个抽取字段及其依据。"""

    key: str
    label: str
    value: str = ""
    confidence: float = 0.0
    evidence: str = Field(default="", description="支撑该字段的合同原文片段")


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


class ContractFacts(BaseModel):
    """面向推理的结构化事实。

    抽取原则：**抽不到就留空，绝不用 0 或猜测值填充**。
    宁可空缺，不可编造——这与 evidence 是同一条原则。
    """

    amount: Money = Field(default_factory=Money)
    unit_price: Money = Field(default_factory=Money)
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
    # fields 供人看（原文片段），facts 供机器算（数值 / ISO 日期 / 带比较符的指标）
    facts: ContractFacts = Field(default_factory=ContractFacts)

    # ---- 元信息，用于说明"这份结果是怎么来的" ----
    source_file: str = ""
    page_count: int = 0
    char_count: int = 0
    extractor: str = "unknown"
    used_ocr: bool = False
    warnings: list[str] = Field(default_factory=list)
    raw_text_preview: str = ""

    def field_map(self) -> dict[str, str]:
        """字段字典，便于后续标准校验按 key 取值。"""
        return {f.key: f.value for f in self.fields if f.value}
