# AGENTS.md

> 给在本仓库工作的 AI 助手（以及新加入的人）的项目说明。
> **读完这一份就应当能独立继续开发，不需要翻聊天记录。**

---

## 1. 项目是什么

**订单农业可信性 Agent** —— 参加华为 ICT 创新大赛。

一句话：把一份订单农业合同 PDF，变成「可核验的结构化信息 + 对应标准依据 + 风险推演」。

四个模块与优先级：

| 模块 | 优先级 | 状态 | 做什么 |
|---|---|---|---|
| 合同解析 | **P0** | ✅ 已完成 | 上传 PDF → `fields`（展示层）+ `facts`（推理层，金额/日期/指标数值化），全部带原文依据 |
| 标准校验 | **P0** | ✅ 已完成 | 四层：混合召回 → 精排 → 必备条款缺失检测（18 项清单）→ 数值合规比对（32 条限值） |
| 企业核验 | P1 | ✅ 已完成 | L1 信用代码校验位验算（GB 32100-2015）→ L2 工商查询（企查查/fixture）→ L3 合同 vs 登记交叉校验 |
| 履约模拟 | P1 | ✅ 已完成 | 三情景推演：数值由 Python 计算 + 真实判例引用 + LLM 定性分析（mock 可降级） |

> 两大 P1 已于 2026-10-07 完成并合入（单元测试全部通过）。
> **尚未完成**：汇总判定层、报告导出、AgentArts 接入（详见第 11 节）。

---

## 2. 技术栈（已锁定，不要擅自更换）

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+（Windows 开发机为 3.13）· FastAPI |
| 前端 | Vue3 + Vite（**不引入 UI 框架**） |
| 大模型 | 华为云盘古 · ModelArts Studio（MaaS，OpenAI 兼容接口） |
| OCR | 华为云文字识别（Linux 目标）· SiliconFlow PaddleOCR-VL（Windows 当前）· 仅扫描件需要 |
| 向量化 | `BAAI/bge-m3`：云端 SiliconFlow（Windows 默认）· 本地权重（Linux 有显卡）· 哈希兜底（断网） |
| 检索 | 向量 + BM25 混合召回 → `BAAI/bge-reranker-v2-m3` 精排（可选，失败自动降级） |
| 企业工商数据 | 企查查 MCP（`qcc`，已配 Key）· 内置 fixture 演示库（离线兜底） |
| Agent 接入 | **MCP stdio server**（`backend/app/mcp/agri_server.py`，FastMCP）· AgentArts 参赛资格线 |
| 联网搜索 | Tavily（`SEARCH_PROVIDER=tavily`）· 离线降级（默认）。仅 Agent 加深时用，REST/前端不依赖 |
| 履约模拟 | 纯 Python 数值计算 + 50 份裁判文书知识提炼的规则库（LLM 仅做定性解释，不碰数字） |
| 存储 | SQLite + 本地文件 + 内存索引 |

### 不要擅自引入

- ❌ **不要引入 Docker 依赖** —— 当前阶段项目不需要；主力机仅 128GB 磁盘，含 torch 的镜像加构建缓存会吃掉 20~30GB
- ❌ **不要在 Windows 开发机装 torch / sentence-transformers** —— 2.5GB+ 且 6GB 显存收益有限，用 `hashing` 兜底即可
- ❌ **不要引入 PaddleOCR / Tesseract** —— 已用华为云 OCR 替代，绕开编译依赖这个最大的坑
- ❌ **不要引入重型 UI 框架**（Element Plus / Ant Design）—— 保持前端零运行时依赖
- ❌ **不要引入数据库服务**（PostgreSQL / Milvus / Redis）—— 当前 SQLite + 文件 + 内存索引完全够用

---

## 3. 两台机器怎么协作（关键）

| | Windows（当前开发机） | Linux 主力机 |
|---|---|---|
| 定位 | 开发 + 前端 + 演示 | 后端主力 + 部署 + 本地模型 |
| GPU | RTX 3060 Laptop 6GB | RTX 5060 Ti 16GB |
| 磁盘 | 充足 | **仅 128GB，需节省** |

### 唯一差异点是 `.env` 里的 Provider 开关

