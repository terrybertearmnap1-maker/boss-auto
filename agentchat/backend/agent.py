"""Agent 编排：检索 → 工具判断 → 组装 prompt → 流式回答。

协议（服务端 → 客户端）：
    {"type": "status", "stage": "retrieving"}
    {"type": "tool", "name": "now", "result": "2026-11-18 14:00"}
    {"type": "sources", "items": [{"title": "...", "score": 0.83}]}
    {"type": "token", "delta": "你"}
    {"type": "done", "tokens": 128, "latency_ms": 1200}
    {"type": "error", "message": "..."}
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Iterator, List

from .llm import build_llm
from .memory import build_memory
from .vector import Doc, build_store, tokenize

KNOWLEDGE = [
    Doc("1", "LangGraph 用 StateGraph 定义节点与边，通过 add_conditional_edges 实现条件路由，"
             "配合 checkpointer（如 MemorySaver）可以按 thread_id 回放状态。", "langgraph.md"),
    Doc("2", "RAG 的基本流程是：文档切块 → 向量化入库 → 查询向量化 → 相似度检索 top-k → 拼进 prompt 生成。",
        "rag.md"),
    Doc("3", "FastAPI 的 WebSocket 路由用 @app.websocket(\"/ws\") 声明，配合 async for 逐段推送消息，"
             "适合流式输出场景。", "fastapi.md"),
    Doc("4", "Redis 在会话服务里通常做两件事：存对话历史、做限流计数；用 RPUSH + LTRIM 维护定长列表，"
             "并设置 EXPIRE 防止键无限增长。", "redis.md"),
    Doc("5", "Qdrant 是向量数据库，collection 需要指定向量维度与距离度量（常用 COSINE），"
             "查询用 query_points，支持 payload 过滤。", "qdrant.md"),
    Doc("6", "Agent 的工具调用一般是：模型输出结构化的工具名+参数 → 执行 → 结果回填上下文 → 继续生成。",
        "agent.md"),
]


def tool_now(_: str) -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


TOOLS = {
    "now": (tool_now, ["现在几点", "当前时间", "今天几号"]),
}


class ChatAgent:
    def __init__(self, redis_url: str | None = None, qdrant_url: str | None = None) -> None:
        self.store, self.vector_backend = build_store(qdrant_url)
        self.memory, self.memory_backend = build_memory(redis_url)
        self.llm, self.llm_backend = build_llm()
        self.store.upsert(KNOWLEDGE)

    def health(self) -> dict:
        return {
            "vector": self.vector_backend,
            "memory": self.memory_backend,
            "llm": self.llm_backend,
            "docs": len(KNOWLEDGE),
        }

    @staticmethod
    def _rerank(query: str, hits, k: int):
        """向量召回 + 词面重合度重排。

        哈希向量只保证「同词相近」，排序常被长文档的噪声带偏；
        补一层词面重合度（query 的 token 有多少出现在文档里）能把
        「问 LangGraph 却召回到 Qdrant 文档」这类问题压回去。
        """
        q_tokens = set(tokenize(query))
        if not q_tokens:
            return hits[:k]
        ranked = []
        for h in hits:
            d_tokens = set(tokenize(h.doc.text))
            overlap = len(q_tokens & d_tokens) / len(q_tokens)
            hybrid = 0.6 * float(h.score) + 0.4 * overlap
            ranked.append((hybrid, h))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return [type(h)(doc=h.doc, score=round(s, 4)) for s, h in ranked[:k]]

    def stream(self, conv_id: str, user_text: str, top_k: int = 3) -> Iterator[dict]:
        started = time.time()
        yield {"type": "status", "stage": "retrieving"}

        raw_hits = self.store.search(user_text, top_k=max(top_k * 2, 6))
        hits = self._rerank(user_text, raw_hits, top_k)
        contexts: List[str] = [h.doc.text for h in hits if h.score > 0]
        yield {
            "type": "sources",
            "items": [
                {"title": h.doc.source, "score": round(float(h.score), 3)} for h in hits
            ],
        }

        # 简单工具路由：命中关键词就执行工具并把结果注入上下文
        for name, (fn, keywords) in TOOLS.items():
            if any(k in user_text for k in keywords):
                result = fn(user_text)
                yield {"type": "tool", "name": name, "result": result}
                contexts.insert(0, f"工具 {name} 返回：{result}")
                break

        history = self.memory.history(conv_id, limit=6)
        system = (
            "你是一个知识库问答助手。优先依据给定资料回答；资料不足时明确说明，不要编造。"
            "回答用简洁中文。"
        )
        messages = [{"role": "system", "content": system}]
        messages += [{"role": h["role"], "content": h["content"]} for h in history]
        messages.append({
            "role": "user",
            "content": f"资料：\n" + "\n---\n".join(contexts) + f"\n\n问题：{user_text}",
        })

        self.memory.append(conv_id, "user", user_text)

        answer = []
        for delta in self.llm.stream(messages, context=contexts):
            answer.append(delta)
            yield {"type": "token", "delta": delta}

        full = "".join(answer)
        self.memory.append(conv_id, "assistant", full)
        yield {
            "type": "done",
            "tokens": len(full),
            "latency_ms": int((time.time() - started) * 1000),
        }
