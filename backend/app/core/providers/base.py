"""提供者抽象接口。

约定：
- 每个提供者都必须实现 `is_ready()`，用于在缺凭证时给出明确报错，
  而不是等到调用时才抛出难以理解的异常
- 返回值统一用 dataclass 包装，附带 provider / model 信息，
  便于在接口响应中告诉使用者"这次结果是谁算出来的"
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderNotReadyError(RuntimeError):
    """提供者未就绪（通常是凭证未配置或模型未安装）。"""


@dataclass
class OCRResult:
    """单页/多页文字识别结果。"""

    text: str
    page_count: int = 0
    provider: str = "unknown"
    confidence: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResult:
    """大模型调用结果。"""

    content: str
    provider: str = "unknown"
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbeddingResult:
    """向量化结果。"""

    vectors: list[list[float]]
    dim: int = 0
    provider: str = "unknown"
    model: str = ""


@dataclass
class RerankHit:
    """重排结果中的一条：指向候选文档在入参列表中的下标。"""

    index: int
    score: float


@dataclass
class RerankResult:
    """重排结果。

    `hits` 的下标对应调用方传入的 `documents` 顺序，
    已按相关性从高到低排列。
    """

    hits: list[RerankHit]
    provider: str = "unknown"
    model: str = ""


class OCRProvider(ABC):
    """文字识别提供者。"""

    name: str = "base"

    @abstractmethod
    def is_ready(self) -> bool:
        """是否具备调用条件。"""

    @abstractmethod
    def recognize(self, image_bytes: bytes) -> OCRResult:
        """识别单页图像。"""

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "ready": self.is_ready()}


class LLMProvider(ABC):
    """大模型提供者。"""

    name: str = "base"
    model: str = ""

    @abstractmethod
    def is_ready(self) -> bool:
        """是否具备调用条件。"""

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> LLMResult:
        """自由文本补全。"""

    @abstractmethod
    def complete_json(
        self,
        prompt: str,
        system: str | None = None,
    ) -> dict[str, Any]:
        """要求模型输出 JSON 并解析为字典。"""

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "model": self.model, "ready": self.is_ready()}


class EmbeddingProvider(ABC):
    """向量化提供者。"""

    name: str = "base"
    model: str = ""

    @property
    @abstractmethod
    def dim(self) -> int:
        """向量维度。"""

    @abstractmethod
    def is_ready(self) -> bool:
        """是否具备调用条件。"""

    @abstractmethod
    def embed(self, texts: list[str]) -> EmbeddingResult:
        """批量向量化。"""

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self.model,
            "dim": self.dim,
            "ready": self.is_ready(),
        }


class RerankProvider(ABC):
    """重排提供者（cross-encoder 精排）。

    存在的意义：向量检索是"双塔"式的，query 与文档各自编码、
    彼此看不到对方；重排模型把 query 与候选文档拼在一起打分，
    在中文小语料上通常能把最相关的那条顶到第一位。
    """

    name: str = "base"
    model: str = ""

    @abstractmethod
    def is_ready(self) -> bool:
        """是否具备调用条件。"""

    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> RerankResult:
        """对候选文档重排，返回带下标的得分。"""

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self.model,
            "ready": self.is_ready(),
        }