| 开关 | Windows | Linux（拿到凭证后） |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `pangu` |
| `OCR_PROVIDER` | `cloud`（SiliconFlow PaddleOCR-VL） | `huawei` |
| `EMBEDDING_PROVIDER` | `cloud`（SiliconFlow bge-m3） | `local` |
| `RERANK_PROVIDER` | `cloud`（bge-reranker-v2-m3） | `cloud` / `disabled` |
| `CONTRACT_STRUCTURER` | `rule` | `llm` |
| `CONTRACT_ESCALATION` | `auto` | `auto` |
| `ENTERPRISE_API_PROVIDER` | `qcc`（已配 Key） | `qcc` / `fixture` |
| `VECTOR_STORE_BACKEND` | `simple` | `chroma` |
| `SEARCH_PROVIDER` | `disabled` | `tavily`（有外网时） |

> 向量化三选一：`cloud`（云端 bge-m3，无需显卡与权重，Windows 默认）、
> `local`（本地模型，需 torch）、`hashing`（零依赖，断网演示兜底）。
> 演示现场断网时，务必把 `EMBEDDING_PROVIDER` 切回 `hashing`、`RERANK_PROVIDER` 切回 `disabled`。

> **铁律：不要为了适配某台机器去改业务代码。**
> 需要差异化的东西一律放进 Provider 层 + 环境变量。

### Linux 上的硬件坑：RTX 50 系是 Blackwell

RTX 5060 Ti 算力是 **sm_120**，不是普通的"新显卡"：

- NVIDIA 驱动必须 **≥ 570**
- torch 必须用 **CUDA 12.8+** 构建：`pip install torch --index-url https://download.pytorch.org/whl/cu128`
- **先装 torch，再装 `requirements-ml.txt`**，否则 pip 会拉到不匹配版本
- 症状：`no kernel image is available for execution on the device`（看着像显卡坏了，其实是 wheel 不匹配）

详见 `backend/requirements-ml.txt` 内注释。

---

## 4. 架构铁律

1. **外部依赖一律走 Provider 层**（`app/core/providers/`）
   新增供应商 = 加一个实现类 + 在 `registry.py` 注册映射。业务模块**不得** import 任何厂商 SDK。

2. **业务代码禁止直接读 `os.environ`**
   一律通过 `app/core/config.py` 的 `settings` 取值。

3. **相对路径必须经 `settings.path_of()` 解析**
   保证无论从哪个目录启动进程，数据落地位置都一致。

4. **抽取值必须带证据**
   `ContractField.evidence` 存原文片段，这不是可选项——"可信性"就是这个项目的立身之本。

5. **未就绪要显式报错，失败必须可见**
   用 `ProviderNotReadyError`，不要静默返回空结果。空结果比报错难排查十倍。
   解析结果一律带 `gate`（见下），缺失必备字段时**必须**留下结构化痕迹 +
   一条 `[门禁/*]` warning；下游模块（企业核验 / 履约模拟）在自己没跑成时
   必须填 `notice` 字段，禁止用"summary 全 0"冒充"无风险"。

   反面教材：扫描件 `1000178611.jpg` 解析后 `parties=[]` 且零 warning，
   企业核验静默跳过整套 L1/L2/L3，返回一份 pass/warning/fail 全 0 的报告。

6. **解析分两级，升级要有条件且不可回退**
   `contract_parser/gate.py` 定义整套策略：
   - **L1** = OCR + 规则抽取（廉价、确定、可解释），默认路径。
   - **L2** = LLM 重解析（`LLMStructurer`），仅在
     `needs_escalation()` 命中时触发：主体全缺 / 文档来自 OCR（图片·扫描件）/ 关键交易要素大面积缺失。
     开关 `CONTRACT_ESCALATION=auto|off`。
   - **择优**：`choose_better()` 按 `(主体数, 必备项命中, 字段命中)` 比较，
     **只在 L2 更完整时才采纳**——`LLM_PROVIDER=mock` 时 L2 返回空壳，
     直接采纳会把可用的 L1 结果清空。
   - **L4** = `evaluate()`：`text`/`parties` 缺失为 blocking（level=blocked，下游不可信），
     金额/日期/期限/标题缺失为 degraded（可继续但必须带标注）。

   现有限制（待办）：L2 目前只把 OCR **文本**再送一次 LLM，没有直接读图片；
   真•多模态直读需要在 `LLMProvider` 上加视觉通道，不在此次改动范围内。

   命名提示：这里的 L1/L2 是**解析**层级；`enterprise_verify` 的 L1/L2/L3 是
   **核验**层级（校验位 / 工商查询 / 交叉校验）。两套编号互不相干，别混读。

