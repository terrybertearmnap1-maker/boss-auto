"""挑一个真实岗位，生成 LLM 话术，排进队列等待扩展执行。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from agents import decide_agent  # noqa: E402


BASE = "http://127.0.0.1:8030"

with httpx.Client(timeout=60) as c:
    c.post(f"{BASE}/commands/clear")
    jobs = c.get(f"{BASE}/jobs", params={"limit": 30}).json()["items"]

    # 只要扩展上报的真实岗位，且带可访问的 URL
    real = [j for j in jobs if j.get("source") == "zhipin" and (j.get("url") or "").startswith("http")]
    if not real:
        raise SystemExit("库里没有带 URL 的真实岗位，先用扩展跑一轮")

    # 选分数最高的一条
    real.sort(key=lambda j: j.get("score") or 0, reverse=True)
    job = real[0]
    print(f"选中：{job['title'][:30]} @ {job.get('company','')} | {job.get('score')} 分")
    print(f"URL：{job['url']}")

    profile = c.get(f"{BASE}/resume/current").json()["profile"]
    detail = {
        "title": job["title"], "company": job.get("company", ""),
        "jd": job.get("jd", ""), "matched": (job.get("matched") or "").split("/"),
    }
    greeting = decide_agent._llm_greeting(detail, profile) or decide_agent._template(detail, profile)
    over = decide_agent._overclaims(greeting, profile, detail["matched"])
    print(f"\n话术（{len(greeting)} 字，过度声称={over or '无'}）：\n{greeting}\n")

    r = c.post(f"{BASE}/commands/enqueue", json={
        "job_id": job["job_id"], "title": job["title"], "company": job.get("company", ""),
        "url": job["url"], "greeting": greeting,
    }).json()
    print("入队:", r["ok"], "| 指令 id:", (r.get("item") or {}).get("id"))
    print("队列状态:", c.get(f"{BASE}/commands/status").json())
