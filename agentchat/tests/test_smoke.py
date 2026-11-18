"""最小端到端测试：健康检查 + WebSocket 流式事件序列。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402


def collect(ws, text, conv_id="t1"):
    ws.send_json({"type": "user", "text": text, "conv_id": conv_id})
    events = []
    while True:
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] in ("done", "error"):
            break
    return events


def main():
    ok = True
    with TestClient(app) as client:
        health = client.get("/health").json()
        print("[health]", health)
        ok &= health["ok"] is True and health["docs"] > 0

        with client.websocket_connect("/ws/chat") as ws:
            events = collect(ws, "LangGraph 的条件边怎么用？")
            types = [e["type"] for e in events]
            print("[ws] 事件序列:", types[:6], "... 共", len(types))
            ok &= "token" in types and types[-1] == "done"
            ok &= any(e["type"] == "sources" and e["items"] for e in events)

            # 工具调用路由
            events2 = collect(ws, "现在几点？", conv_id="t2")
            ok &= any(e["type"] == "tool" and e["name"] == "now" for e in events2)

            # 多轮记忆：第二轮应当能拿到历史（这里只验证不报错且能流式返回）
            events3 = collect(ws, "刚才说的方法再解释一下", conv_id="t2")
            ok &= events3[-1]["type"] == "done"

        page = client.get("/")
        ok &= page.status_code == 200 and "Agent Chat" in page.text

    print("全部通过" if ok else "存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
