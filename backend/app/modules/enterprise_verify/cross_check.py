"""L3 交叉校验：合同主体信息 vs 工商登记信息。

四项比对，全部给出可复核的依据：
1. 名称一致性 —— 合同主体名称 vs 登记名称
2. 信用代码一致性 —— 合同载明代码 vs 登记代码
3. 成立日期 vs 签订日期 —— 签约时主体是否已存在（依赖 facts.sign_date）
4. 登记状态与经营范围 —— 主体是否存续、业务是否覆盖合同标的

判定纪律与标准校验一致：判不了就返回 review，不硬给结论。
"""

from __future__ import annotations

import re

from app.core.providers.base import RegistrationInfo
from app.modules.contract_parser.schema import ContractFacts, Party
from app.modules.enterprise_verify.schema import (
    CheckItem,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_REVIEW,
    STATUS_SKIP,
    STATUS_WARNING,
)

# ---- 登记状态关键字 ----
_ACTIVE_STATUS = ("存续", "开业", "在业", "正常")
_DEAD_STATUS = ("注销", "吊销", "停业", "清算", "迁出", "歇业", "撤销")

# ---- 经营范围关键字（订单农业语境）----
_BUYER_SCOPE = ("收购", "粮食", "农产品", "食品", "农业")
_PRODUCER_SCOPE = ("种植", "农业", "农作物", "粮食", "农产品", "养殖", "水产")

_DATE_RE = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})日?")


def _to_iso_date(text: str) -> str | None:
    """「1995-02-10」「1995年2月10日」「1995/2/10」→ ISO 日期；解析不了返回 None。"""
    match = _DATE_RE.search(text or "")
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def detect_role(party: Party) -> str:
    """识别主体在订单农业中的角色：buyer（收购方）| producer（种植/供应方）| unknown。

    先看合同里的角色称谓，再看主体名称特征，最后退到「甲方=收购方」的行业惯例。
    """
    text = f"{party.role} {party.name}"
    if any(k in text for k in ("收购", "订购", "采购")):
        return "buyer"
    if any(k in text for k in ("种植", "供应", "生产", "农场", "合作社", "养殖")):
        return "producer"
    if "甲方" in party.role:
        return "buyer"
    if "乙方" in party.role:
        return "producer"
    return "unknown"


_ROLE_LABEL = {"buyer": "收购方", "producer": "种植/供应方", "unknown": "未能识别"}


