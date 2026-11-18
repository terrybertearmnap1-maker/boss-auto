"""P2 端到端：模拟扩展上报 → /run 用浏览器批次 → 看决策结果。"""

import json
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8030"
ROOT = Path(__file__).resolve().parent.parent
resume = (ROOT / "data" / "resume_sample.txt").read_text(encoding="utf-8")

# 模拟扩展在 BOSS 上抓到的真实岗位（含 JD）
batch = {
    "keywords": ["Agent", "智能体"],
    "city": "广州",
    "source": "extension",
    "jobs": [
        {"job_id": "boss-real-001", "title": "AI Agent 开发工程师", "company": "真实公司A",
         "salary": "15-25K", "city": "广州", "url": "https://www.zhipin.com/job_detail/001.html",
         "jd": "岗位职责：负责 AI Agent 智能体产品开发，基于 LangGraph 编排任务。任职要求：熟悉 Python、MCP、RAG，了解 Qdrant 与 FastAPI，应届生亦可。"},
        {"job_id": "boss-real-002", "title": "AI 平台后端工程师（3-5 年）", "company": "真实公司B",
         "salary": "20-35K", "city": "广州", "url": "https://www.zhipin.com/job_detail/002.html",
         "jd": "岗位职责：负责 AI 平台后端架构。任职要求：3-5 年工作经验，精通 Python、FastAPI、Redis、Docker。"},
        {"job_id": "boss-real-003", "title": "数据分析实习生", "company": "真实公司C",
         "salary": "150-200元/天", "city": "广州", "url": "https://www.zhipin.com/job_detail/003.html",
         "jd": "岗位职责：协助梳理指标，编写 SQL 提取数据。任职要求：数学统计相关专业。"},
    ],
}

with httpx.Client(timeout=60) as c:
    up = c.post(f"{BASE}/search-results", json=batch).json()
    print("== 扩展上报 ==", up)

    latest = c.get(f"{BASE}/search/latest").json()
    print("== 缓存批次 ==", json.dumps(latest, ensure_ascii=False))

    run = c.post(f"{BASE}/run", json={"text": resume, "threshold": 60, "limit": 10}).json()
    print("== /run ==", json.dumps({
        "search_source": run["search_source"],
        "evaluated": run["stats"]["evaluated"],
        "applied": run["stats"]["applied"],
        "elapsed_ms": run["elapsed_ms"],
    }, ensure_ascii=False))

    print("== 决策明细 ==")
    for d in run["decisions"]:
        print(f"  {d['score']:>3} | {d['decision']:<5} | {d['title'][:24]:<26} | {d['reason']}")
