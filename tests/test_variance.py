"""Tests for the prompt-builder variance helpers."""

from __future__ import annotations

from collections import Counter

from scripts.fixtures.prompts import ALL_ERROR_TYPES
from scripts.fixtures.prompts._variance import (
    DIFFICULTIES,
    FLUENCY_SIGNALS,
    PRIOR_TURN_COUNTS,
    SURFACE_FORMS,
    pick_surface_form,
    render_axes_block,
    sample_axes,
)


class TestSampleAxes:
    def test_deterministic(self):
        a = sample_axes("A1", 0)
        b = sample_axes("A1", 0)
        assert a == b

    def test_changes_with_index(self):
        # Over enough indices, at least one axis must vary.
        seen = {sample_axes("A1", i) for i in range(20)}
        assert len(seen) > 1

    def test_changes_with_band(self):
        # Different band seed → different sequence (overwhelmingly likely).
        a1_seq = [sample_axes("A1", i) for i in range(20)]
        c1_seq = [sample_axes("C1", i) for i in range(20)]
        assert a1_seq != c1_seq

    def test_salt_changes_sequence(self):
        # Same (band, idx) but different salt should diverge.
        plain = sample_axes("B1", 5)
        salted = sample_axes("B1", 5, salt="multi")
        assert plain != salted

    def test_returned_values_in_allowed_sets(self):
        for i in range(50):
            diff, fluency, turns = sample_axes("B2", i)
            assert diff in {d for d, _ in DIFFICULTIES}
            assert fluency in FLUENCY_SIGNALS
            assert turns in PRIOR_TURN_COUNTS

    def test_difficulty_distribution_roughly_70_30(self):
        # 1000 samples should land within ±5pp of the 70/30 target.
        samples = [sample_axes("A1", i)[0] for i in range(1000)]
        c = Counter(samples)
        straightforward_pct = c["straightforward"] / 1000
        assert 0.65 <= straightforward_pct <= 0.75

    def test_fluency_roughly_uniform(self):
        samples = [sample_axes("A1", i)[1] for i in range(1500)]
        c = Counter(samples)
        # Each bucket should be within ±5pp of 33%.
        for sig in FLUENCY_SIGNALS:
            assert 0.28 <= c[sig] / 1500 <= 0.39, f"{sig} skew: {c[sig] / 1500:.2f}"


class TestPickSurfaceForm:
    def test_known_type_returns_string(self):
        sf = pick_surface_form("ser_estar", "A1", 0)
        assert sf
        assert sf in SURFACE_FORMS["ser_estar"]

    def test_unknown_type_returns_empty(self):
        assert pick_surface_form("not_a_real_type", "A1", 0) == ""

    def test_deterministic(self):
        assert pick_surface_form("ser_estar", "A1", 7) == pick_surface_form(
            "ser_estar", "A1", 7
        )

    def test_varies_across_index(self):
        seen = {pick_surface_form("ser_estar", "A1", i) for i in range(30)}
        # ser_estar has 5 surface forms — over 30 samples we should see > 1.
        assert len(seen) >= 2

    def test_every_canonical_type_has_a_surface_form(self):
        # Sanity: SURFACE_FORMS should cover every canonical type. If a type is
        # added to ALL_ERROR_TYPES without a surface form, the prompt will lack
        # a specific realisation hint and we'll regress to mode collapse.
        missing = sorted(set(ALL_ERROR_TYPES) - set(SURFACE_FORMS))
        assert not missing, f"SURFACE_FORMS missing entries for: {missing}"


class TestRenderAxesBlock:
    def test_includes_all_axes(self):
        block = render_axes_block("ambiguous", "weak", 2)
        assert "ambiguous" in block
        assert "weak" in block
        assert "**2**" in block

    def test_block_structure_has_difficulty_metadata_pointer(self):
        # The validator expects metadata.difficulty to match — block should tell
        # the generator to set it.
        block = render_axes_block("straightforward", "moderate", 1)
        assert "metadata.difficulty" in block
        assert "fluency_signal" in block
