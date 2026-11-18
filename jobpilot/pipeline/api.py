"""FastAPI 服务：接收扩展上报 → 去重 → 决策 → 入库，并给看板提供查询与实时推送。

接口：
    POST /ingest        扩展上报一个岗位（JD 文本 + 元信息）
    GET  /jobs          岗位列表（可按决策过滤）
    GET  /stats         汇总指标
    GET  /health        各后端实际生效情况
    WS   /ws/live       新岗位上架实时推送（看板订阅）
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import commands, graph, resume_store, search_hub
from .cache import build_cache
from .config import CONFIG
from .db import build_db
from .vectors import build_vectors

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="JobPilot", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

db = build_db(CONFIG.database_url)
cache = build_cache(CONFIG.redis_url)
vectors = build_vectors(CONFIG.qdrant_url)

LAST_RUN: Dict = {}
_subscribers: Set[WebSocket] = set()
_loop: Optional[asyncio.AbstractEventLoop] = None


class JobIn(BaseModel):
    job_id: str
    title: str = ""
    company: str = ""
    salary: str = ""
    url: str = ""
    source: str = "zhipin"
    jd: str = ""


class SearchBatchIn(BaseModel):
    keywords: List[str] = []
    city: str = ""
    jobs: List[Dict] = []
    source: str = "extension"


class PipelineIn(BaseModel):
    text: str = ""          # 留空则用 /resume/upload 上传过的简历
    threshold: int = 60
    limit: int = 8
    execute: bool = False   # True 时把通过的岗位排进投递指令队列


class CommandAckIn(BaseModel):
    id: str
    ok: bool
    reason: str = ""

class JobOut(BaseModel):
    job_id: str
    decision: str
    score: int
    reason: str
    matched: List[str] = []
    greeting: str = ""
    duplicate: bool = False


@app.on_event("startup")
async def _startup() -> None:
    global _loop
    _loop = asyncio.get_running_loop()


async def broadcast(payload: Dict) -> None:
    dead = []
    for ws in list(_subscribers):
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        _subscribers.discard(ws)


def _push(payload: Dict) -> None:
    """从同步上下文（测试 / 线程）推送到所有订阅者。"""
    if _loop and _loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast(payload), _loop)


@app.get("/health")
def health() -> Dict:
    return {
        "ok": True,
        "db": db.backend,
        "cache": cache.backend,
        "vectors": vectors.backend,
        "threshold": CONFIG.score_threshold,
        "dedup_threshold": CONFIG.dedup_threshold,
    }


@app.post("/ingest", response_model=JobOut)
def ingest(job: JobIn) -> JobOut:
    # 1) 已处理过 → 直接返回，不重复打分
    if cache.seen(job.job_id):
        return JobOut(job_id=job.job_id, decision="skip", score=0, reason="已处理过（去重）", duplicate=True)

    # 2) JD 相似度去重（同岗重发）
    neighbor, sim = vectors.nearest(job.jd)
    if neighbor and sim >= CONFIG.dedup_threshold:
        cache.mark(job.job_id)
        return JobOut(job_id=job.job_id, decision="skip", score=0,
                      reason=f"与 {neighbor} 相似度 {sim:.2f}，判定重复", duplicate=True)

    # 3) LangGraph 决策
    final = graph.evaluate(job.model_dump(), CONFIG.score_threshold)

    # 4) 入库 + 标记 + 向量化
    db.upsert({
        "job_id": job.job_id,
        "title": job.title,
        "company": job.company,
        "salary": job.salary,
        "url": job.url,
        "source": job.source,
        "score": final.get("score", 0),
        "decision": final.get("decision", "skip"),
        "reason": final.get("reason", ""),
        "matched": " / ".join(final.get("matched", [])),
        "greeting": final.get("greeting", ""),
        "jd": (job.jd or "")[:4000],
    })
    cache.mark(job.job_id)
    if job.jd:
        vectors.add(job.job_id, job.jd)
    if final.get("decision") == "apply":
        cache.incr_daily()

    _push({"type": "job", "job_id": job.job_id, "title": job.title,
           "score": final.get("score", 0), "decision": final.get("decision")})

    return JobOut(
        job_id=job.job_id,
        decision=final.get("decision", "skip"),
        score=int(final.get("score", 0)),
        reason=final.get("reason", ""),
        matched=final.get("matched", []),
        greeting=final.get("greeting", ""),
        duplicate=False,
    )


@app.post("/resume")
def parse_resume(body: PipelineIn) -> Dict:
    """只跑 Agent1：简历文本 → 结构化画像（技能/方向/关键词/城市/薪资）。"""
    from agents import resume_agent

    out = resume_agent.run({"resume_text": body.text, "trace": []})
    return {"profile": out["profile"], "keywords": out["keywords"], "trace": out["trace"]}


@app.post("/run")
def run_agents(body: PipelineIn) -> Dict:
    """跑完整四段流水线：解析 → 搜索 → 匹配 → 决策，并把通过的岗位入库。"""
    from . import orchestrator

    # 优先用扩展上报的真实岗位；没有（或过期）就回退本地索引
    from agents.search_agent import BrowserHallSearch, LocalIndexSearch, RecentJobsSearch

    # 优先级：扩展刚推的批次 > 扩展历史上报的真实岗位 > 本地索引
    batch = search_hub.get()
    if batch and batch["jobs"]:
        tool, search_source = BrowserHallSearch(), "browser-batch"
    else:
        recent = RecentJobsSearch()
        if recent.search(keywords=[], limit=1):
            tool, search_source = recent, "browser-recent"
        else:
            tool, search_source = LocalIndexSearch(), "local"

    resume_text = body.text or resume_store.text()
    if not resume_text:
        return {"error": "没有简历：先上传简历（POST /resume/upload），或在请求体里传 text"}

    result = orchestrator.run_pipeline(
        resume_text, threshold=body.threshold, limit=body.limit, tool=tool)
    result["search_source"] = search_source
    applied = 0
    for d in result.get("decisions", []):
        if d.get("decision") != "apply":
            continue
        db.upsert({
            "job_id": d.get("job_id", ""),
            "title": d.get("title", ""),
            "company": d.get("company", ""),
            "salary": d.get("salary", ""),
            "url": d.get("url", ""),
            "source": "agent-pipeline",
            "score": d.get("score", 0),
            "decision": "apply",
            "reason": d.get("reason", ""),
            "matched": " / ".join(d.get("matched", [])),
            "greeting": d.get("greeting", ""),
            "penalty": d.get("penalty", 0),
            "penalty_reasons": " / ".join(d.get("penalty_reasons") or []),
            "jd": (d.get("jd") or "")[:4000],
        })
        cache.mark(d.get("job_id", ""))
        applied += 1

    queued = 0
    if body.execute:
        approved = [d for d in result.get("decisions", []) if d.get("decision") == "apply"]
        queued = len(commands.enqueue(approved))

    LAST_RUN.clear()
    LAST_RUN.update({
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "evaluated": len(result.get("decisions", [])),
        "applied": applied,
        "elapsed_ms": result.get("elapsed_ms"),
        "errors": result.get("errors") or [],
        "search_source": result.get("search_source", "local"),
        "queued_commands": queued,
        "city": (result.get("profile") or {}).get("city", ""),
    })
    _push({"type": "run", "applied": applied, "evaluated": LAST_RUN["evaluated"]})

    return {
        "profile": result.get("profile"),
        "stats": {"evaluated": len(result.get("decisions", [])), "applied": applied},
        "elapsed_ms": result.get("elapsed_ms"),
        "search_source": result.get("search_source", "local"),
        "queued_commands": queued,
        "trace": result.get("trace"),
        "decisions": [
            {k: d.get(k) for k in ("job_id", "title", "company", "salary", "score",
                                   "decision", "reason", "greeting", "greeting_source", "penalty", "penalty_reasons")}
            for d in result.get("decisions", [])
        ],
    }


@app.get("/jobs")
def list_jobs(limit: int = 50, decision: Optional[str] = None) -> Dict:
    return {
        "items": db.list_jobs(limit=limit, decision=decision),
        "today_count": cache.daily_count(),
    }


@app.get("/stats")
def stats() -> Dict:
    return {**db.stats(), "today_count": cache.daily_count(), "layer": {
        "db": db.backend, "cache": cache.backend, "vectors": vectors.backend}}


@app.post("/resume/upload")
async def upload_resume(file: UploadFile = File(...)) -> Dict:
    """上传简历（PDF / DOCX / TXT / MD），解析成结构化画像并缓存，供后续 /run 使用。"""
    data = await file.read()
    try:
        return resume_store.parse_upload(file.filename or "resume.pdf", data)
    except ValueError as exc:
        return {"error": str(exc)}


@app.get("/resume/current")
def current_resume() -> Dict:
    cur = resume_store.current()
    return cur or {"error": "尚未上传简历"}


@app.delete("/resume/current")
def clear_resume() -> Dict:
    resume_store.clear()
    return {"ok": True}


@app.post("/search-results")
def upload_search_batch(batch: SearchBatchIn) -> Dict:
    """扩展抓完一页岗位后，把结果推上来；Agent2 直接消费这批数据。"""
    search_hub.put(batch.keywords, batch.city, batch.jobs, batch.source)
    _push({"type": "search", "count": len(batch.jobs), "city": batch.city})
    return {"ok": True, "received": len(batch.jobs), "at": time.strftime("%Y-%m-%d %H:%M:%S")}


@app.post("/search/clear")
def clear_search_batch() -> Dict:
    """调试：清空当前缓存的岗位批次，方便验证扩展是否真的推上来了。"""
    search_hub.clear()
    return {"ok": True, "cleared": True}


@app.get("/search/latest")
def latest_search_batch() -> Dict:
    """调试：看当前缓存的是哪一批岗位。"""
    snap = search_hub.snapshot()
    return {
        "source": snap.get("source"),
        "city": snap.get("city"),
        "keywords": snap.get("keywords"),
        "count": len(snap.get("jobs") or []),
        "age_seconds": round(time.time() - snap.get("at", 0), 1) if snap.get("at") else None,
    }


@app.get("/commands")
def fetch_commands(limit: int = 1) -> Dict:
    """扩展轮询取投递指令。"""
    return {"items": commands.pop(limit), "stats": commands.stats()}


class CommandIn(BaseModel):
    job_id: str
    title: str = ""
    company: str = ""
    url: str
    greeting: str = ""


@app.post("/commands/enqueue")
def enqueue_command(body: CommandIn) -> Dict:
    """手动把一条投递指令排进队列（测试 / 看板手动投递用）。"""
    items = commands.enqueue([body.model_dump()])
    return {"ok": bool(items), "item": items[0] if items else None}


@app.post("/commands/ack")
def ack_command(body: CommandAckIn) -> Dict:
    """扩展回报执行结果。"""
    return {"ok": commands.ack(body.id, body.ok, body.reason)}


@app.get("/commands/status")
def command_status() -> Dict:
    return commands.stats()


@app.post("/commands/clear")
def clear_commands() -> Dict:
    commands.clear()
    return {"ok": True}


@app.get("/runs/last")
def last_run() -> Dict:
    """最近一次流水线运行的汇总（看板顶部展示）。"""
    return LAST_RUN or {"evaluated": 0, "applied": 0, "at": None}


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()
    _subscribers.add(ws)
    try:
        while True:
            await ws.receive_text()  # 心跳，客户端定时发 ping
    except WebSocketDisconnect:
        _subscribers.discard(ws)
    except Exception:  # noqa: BLE001
        _subscribers.discard(ws)


if WEB_DIR.exists():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(WEB_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pipeline.api:app", host="127.0.0.1", port=CONFIG.port, reload=False)
