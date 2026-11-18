"""简历上传与「当前简历」缓存。

为什么要单独一层：
- 上传是网络 IO（multipart），解析是 CPU/文件 IO，两者分开更好测
- 解析结果要能被后续 /run 复用，避免每次调用都重新上传
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional

_ALLOWED = {".pdf", ".docx", ".txt", ".md"}

# 落盘路径：服务重启后不用重新上传（data/ 已在 .gitignore 中）
_STORE = Path(os.getenv("RESUME_STORE", "data/current_resume.json"))

_CURRENT: Dict = {"text": "", "profile": None, "filename": "", "at": 0.0, "chars": 0}


def _save() -> None:
    try:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(_CURRENT, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load() -> None:
    try:
        if _STORE.exists():
            data = json.loads(_STORE.read_text(encoding="utf-8"))
            if data.get("text"):
                _CURRENT.update(data)
    except (OSError, ValueError):
        pass


_load()


def allowed(name: str) -> bool:
    return Path(name).suffix.lower() in _ALLOWED


def parse_upload(filename: str, data: bytes) -> Dict:
    """把上传的字节写成临时文件 → 复用 resume_io 读文本 → 交给 Agent1 解析。"""
    from agents import resume_agent
    from pipeline.resume_io import read_text

    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED:
        raise ValueError(f"不支持的文件类型：{suffix}（支持 pdf / docx / txt / md）")
    if not data:
        raise ValueError("文件是空的")
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("文件超过 10MB")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
        fh.write(data)
        tmp = Path(fh.name)
    try:
        text = read_text(tmp)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

    out = resume_agent.run({"resume_text": text, "trace": []})
    if out.get("errors"):
        raise ValueError(out["errors"][0])

    _CURRENT.update({
        "text": text,
        "profile": out["profile"],
        "filename": filename,
        "at": time.time(),
        "chars": len(text),
    })
    _save()
    return {
        "filename": filename,
        "chars": len(text),
        "profile": out["profile"],
        "keywords": out.get("keywords", []),
        "trace": out.get("trace", []),
    }


def set_text(text: str, source: str = "api") -> Dict:
    """也允许直接传文本（不经过文件）。"""
    from agents import resume_agent

    out = resume_agent.run({"resume_text": text, "trace": []})
    if out.get("errors"):
        raise ValueError(out["errors"][0])
    _CURRENT.update({
        "text": text,
        "profile": out["profile"],
        "filename": source,
        "at": time.time(),
        "chars": len(text),
    })
    _save()
    return {"filename": source, "chars": len(text), "profile": out["profile"],
            "keywords": out.get("keywords", []), "trace": out.get("trace", [])}


def current() -> Optional[Dict]:
    if not _CURRENT["text"]:
        return None
    return {
        "filename": _CURRENT["filename"],
        "chars": _CURRENT["chars"],
        "profile": _CURRENT["profile"],
        "age_seconds": round(time.time() - _CURRENT["at"], 1),
    }


def text() -> str:
    return _CURRENT["text"]


def clear() -> None:
    _CURRENT.update({"text": "", "profile": None, "filename": "", "at": 0.0, "chars": 0})
    try:
        _STORE.unlink(missing_ok=True)
    except OSError:
        pass
