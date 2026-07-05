"""Shared CEFR band constants and helpers.

Single source of truth for the band enumeration, the band-as-numeric
midpoint, and the score-to-band bucketing rule. Imported by the leveling
policy, the prompt renderer, the profile repo, and the replay script —
without this module they had drifting copies.
"""

from __future__ import annotations

from typing import TypeGuard, get_args

from eval.fixtures.schema import CEFRBand

# Tuple form of the ``CEFRBand`` Literal — derived once so adding a band
# to the Literal flows through here without a follow-up edit. Order
# matches the natural progression A1 → C1 (lowest to highest).
ALL_BANDS: tuple[CEFRBand, ...] = get_args(CEFRBand)

# Band-as-numeric anchored at the bucket center. The bucketing rule (below)
# treats "uniformly A2" and "uniformly B1" as exactly one bucket-width apart.
BAND_MIDPOINT: dict[CEFRBand, float] = {
    "A1": 0.1,
    "A2": 0.3,
    "B1": 0.5,
    "B2": 0.7,
    "C1": 0.9,
}

# Half-open bucket boundaries: a score below ``boundary`` belongs to the
# associated band. The C1 boundary is 1.01 so 0.9 (uniformly C1) lands
# cleanly in the C1 bucket without hitting an edge case.
BAND_BUCKETS: tuple[tuple[float, CEFRBand], ...] = (
    (0.20, "A1"),
    (0.40, "A2"),
    (0.60, "B1"),
    (0.80, "B2"),
    (1.01, "C1"),
)


def bucket_band(score: float) -> CEFRBand:
    """Map a band-as-numeric score to its bucket label."""
    for boundary, band in BAND_BUCKETS:
        if score < boundary:
            return band
    return "C1"


def is_valid_cefr_band(value: object) -> TypeGuard[CEFRBand]:
    """Runtime guard for arbitrary input claiming to be a CEFR band string."""
    return isinstance(value, str) and value in ALL_BANDS


def band_index(band: CEFRBand) -> int:
    """Index of ``band`` in ``ALL_BANDS`` — useful for distance metrics."""
    return ALL_BANDS.index(band)
