"""Connector matching engine (spec §2D) over conectores_b2 data.

Pure functions: plain text in, plain matches out — no I/O, unit-test target.
"""

import re
from dataclasses import dataclass

from analiza.conectores_b2 import Conector


@dataclass(frozen=True)
class ConnectorMatch:
    conector: Conector
    start: int  # char offset into the (lowercased) transcript
    end: int


def match_connectors(text: str, conectores: list[Conector]) -> list[ConnectorMatch]:
    """Find connector occurrences in a transcript.

    Contract (spec §2D):
    - lowercase the text, keep accents; forms in the inventory are already
      lowercase-with-accents
    - longest form first, so "a pesar de que" wins over a hypothetical "a pesar"
    - span-consuming: a character range matched by one connector cannot be
      re-matched by a shorter one
    - word-bounded (regex \\b or equivalent): "aunque" must not match inside
      another word
    - discontinuous pairs (Conector.par set): count once when both halves are
      present, in order; a lone half does not count
    """
    lowered = text.lower()
    consumed: list[tuple[int, int]] = []
    matches: list[ConnectorMatch] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < c_end and end > c_start for c_start, c_end in consumed)

    for conector in sorted(conectores, key=lambda c: len(c.forma), reverse=True):
        pattern = re.compile(rf"\b{re.escape(conector.forma)}\b")
        for m in pattern.finditer(lowered):
            if overlaps(m.start(), m.end()):
                continue
            if conector.par is not None:
                second = re.compile(rf"\b{re.escape(conector.par)}\b")
                if not second.search(lowered, m.end()):
                    continue  # lone half does not count
            consumed.append((m.start(), m.end()))
            matches.append(
                ConnectorMatch(conector=conector, start=m.start(), end=m.end())
            )

    matches.sort(key=lambda m: m.start)
    return matches


def connectors_unique_n(matches: list[ConnectorMatch]) -> int:
    """Number of distinct connector forms matched."""
    return len({m.conector.forma for m in matches})


def formal_ratio(matches: list[ConnectorMatch]) -> float:
    """formal / total matched — the alcance trend metric. 0.0 when no matches."""
    if not matches:
        return 0.0
    formal = sum(1 for m in matches if m.conector.registro == "formal")
    return formal / len(matches)
