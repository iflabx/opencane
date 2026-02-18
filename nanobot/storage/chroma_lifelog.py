"""Vector index wrapper for lifelog semantic retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(slots=True)
class _MemoryDoc:
    doc_id: str
    text: str
    metadata: dict[str, Any]


class ChromaLifelogIndex:
    """Chroma-backed index with an in-memory fallback when chromadb is unavailable."""

    def __init__(
        self,
        *,
        collection_name: str = "lifelog_semantic",
        persist_dir: str | None = None,
    ) -> None:
        self.collection_name = collection_name
        self.persist_dir = persist_dir
        self._collection: Any | None = None
        self._memory_docs: list[_MemoryDoc] = []
        self._is_chroma = False
        self._memory_mode_warned = False
        self._setup_chroma()

    def _setup_chroma(self) -> None:
        try:
            import chromadb  # type: ignore[import-not-found]
        except Exception as e:
            logger.warning(f"chromadb unavailable, lifelog index fallback to in-memory mode: {e}")
            self._is_chroma = False
            return

        kwargs: dict[str, Any] = {}
        if self.persist_dir:
            kwargs["path"] = self.persist_dir
            client = chromadb.PersistentClient(**kwargs)
        else:
            client = chromadb.Client()
        self._collection = client.get_or_create_collection(name=self.collection_name)
        self._is_chroma = True

    def add_document(self, *, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        if self._is_chroma and self._collection is not None:
            self._collection.upsert(ids=[doc_id], documents=[text], metadatas=[metadata])
            return
        self._warn_memory_mode_once()
        self._memory_docs = [d for d in self._memory_docs if d.doc_id != doc_id]
        self._memory_docs.append(_MemoryDoc(doc_id=doc_id, text=text, metadata=dict(metadata)))

    def query(
        self,
        *,
        query_text: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self._is_chroma and self._collection is not None:
            kwargs: dict[str, Any] = {}
            if where:
                kwargs["where"] = where
            result = self._collection.query(query_texts=[query_text], n_results=max(1, top_k), **kwargs)
            ids = result.get("ids", [[]])[0]
            docs = result.get("documents", [[]])[0]
            metas = result.get("metadatas", [[]])[0]
            scores = result.get("distances", [[]])[0]
            output: list[dict[str, Any]] = []
            for i, doc_id in enumerate(ids):
                output.append(
                    {
                        "id": doc_id,
                        "text": docs[i] if i < len(docs) else "",
                        "metadata": metas[i] if i < len(metas) else {},
                        "score": float(scores[i]) if i < len(scores) else 0.0,
                    }
                )
            return output

        self._warn_memory_mode_once()
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
        output = []
        for score, doc in scored[: max(1, top_k)]:
            output.append(
                {
                    "id": doc.doc_id,
                    "text": doc.text,
                    "metadata": dict(doc.metadata),
                    "score": score,
                }
            )
        return output

    def _warn_memory_mode_once(self) -> None:
        if self._memory_mode_warned:
            return
        self._memory_mode_warned = True
        logger.warning("lifelog semantic retrieval is running in in-memory fallback mode (non-persistent)")

    @property
    def backend_mode(self) -> str:
        return "chroma" if self._is_chroma and self._collection is not None else "memory"
