"""从合同全文抽取「可推理」的结构化事实。

为什么单独一层：
    `StructuredContract.fields` 面向展示——值是原文片段，人看得懂，
    但机器推理不了：「486,000元」不能参与计算，「2026年9月18日」不能比大小。
    `ContractFacts` 面向推理——金额是数值、日期是 ISO、质量指标是
    (名称, 比较符, 阈值) 三元组。下游的合规比对、企业核验、履约模拟都靠它。

三条原则：
    1. **数值一律用规则抽取，不交给大模型**。
       后面要拿这些数值做合规比对，模型把 14.5 读成 15 就是事故。
       大模型只负责理解语义（相对日期、条款分类），不负责读数。
    2. **抽不到就是空，绝不用 0 或猜测值填充**——与 evidence 原则一致。
    3. **每个事实都带 evidence**，结构化值同样要能回溯原文。

本模块是纯函数，不依赖 PDF 与网络，可直接单元测试。
"""

from __future__ import annotations

import re

from app.modules.contract_parser.schema import (
    ContractFacts,
    DateValue,
    Money,
    Quantity,
    Ratio,
)

_WS_RE = re.compile(r"\s+")
# 截取上下文时会带上前后句的标点，展示出来很脏，去掉
_SNIPPET_EDGE_RE = re.compile(r"^[\s。；，,、：:]+|[\s。；，,、：:]+$")


def _snippet(text: str, start: int, end: int, pad: int = 40) -> str:
    """截取命中位置附近的原文作为 evidence。"""
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    return _SNIPPET_EDGE_RE.sub("", _WS_RE.sub(" ", text[lo:hi]))[:160]


# ============================================================
#  中文数字
# ============================================================

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2, "三": 3, "叁": 3,
    "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8,
    "捌": 8, "九": 9, "玖": 9,
}
_CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CN_SECTIONS = {"万": 10000, "萬": 10000, "亿": 100000000, "億": 100000000}
_CN_NUM_RE = re.compile(r"[零〇一壹二贰两三四肆五伍六陆七柒八捌九玖十拾百佰千仟万萬亿億]{2,}")


def cn_to_number(text: str) -> float | None:
    """中文数字转阿拉伯数字。

    支持财务大写（「肆拾捌万陆仟」→ 486000）与日常写法（「二十」「一百零五」）。
    解析不了返回 None —— 不做任何猜测。
    """
    if not text:
        return None

    total = 0.0  # 已结算的「万 / 亿」段
    section = 0.0  # 当前段（千以内）
    number = 0.0  # 待结算的数字

    for char in text:
        if char in _CN_DIGITS:
            number = float(_CN_DIGITS[char])
        elif char in _CN_UNITS:
            # 「十五」里的「十」前面没有数字，按 1 计
            section += (number or 1.0) * _CN_UNITS[char]
            number = 0.0
        elif char in _CN_SECTIONS:
            section = (section + number) * _CN_SECTIONS[char]
            total += section
            section = 0.0
            number = 0.0
        else:
            return None

    return total + section + number


# ============================================================
#  金额
# ============================================================

_MONEY_RE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿|万|萬)?\s*(?:元|圆|块|人民币)")
_AMOUNT_TEXT_RE = re.compile(
    r"(?:合同总?金额|总金额|总价款|价款合计)[：:\s]*(?:人民币|RMB)?\s*"
    r"([0-9][0-9,，]*(?:\.[0-9]+)?\s*(?:亿|万|萬)?\s*元"
    r"|[零〇一壹二贰两三四肆五伍六陆七柒八捌九玖十拾百佰千仟万萬亿億]{2,}元)"
)


def parse_money(raw: str) -> Money:
    """解析金额。识别不了就留 value=None，绝不用 0 兜底。"""
    text = (raw or "").strip()
    if not text:
        return Money()

    plain = text.replace("，", ",").replace(",", "")
    match = _MONEY_RE.search(plain)
    if match:
        value = float(match.group(1))
        if match.group(2) in ("万", "萬"):
            value *= 10000
        elif match.group(2) == "亿":
            value *= 100000000
        return Money(value=value, currency="CNY", raw=text)

    cn_match = _CN_NUM_RE.search(text)
    if cn_match:
        value = cn_to_number(cn_match.group(0))
        if value:
            return Money(value=value, currency="CNY", raw=text)

    return Money(raw=text)


