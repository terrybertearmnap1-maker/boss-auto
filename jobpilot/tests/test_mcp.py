"""验证 MCP Server 暴露的工具可以被正常调用。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.mcp_server import evaluate_jd, get_stats, list_jobs  # noqa: E402

JD = "负责 AI Agent 智能体开发，基于 LangGraph 编排任务，熟悉 Python 与大模型 API，了解 MCP 协议。"

res = json.loads(evaluate_jd(JD, title="AI Agent 开发工程师", company="迈络科技"))
print("[evaluate_jd]", {k: res[k] for k in ("score", "decision", "reason")})
print("[matched]", res["matched"])

jobs = json.loads(list_jobs(limit=3, decision="apply"))
print("[list_jobs apply]", [j["title"] for j in jobs])

stats = json.loads(get_stats())
print("[stats]", stats)

assert res["score"] >= 0 and res["decision"] in ("apply", "skip")
assert isinstance(jobs, list)
assert "total" in stats
print("MCP 工具调用正常")
