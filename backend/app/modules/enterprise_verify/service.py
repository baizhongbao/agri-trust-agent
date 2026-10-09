"""企业核验服务：L1 本地校验 → L2 工商查询 → L3 交叉校验。

编排原则：
- L1 完全本地，任何环境都能跑（GB 32100-2015 校验位验算）
- L2 走 Provider 层（fixture 离线兜底 / qcc 真实数据），由 .env 切换
- L3 依赖 L2 查到的登记信息；L2 未命中时显式给出 review 结论，不静默跳过
- Provider 未就绪 / 查询失败时报 error 状态并把原因写进报告——
  部分结果（L1）仍然有价值，但失败必须可见
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.providers.base import (
    EnterpriseLookupResult,
    EnterpriseProvider,
    ProviderNotReadyError,
    RegistrationInfo,
)
from app.core.providers.registry import get_enterprise_provider
from app.modules.contract_parser import service as contract_service
from app.modules.contract_parser.schema import Party
from app.modules.enterprise_verify import credit_code, cross_check
from app.modules.enterprise_verify.schema import (
    CheckItem,
    PartyVerification,
    RegistrationInfo as RegistrationInfoModel,
    STATUS_REVIEW,
    STATUS_WARNING,
    VerifyReport,
    combine_status,
)

logger = logging.getLogger(__name__)

_DISCLAIMER = {
    "fixture": "L2 工商数据来自内置演示库（fixture，虚构企业），仅用于功能演示，不代表真实登记信息。",
    "qcc": "L2 工商数据来自企查查（第三方接口），仅供参考，正式核验请以国家企业信用信息公示系统为准。",
}


def _to_model(info: RegistrationInfo) -> RegistrationInfoModel:
    return RegistrationInfoModel(
        name=info.name,
        credit_code=info.credit_code,
        legal_person=info.legal_person,
        registered_capital=info.registered_capital,
        founding_date=info.founding_date,
        status=info.status,
        business_scope=info.business_scope,
        address=info.address,
        violations=info.violations,
        raw=info.raw,
    )


def _lookup_party(
    party: Party,
    provider: EnterpriseProvider,
) -> tuple[str, str, RegistrationInfo | None]:
    """执行 L2 查询，返回 (l2_status, note, registration)。"""
    search_key = credit_code.normalize(party.credit_code) or party.name.strip()
    if not search_key:
        return "skipped", "合同未载明该主体的名称与信用代码，无法查询", None

    try:
        result: EnterpriseLookupResult = provider.lookup(search_key)
    except ProviderNotReadyError as exc:
        logger.warning("企业核验 L2 未就绪：%s", exc)
        return "error", str(exc), None
    except Exception as exc:  # 网络 / 解析等一切外部故障都显式入报告
        logger.warning("企业核验 L2 查询失败 key=%s：%s", search_key, exc)
        return "error", f"查询出错：{exc}", None

    if result.found and result.registration is not None:
        return "found", "", result.registration
    return "not_found", result.note or "未查询到该主体的工商信息", None


def _verify_party(
    party: Party,
    facts_registry: Any,
    provider: EnterpriseProvider,
) -> PartyVerification:
    l1 = credit_code.run_l1_checks(party.credit_code)
    l2_status, l2_note, registration = _lookup_party(party, provider)

    l3: list[CheckItem] = []
    if registration is not None:
        l3 = cross_check.run_l3_checks(party, registration, facts_registry)
    elif l2_status in ("not_found", "error", "skipped"):
        status = STATUS_REVIEW if l2_status == "not_found" else STATUS_WARNING
        l3 = [
            CheckItem(
                key="l2_lookup",
                label="工商信息获取",
                layer="L2",
                status=status,
                detail=f"{l2_note}。交叉校验（名称/成立日期/登记状态/经营范围）无法执行",
                evidence=f"查询键：{party.credit_code or party.name}",
            )
        ]

    statuses = [item.status for item in l1] + [item.status for item in l3]
    return PartyVerification(
        role=party.role,
        name=party.name,
        credit_code=party.credit_code,
        overall=combine_status(statuses),
        l1=l1,
        l2_status=l2_status,
        l2_note=l2_note,
        l2=_to_model(registration) if registration is not None else None,
        l3=l3,
    )


def verify_contract(
    doc_id: str,
    provider: EnterpriseProvider | None = None,
) -> VerifyReport | None:
    """对一份已解析合同的全部主体执行企业核验。"""
    contract = contract_service.get_contract(doc_id)
    if contract is None:
        return None
    if provider is None:
        provider = get_enterprise_provider()

    parties = [
        _verify_party(party, contract.facts, provider)
        for party in contract.parties
    ]
    summary = {status: 0 for status in ("pass", "warning", "fail", "review")}
    for item in parties:
        summary[item.overall] = summary.get(item.overall, 0) + 1

    return VerifyReport(
        doc_id=doc_id,
        contract_title=contract.title,
        provider=provider.name,
        notice=_skipped_notice(contract, parties),
        parties=parties,
        summary=summary,
        disclaimer=_DISCLAIMER.get(provider.name, _DISCLAIMER["fixture"]),
    )


def _skipped_notice(
    contract,
    parties: list[PartyVerification],
) -> str:
    """当核验无法逐项跑完时，给出一句不能误读的说明。

    没有主体时**不返回空报告了事**：那样的 summary 全 0 会被读成
    “已核验、无风险”，而事实是一次工商查询都没发出（L4 门禁的下游半段）。
    """
    if not parties:
        return (
            "合同解析未识别到任何主体，企业核验（L1 信用代码校验 / L2 工商查询 / "
            "L3 交叉校验）全部未执行；下面的 summary 全 0 表示『没查』，"
            "不表示『没问题』。请先修复合同主体抽取或人工补录主体后重跑。"
        )
    missing_code = [p for p in parties if not p.credit_code]
    if missing_code:
        roles = "、".join(p.role for p in missing_code)
        note = f"{roles}未载明统一社会信用代码，仅按名称查询，未经 L1 校验位验算。"
        if contract.gate.level != "ok":
            note += f"合同解析门禁：{contract.gate.summary}。"
        return note
    if contract.gate.level != "ok":
        return f"合同解析门禁未通过，核验依据的字段可能存在缺失：{contract.gate.summary}。"
    return ""


def lookup(
    search_key: str,
    provider: EnterpriseProvider | None = None,
) -> dict[str, Any]:
    """直接核验单个主体（不经过合同），供前端独立查询与演示。"""
    if provider is None:
        provider = get_enterprise_provider()
    key = search_key.strip()
    if not key:
        return {"search_key": "", "l1": [], "l2_status": "skipped", "l2_note": "查询关键字为空", "l2": None}

    looks_like_code = len(credit_code.normalize(key)) == 18
    l1 = credit_code.run_l1_checks(key) if looks_like_code else []

    try:
        result = provider.lookup(key)
        l2_status = "found" if result.found else "not_found"
        note = result.note
        registration = result.registration
    except ProviderNotReadyError as exc:
        l2_status, note, registration = "error", str(exc), None
    except Exception as exc:
        l2_status, note, registration = "error", f"查询出错：{exc}", None

    return {
        "search_key": key,
        "provider": provider.name,
        "l1": [item.model_dump() for item in l1],
        "l2_status": l2_status,
        "l2_note": note or "",
        "l2": _to_model(registration).model_dump() if registration is not None else None,
        "disclaimer": _DISCLAIMER.get(provider.name, _DISCLAIMER["fixture"]),
    }
