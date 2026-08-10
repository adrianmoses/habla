"""Progress aggregation (spec 034 WS2): pure functions over stored sessions.

No I/O and no LLM — the same posture as `metrics.py`, and for the same reason:
the numbers in a progress report must not move because a model was called
twice. `historial.py` reads the corpus off disk and hands this module plain
data; the narrative pass (WS3) gets what comes out of here, never transcripts
and never the raw `examiner.json` files.

Three things this refuses to do, each one a lesson from the corpus:

1. **Trend across a provenance boundary.** `errors_n` changed meaning at
   examiner_v2 (rows → patterns) and `fillers_n` moves with the whisper model,
   so sessions are segmented by `(prompt_version, whisper_model)` and each
   segment trends on its own.
2. **Read absence as evidence.** The examiner reports at most
   `MAX_PATRONES` patterns and that cap binds every run so far, so a fault
   missing from a session may just have ranked 11th. Absence counts only when
   the session *could* have reported the fault and did not — see
   `absence_is_conclusive`.
3. **Fit a line.** ~10–40 noisy points over topics of varying difficulty; a
   slope would read as far more precision than exists (Key Decision 3), so a
   trend is a first-window/last-window comparison carrying the session count
   behind each side.
"""

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from statistics import fmean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from analiza.config import ProgresoThresholds
from analiza.patrones_b2 import PATRONES_POR_ID, PatternId, Tipo, ids_disponibles

# CSV cells that parse as numbers. Everything else in note.STATS_COLUMNS is
# provenance or free text.
NUMERIC_COLUMNS: tuple[str, ...] = (
    "duration_s", "wpm_gross", "wpm_articulation", "pauses_n", "pause_max_s",
    "fillers_per_min", "connectors_unique", "formal_ratio", "mtld", "errors_n",
    "calcos_n", "score_total",
)

# What gets trended, with the label the note and the model read. Deliberately
# not every numeric column:
#   · errors_n / calcos_n — capped at MAX_PATRONES (the cap binds), and
#     `tipo` is unstable run to run, so calcos_n carries ±1 of pure model
#     noise on identical audio (spec 034 §Why, Key Decision 4).
#   · pauses_n / connectors_unique — raw counts that grow with session length;
#     pauses becomes `pauses_per_min` below, and connector *variety* has no
#     honest per-minute reading.
#   · duration_s — a property of the recording, not of the speaker.
TREND_METRICS: tuple[tuple[str, str], ...] = (
    ("wpm_gross", "WPM (bruto)"),
    ("wpm_articulation", "WPM (articulación)"),
    ("pauses_per_min", "Pausas/min"),
    ("pause_max_s", "Pausa máx (s)"),
    ("fillers_per_min", "Muletillas/min (cota inferior)"),
    ("formal_ratio", "Ratio de conectores formales"),
    ("mtld", "MTLD"),
    ("score_total", "Puntuación DELE (/12)"),
)

EstadoPatron = Literal["persistente", "ausente", "no-concluyente"]


