"""岗位数据中转站：扩展抓到的岗位临时存在这里，供 Agent2 消费。

为什么不做双向 WebSocket 指令：
- 扩展侧改动越少越不容易坏（现在只需要多一个 POST）
- 后端"请求一次搜索"要等浏览器往返，一旦超时整个流水线就卡住
- 折中：扩展抓完就推上来，Agent2 读「最近 N 秒内」的批次；没有就回退本地索引

生产环境如果要做后端主动触发，把这里换成命令队列 + 扩展轮询即可，接口不用动。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

# 只有一份"最新批次"：岗位列表不大，够用且实现简单
_LATEST: Dict[str, Any] = {"at": 0.0, "keywords": [], "city": "", "jobs": [], "source": ""}

DEFAULT_TTL_SECONDS = 900  # 15 分钟内的批次算「新鲜」


def put(keywords: Optional[List[str]], city: str, jobs: List[Dict], source: str = "extension") -> None:
    """扩展上报一批岗位。"""
    _LATEST.update({
        "at": time.time(),
        "keywords": list(keywords or []),
        "city": city or "",
        "jobs": list(jobs),
        "source": source,
    })


def get(max_age: int = DEFAULT_TTL_SECONDS) -> Optional[Dict]:
    """取最新批次；超过 max_age 秒视为过期，返回 None。"""
    if not _LATEST["jobs"]:
        return None
    if time.time() - _LATEST["at"] > max_age:
        return None
    return dict(_LATEST)


def snapshot() -> Dict:
    """调试用：不做过期判断，原样返回。"""
    return dict(_LATEST)


def clear() -> None:
    _LATEST.update({"at": 0.0, "keywords": [], "city": "", "jobs": [], "source": ""})
