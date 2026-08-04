# Spec: Knowledge-Graph Read Path (or Honest Downgrade)

| Field | Value |
|---|---|
| id | 022 |
| status | approved |
| created | 2026-08-04 |
| approved | 2026-08-04 |

---

## Why

`OVERVIEW.md:19` sells the product on "a knowledge-graph–based learner model."
The graph exists, it is written on every turn, and **nothing has ever read it.**

`hable_ya/learner/graph.py` is five functions, all writers. Its only primitive,
`_run_cypher`, calls `conn.execute` and returns `None` — it *structurally
cannot* return rows. There is no read path to switch on, because none was ever
built. Every piece of live adaptivity is relational:

| Behaviour | Actually driven by |
|---|---|
| Tutor prompt profile | `LearnerProfileSnapshot` → `render.py` |
| Theme selection | `themes.py` + `learner_profile.band` |
| Leveling / promotion | `turns`, `band_history`, `leveling/policy.py` |
| `/api/learner` payload | `error_counts`, `vocabulary_items` |
| `/dev/learner` | the same relational reads (`learner/read.py`) |

So the graph is pure cost. Each turn's ingest transaction
(`ingest.py:63-78`) issues **two cypher round trips per distinct error
category and two per lemma** — a turn producing eight lemmas and two error
categories runs twenty statements against AGE, inside the same transaction as
the relational writes, for data no code consults.

This is the same class of defect the last four specs have been removing. #020
found screens inventing progress a learner had not made. #021 removed a
fabricated name. #025–#028 are queued because aggregates claim more than they
measure. This one is the architecture claiming a capability it does not have —
and it is the oldest of them, dating to the pre-cloud design.

The spec's job is to end the ambiguity in one direction or the other: make the
graph load-bearing, or say plainly that it is not.

### Consumer Impact

- **The learner.** Under the recommended branch (see OQ1), *no visible change*
  — and that is the honest answer. Under the adaptation branch they would get
  theme and prompt selection informed by error-pattern structure. Saying which
  of those is being delivered, rather than implying the second while shipping
  the first, is the point.
- **The operator** gets the graph's actual schema documented for the first
  time, a working set of inspection queries, and — for the first time — a
  measured answer to "what do those per-turn cypher writes cost me?"
- **Anyone following `README.md`** stops hitting a query that cannot run.
  `README.md:154` documents `SELECT id, session_id, created_at, cefr_band,
  l1_reliance_score FROM turns` — `turns` has `timestamp`, not `created_at`,
  and has no `l1_reliance_score` column at all (that signal is computed in
  `aggregations.py` and never stored per-turn). Two errors in five columns, in
  the first query an operator would try.
- **Future planning turns** stop re-deriving whether the graph matters.
  `ARCHITECTURE.md:234` still lists the concrete AGE schema as
  `[INFERRED: uncertain] … not yet designed`, which has been false since
  `bd55d203ae25` shipped it.

### Roadmap Fit

Depends on nothing. Everything it touches is already built.

It **unblocks accounting elsewhere**: #021's Key Decision 4 records that
reversing the single-tenant non-goal requires an AGE re-model that is "blocked
on #022 deciding whether the graph is load-bearing at all." `VocabItem` and
`ErrorPattern` nodes are global and carry counters on the node
(`graph.py:85,118`) while the per-learner edge carries its own — two learners
producing *viajar* would inflate a shared node. That cannot be fixed before
knowing whether the graph is worth fixing.

It is **adjacent to but independent of #025–#028**. Those concern the accuracy
of what the relational aggregates claim; this concerns whether a whole
subsystem is claimed to do something it does not. No shared code, no ordering
constraint.

---

## What

### Acceptance Criteria

These hold under either branch of OQ1 — the decision itself is the deliverable,
and the work below is what makes it verifiable rather than editorial.

- [ ] The load-bearing question is **answered in writing** in the decision
      record, with the evidence behind it, and reflected in `OVERVIEW.md` and
      `ARCHITECTURE.md`.
- [ ] `OVERVIEW.md:19`'s "knowledge-graph–based learner model" is either
      substantiated by a shipped read path or reworded to describe what the
      graph actually is.
- [ ] `ARCHITECTURE.md:234`'s `[INFERRED: uncertain]` AGE-schema line is
      replaced by the **shipped** schema: labels (`Learner`, `Scenario`,
      `VocabItem`, `ErrorPattern`), edges (`PRODUCED`, `MADE_ERROR`,
      `ENGAGED_WITH`), and the properties each carries — including that
      counters are duplicated on node *and* edge, and why (`occurrences` rather
      than `count`, per `graph.py:102-107`).
