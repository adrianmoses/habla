# Habla Eval Fixture Specification

## Overview

Fixtures are the ground truth for model evaluation. They define what correct
agent behavior looks like across every situation Habla will encounter. All
model checkpoints — base, prompt-engineered, fine-tuned — are scored against
the same fixtures, making performance gains provable and comparable.

---

## Guiding Principles

**One behavior per fixture.** Each fixture tests exactly one thing clearly.
A fixture that tests recast quality AND tool call correctness simultaneously
tells you nothing useful when it fails.

**Realistic over clean.** Learner utterances should feel like real L2 speech
— imperfect, hesitant, sometimes mixed with English. Artificially constructed
utterances produce misleading eval scores.

**Ranges over exact values.** Where agent judgment is involved (cold start
level estimates, fluency signals), fixtures specify acceptable ranges rather
than single correct values. This avoids penalizing reasonable variation.

**Human review is mandatory.** Every generated fixture must be reviewed and
approved before it enters the eval set. Generated fixtures are a starting
point, not a final product.

---

## File Layout

```
eval/
  fixtures/
    schema.py                    # Pydantic models — the authoritative schema
    single_error_recast.json     # 50 fixtures
    multi_error.json             # 30 fixtures
    l1_handling.json             # 25 fixtures
    mimicry_cycle.json           # 15 fixtures (A1 only)
    cold_start.json              # 20 fixtures
    register_boundary.json       # 20 fixtures
    tool_call_correctness.json   # 20 fixtures
    error_pattern_threshold.json # 20 fixtures
```

Each file is a JSON array of fixture objects. Total: **200 fixtures**.

---

## Fixture Structure

Every fixture (except cold start) has four sections:

```
1. Identity      id, type
2. Context       system_params, conversation
3. Expected      response_text, recast_form, tool_calls
4. Metadata      cefr_band, difficulty, tags, ...
5. Negatives     label, response, why_bad
```

### Full example — single error recast

```json
{
  "id": "single_error_recast_A2_gender_agreement_003",

  "system_params": {
    "profile": {
      "production_level": 0.40,
      "L1_reliance": 0.20,
      "speech_fluency": 0.50,
      "is_calibrated": true,
      "sessions_completed": 3,
      "vocab_strengths": [],
      "error_patterns": []
    },
    "theme": {
      "domain": "food_and_cooking",
      "prompt": "¿Qué comes normalmente?",
      "target_structures": ["present tense", "gustar"]
    }
  },

  "conversation": [
    {
      "role": "assistant",
      "content": "¿Qué sueles comer durante la semana?"
    },
    {
      "role": "user",
      "content": "Normalmente como arroz y pollo."
    },
    {
      "role": "user",
      "content": "Ayer fui al mercado y compré mucho verdura fresca."
    }
  ],

  "expected": {
    "response_text": "¡Qué bien! ¿Encontraste muchas verduras de temporada?",
    "recast_form": "muchas verduras",
    "tool_calls": [
      {
        "name": "log_turn",
        "arguments": {
          "learner_id": "eval_learner",
          "learner_utterance": "Ayer fui al mercado y compré mucho verdura fresca.",
          "L1_used": false,
          "errors_observed": [
            {
              "type": "grammar",
              "example": "mucho verdura",
              "recast": "muchas verduras"
            }
          ],
          "vocab_produced": ["mercado", "verdura", "fresca"],
          "fluency_signal": "moderate"
        }
      }
    ]
  },

  "metadata": {
    "cefr_band": "A2",
    "learner_production_level": 0.40,
    "errors_present": ["gender_agreement"],
    "expected_recast": "muchas verduras",
    "L1_used": false,
    "fluency_signal": "moderate",
    "difficulty": "straightforward",
    "tags": ["gender_agreement", "food_and_cooking", "preterite"]
  },

  "negative_examples": [
    {
      "label": "explicit_correction",
      "response": "Dijiste 'mucho verdura' pero es 'muchas verduras'. ¿Fuiste solo?",
      "why_bad": "Names the error directly — breaks conversational flow"
    },
    {
      "label": "no_recast",
      "response": "¡Qué interesante! ¿Qué más compraste?",
      "why_bad": "Error passes without correct form appearing anywhere"
    },
    {
      "label": "too_long",
      "response": "¡Qué bien! Los mercados en España son increíbles. Tienen tanta variedad de verduras frescas. Yo también voy mucho al mercado. ¿Encontraste algo especial?",
      "why_bad": "Four sentences — agent dominates the turn"
    },
    {
      "label": "register_mismatch",
      "response": "Es encomiable que hayas adquirido productos frescos en el mercado local. ¿Qué otras verduras encontraste?",
      "why_bad": "C1 register for an A2 learner"
    }
  ]
}
```

