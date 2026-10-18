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
from dataclasses import dataclass

from app.core.config import settings
from app.core.providers.registry import get_llm_provider, require
from app.modules.contract_parser.facts import extract_facts
from app.modules.contract_parser.pdf_reader import PdfText
from app.modules.contract_parser.schema import (
    ARB_SINGLE,
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
    ("甲方", (r"甲\s*方\s*(?:[（(][^)）\n]{0,12}[)）])?\s*[：:]?(?:单位名称[：:])?([^\n，。；：:]{2,40})",)),
    ("乙方", (r"乙\s*方\s*(?:[（(][^)）\n]{0,12}[)）])?\s*[：:]?(?:单位名称[：:])?([^\n，。；：:]{2,40})",)),
    ("丙方", (r"丙\s*方\s*(?:[（(][^)）\n]{0,12}[)）])?\s*[：:]?(?:单位名称[：:])?([^\n，。；：:]{2,40})",)),
    # 订单农业合同常以「供方/需方」替代「甲方/乙方」——规则顺序放在甲乙之后，
    # 避免优先捕获正文里的「甲方」等词；同位「需方:单位名称:李姜伟」需逐个冒号截断
    ("供方", (r"供\s*方\s*(?:[（(][^)）\n]{0,12}[)）])?\s*[：:](?:单位名称[：:])?([^\n，。；：:]{2,40})",)),
    ("需方", (r"需\s*方\s*(?:[（(][^)）\n]{0,12}[)）])?\s*[：:](?:单位名称[：:])?([^\n，。；：:]{2,40})",)),
)

# 统一社会信用代码：18 位，字母部分排除 I / O / S / V / Z
_CREDIT_CODE_RE = re.compile(r"[0-9A-HJ-NP-RT-UW-Y]{18}")

# 信用代码与主体名称的最大关联距离（字符）。超出则视为无法归属，宁可不填也不硬猜。
# 示例合同里代码紧跟在名称下一行，距离约 15；这里给足 OCR 换行/空白的余量。
_CREDIT_CODE_MAX_DISTANCE = 120

_CLAUSE_HEAD_RE = re.compile(r"(?m)^\s*(第[一二三四五六七八九十百零〇\d]+条[^\n]*)")

# 直接从标签:值 行流中剥离出的「四处重复的页眉/签名区」噪声（跨页逐页重复捞取）
# 只匹配签名类标签，不匹配 供方/需方/甲方/乙方——命名行是真实主体信息，不是噪声
_REPEATED_BLOCK_RE = re.compile(
    r"^(?:法定代表人或授权代表签字/盖章|法定代表人|法人代表|法人|代表)"
    r"[（(]?[^)）\n:：]{0,12}[)）]?[：:]\s*\S+$",
)

# 标签:值 行流关键字段，出现则说明该段是签约页/主体信息区，而非可检索的条款正文
_HEADER_LINE_RE = re.compile(
    r"^(?:单位名称|法定代表人|法人代表|法人|法定代表人或授权代表签字/盖章|"
    r"供方|需方|甲方|乙方|丙方|签订日期|签署日期|签约日期|签订地点)$",
)

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


def _assign_credit_codes(parties: list[Party], text: str) -> list[str]:
    """按「就近原则」把统一社会信用代码归属到各主体，返回未能归属的代码列表。

    事故背景：原实现用 ``zip(parties, findall(codes))`` 按出现顺序硬配对。
    当代码出现在主体名称之前、只有一个主体带码、或正文里混入其他 18 位串时，
    会把甲的代码挂到乙身上，且**静默**污染下游 L1 校验位与 L3 交叉校验——
    最终给出一个"看起来很确定"的错误结论。

    现在改为：以主体名称在原文中的位置为锚，取距离最近的代码，
    按距离升序一对一贪心绑定；超出关联窗口的代码宁可不填，也不硬猜。
    一对一贪心天然处理"代码共用一个区块"的情形——离谁近就归谁。
    """
    occurrences = [(m.group(0), m.start()) for m in _CREDIT_CODE_RE.finditer(text)]
    if not occurrences or not parties:
        return [code for code, _ in occurrences]

    anchors: list[list[int]] = []
    for party in parties:
        positions = (
            [m.start() for m in re.finditer(re.escape(party.name), text)]
            if party.name
            else []
        )
        anchors.append(positions)

    candidates: list[tuple[int, int, int]] = []
    for party_index, positions in enumerate(anchors):
        if not positions:
            continue
        for code_index, (_, code_pos) in enumerate(occurrences):
            distance = min(abs(code_pos - pos) for pos in positions)
            candidates.append((distance, party_index, code_index))
    candidates.sort()

    assigned_parties: set[int] = set()
    used_codes: set[int] = set()
    for distance, party_index, code_index in candidates:
        if distance > _CREDIT_CODE_MAX_DISTANCE:
            continue
        if party_index in assigned_parties or code_index in used_codes:
            continue
        parties[party_index].credit_code = occurrences[code_index][0]
        assigned_parties.add(party_index)
        used_codes.add(code_index)

    return [code for i, (code, _) in enumerate(occurrences) if i not in used_codes]


