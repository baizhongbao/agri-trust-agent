"""企业核验结果的数据模型。

与 contract_parser 的 fields 同一条原则：每个判定项都必须带 evidence，
使「主体可信 / 不可信」的结论可回溯到登记信息或计算过程。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# 判定状态：pass 通过 | fail 不通过（重大风险）| warning 需关注 | review 待人工核对 | skip 不适用
STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_WARNING = "warning"
STATUS_REVIEW = "review"
STATUS_SKIP = "skip"

_STATUS_PRECEDENCE = (STATUS_FAIL, STATUS_REVIEW, STATUS_WARNING, STATUS_PASS, STATUS_SKIP)


class CheckItem(BaseModel):
    """单条核验判定。"""

    key: str
    label: str
    layer: str = Field(default="L3", description="所属层级：L1 本地校验 | L3 交叉校验")
    status: str = Field(default=STATUS_REVIEW)
    detail: str = ""
    evidence: str = Field(default="", description="支撑该判定的依据")


class RegistrationInfo(BaseModel):
    """工商登记信息（L2 查询结果）。字段缺失时留空，不猜。"""

    name: str = ""
    credit_code: str = ""
    legal_person: str = ""
    registered_capital: str = ""
    founding_date: str = Field(default="", description="成立日期，尽量归一为 ISO 格式")
    status: str = Field(default="", description="登记状态，如 存续 / 开业 / 注销")
    business_scope: str = ""
    address: str = ""
    raw: dict = Field(default_factory=dict, description="接口原始返回（供追溯）")


class PartyVerification(BaseModel):
    """单个合同主体的核验结果。"""

    role: str = ""
    name: str = ""
    credit_code: str = ""
    overall: str = Field(default=STATUS_REVIEW, description="综合判定：fail > review > warning > pass")

    l1: list[CheckItem] = Field(default_factory=list, description="本地逻辑校验（格式 + 校验位）")
    l2_status: str = Field(
        default="skipped",
        description="工商查询结果：found | not_found | error | skipped",
    )
    l2_note: str = ""
    l2: RegistrationInfo | None = None
    l3: list[CheckItem] = Field(default_factory=list, description="交叉校验（合同 vs 登记）")


class VerifyReport(BaseModel):
    """一份合同的企业核验报告。"""

    doc_id: str
    contract_title: str = ""
    provider: str = Field(default="", description="工商数据来源：fixture | qcc")
    parties: list[PartyVerification] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict, description="各综合判定的主体数量")
    disclaimer: str = ""


def combine_status(statuses: list[str]) -> str:
    """按严重度归并多个判定：fail > review > warning > pass > skip。

    一个主体只要有一项 fail，整体就是 fail——
    主体核验与条款覆盖不同，这里没有「功过相抵」。
    """
    for status in _STATUS_PRECEDENCE:
        if status in statuses:
            return status
    return STATUS_REVIEW
