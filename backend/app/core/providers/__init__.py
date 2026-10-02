"""可插拔提供者层。

所有外部依赖（大模型 / OCR / 向量化）都在这里定义抽象接口，
具体实现按 `.env` 配置选择。这样做的目的：

1. 零凭证、零重依赖时，用 mock / 轻量实现也能跑通全链路
2. Windows 开发机与 Linux 主力机可以跑不同的实现，而业务代码完全不变
3. 换供应商（如盘古 → 其他模型）只影响一个文件
"""

from app.core.providers.base import (
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    LLMResult,
    OCRProvider,
    OCRResult,
)

__all__ = [
    "EmbeddingProvider",
    "EmbeddingResult",
    "LLMProvider",
    "LLMResult",
    "OCRProvider",
    "OCRResult",
]