- [ ] `README.md`'s `turns` query runs: `created_at` → `timestamp`, and
      `l1_reliance_score` removed or replaced with a column that exists.
- [ ] **Every** SQL and cypher snippet in `README.md` executes against a seeded
      database — verified by a test, not by inspection, so this cannot rot
      again.
- [ ] The per-turn graph write cost is **measured** (round trips and wall-clock
      against a local AGE instance) and recorded, so "is this cheap?" stops
      being a guess.
- [ ] The graph is read by *something* in the repo — at minimum an inspection
      surface (OQ3), so "write-only" is no longer true in either branch.
- [ ] A graph read primitive exists that can return rows, with the same
      identifier-safety posture as the writers (`_IDENT_RE`), since
      `_run_cypher` cannot.
- [ ] Whatever the branch, the ingest transaction's **relational** writes are
      unchanged and `tests/test_log_turn_ingestion.py` passes unmodified.

Under the recommended branch (honest downgrade), additionally:

- [ ] The rendered tutor system prompt is **byte-identical** — the cold-start
      prompt-identity tests pass unmodified and `git diff --stat` on
      `hable_ya/pipeline/` is empty.

### Non-Goals

- **Multi-user graph re-modeling.** #021 Key Decision 4's re-model stays
  deferred. This spec decides whether the graph matters; it does not restructure
  it for a tenancy model that is a standing non-goal.
- **New node or edge types.** No `Skill`, no `Concept`, no error-to-error
  edges. If the adaptation branch wins, the modelling work it implies is its
  own spec (see Key Decision 2).
- **Removing Apache AGE from the stack.** Even under the downgrade, the
  extension stays: it is already in the image, the migration chain creates the
  graph, and inspection queries use it.
- **Dropping the graph tables or the accumulated data.** Whatever is decided,
  no destructive migration.
- **Graph reads in the production `/api/learner*` payload.** Unless OQ1
  resolves to adaptation, graph reads stay dev-gated.
- **#025–#028's aggregate accuracy work.** Same family, different specs.
- **Fixing the rest of `OVERVIEW.md`'s rot.** Lines 78, 110 and 111 still
  describe the pre-implementation state ("No DB code is implemented yet",
  "Learner model is schema-only", `aiosqlite`). Real, but out of scope — noted
  here so the next reader knows it was seen, not missed.

### Open Questions

**All four were resolved at their recommended default on 2026-08-04, at
approval** — except OQ2, whose resolution *is* to decide after the measurement
the Approach requires (see below). They are kept with their reasoning intact:
the alternatives are what the acceptance criteria defend against, so deleting
them would lose why the criteria are phrased as they are.

**OQ1 — Adaptation, or honest downgrade?** The central question.

*Adaptation* means wiring graph reads into theme or prompt selection — the
roadmap's suggestion is "error-pattern neighborhoods informing theme/prompt
selection." The obstacle is that **there are no neighbourhoods**. The shipped
graph is a star around `(:Learner {id: 1})`: `VocabItem`s connect to the
learner and to nothing else, `ErrorPattern`s likewise, `Scenario`s likewise.
There is no edge between two vocabulary items, or two error patterns, or an
error pattern and a scenario. Every traversal available today is one hop from a
node whose counters duplicate a relational table that has real indexes.

So adaptation is not "write a query" — it is *design a graph worth querying*,
then backfill it, then find an adaptation policy that beats the relational one,
then re-baseline the prompt tests. That is at least the size of #023, on a
subsystem with no demonstrated value.

*Honest downgrade* means: document what the graph is (an inspection artifact
and an append-only record of learner activity), ship a read path for exactly
that, correct the two docs that oversell it, and stop.

**Recommend the honest downgrade**, on the principle the last four specs have
been applying: remove the false claim first, and let a real need justify the
feature later. The graph keeps accumulating data, so the optionality is not
lost — a future spec can still query five months of history. What is lost is
only the implication that it is doing something today.
**Resolved: honest downgrade.** The validation steps still run first — if the
candidate-query table (Approach step 2) turns up a query the current graph can
answer and SQL cannot, that is a finding worth surfacing before the doc edits
land, and it belongs in the decision record either way.

**OQ2 — Keep, move, or drop the per-turn writes?**
(a) keep them where they are; (b) move them out of the ingest transaction so a
graph failure cannot roll back relational learner state; (c) stop writing.

