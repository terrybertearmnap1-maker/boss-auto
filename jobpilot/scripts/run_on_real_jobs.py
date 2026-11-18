"""清空批次后，用「库里扩展真实上报过的岗位」跑流水线（browser-recent 路径）。"""

from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8030"
ROOT = Path(__file__).resolve().parent.parent
resume = (ROOT / "data" / "resume_sample.txt").read_text(encoding="utf-8")

with httpx.Client(timeout=60) as c:
    c.post(f"{BASE}/search/clear")
    print("已清空批次缓存:", c.get(f"{BASE}/search/latest").json())

    run = c.post(f"{BASE}/run", json={"text": resume, "threshold": 60, "limit": 10}).json()
    print("数据源:", run["search_source"], "| 评估", run["stats"]["evaluated"],
          "| 投递", run["stats"]["applied"], "| 耗时", run["elapsed_ms"], "ms")
    print("\n决策明细（来自扩展真实上报的 JD）：")
    for d in run["decisions"]:
        score = d["score"] if d["score"] is not None else " - "
        print(f"  {score!s:>3} | {d['decision']:<5} | {d['title'][:30]:<32} | {d['reason']}")
