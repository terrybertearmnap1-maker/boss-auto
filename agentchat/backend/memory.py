"""会话记忆：Redis 优先，不可用时降级为进程内字典。

为什么用 Redis：WebSocket 连接可能落到不同进程/实例，会话历史必须共享。
降级到内存只适合单进程调试——这点写进 README，面试也常被问。
"""

from __future__ import annotations

import json
import time
from typing import Dict, List


class MemoryMemory:
    name = "memory"

    def __init__(self) -> None:
        self._data: Dict[str, List[dict]] = {}

    def append(self, conv_id: str, role: str, content: str) -> None:
        self._data.setdefault(conv_id, []).append(
            {"role": role, "content": content, "ts": time.time()}
        )
        # 只保留最近 20 轮，防止上下文无限增长
        self._data[conv_id] = self._data[conv_id][-40:]

    def history(self, conv_id: str, limit: int = 8) -> List[dict]:
        return self._data.get(conv_id, [])[-limit:]


class RedisMemory:
    name = "redis"

    def __init__(self, url: str = "redis://127.0.0.1:6379/0", ttl: int = 3600) -> None:
        import redis

        self.client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        self.client.ping()  # 探活，失败就抛给 build_memory 降级
        self.ttl = ttl

    def _key(self, conv_id: str) -> str:
        return f"agentchat:conv:{conv_id}"

    def append(self, conv_id: str, role: str, content: str) -> None:
        key = self._key(conv_id)
        self.client.rpush(key, json.dumps({"role": role, "content": content, "ts": time.time()}, ensure_ascii=False))
        self.client.ltrim(key, -40, -1)
        self.client.expire(key, self.ttl)

    def history(self, conv_id: str, limit: int = 8) -> List[dict]:
        raw = self.client.lrange(self._key(conv_id), -limit, -1)
        return [json.loads(x) for x in raw]


def build_memory(redis_url: str | None = None):
    """返回 (memory, backend_name)；Redis 连不上就降级。"""
    if not redis_url:
        return MemoryMemory(), "memory"
    try:
        m = RedisMemory(redis_url)
        return m, m.name
    except Exception as exc:  # noqa: BLE001
        print(f"[memory] Redis 不可用，降级为内存实现：{exc}")
        return MemoryMemory(), "memory"
