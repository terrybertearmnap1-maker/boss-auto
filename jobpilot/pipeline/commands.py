"""投递指令队列：后端把「该投哪些岗、用什么话术」排进队列，扩展轮询取走执行。

为什么用轮询而不是 WebSocket：
- 扩展侧的 WebSocket 在 MV3 里生命周期不稳（service worker 会被回收）
- 轮询 6 秒一次，对人肉投递节奏完全够用，且断线自愈
- 实现简单，不需要维护连接状态

指令状态：queued → delivered → acked（成功/失败），全部可查。
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, List, Optional

_QUEUE: List[Dict] = []          # 待取
_INFLIGHT: Dict[str, Dict] = {}  # 已取走、等 ack
_DONE: List[Dict] = []           # 已 ack（保留最近 200 条）


def enqueue(jobs: List[Dict]) -> List[Dict]:
    """把待投递岗位排进队列；同一 job_id 若已在队列里则跳过。"""
    # 注意：_INFLIGHT 的 key 是指令 id，不是 job_id，必须取 values 里的 job_id
    existing = {c["job"]["job_id"] for c in _QUEUE}
    existing |= {c["job"]["job_id"] for c in _INFLIGHT.values()}
    created = []
    for job in jobs:
        jid = job.get("job_id", "")
        if not jid or jid in existing:
            continue
        cmd = {
            "id": uuid.uuid4().hex[:12],
            "type": "apply",
            "job": {
                "job_id": jid,
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "url": job.get("url", ""),
                "greeting": job.get("greeting", ""),
            },
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _QUEUE.append(cmd)
        created.append(cmd)
    return created


def pop(limit: int = 1) -> List[Dict]:
    """扩展来取指令；取走的移到 inflight，等 ack 确认。"""
    take = _QUEUE[:limit]
    del _QUEUE[:len(take)]
    for cmd in take:
        cmd["delivered_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _INFLIGHT[cmd["id"]] = cmd
    return take


def ack(cmd_id: str, ok: bool, reason: str = "") -> bool:
    """扩展执行完回报结果。"""
    cmd = _INFLIGHT.pop(cmd_id, None)
    if not cmd:
        return False
    cmd.update({
        "ok": ok,
        "reason": reason,
        "acked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    _DONE.append(cmd)
    if len(_DONE) > 200:
        del _DONE[:len(_DONE) - 200]
    return True


def stats() -> Dict:
    return {
        "queued": len(_QUEUE),
        "inflight": len(_INFLIGHT),
        "done": len(_DONE),
        "ok": sum(1 for c in _DONE if c.get("ok")),
        "failed": sum(1 for c in _DONE if not c.get("ok")),
        "recent": _DONE[-5:],
    }


def clear() -> None:
    _QUEUE.clear()
    _INFLIGHT.clear()
    _DONE.clear()
