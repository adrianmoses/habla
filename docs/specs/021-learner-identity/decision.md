# Decision Record: Learner Identity

| Field | Value |
|---|---|
| id | 021 |
| status | implemented |
| created | 2026-08-04 |
| spec | [spec.md](./spec.md) |

---

## Context

#020 wired every dead surface in the SPA to live data and stopped at two: the
hardcoded `<em>Ana</em>` in Home's hero and the hardcoded `A` in the avatar,
both left with explicit `PLACEHOLDER … spec #021` comments because
`learner_profile` had no name to read. This spec closed that, and settled the
question underneath it — whether the backend ever grows a user concept — as a
costed non-goal rather than an open item.

Three things shaped the work beyond what the spec captured.

**The spec's own code sketch contradicted its resolved Open Question.** OQ3
resolved validation as "trim, then reject if the *trimmed* value exceeds 40
characters". The Approach section then sketched
`display_name: str | None = Field(default=None, max_length=40)`, which
validates the raw string — so `"  <40-char name>  "` would have 422'd. Caught
while planning, not while debugging; the rule went into the pure helper and the
Pydantic bound became a loose outer guard.

**A testing precedent the spec cited does not exist.** The Testing Approach
called for an `upgrade()`/`downgrade()` round-trip "the existing migration
tests' pattern". There is no such pattern — `test_init_db.py` and `test_db.py`
only assert idempotency and table presence. The round-trip written here is the
suite's first, which means every migration before this one has a `downgrade()`
that has never been executed.

**Browser verification was initially skipped on a false premise, then run —
and it found a defect.** The first pass of this record claimed Playwright was
unavailable and filed that as a spec gap. That was wrong: Playwright 1.56.0 is
installed via pipx at `/home/adrian/.local/bin/playwright` with browsers in
`~/.cache/ms-playwright`. The detection only checked `node_modules/.bin`,
`web/node_modules/.bin`, the default `python3`, and `npx --no-install` — none of
which see a pipx user install. #020's "Playwright is available locally" was
correct all along.

Running the three checks then falsified one of the spec's own claims. OQ3
justified the 40-character bound as fitting "the 96px serif greeting without
wrapping past two lines at the SPA's `maxWidth: 520`". `maxWidth: 520` is on
the `<p>` beneath the hero, not on the `<h1>`, which spans the full `1.2fr`
grid column — a 40-character name rendered **five** lines and pushed the CTA
below the fold. `greetingLine` now greets by first name only. This is exactly
the class of defect #020 credited browser verification with catching, found in
exactly the way #020 predicted, and it very nearly shipped behind a detection
error.

## Decision

Ship the six changes as specced: a nullable `learner_profile.display_name`
column; the field on `GET /api/learner`, read off the raw profile row; a
`PATCH /api/learner` behind the same Bearer gate — the first write on the
production HTTP surface; `apiPatch` plus two pure render helpers in the SPA;
Home and AppShell consuming them with both placeholder comments deleted; and a
`Tu nombre` panel in Ajustes.

The name is UI-only by construction, not by convention. It never touches
`LearnerProfileSnapshot`, so it has no path to `render.py`'s `## Learner`
block, and `hable_ya/pipeline/` ends the implementation with an empty diff. It
never reaches cypher, so `graph.py`'s `_IDENT_RE` filter never has to be
trusted with learner-supplied free text.

Multi-user accounts are recorded in `OVERVIEW.md` and `ARCHITECTURE.md` as a
decided non-goal with the reversal cost attached, so the question stops being
re-derived from the schema at the top of each planning turn.

---

## Alternatives Considered

### Where the 40-character bound lives

