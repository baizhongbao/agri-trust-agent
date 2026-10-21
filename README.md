# 订单农业可信性 Agent

> 把一份订单农业合同 PDF，变成「可核验的结构化信息 + 对应标准依据 + 风险推演」。
所有数值计算都由纯 Python 完成（不交给 LLM），无法判定时显式返回 `review` 而非硬拍结论。

---

## 功能模块

| 模块 | 优先级 | 状态 | 做什么 |
|---|---|---|---|
| 合同解析 | **P0** | ✅ | 上传 PDF / 图片 → `fields`（展示层）+ `facts`（推理层，金额/日期/指标数值化），全部带原文依据 |
| 标准校验 | **P0** | ✅ | 四层：混合召回 → 精排 → 必备条款缺失检测（18 项）→ 数值合规比对（32 条限值） |
| 企业核验 | P1 | ✅ | L1 信用代码校验位验算（GB 32100-2015）→ L2 工商查询 → L3 合同 vs 登记交叉校验 |
| 履约模拟 | P1 | ✅ | 三情景推演（价格波动 / 自然灾害 / 一方违约）：数值由 Python 计算 + 真实判例引用 + LLM 定性分析 |
| 汇总判定 | —— | ✅ | 四模块结论归并为总体可信度等级 + 否决项 + 四维分项，并导出 PDF / Word 报告 |
| Agent 接入 | —— | 🚧 | MCP stdio server 已就绪，待部署到公网并在 AgentArts 注册为 MCP Target |

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ · FastAPI |
| 前端 | Vue3 + Vite（零运行时 UI 框架） |
| 大模型 | deepseek-flash（OpenAI 兼容，默认）· 华为云盘古 MaaS · mock 离线占位 |
| OCR | 华为云文字识别（Linux 目标）· SiliconFlow PaddleOCR-VL（Windows）· 仅扫描件需要 |
| 向量化 | `BAAI/bge-m3`：云端 SiliconFlow · 本地权重 · 哈希兜底（断网） |
| 检索 | 向量 + BM25 混合召回 → `bge-reranker-v2-m3` 精排（可选，失败自动降级） |
| 企业工商数据 | 企查查 MCP · 内置 fixture 演示库（离线兜底） |
| Agent 接入 | MCP stdio server（FastMCP） |
| 报告导出 | PDF：PyMuPDF（内置中文字体，跨平台一致）· Word：python-docx |
| 存储 | SQLite + 本地文件 + 内存索引 |

**所有外部依赖都走 Provider 层**（`backend/app/core/providers/`），靠 `.env` 开关在
「真实服务」与「离线兜底」之间切换，业务代码零改动。

---

## 快速开始（Windows）

```powershell
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2. 复制配置模板
Copy-Item .env.example .env

# 3. 生成示例合同
.venv\Scripts\python.exe scripts\make_sample_contract.py

# 4. 一键起前后端（双窗口）
start.bat
```

- 前端 <http://127.0.0.1:5173>
- 后端 <http://127.0.0.1:8000>
- 接口文档 <http://127.0.0.1:8000/docs>

手动启动：

```powershell
# 后端
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
# 前端（另一终端）
cd frontend; npm install; npm run dev
```

