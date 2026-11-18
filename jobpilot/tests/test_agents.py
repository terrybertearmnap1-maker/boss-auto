"""四段式 Agent 流水线的端到端测试。

验证：Agent1 抽取 → Agent2 搜索 → Agent3 匹配 → Agent4 决策，
以及「排除词只看标题」「覆盖率分母是 JD 技能」这两条关键规则。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import match_agent, resume_agent, search_agent  # noqa: E402
from pipeline.orchestrator import run_pipeline  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESUME = (ROOT / "data" / "resume_sample.txt").read_text(encoding="utf-8")


def main() -> int:
    ok = True

    # Agent1
    a1 = resume_agent.run({"resume_text": RESUME, "trace": []})
    profile = a1["profile"]
    print("[Agent1]", profile["directions"], profile["keywords"], profile["city"], profile["salary_min"])
    ok &= "Agent" in profile["directions"]
    ok &= "数据分析" not in profile["directions"]      # MySQL 里的 SQL 不应误触发
    ok &= profile["city"] == "广州"

    # Agent2
    a2 = search_agent.run({"profile": profile, "keywords": profile["keywords"], "limit": 10, "trace": []})
    print(f"[Agent2] 命中 {len(a2['jobs'])} 个岗位")
    ok &= len(a2["jobs"]) >= 3

    # Agent3：分母是 JD 要求的技能，不是我的技能全集
    cov = match_agent.skill_coverage(RESUME, "要求：熟悉 Python 与 LangGraph，了解 MCP。")
    print("[Agent3] 单 JD 覆盖率", cov["coverage"], "命中", cov["matched"])
    ok &= cov["coverage"] >= 80  # 三项都在简历里

    # 全链路
    result = run_pipeline(RESUME, threshold=60, limit=10)
    applied = [d for d in result["decisions"] if d["decision"] == "apply"]
    skipped = [d for d in result["decisions"] if d["decision"] == "skip"]
    print(f"[Pipeline] 评估 {len(result['decisions'])}，投递 {len(applied)}，跳过 {len(skipped)}")
    ok &= len(applied) >= 2
    ok &= all(d["greeting"] for d in applied)

    # 排除词只看标题：「销售支持方向」应被拒
    sales = [d for d in result["decisions"] if "销售" in d.get("title", "")]
    if sales:
        ok &= sales[0]["decision"] == "skip" and "排除词" in sales[0]["reason"]
        print("[Exclude]", sales[0]["title"], "→", sales[0]["reason"])

    # 按分数降序
    scores = [d["score"] for d in result["decisions"]]
    ok &= scores == sorted(scores, reverse=True)

    print("\n全部通过" if ok else "\n存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
