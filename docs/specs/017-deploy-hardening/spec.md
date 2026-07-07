# Spec: Deployment Hardening

| Field | Value |
|---|---|
| id | 017 |
| status | approved |
| created | 2026-07-07 |

---

## Why

With #016, the public `/ws/session` endpoint is authenticated, single-session
enforcement is safe, and `/health` reflects live cloud reachability — the app is
*functionally* safe to expose. But the *deployment* surface around it is still a
development artifact, not a production one. The image runs as **root** with dev
dependencies baked in and no container-level liveness signal; the only compose
file publishes Postgres to the host and hardcodes the `hable_ya:hable_ya`
credential in two places; there is no image-publish pipeline (CI is test-only),
no database backup path, and no written procedure for redeploying or rolling a
schema migration. Any real deployment today is a hand-assembled, undocumented,
root-owned stack with its database one `docker compose up` away from listening
on a public port with a known password.

This feature closes that gap: it makes the artifact you ship (`Dockerfile`), the
topology you run (a prod compose overlay behind TLS), the secrets you inject, the
pipeline that publishes the image, and the operational procedures (backup,
restore, redeploy, migrate) production-grade — so the deployment is as hardened
as the application logic #016 already made safe.

### Consumer Impact

The consumer is the **operator** (the project owner deploying `habla` to a real
host — the single-tenant "one learner per deployment" posture from OVERVIEW).
Concretely, after this feature the operator can:

- Pull a published, versioned image from GHCR instead of building on the host.
- Run `docker compose -f docker-compose.yml -f docker-compose.prod.yml up` and get
  a non-root app container, restart-on-failure, resource limits, a container
  healthcheck, a database **not** reachable from the host network, and `wss://`
  TLS termination in front of the WebSocket.
- Inject real secrets (DB password, provider keys, session token) rather than run
  with the checked-in `hable_ya:hable_ya` default, with the app refusing to boot
  on a placeholder/empty credential.
- Recover from data loss: take and restore a `pgdata` backup with a documented,
  tested procedure.
- Redeploy and run migrations from a runbook rather than from tribal knowledge
  about how boot-coupled migrations behave.

The learner (end user) benefits indirectly: a container that restarts on crash,
reports health honestly to the orchestrator, and terminates TLS means fewer
dropped sessions and no cleartext audio-token exposure on the wire.

### Roadmap Fit

Final item of the deployment-readiness pair (#016 + #017) opened by the
2026-07-06 assessment. #016 was the **security blocker** (auth, single-session,
fail-fast, honest health); #017 is the **operational hardening** that assumes
#016 has landed — e.g. the TLS reverse proxy here is what makes #016's shared
session token safe on the wire (`.env.example` explicitly flags that the token
"crosses the wire in cleartext until TLS/wss (#017)"). It depends on #016 and on
the CPU-only posture established in #009. It has a documented overlap with **#014**
(resilience & cost): #017 owns the container/compose/CD/backup layer, #014 owns
in-pipeline retry/backoff and token-cost metering — this spec does not touch
either. After #017, the #001–#017 cloud-migration + deployment-readiness arc is
complete.

---

## What

### Acceptance Criteria

From the operator's perspective:

- [ ] **Non-root image.** The app container runs as a non-root user; a shell in
  the running container confirms `whoami` ≠ `root` and the app cannot write
  outside its owned paths.
- [ ] **Lean image.** The image is built with `uv sync --no-dev` (or
  `--no-default-groups`) so pytest/ruff/mypy and the eval/dev extras are absent;
  `es_core_news_sm` is installed at build time so runtime vocabulary tracking
  (`hable_ya/learner/vocabulary.py`) does **not** silently degrade to `[]`.
- [ ] **Multi-stage build.** Dependency install and app copy are separated so a
  code-only change does not reinstall dependencies (build-cache friendly).
- [ ] **Container healthcheck.** The image declares a `HEALTHCHECK` that polls
  `/health`; `docker ps` shows `healthy` only once the app is warm, the DB is
  live, and no provider is degraded (reusing #016's `/health` contract, which
  already returns 503 while `warming_up`/`db_unreachable`/`degraded`).
