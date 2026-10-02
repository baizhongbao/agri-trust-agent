"""文字识别提供者实现。

- HuaweiOCRProvider：华为云 OCR，用于扫描件
- DisabledOCRProvider：未配置时的显式占位

注意：电子版 PDF 有文本层，走 PyMuPDF 直接抽取即可，根本不需要 OCR。
只有扫描件才需要本模块，所以 Demo 阶段即使没有 OCR 凭证也能完整演示。
"""

from __future__ import annotations

import base64
import logging

from app.core.config import settings
from app.core.providers.base import OCRProvider, OCRResult, ProviderNotReadyError

logger = logging.getLogger(__name__)


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
            "OCR 未启用。扫描件需要配置华为云 OCR（HUAWEI_CLOUD_AK/SK/REGION）；"
            "电子版 PDF 有文本层，无需 OCR。"
        )
