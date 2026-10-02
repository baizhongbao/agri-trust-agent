# 订单农业可信性 Agent · 开发环境检查报告

**检测时间**：2026-10-01
**项目场景**：华为 ICT 创新大赛
**技术栈决策**：华为云盘古（LLM） + 华为云 OCR + Vue3/React 前端
**工作区**：`c:/Users/bainote/CodeBuddy/20261001195854`（空目录，从零开始）
**检测脚本**：`check_env.ps1`（只读检测，可重复执行）

---

## 一、总体结论

> **运行时齐全，缺的是三层东西：云端凭证、Python 依赖、容器化能力。**

语言运行时（Python / Node / Git）已经就绪，说明**开发可以直接开始**。
真正阻塞项目的是 **华为云凭证尚未申请**——这不是装软件能解决的，必须人工去控制台开通。

---

## 二、已有能力（无需处理）

| 项目 | 现状 | 对本项目的意义 |
|---|---|---|
| Git | 2.55.0.windows.3 | 版本管理就绪 |
| Python | 3.13.15（`Python313`，含 pip 26.2.1、venv 可用） | 后端语言就绪 |
| Node.js | v24.19.0 | Vue3 前端构建就绪 |
| npm | 11.17.0（registry = 官方源） | 包管理就绪 |
| winget | v1.29.290 | 可命令行装软件 |
| **GPU** | **NVIDIA RTX 3060 Laptop，6GB 显存，驱动 566.07** | **可本地跑 Embedding / Reranker** |
| VC++ 2015-2022 x64 运行库 | 已安装 | 二进制 wheel 可正常加载 |
| PowerShell 执行策略 | RemoteSigned | venv 激活不会报错 |
| 网络 → 华为云 | `www.huaweicloud.com` 可达 | 云 API 可直连 |
| 网络 → PyPI / npmmirror / hf-mirror | 全部可达 | 依赖与模型可下载 |
| 网络 → `api.modelarts-maas.com` | 可达（返回 404，属探测方式所致） | **盘古 MaaS 端点可直连** |
| 磁盘 | C: 97.5 GB / D: 320.1 GB 可用 | 空间充足 |

### 关键发现：`code` 命令缺失不影响项目
VS Code CLI 不在 PATH，但当前 IDE 已具备完整能力，**无需安装**。

---

## 三、缺失清单（按优先级）

### P0 — 阻塞开发，必须解决

| # | 缺失项 | 影响 | 解决方式 |
|---|---|---|---|
| 1 | **华为云凭证全部未配置** | 合同解析（LLM 结构化）、OCR 全部无法调用，项目无法跑通 | **人工去华为云控制台申请**（见第五节） |
| 2 | **26 个 Python 依赖全部未安装** | 后端一行代码都跑不起来 | 建 venv 后批量安装（见第六节） |
| 3 | **Python 版本为 3.13.15（全局唯一）** | 少数科学计算库（如 `faiss-cpu`）在 3.13 上 wheel 可能缺失 | 优先直接使用 3.13；若装包失败再补装 3.11 |

### P1 — 影响体验，建议补齐

| # | 缺失项 | 影响 | 解决方式 |
|---|---|---|---|
| 4 | `pnpm` 未安装 | 无实质影响，npm 已够用 | `npm i -g pnpm`（可选） |
| 5 | `LongPathsEnabled = 0`（长路径未开启） | Python 依赖树过深时可能报路径过长错误 | 开启 Windows 长路径支持（可选） |
| 6 | Docker 未安装；WSL 无可用发行版 | 无法容器化部署（Milvus / MinIO / Postgres） | 可装，镜像源已验证可用，见 DR-3 |

### 不需要安装（已通过技术选型规避）

| 组件 | 为什么可以省掉 |
|---|---|
| **PaddleOCR / PaddlePaddle** | 选定华为云 OCR 后完全不需要。这是省掉的最大一块麻烦——它原本会带来编译依赖、VC++ 版本、Python 版本三重坑 |
| Tesseract OCR | 同上，云 OCR 替代 |
| CUDA / cuDNN 工具链 | 不在本地跑大模型，无需配置 |

---

## 四、重要发现（会直接影响架构决策）

