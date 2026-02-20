from __future__ import annotations

from nanobot.storage.qdrant_lifelog import QdrantLifelogIndex


def test_qdrant_lifelog_index_add_and_query() -> None:
    index = QdrantLifelogIndex(collection_name="lifelog_test_index")
    index.add_document(
        doc_id="1",
        text="stairs ahead near the crossing",
        metadata={"session_id": "sess-a"},
    )
    index.add_document(
        doc_id="2",
        text="bus stop and traffic light",
        metadata={"session_id": "sess-b"},
    )

    hits = index.query(query_text="stairs", top_k=3)
    assert hits
    assert any(str(item.get("id")) == "1" for item in hits)
    assert index.backend_mode in {"qdrant", "memory"}


def test_qdrant_lifelog_index_supports_provider_embedding_projection() -> None:
    def _embed(text: str) -> list[float]:
        if "stairs" in text:
            return [1.0, 0.0, 0.0, 0.0, 0.0]
        if "traffic" in text:
            return [0.0, 1.0, 0.0, 0.0, 0.0]
        return [0.0, 0.0, 1.0, 0.0, 0.0]

    index = QdrantLifelogIndex(
        collection_name="lifelog_test_embed",
        vector_size=8,
        embedding_enabled=True,
        embedding_fn=_embed,
    )
    assert index.embedding_mode == "provider"
    vector = index._embed("stairs ahead")
    assert len(vector) == 8
    assert abs(sum(v * v for v in vector) - 1.0) < 1e-6


def test_qdrant_lifelog_index_falls_back_when_provider_embedding_fails() -> None:
    calls = {"count": 0}

    def _broken(_text: str) -> list[float]:
        calls["count"] += 1
        raise RuntimeError("embedding provider down")

    index = QdrantLifelogIndex(
        collection_name="lifelog_test_embed_fallback",
        vector_size=16,
        embedding_enabled=True,
        embedding_fn=_broken,
    )
    vector = index._embed("hello world")
    assert len(vector) == 16
    assert calls["count"] >= 1
    assert index.embedding_mode == "hash"
