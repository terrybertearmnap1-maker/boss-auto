"""盯队列 20 秒，看扩展有没有取走并执行。"""

import time

import httpx

BASE = "http://127.0.0.1:8030"

with httpx.Client(timeout=20) as c:
    for i in range(5):
        st = c.get(f"{BASE}/commands/status").json()
        print(f"[{i*5:>2}s] queued={st['queued']} inflight={st['inflight']} "
              f"done={st['done']} ok={st['ok']} failed={st['failed']}")
        if st["done"] > 0:
            print()
            for r in st.get("recent", []):
                print(f"  结果: {r['job']['title'][:26]} | ok={r['ok']} | "
                      f"reason={r.get('reason') or '(无)'}")
            break
        time.sleep(5)