class Sesion(BaseModel):
    """One analysed session: its CSV row joined with its stored artifacts.

    Built by `historial.py`. Everything the aggregation needs in order to
    decide *how much this session can be trusted to say* travels with it,
    because that judgment is not recoverable downstream: a `--no-llm` session
    has no opinion about patterns at all, and one that filled the examiner's
    pattern cap has an opinion only about what it did report.
    """

    model_config = ConfigDict(frozen=True)

    fecha: dt.date
    ejercicio: str
    tema: str = ""
    metricas: dict[str, float] = Field(default_factory=dict)
    whisper_model: str = ""
    prompt_version: str = ""
    # "" → recorded before the vocabulary was versioned. Read as the baseline
    # version, which is the truth rather than a guess: it predates every id
    # added since.
    vocab_version: str = ""
    # None → never examined (`--no-llm`, or the LLM pass failed). Distinct from
    # {} (examined, found nothing), which is a real observation about a
    # session and counts as evidence of absence.
    patrones: dict[PatternId, int] | None = None
    otros_n: int = 0  # findings keyed `otro`: real faults, but untrackable
    filas_sin_id: int = 0  # pre-vocabulary rows the backfill never reached
    truncado: bool = False  # examiner returned a full MAX_PATRONES rows
    backfilled: bool = False  # ids assigned retroactively, not natively
    vad_gap_ratio: float | None = None
    # Which session of its (date, exercise) this is. A date is not a unique
    # key — three monólogos in one afternoon is ordinary practice — so without
    # this a report would flag "2026-08-10 monologo" and leave the reader
    # unable to tell which of the three it meant.
    ordinal: int = 1

    @property
    def clave(self) -> str:
        """How a session is named anywhere it is listed. Matches its note
        filename, so a flagged session can actually be opened."""
        sufijo = "" if self.ordinal == 1 else f" ({self.ordinal})"
        return f"{self.fecha.isoformat()} {self.ejercicio}{sufijo}"

    @property
    def examinada(self) -> bool:
        return self.patrones is not None


class Parametros(BaseModel):
    """The gates this aggregation was computed under, recorded alongside it:
    a report that does not say which thresholds produced it cannot be compared
    with the one before it."""

    ventana_n: int
    ausencia_n: int
    min_sesiones: int
    vad_gap_ratio: float

    @classmethod
    def from_thresholds(cls, t: ProgresoThresholds) -> "Parametros":
        return cls(
            ventana_n=t.ventana_n,
            ausencia_n=t.ausencia_n,
            min_sesiones=t.min_sesiones,
            vad_gap_ratio=t.vad_gap_ratio,
        )


class Ventana(BaseModel):
    n: int
    media: float


class TendenciaMetrica(BaseModel):
    metrica: str
    etiqueta: str
    estado: Literal["ok", "insuficiente"]
    sesiones_n: int  # sessions in this segment carrying the metric at all
    primeras: Ventana | None = None
    ultimas: Ventana | None = None
    delta: float | None = None
    faltan: int = 0  # sessions still needed for two non-overlapping windows


class Segmento(BaseModel):
    """Sessions sharing a (prompt_version, whisper_model) pair — the unit a
    trend is allowed to span."""

    prompt_version: str
    whisper_model: str
    sesiones_n: int
    primera: dt.date
    ultima: dt.date
    tendencias: list[TendenciaMetrica]


class PatronRecurrencia(BaseModel):
    pattern_id: PatternId
    etiqueta: str
    tipo_habitual: Tipo
    sesiones_n: int  # examined sessions it appeared in
    instancias_n: int
    primera: dt.date
    ultima: dt.date
    # Examined sessions after `ultima`, split by whether their silence means
    # anything. `ausencias_concluyentes` is what the estado is decided on.
    sesiones_desde_ultima: int
    ausencias_concluyentes: int
    estado: EstadoPatron


class ProgresoStats(BaseModel):
    """The deterministic layer in full — written to `stats.json` and handed to
    the narrative pass instead of the sessions themselves."""

    generado: dt.date
    desde: dt.date | None = None
    hasta: dt.date | None = None
    ejercicio: str | None = None
    parametros: Parametros
    sesiones_n: int
    examinadas_n: int
    primera: dt.date | None = None
    ultima: dt.date | None = None
    # False → below the minimum session count. The aggregation is still
    # complete and still written; only the story is declined.
    narrativa: bool
    segmentos: list[Segmento] = Field(default_factory=list)
    fronteras: list[str] = Field(default_factory=list)
    patrones: list[PatronRecurrencia] = Field(default_factory=list)
    otros_n: int = 0  # findings across the range that no id could carry
    baja_confianza: list[str] = Field(default_factory=list)
    advertencias: list[str] = Field(default_factory=list)


