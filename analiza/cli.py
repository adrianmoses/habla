"""CLI (spec §1): arg parsing, pipeline orchestration, exit codes.

Exit codes: 0 ok · 1 transcription failed · 2 audio unreadable ·
3 vault write failed · 4 LLM failed (note still written, feedback pending).
"""

import datetime as dt
import sys
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from analiza import audio, examiner, note, transcribe, vad
from analiza import config as config_mod
from analiza.examiner import PROMPT_VERSION

EXIT_TRANSCRIPTION_FAILED = 1
EXIT_AUDIO_UNREADABLE = 2
EXIT_VAULT_WRITE_FAILED = 3
EXIT_LLM_FAILED = 4

app = typer.Typer(
    add_completion=False,
    help=__doc__,
    epilog=(
        "Known limitations: whisper silently corrects some learner errors "
        "(error table is a lower bound); filler counts are floors; "
        "pronunciation is out of scope for v0.x; scores from different "
        "prompt_versions are not comparable."
    ),
)


@app.command()
def main(
    audio_path: Annotated[
        Path,
        typer.Argument(metavar="AUDIO", help="path to .wav/.m4a/.mp3/.ogg"),
    ],
    ejercicio: Annotated[
        str, typer.Option(help="monologo | narrar-dia")
    ] = "monologo",
    tema: Annotated[
        str | None, typer.Option(help="topic, goes into note frontmatter")
    ] = None,
    vault: Annotated[
        Path | None, typer.Option(help="vault root (default: from config)")
    ] = None,
    no_llm: Annotated[
        bool, typer.Option("--no-llm", help="metrics only, skip examiner pass")
    ] = False,
    model: Annotated[
        str | None, typer.Option(help="whisper model (default: from config)")
    ] = None,
    llm: Annotated[
        str | None, typer.Option(help="examiner model id (default: from config)")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="print note to stdout, write nothing")
    ] = False,
    lang: Annotated[str, typer.Option(help="force language")] = "es",
) -> None:
    """Analyze a recorded Spanish monólogo: deterministic fluency metrics,
    DELE B2 examiner feedback, and an Obsidian session note + stats row."""
    cfg = config_mod.load_config()
    whisper_model = model or cfg.whisper_model
    if llm is not None:
        cfg = cfg.model_copy(update={"llm_model": llm})
    vault_root = vault or cfg.vault_path
    if vault_root is None and not dry_run:
        typer.echo(
            "error: no vault configured (--vault or config.toml vault_path)", err=True
        )
        raise typer.Exit(EXIT_VAULT_WRITE_FAILED)

    # A. Preprocess
    try:
        with tempfile.TemporaryDirectory(prefix="analiza-") as tmp:
            prepared = audio.preprocess(audio_path, Path(tmp))

            if prepared.duration_s < cfg.thresholds.min_duration_s:
                typer.echo(
                    f"warning: audio is {prepared.duration_s:.0f}s (<"
                    f"{cfg.thresholds.min_duration_s:.0f}s) — metrics are "
                    "meaningless this short; aborting",
                    err=True,
                )
                raise typer.Exit(EXIT_AUDIO_UNREADABLE)
            if prepared.duration_s > cfg.thresholds.warn_duration_s:
                typer.echo(
                    f"warning: audio is {prepared.duration_s / 60:.1f} min long",
                    err=True,
                )

            # B. VAD
            segments = vad.detect_speech(prepared.wav_path)

            # C. Transcription
            try:
                transcription = transcribe.transcribe(
                    prepared.wav_path, model=whisper_model, language=lang
                )
            except transcribe.TranscriptionError as e:
                typer.echo(f"error: transcription failed: {e}", err=True)
                raise typer.Exit(EXIT_TRANSCRIPTION_FAILED) from e
    except audio.AudioUnreadableError as e:
        typer.echo(f"error: audio unreadable: {e}", err=True)
        raise typer.Exit(EXIT_AUDIO_UNREADABLE) from e

    # D. Metrics — TODO(implement): lemmatize with spaCy, match connectors,
    # call metrics.compute_metrics(). Placeholder until those land:
    metrics_dict: dict[str, float | int] = {"duration_s": prepared.duration_s}
    _ = (segments, transcription)  # consumed by the TODO above

    # E. LLM examiner
    examiner_result: examiner.ExaminerResult | None = None
    llm_failed = False
    if not no_llm:
        try:
            prompt = examiner.build_prompt(
                transcript=transcription.text,
                metrics=metrics_dict,
                tema=tema,
                ejercicio=ejercicio,
                low_conf_hints=[],  # TODO(implement): metrics.low_conf_spans
                subjunctive_connectors=[],  # TODO(implement): from matches
            )
            examiner_result = examiner.run_examiner(prompt, cfg)
        except examiner.ExaminerError as e:
            typer.echo(
                f"warning: examiner failed, feedback marked pending: {e}", err=True
            )
            llm_failed = True

    # F. Outputs
    fecha = dt.date.today()
    note_md = note.render_note(
        fecha=fecha,
        ejercicio=ejercicio,
        tema=tema,
        duration_s=prepared.duration_s,
        metrics=metrics_dict,
        examiner=examiner_result,
        prompt_version=PROMPT_VERSION,
    )
    if dry_run:
        typer.echo(note_md)
        raise typer.Exit(EXIT_LLM_FAILED if llm_failed else 0)

    assert vault_root is not None
    try:
        path = note.note_path(vault_root, fecha, ejercicio)
        note.write_note(path, note_md)
        # TODO(implement): note.append_stats_row(...) and raw artifacts
        # (whisper JSON, metrics JSON, LLM response JSON) into note.raw_dir().
        typer.echo(f"wrote {path}")
    except note.VaultWriteError as e:
        typer.echo(f"error: vault write failed: {e}", err=True)
        raise typer.Exit(EXIT_VAULT_WRITE_FAILED) from e

    if llm_failed:
        raise typer.Exit(EXIT_LLM_FAILED)


if __name__ == "__main__":
    sys.exit(app())
