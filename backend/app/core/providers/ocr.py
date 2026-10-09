"""文字识别提供者实现。

- CloudOCRProvider：云端视觉 OCR（SiliconFlow，OpenAI 兼容），模型可配
  （如 PaddlePaddle/PaddleOCR-VL-1.5、Qwen/Qwen2.5-VL 系列）
- HuaweiOCRProvider：华为云 OCR（赛题要求的华为技术，拿到凭证后切换）
- DisabledOCRProvider：未配置时的显式占位

注意：电子版 PDF 有文本层，走 PyMuPDF 直接抽取即可，根本不需要 OCR。
只有扫描件才需要本模块，所以 Demo 阶段即使没有 OCR 凭证也能完整演示。
"""

from __future__ import annotations

import base64
import logging

import httpx

from app.core.config import settings
from app.core.providers.base import OCRProvider, OCRResult, ProviderNotReadyError

logger = logging.getLogger(__name__)

_OCR_PROMPT = (
    "提取图片中的全部文字，按行输出，保持原有阅读顺序，"
    "不要添加任何解释、标题或markdown格式。"
)


class CloudOCRProvider(OCRProvider):
    """云端视觉 OCR（SiliconFlow，OpenAI 兼容接口）。

    与云端向量化共用 CLOUD_API_BASE_URL / CLOUD_API_KEY，
    模型单独配置（OCR_CLOUD_MODEL）。PaddleOCR-VL 专为 OCR 训练，
    中文合同识别效果好；也可换 Qwen2.5-VL 等通用视觉模型。
    """

    name = "cloud"

    def is_ready(self) -> bool:
        return bool(
            settings.cloud_api_base_url
            and settings.cloud_api_key
            and settings.ocr_cloud_model
        )

    def recognize(self, image_bytes: bytes) -> OCRResult:
        if not self.is_ready():
            raise ProviderNotReadyError(
                "云端 OCR 未就绪：需配置 CLOUD_API_KEY 与 OCR_CLOUD_MODEL"
            )

        # 按魔数决定 data URL 的 MIME：直接上传的图片可能是 JPEG，
        # 声明错 MIME 部分服务端会拒收
        b64 = base64.b64encode(image_bytes).decode("ascii")
        mime = "image/png" if image_bytes.startswith(b"\x89PNG") else "image/jpeg"
        payload = {
            "model": settings.ocr_cloud_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                        {"type": "text", "text": _OCR_PROMPT},
                    ],
                }
            ],
            "temperature": 0.1,
            "max_tokens": 4000,
        }
        with httpx.Client(timeout=settings.ocr_cloud_timeout) as client:
            response = client.post(
                settings.cloud_api_base_url.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.cloud_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = (data["choices"][0]["message"]["content"] or "").strip()
        return OCRResult(
            text=content,
            page_count=1,
            provider=self.name,
            raw={
                "model": settings.ocr_cloud_model,
                "usage": data.get("usage", {}) or {},
            },
        )


class HuaweiOCRProvider(OCRProvider):
    """华为云文字识别。

    使用官方 SDK 的通用表格识别接口，凭 AK/SK 鉴权。
    SDK 采用惰性导入，未安装时不影响其他功能启动。
    """

    name = "huawei"

    def is_ready(self) -> bool:
        if not settings.has_ocr_credentials:
            return False
        try:
            import huaweicloudsdkcore  # noqa: F401
            import huaweicloudsdkocr  # noqa: F401
        except ImportError:
            logger.warning("华为云 OCR SDK 未安装，请执行 pip install huaweicloudsdkocr")
            return False
        return True

    def recognize(self, image_bytes: bytes) -> OCRResult:
        if not self.is_ready():
            raise ProviderNotReadyError(
                "华为云 OCR 未就绪：需配置 HUAWEI_CLOUD_AK / SK / REGION，并安装 huaweicloudsdkocr"
            )

        from huaweicloudsdkcore.auth.credentials import BasicCredentials
        from huaweicloudsdkocr.v1 import OcrClient, RecognizeGeneralTableRequest
        from huaweicloudsdkocr.v1.region.ocr_region import OcrRegion

        credentials = BasicCredentials(
            settings.huawei_cloud_ak, settings.huawei_cloud_sk
        ).with_project_id(settings.huawei_cloud_project_id)

        client = (
            OcrClient.new_builder()
            .with_credentials(credentials)
            .with_region(OcrRegion.value_of(settings.huawei_cloud_region))
            .build()
        )

        request = RecognizeGeneralTableRequest()
        request.body = {"image": base64.b64encode(image_bytes).decode("ascii")}
        response = client.recognize_general_table(request)

        result = response.result or {}
        words = [item.get("words", "") for item in (result.get("words_block_list") or [])]

        return OCRResult(
            text="\n".join(w for w in words if w),
            page_count=1,
            provider=self.name,
            raw={"words_block_count": len(words)},
        )


class DisabledOCRProvider(OCRProvider):
    """OCR 未启用。

    显式失败好过静默返回空字符串——后者会让"扫描件解析出空结果"
    变成一个难以定位的问题。
    """

    name = "disabled"

    def is_ready(self) -> bool:
        return False

    def recognize(self, image_bytes: bytes) -> OCRResult:
        raise ProviderNotReadyError(
            "OCR 未启用。扫描件需要文字识别："
            "云端方案（OCR_PROVIDER=cloud，配 CLOUD_API_KEY 与 OCR_CLOUD_MODEL）"
            "或华为云 OCR（OCR_PROVIDER=huawei，配 AK/SK/REGION）。"
            "电子版 PDF 有文本层，无需 OCR。"
        )
