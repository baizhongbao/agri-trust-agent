"""HTTP 接口联调测试。

在服务已启动的前提下，验证接口层是否正常：
    /health                              健康检查
    POST /api/v1/contracts/parse         上传 PDF 并解析
    GET  /api/v1/contracts               合同列表
    GET  /api/v1/contracts/{doc_id}      读取单份结果

用法：
    python scripts/api_test.py
    python scripts/api_test.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF = PROJECT_ROOT / "data" / "samples" / "订单农业合同_示例.pdf"


def main() -> int:
    parser = argparse.ArgumentParser(description="HTTP 接口联调测试")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="服务地址")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()

    try:
        import httpx
    except ImportError:
        print("需要 httpx：pip install httpx", file=sys.stderr)
        return 1

    base = args.base.rstrip("/")
    failures = 0

    # trust_env=False：Windows 上装了系统代理时，httpx 会自动读取它，
    # 连访问 127.0.0.1 的本地请求也会被塞进 CONNECT 隧道，
    # 长耗时的 /standards/check 会撞代理超时，拿到 502 空响应。
    # 本地回环请求本来就不该走代理，这里显式关掉。
    with httpx.Client(base_url=base, timeout=180.0, trust_env=False) as client:
        # ---- 1. 健康检查 ----
        print("=" * 62)
        try:
            response = client.get("/health")
            response.raise_for_status()
            health = response.json()
            print(f"[OK] GET /health  status={health.get('status')}")
            print(f"     providers : {json.dumps(health.get('providers'), ensure_ascii=False)}")
            print(f"     runtime   : {json.dumps(health.get('runtime'), ensure_ascii=False)}")
        except Exception as exc:
            print(f"[FAIL] GET /health -> {exc}")
            print("       服务似乎未启动，请先运行：uvicorn app.main:app --app-dir backend")
            return 1

        # ---- 2. 上传并解析 ----
        print("-" * 62)
        if not args.pdf.exists():
            print(f"[FAIL] 找不到测试 PDF：{args.pdf}")
            return 1

        try:
            with args.pdf.open("rb") as handle:
                response = client.post(
                    "/api/v1/contracts/parse",
                    files={"file": (args.pdf.name, handle, "application/pdf")},
                )
            response.raise_for_status()
            payload = response.json()
            doc_id = payload["doc_id"]
            contract = payload["contract"]
            hits = sum(1 for f in contract["fields"] if f["value"])
            print(f"[OK] POST /api/v1/contracts/parse  doc_id={doc_id}")
            print(f"     合同名称 : {contract['title']}")
            print(f"     合同金额 : {contract['amount'] or '(空)'}")
            print(f"     主体数量 : {len(contract['parties'])}")
            print(f"     字段命中 : {hits}/{len(contract['fields'])}")
            print(f"     条款数量 : {len(contract['clauses'])}")
        except Exception as exc:
            print(f"[FAIL] POST /api/v1/contracts/parse -> {exc}")
            return 1

        # ---- 3. 列表 ----
        print("-" * 62)
        try:
            response = client.get("/api/v1/contracts")
            response.raise_for_status()
            listing = response.json()
            print(f"[OK] GET /api/v1/contracts  total={listing['total']}")
        except Exception as exc:
            print(f"[FAIL] GET /api/v1/contracts -> {exc}")
            failures += 1

        # ---- 4. 详情 ----
        print("-" * 62)
        try:
            response = client.get(f"/api/v1/contracts/{doc_id}")
            response.raise_for_status()
            detail = response.json()
            print(f"[OK] GET /api/v1/contracts/{doc_id}  title={detail['title']}")
        except Exception as exc:
            print(f"[FAIL] GET /api/v1/contracts/{doc_id} -> {exc}")
            failures += 1

        # ---- 5. 错误处理：非 PDF 文件 ----
        print("-" * 62)
        try:
            response = client.post(
                "/api/v1/contracts/parse",
                files={"file": ("fake.pdf", b"this is not a pdf", "application/pdf")},
            )
            if response.status_code == 400:
                print(f"[OK] 非 PDF 文件被正确拒绝：{response.json().get('detail')}")
            else:
                print(f"[FAIL] 非 PDF 文件未返回 400，实际 {response.status_code}")
                failures += 1
        except Exception as exc:
            print(f"[FAIL] 错误处理用例异常 -> {exc}")
            failures += 1

        # ---- 6. 标准库目录 ----
        print("-" * 62)
        try:
            response = client.get("/api/v1/standards")
            response.raise_for_status()
            library = response.json()
            print(f"[OK] GET /api/v1/standards  total={library['total']}")
            for item in library["items"][:4]:
                print(f"     {item['standard_code']:<26} {item['standard_title']}（{item['clause_count']} 条）")
        except Exception as exc:
            print(f"[FAIL] GET /api/v1/standards -> {exc}")
            failures += 1

        # ---- 7. 按文本检索标准条款 ----
        print("-" * 62)
        try:
            response = client.post(
                "/api/v1/standards/search",
                json={"query": "大米水分含量不高于14.5%", "top_k": 3},
            )
            response.raise_for_status()
            result = response.json()
            print(f"[OK] POST /api/v1/standards/search  matches={result['total']}")
            for match in result["matches"][:3]:
                print(
                    f"     score={match['score']:<7} {match['standard_code']} "
                    f"{match['clause_no']} {match['clause_title']}"
                )
        except Exception as exc:
            print(f"[FAIL] POST /api/v1/standards/search -> {exc}")
            failures += 1

        # ---- 8. 校验整份合同的条款覆盖 ----
        print("-" * 62)
        try:
            response = client.post(
                "/api/v1/standards/check",
                json={"doc_id": doc_id, "top_k": 3},
            )
            response.raise_for_status()
            report = response.json()
            required = report.get("required_clauses") or {}
            print(
                f"[OK] POST /api/v1/standards/check  "
                f"必备条款覆盖 {report['coverage']:.0%} "
                f"({required.get('required_covered')}/{required.get('required_total')})"
                f"  条款匹配率 {report.get('clause_match_rate', 0):.0%}"
            )
            for entry in report["results"][:4]:
                top = entry["matches"][0] if entry["matches"] else None
                if top:
                    print(
                        f"     合同第{entry['clause_index']}条 → "
                        f"{top['standard_code']} {top['clause_title']}（score={top['score']}）"
                    )
                else:
                    print(f"     合同第{entry['clause_index']}条 → 未匹配到标准")

            if required:
                print(
                    f"     必备条款 : {required['required_covered']}/{required['required_total']} 覆盖"
                    f"，风险分 {required['risk_score']}（{required['risk_level']}）"
                )
                for item in required.get("missing_required", []):
                    print(f"     [缺失·必备] {item['name']}（风险 {item['risk']}）")
                for item in required.get("missing_recommended", []):
                    print(f"     [缺失·建议] {item['name']}（风险 {item['risk']}）")

            comp = report.get("compliance") or {}
            if comp:
                print(f"     数值比对 : {comp['summary']}")
                labels = {"violation": "偏离", "review": "待核", "compliant": "一致"}
                for item in comp.get("items", []):
                    scope = "/".join(item.get("applies_to") or [])
                    basis = f" [{item['basis']}]" if item.get("basis") else ""
                    print(
                        f"     [{labels.get(item['status'], '?')}] {item['metric']}："
                        f"合同 {item['contract_value']}{item['contract_unit']} vs "
                        f"{item['standard_code']} {item['clause_no']} "
                        f"{item['standard_value']}{item['standard_unit']}"
                        f"{'（' + scope + '）' if scope else ''}{basis}"
                    )
                for notice in comp.get("timeliness", []):
                    print(f"     [时效] {notice['message']}")
        except Exception as exc:
            print(f"[FAIL] POST /api/v1/standards/check -> {exc}")
            failures += 1

    print("=" * 62)
    if failures:
        print(f"测试完成，{failures} 个用例失败")
        return 1
    print("全部用例通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
