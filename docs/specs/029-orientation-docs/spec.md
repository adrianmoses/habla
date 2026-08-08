# Spec: Orientation docs — re-baseline as a living reference, and make the claims checkable

| Field | Value |
|---|---|
| id | 029 |
| status | approved |
| created | 2026-08-08 |

---

## Why

`README.md:25-29` sends every new contributor and every agent to
`docs/specs/OVERVIEW.md` and `docs/specs/ARCHITECTURE.md` as the orientation
entry point. Both documents are substantially false.

They do not describe habla. They describe **hable-ya, at a moment before either
project was implemented.** That is provenance, not drift: commit `6451c4d`
("Port hable-ya runtime as the cloud-fork baseline (#000)") states it outright —
*"hable-ya's OVERVIEW/ARCHITECTURE/README come over as on-device docs to be
rewritten by #015."* Spec #015's scope was the on-device → cloud posture, and it
discharged exactly that axis. The audit sections were never rewritten. Both
files still carry `<!-- status: inferred -->`, `created: 2026-04-19`, and an
`inferred-from` list naming `hable-ya/config.py`, `finetune/format.py`,
`finetune/generate.py` — upstream paths, under a package directory (`hable-ya/`,
hyphenated) that has never existed in this repository.

The residue is visible on the surface. `OVERVIEW.md:30` cites "specs 029/049" as
having landed the learner model — those are *hable-ya's* spec numbers. In this
repo #029 is this document and there is no #049.

### What is actually false

Verified against `HEAD` (`de98e1c`) while writing this spec:

| Claim | Location | Reality |
|---|---|---|
| "No DB code is implemented yet"; persistence "(planned)" | `OVERVIEW.md:83` | 5 Alembic migrations, `hable_ya/db/`, the whole `learner/` package |
| "`aiosqlite` is currently vendored" | `OVERVIEW.md:83` | Zero occurrences in `pyproject.toml` |
| "Learner model is schema-only… no knowledge graph, no profile persistence, no error-pattern aggregation" | `OVERVIEW.md:115` | All three shipped; the graph is documented in `ARCHITECTURE.md:236-272` *in the same repo* |
| "`db/connection.py` and `db/hable_ya_db.py` are empty, no schema, no migrations, no init script" | `OVERVIEW.md:116` | All present; `scripts/init_db.py` implemented in #017 |
| "Runtime pipeline is entirely stubbed"; 5 files "raise `NotImplementedError`" | `OVERVIEW.md:114` | `grep -rn NotImplementedError hable_ya/ api/` returns **nothing** |
| "Tool schema is empty (`HABLE_YA_TOOLS = []`)" | `OVERVIEW.md:117` | Implemented in #002 |
| "Stubbed tests: `test_db.py`, `test_prompts.py`, `test_tools.py` — docstrings only" | `OVERVIEW.md:94` | 8, 25 and 5 real tests respectively |
| "Whether tests are run in CI anywhere (no CI config found)" | `OVERVIEW.md:132` | Contradicted by `OVERVIEW.md:95` **in the same document**, which describes the workflow. CI has 3 jobs: `checks`, `web`, `e2e` |
| `config.py` exposes `db_path`, `llama_cpp_url` | `ARCHITECTURE.md:39` | Neither identifier exists |
| Component map lists `finetune/`, `notebooks/`, `models/`, `download_model.py` | `ARCHITECTURE.md:73-102` | Deleted in #010/#011; `models/` is untracked |
| `eval/agent/{opus_judge,synthetic_learner,run_agent_eval}.py` `[stub]` | `ARCHITECTURE.md:68-71` | 185, 151 and 546 lines |
| "Three logical systems" | `ARCHITECTURE.md:20` | Undercounts: `analiza/` (13 files, its own spec) and `web/` (the SPA shipped in #018/#020) appear in **neither** document |

### Why this is a roadmap item and not an edit

Because "keep them current" is the strategy that has already failed. Since
`#000`, four commits have touched these files, each correcting only what it
tripped over: #015 (the scoped cloud rewrite), #013 (2 lines), #021 (1 line in
each), #022 (40 lines of AGE schema + 8). Every one left the surrounding
paragraph false.

