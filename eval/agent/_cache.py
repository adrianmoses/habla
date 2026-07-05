"""On-disk JSON cache primitive used by the synthetic learner and Opus judge.

Each entry is one file under `cache_dir/{key}.json`. Callers compute their
own keys (`sha256(...)` over canonical inputs + a version string) so the
cache module stays domain-agnostic. The format is human-readable on
purpose — diffing a cache miss is part of debugging persona regressions.

Also exposes two helpers shared by the learner and judge: a transcript
canonicalizer used inside cache-key formation, and the Anthropic
system-block dict that turns prompt-caching on for the judge/learner
system prompt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anthropic.types import TextBlockParam

from eval.fixtures.schema import ConversationTurn


def canonical_transcript(transcript: list[ConversationTurn]) -> str:
    """Stable JSON encoding of a transcript for cache-key hashing."""
    return json.dumps(
        [{"role": t.role, "content": t.content} for t in transcript],
        ensure_ascii=False,
    )


def cached_system_block(text: str) -> TextBlockParam:
    """Anthropic system-message block with ephemeral prompt caching turned on."""
    return {
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"},
    }


class JsonDiskCache:
    """File-per-key JSON cache. Not thread-safe — callers serialize access.

    The orchestrator uses a Semaphore-bounded asyncio.gather; concurrent
    reads/writes of *different* keys are safe (each key is its own file).
    Concurrent writes of the *same* key would race, but the orchestrator
    only writes after a Sema-serialized API call returns.
    """

    def __init__(self, cache_dir: Path, *, key_prefix: str = "") -> None:
        self._dir = cache_dir
        self._prefix = key_prefix
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Keys are expected to be hex digests already; defensively forbid
        # filesystem separators so a misuse cannot escape `cache_dir`.
        if "/" in key or ".." in key:
            raise ValueError(f"invalid cache key: {key!r}")
        name = f"{self._prefix}{key}" if self._prefix else key
        return self._dir / f"{name}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        with path.open() as f:
            value: dict[str, Any] = json.load(f)
        return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self._path(key).open("w") as f:
            json.dump(value, f, indent=2, sort_keys=True, ensure_ascii=False)

    def has(self, key: str) -> bool:
        return self._path(key).exists()
