# Spec: Learner Identity

| Field | Value |
|---|---|
| id | 021 |
| status | draft |
| created | 2026-08-04 |

---

## Why

The app greets a person who does not exist. `Home.tsx:141` renders a hardcoded
`<em>Ana</em>` under the time-of-day greeting, and `AppShell.tsx:115` renders a
hardcoded `A` in the avatar circle. Both carry explicit `PLACEHOLDER … spec
#021` comments left by #020, which deliberately wired every *other* dead
surface to live data and stopped at these two because the learner model has no
name to read.

The gap is real, not cosmetic. #020's whole argument was that the product
*felt* like it neither logged sessions nor adapted, because a fully-working
backend loop had no read path. It closed that for band, history, errors, vocab
and themes — and then the first thing the learner sees on every page load is
still a fabricated name belonging to someone else. It is the last invented
claim on the surface, and the same class of defect #020 removed everywhere
else.

Underneath it sits a question the roadmap has deferred four times: the backend
has no user concept at all. `learner_profile` is a schema-enforced singleton
(`id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1)`), sessions are ephemeral
`uuid4` strings with no owner, and `hable_ya/auth.py` is one shared secret
compared with `compare_digest` — a boolean, not an identity. This spec answers
that question with a **standing non-goal** and writes down what reversing it
would cost, so it stops being re-litigated at the top of every planning turn.

### Consumer Impact

- **The learner** (single-tenant — the one person the deployment serves) sees
  their own name in the greeting and the avatar, and can set or change it from
  the Ajustes screen #020 built. No redeploy, no `.env` edit, no DB console.
- **The operator** gets the first *write* surface on the production HTTP API.
  Until now `/api/learner*` is read-only (three GETs); setting anything about
  the learner required `psql`.
- **The `web/` SPA** gets one new nullable field on a payload it already
  consumes (`LearnerProfile` in `web/src/lib/types.ts`), and one new call. No
  new screen, no new route.
- **Future planning turns** get a written non-goal with a costed alternative,
  instead of an open question that has to be re-derived from the schema each
  time.

### Roadmap Fit

#020 explicitly deferred the learner name and avatar initial to this spec, and
recorded them as untouched in its decision record. #019's read API is the
transport (`profile_payload` already fetches from `learner_profile` directly),
so nothing new has to be built to carry the field.

This spec depends on #019 (the payload) and #020 (the Ajustes screen that edits
it). It blocks nothing. It is deliberately independent of #025–#028, which all
concern the *accuracy* of what the learner model claims; #021 concerns only who
the model is about, and touches none of the aggregates they revise.

The multi-user decision has one interaction worth naming: were it ever
reversed, #022 would have to be resolved first (see Key Decision 4), which is
part of why it stays a non-goal now.

---

## What

### Acceptance Criteria

- [ ] `learner_profile` has a nullable `display_name TEXT` column, added by a
      migration revising head `c7f3a9b21d84`, with a working `downgrade()`.
- [ ] The `CHECK (id = 1)` singleton constraint is unchanged.
- [ ] `GET /api/learner` includes `display_name` (`string | null`), read
      directly from the profile row — not routed through
      `LearnerProfileSnapshot`.
- [ ] `PATCH /api/learner` accepts `{"display_name": "…"}` and persists it,
      gated by the same `require_api_token` Bearer dependency as the GETs,
      fail-closed.
- [ ] `PATCH` with `null` or an all-whitespace string clears the name back to
      SQL `NULL` — "not set" stays representable.
- [ ] `PATCH` rejects a name outside the length bound or containing control
      characters with a 422, and never persists a partially-validated value.
- [ ] A learner with a name set sees it in Home's greeting and as the avatar
      initial (first code point, uppercased — correct for `Ángela` → `Á`).
- [ ] A learner with **no** name set sees a greeting with no name and a blank
      avatar circle — never a fabricated name, never the literal `null`.
- [ ] The Ajustes screen has a name field that saves, shows a confirmation, and
      leaves the token controls working as they do today.
- [ ] Navigating from Ajustes back to Home shows the new name (no manual
      reload).
- [ ] The rendered tutor system prompt is **byte-identical** to before this
      spec — the cold-start prompt-identity tests pass unmodified.
- [ ] `OVERVIEW.md` and `ARCHITECTURE.md` record single-tenant as a decided
      non-goal with the reversal cost, replacing today's bare assertion.
- [ ] Full suite green: pytest (DB up), vitest, ruff, mypy.

### Non-Goals

- **Multi-user accounts.** Settled here as a standing non-goal; the cost is
  documented in Key Decision 4 rather than built.
- **The name in the tutor prompt.** Claude does not learn, greet, or use the
  learner's name. `hable_ya/pipeline/prompts/render.py` is not edited.
