# Decision Record: Deployment Hardening

| Field | Value |
|---|---|
| id | 017 |
| status | implemented |
| created | 2026-07-08 |
| spec | [spec.md](./spec.md) |

---

## Context

#016 made the app *functionally* safe to expose (auth, single-session
enforcement, fail-fast, honest `/health`). #017 hardens the *deployment* surface
around it: the image ran as root with dev deps baked in and no liveness signal;
the only compose file host-published Postgres and hardcoded `hable_ya:hable_ya`;
there was no image-publish pipeline, no DB backup path, and no written deploy
procedure.

Two things shaped the implementation beyond what the spec anticipated, both
surfaced by *building and running* the artifacts rather than reasoning about them:

1. **`eval/` is a runtime dependency, not just an eval-harness package.** The
   first non-root image built fine but failed to import `api.main` with
   `ModuleNotFoundError: No module named 'eval'` — `hable_ya` imports
   `eval.fixtures.schema` (CEFR/profile schemas) and `eval.scoring.recast`
   (Spanish lemmatization) across ~11 modules. The design pass (which scoped the
   image to `hable_ya` + `api`) missed this. `eval/` now ships in the image.
2. **pipecat downloads NLTK `punkt_tab` at first import.** `pipecat.utils.string`
   fetches it to a cwd/HOME-relative dir the non-root user cannot write. The
   design pass checked Silero/SmartTurn ONNX + HF caches (correctly finding those
   ship in the wheel) but not NLTK. It is now pre-baked at build into
   `/usr/local/share/nltk_data` (`NLTK_DATA`).

The spec's headline Medium-confidence risk — whether a logical `pg_dump`
round-trips the Apache AGE graph — was resolved by running the round-trip
locally: it does, cleanly, with no special flags and no volume-snapshot fallback.

All five spec Open Questions were owner-resolved before implementation (Caddy +
ACME, prod-only TLS, boot-coupled migrations, env-injection secrets, `sha`/
`latest`/`v` image tags); the local-dev data-mount question raised during
planning was resolved to a named volume in both stacks.

## Decision

Shipped the six-workstream hardening as specced, with local `docker compose up`
preserved as a plain TLS-free `ws://localhost:8000` loop:

1. **Multi-stage non-root `Dockerfile`** — builder runs `uv sync --frozen
   --no-dev --no-install-project` + bakes `es_core_news_sm`; runtime is
   `python:3.12-slim` as uid/gid 10001 with `libstdc++6` (onnxruntime), a
   curl-free urllib `HEALTHCHECK` on `/health`, app source at `/app` (so the
   boot-coupled `parents[2]/alembic.ini` path resolves), plus the two Context
   fixes (`eval/` copied, NLTK pre-baked).
2. **`docker-compose.prod.yml` + `Caddyfile`** — overlay (Compose v2.24.4+
   `!reset`/`!override`) that pulls the GHCR image, adds restart/limits, strips
   all host-published ports, injects DB creds, and fronts the app with Caddy
   (automatic ACME `wss://`). Base file switched `./data` → named `appdata`
   volume and stays TLS-free/host-published for dev.
3. **DB-credential fail-fast** — `require_secure_db_credentials()` rejects an
   empty/placeholder DB password on the serving path unless
   `allow_default_db_credentials` (dev opt-out, base compose `true`, prod
   `false`).
4. **`release.yml`** — GHCR build-push CD, separate from test-only `ci.yml`.
5. **`backup_db.sh` / `restore_db.sh`** — AGE-safe `pg_dump -Fc`/`pg_restore`,
   round-trip verified.
6. **`docs/RUNBOOK.md`** — deploy/redeploy/migrate/backup/rollback/local.

---

## Alternatives Considered

### AGE backup mechanism (the spec's central risk)

**Option A — logical `pg_dump -Fc` + `pg_restore`.**
- Pros: portable, human-inspectable, selective restore, one small file.
- Cons: *feared* to not round-trip AGE — graph label tables + `ag_catalog`
  registration might not reconstruct into a fresh DB.

**Option B — physical `pgdata` volume snapshot (tar with db stopped).**
- Pros: byte-identical, guaranteed round-trip regardless of AGE internals.
- Cons: not portable across PG versions, coarse (whole cluster), requires
  downtime to be consistent.