- [ ] **Prod compose overlay.** A `docker-compose.prod.yml` overlay exists that,
  layered over the base file, sets a `restart:` policy, CPU/memory `limits`, an
  app-service healthcheck, and **removes the `db` host port publish** (Postgres
  is reachable only on the internal compose network).
- [ ] **TLS / `wss://` (prod only).** The overlay puts **Caddy** in front of the
  app, obtaining/renewing an ACME cert automatically for the operator's domain, so
  the operator connects over `wss://` (and `https://` for `/health`); the raw
  `ws://` app port is not published to the host in prod.
- [ ] **Local compose has no TLS.** `docker compose up` on the base
  `docker-compose.yml` alone (no prod overlay) runs the app over plain
  `ws://localhost:8000` with **no Caddy, no cert, and no domain requirement** — the
  local dev loop is unchanged from today. TLS/Caddy exists only when the prod
  overlay is layered on.
- [ ] **Injected secrets, no hardcoded creds.** The DB credential is supplied via
  injected config (not the literal `hable_ya:hable_ya` in `docker-compose.yml`
  and `config.py`); a placeholder/empty DB password, provider key, or session
  token is rejected at startup with a clear error (extending #016's
  `require_cloud_secrets` fail-fast to cover the DB credential and reject known
  placeholder values).
- [ ] **Image CD to GHCR.** A GitHub Actions job builds and pushes a tagged image
  to GHCR on merge to `main` (and/or on a version tag), separate from the
  existing test-only `ci.yml`.
- [ ] **Backup/restore path.** A documented, executable procedure backs up and
  restores the `pgdata` volume (e.g. `pg_dump`/`pg_restore` wrapper scripts), and
  a restore into a fresh volume round-trips the learner data.
- [ ] **Runbook.** A deploy/operations runbook documents first deploy, redeploy,
  the migration step (how `upgrade_to_head()` runs at boot today and how to run
  `scripts/init_db.py` standalone instead), backup/restore, and rollback.

### Non-Goals

- **Not #014.** No retry/backoff, rate-limit handling, or token-cost metering —
  that is #014. `/health` stays reactive as shipped in #016 (the #016 note that a
  reactive `/health` can't see pipeline-internal `ErrorFrame` provider failures is
  a #014 gap, not addressed here).
- **Not multi-host / Kubernetes.** Single-host Docker Compose only, matching the
  single-tenant posture. No k8s manifests, no Helm, no autoscaling.
- **Not multi-tenant.** No per-tenant secrets, routing, or isolation.
- **Not a managed-secrets backend.** Secrets are injected via host env / compose;
  no Vault/AWS Secrets Manager/SOPS integration (may be noted as future work).
- **Not automated deploys / GitOps.** CD publishes the *image*; it does not deploy
  to a host. Deployment stays an operator-run `compose up` per the runbook.
- **No frontend build/deploy.** `web/` is served separately and stays excluded
  from the API image (`.dockerignore` already excludes it).
- **No CI test-matrix or coverage-gate changes** beyond adding the publish job.

### Open Questions

1. **Reverse-proxy choice.** *Resolved: **Caddy**.* Least-config automatic HTTPS;
   the prod overlay adds a `caddy` service reverse-proxying `wss://`/`https://` →
   `app:8000`. Lives only in the prod overlay — the base compose file has no proxy.
2. **TLS certificate source.** *Resolved: **ACME via Caddy**.* Caddy obtains and
   renews a real cert automatically for the operator-supplied domain (requires a
   public DNS name pointing at the host + ports 80/443 reachable). The runbook
   documents the domain/DNS/port prerequisites. **Local development does not use
   TLS at all** — see the local-dev constraint below.
3. **Migration execution model.** *Resolved: **boot-coupled**.* Migrations keep
   running at app boot via `upgrade_to_head()` in the `api/main.py` lifespan (works
   today, no change). The runbook documents `scripts/init_db.py` as the standalone
   escape hatch for review-first/zero-downtime migrations, but it is not wired into
   the default deploy path.
4. **Secret transport.** *Resolved: **env injection baseline**.* Secrets are
   injected via host env / `.env` (matches today) with the extended startup
   validation rejecting empty/placeholder values. Docker Compose `secrets:`
   (file-based, keeps secrets out of `docker inspect`) is offered as an optional
   overlay for the DB password, documented in the runbook, not the default.