7. **模块之间不直接互相 import**
   跨模块协作通过 core 层接口或上层编排完成，保证任一模块可单独测试与替换。

---

## 5. 目录结构

```
合同agent/
├── AGENTS.md                    本文件
├── .env                         本机配置（不入库，含凭证）
├── .env.example                 模板 + Provider 开关说明
├── .gitattributes               行尾符统一为 LF（跨平台协作必需）
├── .gitignore
├── docker-compose.yml           开发编排（当前默认只起 API，INSTALL_ML=false）
│
├── backend/
│   ├── Dockerfile               固定 Python 3.11
│   ├── requirements.txt         基础层：Web / PDF / 华为云 SDK / MCP
│   ├── requirements-ml.txt      RAG 层：torch / sentence-transformers / 向量库
│   └── app/
│       ├── main.py              FastAPI 入口 + /health + 路由挂载
│       ├── core/
│       │   ├── config.py        集中配置（唯一配置入口）
│       │   └── providers/       可插拔外部依赖
│       │       ├── base.py        抽象接口 + 异常
│       │       ├── llm.py         pangu | mock
│       │       ├── ocr.py         huawei | disabled
│       │       ├── embedding.py   cloud | local | hashing
│       │       ├── rerank.py      cloud（SiliconFlow）| disabled
│       │       ├── search.py      tavily | disabled（仅 MCP search_web 用）
│       │       └── registry.py    工厂 + 就绪校验
│       ├── mcp/
│       │   └── agri_server.py    MCP stdio server：四模块 + search_web 包装成工具
│       └── modules/
│           ├── contract_parser/   ✅ P0
│           │   ├── pdf_reader.py    PDF 文本层直抽 / 扫描件与图片（PNG/JPG）走 OCR，统一 read_document 入口
│           │   ├── structurer.py    规则 / 大模型双实现（L1=rule，L2=llm）
│           │   ├── gate.py          L1→L2 升级判定 + L4 硬失败门禁（必备字段）
│           │   ├── facts.py         可推理事实抽取（金额/日期/指标数值化）
│           │   ├── schema.py        数据模型（fields + facts 双层，含 evidence）
│           │   ├── storage.py       落盘与查询
│           │   ├── service.py       编排
│           │   └── router.py        HTTP 接口
│           ├── standard_check/    ✅ P0
│           │   ├── loader.py        标准库加载
│           │   ├── store.py         向量 + BM25 混合检索 + 精排
│           │   ├── checklist.py     必备条款清单（18 项）与覆盖检测
│           │   ├── compliance.py    数值合规比对（32 条限值）
│           │   ├── service.py       校验编排 + 自动降级
│           │   └── router.py
│           ├── enterprise_verify/ ✅ P1
│           │   ├── credit_code.py   L1 校验位验算（GB 32100-2015）
│           │   ├── cross_check.py   L3 合同 vs 登记交叉校验
│           │   ├── schema.py        报告数据模型
│           │   ├── service.py       L1→L2→L3 编排
│           │   └── router.py
│           └── simulation/        ✅ P1
│               ├── calculator.py    三情景纯 Python 数值计算（calc_steps 可复核）
│               ├── rulebook.py      裁判规则库检索（50 份判例提炼）
│               ├── schema.py        模拟报告数据模型
│               ├── service.py       计算 → 引用 → LLM 定性（可降级）
│               └── router.py
│   └── tests/                    单元测试
│       ├── test_parse_gate.py    L1→L2 升级判定 + L4 门禁 + 场景回归
│       ├── test_image_upload.py  图片上传（magic byte → OCR 分发）
│       ├── test_mcp_compact.py   MCP 工具输出体积上限（截断后须仍是合法 JSON）
│       ├── test_party_credit_code.py  最近邻信用代码归属
│       └── test_link_flow.py     条款切分 + 供方/需方角色识别
│
├── frontend/                     Vue3 + Vite
│   ├── vite.config.js            代理 /api 与 /health 到 127.0.0.1:8000
│   └── src/
│       ├── App.vue               四页签主布局 + 离线模式提示
│       ├── api.js                接口封装
│       ├── styles.css            设计系统
│       └── components/           Upload / Contract / Standard / Enterprise / Simulation / ProviderCard
│
├── data/
│   ├── standards/                标准库语料 JSON（依据库 v2.0 + 必备条款清单）
│   ├── knowledge/                裁判文书知识库（50 份案例提炼，cases_summary.json）
│   ├── fixtures/                 企业核验离线演示数据（虚构企业）
│   ├── samples/                  示例合同 PDF（电子版 + 扫描件）
│   ├── contracts/                解析结果（运行时生成，勿删）
│   └── uploads/                  合同原件副本
│
├── docs/                         环境报告 / 技术分析 / 交接文档 / 法规原文
start.bat                     Windows 一键起后端 + 前端（双窗口）
└── scripts/
    ├── make_sample_contract.py   生成示例合同（PyMuPDF 内置中文字体，跨平台一致）
    ├── extract_knowledge.py      裁判文书知识提炼（一次性数据准备，LLM 辅助）
    ├── smoke_test.py             端到端冒烟测试（不启服务）
    ├── api_test.py               HTTP 接口测试（需服务已启动）
    ├── check_env.ps1             Windows 环境体检
    ├── check_docker_net.ps1      Docker / 镜像源探测
    └── check_env.sh              Linux 环境体检
```