# ============================================================
#  日期
# ============================================================

_DATE_TOKEN = r"([12]\d{3})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*日?"
_DATE_RE = re.compile(_DATE_TOKEN)
_RANGE_SEP = r"(?:至|到|—|–|－|~|～)"
_RANGE_RE = re.compile(_DATE_TOKEN + r"[^\n]{0,6}?" + _RANGE_SEP + r"[^\n]{0,6}?" + _DATE_TOKEN)
_RELATIVE_RE = re.compile(r"自\s*([^\n。；，]{2,20}?)\s*之日起")


def _to_iso(year: str, month: str, day: str) -> str | None:
    y, m, d = int(year), int(month), int(day)
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def parse_date(raw: str) -> DateValue:
    """解析日期为 DateValue。

    判断顺序很关键：
      1. 区间（「至 / 到」两侧都是日期）
      2. 「自…之日起」→ relative。**必须早于绝对日期判断**，否则
         「本合同自双方签字盖章之日起生效，签订日期：2026年9月18日」
         会被误判成绝对日期——而相对日期本身就是风险信号，不能被吞掉
      3. 绝对日期
      4. 其余带内容的表达 → relative（如「验收合格后15个工作日内」）
    """
    text = (raw or "").strip()
    if not text:
        return DateValue()

    range_match = _RANGE_RE.search(text)
    if range_match:
        start = _to_iso(*range_match.group(1, 2, 3))
        end = _to_iso(*range_match.group(4, 5, 6))
        if start and end:
            return DateValue(kind="range", start=start, end=end, raw=text)

    relative_match = _RELATIVE_RE.search(text)
    if relative_match:
        return DateValue(
            kind="relative", expr=f"{relative_match.group(1)}之日起", raw=text
        )

    absolute_match = _DATE_RE.search(text)
    if absolute_match:
        iso = _to_iso(*absolute_match.group(1, 2, 3))
        if iso:
            return DateValue(kind="absolute", start=iso, raw=text)

    if len(text) >= 4:
        return DateValue(kind="relative", expr=text[:40], raw=text)

    return DateValue(raw=text)


# ============================================================
#  质量指标 / 数量 / 面积
# ============================================================

_OP_ALIASES: tuple[tuple[str, str], ...] = (
    ("不高于", "<="),
    ("不超过", "<="),
    ("不大于", "<="),
    ("不超", "<="),
    ("最高", "<="),
    ("不低于", ">="),
    ("不小于", ">="),
    ("不少于", ">="),
    ("最低", ">="),
    ("≥", ">="),
    ("≤", "<="),
    (">=", ">="),
    ("<=", "<="),
)
_OP_LOOKUP = dict(_OP_ALIASES)
_OP_PATTERN = "(?:" + "|".join(re.escape(alias) for alias, _ in _OP_ALIASES) + ")"

# 指标名限 2~8 个汉字、非贪婪——只吃到比较符之前为止
_METRIC_RE = re.compile(
    r"([\u4e00-\u9fa5]{2,8}?)\s*(" + _OP_PATTERN + r")\s*([0-9]+(?:\.[0-9]+)?)\s*(%|％|‰)"
)

# 指标名尾部的冗余词：「水分含量」→「水分」
_METRIC_NAME_NOISE = ("含量", "指标", "限值", "限量", "数值", "要求")
# 这些词打头的「指标」其实不是质量指标（多是违约金 / 费用比例）
_METRIC_BLACKLIST = (
    "金额", "价款", "总价", "违约", "定金", "订金", "预付", "费用", "利息",
    "比例", "税", "折", "利率", "单价", "赔偿",
)


def _clean_metric_name(name: str) -> str:
    cleaned = name
    for noise in _METRIC_NAME_NOISE:
        if cleaned.endswith(noise) and len(cleaned) > len(noise):
            cleaned = cleaned[: -len(noise)]
    return cleaned


