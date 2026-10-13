"""报告导出（PDF / Word）的回归测试。

只验证「能生成、格式正确、关键章节进得去」——排版细节不做像素级断言。
"""

from __future__ import annotations

import io

from app.modules.contract_parser.schema import GATE_OK, ParseGate, StructuredContract
from app.modules.enterprise_verify.schema import PartyVerification, VerifyReport
from app.modules.simulation.schema import ScenarioResult, SimulationReport
from app.modules.verdict import exporter, service


def _contract() -> StructuredContract:
    contract = StructuredContract(title="测试合同", contract_no="DD-001")
    contract.gate = ParseGate(level=GATE_OK, summary="门禁通过")
    return contract


def _standard() -> dict:
    return {
        "required_clauses": {
            "required_total": 11,
            "required_covered": 9,
            "missing_required": [{"name": "不可抗力与自然灾害免责", "risk": "high"}],
            "summary": "必备条款 9/11",
        },
        "compliance": {
            "violation_count": 1,
            "mandatory_violation_count": 0,
            "violations": [
                {
                    "metric": "水分",
                    "contract_value": 14.5,
                    "contract_unit": "%",
                    "standard_code": "GB/T 17891-2017",
                    "clause_no": "4.7",
                    "standard_value": 13.5,
                    "standard_unit": "%",
                    "basis": "推荐性标准",
                }
            ],
            "summary": "可比对指标 8 项",
        },
    }


def _verify() -> VerifyReport:
    return VerifyReport(
        doc_id="d",
        provider="fixture",
        parties=[PartyVerification(role="甲方", name="某公司", credit_code="X", overall="pass", l2_status="found")],
        summary={},
    )


def _simulation() -> SimulationReport:
    return SimulationReport(
        doc_id="d",
        scenarios=[ScenarioResult(scenario="party_breach", label="一方违约", computable=True, summary="违约金约 48600 元")],
    )


def _model() -> exporter.ReportModel:
    verdict = service.build_verdict(_contract(), _standard(), _verify(), _simulation(), doc_id="d")
    return exporter.ReportModel(
        contract_title="测试合同",
        doc_id="d",
        generated_at=verdict.generated_at,
        verdict=verdict,
        sections=[
            exporter.ReportSection(title="合同要点", lines=["甲方：某公司"]),
            exporter.ReportSection(title="标准校验明细", lines=["必备条款 9/11"]),
        ],
        data_sources=["工商数据来源：fixture"],
        disclaimer="仅供参考",
    )


def test_build_report_from_collect(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "collect",
        lambda doc_id: (_contract(), _standard(), _verify(), _simulation(), {}),
    )
    model = exporter.build_report("d")
    assert model is not None
    assert model.doc_id == "d"
    assert model.verdict.grade  # 有结论
    titles = [s.title for s in model.sections]
    assert "合同要点" in titles
    assert "标准校验明细" in titles
    assert "主体核验明细" in titles
    assert "履约模拟明细" in titles


def test_render_pdf_is_valid_pdf() -> None:
    data = exporter.render_pdf(_model())
    assert data[:5] == b"%PDF-"
    assert len(data) > 1000


def test_render_docx_is_valid_zip_and_has_text() -> None:
    from docx import Document

    data = exporter.render_docx(_model())
    assert data[:2] == b"PK"
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "总体可信度" in text
    assert "一、总体结论" in text
    assert "标准校验明细" in text


def test_export_to_file_rejects_bad_format(monkeypatch) -> None:
    monkeypatch.setattr(exporter, "build_report", lambda doc_id: _model())
    import pytest

    with pytest.raises(ValueError):
        exporter.export_to_file("d", fmt="txt")
