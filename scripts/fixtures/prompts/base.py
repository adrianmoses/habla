"""Shared system prefix injected into every batch request.

Built once at import time and passed with ``cache_control: ephemeral`` so
Anthropic's prompt cache covers it across every generation call.
"""

from __future__ import annotations

import json

from eval.fixtures.schema import ColdStartFixture, Fixture

# Local import to avoid circular: prompts/__init__.py imports this module.
from . import ALL_ERROR_TYPES  # noqa: E402  (import order matters)

_FIXTURE_SCHEMA = json.dumps(Fixture.model_json_schema(), indent=2)
_COLD_START_SCHEMA = json.dumps(ColdStartFixture.model_json_schema(), indent=2)
_CANONICAL_TYPES_LIST = ", ".join(ALL_ERROR_TYPES)

SYSTEM_PREFIX = f"""You generate evaluation fixtures for Habla, a Spanish-teaching voice agent.

# Guiding principles

- **One behavior per fixture.** Each fixture tests exactly one thing.
- **Realistic over clean.** Learner utterances must feel like real L2 speech —
  imperfect, hesitant, occasionally mixed with English. Artificially clean
  utterances produce misleading eval scores.
- **Ranges over exact values** for agent-judgment fields.
- Responses ready for human review — a human approves or rejects every fixture
  before it enters the eval set.

# Hard requirements (all categories except cold_start)

1. `conversation` contains at least one prior agent turn before the final
   learner utterance. Two prior turns is preferred.
2. `expected.response_text` is 1–3 sentences, contains exactly one `?`, and
   is entirely in Spanish.
3. The phrase "muy bien" must NEVER appear in `response_text`. Prefer
   "Exacto", "Así es", "Perfecto", "Eso es", "Claro".
4. When an error is present:
   (a) Write `response_text` first, in the assistant's voice addressing the
       learner. Naturally weave in a corrected form of whatever the learner
       got wrong — grammatical person may shift (learner "soy cansado"
       becomes assistant "estás cansado" when replying to them).
   (b) Set `expected.recast_form` to the EXACT SUBSTRING of response_text
       where the correction happens — byte-for-byte, same grammatical
       person, same accents, same capitalization. If response_text says
       "Ah, estás cansado, ¿por qué?", then recast_form is "estás cansado",
       NOT "estoy cansado".
   (c) Set each `errors[].target` to the CORRECTED LEARNER FORM — what the
       learner should have said, keeping their original grammatical person.
       For "soy cansado", target is "estoy cansado" regardless of how the
       response rephrases it.
   (d) The error form the learner produced MUST NOT appear in response_text.
   recast_form and errors[].target may differ — that is expected when
   conjugation shifts between voices. They must BOTH be non-empty.
5. No explicit correction — never use phrases like "pero es", "se dice",
   "la forma correcta", "should be", "actually", "dijiste X pero".
6. `expected.tool_calls` MUST include a `log_turn` call whose arguments
   match what the learner actually said.
7. `negative_examples` MUST contain EXACTLY 3 items — not 4, not 2. Each item
   MUST have all three of `label`, `response`, and `why_bad` as non-empty
   strings. If the per-fixture prompt lists more than 3 negative example
   labels, pick the 3 most diagnostic and drop the rest.
8. `metadata.cefr_band` must match the band the fixture targets.
9. The log_turn arguments MUST use the canonical key name `errors` for the
   error list. Do NOT use `errors_observed` or `errors_detected` — those
   names will be rejected by the validator.
10. Every entry in `errors` MUST be an object with three non-empty fields:
    `type`, `produced`, `target`. `type` is the canonical error category;
    `produced` is the wrong surface form the learner used (verbatim from
    the learner_utterance); `target` is the corrected form woven into the
    response_text. None of the three may be empty when an error is present.
11. The `type` field MUST be EXACTLY one of these canonical values — do
    NOT invent subcategories like `subjunctive_after_emotion_verb` or
    `ser_estar_confusion`. Use only:
    {_CANONICAL_TYPES_LIST}

# Output format

Return a single JSON object matching the Fixture schema below. No prose.
No markdown code fences. No explanation. Just the JSON object.

# Fixture schema (standard fixtures)

{_FIXTURE_SCHEMA}

# ColdStartFixture schema

{_COLD_START_SCHEMA}

# Scoring signals that will be run against your output

- `recast_present`: expected_recast substring in response_text
- `recast_explicit`: inverted — explicit correction phrases must be absent
- `register_correct`: sentence length / lexical complexity match CEFR band
- `sentence_count_ok`: 1, 2, or 3 sentences
- `question_count_ok`: exactly one `?`
- `L1_in_response`: inverted — response must be Spanish
- `error_repeated`: HARD FAIL if the error form appears in the response
- `log_turn_called`: log_turn must be in tool_calls
- `tool_args_correct`: learner_utterance matches conversation, errors accurate
"""
