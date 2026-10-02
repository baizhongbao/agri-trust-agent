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
| 合同解析 | **P0** | ✅ 已完成 | 上传 PDF → 结构化合同字段（带原文依据） |
| 标准校验 | **P0** | ✅ 已完成 | 合同条款 → 匹配标准库条款 + 覆盖率 |
| 企业核验 | P1 | ⬜ 待做 | 企业名称 → 工商信息 |
| 履约模拟 | P1 | ⬜ 待做 | 合同 + 参数 → 风险场景推演 |

---

## 2. 技术栈（已锁定，不要擅自更换）

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+（Windows 开发机为 3.13）· FastAPI |
| 前端 | Vue3 + Vite（**不引入 UI 框架**） |
| 大模型 | 华为云盘古 · ModelArts Studio（MaaS，OpenAI 兼容接口） |
| OCR | 华为云文字识别（仅扫描件需要） |
| 向量化 | `BAAI/bge-m3`：云端 SiliconFlow（Windows 默认）· 本地权重（Linux 有显卡）· 哈希兜底（断网） |
| 检索 | 向量 + BM25 混合召回 → `BAAI/bge-reranker-v2-m3` 精排（可选，失败自动降级） |
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
| `OCR_PROVIDER` | `disabled` | `huawei` |
| `EMBEDDING_PROVIDER` | `cloud`（SiliconFlow bge-m3） | `local` |
| `RERANK_PROVIDER` | `cloud`（bge-reranker-v2-m3） | `cloud` / `disabled` |
| `CONTRACT_STRUCTURER` | `rule` | `llm` |
| `VECTOR_STORE_BACKEND` | `simple` | `chroma` |

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

5. **未就绪要显式报错**
   用 `ProviderNotReadyError`，不要静默返回空结果。空结果比报错难排查十倍。

6. **模块之间不直接互相 import**
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
│   ├── requirements.txt         基础层：Web / PDF / 华为云 SDK
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
│       │       └── registry.py    工厂 + 就绪校验
│       └── modules/
│           ├── contract_parser/   ✅ P0
│           │   ├── pdf_reader.py    文本层直抽，扫描件自动降级 OCR
│           │   ├── structurer.py    规则 / 大模型双实现
│           │   ├── schema.py        数据模型（含 evidence）
│           │   ├── storage.py       落盘与查询
│           │   ├── service.py       编排
│           │   └── router.py        HTTP 接口
│           ├── standard_check/    ✅ P0
│           │   ├── loader.py        标准库加载
│           │   ├── store.py         哈希向量 + BM25 混合检索
│           │   ├── service.py       校验编排 + 自动降级
│           │   └── router.py
│           ├── enterprise_verify/ ⬜ P1 占位
│           └── simulation/        ⬜ P1 占位
│
├── frontend/                     Vue3 + Vite
│   ├── vite.config.js            代理 /api 与 /health 到 127.0.0.1:8000
│   └── src/
│       ├── App.vue
│       ├── api.js                接口封装
│       ├── styles.css            设计系统
│       └── components/           UploadPanel / ContractPanel / StandardPanel / ProviderCard
│
├── data/
│   ├── standards/                标准库语料 JSON（知识来源）
│   ├── samples/                  示例合同 PDF
│   ├── contracts/                解析结果（运行时生成，勿删）
│   └── uploads/                  合同原件副本
│
├── docs/ENV-REPORT.md            环境检查报告
└── scripts/
    ├── make_sample_contract.py   生成示例合同（PyMuPDF 内置中文字体，跨平台一致）
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
| POST | `/api/v1/contracts/parse` | 上传 PDF 并解析 |
| GET | `/api/v1/contracts` | 已解析合同列表 |
| GET | `/api/v1/contracts/{doc_id}` | 读取单份解析结果 |
| GET | `/api/v1/standards` | 标准库目录 |
| GET | `/api/v1/standards/stats` | 检索库状态 |
| POST | `/api/v1/standards/search` | 按文本检索标准条款 |
| POST | `/api/v1/standards/check` | 校验某份合同的条款覆盖 |
| POST | `/api/v1/standards/reindex` | 重建检索库 |

---

## 8. 改完必须验证

**不接受"我看代码应该没问题"。** 任何影响链路的改动都要跑：

```powershell
# 1. 端到端冒烟（不启服务，最快）
.venv\Scripts\python.exe scripts\smoke_test.py

# 2. 接口测试（需服务已启动）
.venv\Scripts\python.exe scripts\api_test.py
```

**通过标准：字段命中率必须是 8/8，接口用例必须全过。**

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

---

## 11. 当前进度与下一步

### 已完成并验证

- [x] 项目骨架、跨平台可移植配置、Provider 抽象层
- [x] **合同解析 P0**：PDF 上传 → 文本抽取（含扫描件 OCR 降级）→ 规则/LLM 双抽取器 → 落盘
- [x] **标准校验 P0**：标准库加载 → 混合检索 → 条款覆盖率报告
- [x] 前端界面：上传、结构化结果、标准校验、运行环境状态
- [x] 测试脚本：冒烟测试 + 接口测试，全部通过

### 下一步（建议顺序）

1. **企业核验 P1** —— 接口 + mock 实现先行，等凭证到位切真实 API
2. **履约模拟 P1** —— 用 LangGraph 编排，接盘古做风险推演
3. **接入华为云真实凭证** —— 切换 4 个 Provider 开关，联调
4. **演示准备** —— 演示脚本、断网演练、录屏

### 待人类完成（AI 无法代做）

- [ ] 华为云控制台开通 **ModelArts Studio（MaaS）** 并获取 API Key
- [ ] 开通 **文字识别 OCR** 并获取 AK/SK + Region
- [ ] 确认企业信息数据源（第三方 API 或 MCP）

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
