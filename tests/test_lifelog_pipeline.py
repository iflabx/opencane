import base64
import sqlite3
from pathlib import Path

import pytest

from nanobot.storage.chroma_lifelog import ChromaLifelogIndex
from nanobot.vision.image_assets import ImageAssetStore
from nanobot.vision.indexer import VisionIndexer
from nanobot.vision.pipeline import VisionLifelogPipeline
from nanobot.vision.store import VisionLifelogStore
from nanobot.vision.timeline import LifelogTimelineService


class _DummyVisionAnalyzer:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, *, question: str, image: bytes, mime: str):  # type: ignore[no-untyped-def]
        del image, mime
        self.calls += 1
        return {"success": True, "result": f"scene summary: {question or 'default'}"}


class _StructuredVisionAnalyzer:
    async def analyze(self, *, question: str, image: bytes, mime: str):  # type: ignore[no-untyped-def]
        del question, image, mime
        return {
            "summary": "前方有台阶，需要注意。",
            "objects": [{"label": "台阶", "confidence": 0.91}],
            "ocr": [{"text": "出口", "confidence": 0.88}],
            "risk_hints": ["台阶较陡"],
            "actionable_summary": "请减速并先探测台阶高度。",
            "risk_level": "P1",
            "risk_score": 0.72,
            "confidence": 0.9,
        }


@pytest.mark.asyncio
async def test_lifelog_pipeline_ingest_and_search(tmp_path: Path) -> None:
    db_path = tmp_path / "lifelog.db"
    store = VisionLifelogStore(db_path)
    indexer = VisionIndexer(ChromaLifelogIndex())
    analyzer = _DummyVisionAnalyzer()
    asset_store = ImageAssetStore(tmp_path / "images", max_files=100, cleanup_interval=1)
    pipeline = VisionLifelogPipeline(
        store=store,
        indexer=indexer,
        analyzer=analyzer,
        asset_store=asset_store,
    )

    payload = base64.b64encode(b"demo-image-bytes").decode("ascii")
    result = await pipeline.ingest_image(
        session_id="sess-p2",
        image_base64=payload,
        question="前方有什么障碍物",
    )

    assert result["success"] is True
    assert result["dedup"] is False
    assert str(result["image_uri"]).startswith("asset://")
    asset_path = asset_store.resolve_uri(str(result["image_uri"]))
    assert asset_path is not None
    assert asset_path.exists()
    assert analyzer.calls == 1

    timeline = LifelogTimelineService(store).list_timeline(session_id="sess-p2")
    assert len(timeline) == 1
    assert timeline[0]["event_type"] == "image_ingested"

    hits = indexer.search(query="障碍物", top_k=3, where={"session_id": "sess-p2"})
    assert hits
    assert hits[0]["metadata"]["session_id"] == "sess-p2"

    store.close()


@pytest.mark.asyncio
async def test_lifelog_pipeline_persists_structured_context(tmp_path: Path) -> None:
    db_path = tmp_path / "lifelog.db"
    store = VisionLifelogStore(db_path)
    indexer = VisionIndexer(ChromaLifelogIndex())
    pipeline = VisionLifelogPipeline(store=store, indexer=indexer, analyzer=_StructuredVisionAnalyzer())

    payload = base64.b64encode(b"structured-image").decode("ascii")
    result = await pipeline.ingest_image(session_id="sess-structured", image_base64=payload)

    assert result["success"] is True
    assert result["structured_context"]["risk_level"] == "P1"
    assert result["structured_context"]["objects"][0]["label"] == "台阶"
    assert result["structured_context"]["actionable_summary"].startswith("请减速")

    context = store.get_context_by_image_id(image_id=int(result["image_id"]))
    assert context is not None
    assert context["risk_level"] == "P1"
    assert context["objects"][0]["label"] == "台阶"
    assert context["ocr"][0]["text"] == "出口"
    assert context["risk_hints"] == ["台阶较陡"]
    assert str(context["actionable_summary"]).startswith("请减速")

    timeline = LifelogTimelineService(store).list_timeline(session_id="sess-structured")
    assert timeline[0]["payload"]["structured_context"]["objects"][0]["label"] == "台阶"
    assert timeline[0]["payload"]["structured_context"]["risk_hints"] == ["台阶较陡"]

    store.close()


@pytest.mark.asyncio
async def test_lifelog_pipeline_dedup_skips_extra_analysis(tmp_path: Path) -> None:
    db_path = tmp_path / "lifelog.db"
    store = VisionLifelogStore(db_path)
    indexer = VisionIndexer(ChromaLifelogIndex())
    analyzer = _DummyVisionAnalyzer()
    pipeline = VisionLifelogPipeline(store=store, indexer=indexer, analyzer=analyzer)

    payload = base64.b64encode(b"same-image").decode("ascii")
    first = await pipeline.ingest_image(session_id="sess-dup", image_base64=payload, question="first")
    second = await pipeline.ingest_image(session_id="sess-dup", image_base64=payload, question="second")

    assert first["dedup"] is False
    assert second["dedup"] is True
    assert analyzer.calls == 1

    timeline = LifelogTimelineService(store).list_timeline(session_id="sess-dup")
    assert len(timeline) == 2

    store.close()


@pytest.mark.asyncio
async def test_lifelog_pipeline_asset_cleanup_marks_deleted_uri_in_db(tmp_path: Path) -> None:
    db_path = tmp_path / "lifelog.db"
    store = VisionLifelogStore(db_path)
    indexer = VisionIndexer(ChromaLifelogIndex())
    analyzer = _DummyVisionAnalyzer()
    asset_store = ImageAssetStore(tmp_path / "images", max_files=1, cleanup_interval=1)
    pipeline = VisionLifelogPipeline(
        store=store,
        indexer=indexer,
        analyzer=analyzer,
        asset_store=asset_store,
    )

    payload1 = base64.b64encode(b"image-one").decode("ascii")
    payload2 = base64.b64encode(b"image-two").decode("ascii")
    await pipeline.ingest_image(session_id="sess-gc", image_base64=payload1, question="first", ts=1000)
    await pipeline.ingest_image(session_id="sess-gc", image_base64=payload2, question="second", ts=2000)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT image_uri FROM lifelog_images ORDER BY id ASC")
    uris = [str(row[0]) for row in cur.fetchall()]
    conn.close()
    assert len(uris) == 2
    deleted = [uri for uri in uris if uri.startswith("deleted:asset://")]
    active = [uri for uri in uris if uri.startswith("asset://")]
    assert len(deleted) == 1
    assert len(active) == 1

    store.close()
