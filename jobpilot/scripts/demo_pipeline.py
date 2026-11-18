"""跑一轮并把四个 Agent 的轨迹打印出来。"""

import httpx

with httpx.Client(timeout=60) as c:
    d = c.post("http://127.0.0.1:8030/run", json={"limit": 8, "threshold": 60}).json()

print("数据源:", d["search_source"], "| 耗时:", d["elapsed_ms"], "ms")
print()
for line in d["trace"]:
    print(line)

print()
print("最终决策：")
for x in d["decisions"]:
    score = x["score"] if x["score"] is not None else "-"
    print(f"  {str(score):>3} | {x['decision']:<5} | {x['title'][:26]:<28} | {x['reason']}")
