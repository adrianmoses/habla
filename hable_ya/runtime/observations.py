"""Per-session `log_turn` observation sink.

Collects validated ``log_turn`` payloads emitted by the LLM during a live
session. Persists each observation as one JSON line to a configurable path
(dev artifact; spec #026 replaces this with the durable learner DB) and keeps
a bounded ring buffer in memory for ``GET /dev/observations``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("hable_ya.runtime.observations")


@dataclass
class TurnObservation:
    session_id: str
    timestamp_iso: str
    learner_utterance: str
    errors: list[dict[str, str]]
    fluency_signal: str
    L1_used: bool
    # Spec 049: best-effort model emission. None when the model omitted
    # cefr_band or emitted an out-of-enum value; the runtime degrades
    # gracefully and the placement/leveling policies treat None as "no
    # signal from this turn" rather than erroring.
    cefr_band: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def now(
        cls,
        *,
        session_id: str,
        learner_utterance: str,
        errors: list[dict[str, str]],
        fluency_signal: str,
        L1_used: bool,
        cefr_band: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> TurnObservation:
        return cls(
            session_id=session_id,
            timestamp_iso=datetime.now(UTC).isoformat(timespec="milliseconds"),
            learner_utterance=learner_utterance,
            errors=errors,
            fluency_signal=fluency_signal,
            L1_used=L1_used,
            cefr_band=cefr_band,
            extra=extra or {},
        )


class TurnObservationSink:
    """Append-only JSONL sink + bounded in-memory ring buffer.

    Single-tenant runtime means concurrent overlapping sessions are not
    expected, but ``append`` takes a lock anyway so the JSONL file stays
    coherent if two pipelines ever end up sharing the sink.
    """

    def __init__(self, path: Path, ring_size: int = 100) -> None:
        self._path = path
        self._buffer: deque[TurnObservation] = deque(maxlen=ring_size)
        self._lock = asyncio.Lock()
        self.missing: int = 0
        # Incremented by HableYaToolHandler when the post-`log_turn` learner
        # DB write fails (spec 029). The JSONL line still appended; this
        # counter surfaces in /dev/observations as a graceful-degradation
        # signal so the researcher notices drift between sink and DB.
        self.ingest_failed: int = 0
        # Spec 049: incremented when the model omits cefr_band or emits an
        # out-of-enum value. Visible to decide whether prompt engineering
        # alone is sufficient or a fine-tune pass on the field is needed.
        self.band_missing: int = 0
        # Spec 049: incremented when end_session's placement/leveling write
        # fails (e.g. DB unavailable mid-session). Same posture as
        # ingest_failed — exception is logged, not raised.
        self.leveling_failed: int = 0

    @property
    def path(self) -> Path:
        return self._path

    async def append(self, obs: TurnObservation) -> None:
        async with self._lock:
            self._buffer.append(obs)
            line = json.dumps(asdict(obs), ensure_ascii=False)
            # Use append mode so concurrent sinks pointing at the same file
            # don't clobber each other. Newline is explicit because Path.open
            # in text mode doesn't add one.
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def recent(self, n: int | None = None) -> list[TurnObservation]:
        if n is None or n >= len(self._buffer):
            return list(self._buffer)
        return list(self._buffer)[-n:]
