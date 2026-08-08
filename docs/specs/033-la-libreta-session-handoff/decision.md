# Decision Record: La Libreta speaking-session handoff

| Field | Value |
|---|---|
| id | 033 |
| status | implemented |
| created | 2026-08-08 |
| spec | [spec.md](./spec.md) |

---

## Context

The spec arrived in an unusual shape for this repo: written against a contract
another application had already published (`la-libreta/docs/specs/012-deep-links/companion-interface.md`),
rather than raised here as a suspicion to be investigated. So there was no
premise to check, and the two things that shaped the work were the three
questions the spec deliberately left open and one defect the implementation
tripped over.

The spec was authored as **032**, on the same day #032 — *alembic manages
relational schema; AGE DDL should live elsewhere* — entered `ROADMAP.md`. Spec
ids and roadmap feature ids share one namespace here (every other spec
directory matches its row), so the two collided. The La Libreta feature was
renumbered to **033**, moving the item that had not been published yet rather
than amending a revision-history entry that already names #032 correctly.

The three open questions were answered rather than deferred, because all three
were load-bearing: each one, answered the obvious lazy way, silently breaks a
guarantee the spec makes elsewhere.

**The one discovery.** Two of the tests written for this spec passed in
isolation and failed in the full suite with empty log capture. The cause was
not a test artifact: `hable_ya/db/alembic/env.py` called
`logging.config.fileConfig(...)`, whose `disable_existing_loggers` parameter
defaults to `True` — it sets `disabled = True` on every logger that already
exists and is not named in `alembic.ini`. That file runs *inside the live app*:
`api/main.py`'s lifespan calls `upgrade_to_head()` after the routers have been
imported and their module loggers created. So on every production boot, every
logger under `hable_ya.*` and `api.*` was permanently silenced the moment
migrations ran — session auth refusals, provider errors, ingest failures,
none of it reached the log. Confirmed directly:

```
$ uv run python -c "
import logging; log = logging.getLogger('hable_ya.api.session')
print('before:', log.disabled)
from logging.config import fileConfig; fileConfig('alembic.ini')
print('after fileConfig:', log.disabled)"
before: False
after fileConfig: True
```

It is fixed here rather than filed, because this spec's acceptance criteria
require callback and lifecycle failures to *stay diagnosable* — a criterion
that was unsatisfiable while the fix was outstanding. `latency_metrics.py`
already carried a comment about log output being "unreliable to capture once a
global `logging.disable` is in effect", which appears to be this same effect
observed and worked around rather than diagnosed.

## Decision

**`POST /api/sessions` creates a durable *handoff*, not a session.** The row
exists before microphone consent and before any WebSocket, so a deep link
survives a reload and a bookmark without ever having claimed that paid work
began. Idempotency on `(source, source_ref, source_date)` is a database unique
index driving an `INSERT … ON CONFLICT DO NOTHING` + follow-up `SELECT`, so two
concurrent requests resolve to one row without a lock.

**The two credentials never touch.** `LA_LIBRETA_API_TOKEN` opens exactly one
door — creating a handoff — and is compared in constant time, fails closed when
unset, and never reaches the browser. Reading and completing a handoff use the
#016 learner secret like every other `/api` surface. `/session/:id` is a real
route with pre-session, not-found and needs-token states, and it starts nothing
until the learner presses start.

**The handoff steers the prompt; it does not become it.** `handoff_theme()`
replaces the `## Topic:` block so one session has one topic, and the verbatim
consigna is appended last inside `<consigna>` tags under a notice telling the
model, in the prompt, that the block is learner material and not a directive.
The browser sends only the opaque id.

**Completion is an action, and the callback is best-effort.** A conditional
`UPDATE … WHERE completed_at IS NULL` makes exactly one caller the winner, and
only that caller queues the callback. Delivery is validated against an HTTPS
origin allowlist that defaults to empty, re-checks DNS at send time, disables
redirects, retries once on `5xx`/transport failure and never on `4xx`.

---

## Alternatives Considered

### Open Question 1: what event means "completed"?

The upstream contract says "when the user marks the session complete"; the UI
had only close/exit and WebSocket teardown.

**Option A — bind completion to session teardown.** No new UI, and it fires
without the learner having to remember anything.
- Pros: zero interface surface; can never be forgotten.
- Cons: disconnect, provider error, idle timeout and #016 preemption all run
  the same teardown. Every one of them would report practice that did not
  happen, to a system whose entire purpose is activity tracking. The spec calls
  this out and it is not a marginal case — a dropped connection is ordinary.

**Option B — an explicit "Terminar práctica" action, distinct from "Cerrar".**
`POST /api/sessions/:id/complete`, only present in a handoff-backed session.
- Pros: the reported event is the one La Libreta actually asked for; the
  learner keeps a way to leave without reporting.
- Cons: a learner who finishes and closes the tab reports nothing. Under-report
  rather than over-report.

**Chosen: B.** Under-reporting is recoverable — the learner can redo the
prompt, and La Libreta's tracking is simply blank. Over-reporting is not: it
tells someone they practised when they did not, and there is nothing in the
data afterwards to distinguish it.