*(Correcting the roadmap entry's own claim: it names #020, #021 and #022 as the
three that routed around this. #020 touched neither file — the third was #013.
The pattern it describes is real; the attribution was not checked.)*

The reason is structural, and it is the thing this spec fixes. These documents
carry **derived facts with no derivation** — a per-file inventory of which
modules are stubs, which tests are docstrings, which capabilities exist. Those
claims change on almost every commit, are already answered authoritatively by
`git ls-files` and by the test suite, and are checked by nothing. A hand-copied
cache with no invalidation goes stale; the only surprise is expecting otherwise.

### Consumer Impact

- **New contributors and agents.** Today the first document you are told to read
  says the runtime does not exist. An agent that trusts it will re-implement
  shipped subsystems or refuse to find code it is standing on; one that does not
  trust it has no orientation document at all. Both `analiza/` and `web/` are
  currently invisible to anyone reading only these files.
- **Future specs.** #021 and #022 both had to establish repo reality from source
  before they could plan, and #022 spent part of its budget re-deriving the AGE
  schema into `ARCHITECTURE.md` because nothing recorded it. A document that is
  true where it speaks is the input every subsequent spec assumes it has.
- **This is not a user-facing feature and does not claim to be.** The
  beneficiary is whoever opens this repo next, which — given how it is
  developed — is usually an agent.

### Roadmap Fit

