"""Image dedup helpers for lifelog ingestion."""

from __future__ import annotations

import hashlib
import io


def compute_image_hash(image_bytes: bytes) -> str:
    """Compute multi-hash payload for robust near-duplicate matching.

    Preferred algorithm is perceptual `dhash` (when Pillow is available), and we
    always keep a `blake2` fallback for legacy compatibility.
    """
    hashes: list[str] = []

    dhash = _compute_dhash(image_bytes)
    if dhash:
        hashes.append(f"dhash:{dhash}")

    digest = hashlib.blake2b(image_bytes, digest_size=8).digest().hex()
    hashes.append(f"blake2:{digest}")
    return ";".join(hashes)


def hamming_distance(hash_a: str, hash_b: str) -> int:
    """Compute hamming distance using shared hash algorithm.

    Supported input formats:
    1. Multi-hash: ``dhash:<hex>;blake2:<hex>``
    2. Single prefixed hash: ``blake2:<hex>``
    3. Legacy raw hex: ``<hex>`` (treated as blake2)
    """
    left = _parse_hash_payload(hash_a)
    right = _parse_hash_payload(hash_b)

    shared = [name for name in ("dhash", "phash", "blake2") if name in left and name in right]
    if not shared:
        # No common representation, treat as distant.
        return 64

    algo = shared[0]
    return _hex_hamming_distance(left[algo], right[algo])


def is_near_duplicate(current_hash: str, candidates: list[str], *, max_distance: int = 3) -> bool:
    for candidate in candidates:
        try:
            distance = hamming_distance(current_hash, candidate)
        except Exception:
            continue
        if distance <= max(0, int(max_distance)):
            return True
    return False


def _parse_hash_payload(value: str) -> dict[str, str]:
    text = str(value or "").strip().lower()
    if not text:
        return {}

    output: dict[str, str] = {}
    segments = [seg.strip() for seg in text.split(";") if seg.strip()]
    for seg in segments:
        if ":" in seg:
            name, payload = seg.split(":", 1)
            name = name.strip()
            payload = payload.strip()
            if not name or not payload:
                continue
            if _is_hex(payload):
                output[name] = payload
            continue
        if _is_hex(seg):
            # Legacy storage format (no prefix): treat as blake2.
            output["blake2"] = seg
    return output


def _hex_hamming_distance(left: str, right: str) -> int:
    if not _is_hex(left) or not _is_hex(right):
        raise ValueError("invalid hex hash")
    return int((int(left, 16) ^ int(right, 16)).bit_count())


def _is_hex(value: str) -> bool:
    if not value:
        return False
    try:
        int(value, 16)
        return True
    except Exception:
        return False


def _compute_dhash(image_bytes: bytes) -> str:
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except Exception:
        return ""

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            gray = img.convert("L").resize((9, 8))
            pixels = list(gray.getdata())
    except Exception:
        return ""

    bits = 0
    for y in range(8):
        row = y * 9
        for x in range(8):
            left = pixels[row + x]
            right = pixels[row + x + 1]
            bits <<= 1
            if left > right:
                bits |= 1
    return f"{bits:016x}"