5. **Image tagging.** *Resolved.* The CD job pushes `sha-<short>` + `latest` on
   every `main` merge, and `v<version>` when a git version tag is pushed.

---

## How

### Approach

Six independent workstreams, deliverable and reviewable in isolation:

**1. Dockerfile (multi-stage, non-root, healthcheck).**
Replace the single-stage root Dockerfile with a builder/runtime split:
- *Builder stage:* `uv sync --frozen --no-dev` into a venv; run
  `python -m spacy download es_core_news_sm` so the Spanish model is baked in
  (today it's a manual post-install step and its absence silently degrades
  vocabulary tracking to `[]` — see `vocabulary.py:44`).
- *Runtime stage:* `python:3.12-slim`, create a non-root user, copy the venv +
  app code with correct ownership, drop to the non-root user, `EXPOSE 8000`.
- Add `HEALTHCHECK` hitting `/health` (curl/python one-liner) — the endpoint's
  #016 semantics already return non-200 until genuinely serviceable, so no
  new app code is needed.
- Verify `.dockerignore` still excludes dev/large artifacts (it does today:
  `.git`, `models`, `notebooks`, `data`, `web`, caches, `.env`).

**2. Prod compose overlay (`docker-compose.prod.yml`).**
Layered over the base `docker-compose.yml` (which stays dev-friendly):
- `app`: `restart: unless-stopped`, `deploy.resources.limits` (CPU/mem),
  a service-level `healthcheck` (or rely on the image `HEALTHCHECK`), and **no**
  host port publish for `ws://` (traffic enters via the proxy).
- `db`: remove the `5433:5432` publish so Postgres is internal-only; keep the
  named `pgdata` volume and `pg_isready` healthcheck.
- `caddy` (new, prod overlay only): reverse proxy with automatic ACME TLS,
  forwarding `wss://` → `app:8000` and `https://` → `/health` for the
  operator-supplied domain. Absent from the base file, so local `docker compose up`
  serves plain `ws://localhost:8000` with no proxy, cert, or domain — the dev loop
  is untouched.

**3. Secrets injection + config validation.**
- Remove the literal `hable_ya:hable_ya` from `docker-compose.yml`'s
  `HABLE_YA_DATABASE_URL` override and the `db` service's
  `POSTGRES_USER/PASSWORD`; source them from injected env (with dev defaults kept
  only in the base file for local ergonomics, overridden in prod).
- Extend the #016 startup fail-fast (`require_cloud_secrets` in `api/main.py`, or
  a shared validator in `config.py`) to also reject: an empty DB password, and
  known placeholder values (`hable_ya:hable_ya`, empty provider keys) **when not
  in dev mode**. Keep it out of the `Settings` validator so keyless test
  construction (`Settings()`) still works — mirror #016's lifespan-level check.

**4. GHCR CD job.**
A new workflow (e.g. `.github/workflows/release.yml`) using
`docker/build-push-action` + `docker/login-action` against `ghcr.io`, triggered
on `push: main` and on version tags, with `packages: write` permission. Tags per
Open Question 5. Kept separate from `ci.yml` so the test gate and the publish
gate stay independent.

**5. Backup/restore.**
`scripts/backup_db.sh` / `scripts/restore_db.sh` wrapping `pg_dump`/`pg_restore`
(or `docker compose exec db pg_dump …`) against the AGE-enabled Postgres, plus a
note on the AGE extension/graph so a restore re-creates the graph. Validate a
dump→drop→restore round-trip preserves learner rows and the AGE graph.

**6. Runbook (`docs/RUNBOOK.md` or under `docs/specs/017-...`).**
First deploy, redeploy (pull new image, `compose up`), the migration model
(boot-coupled `upgrade_to_head()` today at `api/main.py:83`; `scripts/init_db.py`
as the standalone path), backup/restore invocation, and rollback (previous image
tag + restore).

### Confidence

**Level:** Medium