- **Any other profile field.** No email, timezone, learning goal, target band,
  or pronouns. Each would need a consumer, and the only consumer surfaces are
  the greeting and the avatar. A second field is cheap to add later on the same
  column pattern.
- **Avatar images.** The circle stays a letter on a sand background — no
  upload, no storage, no serving path.
- **Any auth change.** `hable_ya/auth.py` keeps its shared-secret boolean.
- **Any AGE graph change.** The name is never written to cypher (see Key
  Decision 3).
- **`/dev/learner` work.** It shares `profile_payload`, so it inherits the
  field for free; no separate change.

### Open Questions

Three decisions were made before drafting and are treated as settled: storage
is a DB column with a PATCH endpoint (not a config setting); the name is UI-only
and never enters the prompt; multi-user is a standing non-goal. What remains:

**OQ1 — PATCH path: `/api/learner` or `/api/learner/profile`?**
`PATCH /api/learner` is symmetric with `GET /api/learner` and REST-correct: the
same resource, partially updated. The asymmetry is that GET returns a composed
payload (snapshot + aggregates + themes) while PATCH accepts one mutable field,
which could argue for a distinct `/profile` sub-resource.
**Recommend `PATCH /api/learner`** — one resource, one path; the payload
asymmetry is normal for a computed representation, and a `/profile` child under
a router already prefixed `/api/learner` reads redundantly.

**OQ2 — What renders when `display_name` is `NULL`?**
Options: (a) greeting alone, capitalized and terminated (`Buenas tardes.`) with
an empty avatar circle; (b) a neutral Spanish placeholder word; (c) a prompt to
set a name.
**Recommend (a).** It is the only option that claims nothing. (b) reintroduces
exactly the invented-identity defect this spec removes; (c) puts onboarding
chrome on the main screen for a state most deployments leave within a minute.
The empty circle still reads as an avatar and still navigates to Ajustes, where
the field is.

**OQ3 — Validation bounds.**
Proposed: trim surrounding whitespace; reject if the trimmed value exceeds **40
characters** or contains any Unicode `Cc`/`Cf` control or formatting character;
an empty trimmed value means "clear it". No character-class allowlist —
accented Latin, non-Latin scripts and spaces must all work, and the value is
never interpolated into SQL (asyncpg parameterizes) or cypher (Key Decision 3),
so there is no injection surface to defend with a regex. React escapes on
render.
**Recommend as proposed.** 40 characters fits the 96px serif greeting without
wrapping past two lines at the SPA's `maxWidth: 520`.

---

## How

### Approach

Six small changes across three layers. Nothing is coupled to anything else
except through the payload field.

**1. Migration** — `hable_ya/db/alembic/versions/<rev>_learner_display_name.py`,
`down_revision = "c7f3a9b21d84"` (verified current head; chain is
`20c019e280a9 → bd55d203ae25 → 99507a1b3027 → c7f3a9b21d84`). Follows the
established convention in this repo's migrations:

```sql
SET LOCAL search_path TO public, ag_catalog;   -- else CREATE/ALTER lands in ag_catalog
ALTER TABLE learner_profile ADD COLUMN display_name TEXT;
```

Nullable with no default and no backfill — the existing row's name is genuinely
unset, and `NULL` says so. `downgrade()` drops the column.

**2. Read path** — `hable_ya/learner/read.py::profile_payload` already issues a
second `fetchrow` against `learner_profile` for `stable_sessions_at_band,
last_band_change_at` (lines 43–48). Add `display_name` to that same `SELECT`
and emit it in the returned dict. One query, one key; no new round trip.

**3. Write path** — a `PATCH` on the existing `api/routes/learner.py` router,
reusing `require_api_token` and `_pool` verbatim:

```python
class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=40)

@router.patch("", dependencies=[Depends(require_api_token)])
async def patch_learner(request: Request, body: ProfileUpdate) -> dict[str, Any]:
    ...
```

Normalization (trim → empty means `NULL`, reject control characters) lives in a
pure helper in `hable_ya/learner/read.py`'s sibling — a new
`hable_ya/learner/identity.py` holding `normalize_display_name(raw) -> str |
None` plus the `UPDATE learner_profile SET display_name = $1, updated_at =
now() WHERE id = 1` writer. Pure normalization is unit-testable without a DB,
matching how #024 split its observer state machine from its wiring. The
endpoint returns the updated `{"display_name": …}` so the client can render
without a refetch.

**4. Frontend types + client** — `display_name: string | null` on
`LearnerProfile` (`web/src/lib/types.ts`); an `apiPatch<T>(path, body)` beside
`apiGet` in `web/src/lib/api.ts` sharing its 401 → `clearSessionToken()` →
`UnauthorizedError` path exactly (a rotated token must recover identically on a
write).

