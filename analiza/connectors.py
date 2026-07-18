"""Connector matching engine (spec §2D) over conectores_b2 data.

Pure functions: plain text in, plain matches out — no I/O, unit-test target.
"""

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

    TODO(implement).
    """
    raise NotImplementedError


def connectors_unique_n(matches: list[ConnectorMatch]) -> int:
    """Number of distinct connector forms matched."""
    raise NotImplementedError


def formal_ratio(matches: list[ConnectorMatch]) -> float:
    """formal / total matched — the alcance trend metric. 0.0 when no matches."""
    raise NotImplementedError
