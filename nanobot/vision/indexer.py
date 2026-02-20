"""Semantic index helpers for lifelog retrieval."""

from __future__ import annotations

from typing import Any, Protocol


class VectorIndexBackend(Protocol):
    """Minimal vector backend protocol used by lifelog indexer."""

    def add_document(self, *, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        ...

    def query(
        self,
        *,
        query_text: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        ...

    @property
    def backend_mode(self) -> str:
        ...


class VisionIndexer:
    """Indexer for multimodal lifelog contexts."""

    def __init__(self, index: VectorIndexBackend | None = None) -> None:
        if index is None:
            from nanobot.storage.chroma_lifelog import ChromaLifelogIndex

            index = ChromaLifelogIndex()
        self.index = index

    def add_context(
        self,
        *,
        image_id: int,
        title: str,
        summary: str,
        metadata: dict[str, Any],
    ) -> None:
        content = "\n".join([x for x in [title.strip(), summary.strip()] if x]).strip()
        if not content:
            return
        self.index.add_document(
            doc_id=str(image_id),
            text=content,
            metadata=metadata,
        )

    def search(
        self,
        *,
        query: str,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self.index.query(query_text=query, top_k=top_k, where=where)

    def status_snapshot(self) -> dict[str, Any]:
        mode = str(getattr(self.index, "backend_mode", "unknown"))
        snapshot = {
            "backend_mode": mode,
            "persistent": bool(mode in {"chroma", "qdrant"}),
        }
        embedding_mode = str(getattr(self.index, "embedding_mode", "")).strip()
        if embedding_mode:
            snapshot["embedding_mode"] = embedding_mode
        return snapshot
