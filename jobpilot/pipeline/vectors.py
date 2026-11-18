"""向量层：Qdrant 做「相似 JD 去重」。

同一家公司的同一个岗位常被反复发布、或换标题重发，
用 JD 正文的向量相似度可以在打分之前就拦掉，省一次模型调用。
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import List, Sequence, Tuple

DIM = 256
TOKEN_RE = re.compile(r"[\u4e00-\u9fa5]|[a-zA-Z0-9_]+")


def tokenize(text: str) -> List[str]:
    units = TOKEN_RE.findall((text or "").lower())
    grams = list(units)
    for i in range(len(units) - 1):
        grams.append(units[i] + units[i + 1])
    return grams


def embed(text: str) -> List[float]:
    vec = [0.0] * DIM
    for tok in tokenize(text):
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
        vec[h % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class MemoryVectors:
    backend = "memory"

    def __init__(self) -> None:
        self._items: List[Tuple[str, List[float]]] = []

    def add(self, job_id: str, jd: str) -> None:
        self._items.append((job_id, embed(jd)))

    def nearest(self, jd: str) -> Tuple[str, float]:
        q = embed(jd)
        best, score = "", 0.0
        for job_id, vec in self._items:
            s = cosine(q, vec)
            if s > score:
                best, score = job_id, s
        return best, score


class QdrantVectors:
    backend = "qdrant"

    def __init__(self, url: str = "", collection: str = "jd") -> None:
        from qdrant_client import QdrantClient

        self.client = QdrantClient(url=url, timeout=2) if url else QdrantClient(location=":memory:")
        if url:
            self.client.get_collections()
        self.collection = collection
        self._ensure()

    def _ensure(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
            )

    def add(self, job_id: str, jd: str) -> None:
        from qdrant_client.models import PointStruct

        point_id = int(hashlib.md5(job_id.encode()).hexdigest()[:12], 16)
        self.client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=point_id, vector=embed(jd), payload={"job_id": job_id})],
        )

    def nearest(self, jd: str) -> Tuple[str, float]:
        res = self.client.query_points(collection_name=self.collection, query=embed(jd), limit=1).points
        if not res:
            return "", 0.0
        return res[0].payload.get("job_id", ""), float(res[0].score)


def build_vectors(url: str):
    if not url:
        # 无服务端时用 qdrant 本地内存模式，仍然是真 Qdrant 的代码路径
        try:
            return QdrantVectors("")
        except Exception as exc:  # noqa: BLE001
            print(f"[vectors] Qdrant 不可用（{exc}），降级内存")
            return MemoryVectors()
    try:
        return QdrantVectors(url)
    except Exception as exc:  # noqa: BLE001
        print(f"[vectors] Qdrant 服务端不可用（{exc}），改用本地内存模式")
        try:
            return QdrantVectors("")
        except Exception:  # noqa: BLE001
            return MemoryVectors()