### Key structural rules

**`system_params` not rendered prompt.** The system prompt is built at eval
time via `build_system_prompt(fixture.system_params)`. This means all fixtures
automatically reflect prompt changes without manual updates.

**`conversation` includes prior context.** At minimum one prior agent turn
before the final learner utterance. Two prior turns is preferred — it makes
the conversation feel realistic and gives the model context to work with.

**`expected.response_text` is one valid example,** not the only correct
answer. Scoring checks for specific signals (recast present, sentence count,
etc.) rather than string matching against `response_text`.

**`negative_examples` are required** for all categories except cold start.
They serve two purposes: validating that scoring correctly penalizes bad
behavior, and providing DPO contrast pairs for fine-tuning.

---

## The Eight Categories

### 1. `single_error_recast` — 50 fixtures (10 per band)

**Tests:** Core recast behavior. Agent recasts one error naturally without
naming it, in the correct register, with exactly one follow-up question.

**What varies:** Error type, CEFR band, theme domain.

**Error types by band:**

| Band | Error types |
|------|-------------|
| A1   | gender_agreement, missing_article, verb_conjugation, ser_estar |
| A2   | gender_agreement, ser_estar, preterite_imperfect, verb_conjugation |
| B1   | ser_estar, preterite_imperfect, subjunctive_avoidance, por_para |
| B2   | subjunctive, por_para, register_slip, idiomatic_error |
| C1   | subjunctive, register_slip, idiomatic_error |

**Scoring signals tested:** `recast_present`, `recast_explicit`,
`register_correct`, `sentence_count_ok`, `question_count_ok`,
`L1_in_response`, `error_repeated`, `log_turn_called`

**Required negative examples:** explicit_correction, no_recast,
too_long, register_mismatch

---

### 2. `multi_error` — 30 fixtures (6 per band)

**Tests:** When the learner makes multiple errors, the agent recasts only
the highest-priority one and ignores the rest. `log_turn` must record all
errors observed, not just the one recast.

**Priority rule (applied consistently across all multi-error fixtures):**

```
1. Errors that impede comprehension        (highest priority)
2. High-frequency grammar patterns
   (ser/estar, gender agreement, preterite)
3. Low-frequency grammar
4. Vocabulary gaps
5. Register mismatches                     (lowest — often ignorable at A1/A2)
```

**Additional fields in `expected`:**

```json
"priority_error": "ser_estar_confusion",
"ignored_errors": ["missing_article"]
```

**Additional validation:** `log_turn.errors_observed` must contain ALL
errors present in the utterance, not just the priority one.

**Difficulty:** always `"multi_error"`

**Required negative examples:** recasts_wrong_error, recasts_all_errors,
explicit_correction, too_long

---

### 3. `l1_handling` — 25 fixtures (5 per band)

**Tests:** Agent never switches to English even when the learner uses it.
Response must be Spanish only, with enough contextual scaffolding to be
understood without translation.

**Four L1 scenarios:**

| Scenario | Learner behavior |
|----------|-----------------|
| `full_english` | Responds entirely in English |
| `mixed_switch` | Starts Spanish, switches mid-sentence |
| `english_word` | Uses one English word when vocabulary fails |
| `meta_question` | Asks "how do you say X?" in English |

**Additional validation:**
- Agent response must contain no English (langdetect check)
- `metadata.L1_used` must be `true`
- `log_turn.L1_used` must be `true`
- For `meta_question`: agent answers the vocabulary question in Spanish
  with the word embedded in a sentence, not as a translation

**Required negative examples:** switches_to_english, ignores_question,
over_explains, register_mismatch

---

### 4. `mimicry_cycle` — 15 fixtures (A1 only, 5 per stage)

**Tests:** A1-specific mimicry behavior. Agent offers a sentence, accepts
an imperfect repetition warmly, then extends by exactly one word.

**Three stages:**

| Stage | What happens |
|-------|-------------|
| `offer` | Agent offers a short sentence and invites repetition |
| `repeat` | Learner attempts (imperfect) repetition, agent accepts and extends |
| `extend` | Agent adds one word and invites another repetition cycle |

**Constraints:**
- Response must be very short (≤ 20 words total)
- `offer` stage must contain an explicit repetition invitation
  ("¿Puedes repetir?", "Repite conmigo", etc.)
- `repeat` stage must contain a warm affirmation —
  "muy bien" is banned; use "Exacto", "Así es", "Perfecto", "Eso es"
- `extend` stage must add exactly one new meaningful word to the sentence

**Required negative examples:** too_long, corrects_pronunciation,
skips_to_full_conversation

---

### 5. `cold_start` — 20 fixtures (4 per band)

**Tests:** Agent correctly infers the learner's level from four turns of
natural conversation and calls `update_learner_profile` with a reasonable
estimate. No explicit assessment — inference only.

