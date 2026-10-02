"""业务模块层。

四个模块与产品需求一一对应：

    contract_parser     合同解析   P0   PDF + OCR + LLM → 结构化合同
    standard_check      标准校验   P0   条款与标准库匹配（RAG）
    enterprise_verify   企业核验   P1   企业名称 → 工商信息
    simulation          履约模拟   P1   合同 + 参数 → 风险场景推演

约定：模块之间不直接互相 import，跨模块协作通过 core 层的接口或
上层编排完成，以便任一模块单独测试与替换。
"""
