"""看两条真实岗位的 JD 与打分依据。"""

import httpx

BASE = "http://127.0.0.1:8030"

with httpx.Client(timeout=20) as c:
    jobs = c.get(f"{BASE}/jobs", params={"limit": 12}).json()["items"]

for j in jobs:
    if j.get("source") != "zhipin":
        continue
    print("=" * 70)
    print("职位:", j["title"], "| 薪资:", j["salary"], "| 分数:", j["score"], "| 决策:", j["decision"])
    print("命中技能:", j.get("matched") or "（无）")
    print("拒绝原因:", j.get("reason"))
    print("JD 长度:", len(j.get("jd") or ""))
    print("JD 前 200 字:", (j.get("jd") or "")[:200].replace("\n", " "))
