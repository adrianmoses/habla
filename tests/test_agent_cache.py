"""JsonDiskCache primitive tests (no network, no DB)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.agent._cache import JsonDiskCache


def test_get_returns_none_for_missing_key(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path)
    assert cache.get("abc123") is None
    assert cache.has("abc123") is False


def test_put_then_get_round_trip(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path)
    payload = {"a": 1, "b": ["c", "d"], "nested": {"k": "v"}}
    cache.put("key1", payload)
    assert cache.has("key1") is True
    assert cache.get("key1") == payload


def test_keys_isolated(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path)
    cache.put("k1", {"v": 1})
    cache.put("k2", {"v": 2})
    assert cache.get("k1") == {"v": 1}
    assert cache.get("k2") == {"v": 2}


def test_creates_directory_if_missing(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "cache"
    JsonDiskCache(nested)
    assert nested.is_dir()


def test_key_prefix_namespaces_files(tmp_path: Path) -> None:
    learner = JsonDiskCache(tmp_path, key_prefix="learner_")
    judge = JsonDiskCache(tmp_path, key_prefix="judge_")
    learner.put("abc", {"who": "learner"})
    judge.put("abc", {"who": "judge"})
    # Same key, different namespaces — two distinct files.
    assert learner.get("abc") == {"who": "learner"}
    assert judge.get("abc") == {"who": "judge"}
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["judge_abc.json", "learner_abc.json"]


def test_rejects_path_traversal_in_key(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path)
    with pytest.raises(ValueError):
        cache.put("../escape", {"x": 1})
    with pytest.raises(ValueError):
        cache.get("a/b")


def test_files_are_human_readable_json(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path)
    cache.put("readable", {"español": "ñ"})
    raw = (tmp_path / "readable.json").read_text()
    # Pretty-printed, sorted, unicode preserved.
    assert "ñ" in raw
    assert json.loads(raw) == {"español": "ñ"}