### Open Question 2: how does the WebSocket identify the handoff?

**Option A — the browser passes the prompt text on the socket URL.** Simplest;
no server lookup.
- Pros: no second read; the client already has the text rendered.
- Cons: makes the browser authoritative over what the tutor is told. Editing a
  URL would rewrite the consigna, and the "verbatim" guarantee would mean
  "verbatim as of whatever the client last sent".

**Option B — an opaque `?handoff=<id>` resolved server-side after auth.**
- Pros: the id is useless without the session token; the payload is re-read
  from the row that La Libreta wrote; nothing of the prompt appears in a URL or
  an access log.
- Cons: one extra query per session start, and an unknown id needs a defined
  behaviour.

**Chosen: B**, the spec's stated preference. An unknown id degrades to an
ordinary session rather than failing the handshake — the pre-session view is
where a stale link is supposed to be reported, and turning it into a connection
error at the socket would report it in the wrong place and in the wrong words.

### Open Question 3: what constrains callback destinations?

**Option A — fetch whatever `callbackUrl` says, with IP-range checks.**
- Pros: no configuration; works the moment La Libreta sends a URL.
- Cons: it is an SSRF primitive with a denylist in front of it, and denylists
  lose to redirects, DNS rebinding, and the next address range someone
  remembers about.

**Option B — an explicit HTTPS origin allowlist defaulting to empty, plus
range checks as defence in depth.**
- Pros: a single-operator integration has exactly one legitimate destination.
  Nothing is fetched until an operator names it.
- Cons: a deployment that configures the token but forgets the allowlist gets
  handoffs that work and callbacks that are refused.

**Chosen: B.** The cost lands in the right place — the refusal is logged by
handoff id, and accepting handoffs while delivering no callbacks is a coherent
posture rather than a broken one, which is why the allowlist is deliberately
*not* part of the startup fail-fast.

### Where the handoff enters the prompt

**Option A — put the consigna in `Theme.prompt`** (the `## Topic:` block's
body), which is where mode/topic steering already goes.
- Pros: one mechanism, no new prompt section.
- Cons: `Theme.prompt` is rendered as instructions to the model. External text
  in that position is an injection with a nice frame around it.

**Option B — a Habla-authored `Theme.prompt` that *points at* a delimited block
appended after the system instructions.**
- Pros: the untrusted text is last, tagged, and explicitly demoted in prose the
  model reads; Habla's own rules are never downstream of it.
- Cons: two places to keep in sync, handled by having the theme reference the
  section title constant.

**Chosen: B.** `target_structures` is the one exception — it carries La Libreta
strings into the rendered `Target structures:` line, because that line is a
comma-joined list of terms, not a position from which instructions are read.

### Cold start + handoff

Only one option was ever sensible for the topic (the handoff wins — a learner
who followed a link to practise one consigna must get that consigna), but the
cold-start block bundles two unrelated things: a four-step diagnostic *ladder*
that would drag the session away from the task, and the instruction to report
`cefr_band` on every `log_turn`, which placement needs. `COLD_START_INSTRUCTIONS`
was split into `COLD_START_LADDER` + `BAND_ESTIMATE_INSTRUCTION` and recomposed,
so a first-ever session arriving by deep link keeps its consigna *and* stays
placeable. The recomposition is byte-identical, so `tests/test_prompts.py`'s
existing identity assertions still describe one string.

---

## Tradeoffs

- **Under-reporting practice** is accepted, per Open Question 1 above.
- **A configured-but-unallowlisted callback fails at create time with a `400`**,
  which surfaces as a La Libreta-side error rather than a Habla-side warning.
  That is the intended direction: the alternative is accepting the handoff and
  silently never calling back.
- **DNS rebinding is narrowed, not eliminated.** `resolve_public_addresses`
  refuses a name that answers with any non-global address, but the socket
  resolves again when it connects. Closing that window entirely means pinning
  the resolved IP through a custom transport and losing ordinary TLS hostname
  verification. The residual attack requires control of an operator-configured
  DNS zone — at which point the approved destination is already the attacker's.
  Documented in the function's docstring rather than left as an unstated gap.
