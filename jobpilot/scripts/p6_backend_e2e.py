"""P6 后端侧验证：/run?execute=true 生成投递指令，扩展取走并 ack。"""

from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8030"
ROOT = Path(__file__).resolve().parent.parent
resume = (ROOT / "data" / "resume_sample.txt").read_text(encoding="utf-8")

BATCH = {
    "keywords": ["Agent"],
    "city": "广州",
    "source": "extension",
    "jobs": [
        {"job_id": "p6-001", "title": "AI Agent 开发工程师", "company": "甲公司",
         "salary": "15-25K", "city": "广州", "url": "https://www.zhipin.com/job_detail/p6-001.html",
         "jd": "负责 AI Agent 智能体开发，熟悉 Python、LangGraph、MCP、RAG 与 Qdrant，了解 FastAPI、Redis，应届生亦可。"},
        {"job_id": "p6-002", "title": "大模型应用工程师", "company": "乙公司",
         "salary": "18-30K", "city": "广州", "url": "https://www.zhipin.com/job_detail/p6-002.html",
         "jd": "负责大模型应用落地，熟悉 Python、LangGraph、Prompt 工程，了解 MCP 与向量数据库。"},
    ],
}

with httpx.Client(timeout=60) as c:
    c.post(f"{BASE}/commands/clear")
    c.post(f"{BASE}/search/clear")
    c.post(f"{BASE}/search-results", json=BATCH)

    run = c.post(f"{BASE}/run", json={
        "text": resume, "threshold": 60, "limit": 8, "execute": True,
    }).json()
    print(f"== /run ==")
    print(f"  数据源 {run['search_source']} | 评估 {run['stats']['evaluated']} | "
          f"投递 {run['stats']['applied']} | 入队 {run['queued_commands']}")

    print("\n== 扩展取指令 ==")
    got = c.get(f"{BASE}/commands", params={"limit": 2}).json()
    for item in got["items"]:
        job = item["job"]
        print(f"  [{item['id']}] {job['title']} @ {job['company']} | 话术 {len(job['greeting'])} 字")

    print("\n== 扩展 ack ==")
    for item in got["items"]:
        r = c.post(f"{BASE}/commands/ack", json={"id": item["id"], "ok": True, "reason": ""}).json()
        print(f"  ack {item['id']} → {r}")

    print("\n== 指令状态 ==")
    st = c.get(f"{BASE}/commands/status").json()
    print(f"  queued={st['queued']} inflight={st['inflight']} done={st['done']} ok={st['ok']} failed={st['failed']}")

    # 再取一次应为空
    again = c.get(f"{BASE}/commands", params={"limit": 2}).json()
    print(f"\n== 再取一次 ==")
    print(f"  剩余指令 {len(again['items'])} 条（应为 0）")