**5. Frontend rendering** — two pure helpers in `web/src/lib/format.ts`
(where #020 put its testable client-side logic):

- `greetingLine(time, name)` → the greeting with the name, or the capitalized
  greeting alone when `name` is null.
- `avatarInitial(name)` → `Array.from(name)[0].toUpperCase()`, or `''`.
  `Array.from` rather than `name[0]` so a surrogate pair is not split.

Then `Home.tsx:136-141` and `AppShell.tsx:110-116` consume them, deleting both
`PLACEHOLDER … spec #021` comments.

**6. Ajustes** — a `Tu nombre` panel above the token panel, in María's register
(`Así te saluda la app.`), reusing the existing input/button styling. On save it
PATCHes; on success it shows the same transient `guardado` confirmation the
token panel uses.

**Why no cache invalidation is needed:** `useApi` in `web/src/lib/learner.ts`
refetches on mount and on token change, with no cache. Navigating Ajustes → Home
unmounts Ajustes and mounts Home, so Home's `useLearnerProfile()` refetches and
picks up the new name. No store, no invalidation machinery, no change to the
hook layer.

**Housekeeping the change forces:**

- `tests/conftest.py::clean_learner_state` resets the profile row between tests
  (`sessions_completed`, `band`, `stable_sessions_at_band`,
  `last_band_change_at`). It must also reset `display_name = NULL`, or a PATCH
  test leaks a name into every test that runs after it.
- `scripts/seed_dev_learner.py` sets a name, so the seeded dev DB exercises the
  populated state rather than only the empty one.

### Confidence

**Level:** High

**Rationale:** Every piece has a shipped precedent in this repo. The migration
is the fourth of the same shape (`SET LOCAL search_path` + `ALTER TABLE`,
exactly like `99507a1b3027`'s two-column add). The endpoint reuses #019's
`require_api_token` and `_pool` unchanged. The frontend pattern — pure helper in
`format.ts`, unit-tested with Vitest, consumed by a screen — is #020's, and the
401 recovery rule is already stated once in `useAuthGuard`. There is no new
dependency, no new service, no provider key involved, and the whole feature is
verifiable against a local Postgres with placeholder cloud credentials
(`require_cloud_secrets` only checks truthiness — the finding #020 confirmed).

Two things are genuinely new and worth naming rather than hiding:

1. **The first write endpoint on the production HTTP surface.** All three
   existing `/api/learner*` routes are GETs. Auth is unchanged (same Bearer
   dependency), and because the credential is a header token rather than a
   cookie there is no CSRF vector. The posture shift is that the shared secret
   is now a write credential as well as a read one — but a holder of that token
   could already open `/ws/session` and spend real money on the metered APIs, so
   it is not an escalation of what the secret grants.
2. **Free-text learner input reaching a rendered surface.** React escapes by
   default, the value is parameterized into SQL, and it never reaches cypher.
   The length bound is a layout constraint, not a security one.

Neither needs a spike. The residual risk is confined to OQ1–OQ3, which are
naming and empty-state choices, not architectural ones.

### Key Decisions

**1. A DB column, not a config setting.**
`Settings` was the cheaper option — an env var, no migration. Rejected because
the roadmap's requirement is an *owner-configurable* name surfaced in the UI,
and a config value is only configurable by redeploying: #020's Ajustes screen
could display it but never edit it, leaving a settings screen that settles
nothing. The column also lives where a `learner_id` would eventually live, so
it costs nothing against the alternative future.

**2. The name is read outside `LearnerProfileSnapshot` — safe by construction.**
`profile_payload` could have carried the name on the snapshot, since it already
builds one via `LearnerProfileRepo.get()`. It deliberately does not.
`LearnerProfileSnapshot` feeds `snapshot_to_profile()` → `LearnerProfile` →
`render.py`'s `## Learner` block. Any field on the snapshot is one careless
edit away from the tutor's system prompt. Reading `display_name` from the raw
profile row instead means the name has **no path** to the prompt — the guarantee
is structural rather than a comment asking implementers not to. This is the
same argument #023 used for keeping a mode confined to the `## Topic:` block.

The consequence is that the cold-start byte-identity tests need no
re-baselining, which is the whole reason UI-only was chosen over greeting the
learner by name.

**3. The name never enters the AGE graph.**
`graph.py` builds cypher by f-string interpolation into a dollar-quoted body,
defended by `_IDENT_RE` (`graph.py:37`) which rejects quotes and backslashes and
*drops* unsafe values with a warning. A learner-supplied name is exactly the
kind of value that filter exists to fear, and the graph is write-only today
(#022) so nothing would read it. Keeping the name relational-only removes the
question entirely.

**4. Multi-user is a standing non-goal — the cost, for the record.**
Reversing this is a project, not a variant of this spec. What it would take, as
verified against the code on 2026-08-04:

- **Schema, beyond dropping the `CHECK`.** `error_counts` is `PRIMARY KEY
  (category)` and `vocabulary_items` is `PRIMARY KEY (lemma)`
  (`bd55d203ae25:80-98`) — today one learner's vocabulary table *is* the
  vocabulary table. Both become composite `(learner_id, …)`, plus `learner_id`
  FKs on `sessions` and `band_history`. The data backfill itself is trivial
  (everything belongs to learner 1).
- **The AGE graph is modelled wrong for it, and the fix is blocked.**
  `(l:Learner {id: 1})` appears in four cypher bodies — mechanical. But
  `VocabItem` / `ErrorPattern` nodes are global and carry their counters on the
  *node* (`v.production_count` at `graph.py:85`, `e.occurrences` at
  `graph.py:118`) while the per-learner edge carries its own count. Two learners
  producing *viajar* would inflate a shared node. Fixing that is a re-modeling
  decision on a graph that #022 has not yet decided is load-bearing at all.
- **Auth becomes a real system.** `hable_ya/auth.py` is 29 lines returning a
  bool. Multi-user needs a users table, credential storage, issuance and
  revocation, and both call sites (`/ws/session` pre-`accept()`,
  `/api/learner*` Bearer) resolving an identity instead of a yes/no.
- **#016's cost bound reopens.** `session.py` enforces one active session
  globally (`app.state.active_session`, newest-wins preemption). Per-learner
  sessions mean N concurrent paid pipelines and a new global ceiling to design.
- **Breadth.** ~41 SQL sites across `hable_ya/` and `api/` (`WHERE id = 1`
  alone appears four times in `profile.py`); `conftest.py`'s
  `clean_learner_state` assumes the singleton across the whole suite; the SPA
  needs login, per-user storage replacing `lib/token.ts`'s pasted shared
  secret, and logout.
- **Product posture.** It inverts OVERVIEW's `Not multi-tenant` non-goal and
  changes the privacy statement #015 wrote (multiple people's audio leaving the
  device under one operator's keys).

Five workstreams touching auth, schema, graph, session routing and the SPA —
comparable to #016 + #017 + #018 combined, with one piece blocked behind #022.
Against that, the product need is one person's name in a greeting.

### Testing Approach

Per OVERVIEW's testing suite: pytest (`asyncio_mode = "auto"`, DB tests against
real Postgres) plus the Vitest dev-dependency #020 added for pure client logic.

**pytest — `tests/test_learner_api.py` (extends #019's 26 tests):**

- `display_name` appears in `GET /api/learner`, `null` when unset.
- `PATCH` sets a name; a following `GET` returns it.
- `PATCH` with `null`, `""`, and `"   "` each clear it back to SQL `NULL`.
- `PATCH` with no token, and with a wrong token → 401 (fail-closed, same as the
  GETs).
- `PATCH` with a 41-character name → 422; with a control character → 422; the
  stored value is unchanged after a rejected request.
- A name with accents and a name with a non-BMP first code point round-trip
  intact.
- The `CHECK (id = 1)` constraint still rejects a second profile row.

**pytest — new `tests/test_identity.py` (DB-free):**

- `normalize_display_name` over the trim / empty / too-long / control-character
  / unicode cases, as a pure function.

**pytest — migration:**

- `upgrade()` then `downgrade()` round-trips against a real DB without leaving
  the column behind (the existing migration tests' pattern).

**Vitest — `web/src/lib/format.test.ts` (extends #020's 37):**

- `greetingLine` with a name and with `null` — the null case must produce no
  stray comma, no trailing `undefined`, and a capitalized first word.
- `avatarInitial` over `'ana'` → `'A'`, `'Ángela'` → `'Á'`, a non-BMP first
  character (not split), `null` → `''`.

**Regression / guard:**

- The cold-start prompt byte-identity tests run unmodified and pass — the
  mechanical proof that nothing reached `render.py`.
- `git diff --stat` on `hable_ya/pipeline/` is empty at the end of the
  implementation.

**Manual verification (Playwright is available locally, as #020 established —
and there found three defects no unit test would have):**

- Against a seeded DB *with* a name and *without* one: Home, Ajustes and the
  avatar in both states, zero console errors.
- Set a name in Ajustes → navigate to Home → the greeting shows it without a
  reload.
- Clear the name → the greeting degrades to greeting-only, avatar circle blank.

**Deferred (same class as #016–#020):** nothing here needs a keyed host. The
read *and* write paths touch no provider, so unlike prior specs in this series
there is no deferred live spike.
