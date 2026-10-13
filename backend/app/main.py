"""应用入口。

当前已接入「合同解析」模块（P0），其余模块接口后续接入。
所有外部依赖都通过 Provider 层获取，因此没有凭证时也能完整启动。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import BASE_DIR, settings
from app.core.providers.registry import describe_providers
from app.modules.contract_parser.router import router as contract_router
from app.modules.enterprise_verify.router import router as enterprise_router
from app.modules.simulation.router import router as simulate_router
from app.modules.standard_check.router import router as standard_router
from app.modules.verdict.router import router as verdict_router

logging.basicConfig(
    level=logging.DEBUG if settings.app_debug else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_dirs()
    logging.getLogger(__name__).info(
        "启动完成 | 工作目录=%s | LLM=%s | OCR=%s | Embedding=%s | Rerank=%s | 抽取器=%s | 企业核验=%s",
        BASE_DIR,
        settings.llm_provider,
        settings.ocr_provider,
        settings.embedding_provider,
        settings.rerank_provider,
        settings.contract_structurer,
        settings.enterprise_api_provider or "fixture",
    )
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.app_debug,
    description="订单农业可信性 Agent：合同解析 / 企业核验 / 标准校验 / 履约模拟",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(contract_router, prefix=API_PREFIX)
app.include_router(standard_router, prefix=API_PREFIX)
app.include_router(enterprise_router, prefix=API_PREFIX)
app.include_router(simulate_router, prefix=API_PREFIX)
app.include_router(verdict_router, prefix=API_PREFIX)


@app.get("/", tags=["system"], summary="服务入口")
def index() -> dict:
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
        "api_prefix": API_PREFIX,
    }


@app.get("/health", tags=["system"], summary="健康检查")
def health() -> dict:
    """报告运行状态与外部依赖的配置情况。

    只返回"是否已配置 / 当前用哪个实现"，绝不回显凭证内容。
    """
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env,
        "providers": describe_providers(),
        "credentials_configured": {
            "pangu_llm": settings.has_pangu_credentials,
            "deepseek_llm": settings.has_deepseek_credentials,
            "huawei_ocr": settings.has_ocr_credentials,
            "enterprise_api": settings.has_enterprise_credentials,
            "cloud_embedding": settings.has_cloud_credentials,
        },
        "runtime": {
            "contract_structurer": settings.contract_structurer,
            "vector_store": settings.vector_store_backend,
            "storage": settings.storage_backend,
            "database": settings.database_backend,
        },
    }
