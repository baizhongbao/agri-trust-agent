"""pytest 全局配置。

把 backend/ 加入 sys.path，使测试里可以直接 `from app...` 导入，
与 scripts/smoke_test.py 的做法保持一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
