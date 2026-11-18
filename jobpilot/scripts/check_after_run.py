"""跑完后的状态检查。"""

import httpx

BASE = "http://127.0.0.1:8030"

with httpx.Client(timeout=20) as c:
    s = c.get(f"{BASE}/stats").json()
    print(f"今日已投 {s['today_count']} | 库内岗位 {s['total']} | apply {s['apply']} | skip {s['skip']}")

    b = c.get(f"{BASE}/search/latest").json()
    print("扩展批次:", {k: b.get(k) for k in ("count", "age_seconds", "source")})

    cmd = c.get(f"{BASE}/commands/status").json()
    print("指令队列:", {k: cmd[k] for k in ("queued", "inflight", "done", "ok", "failed")})

    jobs = c.get(f"{BASE}/jobs", params={"limit": 12}).json()["items"]
    print("\n最近入库:")
    for j in jobs[:10]:
        ts = (j.get("created_at") or "")[11:16]
        print(f"  {ts} | {j.get('source',''):<14} | {str(j.get('score')):>3} | {j.get('title','')[:26]}")
