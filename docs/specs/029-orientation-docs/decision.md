# Decision Record: Orientation docs — re-baseline as a living reference, and make the claims checkable

| Field | Value |
|---|---|
| id | 029 |
| status | implemented |
| created | 2026-08-08 |
| spec | [spec.md](./spec.md) |

---

## Context

The roadmap entry asked for a decision before an edit pass: are `OVERVIEW.md`
and `ARCHITECTURE.md` a living reference or a dated audit snapshot? It framed
the item that way because three specs in a row had corrected a line or two and
left the rest, so "keep them current" had visibly failed.

Establishing the facts changed the framing, and it changed what the fix had to
be. **This was never drift.** Commit `6451c4d` states it outright — hable-ya's
`OVERVIEW`/`ARCHITECTURE`/`README` "come over as on-device docs to be rewritten
by #015" — and #015's scope was the on-device → cloud posture, which it
discharged. The audit sections were never rewritten. So both files were an audit
of a *different repository* at a pre-implementation moment, and had never been
true of habla. The residue was still on the surface at implementation time: an
`inferred-from` header naming `hable-ya/config.py` and `finetune/format.py`
(upstream paths, under a hyphenated package directory this repo has never had),
and `OVERVIEW.md:30` citing "specs 029/049" — hable-ya's spec numbers, where
this repo's #029 is this document and #049 does not exist.

That reframing matters because it rules out the obvious remedy. If the documents
had drifted, a careful correction pass would restore them. Since they were
describing another codebase, a correction pass would have been a rewrite wearing
an audit's structure — and would have re-created the same hand-maintained
inventory that had already gone stale.

Two things shaped the work beyond the spec. The owner resolved both open
questions before approval (living reference; `analiza` and `web` as first-class
systems), which is what licensed deleting sections rather than fixing them. And
the spec's one flagged risk — the path-extraction regex — did fire on first run,
which is what produced the component-map change described below.

## Decision

**`OVERVIEW.md` and `ARCHITECTURE.md` remain the living orientation documents
the README points at, de-scoped to claims that change by decision rather than by
commit, with the one mechanically checkable class of claim now enforced by a
test.**

The governing rule, applied section by section: *keep a claim only if it changes
by decision; delete it if it changes by commit.* Product intent, consumers,
decided non-goals, external dependencies, constraints, data flow and the AGE
schema all change when someone decides something — and a decision record is the
natural moment to update them, which is exactly how #022's schema section
correctly arrived. Per-file implementation status changes every commit, is
already answered authoritatively by `git ls-files` and the test suite, and is
what rotted.

So `OVERVIEW.md` lost "Capabilities Observed", "Gaps and Inconsistencies" and
"Uncertain Areas" entirely; `ARCHITECTURE.md` lost its per-file
`[stub]`/`[implemented]`/`[partial]` component map; both lost their
`status: inferred` headers, their `inferred-from` lists, and three accumulated
migration-note blockquotes. What replaced the component map is a table of full
repo-relative paths and responsibilities, with no status labels. `analiza/` and
`web/` are documented as first-class systems, the former by link to its own spec.

`tests/test_doc_paths.py` then fails the build if either document names a path
that does not exist.

---

## Alternatives Considered

### What the documents are for

**Option A — Living reference, de-scoped.** Keep them where the README points,
delete the sections that rot by design.
- Pros: preserves genuinely durable content that is load-bearing elsewhere
  (#021's single-tenant reversal cost, #022's graph posture, #013's latency
  floor); no README churn; the remainder is maintainable at the rate decisions
  are actually made.
- Cons: still requires discipline, just much less of it; "living" is a claim
  that has to be re-earned each spec.

**Option B — Freeze as a dated audit snapshot.** Move both to `docs/artifacts/`
with a banner, write a thin new orientation doc, repoint `README.md:25-29`.
- Pros: honest about provenance; zero maintenance burden; no pretence.
- Cons: strands the durable content or forces it to be copied into the new
  document — creating the second copy this work exists to eliminate. The
  precedent `docs/artifacts/hable-ya/` sets is for *inherited design artifacts*,
  not for the document the README calls the product entry point.

**Option C — Full re-baseline, same structure.** Correct all 40+ component-map
entries and keep the inventory.
- Pros: highest fidelity today; smallest conceptual change; nothing is lost.
- Cons: no mechanism prevents the next drift. It would pass an audit today and
  be false again within a few specs — which is precisely the history.

