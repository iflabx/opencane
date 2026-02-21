from __future__ import annotations

from opencane.vision.dedup import compute_image_hash, hamming_distance, is_near_duplicate


def test_compute_image_hash_includes_blake2_fallback() -> None:
    value = compute_image_hash(b"hello-image")
    assert "blake2:" in value


def test_hamming_distance_supports_legacy_raw_hex() -> None:
    raw = "0f0f0f0f0f0f0f0f"
    wrapped = f"blake2:{raw}"
    assert hamming_distance(raw, wrapped) == 0


def test_hamming_distance_prefers_shared_perceptual_hash() -> None:
    left = "dhash:0000000000000000;blake2:ffffffffffffffff"
    right = "dhash:0000000000000001;blake2:0000000000000000"
    assert hamming_distance(left, right) == 1


def test_hamming_distance_returns_large_when_no_shared_algorithm() -> None:
    assert hamming_distance("dhash:0f", "phash:0f") == 64


def test_is_near_duplicate_handles_mixed_formats() -> None:
    current = "dhash:0000000000000000;blake2:aaaaaaaaaaaaaaaa"
    candidates = ["aaaaaaaaaaaaaaaa", "blake2:bbbbbbbbbbbbbbbb"]
    assert is_near_duplicate(current, candidates, max_distance=0)
