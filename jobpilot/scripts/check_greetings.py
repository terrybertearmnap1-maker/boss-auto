"""统计一次运行里 LLM 话术与模板话术的比例，并展示样本。"""

import time

import httpx

t0 = time.time()
with httpx.Client(timeout=180) as c:
    d = c.post("http://127.0.0.1:8030/run", json={"limit": 4}).json()

decisions = d["decisions"]
llm = [x for x in decisions if x.get("greeting_source") == "llm"]
tpl = [x for x in decisions if x.get("greeting_source") == "template"]

print(f"评估 {d['stats']['evaluated']} | LLM {len(llm)} 条 | 模板 {len(tpl)} 条 | "
      f"耗时 {round(time.time() - t0, 1)}s")
print()
for x in decisions[:4]:
    print(f"· {x['title'][:30]} | {x.get('greeting_source')} | {x['score']} 分")
    print(f"  {x['greeting']}")
    print()
