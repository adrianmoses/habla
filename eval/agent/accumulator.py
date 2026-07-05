"""In-memory profile accumulator for agent-eval sessions.

Mirrors what `LearnerProfileRepo.get` reads back from Postgres after a
session of `log_turn` writes, but lives entirely in-process so the eval
loop has no DB dependency. Calls into the same
`hable_ya.learner.aggregations.compute_snapshot` pure function the repo
uses; the equivalence test in `tests/test_agent_accumulator.py` is the
guard against silent drift.

Hybrid state:
- `deque[bool]` and `deque[FluencySignal]` (size <= window_turns) for the
  rolling-mean inputs — auto-evict the oldest entry on overflow, same
  semantics as the repo's `ORDER BY timestamp DESC LIMIT N`.
- `Counter[str]` and `dict[str, datetime]` for error categories — mirror
  the production `error_counts` table (which is already pre-aggregated),
  not the per-turn `error_observations` table.
- `dict[str, datetime]` for vocab last-seen — mirrors `vocabulary_items`.

`sessions_completed` is held at 0 because the agent-eval flow does not
chain sessions; per the spec, persona-driven "this learner has done N
sessions already" is authored into the persona, not derived. If a future
spec does multi-session continuity, the constructor takes the count.
"""

from __future__ import annotations

from collections import Counter, deque
from datetime import UTC, datetime

from eval.agent.personas.schema import Persona
from eval.agent.types import TurnRecord
from eval.fixtures.schema import FluencySignal
from hable_ya.learner.aggregations import (
    LearnerProfileSnapshot,
    compute_snapshot,
)

DEFAULT_WINDOW_TURNS = 20
DEFAULT_TOP_ERRORS = 3
DEFAULT_TOP_VOCAB = 5


class ProfileAccumulator:
    def __init__(
        self,
        persona: Persona,
        *,
        window_turns: int = DEFAULT_WINDOW_TURNS,
        top_errors: int = DEFAULT_TOP_ERRORS,
        top_vocab: int = DEFAULT_TOP_VOCAB,
        sessions_completed: int = 0,
    ) -> None:
        self._persona = persona
        self._window_turns = window_turns
        self._top_errors = top_errors
        self._top_vocab = top_vocab
        self._sessions_completed = sessions_completed

        self._l1_flags: deque[bool] = deque(maxlen=window_turns)
        self._fluency: deque[FluencySignal] = deque(maxlen=window_turns)
        self._error_counter: Counter[str] = Counter()
        self._error_last_seen: dict[str, datetime] = {}
        self._vocab_last_seen: dict[str, datetime] = {}
        self._turns_ingested = 0

    def ingest(
        self,
        record: TurnRecord,
        *,
        observed_at: datetime | None = None,
    ) -> None:
        when = observed_at or datetime.now(UTC)
        self._l1_flags.append(record.L1_used)
        self._fluency.append(record.fluency_signal)
        for category in record.error_categories:
            self._error_counter[category] += 1
            self._error_last_seen[category] = when
        for lemma in record.vocab_lemmas:
            self._vocab_last_seen[lemma] = when
        self._turns_ingested += 1

    def snapshot(self) -> LearnerProfileSnapshot:
        return compute_snapshot(
            band=self._persona.cefr_band,
            sessions_completed=self._sessions_completed,
            l1_used_flags=list(self._l1_flags),
            fluency_signals=list(self._fluency),
            error_counter=self._error_counter,
            error_last_seen=self._error_last_seen,
            vocab_last_seen=self._vocab_last_seen,
            top_errors=self._top_errors,
            top_vocab=self._top_vocab,
        )

    @property
    def turns_ingested(self) -> int:
        return self._turns_ingested
