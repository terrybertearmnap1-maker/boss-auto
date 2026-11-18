"""MCP 客户端示例：以 stdio 启动 jobpilot 的 MCP Server，列出工具并调用一次。

不需要任何模型密钥——MCP 只是「客户端 ⇄ 服务端」的工具协议，
这里我们自己充当客户端，把评估结果打印出来。

用法：
    python scripts/mcp_client_demo.py
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent

JD = (
    "岗位职责：负责 AI Agent 智能体产品开发，基于 LangGraph 编排多步任务，"
    "参与 RAG 检索与知识库建设。任职要求：熟悉 Python 与大模型 API，"
    "了解 MCP 协议与 Qdrant 向量数据库，有 FastAPI 服务开发经验。"
)


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pipeline.mcp_server"],
        cwd=str(ROOT),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("发现工具:", [t.name for t in tools.tools])

            result = await session.call_tool(
                "evaluate_jd",
                {"jd_text": JD, "title": "AI Agent 开发工程师", "company": "迈络科技"},
            )
            payload = json.loads(result.content[0].text)
            print("\n评估结果:")
            print(json.dumps(payload, ensure_ascii=False, indent=2)[:600])

            stats = await session.call_tool("get_stats", {})
            print("\n统计:", stats.content[0].text)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
