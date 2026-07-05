"""mimicry_cycle — 15 fixtures (A1 only, 5 per stage)."""

from __future__ import annotations

from eval.fixtures.schema import CEFRBand

STAGES = ["offer", "repeat", "extend"]


def build_user_prompts(n: int, band: CEFRBand) -> list[str]:
    if band != "A1":
        return []
    prompts: list[str] = []
    for i in range(n):
        stage = STAGES[i % len(STAGES)]
        prompts.append(
            f"""Generate ONE `mimicry_cycle` fixture (A1 only).

Stage: **{stage}**

Stage definitions:
- `offer`: agent offers a short sentence and explicitly invites repetition
  ("¿Puedes repetir?", "Repite conmigo", "Di conmigo"). Learner has not
  yet attempted.
- `repeat`: learner has attempted imperfect repetition in the previous turn;
  agent accepts warmly and prepares to extend.
- `extend`: agent adds exactly ONE new meaningful word to the sentence and
  invites another repetition cycle.

Hard constraints:
- `response_text` is ≤ 20 words total
- "muy bien" is BANNED (use "Exacto", "Así es", "Perfecto", "Eso es")
- `offer` must contain an explicit repetition invitation
- `extend` adds exactly one new word beyond what was offered before
- Tag with the stage label

Required negative examples:
- `too_long` — more than 20 words
- `corrects_pronunciation` — agent names pronunciation errors
- `skips_to_full_conversation` — drops the mimicry frame and asks an
  open-ended question

Variation #{i + 1} of {n}."""
        )
    return prompts