def plural(n: int, singular: str, plural_: str) -> str:
    """"1 sesión" / "3 sesiones". The note and the warnings are read by a
    learner of Spanish, so "1 sesiones" is not an option."""
    return f"{n} {singular if n == 1 else plural_}"


def session_metrics(row: Mapping[str, str]) -> dict[str, float]:
    """Numeric CSV cells as floats, plus the length-normalised derivations.

    An empty cell is dropped, never zeroed: `--no-llm` leaves `score_total`
    blank, and a missing score is not a score of zero — it would drag a window
    mean down as if the session had been terrible.
    """
    out: dict[str, float] = {}
    for col in NUMERIC_COLUMNS:
        raw = (row.get(col) or "").strip()
        if not raw:
            continue
        try:
            out[col] = float(raw)
        except ValueError:
            continue  # a hand-edited cell; the rest of the row is still good
    duration = out.get("duration_s", 0.0)
    if duration > 0 and "pauses_n" in out:
        out["pauses_per_min"] = round(out["pauses_n"] / duration * 60, 2)
    return out


def orden(sesion: Sesion) -> tuple[dt.date, str]:
    """The corpus's chronological order.

    Keyed on (fecha, ejercicio) rather than the date alone so two sessions on
    one day order the same way on every run — determinism is a stated
    acceptance criterion, and CSV row order is not a contract. Everything that
    needs "before" and "after" sorts by this and then works in *positions*:
    a date is not a unique key here, so date comparisons cannot separate two
    sessions recorded on one day.
    """
    return (sesion.fecha, sesion.ejercicio)


def select(
    sesiones: Iterable[Sesion],
    *,
    desde: dt.date | None = None,
    hasta: dt.date | None = None,
    ejercicio: str | None = None,
) -> list[Sesion]:
    """The report's range filter, chronological. Bounds are inclusive."""
    chosen = [
        s
        for s in sesiones
        if (desde is None or s.fecha >= desde)
        and (hasta is None or s.fecha <= hasta)
        and (ejercicio is None or s.ejercicio == ejercicio)
    ]
    return sorted(chosen, key=orden)


def metric_trend(
    metrica: str, etiqueta: str, valores: Sequence[float], ventana_n: int
) -> TendenciaMetrica:
    """First-N vs last-N over one metric's chronological values.

    Requires two *non-overlapping* windows: with fewer sessions the same
    session would sit on both sides and the comparison would report a
    difference between a number and itself.
    """
    needed = 2 * ventana_n
    if len(valores) < needed:
        return TendenciaMetrica(
            metrica=metrica,
            etiqueta=etiqueta,
            estado="insuficiente",
            sesiones_n=len(valores),
            faltan=needed - len(valores),
        )
    primeras = Ventana(n=ventana_n, media=round(fmean(valores[:ventana_n]), 3))
    ultimas = Ventana(n=ventana_n, media=round(fmean(valores[-ventana_n:]), 3))
    return TendenciaMetrica(
        metrica=metrica,
        etiqueta=etiqueta,
        estado="ok",
        sesiones_n=len(valores),
        primeras=primeras,
        ultimas=ultimas,
        delta=round(ultimas.media - primeras.media, 3),
    )


def segment_key(sesion: Sesion) -> tuple[str, str]:
    return (sesion.prompt_version, sesion.whisper_model)


def segment_sessions(
    sesiones: Sequence[Sesion], ventana_n: int
) -> list[Segmento]:
    """Group by provenance pair, then trend inside each group.

    Groups are keyed in first-appearance order over chronologically sorted
    input, so the oldest segment leads.
    """
    grupos: dict[tuple[str, str], list[Sesion]] = {}
    for s in sesiones:
        grupos.setdefault(segment_key(s), []).append(s)
    return [
        Segmento(
            prompt_version=prompt_version,
            whisper_model=whisper_model,
            sesiones_n=len(grupo),
            primera=grupo[0].fecha,
            ultima=grupo[-1].fecha,
            tendencias=[
                metric_trend(
                    metrica,
                    etiqueta,
                    [s.metricas[metrica] for s in grupo if metrica in s.metricas],
                    ventana_n,
                )
                for metrica, etiqueta in TREND_METRICS
            ],
        )
        for (prompt_version, whisper_model), grupo in grupos.items()
    ]