---

## 6. 怎么跑

### Windows

```powershell
# 后端
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend

# 前端（另开一个终端）
cd frontend
npm run dev
```

前端 <http://127.0.0.1:5173> · 后端 <http://127.0.0.1:8000> · 文档 <http://127.0.0.1:8000/docs>

也可以直接双击仓库根目录的 `start.bat`（一键开两个窗口起前后端）。

### Linux

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
# 需要本地模型时（注意先单独装 torch，见第 3 节）
uvicorn app.main:app --app-dir backend --reload
```

### 首次准备

```powershell
# 1. 复制配置模板
Copy-Item .env.example .env

# 2. 生成示例合同
.venv\Scripts\python.exe scripts\make_sample_contract.py
```

---

## 7. 接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查，返回各 Provider 就绪状态与运行时配置 |
| POST | `/api/v1/contracts/parse` | 上传 PDF 或图片（PNG/JPG）并解析 |
| GET | `/api/v1/contracts` | 已解析合同列表 |
| GET | `/api/v1/contracts/{doc_id}` | 读取单份解析结果 |
| GET | `/api/v1/standards` | 标准库目录 |
| GET | `/api/v1/standards/stats` | 检索库状态 |
| POST | `/api/v1/standards/search` | 按文本检索标准条款 |
| POST | `/api/v1/standards/check` | 校验某份合同的条款覆盖 |
| POST | `/api/v1/standards/reindex` | 重建检索库 |
| POST | `/api/v1/enterprise/verify` | 核验某份合同的全部主体（L1+L2+L3） |
| POST | `/api/v1/enterprise/lookup` | 直接查询单个企业（本地校验 + 工商信息） |
| POST | `/api/v1/simulate/{doc_id}` | 履约模拟（价格波动 / 自然灾害 / 一方违约） |
| GET | `/api/v1/simulate/rules` | 裁判规则库状态 |

### MCP 工具（Agent 接入，非 HTTP）

`backend/app/mcp/agri_server.py` 是 **stdio** server，不经过 FastAPI，
由 MCP 客户端拉起。工具返回 JSON 字符串，上限 4000 字符；
失败信号（`gate` / `notice`）会被 `_prioritized` 提到最前面，防止被截断吃掉。

| 工具 | 参数 | 对应能力 |
|---|---|---|
| `list_contracts` | `limit` | 列出已解析合同 |
| `get_contract` | `doc_id` | 读取结构化字段 + facts |
| `check_standard` | `doc_id`, `top_k`, `clause_limit` | 必备条款 + 数值合规 |
| `verify_enterprise` | `doc_id` | L1 校验位 + L2 工商 + L3 交叉 |
| `simulate` | `doc_id`, `scenarios`, `price_change_pct`, … | 三情景推演 |
| `search_web` | `query`, `max_results` | Tavily 联网取证（`SEARCH_PROVIDER=disabled` 时返回空 + 说明） |

```bash
# 手动验证 server 能起（stdio 会等输入，属正常；Ctrl-C 退出）
.venv\Scripts\python.exe backend\app\mcp\agri_server.py
```

> 注意：MCP 工具**不含上传入口**。文件解析只能走 REST `/contracts/parse`
> 或预先放好样本；Agent 先 `list_contracts` 拿 `doc_id` 再串后续工具。

---

## 8. 改完必须验证

**不接受"我看代码应该没问题"。** 任何影响链路的改动都要跑：

```powershell
# 1. 单元测试（最快，不启服务）
.venv\Scripts\python.exe -m pytest backend\tests -q

