"""Optional Qdrant-backed vector index for lifelog retrieval."""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(slots=True)
class _MemoryDoc:
    doc_id: str
    text: str
    metadata: dict[str, Any]


class QdrantLifelogIndex:
    """Qdrant vector index with automatic in-memory fallback."""

    def __init__(
        self,
        *,
        collection_name: str = "lifelog_semantic",
        url: str = "",
        api_key: str = "",
        timeout_seconds: float = 3.0,
        vector_size: int = 64,
    ) -> None:
        self.collection_name = str(collection_name or "lifelog_semantic").strip()
        self.url = str(url or "").strip()
        self.api_key = str(api_key or "").strip()
        self.timeout_seconds = max(0.2, float(timeout_seconds))
        self.vector_size = max(8, int(vector_size))

        self._client: Any | None = None
        self._qm: Any | None = None
        self._is_qdrant = False
        self._memory_mode_warned = False
        self._memory_docs: list[_MemoryDoc] = []
        self._setup_qdrant()

    def _setup_qdrant(self) -> None:
        try:
            from qdrant_client import QdrantClient  # type: ignore[import-not-found]
            from qdrant_client.http import models as qm  # type: ignore[import-not-found]
        except Exception as e:
            logger.warning(f"qdrant unavailable, lifelog index fallback to in-memory mode: {e}")
            return

        try:
            if self.url:
                client = QdrantClient(
                    url=self.url,
                    api_key=self.api_key or None,
                    timeout=self.timeout_seconds,
                )
            else:
                # Local in-memory qdrant mode for dev/test.
                client = QdrantClient(location=":memory:")
            try:
                client.get_collection(self.collection_name)
            except Exception:
                client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qm.VectorParams(
                        size=self.vector_size,
                        distance=qm.Distance.COSINE,
                    ),
                )
            self._client = client
            self._qm = qm
            self._is_qdrant = True
        except Exception as e:
            logger.warning(f"qdrant init failed, lifelog index fallback to in-memory mode: {e}")
            self._client = None
            self._qm = None
            self._is_qdrant = False

    def add_document(self, *, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        if self._is_qdrant and self._client is not None and self._qm is not None:
            try:
                vector = self._embed(text)
                payload = {"text": str(text or ""), "metadata": dict(metadata or {})}
                point = self._qm.PointStruct(id=str(doc_id), vector=vector, payload=payload)
                self._client.upsert(
                    collection_name=self.collection_name,
                    points=[point],
                    wait=False,
                )
                return
            except Exception as e:
                logger.warning(f"qdrant upsert failed, fallback to in-memory mode: {e}")
                self._is_qdrant = False
                self._client = None
                self._qm = None
        self._warn_memory_mode_once()
        self._memory_docs = [d for d in self._memory_docs if d.doc_id != str(doc_id)]
        self._memory_docs.append(
            _MemoryDoc(
                doc_id=str(doc_id),
                text=str(text or ""),
                metadata=dict(metadata or {}),
            )
        )

    def query(
        self,
        *,
        query_text: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, int(top_k))
        if self._is_qdrant and self._client is not None and self._qm is not None:
            try:
                vector = self._embed(query_text)
                query_filter = self._build_filter(where)
                points = self._query_qdrant(vector=vector, limit=limit, query_filter=query_filter)
                output: list[dict[str, Any]] = []
                for point in points:
                    payload = getattr(point, "payload", {}) or {}
                    meta = payload.get("metadata")
                    metadata = dict(meta) if isinstance(meta, dict) else {}
                    output.append(
                        {
                            "id": str(getattr(point, "id", "")),
                            "text": str(payload.get("text") or ""),
                            "metadata": metadata,
                            "score": float(getattr(point, "score", 0.0)),
                        }
                    )
                return output
            except Exception as e:
                logger.warning(f"qdrant query failed, fallback to in-memory mode: {e}")
                self._is_qdrant = False
                self._client = None
                self._qm = None

        self._warn_memory_mode_once()
        return self._memory_query(query_text=query_text, top_k=limit, where=where)

    def _query_qdrant(
        self,
        *,
        vector: list[float],
        limit: int,
        query_filter: Any | None,
    ) -> list[Any]:
        assert self._client is not None
        try:
            result = self._client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            points = getattr(result, "points", None)
            if isinstance(points, list):
                return points
        except Exception:
            pass
        result = self._client.search(
            collection_name=self.collection_name,
            query_vector=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return list(result or [])

    def _build_filter(self, where: dict[str, Any] | None) -> Any | None:
        if not where or self._qm is None:
            return None
        must = []
        for key, value in where.items():
            must.append(
                self._qm.FieldCondition(
                    key=f"metadata.{key}",
                    match=self._qm.MatchValue(value=value),
                )
            )
        if not must:
            return None
        return self._qm.Filter(must=must)

    def _memory_query(
        self,
        *,
        query_text: str,
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_query = (query_text or "").strip().lower()
        tokens = set(normalized_query.split())
        chars = {c for c in normalized_query if not c.isspace()}
        scored: list[tuple[float, _MemoryDoc]] = []
        for doc in self._memory_docs:
            if where and not all(doc.metadata.get(k) == v for k, v in where.items()):
                continue
            normalized_doc = doc.text.lower()
            doc_tokens = set(normalized_doc.split())
            token_overlap = len(tokens.intersection(doc_tokens)) if tokens else 0
            char_overlap = len(chars.intersection({c for c in normalized_doc if not c.isspace()}))
            substring_bonus = 10 if normalized_query and normalized_query in normalized_doc else 0
            score = float(substring_bonus + token_overlap + char_overlap)
            if score <= 0:
                continue
            scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        output: list[dict[str, Any]] = []
        for score, doc in scored[:top_k]:
            output.append(
                {
                    "id": doc.doc_id,
                    "text": doc.text,
                    "metadata": dict(doc.metadata),
                    "score": score,
                }
            )
        return output

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.vector_size
        normalized = str(text or "").strip().lower()
        tokens = normalized.split()
        if not tokens:
            tokens = [normalized] if normalized else ["<empty>"]
        for token in tokens:
            idx = int(zlib.adler32(token.encode("utf-8")) % self.vector_size)
            vec[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm <= 0:
            return [0.0] * self.vector_size
        return [x / norm for x in vec]

    def _warn_memory_mode_once(self) -> None:
        if self._memory_mode_warned:
            return
        self._memory_mode_warned = True
        logger.warning("lifelog semantic retrieval is running in in-memory fallback mode (non-persistent)")

    @property
    def backend_mode(self) -> str:
        return "qdrant" if self._is_qdrant and self._client is not None else "memory"
