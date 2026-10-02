"""合同文本 → 结构化合同。

两套实现，输出同一个 StructuredContract：
- RuleBasedStructurer：正则 + 关键词。离线可用、零成本、可解释，
  在格式规范的合同上召回率相当可观，是 Demo 的默认实现
- LLMStructurer：调用盘古大模型，能处理格式多变、表述口语化的合同

通过 CONTRACT_STRUCTURER 切换。这样"没有凭证"和"有凭证"两条路
共用同一套下游代码。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.providers.llm import extract_json
from app.core.providers.registry import get_llm_provider, require
from app.modules.contract_parser.facts import extract_facts
from app.modules.contract_parser.pdf_reader import PdfText
from app.modules.contract_parser.schema import (
    Clause,
    ContractField,
    Party,
    StructuredContract,
)

logger = logging.getLogger(__name__)

# 送入模型的最大字符数，防止超长合同撑爆上下文
_LLM_MAX_CHARS = 12000


# ============================================================
#  规则版
# ============================================================


@dataclass(frozen=True)
class FieldRule:
    key: str
    label: str
    patterns: tuple[str, ...]
    confidence: float = 0.8


_FIELD_RULES: tuple[FieldRule, ...] = (
    FieldRule(
        "contract_no",
        "合同编号",
        (r"合同编号[：:\s]*([A-Za-z0-9\-—一-龥]{2,40})",),
    ),
    FieldRule(
        "amount",
        "合同金额",
        (
            r"(?:合同总?金额|总价款|总金额|价款合计)[^0-9]{0,12}?([0-9][0-9,，]*(?:\.\d+)?\s*(?:万元|万|元))",
            r"人民币[^0-9]{0,6}?([0-9][0-9,，]*(?:\.\d+)?\s*(?:万元|万|元))",
        ),
        0.75,
    ),
    FieldRule(
        "sign_date",
        "签订日期",
        (
            r"(?:签订|签约|签署)日期[：:\s]*([12]\d{3}\s*[年\-/.]\s*\d{1,2}\s*[月\-/.]\s*\d{1,2}\s*日?)",
        ),
    ),
    FieldRule(
        "effective_date",
        "生效日期",
        (r"生效(?:日期|时间)[：:\s]*([^\n，。；]{2,30})",),
        0.7,
    ),
    FieldRule(
        "delivery_deadline",
        "交货期限",
        (
            r"(?:交货|交付|供货|采收)(?:时间|期限|日期|期)[：:\s]*([^\n，。；]{2,40})",
        ),
        0.7,
    ),
    FieldRule(
        "quality_standard",
        "质量标准",
        (r"质量(?:标准|要求|等级|规格)[：:\s]*([^\n，。；]{2,60})",),
        0.7,
    ),
    FieldRule(
        "payment_terms",
        "付款方式",
        (r"(?:付款|支付|结算)(?:方式|条件|办法|时间)[：:\s]*([^\n。；]{2,80})",),
        0.65,
    ),
    FieldRule(
        "breach_terms",
        "违约责任",
        (r"违约(?:责任|条款|金)[：:\s]*([^\n。；]{2,80})",),
        0.65,
    ),
)

_PARTY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("甲方", (r"甲\s*方[（(]?[^)）\n]{0,10}[)）]?[：:\s]*([^\n，。；]{2,40})",)),
    ("乙方", (r"乙\s*方[（(]?[^)）\n]{0,10}[)）]?[：:\s]*([^\n，。；]{2,40})",)),
    ("丙方", (r"丙\s*方[（(]?[^)）\n]{0,10}[)）]?[：:\s]*([^\n，。；]{2,40})",)),
)

# 统一社会信用代码：18 位，字母部分排除 I / O / S / V / Z
_CREDIT_CODE_RE = re.compile(r"[0-9A-HJ-NP-RT-UW-Y]{18}")

_CLAUSE_HEAD_RE = re.compile(r"(?m)^\s*(第[一二三四五六七八九十百零〇\d]+条[^\n]*)")

_EDGE_NOISE_RE = re.compile(r"^[\s：:，,。；;、]+|[\s：:，,。；;、]+$")
_LEADING_VERB_RE = re.compile(r"^(?:为|是|按照|按|采用|执行|应|应当)\s*")
# 形如「交货时间为」「付款方式为」的前缀：重复了字段名，对读者没有信息量
_LEADING_PHRASE_RE = re.compile(r"^[\u4e00-\u9fa5]{1,8}(?:为|是)\s*")


def _clean(value: str) -> str:
    """清理抽取值首尾的标点与「交货时间为 / 执行」这类引导词。

    规则抽取拿到的是原文片段，直接展示会带上这些噪音，
    它们对阅读者没有任何信息量。
    """
    value = _EDGE_NOISE_RE.sub("", value.strip())
    value = _LEADING_PHRASE_RE.sub("", value)
    value = _LEADING_VERB_RE.sub("", value)
    return _EDGE_NOISE_RE.sub("", value).strip()


# 抽取值以这些字符开头，通常说明命中的是正文里的偶然提及而非字段本身
_BAD_LEADING_CHARS = set("的了和与及或并且，,。；;：:")


def _quality_ok(value: str) -> bool:
    return len(value) >= 4 and value[0] not in _BAD_LEADING_CHARS


def _search(text: str, patterns: tuple[str, ...]) -> tuple[str, str]:
    """在多条正则间择优。

    规则抽取容易命中正文里的偶然提及——例如「符合质量标准的稻谷」
    中的「质量标准」，抽出来会得到毫无意义的「的稻谷」。
    因此收集全部候选，剔除明显是噪音的，再取第一个合格的。
    """
    fallback: tuple[str, str] = ("", "")
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            raw_value = (match.group(1) if match.groups() else match.group(0)).strip()
            value = _clean(raw_value)
            if not value:
                continue
            evidence = match.group(0).strip()[:160]
            if _quality_ok(value):
                return value, evidence
            if not fallback[0]:
                fallback = (value, evidence)
    return fallback


# 法条名称的结尾，用于排除《中华人民共和国民法典》这类误命中
_LAW_NAME_RE = re.compile(r"(法|典|条例|规定|办法|细则|意见|通知)$")


def _guess_title(text: str) -> str:
    """推断合同名称。

    优先取正文前几行——合同标题几乎总在文件最上方。
    若直接全文搜《》，会误命中正文里的法条引用，必须排除。
    """
    for line in (text or "").splitlines()[:6]:
        line = line.strip()
        if (
            4 <= len(line) <= 40
            and re.search(r"(合同|协议)$", line)
            and not _LAW_NAME_RE.search(line)
        ):
            return line

    for match in re.finditer(r"《([^》]{2,50})》", text or ""):
        candidate = match.group(1).strip()
        if re.search(r"(合同|协议)$", candidate):
            return candidate
    return ""


def _extract_parties(text: str) -> list[Party]:
    parties: list[Party] = []
    for role, patterns in _PARTY_RULES:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                name = match.group(1).strip()
                # 过滤掉"（以下简称…）"这类噪音
                name = re.sub(r"[（(].*?[)）]", "", name).strip()
                if name:
                    parties.append(Party(role=role, name=name))
                break

    codes = _CREDIT_CODE_RE.findall(text)
    for party, code in zip(parties, codes):
        party.credit_code = code
    return parties


def split_clauses(text: str) -> list[Clause]:
    """把合同正文切成条款。

    优先按"第X条"切分；切不出来时退化为按空行分段，
    保证下游始终有可检索的片段。

    第一个"第X条"**之前**的内容必须保留为 index=0 的「合同首部」。
    当事人名称、统一社会信用代码、合同编号都在这段里，
    而《订单农业合同规范指引》第一条要求的正是这些信息。
    丢掉它，「主体信息缺失」会被永远误报。
    """
    heads = list(_CLAUSE_HEAD_RE.finditer(text))

    if not heads:
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
        return [
            Clause(index=i + 1, title="", content=block[:2000])
            for i, block in enumerate(blocks[:40])
        ]

    clauses: list[Clause] = []

    preamble = text[: heads[0].start()].strip()
    if preamble:
        clauses.append(Clause(index=0, title="合同首部", content=preamble[:3000]))

    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        block = text[head.start() : end].strip()
        header = head.group(1).strip()
        title = re.split(r"[：:，。,、\s]", header, maxsplit=1)[0][:40]
        clauses.append(Clause(index=i + 1, title=title, content=block[:3000]))
    return clauses


class RuleBasedStructurer:
    """正则抽取。离线可用，是 Windows 开发期的默认实现。"""

    name = "rule"

    def structure(self, pdf_text: PdfText, filename: str = "") -> StructuredContract:
        text = pdf_text.text or ""

        contract = StructuredContract(
            source_file=filename,
            page_count=pdf_text.page_count,
            char_count=pdf_text.char_count,
            extractor=self.name,
            used_ocr=pdf_text.used_ocr,
            warnings=list(pdf_text.warnings),
            raw_text_preview=text[:600],
        )

        if not text.strip():
            contract.warnings.append("未抽取到任何文本，无法结构化")
            return contract

        contract.title = _guess_title(text)
        contract.parties = _extract_parties(text)

        fields: list[ContractField] = []
        for rule in _FIELD_RULES:
            value, evidence = _search(text, rule.patterns)
            fields.append(
                ContractField(
                    key=rule.key,
                    label=rule.label,
                    value=value,
                    confidence=rule.confidence if value else 0.0,
                    evidence=evidence,
                )
            )

        contract.fields = fields
        for item in fields:
            if item.value and hasattr(contract, item.key):
                setattr(contract, item.key, item.value)

        contract.clauses = split_clauses(text)
        # 结构化事实走纯规则：合规比对要求数值精确，不能交给模型
        contract.facts = extract_facts(text)

        missing = [f.label for f in fields if not f.value]
        if missing:
            contract.warnings.append("未抽取到的字段：" + "、".join(missing))
        if not contract.parties:
            contract.warnings.append("未识别到合同主体（甲乙方）")

        return contract


# ============================================================
#  大模型版
# ============================================================

_LLM_SYSTEM = """你是订单农业合同的解析专家。请从合同原文中抽取结构化信息。

