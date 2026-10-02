"""向量化提供者实现。

- CloudEmbeddingProvider：云端 API（SiliconFlow，OpenAI 兼容 /embeddings），
  无需显卡、无需下载权重，Windows 开发机上也能拿到真正的语义向量
- LocalEmbeddingProvider：本地模型（bge-m3 等），主力机 Linux + 显卡使用
- HashingEmbeddingProvider：零依赖的哈希向量，无网络/无凭证时兜底

三者输出格式完全一致（均已 L2 归一化，余弦相似度即点积），
因此上层检索代码不需要任何改动，只靠 `.env` 里的 EMBEDDING_PROVIDER 切换。
"""

from __future__ import annotations

import hashlib
import logging
import re
import struct
from collections import Counter

import httpx

from app.core.config import settings
from app.core.providers.base import EmbeddingProvider, EmbeddingResult, ProviderNotReadyError

logger = logging.getLogger(__name__)

_CLEAN_RE = re.compile(r"\s+")

# 空文本会让部分向量接口直接报错，统一替换为一个空格占位
_EMPTY_PLACEHOLDER = " "


def _l2_normalize(vector: list[float]) -> list[float]:
    """L2 归一化。

    检索层直接以点积当余弦用，因此"输出已归一化"是本层的硬约定；
    云端接口不保证返回单位向量，必须在提供者内部补齐。
    """
    norm = sum(v * v for v in vector) ** 0.5
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


def _stable_hash(token: str) -> int:
    """进程间稳定的哈希。

    不能用内置 hash()——它受 PYTHONHASHSEED 影响，
    同一个词在不同进程会得到不同结果，索引将彻底失效。
    """
    digest = hashlib.md5(token.encode("utf-8")).digest()[:4]
    return struct.unpack("<I", digest)[0]


class HashingEmbeddingProvider(EmbeddingProvider):
    """字符 n-gram 哈希向量。

    设计取舍：
    - 不引入 numpy / torch，Python 3.13 的 Windows 上开箱即用
    - 中文用字符级 n-gram，无需分词器，也回避了词典依赖
    - 向量已做 L2 归一化，余弦相似度即点积
    - 单靠它有语义天花板，因此检索层会再叠加 BM25 做混合排序
    """

    name = "hashing"
    model = "char-ngram-hashing"

    def __init__(self, dim: int = 512) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def is_ready(self) -> bool:
        return True

    def _tokens(self, text: str) -> Counter[str]:
        cleaned = _CLEAN_RE.sub("", text.lower())
        if not cleaned:
            return Counter()

        tokens: Counter[str] = Counter()
        # 单字权重低，双字权重高——中文里双字组合的区分度更强
        tokens.update({ch: 1.0 for ch in cleaned})
        tokens.update({cleaned[i : i + 2]: 1.6 for i in range(len(cleaned) - 1)})
        # 英文/数字按词切分补充
        tokens.update({w: 1.4 for w in re.findall(r"[a-z0-9]+", text.lower())})
        return tokens

    def _vectorize(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token, weight in self._tokens(text).items():
            vector[_stable_hash(token) % self._dim] += weight

        norm = sum(v * v for v in vector) ** 0.5
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]

    def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[self._vectorize(t) for t in texts],
            dim=self._dim,
            provider=self.name,
            model=self.model,
        )