def segment_boundaries(sesiones: Sequence[Sesion]) -> list[str]:
    """Every provenance change in the range, named and dated.

    A boundary is not a footnote: it is the reason two segments exist, and the
    report has to say which change split them so the reader knows the numbers
    on either side were never comparable.
    """
    fronteras: list[str] = []
    for prev, cur in zip(sesiones, sesiones[1:], strict=False):
        for campo in ("prompt_version", "whisper_model"):
            antes, ahora = getattr(prev, campo), getattr(cur, campo)
            if antes != ahora:
                fronteras.append(
                    f"{campo}: {antes or '(sin registrar)'} → "
                    f"{ahora or '(sin registrar)'} en {cur.clave}"
                )
    return fronteras


def absence_is_conclusive(sesion: Sesion, pattern_id: PatternId) -> bool:
    """Whether this session not reporting `pattern_id` is evidence of anything.

    Four ways a silence means nothing:

    · the session was never examined — it has no opinion to give;
    · the examiner filled its pattern cap, so the fault may have ranked 11th
      (spec 034 §Validate: the cap binds on every run measured);
    · the id did not exist at the session's vocabulary version, so nothing
      could have been keyed to it;
    · the ids were assigned by backfill, which saw only the finding prose and
      not the transcript — a mis-key there produces a false absence exactly
      as easily as a false presence, which is what the `backfill.json`
      sidecar exists to let us notice.

    A session carrying rows the backfill never reached is the same problem in
    a smaller form: those rows have no id, so they cannot rule anything out.
    """
    return (
        sesion.examinada
        and not sesion.truncado
        and not sesion.backfilled
        and sesion.filas_sin_id == 0
        and pattern_id in ids_disponibles(sesion.vocab_version)
    )


def pattern_recurrence(
    sesiones: Sequence[Sesion], ausencia_n: int
) -> list[PatronRecurrencia]:
    """Sessions/first/last/instances per `pattern_id`, plus what the silence
    since then is worth.

    Computed across the whole range rather than per segment: a stable
    `pattern_id` surviving a prompt bump is the entire point of the vocabulary,
    and the availability check above already handles the one boundary that
    genuinely breaks comparability.
    """
    # Sorted here as well as in `select`, because everything below indexes into
    # this list and being handed it out of order would silently invert "since".
    examinadas = sorted((s for s in sesiones if s.examinada), key=orden)
    apariciones: dict[PatternId, list[tuple[int, int]]] = {}
    for i, s in enumerate(examinadas):
        for pattern_id, instancias in (s.patrones or {}).items():
            apariciones.setdefault(pattern_id, []).append((i, instancias))

    recurrencias: list[PatronRecurrencia] = []
    for pattern_id, hits in apariciones.items():
        indices = [i for i, _ in hits]
        ultimo = max(indices)
        # Position, not date. Two sessions can share a day, and `fecha > ultima`
        # would drop every same-day session recorded after the appearance — a
        # fault seen in the morning's monólogo and absent from that afternoon's
        # narración would count as zero sessions gone by, so the absence
        # threshold could be reached late or never.
        posteriores = examinadas[ultimo + 1 :]
        concluyentes = sum(
            1 for s in posteriores if absence_is_conclusive(s, pattern_id)
        )
        if concluyentes >= ausencia_n:
            estado: EstadoPatron = "ausente"
        elif len(posteriores) >= ausencia_n:
            # Long gone by the calendar, but not by the evidence.
            estado = "no-concluyente"
        else:
            estado = "persistente"
        patron = PATRONES_POR_ID[pattern_id]
        recurrencias.append(
            PatronRecurrencia(
                pattern_id=pattern_id,
                etiqueta=patron.etiqueta,
                tipo_habitual=patron.tipo_habitual,
                sesiones_n=len(hits),
                instancias_n=sum(n for _, n in hits),
                primera=examinadas[min(indices)].fecha,
                ultima=examinadas[ultimo].fecha,
                sesiones_desde_ultima=len(posteriores),
                ausencias_concluyentes=concluyentes,
                estado=estado,
            )
        )
    # Most recurrent first — the "focus next" ordering. Every tie broken on the
    # id so repeated runs produce a byte-identical file.
    return sorted(
        recurrencias, key=lambda r: (-r.sesiones_n, -r.instancias_n, r.pattern_id)
    )