**Chosen: A**, by the owner. C was rejected on the evidence that it is what has
already been tried, in effect, four times. B is the right answer for a document
nobody will maintain, and would have been chosen if these files held only the
audit material — but they hold decided constraints that later specs cite.

### How to make the component map checkable

The extractor's first run flagged six false positives across the two documents
(`/api/learner`, `/dev/learner`, `/ws/session`, `apache/age:release_PG18_1.7.0`,
`postgresql://…`, and bare sibling links like `ARCHITECTURE.md`). Tightening
those was mechanical. The real problem was different: the component map was a
fenced ASCII tree, and backtick-based extraction does not see inside fences — so
the section that had rotted the worst was the one the test would not have
covered.

**Option A — Teach the extractor to parse the tree.** Track indentation inside
fenced blocks, reconstruct `api/` + `  routes/` into `api/routes/`.
- Pros: keeps the tree's scannability; no doc restructuring.
- Cons: ~25 lines of indentation-inheritance logic that has to coexist with the
  ASCII data-flow diagrams in the same document; fragile against reformatting;
  a test whose own correctness becomes non-obvious.

**Option B — Restructure the map as a table of full paths.**
- Pros: every row is independently checkable by the existing five-line rule; the
  map becomes greppable; no nesting ambiguity; the extractor stays simple enough
  to read in one pass.
- Cons: loses the visual hierarchy of a tree; paths repeat their prefixes.

**Chosen: B.** Changing the document to fit a simple check beat complicating the
check to fit decorative formatting — and the tree's hierarchy was carrying less
information than it appeared to, since the directories are only two deep.

### Scope of the check

**Option A — Assert paths are not dangling.** What was built.
**Option B — Broader verification**: that documented endpoints respond, that
documented config keys exist in `config.py`, that documented CI jobs are in the
workflow.

**Chosen: A.** Same reasoning #022 used when it chose to execute the README's
SQL rather than to lint its prose: a narrow check that runs beats a broad one
that is a promise. B is a real candidate later, and B's most valuable member
(config keys) is noted as a follow-up below.

---

## Tradeoffs

**Given up: the ability to answer "is X implemented?" from the documents.**
Deliberately. That question now requires `git ls-files`, the test suite, or the
roadmap. This is a real loss for a reader skimming without a checkout — and it
is the loss that buys everything else, because that question is exactly the one
whose answer went stale.

**Given up: fidelity of the component map.** A directory-level map says less
than a per-file one. Someone looking for where `log_turn` arguments are
normalized now has to grep `hable_ya/pipeline/prompts/` rather than read
`render.py` off a line in the map. Accepted: grep is authoritative and free,
while the map's per-file detail was neither.

**Optimised for: the next reader being an agent.** Both documents now lead with
what they are and what they deliberately omit, so a reader that trusts them is
not misled about their scope. The `verified-at` commit lets staleness be judged
against `git log` instead of the prose's own confidence.

**Accepted risk: the floor counts in `MIN_PATHS` are a heuristic.** They are set
at 10 and 20 against actual counts of 15 and 38. A future edit that halves a
document's path references without breaking the extractor would pass. The guard
is aimed at the failure it can actually catch — an extractor that silently
matches nothing — not at policing document size.

**Not addressed: prose accuracy.** The test asserts a path is not dangling. A
document can name every path correctly and still describe what they do
incorrectly. Review remains the only check on that, and the spec's evidence
table was the checklist used here.

---

### Spec Divergence

Two divergences, both discovered during implementation.

| Spec Said | What Was Built | Reason |
|---|---|---|
| Replace the component map with "a systems-level map that names directories and their responsibility" — implicitly still a fenced tree, as the existing one was | A markdown **table** of full repo-relative paths | The spec did not anticipate that backtick extraction cannot see inside code fences. Left as a tree, the highest-value target would have been invisible to the very test written to protect it. See "How to make the component map checkable" above. |
| Path resolution against the repo root | Repo root **or** the document's own directory | `OVERVIEW.md` links its siblings as `ARCHITECTURE.md` and its children as `analiza/spec.md`. Both are correct markdown links and neither resolves from the root; rejecting them would have forced the documents to write worse links to satisfy the test. |

Everything else matched. All twelve rows of the spec's evidence table are
resolved, `KNOWN_ABSENT` shipped empty as the spec hoped, and the test was
verified by reintroducing a defect as required.

The one acceptance criterion that needed no work: `README.md:25-29`'s one-line
descriptions still match both documents. "Component map, data flow, constraints"
remains accurate — the map survived, in a different shape.

