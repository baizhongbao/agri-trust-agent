"""合同解析模块（P0）。

职责：上传 PDF 合同 → 结构化合同 JSON。

实现链路：
    pdf_reader.py   电子版走 PyMuPDF 直抽文本；扫描件自动降级到华为云 OCR
    structurer.py   规则抽取（离线）或盘古大模型抽取，由 CONTRACT_STRUCTURER 切换
    schema.py       结构化数据模型，每个字段都带原文证据，支撑"可信性"
    storage.py      原件与结果落盘
    service.py      编排三步流程
    router.py       HTTP 接口

接口：
    POST /api/v1/contracts/parse   上传 PDF 并解析
    GET  /api/v1/contracts         已解析合同列表
    GET  /api/v1/contracts/{id}    读取解析结果
"""

from app.modules.contract_parser.schema import (
    Clause,
    ContractField,
    Party,
    StructuredContract,
)

__all__ = ["Clause", "ContractField", "Party", "StructuredContract"]
