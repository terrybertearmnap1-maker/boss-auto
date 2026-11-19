"""测试 /greeting：同一份简历，两个不同岗位应产出不同话术。"""

import httpx

JOBS = [
    {"title": "AI Agent 开发工程师", "company": "迈络科技",
     "jd": "负责 Agent 任务规划、工具调用、记忆模块开发。要求熟悉 Python、LangGraph、MCP，了解 RAG 与向量数据库。",
     "matched": ["Python", "Agent", "LangGraph"]},
    {"title": "大模型应用工程师", "company": "云智科技",
     "jd": "负责 RAG 知识库问答、Prompt 工程与向量检索优化。要求熟悉 LangChain、向量数据库、FastAPI。",
     "matched": ["Python", "RAG", "LangChain"]},
]

with httpx.Client(timeout=60) as c:
    for job in JOBS:
        d = c.post("http://127.0.0.1:8030/greeting", json=job).json()
        print(f"[{d.get('source')}] {job['title']}")
        print("  ", d.get("greeting") or d.get("error"))
        if d.get("reason"):
            print("   回退原因:", d["reason"])
        print()
