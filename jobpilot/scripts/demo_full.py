"""清理测试记录并跑一轮完整演示。"""

import sqlite3

import httpx

DB = r"C:\Users\EDY\Documents\deepseek-harness\default-workspace\boss-auto\jobpilot\jobpilot.db"

conn = sqlite3.connect(DB)
removed = conn.execute("DELETE FROM jobs WHERE job_id LIKE 't-%'").rowcount
conn.commit()
print("清理测试记录:", removed)

with httpx.Client(timeout=60) as c:
    d = c.post("http://127.0.0.1:8030/run", json={"limit": 8, "threshold": 60}).json()
    print(f"数据源: {d['search_source']} | 评估 {d['stats']['evaluated']} | "
          f"投递 {d['stats']['applied']} | {d['elapsed_ms']} ms")
    print()
    for line in d["trace"]:
        print(line)
    print()
    for x in d["decisions"]:
        score = x["score"] if x["score"] is not None else "-"
        print(f"  {str(score):>3} | {x['decision']:<5} | {x['title'][:26]:<28} | {x['reason']}")