def low_confidence(sesiones: Sequence[Sesion], vad_gap_ratio: float) -> list[str]:
    """Sessions whose VAD speech went largely untranscribed — detected speech
    that produced no words is usually mumbling or fillers, and every metric
    downstream of the word list is understated for that session."""
    return [
        s.clave
        for s in sesiones
        if s.vad_gap_ratio is not None and s.vad_gap_ratio > vad_gap_ratio
    ]


def aggregate(
    sesiones: Iterable[Sesion],
    *,
    hoy: dt.date,
    parametros: ProgresoThresholds,
    desde: dt.date | None = None,
    hasta: dt.date | None = None,
    ejercicio: str | None = None,
    advertencias: Sequence[str] = (),
) -> ProgresoStats:
    """The whole deterministic layer for one report.

    `hoy` is a parameter rather than `date.today()` so this stays a pure
    function of its inputs — the determinism criterion would otherwise fail
    across midnight.
    """
    rango = select(sesiones, desde=desde, hasta=hasta, ejercicio=ejercicio)
    examinadas = [s for s in rango if s.examinada]
    avisos = list(advertencias)

    sin_id = sum(s.filas_sin_id for s in rango)
    if sin_id:
        avisos.append(
            f"{plural(sin_id, 'fila', 'filas')} de error sin pattern_id: fuera "
            "del seguimiento (ejecuta `analiza backfill-patrones`)."
        )
    backfilled = [s.clave for s in examinadas if s.backfilled]
    if backfilled:
        avisos.append(
            f"{plural(len(backfilled), 'sesión', 'sesiones')} con pattern_id "
            f"asignado por backfill ({', '.join(backfilled)}): su silencio "
            "sobre un patrón no cuenta como prueba."
        )
    truncadas = [s.clave for s in examinadas if s.truncado]
    if truncadas:
        avisos.append(
            f"{plural(len(truncadas), 'sesión', 'sesiones')} en el tope de "
            f"patrones del examinador ({', '.join(truncadas)}): lo que falta "
            "ahí pudo quedar fuera por el corte."
        )
    no_examinadas = len(rango) - len(examinadas)
    if no_examinadas:
        avisos.append(
            f"{plural(no_examinadas, 'sesión', 'sesiones')} sin pase de "
            "examinador: entra en las métricas, no en los patrones."
        )

    return ProgresoStats(
        generado=hoy,
        desde=desde,
        hasta=hasta,
        ejercicio=ejercicio,
        parametros=Parametros.from_thresholds(parametros),
        sesiones_n=len(rango),
        examinadas_n=len(examinadas),
        primera=rango[0].fecha if rango else None,
        ultima=rango[-1].fecha if rango else None,
        narrativa=len(rango) >= parametros.min_sesiones,
        segmentos=segment_sessions(rango, parametros.ventana_n),
        fronteras=segment_boundaries(rango),
        patrones=pattern_recurrence(rango, parametros.ausencia_n),
        otros_n=sum(s.otros_n for s in rango),
        baja_confianza=low_confidence(rango, parametros.vad_gap_ratio),
        advertencias=avisos,
    )
