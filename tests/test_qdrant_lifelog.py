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