**Option A: `Field(max_length=40)` on the request model** (the spec's sketch)
- Pros: one line; FastAPI produces the 422 with a structured error body for free.
- Cons: validates the raw string, so trailing spaces count against the bound —
  contradicting OQ3, which bounds the trimmed value. Untestable without going
  through HTTP.

**Option B: the bound inside `normalize_display_name`, with a loose Pydantic guard**
- Pros: the product rule is one pure function, unit-tested over trim / limit /
  control-character / Unicode cases with no DB and no HTTP. `"  Ana  "` behaves
  as OQ3 says it should.
- Cons: two places name a number (200 on the model, 40 in the helper); the 422
  body is a plain string detail rather than Pydantic's structured error.

**Chosen: B.** OQ3 is the contract and the sketch was shorthand for it. The
loose `max_length=200` stays as a guard against buffering something absurd, and
`test_identity.py::test_trimming_happens_before_the_length_check` pins the exact
case Option A got wrong.

### What `PATCH {}` means

**Option A: treat a missing key as `null` — clear the name**
- Pros: no extra code; `default=None` already does it.
- Cons: an empty body silently wipes the only field. Indistinguishable from
  `{"display_name": null}`, so a malformed client request destroys data.

**Option B: require the key, 422 otherwise**
- Pros: `{}` (a mistake) and `{"display_name": null}` (an intent) stay distinct.
- Cons: two lines of `model_fields_set` inspection; slightly unusual for PATCH,
  where an absent field conventionally means "leave alone" — which here is
  indistinguishable from "no-op request".

**Chosen: B.** With exactly one mutable field, "leave alone" and "empty body"
collapse into the same request, and the destructive reading is the wrong default.
The spec did not address this.

### `greetingLine`'s return shape

**Option A: return one string** (the spec's wording: "the greeting with the name")
- Pros: trivial to test; matches the spec literally.
- Cons: flattens the hero. Home renders the name in a clay-deep `<em>` after a
  `<br/>`; a single string loses both, turning a 96px two-line serif hero into
  one flat sentence — a visual regression introduced by a helper meant to be
  cosmetic.

**Option B: return `{ lead, name }`**
- Pros: keeps the existing hero exactly; still one pure, dependency-free helper;
  the null case is still directly assertable (`lead` capitalized and terminated,
  `name` null).
- Cons: a structured return for what reads like a string function.

**Chosen: B**, confirmed with the human before implementation. The spec was
describing behaviour, not prescribing a signature, and the behaviour it
describes is preserved.

### What the hero does with a long name

Forced by browser verification: a 40-character name rendered five lines and put
the CTA below the fold.

**Option A: greet by first name only**
- Pros: two lines at any length; reads the way a person greets; the full name is
  still stored, still edited in Ajustes, still the source of the avatar initial.
- Cons: the hero shows something other than what was typed.

**Option B: shrink the hero font past a length threshold**
- Pros: renders the full name verbatim.
- Cons: an inconsistent hero scale — the app's most deliberate typographic
  moment becomes a function of name length.

**Option C: truncate with an ellipsis in the greeting**
- Pros: predictable single line.
- Cons: shows the learner a clipped version of their own name, which is a worse
  version of Option A's cost with none of its readability.

**Option D: lower the stored bound below 40**
- Pros: no render change.
- Cons: rejects legitimate full names, and reverses an approved Open Question to
  work around a layout bug.

**Chosen: A**, confirmed with the human. The bound stays where OQ3 put it; only
the hero's use of the value changes.

### Where AppShell gets the name

**Option A: `useLearnerProfile()` inside AppShell**
- Pros: one place, cannot be forgotten; consistent with #020's per-surface
  fetching.
- Cons: a second `/api/learner` GET on Home, Progreso and Ajustes, which already
  fetch it — `useApi` has no cache by #020's explicit decision.

**Option B: a `displayName` prop threaded from each route**
- Pros: no duplicate reads on the three screens that already have the profile.
- Cons: Historial would need a fetch it does not currently make, and any screen
  that forgets the prop renders a blank avatar — a silent failure that looks
  identical to the legitimate "no name set" state.

**Chosen: A.** On a single-tenant deployment an extra authenticated read of a
five-query payload is cheaper than a failure mode that is invisible by
construction.

### Verifying the migration's `downgrade()`

**Option A: add `downgrade_to()` beside `upgrade_to_head()` in `hable_ya/db/migrations.py`**
- Pros: symmetrical, tidy test.
- Cons: production API with no production caller, existing only for a test.

**Option B: drive alembic directly from the test**
- Pros: no production surface added; the test owns its own machinery.
- Cons: duplicates `_build_config`'s three lines; the test must restore head
  itself or poison every test after it.

**Option C: verify by hand, note the divergence**
- Pros: zero code.
- Cons: an unexecuted `downgrade()` is a claim, not a fact.

**Chosen: B**, confirmed with the human. The restore runs in a `finally` so a
failing assertion cannot leave the session database half-migrated.

---

## Tradeoffs

**What this optimises for: the name having no route into the tutor prompt.**
That is why the read goes through a raw `fetchrow` rather than the snapshot the
rest of the payload uses, and it costs a small inconsistency — `display_name`
is the one field in `profile_payload` not derived from
`LearnerProfileRepo.get()`. The payoff is that "the name never reaches
`render.py`" is enforced by there being no code path, not by a comment asking
implementers to be careful. `git diff --stat -- hable_ya/pipeline/` is empty and
the 37 prompt tests pass unmodified.

**What it gives up: any second profile field is now slightly awkward.**
`ProfileUpdate` has one field and the endpoint's `model_fields_set` check is
written for exactly that shape. A second field means either per-field presence
handling or revisiting the `{}` decision. The spec's Non-Goals rule out a second
field for now, and the column pattern itself is cheap to extend.

**What it gives up: three redundant `/api/learner` reads per session.** Home,
Progreso and Ajustes each fetch the profile twice now (once for the screen, once
for AppShell's avatar). Accepted deliberately; the alternative trades it for a
silent-blank-avatar failure mode. If the SPA ever grows a shared profile store
this reverts to one fetch with no change to either call site.

**What it gives up: shared-secret posture is now read *and* write.** A token
holder could already open `/ws/session` and spend real money on the metered
APIs, so this is not an escalation of what the secret grants — but the blast
radius of a leaked token now includes mutating stored state. There is no CSRF
vector (header credential, not a cookie), and the write is idempotent and
bounded to one 40-character field.

---

### Spec Divergence

| Spec Said | What Was Built | Reason |
|---|---|---|
| `display_name: str \| None = Field(default=None, max_length=40)` | `max_length=200` on the model; the 40-character bound enforced in `normalize_display_name` on the trimmed value | The sketch contradicted the spec's own OQ3, which bounds the *trimmed* value. Following the sketch would 422 a valid padded name. |
| PATCH accepts `{"display_name": "…"}` (empty body unaddressed) | `{}` is a 422; only an explicit `null` clears | Unspecified. With one mutable field, treating an empty body as "clear" makes a malformed request destructive. |
| `greetingLine(time, name)` → "the greeting with the name" | Returns `{ lead, name }` | A flat string would drop the clay-deep `<em>` and the line break from the hero — a visual regression from a cosmetic helper. Confirmed with the human before building. |
| OQ3: 40 characters "fits the 96px serif greeting without wrapping past two lines at the SPA's `maxWidth: 520`" | 40 characters still stored and editable, but the **hero greets by first name only** | The premise was false. `maxWidth: 520` is on the paragraph beneath the hero, not the `<h1>`, which spans the full `1.2fr` column. Browser verification measured 5 lines and a CTA below the fold; first-name-only holds two lines at any length. |
| Migration round-trip test follows "the existing migration tests' pattern" | New `tests/test_learner_display_name_migration.py` drives alembic directly | No such pattern exists in the suite. This is its first upgrade→downgrade test. |
| `avatarInitial(name)` → `Array.from(name)[0].toUpperCase()` | Same, plus an empty-string guard so `''` behaves as "unset" | `''` and `null` should render identically; the sketch would return `''` anyway, but the guard makes it explicit and testable. |

Everything else was built as written. All 13 acceptance criteria are addressed;
all three resolved Open Questions were implemented at their approved
resolutions (`PATCH /api/learner`; greeting-alone with a blank circle; trim /
≤40 / no `Cc`-`Cf` / empty clears).

---

## Spec Gaps Exposed

1. **The Approach section's code sketches are not checked against the resolved
   Open Questions.** #021's `max_length=40` directly contradicted OQ3 two
   sections earlier. Cheap to catch at approval; expensive if it had been typed
   in verbatim and shipped. Worth a pass over future specs whose sketches encode
   a rule stated elsewhere in prose.

2. **No migration in this repo has an executed `downgrade()`.** #021's is the
   first. `20c019e280a9`, `bd55d203ae25`, `99507a1b3027` and `c7f3a9b21d84` all
   have `downgrade()` bodies that have never run — including
   `bd55d203ae25`'s, which would have to drop the AGE graph. **Roadmap
   candidate:** extend the round-trip pattern down the whole chain, or delete
   the `downgrade()` bodies and say the migrations are forward-only.

3. **OQ3's layout justification was measured against the wrong element**, and
   nothing in the acceptance criteria would have caught it. The criteria say a
   named learner "sees it in Home's greeting" — true at five lines with the CTA
   off-screen. The constraint that actually mattered lived only in OQ3's
   *rationale*, where it was never turned into a checkable criterion. **Worth
   generalising:** when a spec justifies a numeric bound with a layout claim,
   that claim belongs in the acceptance criteria, not the rationale.

4. **Tooling-availability claims in a spec should be verified, not inherited.**
   This record's first pass asserted Playwright was unavailable and filed it as
   a gap; the detection was wrong (a pipx install at `~/.local/bin`, invisible to
   a `node_modules` / `npx --no-install` / default-`python3` check). The cost was
   nearly shipping the hero defect above. A negative tooling result deserves the
   same scepticism as a negative test result — check where the tool would
   actually be, not only where it usually is.

5. **The spec did not say where AppShell reads the name from**, and #020's
   deliberate no-cache hook design makes an avatar in shared chrome cost a
   duplicate fetch on every screen. Not a defect at this scale. **Roadmap
   candidate:** a shared profile read for the SPA, if a second consumer of
   profile-wide data ever lands in the shell.

6. **`ARCHITECTURE.md` remains `status: inferred`** and its component map still
   describes stubs and the deleted `finetune/` package. Only the tenancy bullet
   was corrected here — the rest was out of scope and is still stale.

---

## Test Evidence

**Full pytest suite (DB up) — 469 before this spec, +55 here:**

```
$ uv run pytest -q
524 passed, 9 warnings in 18.48s
```

**The new pure-rule and migration tests:**

```
$ uv run pytest tests/test_identity.py tests/test_learner_display_name_migration.py -q
.................................                                        [100%]
33 passed in 0.36s
```

**The new endpoint tests (22 of `test_learner_api.py`'s 48):**

```
$ uv run pytest tests/test_learner_api.py -q -k "display_name or patch or singleton"
22 passed, 26 deselected, 1 warning in 2.83s
```

**Prompt byte-identity guard — unmodified tests, plus an empty pipeline diff:**

```
$ uv run pytest tests/test_prompts.py -q
.....................................                                    [100%]
37 passed in 0.05s

$ uv run pytest -q -k "cold_start or byte_identical or prompt_identity or snapshot"
10 passed, 514 deselected, 1 warning in 2.55s

$ git diff --stat -- hable_ya/pipeline/
(empty)
```

**Lint and types:**

```
$ uv run ruff check hable_ya/ api/ eval/agent/ tests/ scripts/
All checks passed!

$ uv run mypy hable_ya/ api/ eval/agent/
Success: no issues found in 65 source files
```

**Frontend — 51 Vitest cases (37 before this spec) and the build gate:**

```
$ cd web && npm test
 ✓ src/lib/api.test.ts (7 tests) 4ms
 ✓ src/lib/format.test.ts (44 tests) 6ms
 Test Files  2 passed (2)
      Tests  51 passed (51)

$ npm run build      # tsc --noEmit && vite build
✓ 50 modules transformed.
dist/assets/index-o1HPtCy3.js   184.95 kB │ gzip: 58.21 kB
✓ built in 398ms
```

**End-to-end over real HTTP against the dev Postgres.** The learner router was
mounted on a bare FastAPI app with a real pool and a real Bearer token,
deliberately bypassing `api.main`'s lifespan so the check cost nothing on the
metered APIs:

```
--- 1. unset state ---
  GET 200  display_name = None
--- 2. set (with padding) and read back ---
  PATCH 200  -> {'display_name': 'Ángela'}
  GET 200    display_name = 'Ángela'  (trimmed)
--- 3. auth fails closed on the write ---
  no token:    401
  wrong token: 401
--- 4. validation, and nothing partially persisted ---
  41 chars:    422
  control chr: 422
  RTL over.:   422
  empty body:  422
  GET 200    display_name = 'Ángela'  (unchanged)
--- 5. 40 chars is accepted ---
  PATCH 200
--- 6. whitespace clears it ---
  PATCH 200  -> {'display_name': None}

ALL E2E CHECKS PASSED
```

**Migration against the real dev database** (not just the test database):

```
$ uv run python -c "asyncio.run(upgrade_to_head())"
INFO  [alembic.runtime.migration] Running upgrade c7f3a9b21d84 -> f1e6a742b90c, learner_display_name
migrated to head
```

**Browser verification (Playwright 1.56.0, chromium, 1440×900)** — the three
checks from the spec's manual verification section, against the real learner
router and a seeded dev database. Run *after* the first pass of this record
wrongly concluded the tool was unavailable; check 3 failed on the first run at
five lines, and passes here after `greetingLine` switched to first-name-only:

```
1. EMPTY STATE
   hero   = 'Buenas noches.'
   avatar = ''
   blank avatar navigates -> http://localhost:5173/ajustes

2. SET IN AJUSTES -> HOME (no reload)
   confirmation shown = True
   url    = http://localhost:5173/
   hero   = 'buenas noches,\nÁngela.'
   avatar = 'Á'

3. 40-CHARACTER NAME AT maxWidth 520
   hero height = 196px, line-height = 98px
   rendered lines = 2
   hero = 'buenas noches,\nMaximiliana.'
   CTA top = 693px (viewport 900px)

CONSOLE ERRORS: none
```

The first run of check 3, before the fix:

```
3. 40-CHARACTER NAME AT maxWidth 520
   hero height = 490px, line-height = 98px
   rendered lines = 5
   hero = 'buenas noches,\nMaximiliana Guadalupe Fernández Ochoa Ru.'
```

This closes the two acceptance criteria that could not be settled by unit tests:
*"A learner with no name set sees a greeting with no name and a blank avatar
circle — never a fabricated name, never the literal `null`"* (check 1, including
that the blank circle still navigates), and *"Navigating from Ajustes back to
Home shows the new name (no manual reload)"* (check 2 — `performance.now()`
confirms the document was never reloaded).
