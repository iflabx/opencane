"""P2 multimodal lifelog pipeline skeleton."""

from nanobot.vision.dedup import compute_image_hash, hamming_distance, is_near_duplicate
from nanobot.vision.image_assets import ImageAssetStore
from nanobot.vision.indexer import VisionIndexer
from nanobot.vision.pipeline import VisionLifelogPipeline
from nanobot.vision.store import VisionLifelogStore
from nanobot.vision.timeline import LifelogTimelineService

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
