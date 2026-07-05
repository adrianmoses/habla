"""TurnObservationSink tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from hable_ya.runtime.observations import TurnObservation, TurnObservationSink


def _obs(i: int, session_id: str = "abc") -> TurnObservation:
    return TurnObservation.now(
        session_id=session_id,
        learner_utterance=f"hola {i}",
        errors=[],
        fluency_signal="moderate",
        L1_used=False,
    )


async def test_append_writes_single_jsonl_line(tmp_path: Path) -> None:
    path = tmp_path / "turns.jsonl"
    sink = TurnObservationSink(path, ring_size=10)
    await sink.append(_obs(0))
    text = path.read_text(encoding="utf-8")
    assert text.count("\n") == 1
    record = json.loads(text.strip())
    assert record["learner_utterance"] == "hola 0"
    assert record["session_id"] == "abc"


async def test_recent_returns_last_n(tmp_path: Path) -> None:
    sink = TurnObservationSink(tmp_path / "turns.jsonl", ring_size=10)
    for i in range(5):
        await sink.append(_obs(i))
    recent = sink.recent(3)
    assert [o.learner_utterance for o in recent] == ["hola 2", "hola 3", "hola 4"]


async def test_recent_no_arg_returns_all(tmp_path: Path) -> None:
    sink = TurnObservationSink(tmp_path / "turns.jsonl", ring_size=10)
    for i in range(3):
        await sink.append(_obs(i))
    assert len(sink.recent()) == 3


async def test_ring_buffer_caps_at_ring_size(tmp_path: Path) -> None:
    sink = TurnObservationSink(tmp_path / "turns.jsonl", ring_size=2)
    for i in range(5):
        await sink.append(_obs(i))
    recent = sink.recent()
    assert len(recent) == 2
    assert [o.learner_utterance for o in recent] == ["hola 3", "hola 4"]


async def test_jsonl_retains_all_appends_not_just_ring(tmp_path: Path) -> None:
    path = tmp_path / "turns.jsonl"
    sink = TurnObservationSink(path, ring_size=2)
    for i in range(5):
        await sink.append(_obs(i))
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 5


async def test_concurrent_appends_preserve_file(tmp_path: Path) -> None:
    path = tmp_path / "turns.jsonl"
    sink = TurnObservationSink(path, ring_size=100)
    await asyncio.gather(*(sink.append(_obs(i)) for i in range(20)))
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 20
    parsed = [json.loads(line) for line in lines]
    utterances = sorted(r["learner_utterance"] for r in parsed)
    assert utterances == sorted(f"hola {i}" for i in range(20))


def test_missing_counter_starts_zero(tmp_path: Path) -> None:
    sink = TurnObservationSink(tmp_path / "turns.jsonl", ring_size=10)
    assert sink.missing == 0
