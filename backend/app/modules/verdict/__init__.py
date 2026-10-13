"""汇总判定层。

把合同解析 / 标准校验 / 企业核验 / 履约模拟四模块的分项结论归并成
一份总体可信度判断。这是跨模块编排层，因此允许 import 四个业务模块。
"""

from app.modules.verdict.schema import (
    Blocker,
    DimensionVerdict,
    OverallVerdict,
)

__all__ = ["Blocker", "DimensionVerdict", "OverallVerdict"]
