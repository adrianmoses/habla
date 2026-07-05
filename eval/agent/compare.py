"""Diff two agent-eval JSONs.

Mirrors the shape of `eval.compare` for the session-level metrics.
Each dimension is a 1-5 score, so deltas are absolute (not rate
percentages). Threshold values are placeholders (TODO: recalibrate from
the first full baseline run); ``compare`` prints the recommendation
column from day one but the numbers are explicitly provisional.

Usage::

    python -m eval.agent.compare baseline_agent.json tuned_agent.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from eval.agent.run_agent_eval import DIMENSION_KEYS
from eval.agent.types import AgentEvalOutput

console = Console()

# (threshold_value, direction, action_label)
# TODO: recalibrate from the first baseline run's distribution; ship at 3.5
# placeholders so the recommendation column is functional from day one.
THRESHOLDS: dict[str, tuple[float, str, str]] = {
    "pedagogical_flow": (3.5, "below", "investigate"),
    "level_consistency": (3.5, "below", "investigate"),
    "recast_naturalness": (3.5, "below", "fine-tune recasts"),
    "learner_production_space": (3.5, "below", "investigate"),
    "coherence": (3.5, "below", "investigate"),
    "overall": (3.5, "below", "investigate"),
}


def _load(path: str) -> AgentEvalOutput:
    return AgentEvalOutput.model_validate_json(Path(path).read_text())


def _format_score(score: float) -> str:
    return f"{score:.2f}"


def _format_delta(delta: float) -> str:
    color = "green" if delta > 0 else "red" if delta < 0 else ""
    sign = "+" if delta > 0 else ""
    text = f"{sign}{delta:.2f}"
    return f"[{color}]{text}[/{color}]" if color else text


def _check_threshold(metric: str, score_b: float) -> str:
    if metric not in THRESHOLDS:
        return ""
    threshold, direction, action = THRESHOLDS[metric]
    if direction == "below" and score_b < threshold:
        return f"[red]{action} (< {threshold})[/red]"
    if direction == "above" and score_b > threshold:
        return f"[red]{action} (> {threshold})[/red]"
    return "[green]ok[/green]"


def compare(a: AgentEvalOutput, b: AgentEvalOutput) -> None:
    agg_a = a.aggregates
    agg_b = b.aggregates

    console.print()
    console.print(
        f"[bold]Run A:[/bold] {a.run_id[:8]}  ({a.timestamp[:10]})  "
        f"n={a.session_count}  model={a.model_label}"
    )
    console.print(
        f"[bold]Run B:[/bold] {b.run_id[:8]}  ({b.timestamp[:10]})  "
        f"n={b.session_count}  model={b.model_label}"
    )
    console.print()

    # --- Per-dimension ---
    dim_table = Table(title="Per-Dimension Comparison (TODO: recalibrate thresholds)")
    dim_table.add_column("Dimension", style="bold")
    dim_table.add_column("Run A", justify="right")
    dim_table.add_column("Run B", justify="right")
    dim_table.add_column("Delta", justify="right")
    dim_table.add_column("Status (Run B)", justify="left")

    dim_a = agg_a.get("by_dimension", {})
    dim_b = agg_b.get("by_dimension", {})
    for dim in DIMENSION_KEYS:
        ma = dim_a.get(dim, {}).get("mean", 0.0)
        mb = dim_b.get(dim, {}).get("mean", 0.0)
        dim_table.add_row(
            dim,
            _format_score(ma),
            _format_score(mb),
            _format_delta(mb - ma),
            _check_threshold(dim, mb),
        )

    overall_a = agg_a.get("overall", {}).get("mean", 0.0)
    overall_b = agg_b.get("overall", {}).get("mean", 0.0)
    dim_table.add_section()
    dim_table.add_row(
        "[bold]overall[/bold]",
        _format_score(overall_a),
        _format_score(overall_b),
        _format_delta(overall_b - overall_a),
        _check_threshold("overall", overall_b),
    )
    console.print(dim_table)

    # --- Per-band ---
    band_a = agg_a.get("by_band", {})
    band_b = agg_b.get("by_band", {})
    all_bands = sorted(set(band_a.keys()) | set(band_b.keys()))
    if all_bands:
        band_table = Table(title="Per-Band Overall")
        band_table.add_column("Band", style="bold")
        band_table.add_column("Run A", justify="right")
        band_table.add_column("Run B", justify="right")
        band_table.add_column("Delta", justify="right")
        band_table.add_column("n (A/B)", justify="right")
        for band in all_bands:
            ma = band_a.get(band, {}).get("overall_mean", 0.0)
            mb = band_b.get(band, {}).get("overall_mean", 0.0)
            na = band_a.get(band, {}).get("n", 0)
            nb = band_b.get(band, {}).get("n", 0)
            band_table.add_row(
                band,
                _format_score(ma),
                _format_score(mb),
                _format_delta(mb - ma),
                f"{na}/{nb}",
            )
        console.print()
        console.print(band_table)

    # --- Per-error-pattern ---
    ep_a = agg_a.get("by_error_pattern", {})
    ep_b = agg_b.get("by_error_pattern", {})
    all_patterns = sorted(set(ep_a.keys()) | set(ep_b.keys()))
    if all_patterns:
        ep_table = Table(title="Per-Error-Pattern Overall")
        ep_table.add_column("Error Pattern", style="bold")
        ep_table.add_column("Run A", justify="right")
        ep_table.add_column("Run B", justify="right")
        ep_table.add_column("Delta", justify="right")
        ep_table.add_column("n (A/B)", justify="right")
        for pattern in all_patterns:
            ma = ep_a.get(pattern, {}).get("overall_mean", 0.0)
            mb = ep_b.get(pattern, {}).get("overall_mean", 0.0)
            na = ep_a.get(pattern, {}).get("n", 0)
            nb = ep_b.get(pattern, {}).get("n", 0)
            ep_table.add_row(
                pattern,
                _format_score(ma),
                _format_score(mb),
                _format_delta(mb - ma),
                f"{na}/{nb}",
            )
        console.print()
        console.print(ep_table)

    # --- Stop reasons ---
    sr_a = agg_a.get("stop_reasons", {})
    sr_b = agg_b.get("stop_reasons", {})
    all_reasons = sorted(set(sr_a.keys()) | set(sr_b.keys()))
    if all_reasons:
        sr_table = Table(title="Stop Reasons")
        sr_table.add_column("Reason", style="bold")
        sr_table.add_column("Run A", justify="right")
        sr_table.add_column("Run B", justify="right")
        for reason in all_reasons:
            sr_table.add_row(
                reason,
                str(sr_a.get(reason, 0)),
                str(sr_b.get(reason, 0)),
            )
        console.print()
        console.print(sr_table)

    console.print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two agent-eval output JSONs"
    )
    parser.add_argument("run_a", help="Baseline agent-eval JSON")
    parser.add_argument("run_b", help="Candidate agent-eval JSON")
    args = parser.parse_args()
    try:
        a = _load(args.run_a)
        b = _load(args.run_b)
    except FileNotFoundError as e:
        console.print(f"[red]File not found: {e}[/red]")
        sys.exit(1)
    compare(a, b)


if __name__ == "__main__":
    main()
