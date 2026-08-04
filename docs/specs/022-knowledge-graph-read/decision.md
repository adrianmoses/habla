# Decision Record: Knowledge-Graph Read Path (or Honest Downgrade)

| Field | Value |
|---|---|
| id | 022 |
| status | implemented |
| created | 2026-08-04 |
| spec | [spec.md](./spec.md) |
| measurement | [graph-cost.json](./graph-cost.json) |

---

## Context

The spec framed the decision as the deliverable and required the evidence to
arrive before the documentation edits that encode it. That ordering earned its
place: the recommendation going in was argued from the shipped topology, and
implementation turned it into measurement.

Three things shaped the work beyond what the spec captured.

**The measurement was ambiguous, and that ambiguity was informative.** The
spec's OQ2 default was "leave the writes in place if the graph portion is a
small fraction of the ingest transaction." It is *not* a small fraction — 58.5%
— but it is 3.1ms against #013's measured ~2,050ms p50 turn floor, so 0.15% of
a turn's latency budget. The number could not settle OQ2 on its own terms. What
settled it was the failure mode, which the measurement had nothing to say
about.

**The first measurement run was wrong, in a way that would have flattered the
graph.** Relational mean came out at 18ms against a p50 of 2ms — the first
`VocabularyRepo.record` loading the `es_core_news_sm` spaCy model, a cost the
runtime pays once at boot, not per turn. Reporting it would have overstated the
relational side and understated the graph's share. A discarded warm-up
iteration fixed it, and the numbers then held across runs to within 0.4%.

**The new inspection surface immediately found something.** Running
`graph_summary` against a freshly reseeded dev database showed graph counts
that contradicted the relational data beside them:
`scripts/seed_dev_learner.py --reset` truncates the learner tables but
`TRUNCATE` does not touch AGE, so every reseed had been leaving stale graph
nodes behind. That is precisely the drift a write-only subsystem hides, found
within minutes of it having a reader.

## Decision

**The graph is an inspection artifact, not an input to adaptation.** Every
adaptive decision in the runtime — prompt profile, theme selection, leveling,
`/api/learner` — reads relational Postgres tables, and that is now written down
in `OVERVIEW.md` and `ARCHITECTURE.md` instead of being contradicted by them.

The downgrade is not merely editorial. Three things make it verifiable:

- **A read path exists** (`graph._fetch_cypher`, `graph.graph_summary`), so the
  graph is no longer write-only and a day when the writers silently stop is a
  day tests fail.
- **The writes moved out of the relational transaction** and are best-effort,
  counted on the sink's `graph_failed`. Decorative work can no longer roll back
  load-bearing state.
- **The shipped schema is documented** — including the three properties that
  make the roadmap's proposed adaptation impossible, so the next person to
  propose it starts from what exists.

The writes continue, so a future spec inherits history rather than an empty
graph. Making the graph load-bearing remains possible; it is a re-modelling
spec, not a query.

---

## Alternatives Considered

### OQ1 — adaptation vs honest downgrade

Resolved at approval, but the spec required it be *evidenced* rather than
asserted, so the candidate queries were run against the real graph rather than
reasoned about. The results:

| Candidate query | Current graph | SQL |
|---|---|---|
| Error patterns that co-occur — **the roadmap's own suggestion** | **Cannot.** Returns `[]`; no `ErrorPattern`↔`ErrorPattern` edge exists | One join on `error_observations.turn_id` → `gender_agreement` + `preterite_imperfect`, 17× |
| Scenario engagement history | **Lossier.** `MERGE … SET r.last_at` overwrites: 3 engagements → 1 edge, latest timestamp only | `sessions` keeps every row with `started_at` / `ended_at` / `mode` |
| Vocabulary ↔ theme association | **Cannot.** Zero `VocabItem`↔`Scenario` edges | `turns` ⋈ `sessions` |
| Top error patterns by frequency | **Can** | **Identical output**, from an indexed table |

**Option A: adaptation.** Wire graph reads into theme or prompt selection.
- Pros: would substantiate the product's headline claim as written.
- Cons: the graph is a star around `(:Learner {id: 1})` with only two edge
  types in practice. The one traversal it was imagined for returns nothing.
  Delivering it means designing a graph worth querying, backfilling it, beating
  the relational policy, and re-baselining the prompt tests.

**Option B: honest downgrade.** Document what it is, give it a reader, correct
the docs.
- Pros: removes the false claim now; preserves optionality since the data keeps
  accumulating; small and fully verifiable.
- Cons: ships no learner-visible improvement — the product is exactly as
  adaptive as it was yesterday.

**Chosen: B**, now evidenced. Every candidate query is either impossible on the
graph and easy in SQL, or identical in both and cheaper in SQL.

### OQ2 — where the per-turn graph writes run

**Option A: leave them in the ingest transaction.**
- Pros: no change to a working path; graph and relational state cannot diverge.
- Cons: a cypher failure discards the turn row, error observations and
  vocabulary — real learner state — to protect data that nothing reads.

