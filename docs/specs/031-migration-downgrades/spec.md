# Spec: Exercise every migration's downgrade, in both directions

| Field | Value |
|---|---|
| id | 031 |
| status | approved |
| created | 2026-08-08 |

---

## Why

Five migrations, each with a `downgrade()`. Before this spec, **one had ever been
executed**: #021 added `tests/test_learner_display_name_migration.py`, and it
covers `-1` only, so `f1e6a742b90c` was the sole revision whose reverse path had
ever run. The other four were untested code on the deploy path, documented as
supported by their own existence.

**Downgrades are supported.** That is a standing decision, not a question this
spec reopens: the roadmap offered "delete the `downgrade()` bodies and declare
the migrations forward-only" as an alternative, and it is rejected. The repo
already ships `scripts/backup_db.sh` and `restore_db.sh` (#017), so rollback is
part of the operational story, and a reverse path that exists must work.

### The roadmap's specific suspicion is wrong, and that changes the justification

The roadmap called two migrations "not merely unexercised but suspect", the sharp
one being `20c019e280a9`'s `DROP EXTENSION IF EXISTS age;` **without `CASCADE`** —
"correct in a full `downgrade base` chain and a failure in any partial one."

That was checked rather than inherited. Against a scratch database at `c5a36d0`:

```
$ alembic upgrade head     # 20c019e280a9 → bd55d203ae25 → 99507a1b3027
                           # → c7f3a9b21d84 → f1e6a742b90c        OK
$ alembic downgrade base   # all five downgrades, in reverse       OK
$ alembic upgrade head     # rebuilds: 8 tables, age extension,
                           # learner_knowledge graph               OK
```

**The whole chain round-trips cleanly.** Two reasons the suspicion does not
materialise:

1. Alembic enforces chain order, so `20c019e280a9.downgrade()` only ever runs
   when going to `base` — which necessarily runs `bd55d203ae25`'s graph drop
   first. The "partial downgrade" that was supposed to fail is not reachable
   through alembic.
2. The stronger version of the concern — *another* AGE graph existing, which
   `bd55d203ae25` would not drop since it only knows `learner_knowledge` — was
   tested directly by creating `un_grafo_ajeno` and running `downgrade base`.
   It also succeeded, and took the foreign graph's schema with it: AGE registers
   graph schemas as members of the extension, so they drop *with* it rather than
   blocking it as dependents.

So there is nothing to fix. The justification is therefore not "repair a latent
break" but the weaker and more honest one: **five reverse paths work today, four
of them have never been run by anything but this investigation, and nothing keeps
them working.** The next schema change is free to break any of them silently, and
the discovery moment would be an incident.

That is a straightforwardly good reason to write a test, and a bad reason to
claim urgency. This spec claims none.

### One real finding

`DROP EXTENSION age` leaves the **`ag_catalog` schema behind**. After
`downgrade base` the database still has `ag_catalog` (empty), and the subsequent
`CREATE EXTENSION IF NOT EXISTS age` copes with it — which is why the re-upgrade
works. Undocumented, load-bearing, and currently true by luck rather than by
assertion.

### Consumer Impact

- **Whoever operates a rollback.** Today they would be running code that has
  never executed, on a production database, under incident pressure. After this,
  the reverse path has run on every commit.
- **Whoever writes migration six.** They get the round-trip harness for free, and
  a failure if their `downgrade()` does not restore a state the forward path can
  rebuild from — which is the property that actually matters and the one no
  existing test checks.
- **Not the learner.** No runtime or schema change.

### Roadmap Fit

Last of the three items about claims nothing checks — #029 for documentation
prose, #030 for dev data, this for the reverse migration path. It reuses their
mechanism: assert the claim, then verify the assertion by reintroducing the
defect.

Independent of #030 (different files; both touch `ROADMAP.md`). It is also the
sensible predecessor to any future decision about moving AGE DDL out of alembic —
that change would restructure this chain, and this is the harness that would
prove the restructure preserved behaviour.

---

## What

### Acceptance Criteria

- [ ] A test runs the full chain `upgrade head → downgrade base → upgrade head`
      and asserts the schema at each end: learner tables, `age` extension, and the
      `learner_knowledge` graph present after each upgrade; absent after the
      downgrade.
- [ ] **The second upgrade is asserted, not just performed.** A downgrade that
      leaves residue the forward path cannot rebuild from is the failure this
      spec exists to catch, and it is invisible if the test stops at `base`.
- [ ] Every revision's `downgrade()` is exercised individually — for each, the
      object it introduces is present at that revision, absent one step down, and
      present again on re-upgrade.
- [ ] The chain tests run against a **dedicated throwaway database**, never the
      shared session database.
- [ ] `tests/test_learner_display_name_migration.py`'s round-trip test is removed
      in favour of the per-revision coverage, and its non-round-trip assertions
      (nullability, singleton constraint) are kept. It currently downgrades the
      *shared* session database and restores it in a `finally` — the pattern this
      spec replaces.
- [ ] The `ag_catalog`-survives-`DROP EXTENSION` behaviour is asserted and
      commented, so the thing the re-upgrade depends on is pinned rather than
      incidental.
- [ ] Verified by reintroducing a defect: breaking a `downgrade()` body makes the
      relevant test fail, naming the revision.
- [ ] The added CI time is measured and reported in the decision record. If it
      exceeds ~15s, the tests get a marker and CI runs them as their own step.
- [ ] `ruff`, `mypy`, and the full `pytest` suite pass.

### Non-Goals

- **Not deleting the `downgrade()` bodies.** The roadmap's second resolution is
  explicitly rejected; see Why.
- **Not moving AGE DDL out of alembic.** The transactional mismatch between
  alembic's per-migration transaction and AGE's non-rollback-able DDL is a real
  architectural question — and it is now **#032**, sequenced after this one
  precisely so the harness built here can demonstrate that restructure preserves
  behaviour. Not a change to smuggle in behind a test.
- **Not asserting data survives a round-trip.** `downgrade base` drops every
  learner table; nothing preserves rows across it and nothing should pretend to.
  These tests assert *schema* reversibility only. Data safety is what
  `scripts/backup_db.sh` is for.
- **Not testing downgrade against a populated database.** A rollback with live
  rows is a plausible follow-up; the schema path has to work first, and mixing
  the two would obscure which failed.
- **No new migration**, and no change to any existing `upgrade()`.

### Open Questions

1. **Does the per-revision test justify its runtime?** Each step is a separate
   alembic invocation (thread + connection + transaction), and there are five
   revisions × three operations plus the full chain. Against an 18s suite this
   could be a material fraction. *Proposed: build it, measure it, and fall back
   to a marker if it exceeds ~15s* — a number rather than a feeling, decided in
   the decision record.

---

## How

### Approach

**1. A throwaway-database fixture (`tests/conftest.py`)**

The chain tests cannot use the session-scoped `db_pool`. That fixture creates
`hable_ya_test` once and every DB test in the session shares it; a
`downgrade base` mid-session would drop the schema out from under everything
that follows. The existing #021 test gets away with a `-1` and a `finally`
restore, which is exactly the fragility being removed.

`_drop_and_create_test_db` / `_drop_test_db` are generalised to take a database
name, and a new fixture creates a uniquely-named database, points
`settings.database_url` at it via the existing `_override_database_url` context
manager (alembic's `env.py` reads `settings.async_database_url`, so this is what
redirects migrations), yields, and drops it afterwards.

**2. `tests/test_migration_chain.py`**

Reuses the `_run` helper pattern from `test_learner_display_name_migration.py` —
`asyncio.to_thread(command.upgrade, config, "head")`, because alembic's `env.py`
calls `asyncio.run` internally and cannot run on a thread that already owns a
loop.

A table of revisions and the object each introduces drives the per-revision test:

| Revision | Probe |
|---|---|
| `20c019e280a9` | `age` extension in `pg_extension` |
| `bd55d203ae25` | `learner_profile` table + `learner_knowledge` in `ag_catalog.ag_graph` |
| `99507a1b3027` | `band_history` table + `turns.cefr_band` |
| `c7f3a9b21d84` | `sessions.mode` |
| `f1e6a742b90c` | `learner_profile.display_name` |

For each: `upgrade <rev>` → probe present → `downgrade -1` → probe absent →
`upgrade <rev>` → probe present. The last step is the one that catches a
downgrade leaving unrebuildable residue.

**3. Schema assertions**

Existence checks against `information_schema` and `pg_extension`, plus
`ag_catalog.ag_graph` for the graph — the same sources the probe used, so what
the test asserts is what was actually observed rather than what the migrations
appear to say.

### Confidence

**Level:** High

**Rationale:** The behaviour under test has been executed end to end against a
real database while writing this spec, including the failure mode the roadmap
predicted (which did not occur) and the sharper version of it (which also did
not). The remaining work is harness construction, and both patterns it needs
already exist in the repo — `test_learner_display_name_migration.py` for driving
alembic from a test, `conftest.py` for creating and dropping databases.

The only genuine unknown is runtime, which is Open Question 1 and is resolved by
measuring rather than deciding.

### Key Decisions

1. **Assert the re-upgrade, not just the downgrade.** The interesting property is
   not "does `downgrade()` run without error" but "does it leave a state the
   forward path can rebuild from". A downgrade that drops a table but orphans a
   type, a sequence, or a schema would pass the first check and fail the second —
   and `ag_catalog` surviving `DROP EXTENSION` proves this class of residue is
   real here, even though in this instance it happens to be benign.

2. **A dedicated database rather than restore-in-`finally`.** The existing test's
   pattern works for `-1` and does not scale to `base`: any failure between the
   downgrade and the restore leaves the shared database unusable for every test
   that follows, turning one failure into a cascade that obscures its own cause.
   A throwaway database makes the blast radius the test itself.

3. **Record the roadmap's error in the decision record rather than quietly
   fixing it.** The `CASCADE` suspicion was specific, plausible, written down
   twice, and wrong. Following #030 — where the spec's own claim about a test's
   efficacy proved false — the useful artifact is the correction and how it was
   found, not a spec that silently describes something else.

### Testing Approach

Per `OVERVIEW.md`'s Testing Suite: pytest, `asyncio_mode = "auto"`. These are
DB-backed and run in CI's `checks` job against the Postgres/AGE service.

| Test | Asserts |
|---|---|
| `test_full_chain_round_trip` | `head → base → head`; schema present at both heads, gone at base |
| `test_downgrade_base_leaves_only_alembic_version` | After `base`, `public` holds `alembic_version` and nothing else |
| `test_revision_round_trip[<rev>]` (×5) | Per-revision probe present → absent at `-1` → present again |
| `test_ag_catalog_survives_extension_drop` | The residue the re-upgrade depends on, pinned deliberately |

**Verification of the tests themselves** (#029's and #030's precedent): break a
`downgrade()` body — e.g. remove the `DROP TABLE IF EXISTS band_history` from
`99507a1b3027` — and confirm the relevant test fails naming that revision, then
revert. #030's lesson applies directly and is the thing to watch for: a test that
asserts an invariant the defect preserves is not a test of that defect, so the
reintroduced defect must be one the probe can actually observe.

**Regression surface:** new test file plus a generalisation of two conftest
helpers. The helper change touches the session `db_pool` fixture every DB test
depends on, so a mistake there is loud and immediate.