def _extract_parties(text: str) -> tuple[list[Party], list[str]]:
    """抽取合同主体，并把信用代码按就近原则归属。返回 (主体列表, 未归属代码列表)。"""
    parties: list[Party] = []
    for role, patterns in _PARTY_RULES:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                name = match.group(1).strip()
                # 过滤掉"（以下简称…）"这类噪音
                name = re.sub(r"[（(].*?[)）]", "", name).strip()
                # 剥离「单位名称:」标签本身（正则已用非捕获组绕开，此处兜底）
                name = re.sub(r"^(?:单位名称)\s*[：:]?", "", name).strip()
                # 截掉姓名后粘连的后续段落：标签:值 模式的合同同行常附带其他字段
                name = re.split(
                    r"\s+(?:法定代表|委托代理|法人代表|开户|账号|联系|地址|电话)", name
                )[0].strip()
                # 主体名比字段值短得多（自然人 2~3 字），不能用 _quality_ok 的 len>=4 门槛
                if (
                    len(name) >= 2
                    and name[0] not in _BAD_LEADING_CHARS
                    and re.search(r"[\u4e00-\u9fa5]", name)
                ):
                    parties.append(Party(role=role, name=name))
                    break

    unmatched_codes = _assign_credit_codes(parties, text)
    return parties, unmatched_codes


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
        return _split_without_heads(text)

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


def _split_without_heads(text: str) -> list[Clause]:
    """合同没有「第X条」标题时的兜底切分。

    至少分为「首部（主体/编号区）」与「后续正文」两段，保证下游
    始终有可检索的片段，而不是把整份合同揉成一条。

    注意：合同的**签字盖章页**往往在每页页眉/页脚重复出现（「法定代表人或
    授权代表签字/盖章」「法人代表」等逐页捞取），必须过滤，否则整页签名区
    会被当成一条正文条款。
    """
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return []

    # 第一段：所有纯头部标签行（单位名称/甲方/法定代表人…及其值）连续出现的部分
    head_end = 0
    while head_end < len(lines) and _HEADER_LINE_RE.match(lines[head_end].strip()):
        head_end += 1
    # 把夹在中间、以非关键字开头的行也并入主体块：它们通常是「地址/联系人」的换行
    while head_end < len(lines) and not _HEADER_LINE_RE.match(lines[head_end].strip()):
        head_end += 1
    header_lines = lines[:head_end]
    body_lines = lines[head_end:]

    clauses: list[Clause] = []

    # 首部：过滤掉重复的「法人代表/签字盖章」噪声后仍保留关键信息
    cleaned = _strip_signature_noise("\n".join(header_lines), keep_first=True)
    if cleaned:
        clauses.append(Clause(index=0, title="合同首部", content=cleaned[:3000]))

    # 正文块：按空行分组，再去做签名噪声清洗
    for block in re.split(r"\n\s*\n", "\n".join(body_lines)):
        block = block.strip()
        if not block:
            continue
        cleaned = _strip_signature_noise(block)
        if cleaned:
            clauses.append(
                Clause(index=len(clauses), title="", content=cleaned[:2000])
            )
    return clauses


def _strip_signature_noise(block: str, keep_first: bool = False) -> str:
    """剥离「法人代表:李姜伟」「签字/盖章:谭小东」这类签名/页眉噪声行。

    keep_first=True 时保留首个签名行——项目要求「抽取值必须带证据」，
    主体区里的签名行本身也是合同原文的一部分（尤其首部需要保留签字痕迹）。
    """
    out: list[str] = []
    skip_next_repeat = False
    for ln in block.splitlines():
        line = ln.strip()
        if not line:
            continue
        if _REPEATED_BLOCK_RE.match(line):
            if keep_first and not skip_next_repeat:
                skip_next_repeat = True
                out.append(line)
            continue
        out.append(line)
    cleaned = "\n".join(out).strip()
    # 该块几乎全部是签名行（超过 7 成）时，直接视为无正文
    if not cleaned:
        return ""
    # 首部模式：只判断纯噪声块，保留签名首行后其余皆可入
    return cleaned[:2000]


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
        contract.parties, unmatched_codes = _extract_parties(text)
        if unmatched_codes:
            contract.warnings.append(
                "以下统一社会信用代码未能归属到具体主体（名称与代码距离过远或数量不匹配）："
                + "、".join(unmatched_codes)
                + "。企业核验将主要按主体名称查询，建议人工核对。"
            )

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
                    # 单源：没有第二个抽取器可比，confidence 只是本抽取器的静态先验
                    agreement=ARB_SINGLE,
                    source="rule",
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
                    # 单源：0.9 是写死的先验，不代表"模型很确信"——只有双源一致才叫证据
                    agreement=ARB_SINGLE,
                    source="llm",
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
