"""CLI (spec §1): arg parsing, pipeline orchestration, exit codes.

Exit codes: 0 ok · 1 transcription failed · 2 audio unreadable ·
3 output write failed · 4 LLM failed (note still written, feedback pending).
"""

import datetime as dt
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from analiza import (
    audio,
    backfill,
    connectors,
    examiner,
    metrics,
    note,
    transcribe,
    vad,
)
from analiza import config as config_mod
from analiza.conectores_b2 import CONECTORES
from analiza.examiner import PROMPT_VERSION

EXIT_TRANSCRIPTION_FAILED = 1
EXIT_AUDIO_UNREADABLE = 2
EXIT_OUTPUT_WRITE_FAILED = 3
EXIT_LLM_FAILED = 4

def _lemmatize(text: str) -> list[str]:
    """spaCy es_core_news_sm lemmas of alphabetic tokens; degrades to empty
    (with a warning) when the model isn't installed — TTR/MTLD read 0 then."""
    import spacy

    try:
        nlp = spacy.load("es_core_news_sm")
    except OSError:
        typer.echo(
            "warning: spaCy model es_core_news_sm not installed "
            "(python -m spacy download es_core_news_sm); ttr/mtld will be 0",
            err=True,
        )
        return []
    return [t.lemma_.lower() for t in nlp(text) if t.is_alpha]


def _resolve_base(
    vault: Path | None, out: Path | None, cfg: config_mod.Config
) -> Path:
    """Where the three artifacts go.

    Precedence: --vault > config vault_path > --out > config output_dir >
    note.DEFAULT_OUTPUT_DIR. A vault (from either source) also selects the
    nested Español/ layout. There is always a destination, so no run fails
    for lack of one — the vault is optional, not required.
    """
    vault_root = vault or cfg.vault_path
    return note.output_base(
        vault_root or out or cfg.output_dir or note.DEFAULT_OUTPUT_DIR,
        vault_layout=vault_root is not None,
    )


def _stats_row(
    fecha: dt.date,
    ejercicio: str,
    tema: str | None,
    metrics_dict: dict[str, float | int],
    examiner_result: "examiner.ExaminerResult | None",
    whisper_model: str,
) -> dict[str, object]:
    """One append-only CSV row (note.STATS_COLUMNS order). LLM columns are
    empty strings when the examiner pass was skipped or failed."""
    return {
        "date": fecha.isoformat(),
        "ejercicio": ejercicio,
        "tema": tema or "",
        "duration_s": metrics_dict["duration_s"],
        "wpm_gross": metrics_dict["wpm_gross"],
        "wpm_articulation": metrics_dict["wpm_articulation"],
        "pauses_n": metrics_dict["pauses_n"],
        "pause_max_s": metrics_dict["pause_max_s"],
        "fillers_per_min": metrics_dict["fillers_per_min"],
        "connectors_unique": metrics_dict["connectors_unique_n"],
        "formal_ratio": metrics_dict["connectors_formal_ratio"],
        "mtld": metrics_dict["mtld"],
        "errors_n": (
            len(examiner_result.errores) if examiner_result is not None else ""
        ),
        "calcos_n": (
            len(examiner_result.calcos) if examiner_result is not None else ""
        ),
        "score_total": (
            sum(p.puntuacion for p in examiner_result.puntuaciones)
            if examiner_result is not None
            else ""
        ),
        "whisper_model": whisper_model,
        "prompt_version": PROMPT_VERSION,
    }


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


@app.command("sesion")
def sesion(
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
        Path | None,
        typer.Option(help="Obsidian vault root; writes under {vault}/Español/"),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(help=f"plain output dir (default: ./{note.DEFAULT_OUTPUT_DIR})"),
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
    DELE B2 examiner feedback, and a session note + stats row.

    Writes to ./analiza-out by default; --out redirects it, and --vault uses
    the Obsidian vault layout instead."""
    cfg = config_mod.load_config()
    whisper_model = model or cfg.whisper_model
    if llm is not None:
        cfg = cfg.model_copy(update={"llm_model": llm})
    base = _resolve_base(vault, out, cfg)

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

    # D. Metrics
    lemmas = _lemmatize(transcription.text)
    matches = connectors.match_connectors(transcription.text, CONECTORES)
    metrics_dict = metrics.compute_metrics(
        duration_s=prepared.duration_s,
        segments=segments,
        words=transcription.words,
        lemmas=lemmas,
        connector_matches=matches,
        thresholds=cfg.thresholds,
    )

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
                low_conf_hints=metrics.low_conf_spans(
                    transcription.words, cfg.thresholds.low_conf_prob
                ),
                subjunctive_connectors=sorted(
                    {m.conector.forma for m in matches if m.conector.subjuntivo}
                ),
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

    try:
        path = note.note_path(base, fecha, ejercicio)
        note.write_note(path, note_md)
        note.append_stats_row(
            base,
            _stats_row(
                fecha, ejercicio, tema, metrics_dict, examiner_result, whisper_model
            ),
        )
        raw = note.raw_dir(base, fecha, ejercicio)
        transcribe.persist_raw(transcription, raw / "whisper.json")
        (raw / "metrics.json").write_text(
            json.dumps(metrics_dict, ensure_ascii=False, indent=2)
        )
        if examiner_result is not None:
            (raw / "examiner.json").write_text(
                examiner_result.model_dump_json(indent=2)
            )
        if cfg.copy_source_audio:
            shutil.copy2(audio_path, raw / audio_path.name)
        typer.echo(f"wrote {path}")
    except (note.OutputWriteError, OSError) as e:
        typer.echo(f"error: output write failed: {e}", err=True)
        raise typer.Exit(EXIT_OUTPUT_WRITE_FAILED) from e

    if llm_failed:
        raise typer.Exit(EXIT_LLM_FAILED)


@app.command("backfill-patrones")
def backfill_patrones(
    vault: Annotated[
        Path | None,
        typer.Option(help="Obsidian vault root; reads under {vault}/Español/"),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(help=f"plain output dir (default: ./{note.DEFAULT_OUTPUT_DIR})"),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="report assignments, write nothing")
    ] = False,
) -> None:
    """Assign pattern_id to stored sessions examined before the vocabulary.

    Reads persisted examiner.json artifacts and classifies each error row
    against patrones_b2 — no audio, no re-transcription. Idempotent: sessions
    that already carry pattern_id are skipped."""
    cfg = config_mod.load_config()
    base = _resolve_base(vault, out, cfg)

    outcomes = backfill.backfill_all(
        base, cfg, dry_run=dry_run, today=dt.date.today()
    )
    if not outcomes:
        typer.echo(f"no stored sessions under {base / 'analiza-raw'}")
        return

    for o in outcomes:
        sesion_name = o.path.parent.name
        detail = f" — {o.detail}" if o.detail else ""
        count = f" ({o.assigned} patrones)" if o.assigned else ""
        typer.echo(f"{o.status:8} {sesion_name}{count}{detail}")

    failed = [o for o in outcomes if o.status == "failed"]
    assigned = sum(1 for o in outcomes if o.status == "assigned")
    typer.echo(
        f"\n{assigned} assigned, "
        f"{sum(1 for o in outcomes if o.status == 'skipped')} skipped, "
        f"{len(failed)} failed"
    )
    # A failed file leaves the rest of the corpus correctly assigned; exit
    # non-zero so a scripted run notices, but never abort mid-walk.
    if failed:
        raise typer.Exit(EXIT_LLM_FAILED)


if __name__ == "__main__":
    sys.exit(app())