class CloudEmbeddingProvider(EmbeddingProvider):
    """云端向量化（SiliconFlow，OpenAI 兼容 /embeddings）。

    为什么先上云端：
        本地 bge-m3 需要 torch + 2GB 权重，Windows 开发机装不了，
        Linux 主力机磁盘也紧张。云端接口只需一份凭证就能拿到同款模型，
        而在 .env 里换回 hashing / local 时，上层代码零改动。

    ⚠️ 会把标准库语料与合同条款正文发送到第三方服务。
       处理敏感合同时请把 EMBEDDING_PROVIDER 切回 local。
    """

    name = "cloud"

    def __init__(self) -> None:
        self._dim = 0

    @property
    def model(self) -> str:  # type: ignore[override]
        return settings.embedding_cloud_model

    @property
    def dim(self) -> int:
        # 尚未发起过调用时（如 /health 启动期）回落到配置里的预期维度
        return self._dim or settings.embedding_cloud_dim

    def is_ready(self) -> bool:
        return bool(
            settings.cloud_api_base_url
            and settings.cloud_api_key
            and settings.embedding_cloud_model
        )

    def _endpoint(self) -> str:
        # CLOUD_API_BASE_URL 需包含版本路径，例如 https://api.siliconflow.cn/v1
        return settings.cloud_api_base_url.rstrip("/") + "/embeddings"

    def _embed_batch(self, client: httpx.Client, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self.model,
            "input": [t if t and t.strip() else _EMPTY_PLACEHOLDER for t in texts],
            "encoding_format": "float",
        }
        response = client.post(
            self._endpoint(),
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.cloud_api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json().get("data") or []
        # 接口不保证返回顺序，按 index 归位后再还原成入参顺序
        return [
            list(item.get("embedding") or [])
            for item in sorted(data, key=lambda item: item.get("index", 0))
        ]

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not self.is_ready():
            raise ProviderNotReadyError(
                "云端向量化未就绪：请在 .env 中配置 CLOUD_API_BASE_URL 与 CLOUD_API_KEY"
            )
        if not texts:
            return EmbeddingResult(
                vectors=[], dim=self.dim, provider=self.name, model=self.model
            )

        batch_size = max(1, settings.embedding_cloud_batch_size)
        vectors: list[list[float]] = []
        with httpx.Client(timeout=settings.cloud_timeout) as client:
            for start in range(0, len(texts), batch_size):
                vectors.extend(self._embed_batch(client, texts[start : start + batch_size]))

        if len(vectors) != len(texts):
            raise RuntimeError(
                f"云端向量化返回条数不匹配：请求 {len(texts)} 条，实际 {len(vectors)} 条"
            )

        vectors = [_l2_normalize(vector) for vector in vectors]
        self._dim = len(vectors[0])
        return EmbeddingResult(
            vectors=vectors,
            dim=self.dim,
            provider=self.name,
            model=self.model,
        )


class LocalEmbeddingProvider(EmbeddingProvider):
    """本地句向量模型（默认 BAAI/bge-m3）。

    惰性加载：只有真正调用时才导入 sentence-transformers 并加载权重，
    避免拖慢应用启动，也让未安装 torch 的机器仍能启动服务。

    ⚠️ RTX 50 系（Blackwell, sm_120）需 CUDA 12.8+ 的 torch 构建，
       详见 backend/requirements-ml.txt
    """

    name = "local"

    def __init__(self) -> None:
        self._model = None
        self._dim = 0

    @property
    def model(self) -> str:  # type: ignore[override]
        return settings.embedding_model

    @property
    def dim(self) -> int:
        if self._dim:
            return self._dim
        # bge-m3 为 1024 维；未加载时给出预期值，避免上层拿到 0
        return 1024

    def is_ready(self) -> bool:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._model is not None:
            return self._model
        if not self.is_ready():
            raise ProviderNotReadyError(
                "本地向量模型不可用：请安装 sentence-transformers（见 backend/requirements-ml.txt）"
            )

        from sentence_transformers import SentenceTransformer

        logger.info("加载本地向量模型：%s（device=%s）", self.model, settings.embedding_device)
        self._model = SentenceTransformer(self.model, device=settings.embedding_device)
        self._dim = int(self._model.get_sentence_embedding_dimension())
        return self._model

    def embed(self, texts: list[str]) -> EmbeddingResult:
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True).tolist()
        return EmbeddingResult(
            vectors=vectors,
            dim=self.dim,
            provider=self.name,
            model=self.model,
        )
