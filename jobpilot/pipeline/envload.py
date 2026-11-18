"""加载 .env（本地密钥）并暴露配置。

不用 python-dotenv，避免多一个依赖：格式简单，自己解析足够。
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = ROOT / ".env"


def load_env(path: Path | None = None) -> int:
    """把 .env 里的键值读进 os.environ（已存在的环境变量优先，不覆盖）。"""
    target = path or _ENV_FILE
    if not target.exists():
        return 0
    loaded = 0
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def llm_ready() -> bool:
    return bool(os.getenv("OPENAI_BASE_URL") and os.getenv("OPENAI_API_KEY"))


load_env()
