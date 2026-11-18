"""Agent2 两段式搜索测试：关键词粗筛 + 命中不足时放宽补量。

核心要验证的是「结果不够时自动放宽，够了就不多此一举」——
否则要么投得少，要么每轮都去扫全库。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import search_agent  # noqa: E402

PROFILE = {"city": "广州", "salary_min": 4, "keywords": ["Agent", "智能体"]}


class StubSearch:
    """可控的搜索桩：按 keywords 是否为空返回不同批次。"""

    def __init__(self, narrow, wide):
        self.narrow = narrow
        self.wide = wide
        self.calls = []

    def search(self, keywords, city="", salary_min=0, limit=10):
        self.calls.append(list(keywords))
        pool = self.narrow if keywords else self.wide
        return [dict(j) for j in pool[:limit]]


def job(i, title, relaxed_ok=True):
    return {"job_id": f"j{i}", "title": title, "company": f"公司{i}",
            "salary": "10-20K", "jd": "熟悉 Python 与 Agent 开发" * 2, "city": "广州"}


def main() -> int:
    ok = True

    # 1) 粗筛不足 → 放宽带关键词为空的第二段
    narrow = [job(1, "AI Agent 开发")]
    wide = [job(1, "AI Agent 开发"), job(2, "大模型应用"), job(3, "Python 后端"),
            job(4, "数据平台"), job(5, "算法工程"), job(6, "平台研发"), job(7, "测试开发")]
    stub = StubSearch(narrow, wide)
    out = search_agent.run({"profile": PROFILE, "keywords": ["Agent"], "limit": 8, "trace": []}, tool=stub)
    jobs = out["jobs"]
    print(f"[放宽] 共 {len(jobs)} 个，调用 {len(stub.calls)} 次，第二段关键词={stub.calls[-1]}")
    ok &= len(jobs) >= 6
    ok &= len(stub.calls) == 2 and stub.calls[1] == []
    ok &= sum(1 for j in jobs if j.get("relaxed")) >= 5

    # 2) 粗筛足够 → 不应触发放宽
    enough = [job(i, f"AI Agent {i}") for i in range(1, 9)]
    stub2 = StubSearch(enough, enough)
    out2 = search_agent.run({"profile": PROFILE, "keywords": ["Agent"], "limit": 8, "trace": []}, tool=stub2)
    print(f"[充足] 共 {len(out2['jobs'])} 个，调用 {len(stub2.calls)} 次")
    ok &= len(stub2.calls) == 1
    ok &= len(out2["jobs"]) == 8

    # 3) 放宽也不能突破 limit（避免一轮扫太多）
    stub3 = StubSearch([job(1, "AI Agent")], [job(i, f"岗位{i}") for i in range(1, 30)])
    out3 = search_agent.run({"profile": PROFILE, "keywords": ["Agent"], "limit": 5, "trace": []}, tool=stub3)
    print(f"[上限] limit=5 → 实际 {len(out3['jobs'])} 个")
    ok &= len(out3["jobs"]) <= 5

    # 4) trace 里要写清「放宽补了几个」
    ok &= any("放宽" in line for line in out["trace"])
    print("[trace]", out["trace"][0])

    print("\nAgent2 测试通过" if ok else "\nAgent2 测试失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