**Different structure from other categories:**

```json
{
  "id": "cold_start_B1_consistent_signal_001",
  "type": "cold_start_sequence",

  "learner_turns": [
    {
      "utterance": "Normalmente trabajo desde casa.",
      "signals": {
        "L1_used": false,
        "fluency": "strong",
        "band_indicators": ["B1"]
      }
    },
    {
      "utterance": "Me gusta porque puedo organizar mi tiempo.",
      "signals": {
        "L1_used": false,
        "fluency": "strong",
        "band_indicators": ["B1"]
      }
    },
    {
      "utterance": "Aunque a veces es difícil separar el trabajo de casa.",
      "signals": {
        "L1_used": false,
        "fluency": "moderate",
        "band_indicators": ["B1", "B2"]
      }
    },
    {
      "utterance": "Sí, necesito más disciplina.",
      "signals": {
        "L1_used": false,
        "fluency": "strong",
        "band_indicators": ["B1"]
      }
    }
  ],

  "true_level": 0.62,
  "true_band": "B1",

  "expected_profile_update": {
    "production_level": { "min": 0.47, "max": 0.77 },
    "L1_reliance":      { "min": 0.0,  "max": 0.2  },
    "is_calibrated":    true
  },

  "metadata": {
    "cefr_band": "B1",
    "learner_production_level": 0.62,
    "errors_present": [],
    "L1_used": false,
    "fluency_signal": "moderate",
    "difficulty": "ambiguous",
    "tags": ["cold_start", "consistent_signal", "B1"]
  }
}
```

**Four calibration traps (one per band):**

| Trap | What it tests |
|------|---------------|
| `consistent_signal` | Clean, unambiguous signal throughout |
| `starts_hesitant_improves` | Learner warms up — agent must adjust upward |
| `overconfident_errors` | Complex structures but systematic errors — don't over-estimate |
| `heavy_L1_early` | English first two turns then switches — agent must reassess |

**Scoring:** Level estimate within `expected_profile_update.production_level`
range, `is_calibrated: true` set after turn 4.

No negative examples for cold start fixtures.

---

### 6. `register_boundary` — 20 fixtures (4 per band)

**Tests:** Agent maintains the correct register when the learner's utterance
is at the edge of their CEFR band or temporarily above/below it.

**Four traps:**

| Trap | Learner behavior | Agent must |
|------|-----------------|------------|
| `high_end_of_band` | Performing at top of stated band | Stay at band register, not drift upward |
| `low_end_of_band` | Struggling at bottom of stated band | Hold band register, anchor to profile |
| `band_crossing` | One utterance clearly above stated band (memorized phrase) | Not permanently adjust upward for one strong turn |
| `regression` | Drops below expected level mid-topic | Temporarily simplify without abandoning theme |

**Difficulty:** always `"ambiguous"`

**Required negative examples:** drifts_register_up, drifts_register_down,
over_simplifies

---

### 7. `tool_call_correctness` — 20 fixtures (4 per band)

**Tests:** `log_turn` is called after every turn, with arguments that
accurately reflect what the learner actually said. Alternates between
turns with errors and clean turns.

**What "accurate" means:**
- `learner_utterance` exactly matches the last user turn in conversation
- `errors_observed` is empty for clean turns, accurate for error turns
- `vocab_produced` contains only words the learner actually produced
- `fluency_signal` matches the realistic assessment of the utterance
- `L1_used` accurately reflects whether English appeared

**Key distinction from `single_error_recast`:** The conversational response
quality is secondary here. The primary signal is whether the tool call
arguments are correct. An otherwise good response with inaccurate
`log_turn` args fails this category.

**Required negative examples:** wrong_utterance_logged, invented_errors,
wrong_vocab, wrong_fluency_signal, missing_log_turn

---

### 8. `error_pattern_threshold` — 20 fixtures (4 per band)

**Tests:** Agent correctly determines when to call `log_error`. The
threshold is 3 occurrences of the same error pattern. Prior conversation
history makes repetition visible.

**Four scenarios:**

| Scenario | Occurrences | Expected tool calls |
|----------|------------|---------------------|
| `third_occurrence` | 3rd time same error | `log_turn` + `log_error` |
| `second_occurrence` | 2nd time same error | `log_turn` only |
| `different_contexts` | 3 different sentences, same pattern | `log_turn` + `log_error` |
| `declining_severity` | 3 occurrences but improving | `log_turn` + `log_error` with trend note |

**Structural note:** These fixtures need longer conversation history
(4-6 prior turns) to make the pattern repetition visible. The `conversation`
array will be longer than other categories.

**Required negative examples:** calls_log_error_too_early,
omits_log_error_at_threshold, wrong_pattern_identified