(c) is rejected outright: it destroys the optionality that makes the downgrade
palatable, and the data is not recoverable afterwards. Between (a) and (b), the
answer depends on the measurement the acceptance criteria require — twenty
cypher statements per turn is a real number in a per-turn transaction, and #024
exists because latency in this path is a known concern.
**Recommend deciding after measuring**, with a bias to (b) if the cost is
non-trivial: graph writes are decorative under the downgrade, so they should
not be able to fail a turn's real persistence.
**Resolved: decide at Approach step 1, from the measurement.** This is a
deliberate deferral, not an unresolved question — the decision has an owner
(the implementer), an input (the measured cost), and a default (leave them in
place if the graph portion is a small fraction of the ingest transaction).
Whichever way it goes, the number and the reasoning go in the decision record.

**OQ3 — Where does the inspection read live?**
(a) extend the existing dev-gated `/dev/learner`; (b) a new `/dev/graph`;
(c) a script under `scripts/`.
**Recommend (a)** — `/dev/learner` is already the inspector, already dev-gated
(`settings.dev_endpoints_enabled`), already shares `learner/read.py` with
production so the two cannot drift. A graph block on the payload it already
returns is the smallest honest surface. (b) is defensible if the graph view
grows past a few counts.
**Resolved: (a) — a graph block on `/dev/learner`.**

**OQ4 — Does the README-snippet test cover cypher as well as SQL?**
The SQL blocks are straightforward to execute against the test database. The
cypher blocks need `ag_catalog` on the `search_path` and one of them is a
`SET search_path` statement that is setup, not a query.
**Recommend covering both**, with the extractor skipping statements marked by
an HTML comment — an explicit opt-out beats a test that silently checks half
the file.
**Resolved: both, with an explicit opt-out marker.** If a snippet needs an
opt-out, the marker must say *why* — an unexplained skip is how the `turns`
query survived.

---

## How

### Approach

Ordered so the evidence arrives before the decision that depends on it.

**1. Measure, before deciding anything.** A script or test that ingests a
representative turn against a local AGE instance and reports: cypher round
trips per turn (derivable — `2 × distinct_categories + 2 × lemmas`, plus 2 for
`start_session`), and wall-clock for the graph portion of the ingest
transaction versus the relational portion. This is the input to OQ2 and one of
the inputs to OQ1.

