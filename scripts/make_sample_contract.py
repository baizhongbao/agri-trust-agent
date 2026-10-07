"""生成示例合同 PDF，用于本地开发与演示。

用 PyMuPDF 内置的简体中文字体（china-s）渲染，避免依赖系统字体，
因此在 Windows / Linux / 容器内渲染结果完全一致。

用法：
    python scripts/make_sample_contract.py
    python scripts/make_sample_contract.py --out data/samples/我的合同.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "data" / "samples" / "订单农业合同_示例.pdf"

FONT = "china-s"  # PyMuPDF 内置简体中文字体
FONT_SIZE = 10.5
LINE_HEIGHT = 17
MARGIN_X = 56
MARGIN_Y = 60
A4_WIDTH = 595
A4_HEIGHT = 842

SAMPLE_TEXT = """订单农业合同

合同编号：DDNY-2026-0918

甲方（收购方）：明光市丰谷粮油有限公司
统一社会信用代码：913411826123456782
联系人：王建国
地址：安徽省明光市工业园区兴农路18号

乙方（种植方）：明光市绿野家庭农场
统一社会信用代码：91341182687654321U
联系人：李秀兰

根据《中华人民共和国民法典》及相关法律法规，甲乙双方本着平等自愿、诚实信用的原则，
就订单农业种植收购事宜达成如下协议：

第一条 订单标的
乙方按甲方订单要求种植优质水稻品种南粳46，种植面积320亩，甲方提供种子及技术指导。

第二条 数量与金额
甲方收购乙方全部符合质量标准的稻谷，预计收购量180吨，合同总金额人民币486,000元。

第三条 质量标准
质量标准执行GB/T 1354-2018大米国家标准，水分含量不高于14.5%，杂质含量不高于1.0%，
整精米率不低于55%。

第四条 交货期限
交货时间为2026年11月1日至2026年11月30日，乙方负责将货物运送至甲方指定仓库，
运输费用由甲方承担。

第五条 付款方式
甲方在收到货物并验收合格后15个工作日内，通过银行转账方式支付货款。

第六条 违约责任
任何一方违约，应向对方支付合同总金额10%的违约金；因乙方原因导致质量标准不达标的，
甲方有权拒收并要求赔偿实际损失。

第七条 争议解决
因本合同发生的争议，双方应友好协商解决；协商不成的，提交明光市人民法院诉讼解决。

第八条 生效日期
本合同自双方签字盖章之日起生效，签订日期：2026年9月18日。

甲方（盖章）：明光市丰谷粮油有限公司
乙方（盖章）：明光市绿野家庭农场
"""


def build_pdf(out_path: Path, text: str = SAMPLE_TEXT) -> Path:
    # PyMuPDF >= 1.24 推荐 import pymupdf；旧版仅有 fitz 模块名
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=A4_WIDTH, height=A4_HEIGHT)

    y = MARGIN_Y
    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        # 标题居中放大
        if line == text.splitlines()[0] and line:
            width = fitz.get_text_length(line, fontname=FONT, fontsize=FONT_SIZE + 6)
            page.insert_text(
                ((A4_WIDTH - width) / 2, y),
                line,
                fontname=FONT,
                fontsize=FONT_SIZE + 6,
            )
            y += LINE_HEIGHT + 8
            continue

        if y > A4_HEIGHT - MARGIN_Y:
            page = doc.new_page(width=A4_WIDTH, height=A4_HEIGHT)
            y = MARGIN_Y

        page.insert_text((MARGIN_X, y), line, fontname=FONT, fontsize=FONT_SIZE)
        y += LINE_HEIGHT

    doc.save(str(out_path))
    doc.close()
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="生成示例合同 PDF")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出路径")
    args = parser.parse_args()

    try:
        path = build_pdf(args.out)
    except ImportError:
        print("未安装 PyMuPDF，请先执行 pip install pymupdf", file=sys.stderr)
        return 1

    print(f"已生成示例合同：{path}")
    print(f"文件大小：{path.stat().st_size} 字节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
