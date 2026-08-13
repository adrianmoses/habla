"""Find English calques in Spanish text and give peninsular equivalents.

Reads text from a file, an inline argument, or standard input, and asks Claude
for every calque it can find: the literal-from-English structure, a neutral
castellano replacement, and — only when it actually differs — how someone in
Madrid would say it in conversation.

Standalone by design: the taxonomy, the prompt and the report shape live here
rather than in `analiza`, so this runs over any text (a transcript, a WhatsApp
message, a draft email) without the session machinery.

Examples:
    uv run python scripts/detect_calcos.py transcripcion.txt
    uv run python scripts/detect_calcos.py --text "Apliqué para el trabajo"
    pbpaste | uv run python scripts/detect_calcos.py -
    uv run python scripts/detect_calcos.py transcripcion.txt --json -o calcos.json
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TextIO

from anthropic import Anthropic, AnthropicError
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

MODEL = "claude-opus-5"
API_KEY_ENV = "ANTHROPIC_API_KEY"

# max_tokens caps thinking AND response text together, and this model thinks by
# default. Sized (as in analiza/examiner.py, where 4096 silently produced zero
# text blocks on a long transcript) for a full think plus the JSON payload.
MAX_TOKENS = 16000


class Calco(BaseModel):
    """One calque — not one occurrence.

    A phrase the speaker leans on repeatedly is a single entry carrying every
    occurrence, so a habit reads as one thing to fix with a frequency attached
    rather than as five separate findings.
    """

    calco: str  # short label in canonical form, e.g. "aplicar para"
    origen_ingles: str  # the English phrase behind it, e.g. "to apply for"
    fragmentos: list[str] = Field(min_length=1)  # verbatim from the input
    castellano: str  # neutral peninsular equivalent
    # Colloquial Madrid alternative, present only when it differs from the
    # neutral one — see the prompt. None is the common case, not a failure.
    madrileno: str | None
    por_que: str  # one line


class CalcoReport(BaseModel):
    calcos: list[Calco]
    resumen: str


class CalcoError(Exception):
    """The LLM call failed, or its output did not match the schema on retry."""


PROMPT = """\
Eres examinador de español de España. Analizas el texto de un angloparlante \
que aprende español y detectas **calcos del inglés**.

Un calco es una estructura, expresión o uso léxico traducido literalmente del \
inglés: suele ser gramatical, pero suena a traducción y no a español natural. \
Cuentan como calco:

- Estructuras calcadas: «hacer sentido» (make sense), «aplicar para un \
trabajo» (apply for), «en orden de» (in order to), «la razón es porque» \
(the reason is because), «estoy bueno» (I'm good).
- Régimen preposicional tomado del verbo inglés: «escuchar a español», \
«depender en», «pensar sobre», «esperar para».
- Falsos amigos usados con el sentido inglés: «realizar» por darse cuenta, \
«soportar» por apoyar, «eventualmente» por finalmente, «asistir» por ayudar, \
«introducir» por presentar.
- Fórmulas traducidas literalmente: «tomar un descanso», «te veo luego», \
«tener un buen tiempo».

No cuentan:

- Préstamos ya asentados en España («email», «wifi», «marketing»).
- Errores de gramática sin origen inglés: concordancia, conjugación \
irregular, ser/estar cuando no viene de una estructura inglesa.
- Vocabulario latinoamericano correcto, que es variación regional y no calco.

Para cada calco:

- `calco`: etiqueta breve en forma canónica («aplicar para»).
- `origen_ingles`: la expresión inglesa de la que viene («to apply for»).
- `fragmentos`: cada aparición, **copiada literalmente del texto**, sin \
corregirla ni recortarla. Un mismo calco va en una sola entrada con todas \
sus apariciones.
- `castellano`: la expresión que lo sustituye en español peninsular neutro, \
en la misma forma canónica que `calco` y no como reescritura de la frase \
del alumno: para «montar el tren», «coger el tren» — no «Ayer cogí el tren \
a Segovia por la mañana». Es la versión que sirve igual en un correo que en \
una conversación.
- `madrileno`: la misma expresión tal y como la diría alguien de Madrid \
hablando informalmente, también en forma canónica, **solo si es distinta** \
de la neutra y suena natural allí. Si el castellano neutro ya es lo que se \
dice, deja el campo en `null`. No inventes jerga ni fuerces coloquialismos.
- `por_que`: una línea explicando el contraste con el inglés.

Analiza solo lo que está en el texto: no completes lo que falta ni corrijas \
errores que no sean calcos. Si no hay ningún calco, devuelve la lista vacía; \
es una respuesta válida. En `resumen`, una o dos frases sobre el patrón \
dominante (o sobre su ausencia).

Texto a analizar:

<texto>
{texto}
</texto>
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Detect English calques in Spanish text and suggest castellano "
            "(and, where it differs, madrileño) equivalents."
        )
    )
    parser.add_argument(
        "input_file",
        type=Path,
        nargs="?",
        help="Text file to analyse; '-' reads standard input",
    )
    parser.add_argument(
        "-t",
        "--text",
        help="Analyse this text directly instead of reading a file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write the report to this file instead of standard output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the raw structured result as JSON instead of a report",
    )
    parser.add_argument(
        "-m",
        "--model",
        default=MODEL,
        help=f"Anthropic model to use (default: {MODEL})",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help=f"File containing {API_KEY_ENV} (default: .env)",
    )
    return parser.parse_args(argv)


