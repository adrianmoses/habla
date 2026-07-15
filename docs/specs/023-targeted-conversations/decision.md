# Decision Record: Targeted Conversations (Modes & Theme)

| Field | Value |
|---|---|
| id | 023 |
| status | implemented |
| created | 2026-07-15 |
| spec | [spec.md](./spec.md) |

---

## Context

Spec 023 emerged from a pre-#020 design discussion: before wiring the frontend's
dead surfaces, we wanted a reason to interact with it — the ability to steer a
session toward a debate, role-play, or interview instead of the random theme
pick every calibrated session gets today (`get_session_theme`,
`hable_ya/learner/themes.py:685`). Exploration surfaced the load-bearing fact
that reshaped the whole feature: the per-band theme pools are *already* full of
role-plays and debates, selected at random and never exposed as a choice. So the
work was less "build a conversation engine" and more "add a steering channel to
content that already exists."

Implementation confirmed the spec's central safety claim structurally. The
runtime prompt is assembled from independent blocks (`render.py:259-355`); only
the `## Topic:` block is filled from a `Theme`, while register / rubric / recast
/ `log_turn` are band-driven and separate. A "mode" therefore only needed to be
an alternative `Theme` factory — it cannot reach the pedagogical blocks. No
change to the renderer, the tool schema, the pipeline, or the learner-model
writes was required.

One constraint discovered during implementation shaped the data flow: `Theme`
and `SystemParams` are pydantic `_Strict` models (`extra="forbid"`,
`eval/fixtures/schema.py:21-43`), so the mode value could not be carried *on* a
`Theme`. It flows separately (`ConversationConfig` → `SessionPrompt.mode` →
`sessions.mode`), and a mode is only *realized as* a `Theme`.

## Decision

Add a per-session conversation configuration — a `mode`
(`open`/`debate`/`role_play`/`interview`) plus an optional freeform `topic` —
transported as `/ws/session` query params (`?mode=&topic=`), parsed fail-safe
(unknown mode → `open`, blank topic → `None`). Each mode is a `Theme` factory
(`hable_ya/learner/modes.py::build_mode_theme`) that fills only the Topic block;
the band continues to scale only the tutor's own language, plus per-band
`target_structures` elicitation hints for the two abstract modes
(`debate`/`interview`). The mode is honoured only once the learner is calibrated,
so the cold-start diagnostic is untouched. The chosen mode is persisted to a new
nullable `sessions.mode` column and surfaced through #019's `session_history`
read for #020.

The implementation matched the approved spec with a single, documented
structural refinement (the home of the `ConversationMode` type alias — see Spec
Divergence).

---

## Alternatives Considered

### How a mode shapes the prompt

**Option A — Mode as a `Theme` factory (chosen).** A mode produces a `Theme`
whose `domain`/`prompt`/`target_structures` fill the existing Topic block.
- Pros: confines all new prose to the one block that cannot affect corrections,
  register, or `log_turn`; zero renderer change; reuses the exact shape
  `render_system_prompt` already consumes.
- Cons: the mode's staging power is bounded by what a Topic-block prompt can
  express (no structural control over the rest of the prompt) — acceptable and,
  in fact, the point.

**Option B — Mode as a system-prompt rewrite / additional block.** Give each
mode its own prompt section or let it edit the assembled prompt.
- Pros: maximal control over the model's framing.
- Cons: reintroduces the risk the whole design exists to avoid — a mode could
  silently weaken the recast contract or suppress `log_turn`, degrading the
  learner model invisibly. Rejected.

**Chosen:** A. The safety property is structural, not a matter of careful
prompt-wording.

### Carrying the mode value

**Option A — Add a `mode` field to `Theme`/`SystemParams`.**
- Cons: both are `_Strict` (`extra="forbid"`); adding a field couples an
  eval-fixture schema to a runtime concept and forces every `Theme` construction
  site to consider it. Rejected.

**Option B — Flow the mode alongside the Theme (chosen).**
`ConversationConfig` → `SessionPrompt.mode` → `start_session(mode=)` →
`sessions.mode`. The Topic-block slug (`"<mode>: <topic>"`) is produced by the
factory setting `Theme.domain`, so `theme_domain` needs no separate plumbing.
- Pros: the pedagogical schema stays untouched; one nullable column carries the
  persisted state.

**Chosen:** B.

### `theme_domain` for moded sessions

**Chosen:** the factory sets `Theme.domain` to a `"<mode>: <topic>"` slug (bare
mode name when no topic), which `start_session` already writes verbatim
(`session.py:216`). No new plumbing; the slug is readable in #020 history and
keeps the cooldown query meaningful. (Spec OQ4, resolved default.)

### Per-band elicitation hints

**Chosen:** author `target_structures` per band for `debate` + `interview` only;
`role_play`/`open` ship empty (render omits the line when empty). The band's
register block already scales the tutor's own language; the hints add
scenario-specific elicitation targets where they matter most. (Spec OQ3.)

### Home of the `ConversationMode` type — the one divergence

**Option A — `hable_ya/pipeline/conversation.py`** (as the spec/plan wrote it).
- Cons: `hable_ya/learner/ingest.py` needs the type to annotate `start_session`;
  importing it from a `pipeline` module would introduce a learner→pipeline
  import (today the dependency runs pipeline→learner).

