"""FastAPI 应用：WebSocket 流式问答 + 健康检查 + 前端静态托管。

启动：
    uvicorn backend.app:app --reload --port 8000
或：
    python -m backend.app
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agent import ChatAgent

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="Agent Chat", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = ChatAgent(
    redis_url=os.getenv("REDIS_URL"),
    qdrant_url=os.getenv("QDRANT_URL"),
)


@app.get("/health")
def health():
    return {"ok": True, **agent.health()}


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            payload = await ws.receive_json()
            if payload.get("type") != "user":
                await ws.send_json({"type": "error", "message": "unsupported type"})
                continue

            conv_id = payload.get("conv_id") or "default"
            text = (payload.get("text") or "").strip()
            if not text:
                await ws.send_json({"type": "error", "message": "empty text"})
                continue

            # 生成器是同步的：放到线程里跑，用 asyncio.Queue 把每个事件转回事件循环，
            # 这样 token 是「生产一个推一个」，而不是攒完再发（后者等于没有流式）。
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()

            def worker(conv_id: str = conv_id, text: str = text) -> None:
                try:
                    for event in agent.stream(conv_id, text):
                        loop.call_soon_threadsafe(queue.put_nowait, event)
                except Exception as exc:  # noqa: BLE001
                    loop.call_soon_threadsafe(
                        queue.put_nowait, {"type": "error", "message": str(exc)}
                    )
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            loop.run_in_executor(None, worker)
            while True:
                event = await queue.get()
                if event is None:
                    break
                await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:  # noqa: BLE001
            pass


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, reload=False)
