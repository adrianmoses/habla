# Decision Record: Exercise every migration's downgrade, in both directions

| Field | Value |
|---|---|
| id | 031 |
| status | implemented |
| created | 2026-08-08 |
| spec | [spec.md](./spec.md) |

---

## Context

The roadmap posed #031 as a choice between two resolutions — round-trip the whole
chain, or delete the `downgrade()` bodies and declare migrations forward-only.
The owner settled it before the spec was written: *"let's never assume downgrades
are not needed."* Forward-only was therefore rejected rather than weighed, and the
repo backs that up — `scripts/backup_db.sh` and `restore_db.sh` shipped in #017,
so rollback is already part of the operational story.

Two things then changed the work's character, both discovered by checking rather
than reasoning.

**The roadmap's technical suspicion was wrong.** It flagged `20c019e280a9`'s
`DROP EXTENSION IF EXISTS age;` without `CASCADE` as "correct in a full
`downgrade base` chain and a failure in any partial one". Run against a scratch
database, the full chain round-trips cleanly. The predicted failure is
unreachable: alembic enforces chain order, so that downgrade only ever executes
when going to `base`, which necessarily runs `bd55d203ae25`'s graph drop first.
The sharper version — a *foreign* AGE graph that `bd55d203ae25` would not know to
drop — was tested directly by creating `un_grafo_ajeno`, and it also succeeded,
taking that schema with it: AGE registers graph schemas as members of the
extension rather than as dependents.

So there was nothing to repair, and the spec said so instead of borrowing
urgency it had not earned. The justification became the weaker, honest one: five
reverse paths work, four had never been run by anything, and nothing kept them
working.

**And the runtime question inverted.** The spec's one open question was whether
the per-revision walk could afford its alembic invocations against an 18s suite,
with a marker as the fallback. The answer was ~1.0s — and that surplus is what
paid for the isolation fix below.

## Decision

**A round-trip harness (`tests/test_migration_chain.py`) that runs every
migration's `downgrade()` on every commit, against a throwaway database, and
asserts that the forward path can rebuild from what each one leaves behind.**

Two tests: the full chain (`head → base → head`) and a walk that takes each
revision down one step and back up, probing the specific object that revision
introduces. The probe is what makes a downgrade observable — asserting only that
it "ran without error" would pass for a `downgrade()` whose body had been deleted.

The `ag_catalog`-survives-`DROP EXTENSION` behaviour is asserted with its reason
attached, because the chain's ability to re-upgrade depends on
`CREATE EXTENSION IF NOT EXISTS age` coping with a schema that is already there.

## Alternatives Considered

### Fixture scope for the throwaway database

This was the plan's stated open risk and the run resolved it against the plan's
own initial choice.

**Option A — module-scoped.** One database for the whole file.
- Pros: fewer `CREATE DATABASE` round trips; the plan's default on the assumption
  that alembic invocations dominate.
- Cons: tests share mutable state. Observed concretely during defect
  verification: with a broken `downgrade()`, `test_full_chain_round_trip` failed
  and left a half-migrated database, so `test_each_revision_round_trips` then
  failed on a raw SQLAlchemy error from its opening `downgrade base` rather than
  on its own assertion. **That is the same cascade this spec objected to in the
  shared session database, reproduced inside the new file.**

**Option B — function-scoped.** A fresh database per test.
- Pros: a failure cannot be handed to the next test; each test diagnoses its own
  defect.
- Cons: one extra create/drop cycle.

**Chosen: B.** The plan committed to deciding this "by measurement, not
preference", and the measurement made it easy: the file runs in ~1.0s against the
spec's ~15s threshold, so isolation costs a rounding error. Re-running the defect
with function scope produced two independent, named failures instead of one real
and one misleading.

### Where the runtime cost actually was

The manual probe during speccing felt slow enough to make the open question seem
real. It was measuring the wrong thing: each `uv run alembic …` pays Python
interpreter and import startup (~1s), while the tests call `command.upgrade`
in-process, where the same 35 upgrade/downgrade operations cost only their SQL.
Worth recording because the mistake is easy to repeat — CLI timings are a bad
proxy for in-process cost, and a spec that had trusted them would have shipped an
unnecessary pytest marker and a CI step to go with it.

### Two tests instead of the spec's four

The spec's Testing Approach listed four tests; the plan consolidated the two
`base`-state assertions (`only alembic_version`, `ag_catalog survives`) into
`test_full_chain_round_trip`, since separate tests would each need their own
`upgrade head` to establish a known start. Every acceptance criterion is still
covered. The cost — one failure meaning several things — is mitigated by distinct
assertion messages, and the function-scoped fixture removed the more serious
version of that objection.

---

## Tradeoffs

**Given up: nothing is protected against a downgrade that succeeds but loses
data.** These tests assert *schema* reversibility on an empty database. A
`downgrade()` that drops a column the upgrade cannot repopulate passes here and
would still lose production data. That is a Non-Goal (`backup_db.sh` is the
answer) and it is worth stating plainly, because "the downgrade is tested" could
otherwise be read as a stronger guarantee than it is.

**Optimised for: the next migration's author.** They inherit the harness. If
migration six's `downgrade()` leaves residue the forward path chokes on, CI says
so with the revision named, rather than an operator discovering it mid-incident.

