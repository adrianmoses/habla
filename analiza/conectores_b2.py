"""B2 connector inventory — the data side of the matching engine (connectors.py).

Starter list; extend freely. Matching semantics (longest-first, span-consuming,
word-bounded) live in connectors.py, so entries here are plain declarative data.
"""

from dataclasses import dataclass
from typing import Literal

Registro = Literal["formal", "neutro"]


@dataclass(frozen=True)
class Conector:
    forma: str  # surface form, lowercase, accents kept
    registro: Registro
    # Triggers the examiner's subjunctive check (spec §2E task 3).
    subjuntivo: bool = False
    # Second half of a discontinuous pair ("no solo … sino también").
    # The pair counts once when both halves are present.
    par: str | None = None


CONECTORES: list[Conector] = [
    # Causa / consecuencia
    Conector("por lo tanto", "formal"),
    Conector("por consiguiente", "formal"),
    Conector("de ahí que", "formal", subjuntivo=True),
    Conector("dado que", "formal"),
    Conector("puesto que", "formal"),
    Conector("ya que", "neutro"),
    Conector("así que", "neutro"),
    # Contraste / concesión
    Conector("sin embargo", "formal"),
    Conector("no obstante", "formal"),
    Conector("en cambio", "neutro"),
    Conector("mientras que", "neutro"),
    Conector("a pesar de que", "neutro"),
    Conector("aunque", "neutro"),
    Conector("aun así", "neutro"),
    # Condición
    Conector("a menos que", "formal", subjuntivo=True),
    Conector("siempre que", "neutro", subjuntivo=True),
    Conector("con tal de que", "formal", subjuntivo=True),
    Conector("en caso de que", "formal", subjuntivo=True),
    # Reformulación / ejemplo
    Conector("es decir", "neutro"),
    Conector("o sea", "neutro"),
    Conector("por ejemplo", "neutro"),
    Conector("en concreto", "formal"),
    # Organización del discurso
    Conector("en primer lugar", "formal"),
    Conector("por un lado", "neutro", par="por otro lado"),
    Conector("no solo", "neutro", par="sino también"),
    Conector("en cuanto a", "formal"),
    Conector("respecto a", "formal"),
    Conector("asimismo", "formal"),
    Conector("además", "neutro"),
    # Cierre
    Conector("en definitiva", "formal"),
    Conector("en resumen", "neutro"),
    Conector("al fin y al cabo", "neutro"),
]
