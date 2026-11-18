"""向量检索：Qdrant 优先，缺失时自动降级为内存实现。

关键设计：embedding 用「字符 n-gram 哈希」而不是模型。
- 好处：零依赖、可离线跑、启动即用；对中文短文本的召回够用
- 代价：语义能力弱于真 embedding，所以留了 `Embedder` 接口，换模型只改一个类
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence

DIM = 256
TOKEN_RE = re.compile(r"[\u4e00-\u9fa5]|[a-zA-Z0-9_]+")


def tokenize(text: str) -> List[str]:
    """中文按字、英文按词切分；再补 2-gram 提升短语区分度。"""
    units = TOKEN_RE.findall(text.lower())
    grams = list(units)
    for i in range(len(units) - 1):
        grams.append(units[i] + units[i + 1])
    return grams


def embed(text: str, dim: int = DIM) -> List[float]:
    """哈希到固定维度并归一化，保证内积等价于余弦相似度。"""
    vec = [0.0] * dim
    for tok in tokenize(text):
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass
class Doc:
    id: str
    text: str
    source: str = ""


@dataclass
class Hit:
    doc: Doc
    score: float


class MemoryStore:
    """兜底实现：文档少时（<1e4）完全够用，也方便测试。"""

    name = "memory"

    def __init__(self) -> None:
        self._items: List[tuple[Doc, List[float]]] = []

    def upsert(self, docs: Iterable[Doc]) -> None:
        for d in docs:
            self._items.append((d, embed(d.text)))

    def search(self, query: str, top_k: int = 3) -> List[Hit]:
        q = embed(query)
        scored = [(cosine(q, v), d) for d, v in self._items]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [Hit(doc=d, score=s) for s, d in scored[:top_k]]


class QdrantStore:
    """真 Qdrant：优先连服务端，连不上就用本地内存模式（qdrant 自带的 location=':memory:'）。"""

    name = "qdrant"

    def __init__(self, url: str | None = None, collection: str = "docs") -> None:
        from qdrant_client import QdrantClient

        self.collection = collection
        if url:
            self.client = QdrantClient(url=url, timeout=2)
            self.client.get_collections()  # 主动探活
        else:
            self.client = QdrantClient(location=":memory:")

    def upsert(self, docs: Iterable[Doc]) -> None:
        from qdrant_client.models import Distance, PointStruct, VectorParams

        docs = list(docs)
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
            )
        points = [
            PointStruct(id=i, vector=embed(d.text), payload={"text": d.text, "source": d.source})
            for i, d in enumerate(docs)
        ]
        self.client.upsert(collection_name=self.collection, points=points)

    def search(self, query: str, top_k: int = 3) -> List[Hit]:
        res = self.client.query_points(
            collection_name=self.collection, query=embed(query), limit=top_k
        ).points
        return [
            Hit(doc=Doc(id=str(p.id), text=p.payload.get("text", ""), source=p.payload.get("source", "")), score=p.score)
            for p in res
        ]


def build_store(qdrant_url: str | None = None):
    """返回 (store, backend_name)；Qdrant 不可用时静默降级。"""
    try:
        store = QdrantStore(url=qdrant_url)
        return store, store.name
    except Exception as exc:  # noqa: BLE001
        print(f"[vector] Qdrant 不可用，降级为内存实现：{exc}")
        return MemoryStore(), "memory"
