"""裁判文书知识提炼脚本（数据准备工具，非运行时代码）。

流程：
    docs/裁判文书案例/案例文件/*.doc(.x)
        │  Word COM 批量转纯文本（缓存，只做一次）
        ▼
    data/knowledge/raw/案例NN.txt
        │  deepseek-flash 结构化提炼（逐份调用，断点续传）
        ▼
    data/knowledge/cases/案例NN.json
        │  汇总
        ▼
    data/knowledge/cases_summary.json + docs/知识提炼/裁判案例提炼.md（人工复核稿）

API 配置从 .env 读取（不入库）：
    EXTRACTION_API_KEY   —— tokenrhythm.studio 的 API Key
    EXTRACTION_BASE_URL  —— 默认 https://tokenrhythm.studio/v1
    EXTRACTION_MODEL     —— 默认 deepseek-flash

用法：
    python scripts/extract_knowledge.py --extract-texts   # 仅提取文本（需本机 Word）
    python scripts/extract_knowledge.py --case 19         # 提炼单份案例
    python scripts/extract_knowledge.py --all             # 提炼全部（断点续传）
    python scripts/extract_knowledge.py --summarize       # 汇总生成复核稿
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

CASES_DIR = PROJECT_ROOT / "docs" / "裁判文书案例" / "案例文件"
RAW_DIR = PROJECT_ROOT / "data" / "knowledge" / "raw"
OUT_DIR = PROJECT_ROOT / "data" / "knowledge" / "cases"
SUMMARY_JSON = PROJECT_ROOT / "data" / "knowledge" / "cases_summary.json"
REVIEW_MD = PROJECT_ROOT / "docs" / "知识提炼" / "裁判案例提炼.md"

MAX_INPUT_CHARS = 24000  # 判决书最长约 2 万字，超长截中间保首尾
RETRY_LIMIT = 3
RETRY_WAIT = 5
CONCURRENCY = 4  # 纯 API 调用，并发跑；太高容易撞限流


# ---------------- 配置（凭证不入库，从 .env 读） ----------------

def load_extraction_config() -> dict[str, str]:
    env_file = PROJECT_ROOT / ".env"
    values: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*([A-Z_]+)\s*=\s*(.*?)\s*$", line)
            if match:
                values[match.group(1)] = match.group(2)
    return {
        "api_key": values.get("EXTRACTION_API_KEY", ""),
        "base_url": values.get("EXTRACTION_BASE_URL", "https://tokenrhythm.studio/v1"),
        "model": values.get("EXTRACTION_MODEL", "deepseek-flash"),
    }


# ---------------- 文本提取（Word COM） ----------------

def extract_texts_with_word() -> int:
    """批量把案例 .doc/.docx 转纯文本缓存。只处理缓存里没有的文件。"""
    import win32com.client

    files = sorted(
        f for f in CASES_DIR.iterdir() if f.suffix.lower() in (".doc", ".docx")
    )
    pending = [f for f in files if not (RAW_DIR / f"{f.stem}.txt").exists()]
    if not pending:
        print(f"文本缓存已齐全（{len(files)} 份），无需重新提取")
        return len(files)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    converted = 0
    try:
        for i, path in enumerate(pending, 1):
            try:
                doc = word.Documents.Open(str(path.resolve()), ReadOnly=True)
                text = doc.Content.Text
                doc.Close(False)
                clean = text.replace("\r", "\n").replace("\x07", "")
                (RAW_DIR / f"{path.stem}.txt").write_text(clean, encoding="utf-8")
                converted += 1
                print(f"[{i}/{len(pending)}] {path.stem[:46]} → {len(clean)} 字")
            except Exception as exc:
                print(f"[{i}/{len(pending)}] 失败 {path.stem[:46]}：{exc}")
    finally:
        word.Quit()
    print(f"完成：新转换 {converted} 份，缓存共 {len(list(RAW_DIR.glob('*.txt')))} 份")
    return converted


# ---------------- LLM 提炼 ----------------

SYSTEM_PROMPT = """你是农业合同法律风控知识工程师，任务是把一份裁判文书（判决书/裁定书）提炼成结构化的风控知识条目，供「订单农业合同可信性 Agent」的履约模拟与风险预警模块使用。

