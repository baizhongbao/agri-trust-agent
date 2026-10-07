"""履约模拟模块（P1）。

三情景推演：价格波动 / 自然灾害 / 一方违约。

架构铁律（与全项目一致）：
    1. **数值计算必须由 Python 做**（calculator.py，用 facts.amount / facts.penalty），
       每个输出带 calc_steps（公式 + 操作数），可逐项复核；LLM 禁止碰数字。
    2. **定性分析引用真实判例**：rulebook.py 从 50 份裁判文书提炼的知识库
       （data/knowledge/cases_summary.json）中检索裁判规则，
       每条推演结论都能指回真实案号与法院认定。
    3. **不引入 LangGraph**：三段情景用顺序流程 + 结构化 prompt 足够，更可控。
    4. LLM 走 Provider 层（mock / pangu），mock 时降级为模板拼接，链路始终可用。

接口：POST /api/v1/simulate/{doc_id}（router.py）
依赖配置项：LLM_*（定性分析）、SIMULATION_RULES_PATH（规则库路径）

状态：已实现。
"""
