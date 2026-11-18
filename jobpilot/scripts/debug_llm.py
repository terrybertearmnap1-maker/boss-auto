"""逐个岗位看 LLM 生成结果与回退原因。"""

import json

import httpx

BASE = "http://127.0.0.1:8030"

with httpx.Client(timeout=180) as c:
    cur = c.get(f"{BASE}/resume/current").json()
    profile = cur["profile"]
    run = c.post(f"{BASE}/run", json={"limit": 4}).json()

print("profile 技能:", profile["skills"][:8], "...")
print()
for x in run["decisions"]:
    print(f"· {x['title'][:30]} | {x.get('greeting_source')}")
    print(f"  {x['greeting']}")
    print()