**Option B — `eval/fixtures/schema.py` beside `CEFRBand` (chosen).**
- Pros: that module is the established shared type-alias home already imported by
  both layers (`ingest.py` imports `CEFRBand` from it); no new cross-layer
  import. `ConversationConfig` + the parser stay in
  `hable_ya/pipeline/conversation.py` as planned.

**Chosen:** B — a structural refinement consistent with the plan's intent.

---

## Tradeoffs

- **Expressiveness bounded by the Topic block.** Modes cannot restructure the
  prompt — deliberately. A debate is staged by a Topic-block instruction, not by
  a dedicated debate persona. This is the price of the safety guarantee, and it
  is the right price.
- **One freeform `topic`, no structured sub-params.** Role assignment, stance,
  and formality are expressed implicitly in free text
  (`"Tú eres el camarero…"`), not as typed fields. Simpler channel and UI;
  slightly less reliable staging than explicit params would give. Structured
  sub-params remain an additive future enhancement (spec Non-Goal / OQ2).
- **Topic can outrun the learner's vocabulary.** By design there is no
  level-gating — an operator can request a debate on bioethics at A2, which is
  hard for the *learner* regardless of the tutor's register. Accepted per the
  product decision; a soft UI hint is left to #020.
- **Fixed at session start.** No mid-session switching (the system prompt is set
  once at `LLMContext` construction). Live switching was scoped out as much
  larger.
- **Live model behaviour not yet verified under keys.** The config→prompt→DB
  path is fully tested against real Postgres, but whether Claude reliably adopts
  each mode's posture in speech is confirmed only by the deferred keyed smoke.

---

### Spec Divergence

The implementation matched the spec's contract and all five resolved Open
Questions. One structural refinement, below.

| Spec Said | What Was Built | Reason |
|---|---|---|
| `ConversationMode` literal lives in `hable_ya/pipeline/conversation.py` (spec How §Approach; plan step 1) | The literal lives in `eval/fixtures/schema.py` beside `CEFRBand`; `ConversationConfig` + `parse_conversation_config` remain in `hable_ya/pipeline/conversation.py` as specified | `hable_ya/learner/ingest.py` annotates `start_session(mode=)` with the type; sourcing it from `schema.py` (already imported there for `CEFRBand`) avoids a new learner→pipeline import while keeping the runtime config object in the pipeline module |

No behavioural divergence. Every acceptance criterion is met; the cold-start
byte-identity tests pass unchanged, confirming the pedagogical path is untouched.

---

## Spec Gaps Exposed

- **`Theme`/`SystemParams` are `_Strict`.** The spec's "How" reasoned about mode
  flowing separately but did not name the `extra="forbid"` constraint that makes
  it mandatory rather than merely preferable. Minor; captured here.
- **No shared runtime-types module exists.** `eval/fixtures/schema.py` has become
  the de-facto home for runtime-shared type aliases (`CEFRBand`, `Theme`, and now
  `ConversationMode`) despite living under `eval/`. Not a blocker, but a
  candidate for a future `hable_ya/types.py` extraction if the coupling grows —
  worth a roadmap note, not a spec revision.

---

## Test Evidence

Gates and suite after the implementation commit (`22fcb50`), DB service up:

```
=== RUFF ===
All checks passed!
=== MYPY ===
Success: no issues found in 52 source files
=== NEW SPEC-023 UNIT TESTS (test_conversation.py + test_modes.py) ===
................................                                         [100%]
32 passed in 0.03s
=== FULL SUITE ===
410 passed, 9 warnings in 17.65s
```

Coverage added for spec 023 (+37 tests over the 373 baseline):
- **`tests/test_conversation.py`** — `parse_conversation_config` normalization:
  defaults to open, valid modes pass through, unknown → open, topic strip/blank
  → None, `open`+topic honoured, config is frozen.
- **`tests/test_modes.py`** — `build_mode_theme` per `(mode, band, topic)`: open
  delegates vs. steers; topic appears in prose; `"<mode>: <topic>"` slug; debate
  available at A1 (no gating); per-band hints differ for debate/interview;
  role_play has none at any band.
- **`tests/test_prompts.py`** — calibrated `debate` routes through the mode
  factory (`SessionPrompt.mode == "debate"`); calibrated `open`/no-topic keeps
  the random pick; uncalibrated **ignores** the config and stays cold-start
  (mode `"open"`, neutral theme, `COLD_START_INSTRUCTIONS` present) — plus the
  pre-existing byte-identity tests still pass.
- **`tests/test_log_turn_ingestion.py`** (DB) — `start_session` defaults
  `mode='open'`; explicit `mode='debate'` persists; the migration `CHECK`
  rejects an out-of-set value (`CheckViolationError`).
- **`tests/test_learner_api.py`** (DB) — `/api/learner/sessions` surfaces `mode`
  per session.

Deferred (documented, consistent with #016/#018/#019): the live keyed `wss://`
turn per mode confirming Claude adopts the posture and still emits exactly one
`log_turn` per turn — a full boot fail-fasts without the three cloud-API keys.