Blocks nothing and is blocked by nothing; it is the deliberate discharge of a
debt #022 named in its own decision record rather than fix out of scope. Doing
it before #030 and #031 is the right order for a different reason: both are
about the same failure mode in another register — #030 is a dev-facing script
that drifted because nothing tested it, #031 is migration `downgrade()` paths
that read as supported and have never run. All three are *claims the repo makes
about itself that nothing checks*. Establishing the mechanism here (a test that
executes a documentation claim, following #022's `test_readme_snippets.py`) sets
the pattern the next two apply to code.

---

## What

### Acceptance Criteria

- [ ] Every factual claim in `OVERVIEW.md` and `ARCHITECTURE.md` is true of
      `HEAD`, or has been deleted. Specifically: every row of the table above is
      resolved.
- [ ] Both documents state what they are and when they are true — no residual
      `status: inferred` / `inferred-from` header pointing at another repo's
      files, and no `[INFERRED: uncertain]` markers left standing for questions
      that specs have since answered.
- [ ] The three accumulated migration-note blockquotes (`OVERVIEW.md:28-33`,
      `ARCHITECTURE.md:10-16`, and the `finetune` note at `ARCHITECTURE.md:175`)
      are gone — a re-baselined document does not need to apologise for itself.
- [ ] `analiza/` and `web/` are documented as first-class systems: what they
      are, where they live, how they relate to the runtime. `analiza` links to
      `docs/specs/analiza/spec.md` rather than restating it.
- [ ] The per-file component map with `[implemented]` / `[stub]` / `[partial]`
      labels is **deleted**, replaced by a systems-level map that names
      directories and their responsibility, not files and their status.
- [ ] `OVERVIEW.md`'s "Capabilities Observed", "Gaps and Inconsistencies" and
      "Uncertain Areas" sections are **deleted**. Anything in them that is both
      still true and durable moves into the body of the document; the rest goes.
- [ ] A new test fails if either document names a repository path that does not
      exist on disk.
- [ ] The test is verified by reintroducing a defect: renaming a referenced path
      makes it fail, naming the file.
- [ ] `README.md:25-29`'s one-line descriptions still match what the documents
      now contain.
- [ ] `ruff`, `mypy`, and the full `pytest` suite pass.

### Non-Goals

- **Not a README rewrite.** `README.md` is separately covered by
  `test_readme_snippets.py` and was corrected in #022. Only the `docs/specs/`
  descriptions at lines 25-29 are in scope, and only if they stop being accurate.
- **Not a `ROADMAP.md` restructure.** Its entries are historical claims — a path
  named in a closed item may legitimately be deleted later, so it is a poor fit
  for the path check. Status update only (`planned` → `in-progress` →
  `implemented`), and the #020/#013 misattribution noted above is corrected in
  #029's own revision-history entry rather than by rewriting #029's row.
- **Not documenting `analiza`'s internals.** It owns `docs/specs/analiza/spec.md`.
  Duplicating it here would create the second copy that this spec exists to
  eliminate.
- **Not a doc-generation tool.** No component map generated from `git ls-files`,
  no docstring extraction. The fix is to stop keeping the inventory, not to
  automate keeping it.
- **No product or architecture decisions.** Where a document is wrong, it is
  corrected to what the code does; where the code is arguably wrong, that is a
  new roadmap item, not an edit here.
- **Not extending the path check to prose in other docs** (`docs/specs/*/spec.md`,
  decision records). Those are point-in-time records and should be free to name
  paths that later move.

### Open Questions

Both resolved before approval, by the owner:

1. **What are these documents for — living reference or dated audit snapshot?**
   *Resolved: living reference*, kept where the README already points, but
   de-scoped so that "living" is achievable. The alternative (freeze both into
   `docs/artifacts/`, write a thin new orientation doc) was considered and
   rejected: the docs contain genuinely valuable durable content — the decided
   non-goals, the latency floor, the AGE schema, the pedagogical thresholds —
   and freezing it would strand it or force a copy.
2. **How should `analiza/` and `web/` be treated?** *Resolved: both as
   first-class systems*, `analiza` by link.

---

## How

### Approach

The governing rule for what survives, applied section by section:

> **Keep a claim only if it changes by decision. Delete it if it changes by
> commit.**

Product intent, target consumer, non-goals, external dependencies, key
constraints, data flow and the AGE schema all change when someone *decides*
something — and a decision record is the natural moment to update them, which is
how the AGE schema section correctly arrived in #022. Per-file implementation
status changes when someone *commits* something, is authoritative in
`git ls-files` and the test suite, and is what has rotted every time.

**1. `OVERVIEW.md`**

Keep and correct: Product Summary, Target Consumer, Job To Be Done, Non-Goals
(these are the most valuable content in either file — #021's single-tenant
accounting and #022's graph posture both live here), Tech Stack, Testing Suite.

Delete outright: the `status: inferred` / `inferred-from` header, the migration
note at lines 28-33, "Capabilities Observed" (an inventory of a
fine-tuning workstream that no longer exists), "Gaps and Inconsistencies" (every
entry is either fixed or now a roadmap item), "Uncertain Areas" (self-contradicting
on CI; the rest is answered — session lifecycle by #016, deployment path by #017).

Rewrite: lines 35-38's "three parallel workstreams" (model/eval, fine-tuning,
stubbed runtime) — two of the three are gone or shipped. Replace with the real
system inventory, matching `ARCHITECTURE.md`'s.

**2. `ARCHITECTURE.md`**

Keep and correct: System Overview (recount the systems), Data Flow (drop
"target — not yet implemented" from the runtime flow, which has been implemented
since #001-#013; correct `hable-ya/db/hable_ya_db.py` to the real ingest path in
`hable_ya/learner/ingest.py`), External Dependencies, Key Constraints, and the
AGE graph schema section (#022's, already accurate — leave it alone).

Replace: the Component Map. A systems-level map of directories and
responsibilities, no status labels, no per-file rows. It should answer "where
does X live" and stop there.

Delete: the `status: inferred` header, the migration note at lines 10-16, the
`finetune` note at 175-177, and the two remaining `[INFERRED: uncertain]`
markers at 232-233 (deployment target and `/ws/session` session lifecycle — both
settled by #016/#017; anything genuinely still open becomes plain prose or a
roadmap item).

**3. Both files: new header**

Replace the `inferred` header with one that states the two things a reader needs:
what the document is for, and the commit it was last verified against.

**4. `tests/test_doc_paths.py`**

Modelled directly on `tests/test_readme_snippets.py` (#022), including its
guard-against-vacuous-pass test:

- Extract backtick-quoted tokens from both documents that look like repo paths
  (contain `/` or end in a known source extension), stripping any `:NN` or
  `:NN-NN` line suffix and trailing punctuation.
- Assert each resolves under the repo root. Directories and files both count.
- A module-level `KNOWN_ABSENT` allowlist, each entry carrying a written reason,
  for paths that are deliberately named without existing (e.g. an upstream
  hable-ya path in a historical note). Empty is the goal; non-empty must justify
  itself.
- A `test_finds_paths_to_check` guard asserting the extractor matched a floor
  count, so a docs reshuffle cannot silently turn the suite vacuous — this is the
  specific failure mode `test_readme_snippets.py:46-50` was written to prevent.

This is not a general documentation linter. It checks one class of claim — "this
path exists" — chosen because it is the class that fails first when code moves,
it is cheap to check, and it is exactly what would have caught the component map
listing `finetune/` for four specs after its deletion.

**5. `ROADMAP.md`**

`#029` → `in-progress` now, `implemented` with the decision record.

### Confidence

**Level:** High

**Rationale:** The repo-state facts are established (verified above, not
inferred), the decision the roadmap demanded is resolved, and the mechanism has
a working precedent in this codebase. The only real judgment is where the
keep/delete line falls in individual paragraphs, and that is reviewable in the
diff.

The one thing that could go wrong is the path-extraction regex: too loose and it
flags prose like `learner_profile`; too tight and it passes vacuously. Both
failure modes are visible during implementation (the first fails loudly, the
second is caught by the floor-count guard), so this is a tuning risk, not a
design risk.

### Key Decisions

1. **Living reference, de-scoped — not a frozen snapshot.** Freezing is the
   honest option for a document nobody will maintain, but these files hold
   content that is genuinely durable and genuinely load-bearing (#021's
   single-tenant reversal cost, #022's graph posture, #013's latency floor). The
   real problem is not that the documents are alive; it is that they were
   carrying an inventory no one could keep alive. Remove that and the remainder
   is maintainable at the rate decisions are actually made.

2. **Deleting the per-file component map is the substance of this spec, not a
   side effect.** Correcting all 40+ entries and keeping the section would
   satisfy an audit today and be false again within a few specs. #022's
   conclusion applies unchanged: unused machinery is the thing to remove, not
   to maintain.

3. **The check is executable, and deliberately narrow.** "Every path named
   exists" is a small fraction of what these documents assert, and it is not a
   claim that the prose is *true* — only that it is not pointing at something
   deleted. It is chosen for the same reason #022 chose executing the README's
   SQL: a narrow check that runs beats a broad one that is a promise. Broader
   verification (asserting that a documented endpoint responds, say) is a
   candidate for later, and is not part of this.

4. **Recording the verified-at commit in the header.** A reader can then tell
   staleness by comparing against `git log` instead of trusting the prose. It
   also makes the next re-baseline a diff rather than an audit.

### Testing Approach

Per `OVERVIEW.md`'s Testing Suite: pytest, `asyncio_mode = "auto"`,
`testpaths = ["tests"]`.

**New — `tests/test_doc_paths.py`:**

| Test | Asserts |
|---|---|
| `test_finds_paths_to_check` | Extractor matches ≥ a floor count in each document — guards against a vacuous suite after a docs reshuffle |
| `test_overview_paths_exist` | Every path named in `OVERVIEW.md` resolves under the repo root |
| `test_architecture_paths_exist` | Same for `ARCHITECTURE.md` |
| `test_known_absent_are_actually_absent` | Every `KNOWN_ABSENT` entry is still missing — so the allowlist cannot quietly outlive its reason |

**Verification of the test itself** (the #022 precedent — its README test was
proven by reintroducing the original defect): rename a path referenced by the
re-baselined docs, confirm the suite fails and names the offending path, revert.
The result is recorded in the decision record.

**Regression surface:** documentation-only apart from the new test file. No
runtime code changes, so the existing 538 tests should be unaffected — and if
any test asserts on doc content, that is a finding worth reporting rather than
working around. Full `pytest`, `ruff` and `mypy` before the decision record.

**Not covered by automation:** whether the prose is *accurate*, as opposed to
non-dangling. That is what review is for, and this spec's evidence table is the
checklist.
