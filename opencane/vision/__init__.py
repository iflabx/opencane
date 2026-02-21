"""P2 multimodal lifelog pipeline skeleton."""

from opencane.vision.dedup import compute_image_hash, hamming_distance, is_near_duplicate
from opencane.vision.image_assets import ImageAssetStore
from opencane.vision.indexer import VisionIndexer
from opencane.vision.pipeline import VisionLifelogPipeline
from opencane.vision.store import VisionLifelogStore
from opencane.vision.timeline import LifelogTimelineService

__all__ = [
    "compute_image_hash",
    "hamming_distance",
    "is_near_duplicate",
    "ImageAssetStore",
    "VisionIndexer",
    "VisionLifelogPipeline",
    "VisionLifelogStore",
    "LifelogTimelineService",
]