### DR-1：技术选型帮你绕开了最大的环境地雷
"华为云 OCR" 这个决定，让本项目**完全不需要 PaddlePaddle**。
PaddlePaddle 是这套技术栈里唯一对 Python 版本 + VC++ + 编译环境极度挑剔的组件，绕开它之后，**现有的 Python 3.13 大概率可以直接用**。

### DR-2：那块 RTX 3060 是白捡的算力
6GB 显存足以在本地运行 RAG 的两个关键模型：
- `bge-m3` 类 Embedding 模型（约 2GB）
- `bge-reranker` 类重排模型（约 1GB）

意味着**标准校验模块的向量化与重排可以全本地完成**，零 API 成本、无网络延迟、演示时不怕断网。
建议：**Embedding / Reranker 走本地 GPU，LLM 生成走盘古**——这是性价比最高的组合。

### DR-3：Docker Hub 直连不可用，但代理与镜像源均可用（修正版）

**初次结论已修正**：不是"绝对拉不到"，而是"直连不行，需要绕一下"。深度探测结果如下。

| 探测项 | 结果 | 说明 |
|---|---|---|
| DNS：`registry-1.docker.io` | `162.125.32.13` | **该地址属于 Dropbox，是 DNS 污染**，非 Docker 真实 IP |
| DNS：`auth.docker.io` | `199.59.149.232` | 属 Bitly 网段，同样被污染 |
| DNS：`hub.docker.com` | `104.16.251.55` | Cloudflare，解析正常 |
| TCP 直连（4 个 docker.io 域名） | **全部超时** | 绕开代理时确实不通 |
| HTTP 经代理访问 `registry-1.docker.io/v2/` | **401（2192 ms）** | 401 是 Registry 的正常鉴权响应 → **经代理可拉取** |

**关键发现：本机已配置系统代理 `127.0.0.1:7897`**（`ProxyEnable=1`，典型 Clash/Mihomo 混合端口）。
这解释了"TCP 不通但 HTTP 通"的矛盾——`Invoke-WebRequest` 走 WinINET 代理，裸 TCP 不走。

**国内镜像源实测（返回 401 = 可用）**

| 镜像源 | 状态 | 延迟 |
|---|---|---|
| `docker.m.daocloud.io` | 可用 | 603 ms |
| `hub.rat.dev` | 可用 | 1500 ms |
| `docker.1ms.run` | 可用 | 1519 ms |
| `docker.nju.edu.cn` | 403 不可用 | — |
| `docker.1panel.live` | 403 不可用 | — |
| `dockerpull.org` | 404 不可用 | — |
| `docker.mirrors.ustc.edu.cn` | 超时不可用 | — |

> 华为云 `swr.cn-north-4.myhuaweicloud.com`（499 ms）是 **SWR 私有仓库端点**，非 Docker Hub 加速器。
> 若要作加速器，需登录华为云控制台 →「容器镜像服务 SWR」→「镜像加速器」获取**专属地址**（形如 `https://xxxx.mirror.swr.myhuaweicloud.com`）。对华为大赛而言这是最顺的选择。

**⚠️ 必须注意的坑**：Docker daemon 跑在 WSL2 内，**不会继承 Windows 的 `127.0.0.1:7897` 代理**——WSL2 里的 `127.0.0.1` 指向 WSL 自身而非宿主。三种解法：
1. Docker Desktop → Settings → Resources → Proxies 手动配置（配合 Clash 开启「允许局域网」并使用宿主 IP）
2. 将 WSL2 网络模式改为 `mirrored`（Windows 11 22H2+），此时 `127.0.0.1` 可直通宿主
3. **最省事**：直接配 `registry-mirrors`，完全不走代理

