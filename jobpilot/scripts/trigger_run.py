"""调用 /run 触发一次流水线，然后把看板需要的接口打出来。"""

import json
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8030"
ROOT = Path(__file__).resolve().parent.parent
text = (ROOT / "data" / "resume_sample.txt").read_text(encoding="utf-8")

with httpx.Client(timeout=60) as c:
    r = c.post(f"{BASE}/run", json={"text": text, "threshold": 60, "limit": 10})
    r.raise_for_status()
    data = r.json()
    print("== /run ==")
    print("评估", data["stats"]["evaluated"], "/ 投递", data["stats"]["applied"], "/ 耗时", data["elapsed_ms"], "ms")
    for d in data["decisions"][:4]:
        print(f"  {d['score']:>3} | {d['decision']:<5} | {d['title'][:24]}")

    print("\n== /runs/last ==")
    print(json.dumps(c.get(f"{BASE}/runs/last").json(), ensure_ascii=False))

    print("\n== /stats ==")
    print(json.dumps(c.get(f"{BASE}/stats").json(), ensure_ascii=False))

    print("\n== /jobs 前 5 ==")
    for j in c.get(f"{BASE}/jobs", params={"limit": 5}).json()["items"]:
        print(f"  {j['score']:>3} | {j['decision']:<5} | {j['title'][:24]:<26} | 扣分 {j.get('penalty')} {j.get('penalty_reasons') or ''}")
