"""缓存层：Redis 做「已投去重」和「每日配额」，不可用时降级进程内。

放进 Redis 而不是内存的原因：扩展可能同时开多个标签页、服务也可能多实例，
配额与去重必须共享，否则同一天会超投、同一岗位会重复沟通。
"""

from __future__ import annotations

import time
from typing import Any, Dict


class MemoryCache:
    backend = "memory"

    def __init__(self) -> None:
        self._seen: Dict[str, float] = {}
        self._daily: Dict[str, int] = {}

    def seen(self, job_id: str) -> bool:
        return job_id in self._seen

    def mark(self, job_id: str, ttl_days: int = 60) -> None:
        self._seen[job_id] = time.time() + ttl_days * 86400

    def daily_count(self) -> int:
        return self._daily.get(time.strftime("%Y-%m-%d"), 0)

    def incr_daily(self) -> int:
        key = time.strftime("%Y-%m-%d")
        self._daily[key] = self._daily.get(key, 0) + 1
        return self._daily[key]

    def snapshot(self) -> Dict[str, Any]:
        return {"seen": len(self._seen), "today": self.daily_count()}


class RedisCache:
    backend = "redis"

    def __init__(self, url: str, ttl_days: int = 60) -> None:
        import redis

        self.client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        self.client.ping()
        self.ttl = ttl_days * 86400

    @staticmethod
    def _seen_key(job_id: str) -> str:
        return f"jobpilot:seen:{job_id}"

    @staticmethod
    def _daily_key() -> str:
        return f"jobpilot:daily:{time.strftime('%Y-%m-%d')}"

    def seen(self, job_id: str) -> bool:
        return bool(self.client.exists(self._seen_key(job_id)))

    def mark(self, job_id: str, ttl_days: int | None = None) -> None:
        self.client.set(self._seen_key(job_id), 1, ex=ttl_days * 86400 if ttl_days else self.ttl)

    def daily_count(self) -> int:
        return int(self.client.get(self._daily_key()) or 0)

    def incr_daily(self) -> int:
        key = self._daily_key()
        n = int(self.client.incr(key))
        self.client.expire(key, 3 * 86400)
        return n

    def snapshot(self) -> Dict[str, Any]:
        return {"seen": self.client.dbsize(), "today": self.daily_count()}


def build_cache(url: str, ttl_days: int = 60):
    if not url:
        return MemoryCache()
    try:
        return RedisCache(url, ttl_days)
    except Exception as exc:  # noqa: BLE001
        print(f"[cache] Redis 不可用（{exc}），降级内存")
        return MemoryCache()