---

## Spec Gaps Exposed

1. **`pyproject.toml` still describes the on-device project.** `name =
   "hable-ya"`, `description = "On-device Spanish language acquisition voice
   agent"` — for a package whose defining posture is that it is *not* on-device.
   Deliberately out of scope here (#029 owns two documents, not packaging
   metadata), and it is the same #000 inheritance in another file. Worth a small
   roadmap item, since `pyproject.toml` is what a package index would show.

2. **Upstream spec numbers are cited in code comments.** The `spacy` dependency
   comment in `pyproject.toml` credits vocabulary tracking to "(#029)" — that is
   hable-ya's #029, not this one. Harmless until someone follows the reference.
   A grep for `#0\d\d` in comments would find how widespread this is; nobody has
   run it.

3. **A follow-up worth more than this spec's own check: verify documented config
   keys against `config.py`.** `ARCHITECTURE.md`'s Configuration section lists
   ~20 setting names. They were hand-verified for this record, but nothing keeps
   them honest, and a renamed setting is more actionable to a reader than a moved
   file. This is the strongest candidate for extending `test_doc_paths.py`, and
   it is deliberately not in it.

4. **The roadmap entry's own attribution was wrong**, as flagged in the spec:
   it named #020, #021 and #022 as the three specs that routed around this;
   #020 touched neither file, and the third was #013. Corrected here rather than
   by rewriting the roadmap row.

---

## Test Evidence

The new test, passing:

```
$ uv run pytest tests/test_doc_paths.py -v
tests/test_doc_paths.py::test_finds_paths_to_check[ARCHITECTURE.md] PASSED [ 20%]
tests/test_doc_paths.py::test_finds_paths_to_check[OVERVIEW.md] PASSED   [ 40%]
tests/test_doc_paths.py::test_documented_paths_exist[ARCHITECTURE.md] PASSED [ 60%]
tests/test_doc_paths.py::test_documented_paths_exist[OVERVIEW.md] PASSED [ 80%]
tests/test_doc_paths.py::test_known_absent_are_actually_absent PASSED    [100%]
============================== 5 passed in 0.01s ===============================
```

**Verification that it can fail — direction 1, a stale document.** Reintroducing
the exact row that survived #010 through #022 (`finetune/` was deleted in #011
and stayed in the component map until this spec):

```
$ printf '\n| `finetune/format.py` | fixture→SFT; authoritative prompt |\n' \
    >> docs/specs/ARCHITECTURE.md
$ uv run pytest tests/test_doc_paths.py -q
E   AssertionError: ARCHITECTURE.md names 1 path(s) that do not exist: finetune/format.py
1 failed, 4 passed in 0.03s
```

**Verification that it can fail — direction 2, code moving under a correct
document.** This is the failure mode the test is actually for:

```
$ git mv hable_ya/auth.py hable_ya/session_auth.py
$ uv run pytest tests/test_doc_paths.py -q
E   AssertionError: ARCHITECTURE.md names 1 path(s) that do not exist: hable_ya/auth.py
E   AssertionError: OVERVIEW.md names 1 path(s) that do not exist: hable_ya/auth.py
```

Both changes were reverted; the extractor's coverage after tuning is 38 paths in
`ARCHITECTURE.md` and 15 in `OVERVIEW.md`, against floors of 20 and 10.

**Full suite, lint, and types** (538 tests before this spec, 543 after — the
delta is exactly the five new ones; documentation changes touched no runtime
code):

```
$ uv run pytest -q
543 passed, 6 deselected, 9 warnings in 23.72s

$ uv run ruff check .
All checks passed!

$ uv run mypy tests/test_doc_paths.py hable_ya api
Success: no issues found in 56 source files
```

**Diffstat:**

```
 docs/specs/029-orientation-docs/spec.md |   2 +-
 docs/specs/ARCHITECTURE.md              | 383 ++++++++++++++++++--------------
 docs/specs/OVERVIEW.md                  | 215 ++++++++++--------
 tests/test_doc_paths.py                 | 157 +++++++++++++
 4 files changed, 504 insertions(+), 253 deletions(-)
```

**Not covered by automation:** whether the re-baselined prose is *accurate*, as
opposed to non-dangling. Every claim was verified against the tree while writing
— and the self-review caught one error introduced by this spec itself:
`web/src/lib/` was described as a hash router when it uses
`history.pushState`. That it was caught by reading rather than by a test is the
honest limit of what shipped here.
