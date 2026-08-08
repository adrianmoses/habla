# Decision Record: Test the dev seeder, and define "reset the learner state" once

| Field | Value |
|---|---|
| id | 030 |
| status | implemented |
| created | 2026-08-08 |
| spec | [spec.md](./spec.md) |

---

## Context

The roadmap asked for two things: a test that the seeded end state satisfies the
properties its docstring promises, and one shared definition of "reset the learner
state" instead of three copies. Both were delivered as specified. What the spec
did not anticipate is the finding that reshaped the most important test.

Two facts established before implementation set the stakes. The divergence #022
found was **still live in a different column**: all three reset copies cleared
tables and graph, but only `clean_learner_state` reset `learner_profile`, and the
seeder escaped consequences purely because `_seed_bands` happens to overwrite
exactly the five mutable columns the fixture clears. And a promised property was
**false at the time of writing**: the dev database had been seeded four days
earlier, so "a 3-day streak ending today" no longer held — the shape survived, the
anchor had decayed.

Then, during implementation, the defect-reintroduction pass the spec mandated
produced the result that mattered most: **the first version of the graph test
passed with the graph clear deleted.** The test the spec described as "the
strongest evidence this spec delivers anything" did not detect the bug it was
written for. Details below; it is the reason two tests exist where the spec
planned one.

## Decision

**One definition of the reset (`scripts/learner_reset.py`), consumed by all three
sites; the seeder made importable so its promises can be asserted at a pinned
anchor; and the reset's completeness guarded against schema drift rather than
trusted.**

The reset performs all three steps — `TRUNCATE` the six learner tables, clear the
AGE graph, restore `learner_profile` to its base state — on the principle that any
caller needing one needs all three. That assumption is what the three previous
copies got wrong, in two different ways.

`PROFILE_BASE_STATE` is enumerated rather than derived, because `band` has no
column `DEFAULT` — its base value lives in migration `bd55d203ae25`'s seed
`INSERT`. What makes enumeration safe is `test_reset_covers_every_profile_column`,
which asserts every live `learner_profile` column is either reset or excluded with
a written reason. When #026 adds `turns_observed`, CI fails until someone decides
which side it belongs on.

The eleven tests assert the docstring's contract section, one test per promise.

## Alternatives Considered

### Detecting #022's stale-graph bug

This is the decision the implementation forced, and it was not in the spec.

The spec's plan was `test_graph_mirrors_relational_aggregates`: assert one
`VocabItem` per `vocabulary_items` row, one `ErrorPattern` per `error_counts`
row. Deleting `clear_graph` from the reset left it passing. The cause is that
`upsert_vocab` and `upsert_error_pattern` use `MERGE` on the key, so re-seeding
*unchanged* data over stale nodes reproduces exactly the same node set. Node
counts are invariant under the bug when the seed data does not change — and it
never changes between test runs.

**Option A — Compare key sets instead of counts.**
- Pros: strictly stronger than counting; catches a stale node whose lemma or
  category is absent from the current seed, which is what the bug produces in
  real use (the seed data changes between reseeds).
- Cons: still cannot see the bug when the seed data is *identical*, which is
  precisely the situation inside the test suite.

**Option B — Test the reset's property directly.** Write a node the next seed
will not write, reset, assert the graph is empty.
- Pros: detects the defect unconditionally, because it does not depend on the
  seed data differing. Tests the actual contract (`reset` clears the graph)
  rather than a consequence of it.
- Cons: does not verify the seeder mirrors anything, which was the other half of
  the original intent.

**Chosen: both.** They cover different failures and neither subsumes the other.
`test_graph_mirrors_the_relational_aggregates` compares key sets (A) and answers
"does the seeder populate the graph correctly"; `test_reset_clears_the_graph` (B)
answers "does the reset clear it", and is the one that fails on #022's defect. The
`_state_snapshot` used by the idempotency test was moved from counts to sorted key
lists for the same reason.

The general lesson, worth more than the specific fix: **a test that asserts an
invariant which the bug preserves is not a test of that bug.** Counting was
comfortable and wrong, and only reintroducing the defect exposed it.

### Where the shared reset lives

**Option A — `hable_ya/learner/reset.py`.** Pros: natural home beside the code it
resets; type-checked by CI. Cons: `hable_ya` is packaged, so "delete every learner
row" becomes importable from `api/` and the pipeline, with only a docstring
against it.

**Option B — `scripts/learner_reset.py`.** Pros: hatchling packages `hable_ya`,
`api` and `analiza` only, so dev-only status is structural rather than
documented; `tests/` already imports `scripts.fixtures.*`. Cons: CI's mypy covers
`hable_ya/ api/ eval/agent/`, so it lands in the one place CI will not type-check.

