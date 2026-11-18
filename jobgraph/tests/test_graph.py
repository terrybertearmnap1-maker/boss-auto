"""最小可回归测试：不依赖 pytest，直接 python tests/test_graph.py 运行。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobgraph.graph import build_graph, evaluate  # noqa: E402
from jobgraph.skills import load_profile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROFILE = load_profile(str(ROOT / "data" / "profile.json"))

GOOD_JD = """岗位职责
1. 负责 AI Agent 智能体产品开发；
2. 基于 LangGraph 编排多步任务，实现工具调用；
3. 参与 RAG 检索与知识库建设。
任职要求
1. 熟悉 Python 与大模型 API；
2. 了解 MCP 协议者优先。"""

WEAK_JD = """岗位职责
1. 协助整理业务指标；
2. 编写 SQL 提取数据。
任职要求
1. 熟练使用 SQL；
2. 数学、统计相关专业。"""

BANNED_JD = """岗位职责
1. 负责 Java 后端服务开发。
任职要求
1. 熟悉 Spring Boot。"""


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}{(' — ' + detail) if detail and not cond else ''}")
    return cond


def main():
    ok = True

    # 1. 高匹配岗位应当通过并生成话术
    res = evaluate({"title": "AI Agent 开发工程师", "jd_text": GOOD_JD}, PROFILE, 60)
    ok &= check("高匹配通过阈值", res["score"] >= 60, f"score={res['score']}")
    ok &= check("决策为 apply", res["decision"] == "apply", res["reason"])
    ok &= check("生成了打招呼语", len(res.get("greeting", "")) > 20)

    # 2. 低匹配岗位应当被拒
    weak = evaluate({"title": "数据分析实习生", "jd_text": WEAK_JD}, PROFILE, 60)
    ok &= check("低匹配被拒", weak["decision"] == "skip", weak["reason"])

    # 3. 标题命中排除词 → 0 分
    banned = evaluate({"title": "Java 后端开发工程师", "jd_text": BANNED_JD}, PROFILE, 60)
    ok &= check("排除词生效", banned["score"] == 0 and banned["decision"] == "skip")

    # 4. 正文里出现「后端」不应误伤（排除词只看标题）
    tricky = evaluate(
        {"title": "AI Agent 开发工程师", "jd_text": "负责 AI Agent 开发，包含后端服务与前端页面。"},
        PROFILE, 60,
    )
    ok &= check("正文含排除词不误伤", tricky.get("banned") in (None, ""), f"banned={tricky.get('banned')}")

    # 5. 轨迹完整：每个节点都留下记录
    ok &= check("轨迹不少于 4 条", len(res.get("trace", [])) >= 4, str(res.get("trace")))

    # 6. 断点/回放：同一 thread 可读回最终状态
    app = build_graph(threshold=60)
    cfg = {"configurable": {"thread_id": "replay-demo"}}
    init = {
        "title": "AI Agent 开发工程师", "company": "迈络科技", "salary": "12-20K",
        "jd_text": GOOD_JD, "threshold": 60, "profile": PROFILE, "trace": [],
    }
    app.invoke(init, config=cfg)
    snapshot = app.get_state(cfg)
    ok &= check("checkpoint 可回放", bool(snapshot.values.get("score")),
                str(snapshot.values.get("score")))

    print("\n全部通过" if ok else "\n存在失败用例")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
