"""Diff two eval output JSONs.

Usage::

    python -m eval.compare baseline.json finetuned.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from eval.scoring.turn import EvalOutput

console = Console()

# ---------------------------------------------------------------------------
# Thresholds from habla_fixture_spec.md
# ---------------------------------------------------------------------------

# (threshold_value, "above"|"below", action_label)
THRESHOLDS: dict[str, tuple[float, str, str]] = {
    "recast_present": (0.70, "below", "fine-tune"),
    "recast_explicit": (0.20, "above", "fine-tune"),
    "register_correct": (0.70, "below", "fine-tune"),
    "L1_in_response": (0.15, "above", "fine-tune"),
    "error_repeated": (0.05, "above", "fine-tune IMMEDIATELY"),
    "sentence_count_ok": (0.75, "below", "prompt engineering first"),
    "question_count_ok": (0.80, "below", "prompt engineering first"),
    "tool_fidelity": (0.80, "below", "fine-tune tool examples"),
}

# Dimensions where a higher rate is bad
_INVERTED = {"recast_explicit", "L1_in_response", "error_repeated"}


def _load_eval(path: str) -> EvalOutput:
    return EvalOutput.model_validate_json(Path(path).read_text())


def _format_rate(rate: float) -> str:
    return f"{rate:.2%}"


def _format_delta(delta: float, inverted: bool = False) -> str:
    """Format delta with color: green=improvement, red=regression."""
    # For inverted metrics, a decrease is good
    improved = delta < 0 if inverted else delta > 0
    color = "green" if improved else "red" if not improved else ""
    sign = "+" if delta > 0 else ""
    text = f"{sign}{delta:.2%}"
    return f"[{color}]{text}[/{color}]" if color else text


def _check_threshold(dimension: str, rate_b: float) -> str:
    """Return recommendation string if Run B crosses a threshold."""
    if dimension not in THRESHOLDS:
        return ""
    threshold, direction, action = THRESHOLDS[dimension]
    if direction == "above" and rate_b > threshold:
        return f"[red]{action} (> {threshold:.0%})[/red]"
    if direction == "below" and rate_b < threshold:
        return f"[red]{action} (< {threshold:.0%})[/red]"
    return "[green]ok[/green]"


def compare(a: EvalOutput, b: EvalOutput) -> None:
    """Print comparison tables for two eval runs."""
    agg_a = a.aggregates
    agg_b = b.aggregates

    # --- Header ---
    console.print()
    console.print(
        f"[bold]Run A:[/bold] {a.run_id[:8]}  ({a.timestamp[:10]})  n={len(a.results)}"
    )
    console.print(
        f"[bold]Run B:[/bold] {b.run_id[:8]}  ({b.timestamp[:10]})  n={len(b.results)}"
    )
    console.print()

    # --- Table 1: Overall + Per-Dimension ---
    table = Table(title="Per-Dimension Comparison")
    table.add_column("Dimension", style="bold")
    table.add_column("Run A", justify="right")
    table.add_column("Run B", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("Status (Run B)", justify="left")

    dim_a = agg_a.get("by_dimension", {})
    dim_b = agg_b.get("by_dimension", {})

    dimensions = [
        "recast_present",
        "recast_explicit",
        "register_correct",
        "sentence_count_ok",
        "question_count_ok",
        "L1_in_response",
        "error_repeated",
        "log_turn_called",
        "tool_args_correct",
    ]

    for dim in dimensions:
        rate_a = dim_a.get(dim, {}).get("rate", 0.0)
        rate_b = dim_b.get(dim, {}).get("rate", 0.0)
        delta = rate_b - rate_a
        inverted = dim in _INVERTED
        table.add_row(
            dim,
            _format_rate(rate_a),
            _format_rate(rate_b),
            _format_delta(delta, inverted=inverted),
            _check_threshold(dim, rate_b),
        )

    # Add composite row for tool_fidelity threshold
    overall_a = agg_a.get("overall", {})
    overall_b = agg_b.get("overall", {})

    table.add_section()
    for metric in ("pedagogical", "tool_fidelity", "composite"):
        va = overall_a.get(metric, 0.0)
        vb = overall_b.get(metric, 0.0)
        delta = vb - va
        status = _check_threshold(metric, vb) if metric == "tool_fidelity" else ""
        table.add_row(
            f"[bold]{metric}[/bold]",
            _format_rate(va),
            _format_rate(vb),
            _format_delta(delta),
            status,
        )

    console.print(table)

    # --- Table 2: Per-Band ---
    band_a = agg_a.get("by_band", {})
    band_b = agg_b.get("by_band", {})
    all_bands = sorted(set(list(band_a.keys()) + list(band_b.keys())))

    if all_bands:
        band_table = Table(title="Per-Band Composite")
        band_table.add_column("Band", style="bold")
        band_table.add_column("Run A", justify="right")
        band_table.add_column("Run B", justify="right")
        band_table.add_column("Delta", justify="right")
        band_table.add_column("n (A/B)", justify="right")

        for band in all_bands:
            va = band_a.get(band, {}).get("composite", 0.0)
            vb = band_b.get(band, {}).get("composite", 0.0)
            na = band_a.get(band, {}).get("n", 0)
            nb = band_b.get(band, {}).get("n", 0)
            delta = vb - va
            band_table.add_row(
                band,
                _format_rate(va),
                _format_rate(vb),
                _format_delta(delta),
                f"{na}/{nb}",
            )

        console.print()
        console.print(band_table)

    console.print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two eval output JSONs")
    parser.add_argument("run_a", help="Path to first eval output JSON (baseline)")
    parser.add_argument(
        "run_b", help="Path to second eval output JSON (e.g., finetuned)"
    )
    args = parser.parse_args()

    try:
        a = _load_eval(args.run_a)
        b = _load_eval(args.run_b)
    except FileNotFoundError as e:
        console.print(f"[red]File not found: {e}[/red]")
        sys.exit(1)

    compare(a, b)


if __name__ == "__main__":
    main()