def extract_quality_metrics(text: str) -> list[Quantity]:
    """抽取质量指标，如「水分含量不高于14.5%」→ (水分, <=, 14.5%)。

    这是把「相似度检索」升级为「合规比对」的关键输入。
    """
    metrics: list[Quantity] = []
    seen: set[str] = set()

    for match in _METRIC_RE.finditer(text or ""):
        name = _clean_metric_name(match.group(1))
        if not name or name in seen:
            continue
        if any(bad in name for bad in _METRIC_BLACKLIST):
            continue

        op = _OP_LOOKUP.get(match.group(2), "")
        value = float(match.group(3))
        if not op or value <= 0:
            continue

        seen.add(name)
        metrics.append(
            Quantity(
                name=name,
                op=op,
                value=value,
                unit="%" if match.group(4) in ("%", "％") else "‰",
                raw=match.group(0).strip(),
            )
        )

    return metrics


_QUANTITY_RE = re.compile(
    r"(?:预计收购量|收购数量|收购量|订购量|订货量|数量)"
    r"[^0-9]{0,8}?([0-9]+(?:\.[0-9]+)?)\s*(吨|公斤|千克|斤|担|件|箱|袋|包)"
)
_AREA_RE = re.compile(
    r"(?:种植面积|播种面积|面积)"
    r"[^0-9]{0,6}?([0-9]+(?:\.[0-9]+)?)\s*(亩|公顷|平方米|平方)"
)
_UNIT_PRICE_RE = re.compile(
    r"(?:单价|每吨|每公斤|每斤|收购价|保底价)"
    r"[^0-9]{0,10}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*元"
)


def _extract_quantity(text: str, name: str) -> Quantity:
    match = _QUANTITY_RE.search(text or "")
    if not match:
        return Quantity()
    return Quantity(
        name=name,
        op="=",
        value=float(match.group(1)),
        unit=match.group(2),
        raw=match.group(0).strip(),
    )


# ============================================================
#  比例类（违约金 / 定金）
# ============================================================

_PENALTY_SENTENCE_RE = re.compile(r"[^。；\n]{0,80}违约金[^。；\n]{0,80}")
_PERCENT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(%|％)")
_PENALTY_BASE_RE = re.compile(
    r"(合同总?金额|合同总?价款|总价款|合同总额|货款总额|未履行部分|实际损失)"
)
_PER_DAY_RE = re.compile(r"(?:每日|每天|按日|日万分)")

_DEPOSIT_RE = re.compile(r"(定金|订金|预付款)[^。；\n]{0,20}?([0-9]+(?:\.[0-9]+)?)\s*(%|％)")


def extract_penalty(text: str) -> tuple[Ratio, str]:
    """抽取违约金约定。

    只认与「违约金」出现在同一句的百分比，避免把定金比例、
    税率之类的比例错认成违约金。
    """
    for sentence in _PENALTY_SENTENCE_RE.finditer(text or ""):
        fragment = sentence.group(0)
        percent = _PERCENT_RE.search(fragment)
        if not percent:
            continue

        base_match = _PENALTY_BASE_RE.search(fragment)
        ratio = Ratio(
            rate=float(percent.group(1)) / 100.0,
            base=base_match.group(1) if base_match else "",
            kind="per_day" if _PER_DAY_RE.search(fragment) else "ratio",
            raw=_WS_RE.sub(" ", fragment).strip()[:160],
        )
        return ratio, _snippet(text, sentence.start(), sentence.end())

    return Ratio(), ""


def extract_deposit(text: str) -> tuple[Ratio, str]:
    """抽取定金 / 预付款比例。"""
    match = _DEPOSIT_RE.search(text or "")
    if not match:
        return Ratio(), ""
    return (
        Ratio(
            rate=float(match.group(2)) / 100.0,
            base=match.group(1),
            kind="ratio",
            raw=match.group(0).strip()[:160],
        ),
        _snippet(text, match.start(), match.end()),
    )


# ============================================================
#  付款账期
# ============================================================

_PAY_DAYS_RE = re.compile(r"([0-9]{1,3})\s*个?\s*(?:工作日|日|天)\s*内")
# 付款前置条件——「验收合格后付款」意味着回款挂在验收上，是风险点
_PAY_TRIGGERS = ("验收合格", "验收", "收到货物", "收货", "交货", "交付", "签收", "结算")