**Rationale:** The mechanics are individually well-understood and low-risk —
multi-stage non-root Dockerfiles, compose overlays, GHCR publish jobs, and
`pg_dump`/`pg_restore` are all standard, and the `/health` contract needed for the
healthcheck already exists from #016. What lowers confidence to Medium is the
**cross-cutting infra validation** rather than any single piece: (a) the non-root
image must still be able to write everything it needs at runtime
(`runtime_turns.jsonl` observation sink, any spaCy/HF cache) — a wrong `WORKDIR`
ownership or cache path breaks boot; (b) the AGE graph must survive a
backup/restore round-trip, which needs live verification, not assumption; (c) TLS
+ reverse proxy correctness depends on the domain/cert decision (Open Questions
1–2) and can only be confirmed with a real `wss://` handshake; and (d) the config
validation must reject prod placeholders without breaking the keyless CI
`Settings()` path. None are deep unknowns, but each is an integration point that
must be exercised end-to-end.

**Validate before proceeding:** (All open questions resolved — Caddy+ACME,
prod-only TLS, boot-coupled migrations, env-injection secrets, `sha`/`latest`/`v`
image tags.)
- Spike: build the non-root image and boot it against the compose `db`; confirm
  `whoami` ≠ root, `/health` reaches `healthy`, `es_core_news_sm` loads (vocab
  tracking returns lemmas, not `[]`), and the observation sink can write.
- Spike: `docker compose up` on the **base file alone** serves a working
  `ws://localhost:8000` session with no Caddy/cert/domain — confirm the local loop
  is unbroken before layering the overlay.
- Spike: `backup_db.sh` → drop volume → `restore_db.sh` into a fresh volume;
  confirm learner rows **and** the AGE graph round-trip.
- Spike: a `wss://` connection through Caddy (with a test domain / staging ACME)
  drives one full STT→Claude→Cartesia turn (reuse the #016 `voice_client.py` spike
  over TLS).

### Key Decisions

- **Overlay, not a rewrite.** The prod topology is a *second* compose file layered
  over the existing dev-friendly `docker-compose.yml`, not a replacement — dev
  keeps host-published DB + no proxy; prod gets the hardened shape. Preserves the
  frictionless `docker compose up` local loop the 2026-07-06 assessment praised.
- **Caddy + ACME for TLS, prod overlay only.** TLS termination is a `caddy` service
  with automatic ACME certs (least operator config), and it lives **only** in the
  prod overlay. Local development runs plain `ws://` with no cert or domain — the
  base compose file never touches TLS.
- **Boot-coupled migrations kept.** `upgrade_to_head()` at app boot is the deploy
  default (no change from today); `scripts/init_db.py` is documented as a manual
  alternative, not wired in.
- **Reactive health reused, not extended.** The container `HEALTHCHECK` consumes
  #016's existing `/health` semantics unchanged; deeper provider liveness is #014.
- **Boot-coupled migrations stay the default.** `upgrade_to_head()` at boot works
  today; #017 documents and wires the `scripts/init_db.py` standalone path as an
  option rather than forcing a decoupling (pending Open Question 3).
- **CD publishes, does not deploy.** Scope stops at a pullable GHCR image; host
  deployment stays operator-run per the runbook (single-tenant, no GitOps).

### Testing Approach

Infra-heavy, so validation is a mix of automated gates and live spikes (per the
project's pytest + ruff + mypy suite in OVERVIEW):

- **Config validation — unit tests.** New tests in `tests/` asserting the extended
  startup validator: rejects empty DB password and known placeholder creds when
  not in dev mode, and still permits keyless `Settings()` construction (the CI
  path). Mirror the style of `tests/test_session_auth.py` from #016.
- **Build gates.** `docker build` succeeds; `docker compose -f docker-compose.yml
  -f docker-compose.prod.yml config` parses; image runs as non-root
  (`docker run … whoami`).
- **Boot/health spike.** Non-root container boots against compose `db`, reaches
  `docker ps` `healthy`, `es_core_news_sm` loads (vocab returns lemmas), the
  observation sink writes.
- **Backup/restore spike.** dump → drop → restore round-trip preserves learner
  relational rows and the AGE graph.
- **TLS spike.** One full voice turn over `wss://` through the proxy.
- **CD dry-run.** The publish workflow builds and pushes to GHCR from a branch
  (or `workflow_dispatch`) before relying on the `main` trigger.
- **Existing suite unchanged.** `ci.yml` (pytest + scoped ruff + mypy) stays green;
  the publish job is additive.
