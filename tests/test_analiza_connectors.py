"""Connector matching engine tests (spec §2D / §3 — pure, no audio needed)."""

from analiza.conectores_b2 import CONECTORES, Conector
from analiza.connectors import connectors_unique_n, formal_ratio, match_connectors


def test_inventory_forms_are_lowercase() -> None:
    assert all(c.forma == c.forma.lower() for c in CONECTORES)


def test_inventory_pairs_reference_real_second_halves() -> None:
    for c in CONECTORES:
        if c.par is not None:
            assert c.par == c.par.lower()


def test_longest_first_span_consuming() -> None:
    # "a pesar de que" must match as one connector, not leave "aunque"-style
    # sub-forms re-matching inside the consumed span.
    matches = match_connectors("lo hice a pesar de que llovía", list(CONECTORES))
    assert [m.conector.forma for m in matches] == ["a pesar de que"]


def test_span_consuming_blocks_shorter_overlap() -> None:
    conectores = [Conector("a pesar de que", "neutro"), Conector("a pesar", "neutro")]
    matches = match_connectors("a pesar de que llueve", conectores)
    assert [m.conector.forma for m in matches] == ["a pesar de que"]


def test_word_boundary() -> None:
    # "aunque" must not match inside another word.
    assert match_connectors("me gusta el desayuno", [Conector("ayuno", "neutro")]) == []


def test_uppercase_and_accents_matched() -> None:
    matches = match_connectors("Además, fui al cine", list(CONECTORES))
    assert [m.conector.forma for m in matches] == ["además"]


def test_discontinuous_pair_counts_once_when_both_present() -> None:
    text = "no solo estudio sino también trabajo"
    matches = match_connectors(text, list(CONECTORES))
    assert sum(1 for m in matches if m.conector.forma == "no solo") == 1


def test_lone_pair_half_does_not_count() -> None:
    matches = match_connectors("no solo estudio", list(CONECTORES))
    assert all(m.conector.forma != "no solo" for m in matches)


def test_pair_second_half_must_follow_first() -> None:
    text = "sino también trabajo, no solo estudio"
    matches = match_connectors(text, list(CONECTORES))
    assert all(m.conector.forma != "no solo" for m in matches)


def test_matches_sorted_by_position() -> None:
    matches = match_connectors(
        "sin embargo fui, aunque llovía, así que volví", list(CONECTORES)
    )
    assert [m.conector.forma for m in matches] == ["sin embargo", "aunque", "así que"]
    assert connectors_unique_n(matches) == 3


def test_formal_ratio() -> None:
    matches = match_connectors("sin embargo fui, aunque llovía", list(CONECTORES))
    assert formal_ratio(matches) == 0.5  # "sin embargo" formal, "aunque" neutro


def test_formal_ratio_empty_is_zero() -> None:
    assert formal_ratio([]) == 0.0