def extract_payment_days(text: str) -> tuple[int | None, str]:
    """抽取付款账期天数与前置条件。"""
    match = _PAY_DAYS_RE.search(text or "")
    if not match:
        return None, ""

    days = int(match.group(1))
    window = (text or "")[max(0, match.start() - 30) : match.end()]
    trigger = next((word for word in _PAY_TRIGGERS if word in window), "")
    return days, f"{trigger}后" if trigger else ""


# ============================================================
#  字段定位（沿用 structurer 里已有的字段正则，保持一致）
# ============================================================

_SIGN_DATE_RE = re.compile(r"(?:签订|签约|签署)(?:日期|时间)[：:\s]*([^\n。；]{2,30})")
_EFFECTIVE_RE = re.compile(r"生效(?:日期|时间)[：:\s]*([^\n。；]{2,40})")
_DELIVERY_RE = re.compile(
    r"(?:交货|交付|供货|采收)(?:时间|期限|日期|期)[：:\s]*([^\n。；，]{2,60})"
)


def extract_facts(text: str) -> ContractFacts:
    """从合同全文抽取结构化事实。纯函数，便于单元测试。"""
    facts = ContractFacts()
    body = text or ""
    if not body.strip():
        return facts

    evidences = facts.evidences

    # ---- 合同总金额 ----
    match = _AMOUNT_TEXT_RE.search(body)
    if match:
        facts.amount = parse_money(match.group(0))
        evidences["amount"] = _snippet(body, match.start(), match.end())

    # ---- 单价 ----
    match = _UNIT_PRICE_RE.search(body)
    if match:
        facts.unit_price = parse_money(match.group(0))
        evidences["unit_price"] = _snippet(body, match.start(), match.end())

    # ---- 签订日期 ----
    match = _SIGN_DATE_RE.search(body)
    if match:
        facts.sign_date = parse_date(match.group(1))
        evidences["sign_date"] = _snippet(body, match.start(), match.end())

    # ---- 生效日期（多为「自…之日起」，识别为 relative 才是对的）----
    match = _EFFECTIVE_RE.search(body)
    if match:
        facts.effective_date = parse_date(match.group(1))
        evidences["effective_date"] = _snippet(body, match.start(), match.end())

    # ---- 交货期限（常见区间）----
    match = _DELIVERY_RE.search(body)
    if match:
        facts.delivery = parse_date(match.group(1))
        evidences["delivery"] = _snippet(body, match.start(), match.end())

    # ---- 标的数量与种植面积 ----
    facts.quantity = _extract_quantity(body, "收购量")
    if facts.quantity.value is not None:
        match = _QUANTITY_RE.search(body)
        if match:
            evidences["quantity"] = _snippet(body, match.start(), match.end())

    area_match = _AREA_RE.search(body)
    if area_match:
        facts.planted_area = Quantity(
            name="种植面积",
            op="=",
            value=float(area_match.group(1)),
            unit=area_match.group(2),
            raw=area_match.group(0).strip(),
        )
        evidences["planted_area"] = _snippet(body, area_match.start(), area_match.end())

    # ---- 违约金 / 定金 ----
    facts.penalty, penalty_evidence = extract_penalty(body)
    if penalty_evidence:
        evidences["penalty"] = penalty_evidence

    facts.deposit, deposit_evidence = extract_deposit(body)
    if deposit_evidence:
        evidences["deposit"] = deposit_evidence

    # ---- 付款账期 ----
    facts.payment_days, facts.payment_trigger = extract_payment_days(body)
    pay_match = _PAY_DAYS_RE.search(body)
    if pay_match and facts.payment_days is not None:
        evidences["payment_days"] = _snippet(body, pay_match.start(), pay_match.end())

    # ---- 质量指标 ----
    facts.quality_metrics = extract_quality_metrics(body)
    if facts.quality_metrics:
        evidences["quality_metrics"] = "；".join(
            metric.raw for metric in facts.quality_metrics
        )[:160]

    return facts
