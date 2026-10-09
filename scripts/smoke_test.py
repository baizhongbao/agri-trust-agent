"""端到端冒烟测试：不启动服务，直接跑通合同解析链路。

用途：改完代码后快速确认「读取 → 结构化 → 落盘」没有断，
比启动整个服务再看接口快得多，也便于在 CI 中执行。

用法：
    python scripts/smoke_test.py
    python scripts/smoke_test.py --pdf data/samples/xxx.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND))

DEFAULT_PDF = PROJECT_ROOT / "data" / "samples" / "订单农业合同_示例.pdf"


def _date_text(value) -> str:
    """把 DateValue 渲染成人看的短文本。"""
    if value.kind == "range":
        return f"{value.start} ~ {value.end}（区间）"
    if value.kind == "relative":
        return f"{value.expr or value.raw}（相对表达）"
    if value.start:
        return f"{value.start}（绝对日期）"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="合同解析链路冒烟测试")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"[FAIL] 找不到测试文件：{args.pdf}", file=sys.stderr)
        print("       请先执行：python scripts/make_sample_contract.py", file=sys.stderr)
        return 1

    from app.core.config import BASE_DIR, settings
    from app.core.providers.registry import describe_providers
    from app.modules.contract_parser import service

    print("=" * 62)
    print("工作目录 :", BASE_DIR)
    print("配置来源 :", BASE_DIR / ".env", "存在" if (BASE_DIR / ".env").exists() else "缺失")
    print("提供者   :")
    for name, info in describe_providers().items():
        print(f"  - {name:<10} {info}")
    print("抽取器   :", settings.contract_structurer)
    print("=" * 62)

    pdf_bytes = args.pdf.read_bytes()
    print(f"输入文件 : {args.pdf.name}（{len(pdf_bytes)} 字节）")

    doc_id, contract = service.parse_contract(pdf_bytes, args.pdf.name)

    print(f"文档 ID  : {doc_id}")
    print(f"页数     : {contract.page_count}    字符数：{contract.char_count}")
    print(f"抽取器   : {contract.extractor}    OCR：{'是' if contract.used_ocr else '否'}")
    print("-" * 62)
    print(f"合同名称 : {contract.title or '(未识别)'}")

    print("\n合同主体：")
    if contract.parties:
        for party in contract.parties:
            code = party.credit_code or "—"
            print(f"  {party.role}：{party.name or '(未识别)'}   信用代码：{code}")
    else:
        print("  (未识别)")

    print("\n抽取字段：")
    hit = 0
    for item in contract.fields:
        mark = "OK " if item.value else "空 "
        if item.value:
            hit += 1
        print(f"  [{mark}] {item.label:<8} {item.value or '(未抽取到)'}")
        if item.evidence and item.value:
            print(f"          依据：{item.evidence[:70]}")

    total = len(contract.fields)
    print(f"\n字段命中率：{hit}/{total}")

    facts = contract.facts
    print("\n结构化事实（机器可推理，供下游校验 / 核验 / 模拟使用）：")

    def show(label: str, text: str) -> None:
        print(f"  {label:<8} {text or '—'}")

    show("金额", f"{facts.amount.value} 元" if facts.amount.value else "")
    show("单价", f"{facts.unit_price.value} 元" if facts.unit_price.value else "")
    show("签订日期", f"{facts.sign_date.start}（{facts.sign_date.kind}）" if facts.sign_date.start else "")
    show("生效日期", _date_text(facts.effective_date))
    show("交货期限", _date_text(facts.delivery))
    show("标的数量", f"{facts.quantity.value} {facts.quantity.unit}" if facts.quantity.value else "")
    show("种植面积", f"{facts.planted_area.value} {facts.planted_area.unit}" if facts.planted_area.value else "")
    show(
        "违约金",
        f"{facts.penalty.rate:.0%}（基数：{facts.penalty.base or '未指明'}）"
        if facts.penalty.rate
        else "",
    )
    show(
        "付款账期",
        f"{facts.payment_days} 个工作日（{facts.payment_trigger or '未指明触发条件'}）"
        if facts.payment_days
        else "",
    )

    if facts.quality_metrics:
        print("  质量指标 :")
        for metric in facts.quality_metrics:
            print(f"    {metric.name} {metric.op} {metric.value}{metric.unit}")
    else:
        print("  质量指标 : —")

    print(f"\n事实溯源：{len(facts.evidences)} 项带原文依据")

    # 解析质量门禁（L4）：必备字段缺失必须显式报出，不能只看"抽到几个字段"
    gate_info = contract.gate
    print(f"\n解析门禁：{gate_info.level.upper()} —— {gate_info.summary}")
    if gate_info.escalated:
        print(f"  L1→L2 升级：触发【{gate_info.escalation_reason}】→ {gate_info.escalation_outcome}")
        print(f"    {gate_info.escalation_note}")
    for failure in gate_info.failures:
        print(f"  [缺/{failure.severity}] {failure.label}：{failure.detail}")

    print(f"\n条款切分：共 {len(contract.clauses)} 条")
    for clause in contract.clauses[:3]:
        preview = clause.content.replace("\n", " ")[:60]
        print(f"  第{clause.index}条 {clause.title} | {preview}...")

    if contract.warnings:
        print("\n提示与告警：")
        for warning in contract.warnings:
            print(f"  ! {warning}")

    print("-" * 62)
    saved = settings.data_dir / "contracts" / f"{doc_id}.json"
    print(f"结果已落盘：{saved}")
    if not hit:
        print("冒烟测试未抽到任何字段，请检查数据或规则")
        return 1
    if gate_info.level == "blocked":
        print("冒烟测试未通过：解析门禁 blocked，必备字段缺失（见上）")
        return 1
    if gate_info.level == "degraded":
        print("冒烟测试通过（降级）：字段已抽出，但有关键要素缺失，下游结论需附带标注")
        return 0
    print("冒烟测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