---

## Scoring

Each fixture contributes to two composite scores.

### Pedagogical score

Six binary signals averaged to 0.0–1.0:

| Signal | Source | Pass condition |
|--------|--------|----------------|
| `recast_present` | String match: `expected_recast` in response | Correct form appears |
| `recast_explicit` | Regex: correction phrases in response | None found (inverted) |
| `register_correct` | Heuristic: sentence length + subjunctive + rare words | Matches band |
| `sentence_count_ok` | Split on `.!?` | Count is 1, 2, or 3 |
| `question_count_ok` | Count `?` in sentences | Exactly 1 |
| `L1_in_response` | langdetect on response | Not English (inverted) |

**Hard failure — automatic 0.0:**
If `error_repeated` is true (agent reproduces the learner's error form),
pedagogical score is 0.0 regardless of other signals.

### Tool fidelity score

Two binary signals averaged to 0.0–1.0:

| Signal | Pass condition |
|--------|----------------|
| `log_turn_called` | `log_turn` present in response tool calls |
| `tool_args_correct` | `learner_utterance` matches conversation, `L1_used` accurate, error types valid |

### Composite score

```
composite = (pedagogical × 0.7) + (tool_fidelity × 0.3)
```

### Fine-tuning trigger thresholds

| Metric | Threshold | Action |
|--------|-----------|--------|
| `recast_present` | < 0.70 | Fine-tune |
| `recast_explicit` | > 0.20 | Fine-tune |
| `register_correct` | < 0.70 | Fine-tune |
| `L1_in_response` | > 0.15 | Fine-tune |
| `error_repeated` | > 0.05 | Fine-tune immediately |
| `sentence_count_ok` | < 0.75 | Prompt engineering first |
| `question_count_ok` | < 0.80 | Prompt engineering first |
| `tool_fidelity` | < 0.80 | Fine-tune tool call examples |

---

## Generation Pipeline

Fixtures are generated in three stages:

```
Stage 1 — Generate    Opus produces raw fixtures from prompt templates
Stage 2 — Review      Human approves / edits / rejects each fixture
Stage 3 — Consolidate Approved fixtures assembled into category JSON files
```

### Validation before review

Every generated fixture is validated automatically before entering the
review queue. Fixtures that fail validation are discarded and retried.

**Universal checks (all categories):**
- `expected_recast` appears in `response_text` (if errors present)
- Error form does not appear in `response_text`
- Sentence count is 1–3
- Exactly one question mark in response
- No explicit correction patterns
- `log_turn` present in tool calls
- "muy bien" not in response

**Category-specific checks documented per category above.**

### Review checklist

For each fixture during human review:

```
[ ] Learner utterance feels realistic for this CEFR band?
[ ] Prior conversation context is natural, not forced?
[ ] Expected response is genuinely good pedagogy?
[ ] Recast is natural — not a correction in disguise?
[ ] Tool call arguments accurately reflect the utterance?
[ ] Negative examples are clearly wrong for the stated reason?
[ ] Difficulty tag is accurate?
[ ] Tags are complete and correct?
```

### Target counts

| Category | A1 | A2 | B1 | B2 | C1 | Total |
|----------|----|----|----|----|-----|-------|
| single_error_recast | 10 | 10 | 10 | 10 | 10 | 50 |
| multi_error | 6 | 6 | 6 | 6 | 6 | 30 |
| l1_handling | 5 | 5 | 5 | 5 | 5 | 25 |
| mimicry_cycle | 15 | — | — | — | — | 15 |
| cold_start | 4 | 4 | 4 | 4 | 4 | 20 |
| register_boundary | 4 | 4 | 4 | 4 | 4 | 20 |
| tool_call_correctness | 4 | 4 | 4 | 4 | 4 | 20 |
| error_pattern_threshold | 4 | 4 | 4 | 4 | 4 | 20 |
| **Total** | **52** | **37** | **37** | **37** | **37** | **200** |

---

## Pydantic Schema Reference

The canonical schema lives in `eval/fixtures/schema.py`. Key types:

```python
Fixture              # all categories except cold_start
ColdStartFixture     # cold_start_sequence type

# Nested types
SystemParams         # profile + theme
ConversationTurn     # role + content
ExpectedOutput       # response_text, recast_form, tool_calls
ToolCallExpected     # name + arguments
FixtureMetadata      # cefr_band, difficulty, tags, ...
NegativeExample      # label, response, why_bad

# Cold start only
ColdStartLearnerTurn      # utterance + signals
ColdStartExpectedUpdate   # production_level range, is_calibrated
```

Loading fixtures with automatic validation:

```python
fixtures = load_fixtures(Path("eval/fixtures"))
# Raises ValidationError immediately if any fixture is malformed
```