**Option B: move them after the commit, best-effort.**
- Pros: a decorative failure can no longer destroy load-bearing state. Costs no
  latency: the same ~3.1ms of work, just outside the transaction.
- Cons: graph and relational state can now drift under failure.

**Chosen: B**, confirmed with the human once the measurement showed the latency
argument was weak on its own (0.15% of a turn). The justification is
robustness, not speed. The drift Option B admits is made visible by the
`graph_failed` counter on `/dev/observations` — the same posture
`ingest_failed` and `leveling_failed` already established for swallowed
failures.

### OQ3 — where the inspection read lives

Resolved at approval to a `graph` block on the dev-gated `/dev/learner`, and
implemented as specced. The alternative (`/dev/graph`) stays defensible if the
view grows past counts; nothing during implementation argued for it.

One refinement not in the spec: the block reports **known labels and edge types
at `0` rather than omitting them**. An absent key reads as "nothing to say"; an
explicit zero reads as "this stopped happening," which is the failure the read
path exists to catch.

### Decoding `agtype`

**Option A: `int(str(value))`** — the existing pattern in
`tests/test_learner_graph.py::_count`.
- Pros: already in the repo.
- Cons: works only for integers. asyncpg has no `agtype` codec, so every column
  arrives as `str` with JSON quoting — `label(n)` is `'"Learner"'`. This would
  raise on labels, or silently keep the quotes if coerced differently.

**Option B: `json.loads`.**
- Pros: correct for both scalars in one call.
- Cons: vertices/edges stringify with a `::vertex` suffix that is not valid
  JSON — handled by falling through to the raw string, since nothing here
  returns whole nodes.

**Chosen: B.** The test helper keeps `int(str(...))` deliberately, as an
independent oracle: asserting the read primitive against itself would be
circular.

---

## Tradeoffs

**What this optimises for: an honest map.** The largest deliverable is that
`OVERVIEW.md` and `ARCHITECTURE.md` now describe the system that exists. The
cost is that #022 ships **no learner-visible improvement whatsoever**. Judged as
a feature it delivers nothing; judged as removing a false claim from the
product's headline description, it is the point.

**What it gives up: transactional coherence between graph and relational
state.** Before, they could not diverge. Now a graph outage leaves the graph
behind while turns keep landing. That is deliberate — coherence with a
subsystem nothing reads was being bought with the integrity of a subsystem
everything reads — but it is a real property that was traded away, and
`graph_failed` is the only thing that surfaces it.

**What it gives up: the chance to reclaim ~3.1ms and 13 round trips per
turn.** Deleting the writers was available and rejected (spec Key Decision 4).
The data is not reconstructible after the fact, so the cost buys optionality
for a future spec. If that spec never comes, this is pure waste — a
deliberately accepted bet.

**What it does not resolve: multi-user.** #021 Key Decision 4 named the
per-learner-counters-on-shared-nodes problem as blocked behind this decision.
#022 answers "is the graph worth fixing for multi-user?" with "the graph is not
load-bearing, so that re-model is not on anyone's critical path" — which
unblocks the accounting without doing the re-model.

---

### Spec Divergence

| Spec Said | What Was Built | Reason |
|---|---|---|
| OQ4: cover SQL and cypher, "with an explicit opt-out marker" | Both covered; **no opt-out mechanism built** | Empirically unnecessary. All nine README statements execute; each block runs its statements in order on one connection, so the block's own `SET search_path = ag_catalog, …` covers the cypher after it. Building an unused mechanism is the exact class of speculative machinery this spec exists to remove. Add it when a snippet needs one. |
| OQ2 default: "leave them in place if the graph portion is a small fraction of the ingest transaction" | Moved out of the transaction | The measurement did not fit the default's terms — 58.5% of the transaction, 0.15% of a turn. Decided on the failure mode instead, with the human. |
| Approach step 4: inspection read returns counts and top nodes | Also reports known labels/edges at `0` when absent | An omitted key hides a writer that stopped; an explicit `0` surfaces it. |
| — (not in spec) | `graph_failed` counter on the sink and `/dev/observations` | Forced by the OQ2 move: a survivable failure that is also silent recreates the invisibility this spec exists to remove. Follows the `ingest_failed` / `leveling_failed` convention. |
| — (not in spec) | `seed_dev_learner.py --reset` clears the graph and mirrors aggregates into it | Found by the new reader: `TRUNCATE` does not touch AGE, so reseeds left stale nodes contradicting the relational data. Without the mirror, the new block is permanently empty in dev and cannot be eyeballed. |

Everything else was built as written. All acceptance criteria are met.

---

## Spec Gaps Exposed

1. **`seed_dev_learner.py` and the graph had been silently diverging.** Fixed
   here, but the general shape is worth noting: `TRUNCATE` does not touch AGE,
   so any future reset path must clear the graph explicitly. `conftest.py`'s
   `clean_learner_state` already did; the seed script did not. **Nothing tests
   the seed script**, which is how the two drifted apart.