要求：
1. 只输出 JSON，不要任何解释文字或 markdown 围栏
2. 每个字段都要给出 value（抽取值）和 evidence（支撑该值的合同原文片段，不超过 100 字）
3. 原文中没有的信息，value 留空字符串，不要编造
4. 金额务必保留单位

输出格式：
{
  "fields": {
    "contract_no":      {"value": "", "evidence": ""},
    "amount":           {"value": "", "evidence": ""},
    "sign_date":        {"value": "", "evidence": ""},
    "effective_date":   {"value": "", "evidence": ""},
    "delivery_deadline":{"value": "", "evidence": ""},
    "quality_standard": {"value": "", "evidence": ""},
    "payment_terms":    {"value": "", "evidence": ""},
    "breach_terms":     {"value": "", "evidence": ""}
  },
  "title": "",
  "parties": [
    {"role": "甲方", "name": "", "credit_code": "", "contact": "", "address": ""}
  ]
}"""

_FIELD_LABELS = {rule.key: rule.label for rule in _FIELD_RULES}
_FIELD_LABELS["title"] = "合同名称"


class LLMStructurer:
    """调用盘古大模型抽取。能应对格式多变的真实合同。"""

    name = "llm"

    def structure(self, pdf_text: PdfText, filename: str = "") -> StructuredContract:
        provider = get_llm_provider()
        require(provider, "合同结构化（大模型抽取）")

        text = (pdf_text.text or "").strip()
        contract = StructuredContract(
            source_file=filename,
            page_count=pdf_text.page_count,
            char_count=pdf_text.char_count,
            extractor=f"{self.name}:{provider.name}",
            used_ocr=pdf_text.used_ocr,
            warnings=list(pdf_text.warnings),
            raw_text_preview=text[:600],
        )

        if not text:
            contract.warnings.append("未抽取到任何文本，无法结构化")
            return contract

        truncated = text[:_LLM_MAX_CHARS]
        if len(text) > _LLM_MAX_CHARS:
            contract.warnings.append(
                f"合同文本超出 {_LLM_MAX_CHARS} 字，已截断后送入模型，尾部内容未参与抽取"
            )

        prompt = f"合同原文如下：\n\n{truncated}"

        try:
            data = provider.complete_json(prompt, system=_LLM_SYSTEM)
        except Exception as exc:
            logger.exception("大模型抽取失败")
            contract.warnings.append(f"大模型抽取失败，请检查凭证与网络：{exc}")
            return contract

        if data.get("_mock"):
            contract.warnings.append(
                "当前 LLM_PROVIDER=mock，返回的是占位结构。"
                "配置盘古凭证并将 LLM_PROVIDER 改为 pangu 后即可获得真实抽取结果。"
            )

        contract.title = str(data.get("title", "") or "")

        for key, label in _FIELD_LABELS.items():
            if key == "title":
                continue
            raw = (data.get("fields") or {}).get(key) or {}
            if isinstance(raw, str):
                raw = {"value": raw, "evidence": ""}
            value = str(raw.get("value", "") or "").strip()
            contract.fields.append(
                ContractField(
                    key=key,
                    label=label,
                    value=value,
                    confidence=0.9 if value else 0.0,
                    evidence=str(raw.get("evidence", "") or "").strip()[:160],
                )
            )
            if value and hasattr(contract, key):
                setattr(contract, key, value)

        for item in data.get("parties") or []:
            if not isinstance(item, dict):
                continue
            contract.parties.append(
                Party(
                    role=str(item.get("role", "") or ""),
                    name=str(item.get("name", "") or ""),
                    credit_code=str(item.get("credit_code", "") or ""),
                    contact=str(item.get("contact", "") or ""),
                    address=str(item.get("address", "") or ""),
                )
            )

        # 条款仍用规则切分：这是确定性的文本处理，不需要消耗模型额度
        contract.clauses = split_clauses(text)
        # 结构化事实也走规则：数值精度比"模型更聪明"更重要，
        # 且这样 rule / llm 两条路的 facts 完全一致，下游无需分支
        contract.facts = extract_facts(text)
        return contract


def get_structurer() -> RuleBasedStructurer | LLMStructurer:
    """按配置返回抽取器。"""
    key = settings.contract_structurer.lower()
    if key == "llm":
        return LLMStructurer()
    if key == "rule":
        return RuleBasedStructurer()
    raise ValueError(f"未知的 CONTRACT_STRUCTURER: {key!r}，可选 rule | llm")
