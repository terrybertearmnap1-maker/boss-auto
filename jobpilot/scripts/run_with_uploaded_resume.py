"""用「已上传的简历」跑一轮，检查看板数据。"""

import httpx

with httpx.Client(timeout=120) as c:
    cur = c.get("http://127.0.0.1:8030/resume/current").json()
    print("当前简历:", cur.get("filename"), "| 技能", len(cur.get("profile", {}).get("skills", [])), "项")

    r = c.post("http://127.0.0.1:8030/run", json={})
    print("HTTP", r.status_code)
    d = r.json()
    if d.get("error"):
        print("错误:", d["error"])
    else:
        print("数据源", d.get("search_source"), "| 评估", d["stats"]["evaluated"],
              "| 投递", d["stats"]["applied"], "| 耗时", d.get("elapsed_ms"), "ms")
        for x in d.get("decisions", [])[:6]:
            print(f"  {x['score']:>3} | {x['decision']:<5} | {x['title'][:26]}")

    stats = c.get("http://127.0.0.1:8030/stats").json()
    print("统计:", stats)