**Chosen: B**, resolved by the owner at approval. The cost is real and was named
in the plan; it is mitigated by running mypy on the module locally (clean), and
the alternative trades a structural guarantee for a lint pass.

### Enumerated vs derived profile base state

Deriving from `information_schema` and `SET col = DEFAULT` was considered and is
impossible as stated: `band` is `NOT NULL` with no `DEFAULT`, so a derived reset
cannot know its base value is `'A2'`. Enumeration plus a coverage assertion was
chosen — and the assertion is what makes it the answer to the roadmap's ask rather
than a fourth copy in a nicer location.

## Tradeoffs

**Given up: CI type-checking of the shared reset.** Accepted as the price of
structural dev-only-ness. The mitigation is manual (`mypy scripts/learner_reset.py`
is clean); the durable fix is extending CI's mypy scope, deliberately deferred.

**Given up: any assertion about the magnitude of seeded aggregates.** The tests
check that categories straddle `ALLOWED_ERROR_PATTERNS` and that keys mirror, not
that counts reconcile. `error_counts` holds counts up to 14 against 5
`error_observations` rows by design. This is recorded in the seeder's docstring as
*incidental*, because it is the most plausible thing a future contributor would
"fix" — the assertion would fail immediately and correctly.

**Optimised for: naming the broken promise.** Eleven tests rather than one, so a
failure says *which* property regressed. The cost is more fixture setup per test;
the `seeded` fixture reseeds for each, which is cheap (0.84s for the file).

**Accepted: the seed still decays.** The log line names the anchor date, so a
developer can tell stale data from a broken screen. Nothing refuses to serve stale
data or surfaces seed age on `/dev/learner` — deliberately out of scope, and named
as a Non-Goal.

**Not addressed: `seed()` alone remains non-idempotent.** The turn and
band-history inserts have no conflict handling, so seeding twice without a reset
duplicates rows. The test asserts reset+seed twice, which is what `--reset`
promises; the docstring now says so explicitly rather than leaving it to be
discovered.

---

### Spec Divergence

One divergence, and it is the substance of the work.

| Spec Said | What Was Built | Reason |
|---|---|---|
| One test, `test_graph_mirrors_relational_aggregates`, asserting node counts equal row counts — described as "the #022 regression" | Two tests: the mirror comparing **key sets**, plus `test_reset_clears_the_graph` asserting the graph is empty after a reset | The spec's version **passed with `clear_graph` deleted**. The writers `MERGE` on the key, so re-seeding unchanged data over stale nodes yields an identical node count — the bug preserves the invariant the test asserted. Found by the spec's own defect-reintroduction requirement. |

Everything else matched: eleven of the spec's ten planned tests (the extra being
the split above), the shared reset in `scripts/` with an asserted column
enumeration, the `seed(conn, *, now)` extraction following `init_db.py`'s shape,
the anchor-date log line, and the contract/incidental docstring split.

The defect-verification list was executed as written, with one substitution: for
"add a nullable column to `learner_profile`", the equivalent state was created by
removing `display_name` from `PROFILE_BASE_STATE`, leaving a live column in
neither dict — the same assertion path a new column triggers, without a scratch
migration against the test database.

---

## Spec Gaps Exposed

1. **A pre-existing mypy error in `scripts/seed_dev_learner.py`.** `_SESSIONS`
   types `band` as `str`, but `link_session_to_scenario` expects
   `Literal['A1','A2','B1','B2','C1']`. Confirmed pre-existing (line 208 at
   `c5a36d0`, line 227 now) and untouched here: CI does not type-check `scripts/`,
   so it has never been visible. It is a one-line annotation, left alone to keep
   the diff scoped — but it is evidence for the follow-up below.

2. **CI's mypy scope is the real gap.** `scripts/` gets ruff but no type
   checking, which is how #1 survived and is a standing cost of Key Decision 1.
   Extending the scope would surface a small number of pre-existing errors in
   `scripts/` first, which is why it is its own item rather than a line in this
   one.

3. **The spec asserted a test's efficacy without checking it.** It called the
   count-based mirror test "the strongest evidence this spec delivers anything".
   It was the weakest. The spec's own verify-by-reintroduction requirement caught
   it, which is the process working — but the lesson generalizes: a spec should
   not claim a test detects a specific historical bug until the bug has been
   replayed against it. Recorded for the spec workflow, not as product work.