- **Frontend tests cover logic, not rendering.** `web/` runs vitest in the node
  environment with no jsdom (spec #020 Open Question 4), so the deep link is
  tested through its state machine, its path parser, its request builder and
  its wire format. `renderableFields()` exists as the seam that makes "rendered
  verbatim" a testable claim; what a browser paints is still unasserted.
- **`hable_ya/handoff/` is a fourth top-level package** alongside `learner/`,
  `pipeline/` and `runtime/`. Justified by having three genuinely separate
  concerns (row model, prompt quarantine, outbound delivery) and one of them
  being the only outbound-fetch surface in the codebase.
- **`httpx` is now a direct dependency.** It was already present transitively
  via both `anthropic` and `openai`, but runtime code imports it now, and a
  transitive dependency is not a promise.

---

### Spec Divergence

| Spec Said | What Was Built | Reason |
|---|---|---|
| id `032` | id `033` | Collided with the roadmap's #032 (alembic/AGE), published the same day. Renumbering the unpublished item keeps the existing entry and its revision-history note accurate. |
| `400` for an invalid body | `400`, via manual parsing inside the route | FastAPI answers `422` for a typed body parameter. An app-level `RequestValidationError` handler would have changed `/api/learner` too, so the body is read and validated inside `create_session`. The route's OpenAPI request schema is the cost. |
| "The persisted handoff includes … callback delivery state" | Added `callback_last_error TEXT` to the same migration | The spec named attempts and delivery; a failure with no recorded reason is not diagnosable, which the logging criterion also asks for. Amended in place rather than as a second revision — `6a7b8c9d0e1f` has never shipped. |
| Nothing about logging configuration | Fixed `disable_existing_loggers` in `hable_ya/db/alembic/env.py` | Pre-existing defect, out of scope by topic and squarely in scope by consequence: the "failures remain diagnosable" criterion could not hold while every application logger was disabled at boot. |

Everything else matches the spec as written, including the wire contract, both
status codes, first-payload-wins replay semantics, the four `/session/:id`
states, the retry policy, and the separation of the two credentials.

---

## Spec Gaps Exposed

1. **The spec assumes `callbackUrl` validation and delivery share one notion of
   "allowed".** They cannot: the origin is approved when the row is written and
   the address is resolved when the callback is sent, and the spec's sentence
   "DNS resolution at delivery must not provide a rebinding path around the
   policy" is the only place that gap is acknowledged. The implementation
   splits it into two named functions so the two moments are visible; a future
   revision should say so directly.

2. **Nothing in the spec covers what happens to a handoff-backed session that
   is preempted** by #016's newest-wins policy. Today: the incumbent's socket
   closes, the handoff keeps its `started_at` and stays incompletable until
   someone opens the deep link again. That is defensible but undocumented.

3. **`sessions.theme_domain` now carries `la-libreta: <sourceRef>` values**,
   which feed the theme-cooldown window. A learner practising several La
   Libreta prompts in a row consumes cooldown slots with labels that are not
   themes. Harmless at current volumes; worth a look if handoffs become the
   common path.

4. **A roadmap-level gap the collision revealed**: nothing enforces that a new
   spec directory takes an unused id. `tests/test_doc_paths.py` checks that
   named paths exist, not that ids are unique. A candidate for a small addition
   to that file.

---

## Test Evidence

Full Python suite, frontend suite, lint, types, and production build:

```
$ uv run ruff check .
All checks passed!

$ uv run mypy hable_ya api
Success: no issues found in 62 source files

$ uv run pytest -q
659 passed, 6 deselected, 9 warnings in 19.74s

$ npm --prefix web test
 ✓ src/voice/client.test.ts (4 tests)
 ✓ src/lib/format.test.ts (44 tests)
 ✓ src/lib/api.test.ts (7 tests)
 ✓ src/lib/handoff.test.ts (11 tests)
 Test Files  4 passed (4)
      Tests  66 passed (66)

$ npm --prefix web run build
✓ 52 modules transformed.
dist/assets/index-DUQqT-zD.js   190.98 kB │ gzip: 59.57 kB
✓ built in 373ms
```

New coverage, by file:

```
$ uv run pytest tests/test_external_sessions_api.py tests/test_external_sessions_db.py \
      tests/test_handoff_callback.py tests/test_handoff_prompt.py \
      tests/test_handoff_startup.py -q
83 passed
```

### Defect reintroduction (spec "How", step 6)

The spec asks for the duplicate-create race and the duplicate-completion defect
to be put back, to show the tests fail. Both were, plus the logging defect this
implementation found.

**Duplicate completion** — `mark_completed`'s `AND completed_at IS NULL` removed:

```
FAILED tests/test_external_sessions_db.py::test_completion_transitions_exactly_once
FAILED tests/test_external_sessions_db.py::test_concurrent_completions_transition_once
E       assert 5 == 1
E        +  where 5 = [True, True, True, True, True].count(True)
```

**Duplicate create** — `ON CONFLICT DO NOTHING` replaced with check-then-act:

```
FAILED tests/test_external_sessions_db.py::test_concurrent_creates_produce_one_row
E   AssertionError: the race raised instead of resolving: [
      UniqueViolationError('duplicate key value violates unique constraint
      "external_session_handoffs_source_source_ref_source_date_key"'), … ×3]
```

This one is the reason the exercise was worth doing rather than performing.
**The first version of that test passed against the broken implementation.**
Each racer called `pool.acquire()` inside its own task, so the losers blocked
on connection establishment and the "concurrent" creates quietly serialized —
a race-shaped test that could not observe a race. It now acquires and
establishes all four connections before the gather and releases them through an
`asyncio.Barrier`, and the injected defect fails it as shown.

**Silenced loggers** — `disable_existing_loggers=False` reverted:

```
FAILED tests/test_migration_chain.py::test_running_a_migration_does_not_silence_the_app_loggers
E   AssertionError: an alembic run disabled an application logger — check
    `disable_existing_loggers=False` in hable_ya/db/alembic/env.py
E   assert True is False
E    +  where True = <Logger hable_ya.api.session (WARNING)>.disabled
```

All three defects were reverted and the suite returned to green before this
record was written.
