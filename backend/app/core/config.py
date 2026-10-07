"""集中式配置。

跨机协作约定：
- 业务代码禁止直接读 os.environ，一律通过 settings 取值
- 相对路径统一以 BASE_DIR（仓库根目录）为基准解析，
  这样无论从哪个目录启动进程，数据落地位置都一致
- 「用真实服务还是离线兜底」全部由这里的 provider 开关决定，
  这是 Windows 开发机与 Linux 主力机之间唯一需要差异化的配置
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_base_dir() -> Path:
    """定位仓库根目录。

    优先级：
        1. 环境变量 PROJECT_ROOT（容器内由 Dockerfile 注入为 /app）
        2. 自当前文件向上查找，命中 .git 或 .env.example 的目录
        3. 兜底：backend/ 目录
    """
    env_root = os.getenv("PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()

    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".env.example").exists() or (parent / ".git").exists():
            return parent
    return here.parents[2]


BASE_DIR = _resolve_base_dir()


class Settings(BaseSettings):
    """全部环境相关取值的唯一来源。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------- 应用基础 ----------------
    app_name: str = "agri-trust-agent"
    app_version: str = "0.1.0"
    app_env: str = "development"
    app_debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---------------- 提供者选择 ----------------
    # 默认全部走离线兜底，保证无凭证、无重依赖也能跑通全链路
    llm_provider: str = "mock"             # pangu | mock
    ocr_provider: str = "disabled"         # cloud | huawei | disabled
    embedding_provider: str = "hashing"    # cloud | local | hashing
    contract_structurer: str = "rule"      # llm | rule

    # ---------------- 华为云 · 通用认证 ----------------
    huawei_cloud_ak: str = ""
    huawei_cloud_sk: str = ""
    huawei_cloud_project_id: str = ""
    huawei_cloud_region: str = "cn-north-4"

    # ---------------- 华为云 · 盘古 / ModelArts Studio ----------------
    pangu_base_url: str = ""
    pangu_api_key: str = ""
    pangu_model: str = ""
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096
    llm_timeout: int = 120

    # ---------------- 华为云 · 文字识别 ----------------
    ocr_endpoint: str = ""
    ocr_max_retry: int = 3

    # ---------------- 云端视觉 OCR（SiliconFlow，OpenAI 兼容）----------------
    # 与云端向量化共用 CLOUD_API_BASE_URL / CLOUD_API_KEY
    ocr_cloud_model: str = "PaddlePaddle/PaddleOCR-VL-1.5"
    ocr_cloud_timeout: int = 120

    # ---------------- 企业核验 ----------------
    # fixture：内置虚构演示数据（离线默认）；qcc：企查查 MCP（真实工商数据）
    enterprise_api_provider: str = ""
    enterprise_api_base_url: str = ""
    enterprise_api_key: str = ""
    enterprise_timeout: int = 60
    enterprise_fixture_path: str = "./data/fixtures/enterprise_fixture.json"

    # ---------------- 履约模拟 ----------------
    # 裁判规则库：50 份裁判文书的知识提炼（scripts/extract_knowledge.py 生成）
    simulation_rules_path: str = "./data/knowledge/cases_summary.json"

    # ---------------- 标准校验 · RAG ----------------
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cuda"
    embedding_dim_hashing: int = 512
    rerank_enabled: bool = True
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_device: str = "cuda"
    vector_store_backend: str = "simple"   # simple | chroma | milvus
    chroma_persist_dir: str = "./data/chroma"
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.03

    # ---------------- 云端向量化 / 重排（SiliconFlow，OpenAI 兼容）----------------
    # 与华为云无关，属"先跑通语义检索"的过渡方案：无需显卡、无需下载权重。
    # 换供应商时只改 base_url / api_key，业务代码零改动。
    cloud_api_base_url: str = "https://api.siliconflow.cn/v1"
    cloud_api_key: str = ""
    cloud_timeout: int = 60
    embedding_cloud_model: str = "BAAI/bge-m3"
    embedding_cloud_dim: int = 1024          # bge-m3 固定 1024 维
    embedding_cloud_batch_size: int = 32
    rerank_provider: str = "disabled"        # disabled | cloud

    # ---------------- 存储 ----------------
    database_url: str = "sqlite:///./data/app.db"
    storage_backend: str = "local"
    file_storage_dir: str = "./data/uploads"
    standards_dir: str = "./data/standards"

    # ---------------- 路径解析 ----------------
    def path_of(self, value: str) -> Path:
        """把配置中的相对路径解析为基于仓库根目录的绝对路径。"""
        path = Path(value)
        return path if path.is_absolute() else (BASE_DIR / path).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def data_dir(self) -> Path:
        return BASE_DIR / "data"

    @property
    def chroma_dir(self) -> Path:
        return self.path_of(self.chroma_persist_dir)

    @property
    def upload_dir(self) -> Path:
        return self.path_of(self.file_storage_dir)

    @property
    def standards_path(self) -> Path:
        return self.path_of(self.standards_dir)

    @property
    def database_backend(self) -> str:
        return self.database_url.split(":", 1)[0]

    def ensure_dirs(self) -> None:
        """确保运行时目录存在。启动时调用一次即可。"""
        for path in (self.data_dir, self.upload_dir, self.standards_path):
            path.mkdir(parents=True, exist_ok=True)

    # ---------------- 凭证就绪状态（供健康检查展示，不泄露内容）----------------
    @property
    def has_pangu_credentials(self) -> bool:
        return bool(self.pangu_base_url and self.pangu_api_key)

    @property
    def has_cloud_credentials(self) -> bool:
        """云端向量化 / 重排的凭证是否齐备（SiliconFlow）。"""
        return bool(self.cloud_api_base_url and self.cloud_api_key)

    @property
    def has_ocr_credentials(self) -> bool:
        return bool(
            self.huawei_cloud_ak
            and self.huawei_cloud_sk
            and self.huawei_cloud_region
        )

    @property
    def has_enterprise_credentials(self) -> bool:
        return bool(self.enterprise_api_base_url and self.enterprise_api_key)

    @property
    def enterprise_fixture_file(self) -> Path:
        return self.path_of(self.enterprise_fixture_path)


settings = Settings()