**2. Enumerate the candidate graph queries, and check each against SQL.** A
written table: for each plausible adaptation query ("which error patterns
co-occur", "which scenarios preceded improvement", "which vocabulary clusters
with which theme"), record whether the *current* graph can answer it, whether
SQL can, and at what cost. This is the honest test of OQ1 — if some query is
genuinely graph-shaped and the data is already there, the adaptation branch
gets real support rather than aspiration. If every row says "SQL, more cheaply,"
the downgrade is evidenced rather than asserted.

**3. Add a read primitive** to `hable_ya/learner/graph.py`:

```python
async def _fetch_cypher(
    conn: asyncpg.Connection, body: str, *columns: str
) -> list[asyncpg.Record]:
    ...
```

`_run_cypher` uses `conn.execute` and cannot return rows, so reads need their
own function. AGE requires the result column list to be declared in the `AS
(...)` clause, which is why the column names are a parameter. Same
`_IDENT_RE` filtering discipline as the writers — a read predicate is still
interpolated into a dollar-quoted body.

**4. The inspection read** (OQ3): counts by label, counts by edge type, and the
top vocabulary/error nodes by their node-level counter — deliberately
*including* the counter the relational tables also hold, because seeing them
side by side is what makes the duplication visible to an operator.

**5. The documentation corrections**, which are the actual point:

- `ARCHITECTURE.md:234` — replace the `[INFERRED: uncertain]` schema line with
  the shipped schema, read out of `graph.py` rather than imagined.
- `ARCHITECTURE.md:229` — extend the "Knowledge graph storage" scope decision
  with what the graph *is for*, per OQ1.
- `OVERVIEW.md:19` — reword or substantiate the headline claim.
- `README.md:154` — fix the broken `turns` query.

**6. The README-executes test**, so step 5 cannot rot: extract fenced ` ```sql `
blocks, split into statements, execute each against the seeded test database,
and assert none raise. Statements that are setup rather than queries, or that
are intentionally illustrative, opt out via an HTML comment the extractor
honours.

### Confidence

**Level:** Medium

**Rationale:** The *mechanics* are all High. Every file involved is small and
already understood: `graph.py` is 165 lines, the dev endpoint exists, the doc
edits are surgical, and `tests/test_learner_graph.py` already has a
`clean_graph` fixture and a working pattern for asserting cypher results — so
even the read primitive has a shipped reference for its result shape.

Medium is entirely about **OQ1, which is a judgment this spec should not
pre-empt with a code sketch.** The recommendation above is argued from the
shipped topology, but "is there an adaptation this graph could serve" is the
kind of question that looks settled until someone names the query that changes
it. Steps 1 and 2 exist precisely to convert that judgment into evidence before
any of the irreversible-feeling doc edits land.

There is also a smaller unknown: whether the README-snippet test is pleasant or
fiddly. Extracting and executing SQL from markdown is easy; doing it in a way
that stays readable when a snippet legitimately needs seeded state is the part
that could turn ugly. If it does, the fallback is asserting the schema
references (column names against `information_schema`) rather than executing
the statements — weaker, but still enough to have caught `created_at`.

**Validate before proceeding:**

1. Run step 1 (measure) and step 2 (the query table) and put both in front of a
   human **before** touching `OVERVIEW.md` or `ARCHITECTURE.md`. The doc edits
   encode the decision; they should not precede its evidence.
2. Resolve OQ1 explicitly at approval, as #021 did with its three — the
   acceptance criteria above are branch-aware, but the Approach only details
   the recommended branch.

### Key Decisions

**1. The decision is the deliverable, not the code.**
This spec could have been written as "add graph reads" and quietly shipped a
query nobody needed, which is how the graph got here. Framing the deliverable
as *an answered question, evidenced and documented* means the honest-downgrade
outcome is a success rather than a spec that failed to build anything.

**2. Adaptation, if chosen, is a re-modeling spec — not this one.**
The shipped graph is a star, and the roadmap's own suggestion (error-pattern
neighbourhoods) requires edges that do not exist. Pretending otherwise would
produce either a trivial query dressed up as adaptivity, or a scope explosion
mid-implementation. If OQ1 resolves to adaptation, this spec should end at the
evidence and hand off to a successor with the modelling work scoped properly.

**3. A read primitive is added even under the downgrade.**
It would be cheaper to inspect the graph with raw SQL in a script. But
"write-only" is the specific criticism, and answering it with "still write-only,
but now documented as such" leaves the same asymmetry — no test exercises a
read, so nothing detects the day the writes silently stop. A real read path,
however modest, makes the graph a verifiable artifact.

**4. Keep the writes.**
Under the downgrade the graph earns nothing today, and the tempting move is to
delete the writers and reclaim the per-turn cost. Rejected: the data is not
reconstructible after the fact, and the whole argument for the downgrade is that
optionality is preserved. A future spec with a real query wants history, not an
empty graph and a migration. OQ2 covers *where* the writes run, not whether.

**5. `_IDENT_RE` discipline extends to reads.**
The filter exists because cypher bodies are f-string-interpolated into a
dollar-quoted literal (`graph.py:9-14`). A read predicate is interpolated the
same way, so it needs the same filtering — and #021 Key Decision 3 deliberately
kept learner free-text out of the graph precisely because of this. Nothing in
this spec relaxes that.

### Testing Approach

Per `OVERVIEW.md`'s testing suite: pytest with `asyncio_mode = "auto"` and DB
tests against real Postgres, plus the browser and Vitest layers where they
apply — neither applies here, since nothing in this spec reaches the SPA.

**pytest — `tests/test_learner_graph.py` (extends the existing 6):**

- The read primitive returns rows for a graph seeded by the existing writers,
  using the `clean_graph` fixture already in the file.
- Label counts and edge counts match what the writers produced — the assertion
  that would fail the day a writer silently stops.
- An unsafe identifier in a *read* predicate is rejected the same way the
  writers reject one (`test_unsafe_identifier_is_skipped` is the reference).
- Reading an empty graph returns empty, not an error — a fresh deployment must
  not 500 its inspector.

**pytest — `tests/test_dev_endpoints.py` (if OQ3 resolves to `/dev/learner`):**

- The graph block appears in the payload and matches directly-queried counts.
- The endpoint stays dev-gated: absent when `dev_endpoints_enabled` is false.

**pytest — new `tests/test_readme_snippets.py`:**

- Every ` ```sql ` block in `README.md` executes against the seeded test
  database without raising. Pinned regression: the `turns` query, which fails
  today on both `created_at` and `l1_reliance_score`.
- Cypher blocks likewise, with `ag_catalog` on the `search_path` (OQ4).

**Measurement (step 1), recorded not asserted:**

- Round trips and wall-clock for the graph portion of `ingest`, reported in the
  decision record. Not a pass/fail test — a number that makes OQ2 answerable
  and that a future reader can compare against.

**Regression guards:**

- `tests/test_log_turn_ingestion.py` passes unmodified — the relational writes
  are untouched whatever happens to the graph ones.
- Under the downgrade: the cold-start prompt byte-identity tests pass
  unmodified and `git diff --stat` on `hable_ya/pipeline/` is empty.

**Deferred:** nothing here needs a keyed host or a provider. Like #019–#021,
the whole spec is verifiable against a local Postgres with placeholder cloud
credentials.
