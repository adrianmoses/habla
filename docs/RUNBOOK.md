# Deployment Runbook

Operational procedures for deploying and running `habla` (spec #017). Single-host
Docker Compose, single-tenant. The base `docker-compose.yml` is the local-dev
stack; `docker-compose.prod.yml` is the production overlay (non-root image behind
Caddy/TLS, no host-published ports, injected secrets).

Requires **Docker Compose v2.24.4+** (the prod overlay uses the `!reset` /
`!override` merge tags to unpublish ports and swap the data volume).

---

## Topology

| | Local (`docker-compose.yml`) | Prod (`+ docker-compose.prod.yml`) |
|---|---|---|
| App | `build: .`, root-less image, `ws://localhost:8000` | pulled `ghcr.io/adrianmoses/habla`, behind Caddy |
| App ports | `8000:8000` published | none published (traffic via Caddy) |
| DB ports | `5433:5432` published | none published (internal only) |
| TLS | none | Caddy, automatic ACME for `$DOMAIN` |
| DB creds | placeholder `hable_ya:hable_ya` | injected `POSTGRES_*` (fail-fast if unset/placeholder) |
| Data volume | named `appdata` | named `appdata` |

The app runs as non-root (uid 10001). `/app/data` (the turn-observation sink,
`runtime_turns.jsonl`) is a **named volume** in both stacks so the non-root user
can write it. Inspect it with:

```bash
docker compose exec app cat /app/data/runtime_turns.jsonl
```

---

## Secrets

Provider keys are read from the app service `env_file: .env` (see `.env.example`):
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID`,
`HABLE_YA_SESSION_AUTH_TOKEN`. The app fails fast at startup if any is empty
(spec #016).

The prod overlay additionally requires, in the shell env or a project-level `.env`
in the compose working directory:

```bash
POSTGRES_USER=habla
POSTGRES_PASSWORD=$(openssl rand -base64 24)   # NOT the placeholder
POSTGRES_DB=habla
DOMAIN=habla.example.com                        # public DNS → this host
ACME_EMAIL=you@example.com
```

Compose refuses to start (`${VAR:?}`) if any is unset. The app **also** rejects an
empty or placeholder (`hable_ya`) DB password at startup
(`HABLE_YA_ALLOW_DEFAULT_DB_CREDENTIALS` is `true` in the base file for local dev,
forced `false` in the overlay).

---

## First deploy (production)

Prereqs: `$DOMAIN` resolves (public DNS A/AAAA) to the host, and TCP **80 + 443**
are reachable — Caddy needs both for the ACME HTTP-01 challenge and for `wss://`.

1. Publish the image (CI does this on merge to `main` → `ghcr.io/adrianmoses/habla:latest`;
   or push a `v*` tag for a pinned `v<version>`).
2. On the host, create `.env` with the provider keys + session token, and export
   the `POSTGRES_*` / `DOMAIN` / `ACME_EMAIL` values (above).
3. Start:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   ```

4. On first boot the app runs Alembic migrations automatically (see **Migrations**),
   creates the AGE extension + `learner_knowledge` graph, seeds the learner /
   scenario graph nodes, warms the LLM, then reports healthy. Watch:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f app
   docker compose -f docker-compose.yml -f docker-compose.prod.yml ps   # app → healthy
   ```

The container `HEALTHCHECK` polls `/health`, which is 200 only when the app is
warm, the DB is live, and no cloud provider is degraded (spec #016). Caddy waits
for `app` to be healthy before starting.

---

## Redeploy

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull app
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d app
```

`pull_policy: always` + `restart: unless-stopped` mean a new `latest` (or a bumped
`image:` tag) is fetched and the container is recreated. Any pending migrations
run on boot (below). To pin a specific build, set `image:` to a `sha-<short>` or
`v<version>` tag instead of `latest`.

---

## Migrations

Migrations are **boot-coupled**: the app lifespan calls `upgrade_to_head()`
(`api/main.py`) before serving, so a redeploy that ships new revisions applies
them automatically. Migrations own the AGE extension, the `learner_knowledge`
graph creation, all relational tables, and the initial `learner_profile` row.

> **Caveat — graph node seeding is NOT in migrations.** The `:Learner` and
> `:Scenario` graph *nodes* are seeded by the app lifespan
> (`ensure_learner_node` / `ensure_scenario_nodes`), not by Alembic. So running
> migrations alone (below) yields schema + empty graph + the `learner_profile`
> row, but not the seeded nodes — those appear when the app boots. (`:Learner` is
> also created lazily on the first logged turn.)

**Standalone / review-first migrations** (optional; the boot-coupled path is the
default). To apply migrations without starting the app — e.g. to review or run
them during a maintenance window:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm app \
  python scripts/init_db.py
```

`scripts/init_db.py` is idempotent and runs the same `upgrade_to_head()`; it
assumes the DB + role already exist (the Postgres image creates them from
`POSTGRES_*`).

---

## Backup & restore

The database (relational learner state **and** the Apache AGE graph) backs up with
a single custom-format `pg_dump`. AGE round-trips cleanly: the dump carries
`CREATE EXTENSION age`, the graph registration, the label tables, and all
vertex/edge rows (verified in the #017 spike).

**Back up** (writes a timestamped dump to `./backups/`, gitignored):

```bash
scripts/backup_db.sh
# or: scripts/backup_db.sh /path/to/out.dump
```

**Restore** — target must be an **empty** database (e.g. a fresh `pgdata` volume,
where the Postgres image auto-creates `$POSTGRES_DB`):

```bash
# fresh volume: bring up only the db so it initializes an empty $POSTGRES_DB
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d db
scripts/restore_db.sh backups/habla-<db>-<timestamp>.dump
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d   # start app + caddy
```

Both scripts run `pg_dump`/`pg_restore` inside the `db` container via
`docker compose exec`, so they work even though the DB is not host-published in
prod. They read `POSTGRES_USER` / `POSTGRES_DB` from the env (default `hable_ya`).

> Schedule `backup_db.sh` from host cron for routine backups. Restoring over a
> populated DB is not supported — recreate the volume/DB first.

---

## Rollback

1. Redeploy the previous image tag:

   ```bash
   # set app.image to the prior sha-<short> or v<version>, then:
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d app
   ```

2. If a bad migration corrupted data, restore the pre-deploy backup into a fresh
   volume (**Backup & restore**) and bring the prior image back up. There is no
   automatic down-migration path; roll forward with a fix or restore from backup.

---

## Local development

Unchanged, TLS-free:

```bash
docker compose up            # builds the image, serves ws://localhost:8000
```

The base file keeps the published ports and the placeholder DB creds, and sets
`HABLE_YA_ALLOW_DEFAULT_DB_CREDENTIALS=true` so the secure-credential fail-fast
doesn't fire on the dev placeholder. Turn logs live in the `appdata` volume (see
**Topology**).
