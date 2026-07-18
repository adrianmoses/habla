"""Connector matching engine tests (spec §2D / §3 — pure, no audio needed).

Skeletons for the contract cases; unskip as connectors.py is implemented.
"""

import pytest

from analiza.conectores_b2 import CONECTORES, Conector
from analiza.connectors import formal_ratio, match_connectors


def test_inventory_forms_are_lowercase() -> None:
    assert all(c.forma == c.forma.lower() for c in CONECTORES)


def test_inventory_pairs_reference_real_second_halves() -> None:
    for c in CONECTORES:
        if c.par is not None:
            assert c.par == c.par.lower()


@pytest.mark.skip(reason="scaffold: implement connectors.match_connectors")
def test_longest_first_span_consuming() -> None:
    # "a pesar de que" must match as one connector, not leave "aunque"-style
    # sub-forms re-matching inside the consumed span.
    matches = match_connectors("lo hice a pesar de que llovía", list(CONECTORES))
    assert [m.conector.forma for m in matches] == ["a pesar de que"]


@pytest.mark.skip(reason="scaffold: implement connectors.match_connectors")
def test_word_boundary() -> None:
    # "aunque" must not match inside another word.
    assert match_connectors("me gusta el desayuno", [Conector("ayuno", "neutro")]) == []


@pytest.mark.skip(reason="scaffold: implement connectors.match_connectors")
def test_discontinuous_pair_counts_once_when_both_present() -> None:
    text = "no solo estudio sino también trabajo"
    matches = match_connectors(text, list(CONECTORES))
    assert sum(1 for m in matches if m.conector.forma == "no solo") == 1


@pytest.mark.skip(reason="scaffold: implement connectors.match_connectors")
def test_lone_pair_half_does_not_count() -> None:
    matches = match_connectors("no solo estudio", list(CONECTORES))
    assert all(m.conector.forma != "no solo" for m in matches)


@pytest.mark.skip(reason="scaffold: implement connectors.formal_ratio")
def test_formal_ratio_empty_is_zero() -> None:
    assert formal_ratio([]) == 0.0
