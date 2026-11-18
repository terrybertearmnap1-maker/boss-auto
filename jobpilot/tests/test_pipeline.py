"""端到端测试：/ingest 去重、LangGraph 决策、看板查询、WebSocket 实时推送。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from pipeline.api import app  # noqa: E402

GOOD = "负责 AI Agent 智能体开发，基于 LangGraph 编排任务，熟悉 Python 与大模型 API，了解 MCP 与 RAG。"
WEAK = "负责数据统计与报表，熟练使用 SQL。"
JAVA = "负责 Java 后端服务开发，熟悉 Spring Boot。"


def main():
    ok = True
    with TestClient(app) as client:
        h = client.get("/health").json()
        print("[health]", h)
        ok &= h["ok"] and h["vectors"] in ("qdrant", "memory")

        r1 = client.post("/ingest", json={"job_id": "t-good-1", "title": "AI Agent 开发工程师",
                                          "company": "测试公司", "salary": "12-20K", "jd": GOOD}).json()
        print("[ingest good]", r1["decision"], r1["score"], r1["reason"])
        ok &= r1["decision"] == "apply" and r1["score"] >= 60

        r2 = client.post("/ingest", json={"job_id": "t-weak-1", "title": "数据分析实习生", "jd": WEAK}).json()
        print("[ingest weak]", r2["decision"], r2["score"])
        ok &= r2["decision"] == "skip"

        r3 = client.post("/ingest", json={"job_id": "t-java-1", "title": "Java 后端开发", "jd": JAVA}).json()
        print("[ingest java]", r3["decision"], r3["reason"])
        ok &= r3["decision"] == "skip" and "排除词" in r3["reason"]

        r4 = client.post("/ingest", json={"job_id": "t-good-1", "title": "AI Agent 开发工程师", "jd": GOOD}).json()
        print("[ingest duplicate]", r4["duplicate"], r4["reason"])
        ok &= r4["duplicate"] is True

        jobs = client.get("/jobs?limit=10").json()
        ok &= any(j["job_id"] == "t-good-1" for j in jobs["items"])

        stats = client.get("/stats").json()
        print("[stats]", stats)
        ok &= stats["total"] >= 3 and stats["apply"] >= 1

        # 直接调用 _push 触发广播：在 TestClient 里「WS 连接 + 再发 HTTP」会互相阻塞
        from pipeline.api import _push

        with client.websocket_connect("/ws/live") as ws:
            _push({"type": "job", "job_id": "t-live-1", "decision": "apply", "score": 70, "title": "AI Agent 工程师"})
            ev = ws.receive_json()
            print("[ws live]", ev)
            ok &= ev["type"] == "job" and ev["job_id"] == "t-live-1"

        page = client.get("/")
        ok &= page.status_code == 200 and "JobPilot" in page.text

    print("全部通过" if ok else "存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
