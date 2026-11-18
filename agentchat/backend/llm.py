"""LLM 适配层。

- 有 OPENAI_API_KEY / OPENAI_BASE_URL 时走 OpenAI 兼容接口，真流式
- 没有时用 MockLLM：基于检索到的上下文拼一段有依据的回答，逐字流式吐出来

为什么要有 Mock：项目要能「clone 下来就能跑」，不能因为没 key 就演示不了。
接口一致（`stream(messages) -> Iterator[str]`），换成真模型只改环境变量。
"""

from __future__ import annotations

import json
import os
import time
from typing import Iterable, Iterator, List


class MockLLM:
    name = "mock"

    def stream(self, messages: List[dict], context: List[str] | None = None) -> Iterator[str]:
        """根据上下文拼回答，模拟 token 级流式输出。"""
        question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        context = context or []

        if context:
            body = (
                f"根据知识库检索到的 {len(context)} 条内容，我的回答是：\n\n"
                + context[0].strip()
                + ("\n\n补充：" + context[1].strip()[:120] + "…" if len(context) > 1 else "")
            )
        else:
            body = (
                "我在知识库里没有检索到直接相关的内容。"
                f"关于「{question[:30]}」，建议补充该主题的文档后再提问，或者换个问法。"
            )

        for ch in body:
            yield ch
            time.sleep(0.008)  # 模拟 token 间隔，前端能看到打字机效果


class OpenAICompatLLM:
    name = "openai"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def stream(self, messages: List[dict], context: List[str] | None = None) -> Iterator[str]:
        import httpx

        payload = {"model": self.model, "messages": messages, "stream": True}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.stream("POST", f"{self.base_url}/chat/completions",
                          json=payload, headers=headers, timeout=60) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    delta = json.loads(chunk)["choices"][0]["delta"].get("content") or ""
                except Exception:  # noqa: BLE001
                    continue
                if delta:
                    yield delta


def build_llm():
    """返回 (llm, backend_name)。"""
    base = os.getenv("OPENAI_BASE_URL")
    key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if base and key:
        return OpenAICompatLLM(base, key, model), "openai"
    return MockLLM(), "mock"