`%USERPROFILE%\.docker\daemon.json` 建议内容：

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1ms.run",
    "https://hub.rat.dev"
  ]
}
```

**修正后的建议**：Docker 属于"能装、但要多配一步"。
- 若核心功能只需存结构化数据 → 用 SQLite + 本地文件，**第一阶段跳过 Docker**，优先把业务链路跑通
- 若确定要用 Milvus / MinIO / Postgres → 装 Docker Desktop 并按上述方式配置镜像源

### DR-6：本机存在代理软件，会影响后续所有网络行为
系统代理 `127.0.0.1:7897` 一直开启。这带来两个连带影响：
- **好处**：Docker Hub、HuggingFace、GitHub 等被污染的域名可经代理访问
- **风险**：比赛现场若代理不可用，必须确保关键依赖（模型、镜像、Python 包）**已全部本地化**，否则演示会失败
- `netsh winhttp show proxy` 显示却是 **Direct access**，说明 WinHTTP 与 WinINET 配置不一致——这也是 Exit 早先误判的根因

### DR-4：长路径未开启
`LongPathsEnabled = 0`。Python 生态依赖嵌套较深，建议开启以规避偶发报错。

### DR-5：工作区为空
目录下无任何文件，项目**完全从零开始**，无需担心兼容历史代码。

---

## 五、必须人工完成的准备工作（脚本无法代做）

这三件事需要登录华为云控制台操作：

### 1. 开通 ModelArts Studio（MaaS）并获取 API Key
- 用于：**合同解析**（PDF → 结构化合同）、**履约模拟**（风险推演 Agent）
- 产出：一个 API Key，以及服务的 Base URL
- 提示：MaaS 提供 OpenAI 兼容接口，后端可直接用 `openai` SDK 对接，改 `base_url` 即可

### 2. 开通文字识别 OCR 服务并获取 AK/SK
- 用于：**合同解析**中的扫描件识别
- 产出：`Access Key` + `Secret Key` + 选择的区域（Region，如 `cn-north-4`）
- 注意：OCR 是区域化服务，**AK/SK 与 Region 必须配套**

### 3. 确认企业信息数据源（P1，可延后）
- 用于：**企业核验**模块
- 华为云/百度等有企业信息 API；注意国家企业信用信息公示系统**无官方 API**
- 若走 MCP，需要额外的 MCP Server 配置

> **凭证安全提醒**：拿到后写入项目根目录 `.env`，并确保 `.gitignore` 已忽略它。千万不要提交到 Git。

---

## 六、建议的依赖安装清单（后端）

```powershell
# 1. 在项目根目录创建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
```

```
# 2. requirements.txt 建议内容（分三层，按需安装）

# --- P0 Web 服务层 ---
fastapi
uvicorn[standard]
pydantic
python-multipart          # 文件上传（PDF 合同）
python-dotenv             # 读取 .env 凭证

# --- P0 合同解析：PDF + 华为云 OCR ---
pymupdf                   # 电子版 PDF 文本抽取（最快）
pdfplumber                # 表格结构化抽取
pypdf
huaweicloudsdkcore        # 华为云 SDK 核心
huaweicloudsdkocr         # 华为云文字识别 SDK

# --- P0 标准校验：RAG ---
openai                    # 对接盘古 MaaS（OpenAI 兼容）
sentence-transformers     # 本地 Embedding + Reranker（走 RTX 3060）
numpy
pandas
chromadb                  # 向量库（纯 Python，无需 Docker）
# faiss-cpu               # 备选：更轻快，但 Python 3.13 的 wheel 存在不确定性

# --- P1 Agent 编排 ---
langgraph
langchain

# --- P1 企业核验 / 存储 ---
httpx
mcp
minio                     # 仅在决定使用对象存储时才需要
sqlalchemy
redis

# --- 开发辅助 ---
pytest
```

**国内加速**：`-i https://pypi.tuna.tsinghua.edu.cn/simple`
**模型下载**：设置环境变量 `HF_ENDPOINT=https://hf-mirror.com`（已确认该镜像可达）

---

## 七、下一步行动建议

| 顺序 | 动作 | 依赖 |
|---|---|---|
| 1 | 申请华为云 MaaS API Key + OCR AK/SK | 人工，**优先做，审批需要时间** |
| 2 | 创建 venv 并安装 P0 依赖 | 可立即执行 |
| 3 | 搭建项目骨架（后端 FastAPI + 前端 Vue3） | 可立即执行 |
| 4 | 先打通"合同解析"链路（P0，最核心） | 依赖 1、2 |
| 5 | 再补"标准校验"RAG（P0） | 依赖 2，可本地 GPU |
| 6 | 最后做"企业核验""履约模拟"（P1） | 依赖 1 |

**关于是否需要额外安装 Python 3.11**：建议**先不装**。绕开 PaddlePaddle 后，3.13 的问题面很小；只有在实际安装某个包报 wheel 不兼容时，再补装 3.11 并为其单独建 venv。
