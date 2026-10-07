"""企业工商信息提供者实现。

- FixtureEnterpriseProvider：内置虚构演示数据（JSON 文件），零依赖、可离线，
  演示现场断网时的兜底；数据刻意按结论多样性设计（正常 / 注销 / 代码造假）
- QccEnterpriseProvider：企查查 MCP（HTTP 流式接口，JSON-RPC），
  调用 get_company_registration_info 工具获取真实工商登记信息

为什么 fixture 用「虚构企业 + 合规校验位的代码」：
    对真实企业输出「经营范围不匹配、存在履约风险」有商业诋毁风险，
    而虚构数据演示效果完全一致。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.providers.base import (
    EnterpriseLookupResult,
    EnterpriseProvider,
    ProviderNotReadyError,
    RegistrationInfo,
)

logger = logging.getLogger(__name__)


class FixtureEnterpriseProvider(EnterpriseProvider):
    """虚构演示数据（JSON 文件）。

    文件按名称与信用代码建双向索引，lookup 支持任一键命中。
    未收录的主体返回 found=False 并说明原因——fixture 库很小，
    这是预期行为而不是错误。
    """

    name = "fixture"

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._path = fixture_path or settings.enterprise_fixture_file
        self._index: dict[str, dict] | None = None

    def is_ready(self) -> bool:
        return self._path.exists()

    def _load(self) -> dict[str, dict]:
        if self._index is not None:
            return self._index
        if not self._path.exists():
            raise ProviderNotReadyError(f"企业核验演示数据缺失：{self._path}")
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ProviderNotReadyError(f"企业核验演示数据读取失败 {self._path.name}：{exc}") from exc

        index: dict[str, dict] = {}
        for record in payload.get("companies", []):
            if record.get("name"):
                index[record["name"].strip()] = record
            if record.get("credit_code"):
                index[record["credit_code"].strip().upper()] = record
        self._index = index
        return index

    def lookup(self, search_key: str) -> EnterpriseLookupResult:
        key = (search_key or "").strip()
        if not key:
            return EnterpriseLookupResult(
                found=False, note="查询关键字为空", provider=self.name
            )
        record = self._load().get(key) or self._load().get(key.upper())
        if record is None:
            return EnterpriseLookupResult(
                found=False,
                note="演示数据库（fixture）未收录该主体，仅含示例合同相关企业；"
                "真实核验请在 .env 中切换 ENTERPRISE_API_PROVIDER=qcc",
                provider=self.name,
            )
        return EnterpriseLookupResult(
            found=True,
            registration=RegistrationInfo(
                name=record.get("name", ""),
                credit_code=record.get("credit_code", ""),
                legal_person=record.get("legal_person", ""),
                registered_capital=record.get("registered_capital", ""),
                founding_date=record.get("founding_date", ""),
                status=record.get("status", ""),
                business_scope=record.get("business_scope", ""),
                address=record.get("address", ""),
                raw={"remark": record.get("remark", ""), "source": "fixture"},
            ),
            provider=self.name,
        )


class QccEnterpriseProvider(EnterpriseProvider):
    """企查查 MCP（企业工商信息）。

    接口形态：HTTP POST + JSON-RPC（tools/call），响应为 SSE 流，
    data 行内是 JSON-RPC result，其 content[0].text 里还有一层 JSON——
    两层都要解。中文请求体必须 UTF-8。
    """

    name = "qcc"
    _TOOL = "get_company_registration_info"

    _FIELD_MAP = {
        "企业名称": "name",
        "统一社会信用代码": "credit_code",
        "法定代表人": "legal_person",
        "注册资本": "registered_capital",
        "成立日期": "founding_date",
        "登记状态": "status",
        "经营范围": "business_scope",
        "注册地址": "address",
    }

    def is_ready(self) -> bool:
        return bool(settings.enterprise_api_base_url and settings.enterprise_api_key)

    def _parse_sse(self, text: str) -> dict:
        """从 SSE 文本中取出 JSON-RPC result。"""
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = json.loads(line[len("data:"):].strip())
            if isinstance(payload, dict) and "result" in payload:
                return payload
        raise ValueError("响应中未找到 JSON-RPC result（SSE 解析失败）")

    def _extract_text_payload(self, rpc_result: dict) -> dict:
        """content[0].text 是二次编码的 JSON 字符串。"""
        content = (rpc_result.get("result") or {}).get("content") or []
        for block in content:
            if block.get("type") == "text" and block.get("text"):
                return json.loads(block["text"])
        raise ValueError("响应 content 中无 text 载荷")

    def lookup(self, search_key: str) -> EnterpriseLookupResult:
        if not self.is_ready():
            raise ProviderNotReadyError(
                "企查查企业核验未就绪：请在 .env 中配置 "
                "ENTERPRISE_API_BASE_URL 与 ENTERPRISE_API_KEY"
            )
        key = (search_key or "").strip()
        if not key:
            return EnterpriseLookupResult(found=False, note="查询关键字为空", provider=self.name)

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": self._TOOL, "arguments": {"searchKey": key}},
        }
        with httpx.Client(timeout=settings.enterprise_timeout) as client:
            response = client.post(
                settings.enterprise_api_base_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.enterprise_api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            response.raise_for_status()
            data = self._parse_sse(response.text)

        inner = self._extract_text_payload(data)

        if "无匹配项" in inner:
            return EnterpriseLookupResult(
                found=False,
                note=str(inner.get("无匹配项") or "未匹配到该主体"),
                provider=self.name,
            )

        fields: dict = {}
        for source, target in self._FIELD_MAP.items():
            value = inner.get(source, "")
            if isinstance(value, list):
                value = "、".join(str(v) for v in value)
            fields[target] = str(value or "")
        fields["raw"] = inner

        registration = RegistrationInfo(**fields)
        if not registration.name and not registration.credit_code:
            return EnterpriseLookupResult(
                found=False,
                note=f"接口返回中无名称与信用代码字段：{inner}",
                provider=self.name,
            )
        return EnterpriseLookupResult(
            found=True, registration=registration, provider=self.name
        )