**Chosen: A.** The spec flagged this as spike-gated, so it was tested rather than
assumed. A full seed → `pg_dump -Fc` → restore into a fresh empty DB round-tripped
`learner_profile`, `vocabulary_items`, **and** the `learner_knowledge` graph
(`Learner` vertex count preserved). pg_dump emits `CREATE EXTENSION age` and AGE
marks its catalog tables with `pg_extension_config_dump`, so the registration +
label tables + rows all travel. Option B is documented in the runbook as the
implicit fallback (recreate the volume) but is not needed for correctness.

### Where the DB-credential validation lives

**Option A — a `Settings` (pydantic) validator.**
- Pros: single choke point, runs on every construction.
- Cons: breaks the CI invariant — tests build `Settings()` with no env and the
  local/dev placeholder DSN is legitimate.

**Option B — a serving-path function called in the lifespan (mirrors #016).**
- Pros: only the real serving path is gated; keyless `Settings()` still
  constructs; unit-testable as a pure function.
- Cons: must remember to call it (one line in `lifespan`).

**Chosen: B**, for exact consistency with #016's `require_cloud_secrets`. The dev
opt-out (`allow_default_db_credentials`) rather than unconditional rejection is
because the placeholder credential is *valid* in local dev (unlike an empty
provider key, which never is).

### Unpublishing base ports in the prod overlay

**Option A — Compose `!reset`/`!override` merge tags.**
- Pros: keeps the base file authoritative and dev-friendly; overlay expresses
  only the prod delta.
- Cons: requires Compose v2.24.4+.

**Option B — move host publishes into a `docker-compose.override.yml` dev file.**
- Pros: no minimum Compose version.
- Cons: changes/erodes the base file the spec wanted preserved; dev now needs an
  extra `-f`.

**Chosen: A.** Compose merges `ports`/`volumes` by concatenation, so a base
publish cannot otherwise be removed from an overlay. The deploy host runs Compose
v5.3.0; the version floor is documented in the runbook.

### Reverse proxy / TLS

Owner-resolved to **Caddy + automatic ACME** before implementation (spec Open
Questions 1–2). nginx (manual certs) and Traefik (label-driven) were the
alternatives; Caddy wins on least-config auto-TLS for a single-tenant host. Two
directives (`email`, `reverse_proxy app:8000`); Caddy upgrades WebSockets
transparently.

---

## Tradeoffs

- **Local turn logs moved off the host filesystem.** The base `./data` bind
  became a named `appdata` volume so the non-root container can write
  `runtime_turns.jsonl`. This was an explicit owner choice (over a one-time
  `chown 10001:10001 ./data`): zero manual steps, at the cost of logs no longer
  being directly visible at `./data` (inspect via `docker compose exec app cat
  /app/data/runtime_turns.jsonl`). The `ws://` loop is otherwise unchanged.
- **`eval/` in the runtime image.** Ships an "eval-harness" package into
  production because the runtime genuinely imports it. Correct but architecturally
  untidy — the shared CEFR/profile schemas and lemmatization arguably belong in
  `hable_ya`, not `eval` (see Spec Gaps).
- **Image size ~1.74 GB.** Driven by pipecat + transformers (torchless) + spaCy +
  onnxruntime, not by the (now removed) dev deps. Not optimized further; out of
  scope.
- **Compose v2.24.4+ floor.** Accepted to keep the base file preserved.
- **CD publishes, does not deploy.** GHCR image only; the operator runs `compose
  up` per the runbook. No GitOps (spec Non-Goal).
- **Migrations stay boot-coupled.** Simple and works; a bad migration blocks boot
  (the runbook's rollback path is image-revert + restore, since there is no
  auto-down-migration).

---

### Spec Divergence

The implementation matched the spec's intent on all acceptance criteria. The
divergences are additive — extra files/steps the spec didn't enumerate, forced by
runtime reality — not changes of direction.

| Spec Said | What Was Built | Reason |
|---|---|---|
| Image copies `hable_ya`, `api`, `alembic.ini` | Also copies `eval/` | `hable_ya` imports `eval.fixtures.schema` + `eval.scoring.recast` at runtime; image won't boot without it |
| Only runtime need beyond deps is `libstdc++6` (onnxruntime) | Also pre-bakes NLTK `punkt_tab` into `NLTK_DATA` | pipecat downloads it at first import to a non-writable path under the non-root user |
| Reject placeholder creds "when not in dev mode" | Concrete `allow_default_db_credentials` flag (base `true` / prod `false`) + empty-or-`hable_ya` password check | Spec left the dev-signal unspecified; implemented as an explicit opt-out mirroring #016 |
| Backup = `pg_dump`/`pg_restore`, volume-snapshot fallback if fragile | Logical dump only; fallback documented but unused | Round-trip spike proved the logical dump handles AGE cleanly |
| Base `/app/data` handling left to a planning decision | Named `appdata` volume in base + prod | Owner-selected during planning; non-root can't write the host-root-owned bind |

---

## Spec Gaps Exposed

- **`eval/` ↔ `hable_ya` coupling.** The runtime depending on an `eval`-named
  package is a latent architecture smell the OVERVIEW/ARCHITECTURE docs describe
  as three *independent* workstreams. Candidate follow-up: move the shared schemas
  (`CEFRBand`, `LearnerProfile`, `FluencySignal`, `Theme`, `SystemParams`) and
  `content_lemma_surfaces` into `hable_ya` so the runtime image needn't ship
  `eval/`. Not in #017 scope.
- **NLTK dependency is undeclared.** pipecat's `punkt_tab` need is invisible in
  `pyproject.toml` and only appears at runtime. Worth an explicit note (or a
  vendored data step) so it isn't re-discovered.
- **`/health` liveness blind spot (already flagged by #016).** Reconfirmed as
  #014's: the reactive signal can't see pipeline-internal `ErrorFrame` provider
  failures. Untouched here.
- **ARCHITECTURE/OVERVIEW `.dockerignore` + root-user descriptions** are now
  stale (image is non-root, multi-stage). Minor; folds into the pending
  `inferred`-docs re-baseline.

---

## Test Evidence

Full suite (DB-dependent tests skip without a live db; they run in CI with one
up), plus the CI-scoped lint/type gates:

```
$ uv run pytest tests/ -q
295 passed, 52 skipped, 9 warnings in 14.59s

$ uv run ruff check hable_ya/ api/ eval/agent/ tests/ scripts/
All checks passed!

$ uv run mypy hable_ya/ api/ eval/agent/
Success: no issues found in 56 source files
```

WS1 — image build + non-root runtime checks:

```
=== whoami ===            app   (uid=10001 gid=10001)
=== venv python ===       Python 3.12.13   (/app/.venv/bin/python)
=== onnxruntime import === onnxruntime 1.23.2
=== spaCy model loads ===  lemmas: ['el', 'gato', 'comar', 'pescado']
=== app + alembic path === alembic.ini -> /app/alembic.ini True
=== data dir writable ===  wrote /app/data/_probe OK
=== api imports ===        api.main import OK
=== dev deps ===           pytest/ruff/mypy: absent (good)
image size: 1.74GB
```

WS3 — DB-credential fail-fast, verified in-container:

```
=== placeholder creds, opt-out OFF ===
RuntimeError: Insecure database credentials: the DB password is empty or the
placeholder 'hable_ya'. Inject a real POSTGRES_PASSWORD, or set
HABLE_YA_ALLOW_DEFAULT_DB_CREDENTIALS=true for local development.
=== real creds ===         PASS: real creds accepted
```

WS2 — compose merge (base keeps ports/placeholder; prod strips ports, injects creds):

```
BASE:  app published "8000", db published "5433", appdata volume, no caddy
       HABLE_YA_ALLOW_DEFAULT_DB_CREDENTIALS: "true"
PROD:  published: "80", "443"   (caddy only — app/db host ports !reset)
       services: app, caddy, db
       HABLE_YA_ALLOW_DEFAULT_DB_CREDENTIALS: "false"
       HABLE_YA_DATABASE_URL: postgresql://habla:injected-secret@db:5432/habla
```

WS5 — AGE backup/restore round-trip (via the actual scripts, into a fresh DB):

```
$ ./scripts/backup_db.sh
Wrote ./backups/habla-hable_ya-<ts>.dump (46957 bytes)
$ POSTGRES_DB=habla_scripttest ./scripts/restore_db.sh backups/habla-hable_ya-<ts>.dump
Restore complete. Verifying AGE graph registration…
 learner_knowledge
=== data integrity in restored db ===
 profile 1:A2
 vocab 6
 graph_vertices 1        # AGE Learner vertex survived
```

## Deferred live spikes (need real credentials / a public domain)

Structurally validated but not exercised end-to-end here — for the operator:

1. Healthy-boot end-to-end with real provider keys + the full compose stack
   (`/health` → `healthy` post-warmup).
2. A full `ws://localhost:8000` turn on the base stack.
3. `wss://` through Caddy against a real domain (ACME staging), cert persistence
   across `down`/`up`.
4. GHCR push (via `workflow_dispatch` dry-run or first `main` merge).
