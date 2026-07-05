"""Human review of pending fixtures via a Rich TUI.

Files are always on disk in ``_pending/<category>/<id>.json``. The TUI renders
each fixture, accepts an approve/reject/edit/skip decision, and moves the file
to ``_approved/`` or ``_rejected/`` accordingly. Progress is persisted in
``_review_state.json`` so the session is resumable.

Use ``--non-interactive`` if the human has already hand-sorted files between
staging directories — this just re-validates whatever landed in ``_approved/``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from eval.fixtures.schema import parse_fixture

from .validate_fixtures import validate_one

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures"
PENDING_ROOT = FIXTURES_ROOT / "_pending"
APPROVED_ROOT = FIXTURES_ROOT / "_approved"
REJECTED_ROOT = FIXTURES_ROOT / "_rejected"
STATE_FILE = FIXTURES_ROOT / "_review_state.json"


def _iter_pending() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    if not PENDING_ROOT.exists():
        return out
    for cat_dir in sorted(PENDING_ROOT.iterdir()):
        if not cat_dir.is_dir():
            continue
        for f in sorted(cat_dir.glob("*.json")):
            if f.name.startswith("_"):
                continue
            out.append((cat_dir.name, f))
    return out


def _load_state() -> dict[str, str]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict[str, str]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _move(src: Path, dest_root: Path, category: str) -> Path:
    dest_dir = dest_root / category
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        raise FileExistsError(
            f"refusing to overwrite {dest} — seq collision indicates a bug "
            "in _count_existing or duplicate fixture IDs"
        )
    shutil.move(str(src), dest)
    return dest


def _render(
    console, fixture_path: Path, category: str, idx: int, total: int
) -> list[str]:
    from rich.panel import Panel
    from rich.syntax import Syntax

    data = json.loads(fixture_path.read_text())
    try:
        fixture = parse_fixture(data)
        validation = validate_one(fixture, category)
        warnings = validation.errors
    except Exception as exc:
        warnings = [f"schema error: {exc}"]

    body = json.dumps(data, indent=2, ensure_ascii=False)
    title = f"[{idx}/{total}] {category} / {fixture_path.stem}"
    console.print(
        Panel(Syntax(body, "json", theme="ansi_dark", word_wrap=True), title=title)
    )
    if warnings:
        console.print(
            Panel(
                "\n".join(f"• {w}" for w in warnings),
                title="validation",
                style="yellow",
            )
        )
    return warnings


def _edit(path: Path) -> None:
    editor = os.environ.get("EDITOR", "vi")
    subprocess.call([editor, str(path)])


def interactive() -> int:
    from rich.console import Console
    from rich.prompt import Prompt

    console = Console()
    items = _iter_pending()
    state = _load_state()
    pending = [(c, p) for c, p in items if state.get(str(p)) != "done"]
    total = len(items)
    if not pending:
        console.print("[green]Nothing to review[/green]")
        return 0

    console.print(f"[bold]{len(pending)} of {total} pending[/bold]")

    for i, (category, path) in enumerate(pending, start=1):
        idx = total - len(pending) + i
        _render(console, path, category, idx, total)
        choice = Prompt.ask(
            "[a]pprove / [r]eject / [e]dit / [s]kip / [q]uit",
            choices=["a", "r", "e", "s", "q"],
            default="s",
        )
        if choice == "q":
            break
        if choice == "e":
            _edit(path)
            _render(console, path, category, idx, total)
            choice = Prompt.ask(
                "[a]pprove / [r]eject / [s]kip",
                choices=["a", "r", "s"],
                default="a",
            )
        if choice == "a":
            _move(path, APPROVED_ROOT, category)
            state[str(path)] = "done"
            console.print("[green]approved[/green]")
        elif choice == "r":
            reason = Prompt.ask("rejection reason", default="")
            dest = _move(path, REJECTED_ROOT, category)
            if reason:
                dest.with_suffix(".reason.txt").write_text(reason)
            state[str(path)] = "done"
            console.print("[red]rejected[/red]")
        else:
            console.print("[dim]skipped[/dim]")
        _save_state(state)

    return 0


def non_interactive() -> int:
    from rich.console import Console

    console = Console()
    if not APPROVED_ROOT.exists():
        console.print("[yellow]_approved/ does not exist[/yellow]")
        return 0
    ok = bad = 0
    for cat_dir in sorted(APPROVED_ROOT.iterdir()):
        if not cat_dir.is_dir():
            continue
        for f in sorted(cat_dir.glob("*.json")):
            try:
                fixture = parse_fixture(json.loads(f.read_text()))
                result = validate_one(fixture, cat_dir.name)
                if result.ok:
                    ok += 1
                else:
                    bad += 1
                    console.print(
                        f"[red]FAIL[/red] {cat_dir.name}/{f.name}: {result.errors}"
                    )
            except Exception as exc:
                bad += 1
                console.print(f"[red]SCHEMA[/red] {cat_dir.name}/{f.name}: {exc}")
    console.print(f"\n[bold]{ok} ok, {bad} failing[/bold]")
    return 0 if bad == 0 else 1


def auto_approve() -> int:
    """Move validator-passing pending fixtures to _approved/; the rest to _rejected/.

    Bypasses the TUI for scale generation. Each rejected fixture gets a sibling
    ``<id>.reason.json`` with the validator errors and (if available) the
    schema/parse exception. Resumable via the same ``_review_state.json`` the
    interactive loop uses, so a crash mid-run doesn't reprocess work.
    """
    from rich.console import Console

    console = Console()
    items = _iter_pending()
    state = _load_state()
    pending = [(c, p) for c, p in items if state.get(str(p)) != "done"]
    total = len(items)
    if not pending:
        console.print("[green]Nothing to review[/green]")
        return 0

    console.print(f"[bold]auto-approving {len(pending)} of {total} pending[/bold]")
    approved = rejected = 0

    for category, path in pending:
        try:
            fixture = parse_fixture(json.loads(path.read_text()))
            result = validate_one(fixture, category)
            errors = result.errors
        except Exception as exc:
            errors = [f"schema error: {exc}"]

        if not errors:
            _move(path, APPROVED_ROOT, category)
            approved += 1
        else:
            dest = _move(path, REJECTED_ROOT, category)
            dest.with_suffix(".reason.json").write_text(
                json.dumps({"errors": errors}, indent=2, ensure_ascii=False)
            )
            rejected += 1
            console.print(f"[red]✗[/red] {category}/{path.name}: {errors[0]}")

        state[str(path)] = "done"
        _save_state(state)

    console.print(
        f"\n[bold]auto-approve done:[/bold] "
        f"[green]{approved} approved[/green], [red]{rejected} rejected[/red]"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--non-interactive", action="store_true")
    mode.add_argument(
        "--auto-approve",
        action="store_true",
        help="bypass TUI; move validator-passing pending fixtures to _approved/",
    )
    args = parser.parse_args()
    if args.auto_approve:
        return auto_approve()
    return non_interactive() if args.non_interactive else interactive()


if __name__ == "__main__":
    raise SystemExit(main())