严格纪律：
1. 只依据文书原文，不得编造。文书里没有的信息一律留空字符串或空数组。
2. 每个 risk_rules 条目的 ruling 必须引用/忠实转述法院的认定，不得加入自己的法律观点。
3. 案号、法院、当事人名称逐字照抄原文。
4. 与订单农业合同（种植/养殖回收、农产品购销）风控无关的文书，relevance 填 low。
5. 只输出一个 JSON 对象，不要输出任何其他文字、不要用 markdown 代码围栏。

输出 JSON Schema：
{
  "case_no": "案号，如（2022）辽09民终103号",
  "title": "案件名称（当事人+案由）",
  "court": "审理法院",
  "doc_type": "判决书|裁定书|调解书",
  "contract_type": "合同类型，如 种植回收合同/土地承包经营权转让合同/买卖合同",
  "category": "分类枚举：订单农业购销|土地流转|农资采购|农业保险|农机作业|其他",
  "core_dispute": "核心争议，一句话",
  "holding": "裁判要旨，法院怎么判的、依据什么，2-3 句",
  "contract_amount": "合同金额（原文表述，没有则留空）",
  "penalty_clause": "违约金/定金条款的原文要点（没有则留空）",
  "risk_rules": [
    {
      "scenario": "风险场景枚举：价格波动|自然灾害|质量争议|拖欠款项|擅自处分|主体不适格|合同解除|其他",
      "signal": "合同中的什么约定或情形触发了本案风险",
      "ruling": "法院对该问题的认定（忠实转述）",
      "lesson": "给订单农业合同起草/审查的一条可操作建议"
    }
  ],
  "relevance": "high|medium|low —— 本案对订单农业合同风控的参考价值",
  "key_excerpt": "支撑裁判要旨的原文关键片段，200 字以内"
}"""


def _clip_text(text: str, limit: int = MAX_INPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = text[: int(limit * 0.7)]
    tail = text[-int(limit * 0.3):]
    return f"{head}\n\n[……中间内容略……]\n\n{tail}"


def _clean_json(content: str) -> dict:
    """清洗 LLM 输出：去围栏、截取首个 { 到末个 }、解析。"""
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"输出中找不到 JSON 对象：{text[:120]}")
    return json.loads(text[start : end + 1])


def call_llm(config: dict[str, str], prompt: str) -> dict:
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 6000,
    }
    last_error: Exception | None = None
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            with httpx.Client(timeout=300, trust_env=False) as client:
                response = client.post(
                    f"{config['base_url'].rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            content = data["choices"][0]["message"]["content"]
            return _clean_json(content)
        except Exception as exc:  # 网络 / 解析失败统一重试
            last_error = exc
            print(f"    第 {attempt} 次尝试失败：{exc}")
            if attempt < RETRY_LIMIT:
                time.sleep(RETRY_WAIT * attempt)
    raise RuntimeError(f"LLM 调用最终失败：{last_error}")


def extract_case(stem: str, config: dict[str, str]) -> dict:
    raw_path = RAW_DIR / f"{stem}.txt"
    text = raw_path.read_text(encoding="utf-8")
    prompt = (
        "请提炼以下裁判文书：\n\n"
        f"【文件名】{stem}\n\n"
        f"【文书全文】\n{_clip_text(text)}"
    )
    result = call_llm(config, prompt)
    result["_source_file"] = f"{stem}.doc"
    result["_source_chars"] = len(text)
    return result


def run_all(config: dict[str, str], force: bool = False) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stems = sorted(p.stem for p in RAW_DIR.glob("*.txt"))
    if not stems:
        sys.exit("没有文本缓存，请先运行 --extract-texts")

    pending = [s for s in stems if force or not (OUT_DIR / f"{s}.json").exists()]
    if not pending:
        print(f"全部 {len(stems)} 份已提炼完成，无需重跑")
        return

    print(f"待提炼 {len(pending)} 份（缓存共 {len(stems)} 份），并发 {CONCURRENCY} …")
    done, failed = 0, []

    def work(stem: str) -> tuple[str, dict | None, str]:
        try:
            return stem, extract_case(stem, config), ""
        except Exception as exc:
            return stem, None, str(exc)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {pool.submit(work, stem): stem for stem in pending}
        for future in as_completed(futures):
            stem, result, error = future.result()
            if result is None:
                failed.append(stem)
                print(f"[失败] {stem[:50]}：{error}")
                continue
            (OUT_DIR / f"{stem}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            done += 1
            print(
                f"[{done}/{len(pending)}] {result.get('category')}｜"
                f"{result.get('case_no')}｜规则 {len(result.get('risk_rules', []))} 条"
            )

    print(f"\n提炼完成 {done}/{len(pending)}，失败 {len(failed)} 份")
    if failed:
        print("失败清单：", "、".join(failed))


# ---------------- 汇总与复核稿 ----------------

_RELEVANCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def summarize() -> None:
    items = []
    for path in sorted(OUT_DIR.glob("*.json")):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            print(f"跳过损坏文件：{path.name}")
    if not items:
        sys.exit("没有提炼结果，请先运行 --all")

    items.sort(key=lambda x: (_RELEVANCE_ORDER.get(x.get("relevance"), 3), x.get("case_no", "")))
    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(
        json.dumps({"version": "1.0", "total": len(items), "cases": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    by_category: dict[str, int] = {}
    rules_total = 0
    for item in items:
        by_category[item.get("category", "其他")] = by_category.get(item.get("category", "其他"), 0) + 1
        rules_total += len(item.get("risk_rules", []))

    lines = [
        "# 裁判案例风控知识提炼（复核稿）",
        "",
        f"> 提炼来源：`docs/裁判文书案例/案例文件/` 50 份裁判文书",
        f"> 提炼模型：deepseek-flash（脚本 `scripts/extract_knowledge.py`，配置在 `.env`）",
        f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M')}",
        f"> 统计：{len(items)} 案｜{rules_total} 条风险规则｜" + "，".join(f"{k} {v} 例" for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])),
        "",
        "> **复核说明**：以下内容由 LLM 从判决书原文提炼，`ruling` 应忠实转述法院认定。",
        "> 逐条核对后，高质量条目（relevance=high/medium）将进入履约模拟模块的裁判规则库。",
        "",
    ]
    for item in items:
        badge = item.get("relevance", "?")
        lines.append(f"## {item.get('title', '（无题）')}（{badge}）")
        lines.append("")
        lines.append(f"- 案号：{item.get('case_no', '—')}｜法院：{item.get('court', '—')}｜类型：{item.get('contract_type', '—')}")
        lines.append(f"- 分类：{item.get('category', '—')}｜文书：{item.get('doc_type', '—')}｜金额：{item.get('contract_amount') or '—'}")
        lines.append(f"- **核心争议**：{item.get('core_dispute', '—')}")
        lines.append(f"- **裁判要旨**：{item.get('holding', '—')}")
        if item.get("penalty_clause"):
            lines.append(f"- 违约条款：{item.get('penalty_clause')}")
        rules = item.get("risk_rules", [])
        if rules:
            lines.append("- **风险规则**：")
            for rule in rules:
                lines.append(f"  - [{rule.get('scenario')}] {rule.get('signal')} → {rule.get('ruling')}")
                if rule.get("lesson"):
                    lines.append(f"    - 启示：{rule.get('lesson')}")
        if item.get("key_excerpt"):
            lines.append(f"- 原文摘录：{item.get('key_excerpt')}")
        lines.append("")
    REVIEW_MD.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"汇总完成：{len(items)} 案 → {SUMMARY_JSON}")
    print(f"复核稿：{REVIEW_MD}")


def main() -> int:
    parser = argparse.ArgumentParser(description="裁判文书知识提炼")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--extract-texts", action="store_true", help="Word COM 提取全部案例文本")
    group.add_argument("--case", type=str, help="提炼指定案例（文件名不含扩展名，如 案例19）")
    group.add_argument("--all", action="store_true", help="提炼全部案例（断点续传）")
    group.add_argument("--force", action="store_true", help="配合 --all：覆盖已有结果")
    group.add_argument("--summarize", action="store_true", help="汇总生成复核稿")
    args = parser.parse_args()

    if args.extract_texts:
        extract_texts_with_word()
        return 0

    if args.summarize:
        summarize()
        return 0

    config = load_extraction_config()
    if not config["api_key"]:
        sys.exit("未配置 EXTRACTION_API_KEY，请在 .env 中填写（不入库）")
    if args.case:
        result = extract_case(args.case, config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    run_all(config, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
