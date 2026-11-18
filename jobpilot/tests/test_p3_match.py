"""P3 验收测试：JD 缺失、硬性条件扣分、覆盖率口径、排序。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import decide_agent, match_agent  # noqa: E402

RESUME = """
李知远 2027 届本科 示例大学 软件工程
技能：Python / LangGraph / LangChain / MCP / RAG / Qdrant / FastAPI / Redis / Docker / React
项目：求职多 Agent 编排系统、流式对话服务
期望城市：广州
"""

PROFILE = {"degree": "本科", "years": "应届", "city": "广州", "skills": ["Python", "LangGraph"]}

JD_GOOD = "岗位职责：负责 AI Agent 开发，基于 LangGraph 编排任务。任职要求：熟悉 Python 与大模型 API，了解 MCP 协议。应届生亦可。"
JD_SENIOR = "岗位职责：负责 AI Agent 开发，基于 LangGraph 编排任务。任职要求：3-5 年工作经验，熟悉 Python 与大模型 API，了解 MCP 协议。"
JD_MASTER = "岗位职责：负责大模型算法研究。任职要求：硕士及以上学历，熟悉 Python、大模型训练。"


def main() -> int:
    ok = True

    # 1) JD 缺失 → 不打分，标记待补抓
    empty = match_agent.run({"resume_text": RESUME, "profile": PROFILE, "trace": [],
                             "jobs": [{"job_id": "j0", "title": "某岗位", "jd": ""}]})
    job0 = empty["jobs"][0]
    print("[JD缺失]", job0["jd_missing"], job0["score"])
    ok &= job0["jd_missing"] is True and job0["score"] is None

    # 2) 正常 JD 打分
    good = match_agent.run({"resume_text": RESUME, "profile": PROFILE, "trace": [],
                            "jobs": [{"job_id": "j1", "title": "AI Agent 开发", "jd": JD_GOOD}]})["jobs"][0]
    print(f"[正常] {good['score']} 分（覆盖 {good['coverage']}% / 语义 {good['semantic']}）")
    ok &= good["score"] >= 60 and good["penalty"] == 0

    # 3) 3-5 年要求 → 扣分且分数低于正常
    senior = match_agent.run({"resume_text": RESUME, "profile": PROFILE, "trace": [],
                              "jobs": [{"job_id": "j2", "title": "高级 Agent 工程师", "jd": JD_SENIOR}]})["jobs"][0]
    print(f"[年限] {senior['score']} 分，扣 {senior['penalty']}（{senior['penalty_reasons']}）")
    ok &= senior["penalty"] == 15
    ok &= senior["score"] < good["score"]

    # 4) 硕士要求 → 扣分
    master = match_agent.run({"resume_text": RESUME, "profile": PROFILE, "trace": [],
                              "jobs": [{"job_id": "j3", "title": "算法工程师", "jd": JD_MASTER}]})["jobs"][0]
    print(f"[学历] {master['score']} 分，扣 {master['penalty']}（{master['penalty_reasons']}）")
    ok &= master["penalty"] == 15

    # 5) 排序：混入 4 条，分数必须降序，JD 缺失的排最后
    mixed = match_agent.run({
        "resume_text": RESUME, "profile": PROFILE, "trace": [],
        "jobs": [
            {"job_id": "a", "title": "AI Agent 开发", "jd": JD_GOOD},
            {"job_id": "b", "title": "高级 Agent 工程师", "jd": JD_SENIOR},
            {"job_id": "c", "title": "算法工程师", "jd": JD_MASTER},
            {"job_id": "d", "title": "空 JD 岗位", "jd": ""},
        ],
    })["jobs"]
    scores = [j["score"] for j in mixed if j["score"] is not None]
    print("[排序]", scores, "末位 jd_missing =", mixed[-1]["jd_missing"])
    ok &= scores == sorted(scores, reverse=True)
    ok &= mixed[-1]["jd_missing"] is True

    # 6) 决策阶段：JD 缺失的岗位必须跳过，且原因明确
    decisions = decide_agent.run({
        "profile": PROFILE, "threshold": 60, "trace": [],
        "jobs": [j for j in mixed if j["job_id"] == "d"],
    })["decisions"]
    print("[决策]", decisions[0]["decision"], decisions[0]["reason"])
    ok &= decisions[0]["decision"] == "skip" and "JD 缺失" in decisions[0]["reason"]

    print("\nP3 验收通过" if ok else "\nP3 验收失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