## 快速开始（Linux）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
python scripts/make_sample_contract.py
uvicorn app.main:app --app-dir backend --reload
```

> Linux 上要用本地模型（`EMBEDDING_PROVIDER=local`）时，需先单独装匹配 CUDA 的 torch，
> 再装 `backend/requirements-ml.txt`。RTX 50 系（Blackwell / sm_120）必须 CUDA 12.8+ 构建。

---

## 配置说明

两台机器的差异**只体现在 `.env` 的 Provider 开关上**：

| 开关 | Windows（开发/演示） | Linux（主力机） |
|---|---|---|
| `LLM_PROVIDER` | `deepseek` | `deepseek` / `pangu` |
| `OCR_PROVIDER` | `cloud` | `huawei` |
| `EMBEDDING_PROVIDER` | `cloud` | `local` |
| `RERANK_PROVIDER` | `cloud` | `cloud` / `disabled` |
| `CONTRACT_STRUCTURER` | `rule` | `llm` |
| `ENTERPRISE_API_PROVIDER` | `qcc` | `qcc` / `fixture` |
| `VECTOR_STORE_BACKEND` | `simple` | `chroma` |
| `SEARCH_PROVIDER` | `disabled` | `tavily` |

完整变量及说明见 `.env.example`。

---

## 接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查，返回各 Provider 就绪状态 |
| POST | `/api/v1/contracts/parse` | 上传 PDF / 图片并解析 |
| GET | `/api/v1/contracts` | 已解析合同列表 |
| GET | `/api/v1/contracts/{doc_id}` | 读取单份解析结果 |
| GET | `/api/v1/standards` | 标准库目录 |
| GET | `/api/v1/standards/stats` | 检索库状态 |
| POST | `/api/v1/standards/search` | 按文本检索标准条款 |
| POST | `/api/v1/standards/check` | 校验某份合同的条款覆盖 |
| POST | `/api/v1/standards/reindex` | 重建检索库 |
| POST | `/api/v1/enterprise/verify` | 核验某份合同全部主体（L1+L2+L3） |
| POST | `/api/v1/enterprise/lookup` | 直接查询单个企业 |
| POST | `/api/v1/simulate/{doc_id}` | 履约模拟（三情景） |
| GET | `/api/v1/simulate/rules` | 裁判规则库状态 |
| POST | `/api/v1/verdict/evaluate` | 汇总判定：总体可信度等级 |
| GET | `/api/v1/verdict/{doc_id}/report?format=pdf\|docx` | 导出评估报告 |

### MCP 工具（Agent 接入，非 HTTP）

`backend/app/mcp/agri_server.py` 是 **stdio** server，由 MCP 客户端拉起，
把四模块 + 汇总结论 + 报告导出 + 联网取证包成 8 个工具：

`list_contracts` · `get_contract` · `check_standard` · `verify_enterprise` ·
`simulate` · `overall_verdict` · `export_report` · `search_web`

工具**不含上传入口**：Agent 先 `list_contracts` 拿 `doc_id`，再串后续工具。

---



## 目录结构

```
├── backend/
│   ├── app/
│   │   ├── core/providers/      可插拔外部依赖（LLM / OCR / 向量 / 重排 / 搜索）
│   │   ├── mcp/agri_server.py   MCP stdio server
│   │   └── modules/
│   │       ├── contract_parser/ 合同解析 P0
│   │       ├── standard_check/  标准校验 P0
│   │       ├── enterprise_verify/ 企业核验 P1
│   │       ├── simulation/      履约模拟 P1
│   │       └── verdict/         汇总判定 + 报告导出
│   └── tests/                   单元测试
├── frontend/                    Vue3 + Vite
├── data/                        标准库 / 判例知识 / fixture / 示例合同 / 运行时产物
├── scripts/                     示例合同生成、冒烟测试、接口测试、环境体检
├── docs/                        环境报告 / 技术分析 / 交接文档
└── start.bat                    Windows 一键起前后端
```

---

## 设计要点

- **外部依赖一律走 Provider 层**：新增供应商 = 加一个实现类 + 在 `registry.py` 注册，业务模块不 import 任何厂商 SDK。
- **抽取值必须带证据**：`ContractField.evidence` 存原文片段，结果可回溯、可复核。
- **数值不交给 LLM**：`facts` 抽取、合规比对、损失计算全部是规则 / 纯 Python，LLM 只做语义理解（条款分类、定性风险）。
- **未就绪要显式报错**：用 `ProviderNotReadyError`，不静默返回空结果；缺必备字段时留下结构化痕迹 + `[门禁/*]` warning。
- **解析分两级且不可回退**：L1 规则抽取为默认路径，仅在命中升级条件时触发 L2 LLM 重解析，且**只在更完整时才采纳**。
- **判不了就返回 review**：显式给「需人工核对」，优于错误的确定结论。


