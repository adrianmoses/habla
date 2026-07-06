"""Pure latency-statistics helpers (spec #013).

Shared by the offline benchmark harness (`scripts/benchmark_latency.py`) and
the per-stage runtime observer. No I/O, no pipeline imports — just aggregation
over a list of millisecond samples, so it is trivially unit-testable and stays
inside the CI mypy scope.
"""

from __future__ import annotations

from dataclasses import dataclass


def percentile(samples: list[float], q: float) -> float:
    """Return the q-th percentile (q in [0, 100]) of ``samples``.

    Uses linear interpolation between the two nearest ranks — the same method
    as ``numpy.percentile``'s default — so small sample sizes degrade
    gracefully. Raises ``ValueError`` on an empty input; callers measuring live
    latency always have at least one sample.
    """
    if not samples:
        raise ValueError("percentile() requires at least one sample")
    if not 0.0 <= q <= 100.0:
        raise ValueError(f"q must be in [0, 100], got {q}")
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (q / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


@dataclass(frozen=True)
class LatencyStats:
    """Aggregated latency for one stage, in milliseconds."""

    n: int
    p50: float
    p95: float
    mean: float

    def format_row(self, label: str) -> str:
        """One aligned table row: ``label   n   p50   p95   mean``."""
        return (
            f"{label:<12} {self.n:>4} "
            f"{self.p50:>8.0f} {self.p95:>8.0f} {self.mean:>8.0f}"
        )


def summarize(samples: list[float]) -> LatencyStats:
    """Aggregate millisecond ``samples`` into a :class:`LatencyStats`.

    Raises ``ValueError`` on empty input — an empty stage means the run
    produced no measurement, which the caller should surface, not average to
    zero.
    """
    if not samples:
        raise ValueError("summarize() requires at least one sample")
    return LatencyStats(
        n=len(samples),
        p50=percentile(samples, 50),
        p95=percentile(samples, 95),
        mean=sum(samples) / len(samples),
    )


STATS_HEADER = f"{'stage':<12} {'n':>4} {'p50':>8} {'p95':>8} {'mean':>8}"
