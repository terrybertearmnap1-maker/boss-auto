"""配置：全部走环境变量，缺省即可跑（自动降级到 SQLite / 内存 / 本地 Qdrant）。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    database_url: str
    redis_url: str
    qdrant_url: str
    score_threshold: int
    dedup_threshold: float
    port: int

    @staticmethod
    def from_env() -> "Config":
        return Config(
            # mysql://user:pass@127.0.0.1:3306/jobpilot 或 sqlite:///./jobpilot.db
            database_url=os.getenv("DATABASE_URL", "sqlite:///./jobpilot.db"),
            redis_url=os.getenv("REDIS_URL", ""),
            qdrant_url=os.getenv("QDRANT_URL", ""),
            score_threshold=int(os.getenv("SCORE_THRESHOLD", "60")),
            dedup_threshold=float(os.getenv("DEDUP_THRESHOLD", "0.92")),
            port=int(os.getenv("PORT", "8030")),
        )


CONFIG = Config.from_env()