**Accepted: `CHAIN` is a hand-maintained table.** Each revision is paired with the
object it introduces, and a sixth migration needs a row added. Deriving probes
from the migration bodies was never plausible — they are opaque `op.execute`
strings. The failure mode is benign in the direction that matters: a missing row
means the new revision is not probed, not that the suite goes green while broken.
It is the same class of hand-maintained list #029 deleted from the orientation
docs, kept here because there is no authoritative source to defer to.

**Accepted: the `ag_catalog` assertion pins behaviour we do not control.** If a
future AGE release drops the schema with the extension, that assertion fails even
though nothing is wrong. The message says so and points at what to re-check —
preferable to leaving the re-upgrade's precondition undocumented.

---

### Spec Divergence

| Spec Said | What Was Built | Reason |
|---|---|---|
| Four tests (`test_full_chain_round_trip`, `test_downgrade_base_leaves_only_alembic_version`, `test_revision_round_trip[×5]`, `test_ag_catalog_survives_extension_drop`) | Two, with the `base`-state assertions folded into the full-chain test and the per-revision cases as one walk | Flagged in the plan and approved. Separate tests would each need their own `upgrade head` to establish a starting revision; the criteria are unchanged and every assertion names what it checks. |
| Open Question 1: measure the runtime, add a pytest marker above ~15s | Measured at ~1.0s; **no marker** | Answered by measurement, as the spec required. The surplus was spent on function-scoped isolation instead. |

The spec's acceptance criteria are all met. The plan's own default — module-scoped
fixture — was reversed during implementation for the reason recorded above.

---

## Spec Gaps Exposed

1. **The spec's `Testing Approach` named a test that would have been weaker than
   the one built.** `test_ag_catalog_survives_extension_drop` as a standalone
   would have asserted the residue exists without connecting it to the re-upgrade
   that depends on it. Folded in, the assertion sits between the downgrade and
   the re-upgrade where its purpose is legible. Minor, but it is the second spec
   running (after #030) where the test *shape* proposed in the spec needed
   revising once it met the database.

2. **`CHAIN` has no guard against falling behind the migration directory.** A
   sixth revision that nobody adds a row for is silently unprobed. A cheap check
   — assert `CHAIN`'s revisions match the files in
   `hable_ya/db/alembic/versions/` — would close it, in the spirit of #030's
   `test_reset_covers_every_profile_column`. Deliberately not built here (it is
   past the spec's criteria), and a good candidate for whoever adds migration six.

3. **Nothing tests downgrade against a populated database.** Named as a Non-Goal
   and still the most valuable follow-up: the realistic incident is rolling back
   a database with rows in it, and `bd55d203ae25`'s downgrade drops six tables
   whose foreign keys would be exercised only in that case.

4. **The roadmap entry for #031 remains wrong on the record.** Its `CASCADE`
   claim is refuted by this spec and its decision record, but the entry itself
   still asserts it. Left as-is deliberately — the roadmap is a historical log and
   #029 established that its rows are not rewritten — but a reader who finds the
   entry and not this record will believe it.

---

## Test Evidence

Both tests, passing, with per-test timings:

```
$ uv run pytest tests/test_migration_chain.py -q --durations=3
0.48s call     tests/test_migration_chain.py::test_each_revision_round_trips
0.20s call     tests/test_migration_chain.py::test_full_chain_round_trip
2 passed in 1.00s
```

**The chain really runs** — 35 alembic operations across the two tests, confirmed
because a suspiciously fast pass is exactly the failure #030 was caught by:

```
$ uv run pytest tests/test_migration_chain.py -s --log-cli-level=INFO \
    | grep -cE 'Running upgrade|Running downgrade'
35
```

**Defect reintroduction** — removing `DROP TABLE IF EXISTS band_history` from
`99507a1b3027.downgrade()`. Both tests fail, each naming what it observed:

```
E   AssertionError: downgrade base left ['band_history'] in public;
    alembic_version is alembic's own bookkeeping and is expected to survive
E   AssertionError: 99507a1b3027: downgrade left table:band_history behind
FAILED tests/test_migration_chain.py::test_full_chain_round_trip
FAILED tests/test_migration_chain.py::test_each_revision_round_trips
2 failed in 0.81s
```

Reverted; `git diff --stat hable_ya/` empty afterwards.

**The same defect under the plan's original module-scoped fixture**, kept as the
evidence for the scope change — the second failure is not its own assertion but
fallout from the first test's dirty database:

```
FAILED tests/test_migration_chain.py::test_full_chain_round_trip - AssertionE...
FAILED tests/test_migration_chain.py::test_each_revision_round_trips - sqlalc...
```

**Full suite, lint, types.** 543 on `main` → 544: two added, one removed (the
#021 round-trip, now covered for every revision).

```
$ uv run pytest -q
544 passed, 6 deselected, 9 warnings in 21.13s

$ uv run ruff check .
All checks passed!

$ uv run mypy hable_ya/ api/ eval/agent/
Success: no issues found in 65 source files
```

**No leftover databases** — the fixture creates and drops its own, and never
touches the dev database:

```
$ psql -d postgres -tc "SELECT datname FROM pg_database WHERE datname LIKE 'hable_ya%';"
 hable_ya
```

**Not covered by automation:** downgrade against a populated database (gap 3),
and whether a `downgrade()` loses data that the corresponding `upgrade()` cannot
reconstruct — schema reversibility is a strictly weaker property than data
reversibility, and only the former is asserted here.