4. **`ANCHOR` is a fixed date, and time still leaks in one place.** The tests pin
   `now`, but `test_streak_*` reads `sessions.started_at` in UTC via
   `AT TIME ZONE 'UTC'`. A future change to how the seeder localizes timestamps
   would be caught, which is intended — but no test covers the seeder's behaviour
   near a DST or month boundary. `ANCHOR` was chosen mid-month partly to avoid
   that, which means the boundary cases are untested rather than handled.

---

## Test Evidence

The eleven tests, passing:

```
$ uv run pytest tests/test_seed_dev_learner.py -v
test_streak_is_three_consecutive_days_then_a_gap PASSED  [  9%]
test_exactly_one_session_is_still_open PASSED            [ 18%]
test_modes_cover_null_and_all_four PASSED                [ 27%]
test_error_categories_straddle_the_curated_enum PASSED   [ 36%]
test_turns_exceed_the_profile_window PASSED              [ 45%]
test_display_name_is_set_and_non_ascii PASSED            [ 54%]
test_profile_is_calibrated_at_b1 PASSED                  [ 63%]
test_graph_mirrors_the_relational_aggregates PASSED      [ 72%]
test_reset_clears_the_graph PASSED                       [ 81%]
test_reseed_is_idempotent PASSED                         [ 90%]
test_reset_covers_every_profile_column PASSED            [100%]
============================== 11 passed in 0.84s ==============================
```

**Defect 1 — #022's bug, first attempt (the failure that changed the design).**
Deleting `await clear_graph(conn)` from `reset_learner_state`, with the
count-based mirror test the spec described:

```
$ uv run pytest tests/test_seed_dev_learner.py -q
10 passed in 0.78s          # <-- the bug was NOT detected
```

**Defect 1 — after the redesign.** Same deletion, against key-set comparison plus
the direct reset test:

```
$ uv run pytest tests/test_seed_dev_learner.py -q
E   AssertionError: nodes survived the reset — TRUNCATE does not clear AGE, so a
    reseed would leave stale graph state contradicting the relational data beside
    it (spec #022)
FAILED tests/test_seed_dev_learner.py::test_reset_clears_the_graph
1 failed, 10 passed in 0.81s
```

**Defect 2 — an unaccounted `learner_profile` column** (created by removing
`display_name` from `PROFILE_BASE_STATE`):

```
E   AssertionError: learner_profile column(s) ['display_name'] are neither reset
    nor excluded. Add them to PROFILE_BASE_STATE (with a base value) or to
    PROFILE_NOT_RESET (with a reason) in scripts/learner_reset.py.
FAILED tests/test_seed_dev_learner.py::test_reset_covers_every_profile_column
1 failed, 10 passed in 0.86s
```

**Defect 3 — a broken streak** (dropping the day-1 session from `_SESSIONS`):

```
E   AssertionError: expected a 3-day run ending 2026-06-17, got
    [datetime.date(2026, 6, 17), datetime.date(2026, 6, 15), datetime.date(2026, 6, 13)]
FAILED tests/test_seed_dev_learner.py::test_streak_is_three_consecutive_days_then_a_gap
1 failed, 10 passed in 0.82s
```

All three reverted.

**Full suite, lint, types** — 543 before, 554 after, the delta being exactly the
eleven new tests. The rewritten `clean_learner_state` is depended on by ten test
files plus `tests/e2e/conftest.py`, so this is the regression check that mattered:

```
$ uv run pytest -q
554 passed, 6 deselected, 9 warnings in 18.52s

$ uv run ruff check .
All checks passed!

$ uv run mypy hable_ya/ api/ eval/agent/
Success: no issues found in 65 source files

$ uv run mypy scripts/learner_reset.py
Success                     # the new module, clean (CI does not check scripts/)
```

**End-to-end CLI**, confirming the extraction did not break the entry point, and
demonstrating the new anchor-date log line:

```
$ uv run python scripts/seed_dev_learner.py --reset
INFO seed_dev_learner Clearing learner state (tables, AGE graph, profile row)
INFO seed_dev_learner Seeded 12 sessions / 40 turns, anchored at 2026-08-08
                      (streak ends on that date)
```

The dev database's streak now reaches today, which incidentally resolves the stale
state the spec documented:

```
 days_ago |   mode    | open
        0 | debate    | t
        1 | role_play | f
        2 | open      | f
        4 | debate    | f      <- the gap, at day 3
```

**Not covered by automation:** the seeder's behaviour across month/DST boundaries
(see gap 4), and whether the seeded data is *pedagogically* plausible as opposed
to structurally correct — that remains a human judgement, which is what the
seeder exists to support.