2. **The spec's own OQ2 default was unanswerable as phrased.** "A small
   fraction of the ingest transaction" turned out to be the wrong denominator —
   the useful ratio is against a turn's latency budget, and even that did not
   decide it. **Worth generalising:** a spec that defers a decision to a
   measurement should say which comparison would settle it, or it will produce
   a number that still needs a judgment.

3. **`OVERVIEW.md` lines 78, 110 and 111 remain stale** and were deliberately
   left (spec Non-Goal). They still describe the pre-implementation state — "No
   DB code is implemented yet", "Learner model is schema-only", `aiosqlite` as
   the vendored driver. Two documentation defects were corrected here while
   three sat untouched a few lines away. **Roadmap candidate:** a documentation
   pass over `OVERVIEW.md`'s Audit Notes, which are frozen at a state the repo
   left long ago.

4. **`ARCHITECTURE.md` is still marked `status: inferred`** and its component
   map still lists stubs and the deleted `finetune/` package. #022 corrected the
   two graph-related lines and the AGE schema section; the rest of the document
   remains a hazard for anyone trusting it over the code.

---

## Test Evidence

**Full suite — 538 passed, from 524 before this spec (+14):**

```
$ uv run pytest -q
538 passed, 6 deselected, 9 warnings in 19.52s
```

**The new and extended files:**

```
$ uv run pytest tests/test_learner_graph.py tests/test_readme_snippets.py \
      tests/test_dev_endpoints.py tests/test_log_turn_ingestion.py -q
36 passed in 2.17s

$ uv run pytest tests/test_learner_graph.py -q -k "fetch_cypher or graph_summary"
5 passed, 6 deselected in 0.37s
```

**Lint and types:**

```
$ uv run ruff check hable_ya/ api/ eval/agent/ tests/ scripts/
All checks passed!

$ uv run mypy hable_ya/ api/ eval/agent/
Success: no issues found in 65 source files
```

**The measurement (`graph-cost.json`, 50 turns, two runs agreeing to 0.4%):**

```
stage           n      p50      p95     mean
relational     50        2        3        2
graph          50        3        4        3

graph share of the ingest transaction (p50): 58.5%
cypher round trips per turn: mean 13.4, max 14
```

**The candidate queries, run against the real graph:**

```
== what edge types exist at all ==
  [('MADE_ERROR', 3), ('PRODUCED', 17)]

== Q1: which error patterns CO-OCCUR (same turn)? ==
  graph: []
  sql:   [('gender_agreement', 'preterite_imperfect', 17)]

== Q2: does the graph retain scenario HISTORY? ==
  edges after 3 engagements: 1   last_at retained: 2026-01-03T00:00:00+00:00

== Q3: is any VocabItem linked to a Scenario/theme? ==
  graph: [(0,)]

== Q4: top error patterns by frequency (the one thing the graph CAN do) ==
  graph: [('preterite_imperfect', 17), ('gender_agreement', 17), ('ser_estar', 17)]
  sql:   [('preterite_imperfect', 17), ('gender_agreement', 17), ('ser_estar', 17)]
```

**The README test catches the defect it exists for.** Reintroducing the
original query:

```
$ uv run pytest tests/test_readme_snippets.py -q
E   asyncpg.exceptions.UndefinedColumnError: column "created_at" does not exist
E   Failed: README.md block 1 has a statement that does not run:
2 failed, 2 passed in 0.38s

# restored
4 passed in 0.34s
```

**The inspection surface, against a seeded dev database** — cross-checked
against a direct cypher query, and showing the counter duplication side by
side, which is what it was designed to expose:

```
GET /dev/learner -> graph block:
{
  "graph": "learner_knowledge",
  "nodes": { "Learner": 1, "Scenario": 61, "VocabItem": 15, "ErrorPattern": 7 },
  "edges": { "PRODUCED": 15, "MADE_ERROR": 7, "ENGAGED_WITH": 12 }
}
top_error_patterns[0]:            {'category': 'gender_agreement', 'occurrences': 1}
relational top_errors[0]:         {'category': 'gender_agreement', 'count': 14, ...}

/dev/observations counters: {'missing': 0, 'ingest_failed': 0, 'band_missing': 0,
                             'leveling_failed': 0, 'graph_failed': 0}

direct cypher VocabItem count: 15 | endpoint said: 15
```

**Regression guards — the relational path and the prompt are untouched:**

```
$ uv run pytest tests/test_log_turn_ingestion.py -q
14 passed in 1.61s        # the 12 pre-existing ones unmodified

$ uv run pytest tests/test_prompts.py -q
37 passed in 0.05s

$ git diff --stat -- hable_ya/pipeline/
(empty)

$ uv run pytest tests/e2e -m e2e -q
6 passed in 6.72s         # no SPA surface in this spec; unchanged
```