def run_l3_checks(
    party: Party,
    registration: RegistrationInfo,
    facts: ContractFacts,
) -> list[CheckItem]:
    checks: list[CheckItem] = []

    # 1. 名称一致性
    if party.name and registration.name:
        contract_name = party.name.strip()
        registered_name = registration.name.strip()
        if contract_name == registered_name:
            checks.append(
                CheckItem(
                    key="name_match",
                    label="名称一致性",
                    status=STATUS_PASS,
                    detail=f"合同主体名称与登记名称一致（{registered_name}）",
                    evidence=f"合同：{contract_name}｜登记：{registered_name}",
                )
            )
        else:
            checks.append(
                CheckItem(
                    key="name_match",
                    label="名称一致性",
                    status=STATUS_FAIL,
                    detail=(
                        f"合同载明的主体名称（{contract_name}）与该信用代码对应的"
                        f"登记名称（{registered_name}）不一致，可能冒用主体或名称变更后合同未更新"
                    ),
                    evidence=f"合同：{contract_name}｜登记：{registered_name}",
                )
            )

    # 2. 信用代码一致性
    if party.credit_code and registration.credit_code:
        contract_code = party.credit_code.strip().upper()
        registered_code = registration.credit_code.strip().upper()
        if contract_code == registered_code:
            checks.append(
                CheckItem(
                    key="code_match",
                    label="信用代码一致性",
                    status=STATUS_PASS,
                    detail="合同载明的统一社会信用代码与登记代码一致",
                    evidence=f"合同：{contract_code}｜登记：{registered_code}",
                )
            )
        else:
            checks.append(
                CheckItem(
                    key="code_match",
                    label="信用代码一致性",
                    status=STATUS_FAIL,
                    detail=(
                        f"合同载明的信用代码（{contract_code}）与登记代码（{registered_code}）不一致，"
                        "可能指向不同主体"
                    ),
                    evidence=f"合同：{contract_code}｜登记：{registered_code}",
                )
            )

    # 3. 成立日期 vs 签订日期
    sign = facts.sign_date
    if sign.kind == "absolute" and sign.start:
        founding = _to_iso_date(registration.founding_date)
        if founding is None:
            checks.append(
                CheckItem(
                    key="founding_vs_sign",
                    label="成立日期 vs 签订日期",
                    status=STATUS_REVIEW,
                    detail=(
                        f"登记成立日期「{registration.founding_date}」无法解析为日期，需人工核对"
                    ),
                    evidence=f"登记成立日期：{registration.founding_date}｜合同签订日期：{sign.start}",
                )
            )
        elif founding <= sign.start:
            checks.append(
                CheckItem(
                    key="founding_vs_sign",
                    label="成立日期 vs 签订日期",
                    status=STATUS_PASS,
                    detail=f"签订合同时主体已成立（成立 {founding}，签约 {sign.start}）",
                    evidence=f"成立日期：{founding}｜签订日期：{sign.start}",
                )
            )
        else:
            checks.append(
                CheckItem(
                    key="founding_vs_sign",
                    label="成立日期 vs 签订日期",
                    status=STATUS_FAIL,
                    detail=(
                        f"主体成立日期（{founding}）晚于合同签订日期（{sign.start}），"
                        "签约时该公司尚不存在，合同真实性存疑"
                    ),
                    evidence=f"成立日期：{founding}｜签订日期：{sign.start}",
                )
            )
    else:
        expr = sign.raw or sign.expr or "未载明"
        checks.append(
            CheckItem(
                key="founding_vs_sign",
                label="成立日期 vs 签订日期",
                status=STATUS_SKIP,
                detail=(
                    f"合同签订日期为「{expr}」，无法与成立日期比大小；"
                    "相对表达本身即生效时点不确定的风险信号"
                ),
                evidence=f"合同签订日期：{expr}",
            )
        )

    # 4. 登记状态
    if registration.status:
        status_text = registration.status
        if any(k in status_text for k in _ACTIVE_STATUS):
            checks.append(
                CheckItem(
                    key="registration_status",
                    label="登记状态",
                    status=STATUS_PASS,
                    detail=f"主体登记状态为「{status_text}」，正常经营",
                    evidence=f"登记状态：{status_text}",
                )
            )
        elif any(k in status_text for k in _DEAD_STATUS):
            checks.append(
                CheckItem(
                    key="registration_status",
                    label="登记状态",
                    status=STATUS_FAIL,
                    detail=(
                        f"主体登记状态为「{status_text}」，已丧失或即将丧失经营资格，"
                        "不具备履约能力"
                    ),
                    evidence=f"登记状态：{status_text}",
                )
            )
        else:
            checks.append(
                CheckItem(
                    key="registration_status",
                    label="登记状态",
                    status=STATUS_REVIEW,
                    detail=f"登记状态「{status_text}」不在已知判定集内，需人工核对",
                    evidence=f"登记状态：{status_text}",
                )
            )
    else:
        checks.append(
            CheckItem(
                key="registration_status",
                label="登记状态",
                status=STATUS_REVIEW,
                detail="工商数据未返回登记状态，需人工核对",
            )
        )

    # 5. 经营范围 vs 合同角色（《订单农业合同规范指引》第二条）
    if not registration.business_scope:
        checks.append(
            CheckItem(
                key="scope_match",
                label="经营范围匹配",
                status=STATUS_REVIEW,
                detail="工商数据未返回经营范围，无法比对（依据《订单农业合同规范指引》第二条）",
            )
        )
    else:
        role = detect_role(party)
        scope = registration.business_scope
        if role == "unknown":
            checks.append(
                CheckItem(
                    key="scope_match",
                    label="经营范围匹配",
                    status=STATUS_REVIEW,
                    detail=(
                        "无法从合同中识别该主体的收购/种植角色，经营范围是否覆盖合同标的需人工核对"
                        "（依据《订单农业合同规范指引》第二条）"
                    ),
                    evidence=f"经营范围：{scope[:120]}",
                )
            )
        else:
            keywords = _BUYER_SCOPE if role == "buyer" else _PRODUCER_SCOPE
            hit = next((k for k in keywords if k in scope), None)
            if hit:
                checks.append(
                    CheckItem(
                        key="scope_match",
                        label="经营范围匹配",
                        status=STATUS_PASS,
                        detail=(
                            f"识别角色：{_ROLE_LABEL[role]}；经营范围含「{hit}」，"
                            "与订单农业业务相关（依据《订单农业合同规范指引》第二条）"
                        ),
                        evidence=f"经营范围：{scope[:120]}",
                    )
                )
            else:
                checks.append(
                    CheckItem(
                        key="scope_match",
                        label="经营范围匹配",
                        status=STATUS_WARNING,
                        detail=(
                            f"识别角色：{_ROLE_LABEL[role]}；经营范围未见"
                            f"（{'、'.join(keywords)}）相关表述，"
                            "超范围经营风险需人工核对（依据《订单农业合同规范指引》第二条）"
                        ),
                        evidence=f"经营范围：{scope[:120]}",
                    )
                )

    return checks