def resolve_text(
    input_file: Path | None, text: str | None, stdin: TextIO
) -> str:
    """Pick the one input the invocation actually supplied.

    Ambiguity is an error rather than a precedence rule: silently ignoring the
    file when --text is also present would analyse the wrong thing and still
    print a confident report.
    """
    if text is not None and input_file is not None:
        raise ValueError("pass either a file or --text, not both")
    if text is not None:
        resolved = text
    elif input_file is not None and str(input_file) != "-":
        resolved = input_file.read_text(encoding="utf-8")
    elif input_file is not None or not stdin.isatty():
        resolved = stdin.read()
    else:
        raise ValueError(
            "no input: pass a file, use --text, or pipe text on standard input"
        )
    resolved = resolved.strip()
    if not resolved:
        raise ValueError("input text is empty")
    return resolved


def build_prompt(text: str) -> str:
    # replace(), not format(): the template body contains literal braces.
    return PROMPT.replace("{texto}", text)


def detect_calcos(text: str, api_key: str, model: str = MODEL) -> CalcoReport:
    """Ask the model for the calques in `text`, with one retry.

    `messages.parse` constrains generation to the CalcoReport schema, so field
    names, types and required keys cannot come back wrong and neither can prose
    wrapped around the JSON. What the API cannot express is the "at least one
    fragment per calque" rule, which the SDK moves into the field description
    and pydantic enforces on parse — that, and a payload truncated mid-JSON,
    are what the retry exists for.
    """
    client = Anthropic(api_key=api_key)
    prompt = build_prompt(text)

    attempt_prompt = prompt
    last_error = ""
    for _ in range(2):
        try:
            response = client.messages.parse(
                model=model,
                max_tokens=MAX_TOKENS,
                output_format=CalcoReport,
                messages=[{"role": "user", "content": attempt_prompt}],
            )
        except AnthropicError as exc:
            raise CalcoError(f"LLM call failed: {exc}") from exc
        except ValidationError as exc:
            last_error = str(exc)
            attempt_prompt = (
                f"{prompt}\n\nTu respuesta anterior no cumplió el esquema. "
                f"Error de validación:\n{last_error}\n"
                "Responde de nuevo únicamente con el JSON corregido."
            )
            continue
        # None means no text block at all — the whole budget went on thinking.
        # A retry hits the same wall, so fail with the diagnosis instead.
        if response.parsed_output is None:
            raise CalcoError(
                f"model returned no text block (stop_reason={response.stop_reason}); "
                f"raise MAX_TOKENS if this is 'max_tokens'"
            )
        return response.parsed_output
    raise CalcoError(
        f"schema validation failed after retry (raise MAX_TOKENS if the JSON "
        f"was truncated): {last_error}"
    )


def render_report(report: CalcoReport) -> str:
    lines: list[str] = []
    if not report.calcos:
        lines.append("Ningún calco visible en el texto.")
    else:
        apariciones = sum(len(c.fragmentos) for c in report.calcos)
        lines.append(
            f"{len(report.calcos)} "
            f"{'calco' if len(report.calcos) == 1 else 'calcos'}, "
            f"{apariciones} "
            f"{'aparición' if apariciones == 1 else 'apariciones'}."
        )
        for n, calco in enumerate(report.calcos, start=1):
            lines += ["", f"{n}. {calco.calco}  (← {calco.origen_ingles})"]
            lines.append(f"   castellano: {calco.castellano}")
            # Absent whenever the neutral phrasing is already what Madrid says.
            if calco.madrileno:
                lines.append(f"   madrileño:  {calco.madrileno}")
            lines.append(f"   por qué:    {calco.por_que}")
            lines += [f'   · "{f}"' for f in calco.fragmentos]
    if report.resumen:
        lines += ["", f"Resumen: {report.resumen}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(args.env_file)

    api_key = os.getenv(API_KEY_ENV)
    if not api_key:
        print(
            f"error: {API_KEY_ENV} is missing from the environment or "
            f"{args.env_file}",
            file=sys.stderr,
        )
        return 2

    try:
        text = resolve_text(args.input_file, args.text, sys.stdin)
        report = detect_calcos(text, api_key=api_key, model=args.model)
    except (ValueError, OSError, CalcoError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = report.model_dump_json(indent=2) if args.json else render_report(report)
    try:
        if args.output:
            args.output.write_text(output + "\n", encoding="utf-8")
            print(f"Report written to {args.output}", file=sys.stderr)
        else:
            print(output)
    except OSError as exc:
        print(f"error: could not write report: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