# 2. 端到端冒烟（不启服务）
.venv\Scripts\python.exe scripts\smoke_test.py

# 3. 接口测试（需服务已启动）
.venv\Scripts\python.exe scripts\api_test.py
```

**通过标准：单元测试全过，字段命中率必须是 8/8，接口用例必须全过；
冒烟测试的 gate 一栏必须是 `OK`（示例合同应当完备，出现 degraded/blocked 即视为回归）。**

若改动了规则抽取：以 `data/samples/订单农业合同_示例.pdf` 为基准，9 个字段（含合同名称）应全部正确抽取。

---

## 9. 红线

- `.env` **绝不入库**（含华为云凭证）
- `.venv` / `node_modules` **绝不跨机拷贝**，必须在新机器重建（内含绝对路径）
- **不要删除 `data/`** —— 含用户上传的合同与标准库语料
- **不要删除 `.codebuddy/`**
- 破坏性操作（删除目录、覆盖配置）**必须先确认**

---

## 10. 已知问题与注意事项

| 现象 | 说明 |
|---|---|
| PowerShell 调接口中文乱码 | `Invoke-WebRequest` 在响应无 charset 时按 Latin-1 解码。**不是 bug**，用 httpx 或浏览器验证 |
| 中文路径 | **已实测无问题**（PyMuPDF / FastAPI / Vite 均正常），不必回避 |
| 规则抽取器的边界 | 对格式规范的合同效果好；格式混乱或口语化的合同需要切到 `llm` 抽取器 |
| `fitz` 弃用警告 | 已改用 `import pymupdf as fitz`，旧版有回退分支 |
| 扫描件无 OCR 时 | 会返回明确告警而非空结果，属预期行为 |
| **本机装了系统代理时接口偶发 502** | httpx 会自动读取 Windows 系统代理（本机为 `127.0.0.1:7897`），连 `127.0.0.1` 的本地请求也会被 `CONNECT` 隧道转发，长耗时请求（如 `/standards/check`）会撞代理超时被回 **502 空响应**。`.env` 里的 `HTTP_PROXY=` 无法覆盖（pydantic 不会写回 `os.environ`）。排查时在测试脚本里显式传 `trust_env=False`，或临时关掉代理 |
| 云端向量化已启用 | `EMBEDDING_PROVIDER=cloud` 会把标准库语料与合同条款正文发到 SiliconFlow。断网演示前必须切回 `hashing` + `disabled` |
| 企业核验走 qcc | `ENTERPRISE_API_PROVIDER=qcc` 依赖外网访问企查查 MCP。断网演示前切回 `fixture`；fixture 全部为虚构企业，代码校验位均真实有效 |
| LLM 抽取器未实测 | `CONTRACT_STRUCTURER=llm` 代码就绪但从未接真实盘古跑过。切换后先冒烟验证，再用于演示 |
| 联网搜索默认关闭 | `SEARCH_PROVIDER=disabled`。`search_web` 只在 MCP Agent 里可用，REST/前端无对应入口；`TAVILY_API_KEY` 留空时返回空结果 + 提示，不报错 |

---

## 11. 当前进度与下一步

### 已完成并验证

- [x] 项目骨架、跨平台可移植配置、Provider 抽象层
- [x] **合同解析 P0**：PDF 上传 → 文本抽取（含扫描件 OCR 降级）→ 规则/LLM 双抽取器 → fields + facts 双层落盘；支持图片（PNG/JPG）直接上传走 OCR（已端到端实测，字段命中 8/8）
- [x] **标准校验 P0**：依据库 v2.0（8 部 / 48 条条款 / 32 条限值）→ 混合检索 + 精排 → 必备条款缺失检测（18 项）→ 数值合规比对
- [x] **企业核验 P1**：L1 校验位验算（GB 32100-2015）→ L2 工商查询（企查查 MCP 已配 Key，fixture 兜底）→ L3 合同 vs 登记交叉校验（名称/代码/成立日期/登记状态/经营范围）
- [x] **履约模拟 P1**：三情景（价格波动/自然灾害/一方违约）纯 Python 数值计算（calc_steps 可复核）+ 50 份裁判文书规则库引用 + LLM 定性分析（mock 可降级）
- [x] **MCP stdio server**：四模块 + `search_web` 包成 6 个 MCP 工具，Agent 可自主调度（`backend/app/mcp/agri_server.py`）
- [x] 前端界面：上传、结构化结果、标准校验、企业核验、履约模拟、运行环境状态
- [x] 测试：单元测试 + 冒烟测试 + 接口测试，全部通过

### 下一步（建议顺序）

1. **接盘古 + 实测 LLM 抽取器** —— 代码就绪但从未跑过真实模型，切 `LLM_PROVIDER=pangu` 后必须先冒烟
2. **AgentArts 接入** —— 参赛资格线。MCP server 已就绪，剩下的是把它部署到后端公网可达处，再在 AgentArts 注册为 MCP Target
3. **标的品类识别** —— 解决「水分 14.5% 对籼米一致、对籼稻谷偏离」的矛盾结论（`facts.subject_category` + 合规比对适用性过滤）
4. **前端展示必备条款缺失 + 数值比对** —— 后端已产出，前端不可见
5. **doc_id 冲突修复** —— `new_doc_id()` 是秒级时间戳，同秒上传两份会互相覆盖
6. **汇总判定层 + 报告导出** —— 串起四模块，先出分项不要过早上加权总分
7. **演示准备** —— 演示脚本、断网演练、录屏

### 待人类完成（AI 无法代做）

- [ ] 华为云控制台开通 **ModelArts Studio（MaaS）** 并获取 API Key
- [ ] 开通 **文字识别 OCR** 并获取 AK/SK + Region（当前用 SiliconFlow PaddleOCR-VL 过渡）
- [ ] AgentArts（智果）平台开通 + 后端公网可达地址（部署/内网穿透/APIG 三选一）

---

## 12. 关键概念速查

**Provider 层为什么重要**
所有外部依赖（LLM / OCR / 向量化）都有 `mock` 与 `real` 两套实现，靠 `.env` 切换。
这让"没有凭证"和"有凭证"两条路共用同一套下游代码，也让两台机器可以跑不同实现。

**混合检索为什么不用 FAISS**
Demo 阶段语料仅 30~几百条，纯 Python 完全够用，且 Windows 上零二进制依赖。
接口刻意做成与向量库一致的 `build / search` 形态，换 chroma 时上层代码不动。

**为什么每个字段都要 evidence**
订单农业的核心诉求是"可信"。只给结论不给依据，等于让使用者盲信模型。
`evidence` 存支撑该字段的原文片段，使结果可回溯、可复核。

**为什么 fields 之外还要 facts**
`fields` 的值是原文片段，人看得懂但机器算不了（「486,000元」没法比大小）。
`facts` 把金额变数值、日期变 ISO、指标变成 (名称, 比较符, 阈值) 三元组，
下游的合规比对、交叉校验、履约模拟全靠它。

**为什么数值不交给 LLM**
合规比对和损失计算要求数字精确，模型把 14.5 读成 15 就是事故。
所以 facts 抽取、履约模拟的数值计算全部是规则/纯 Python，
LLM 只负责语义理解（条款分类、定性风险分析）。

**为什么判不了就返回 review**
`review`（需人工核对）优于错误的确定结论。企业核验里登记状态不在已知集合、
日期无法解析、角色识别失败，都显式给 review 而不是硬拍一个 pass/fail。
