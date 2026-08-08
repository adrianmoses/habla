# Spec: Test the dev seeder, and define "reset the learner state" once

| Field | Value |
|---|---|
| id | 030 |
| status | draft |
| created | 2026-08-08 |

---

## Why

`scripts/seed_dev_learner.py` is what every frontend surface and every
inspection endpoint gets eyeballed against. It is also the only dev-facing data
path with no test — and it silently diverged because of that.

#022 found `--reset` truncating the relational tables but not the AGE graph
(`TRUNCATE` does not touch AGE), so every reseed left stale graph nodes
contradicting the relational data beside them. `tests/conftest.py`'s
`clean_learner_state` had always cleared both. The seeder held a copy of the same
statement that did not, and nothing compared the two. That specific bug is fixed;
the class of defect is untouched, and it is worse than "a script lacks a test":
**the artifact that drifts is the one used to judge whether other work is
correct.** A developer looking at a wrong screen cannot tell whether the screen
is wrong or the data is.

### Three copies of "reset the learner state"

Verified at `c5a36d0`:

| Site | TRUNCATE (6 tables) | AGE graph cleared | `learner_profile` reset |
|---|---|---|---|
| `tests/conftest.py:113-144` (`clean_learner_state`) | yes | yes | **yes** — 5 columns |
| `scripts/seed_dev_learner.py:52-55`, `289-300` | yes | yes (since #022) | **no** |
| `scripts/benchmark_graph_writes.py:79-98` (`_reset`) | yes | yes | **no** |

Both scripts carry a comment claiming they use "the same statement(s)" as
`clean_learner_state`. Neither does. The seeder gets away with it only by
coincidence: `_seed_bands` happens to `UPDATE` exactly the five mutable
`learner_profile` columns that `clean_learner_state` resets (`band`,
`sessions_completed`, `stable_sessions_at_band`, `last_band_change_at`,
`display_name`), so its end state is deterministic today. Add a column — #026
proposes `turns_observed`, #028 needs something similar — and the seeder starts
carrying a stale value while the fixture does not. The bug returns in a new
column with the same shape.

### A promised property that is false right now

The docstring leads with:

> A **3-day streak** ending today (today / yesterday / two days ago), then a gap
> — so a streak calculation that ignores gaps is visibly wrong.

The local dev database was seeded four days ago. Queried at `c5a36d0`:

```
 days_ago |      session_id      |   mode    | open_session
        4 | seed-00-contar-un-su | debate    | t
        5 | seed-01-planear-un-v | role_play | f
        6 | seed-02-comida-favor | open      | f
        8 | seed-04-debate:-el-t | debate    | f
```

The *shape* survives — three consecutive days (4/5/6) then a gap at 7 — but the
*anchor* has decayed. There is no session today, so "a 3-day streak ending today"
is false, and any UI that renders an active streak only when it reaches today
shows nothing. That is exactly the failure mode the seeder exists to prevent, and
it is live. The seed has a shelf life and nothing says so.

Everything else the docstring promises does currently hold (40 turns > 20; 2
null-mode sessions; all four modes; exactly one `ended_at IS NULL`; `Ángela`), and
so does #022's graph mirror — 15 `VocabItem` against 15 `vocabulary_items`, 7
`ErrorPattern` against 7 `error_counts`. Which is the point: the promises are
checkable, and nothing checks them.

### Consumer Impact

- **Whoever builds or reviews a frontend surface.** A test turns "the seeded data
  has the shape the screens need" from a docstring claim into a build failure.
  #020 built five screens against this data; #025 and #028 will read it again.
- **Whoever changes the learner schema.** Today a new `learner_profile` column
  silently breaks reseed determinism in one of three places. After this, one
  definition changes and a test names the omission.
- **Not the learner.** No runtime behaviour changes. This is tooling that
  protects the judgement of other work.

### Roadmap Fit

Third in the sequence #029 started, and the middle of three items about the same
failure mode: a claim the repo makes about itself that nothing checks. #029 did
it for documentation prose, this does it for dev data, #031 does it for migration
`downgrade()` paths. It reuses #029's mechanism — assert the claim, and verify
the assertion by reintroducing the defect.

Blocks nothing. It does make #025–#028 safer, since all four will read or reshape
the aggregates this data stands in for, and #026's new column is precisely the
change that would re-break the reset.

---

## What

### Acceptance Criteria

- [ ] One definition of "reset the learner state", used by `clean_learner_state`,
      `seed_dev_learner.py` and `benchmark_graph_writes.py`. No site keeps its
      own copy of the `TRUNCATE`, the graph clear, or the profile reset.
- [ ] The shared reset clears all three: relational tables, the AGE graph, and
      `learner_profile`.
- [ ] **A test fails if a new `learner_profile` column is added without the
      reset accounting for it.** The reset's column coverage is asserted against
      the live table, not trusted.
- [ ] The seeder's logic is importable and callable against a caller-supplied
      connection and a caller-supplied `now`, so a test can pin time. The CLI
      entry point stays a thin wrapper — the shape `scripts/init_db.py` already
      has, and which `tests/test_init_db.py` tests through the library function.
- [ ] Tests assert the properties the docstring promises, at seed time:
      3-consecutive-day streak ending on the seed date then a gap; exactly one
      `ended_at IS NULL`; at least one `mode IS NULL` and all four modes present;
      at least one error category inside and one outside
      `ALLOWED_ERROR_PATTERNS`; more than 20 turns; a `display_name` whose first
      code point is non-ASCII; band `B1` with a placement row making
      `is_calibrated` true.
- [ ] A test asserts the graph mirrors the relational aggregates after seeding —
      one `VocabItem` per `vocabulary_items` row, one `ErrorPattern` per
      `error_counts` row. This is the #022 regression, and it is the one property
      whose absence was a real bug rather than a hypothetical.
- [ ] `--reset` followed by a second `--reset` produces the same end state
      (idempotent reseed), the guarantee the flag exists to provide.
- [ ] The seeder logs the anchor date it seeded against, so a developer
      eyeballing a stale database can tell the data has aged rather than
      concluding a screen is broken.
- [ ] The docstring states which properties are contract (asserted) and which are
      incidental, including that the seed's recency-relative properties are
      anchored to seed time.
- [ ] Each new test verified by reintroducing the defect it guards — including
      #022's original: removing the graph clear from the shared reset must fail.
- [ ] `ruff`, `mypy`, and the full `pytest` suite pass.

### Non-Goals

- **Not routing the seeder through `TurnIngestService`.** Its docstring is
  explicit that it writes tables directly to produce a plausible end state
  cheaply, and that `tests/` already covers the ingest path. Changing that is a
  different (and slower) script.
- **Not making the seeded aggregates internally consistent.** `error_counts`
  holds 7 categories with counts up to 14 while `error_observations` holds 5
  rows, and the graph's counters differ from the relational ones by design
  (#022: "the writers increment per call, so this seeds presence and shape, not
  magnitude"). This is a fabricated end state, not a replayed history. The spec's
  job is to say so explicitly, not to fix it — and therefore **not** to assert
  cross-table count consistency.
- **Not a freshness mechanism beyond the log line.** Refusing to serve stale
  seed data, or surfacing seed age on `/dev/learner`, is a larger design question
  about the inspection surface. Naming the decay and dating the log is the
  proportionate fix here.
- **Not testing `benchmark_graph_writes.py` itself.** It becomes a consumer of
  the shared reset; its measurement logic is out of scope.
- **No schema changes, no runtime changes.** Tooling and tests only.

### Open Questions

1. **Where does the shared reset live?** It is a destructive helper used by
   tests and dev scripts and by nothing in production. Candidates: `hable_ya/`
   (importable everywhere, which is the problem), or `scripts/` (dev-only by
   construction, and `tests/` already imports from `scripts.fixtures.*`, so the
   precedent exists). *Proposed: `scripts/`* — see Key Decision 1. Resolve
   before approval.

2. **Does the profile reset enumerate columns or derive them?** Deriving from
   `information_schema` is drift-proof but cannot know the intended base value
   (`band` has no column default; the migration inserts `'A2'` explicitly).
   *Proposed: enumerate the base state, and assert the enumeration covers the
   table* — the coverage assertion is what makes enumeration safe. See Key
   Decision 2.

---

## How

### Approach

**1. Extract one reset (`scripts/learner_reset.py`)**

A single `reset_learner_state(conn)` performing all three steps in order —
`TRUNCATE` the six tables, clear the AGE graph, restore `learner_profile` to its
base state — plus a module-level declaration of that base state that a test can
compare against the live table.

Call sites become one line each:

- `tests/conftest.py`'s `clean_learner_state` — keeps the fixture, drops the SQL.
- `scripts/seed_dev_learner.py` — `--reset` calls it; `TRUNCATE_SQL` and the
  inline cypher go.
- `scripts/benchmark_graph_writes.py`'s `_reset` — calls it, then keeps its own
  benchmark-session insert.

The comments in both scripts claiming "the same statement the fixture uses"
become true rather than aspirational.

**2. Make the seeder importable**

Extract `async def seed(conn, *, now)` covering the four existing
`_seed_*` steps and the transaction around them. `amain(reset)` keeps pool
lifecycle, the `--reset` call, and the summary log; `main()` stays the CLI
wrapper. This is `init_db.py`'s shape, and it is what lets a test drive the
seeder with the test pool's connection and a pinned `now` instead of
subprocessing it.

`now` is already threaded through every `_seed_*` helper, so this is a signature
change, not a rewrite.

**3. `tests/test_seed_dev_learner.py`**

Uses the `clean_learner_state` fixture — committed writes, no rollback, because
AGE side-effects do not reliably roll back (`tests/conftest.py:100-101`) — then
calls `seed(conn, now=<pinned>)` and asserts the properties. Grouped one test per
promised property, so a failure names which promise broke rather than "the seed
is wrong".

The streak test is the one that needs the pinned `now`: it asserts three
consecutive session dates ending on the anchor date and a gap the day before the
run of three, which is only expressible when the test controls the anchor.

**4. Schema-coverage guard**

A test reading `information_schema.columns` for `learner_profile` and asserting
that every column is either reset by the shared definition or in a small
`_NOT_RESET` set (`id`, `created_at`, `updated_at`) with a reason. Adding a
column fails this test until someone decides which side it belongs on. This is
#029's `KNOWN_ABSENT` pattern pointed at schema drift instead of paths.

**5. Idempotency**

Seed, snapshot the counts and the profile row, reset+seed again with the same
pinned `now`, assert the snapshot is unchanged.

### Confidence

**Level:** High

**Rationale:** All the facts are established rather than assumed — the three
copies and their divergence are tabulated above, the properties were queried
against a live seeded database, and both structural precedents exist in the repo
(`init_db.py`/`test_init_db.py` for the extraction, `scripts.fixtures.*` imports
for the module location). The work is mechanical once the two open questions are
resolved.

The one genuine uncertainty is whether the shared reset in `scripts/` is
importable in every context that needs it. Tests already do it, so CI is
covered; the risk is a future packaged consumer, which is exactly the consumer
that should not have a learner-wipe helper.

### Key Decisions

1. **The shared reset lives in `scripts/`, not `hable_ya/`.** `hable_ya/` is the
   production package: putting "delete all learner state" there makes it
   importable from `api/` and the pipeline, and the only thing preventing that
   would be a docstring. In `scripts/` — which hatchling does not package (`wheel
   packages = ["hable_ya", "api", "analiza"]`) — dev-only status is structural,
   not documented. Cost: `scripts/` is not type-checked as strictly and is a
   slightly odd import for `tests/conftest.py`. Accepted, given `tests/` already
   imports `scripts.fixtures.validate_fixtures` and
   `scripts.fixtures.prompts`.

2. **Enumerate the base profile state, then assert the enumeration is
   complete.** A derived reset cannot know that `band`'s base value is `'A2'`,
   because the column has no default — the value lives in migration
   `bd55d203ae25`'s seed `INSERT`. So enumeration is necessary; what makes it
   safe is the coverage test, which converts "someone remembered to update all
   three copies" into "CI fails until someone decides". This is the actual answer
   to the roadmap's "a single shared definition instead of three copies" — one
   definition is necessary, and a check that it stays complete is what makes it
   sufficient.

3. **Assert properties, not fixture contents.** The tests check *3 consecutive
   days then a gap*, not that `_SESSIONS` has twelve specific rows. Asserting the
   table would make every future tweak to the seed data a test change and teach
   people to update expectations without reading them. Properties survive
   reshaping the data; that is the whole reason the docstring lists properties.

4. **Cross-table consistency is explicitly not a property.** Recorded as a
   Non-Goal above and to be stated in the docstring, because it is the most
   plausible thing a future contributor would "fix" — adding an assertion that
   `error_counts` sums to `error_observations` would fail immediately and
   correctly, and the right response is to know it was never promised.

### Testing Approach

Per `OVERVIEW.md`'s Testing Suite: pytest, `asyncio_mode = "auto"`. These are
DB-backed tests using the `clean_learner_state` fixture (committed writes; AGE
does not reliably roll back), so they run in CI's `checks` job against the
Postgres/AGE service.

| Test | Asserts |
|---|---|
| `test_streak_shape` | Three consecutive session dates ending on the pinned anchor, and a gap immediately before them |
| `test_one_open_session` | Exactly one session with `ended_at IS NULL` |
| `test_modes_cover_null_and_all_four` | ≥1 `mode IS NULL`; all four modes present |
| `test_error_categories_straddle_the_enum` | ≥1 category in `ALLOWED_ERROR_PATTERNS` and ≥1 outside it |
| `test_turns_exceed_profile_window` | Turn count > `profile_window_turns` (20), read from config rather than hardcoded |
| `test_display_name_is_non_ascii` | `display_name` set and its first code point non-ASCII |
| `test_profile_is_calibrated_at_b1` | Band `B1`; a placement row in `band_history` makes `is_calibrated` true |
| `test_graph_mirrors_relational_aggregates` | `VocabItem` count == `vocabulary_items` count; `ErrorPattern` count == `error_counts` count — the #022 regression |
| `test_reseed_is_idempotent` | Two reset+seed cycles at the same pinned `now` produce identical counts and profile row |
| `test_reset_covers_every_profile_column` | Every `learner_profile` column is either reset or explicitly excluded |

**Verification of the tests themselves** (#029's precedent, itself following
#022): each new test is verified by reintroducing the defect it guards, and the
results recorded in the decision record. At minimum:

- Delete the graph clear from `reset_learner_state` → the mirror test and the
  idempotency test must fail. **This is #022's original bug**, and reproducing it
  is the strongest evidence this spec delivers anything.
- Add a nullable column to `learner_profile` in a scratch migration, or simulate
  it, → the coverage test must fail naming the column.
- Drop a session from `_SESSIONS` so days 0/1/2 are no longer consecutive → the
  streak test must fail.

**Regression surface:** `clean_learner_state` is used by most learner tests, so
rewriting it to delegate is the highest-risk change here — a mistake shows up as
broad, loud failures rather than silence, which is the good direction. The full
suite (543 at `c5a36d0`) is the check.
