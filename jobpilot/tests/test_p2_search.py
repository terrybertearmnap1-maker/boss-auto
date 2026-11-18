"""P2 验收测试：扩展数据接入 Agent2（批次缓存 / 过期回退 / 真实记录复用）。"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.search_agent import BrowserHallSearch, LocalIndexSearch, RecentJobsSearch  # noqa: E402
from pipeline import search_hub  # noqa: E402

REAL_JOBS = [
    {"job_id": "real-1", "title": "AI Agent 开发工程师", "company": "某真实公司",
     "salary": "15-25K", "city": "广州", "url": "https://www.zhipin.com/job_detail/real-1.html",
     "jd": "负责 AI Agent 智能体开发，熟悉 Python、LangGraph、MCP、RAG 与 Qdrant，了解 FastAPI 与 Redis。"},
    {"job_id": "real-2", "title": "Java 后端开发", "company": "另一家公司",
     "salary": "11-14K", "city": "广州", "url": "https://www.zhipin.com/job_detail/real-2.html",
     "jd": "负责 Java 后端服务开发，熟悉 Spring Boot 与 MySQL。"},
]


def main() -> int:
    ok = True

    # 1) 批次缓存：扩展上报后 Agent2 能读到
    search_hub.clear()
    search_hub.put(["Agent", "智能体"], "广州", REAL_JOBS, source="extension")
    hits = BrowserHallSearch().search(keywords=["Agent"], city="广州", limit=10)
    print(f"[批次] 命中 {len(hits)} 条：{[h['job_id'] for h in hits]}")
    ok &= len(hits) == 1 and hits[0]["job_id"] == "real-1"

    # 2) 关键词不匹配时应为空（不能把 Java 岗塞进来）
    hits2 = BrowserHallSearch().search(keywords=["机器学习"], city="广州", limit=10)
    print(f"[过滤] 关键词不匹配 → {len(hits2)} 条")
    ok &= hits2 == []

    # 3) 批次过期 → 返回空，调用方应回退
    search_hub._LATEST["at"] = time.time() - 4000
    stale = BrowserHallSearch(max_age=900).search(keywords=["Agent"], limit=10)
    print(f"[过期] 4000 秒前的批次 → {len(stale)} 条")
    ok &= stale == []
    search_hub.clear()

    # 4) 无批次时，本地索引仍可用（保证 demo 不翻车）
    local = LocalIndexSearch().search(keywords=["Agent"], city="广州", limit=5)
    print(f"[兜底] 本地索引命中 {len(local)} 条")
    ok &= len(local) >= 1

    # 5) 真实记录复用：只认 source=zhipin，排除流水线自己写进去的
    #    这里自造两条记录，避免测试依赖运行环境里恰好存在的数据
    from pipeline.api import db

    base_row = {"salary": "10-20K", "url": "u", "score": 70, "decision": "apply",
                "reason": "", "matched": "", "greeting": ""}
    db.upsert({**base_row, "job_id": "t-zhipin-1", "title": "真实岗位", "company": "甲",
               "source": "zhipin", "jd": "熟悉 Python 与 LangGraph，了解 MCP 与 Qdrant。"})
    db.upsert({**base_row, "job_id": "t-pipe-1", "title": "流水线产物", "company": "乙",
               "source": "agent-pipeline", "jd": "熟悉 Python 与 LangGraph，了解 MCP。"})

    ids = [j["job_id"] for j in RecentJobsSearch().search(keywords=[], limit=50)]
    print(f"[复用] 真实岗位 {('t-zhipin-1' in ids)} / 流水线产物被排除 {('t-pipe-1' not in ids)}")
    ok &= "t-zhipin-1" in ids
    ok &= "t-pipe-1" not in ids      # 不能把自己写的结果再当输入

    print("\nP2 验收通过" if ok else "\nP2 验收失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
