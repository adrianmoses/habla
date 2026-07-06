# Spec: Session auth & single-session enforcement

| Field | Value |
|---|---|
| id | 016 |
| status | implemented |
| created | 2026-07-06 |

---

## Why

The `/ws/session` WebSocket endpoint is public and unauthenticated on a
container that binds `0.0.0.0:8000`. Anyone who can reach the port can open a
voice session and drive spend on three metered paid APIs (Anthropic, OpenAI,
Cartesia) — with no auth, no rate limit, no concurrency cap, and no cost
visibility to even notice. That is an open cost-DoS, and it is the single
blocker that makes public deployment unsafe (deployment-readiness assessment,
2026-07-06). This feature closes it.

Bundled with it are three defects the assessment surfaced in the same request
path, which together turn "the app appears healthy" into a lie:

- **The single-active-session assumption is load-bearing but unenforced.** Each
  connection calls `services.llm.register_function(...)` on the **shared**
  process-global LLM service (`api/routes/session.py:80`). Two concurrent
  connections clobber each other's `log_turn` routing — turns get logged to the
  wrong session, silently corrupting the learner model. The code comment admits
  it is "safe under single-tenant (one active session at a time)" but nothing
  enforces that.
- **Startup fail-fast is incomplete.** `warmup_llm` verifies only Anthropic
  (`api/main.py:67`). A missing/invalid `OPENAI_API_KEY`, `CARTESIA_API_KEY`, or
  empty `CARTESIA_VOICE_ID` passes startup, flips `ready = True`, and crashes on
  the first live turn — despite `config.py:45` claiming the runtime fails fast.
- **`/health` lies.** It re-checks only the DB (`api/routes/health.py`); the
  cloud APIs are verified once at startup and never again, so a revoked or
  quota-exhausted key returns `200 ok` while every session is broken.

### Consumer Impact

- **Operator (primary):** can expose the app to a network without handing out
  free access to their paid-API spend. A misconfigured deploy now fails *at
  startup* with a clear error instead of serving broken sessions, and `/health`
  becomes a load-balancer/uptime signal that actually reflects whether sessions
  will work.
- **End user (learner):** protected from the correctness bug where a second
  connection corrupts the first's turn logging — their learner model stops being
  silently polluted by connection races.

### Roadmap Fit

First of the two deployment-hardening items (#016, #017) from the readiness
assessment; #017 (image/compose/CD/backup) is independent and can follow. #016
is the prerequisite for any public exposure. It **partially overlaps #014** (API
resilience & cost): #014 owns retry/backoff and per-turn token accounting; #016
owns auth, the concurrency cap, and the fail-fast/health honesty. Where they
meet — cost *visibility* — #016 does the minimum (a spend-bounding cap + a
degraded-health signal); #014 later adds real token/cost metering. This split is
noted so the two don't collide when #014 is specced.

---

## What

### Acceptance Criteria

- [ ] `/ws/session` rejects a connection that does not present a valid shared
      secret, **before** `websocket.accept()` and before any paid-API work, with
      a clear close code. A valid secret connects as today.
- [ ] The secret is injected via config (env), never hardcoded; it is **not**
      written to logs (no full-URL-with-token log lines).
- [ ] Concurrent-connection safety: two overlapping sessions never corrupt each
      other's `log_turn` routing or learner-model writes. This holds by
      construction (per-session handler state), not merely because a cap usually
      prevents overlap.
- [ ] At most one *active* session runs at a time, enforced by **preemption**: a
      new valid connection evicts the incumbent (cancels its task + closes its
      socket) and takes over. A stale/half-open session can never block a new
      client — there is no "is it dead yet?" timeout gating new connections.
- [ ] The enforcement lock is held only for the brief incumbent-swap, **never**
      for a session's lifetime — so no long-held lock can go stale and brick the
      app.
- [ ] An abandoned/half-open session is reaped on its own (without needing a new
      connection to displace it) via a pipeline idle timeout — `runner.py`'s
      `idle_timeout_secs=None` is replaced with a configured value.
- [ ] Startup fails fast on any missing required cloud config: empty
      `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CARTESIA_API_KEY`, or
      `CARTESIA_VOICE_ID` prevents the app reaching `ready = True` (crash at
      startup, not first turn), with a message naming the missing var(s).
- [ ] `/health` reflects cloud-API health, not just DB: it reports a degraded
      status when a provider is known-bad (see Approach for the mechanism), so a
      `200 ok` means sessions can actually run.
- [ ] CI stays green (`pytest`, CI-scoped `ruff`, CI-scoped `mypy`); new
      `hable_ya/`/`api/` code is mypy-clean.

### Non-Goals

- **Not** multi-tenant auth. A single shared secret matches the single-tenant
  product (one learner per deployment). Per-user identity, JWT/OAuth, user
  accounts, and session-to-user mapping are out of scope.
- **Not** horizontal scaling. Enforcement is in-memory, single-process; a
  process restart is a clean reset. No Redis/distributed lock — the product is
  single-tenant and does not run multiple app replicas.
- **Not** full per-turn token/cost metering — that is #014. #016 bounds spend
  via the single-session cap and surfaces a coarse degraded signal only.
- **Not** rate-limiting beyond the single-active-session cap (no per-IP limiter,
  no request quotas) — deferred to #014 if needed.
- **Not** TLS/`wss://` termination or reverse-proxy config — that is #017.

### Open Questions

All four resolved (owner-confirmed 2026-07-07) along their proposed defaults:

- **Q1 — unset-secret behavior. RESOLVED: fail-closed.** No secret configured →
  refuse all WS connections, with an explicit dev opt-out flag (mirroring
  `dev_endpoints_enabled`) so local `voice_client.py` still works. Fail-open was
  rejected as re-creating the footgun this feature removes.
- **Q2 — `/health` provider signal. RESOLVED: reactive.** The session path
  records provider errors into `app.state`; `/health` reports `degraded` when a
  provider failed recently. No timer-driven probing (would re-introduce spend on
  an idle box).
- **Q3 — per-session isolation scope. RESOLVED: all three services per-session.**
  Construct LLM + STT + TTS fresh per connection (cheap — clients/websockets, no
  model load) for full isolation, so overlap during a racy eviction is harmless.
  Shared instances remain only for startup warmup/health probes.
- **Q4 — token transport. RESOLVED:** accept the token via `Sec-WebSocket-Protocol`
  subprotocol **or** query param, never log it; TLS in prod is #017's job.

---

## How

### Approach

The core reframe: **the single-session requirement is self-inflicted, so the
fix is to remove the reason it exists first, then make the cap a forgiving
policy rather than a brittle lock.** Four layers, in priority order.

**Layer 1 — remove the concurrency correctness bug (per-session handler state).**
Today `session.py:80` mutates the shared `app.state.services.llm`. Give each
session its own `log_turn` handler binding so a second connection cannot corrupt
a first. Because Pipecat's `register_function` is service-global, the clean way
is to construct a **per-session LLM service** in the handler (cheap — wraps
`AsyncAnthropic`, no weights) and register the handler on *that*. Per Q3, extend
the same per-session construction to STT/TTS for full isolation. Keep the shared
instances (`load_services`) only for the startup warmup/health probes. After
this, concurrent sessions are *safe*, so the cap below is about cost/politeness,
not correctness.

**Layer 2 — preemptive single-session cap (newest wins).** Hold one
`app.state.active_session` handle (session id + a cancel/close hook). On a new
valid connection, under a short `asyncio.Lock`: if an incumbent exists, cancel
its `PipelineTask` and close its socket, await teardown, then install the new
session and release the lock **before** running the pipeline. The lock guards
only the pointer swap (microseconds), never the session lifetime — so it cannot
go stale. "Newest wins" is the correct single-tenant semantics (same learner
reconnecting/refreshing) and structurally prevents a dead session from blocking
a live client, with no death-timeout to tune.

**Layer 3 — proactive reaping.** Set `runner.py`'s `PipelineTask`
`idle_timeout_secs` (currently `None`, `runner.py`) from a new config knob, so a
session with no audio activity self-terminates even when no new connection
arrives to evict it. This closes the half-open-socket window that Layer 2 only
covers on the *next* connect.

**Layer 4 — auth gate.** Add `session_auth_token` (+ any dev opt-out per Q1) to
`config.py`. In `session_ws`, validate the presented secret **before**
`accept()` and before the DB/theme/prompt work; on mismatch close with a policy
code and return. Never log the token.

**Fail-fast (AC 7).** Validate the four required secrets are non-empty at
startup — either as a pydantic validator on `Settings` or an explicit check in
the lifespan before `ready = True` — raising with the missing var names. This
turns today's first-turn crash into a boot-time crash.

**Honest health (AC 8).** Per Q2 (reactive), track a per-provider "last error"
signal in `app.state` written by the session error path; `/health` returns
`degraded` (503) when a provider is known-bad, `ok` only when DB + all providers
are healthy. Report per-provider status in the JSON body.

Touch points: `api/routes/session.py` (auth gate, per-session services,
preemptive swap), `hable_ya/pipeline/runner.py` (`idle_timeout_secs`),
`hable_ya/pipeline/services.py` (per-session constructors vs shared warmup),
`hable_ya/config.py` (token, dev opt-out, idle-timeout knob, secret validation),
`api/main.py` (startup validation, active-session state init), `api/routes/health.py`
(provider health), `scripts/voice_client.py` (send the token).

### Confidence

**Level:** Medium

**Rationale:** The design is well understood and grounded in the actual code
(`session.py` fully read; `register_function`/`unregister_function`,
`idle_timeout_secs`, and the health/warmup paths all confirmed). The auth gate,
fail-fast, and idle timeout are low-risk. The uncertainty is in the
concurrency-sensitive parts: getting the preemptive eviction + per-session
service teardown clean (no leaked Cartesia websocket, cancellation propagating
through Pipecat's `task.run` to the `finally` that calls `end_session`), and the
per-session-service scope (Q3). These need live exercise, not just unit tests.

**Validate before proceeding:** (Q1–Q4 resolved above.)
- Spike the eviction path: open session A, connect session B, assert A's task is
  cancelled and its `end_session`/socket-close run before B starts, with no
  leaked TTS websocket and no cross-logging. A half-open A (killed client, no
  close frame) must be displaced by B and also reaped by the idle timeout.
- Verify per-session LLM/STT/TTS construction cost is negligible (no model load,
  just client/websocket setup) so per-connection isolation is acceptable.

### Key Decisions

- **Remove the need for a lock, don't build a better lock.** Per-session handler
  state (Layer 1) makes concurrency *safe*, demoting the cap to a cost policy.
  The alternative — keep shared services and rely on the eviction being perfectly
  clean — makes Layer 2 load-bearing for correctness and is exactly the brittle
  design this avoids.
- **Preemption over rejection.** Newest-connection-wins eliminates the
  stale-session-blocks-everyone failure without a death-timeout heuristic;
  rejection ("refuse the second connection") would require deciding when the
  first is dead — the finicky call that bricks naive implementations.
- **Lock scope = pointer swap only.** The single-session lock is never held for
  a session's duration, so it has no stale-lock failure mode by construction.
- **In-memory, single-process.** No distributed lock; matches the single-tenant
  non-goal and keeps a process restart a clean reset.
- **Shared secret, not identity auth.** Single-tenant means one static secret is
  sufficient; per-user auth is scope creep against the product's single-tenant
  design.

### Testing Approach

Per OVERVIEW's suite (pytest, `asyncio_mode=auto`), offline where possible:

- **Auth gate:** connection with no/invalid token is closed pre-`accept` with the
  policy code and does no DB/API work; valid token proceeds. Token never appears
  in captured logs.
- **Preemptive eviction (unit/integration):** with stubbed services + a fake
  transport, open A then B; assert A's task received cancellation, A's
  `end_session` ran, `app.state.active_session` points at B, and the swap lock is
  released (not held) while B runs. A third connection evicts B.
- **No cross-corruption:** two sessions each register a `log_turn` handler;
  assert each session's turns route to its own sink/session id (guards Layer 1
  regardless of eviction timing).
- **Idle reap:** a session with no frames past `idle_timeout_secs` terminates and
  clears `active_session` (drive via the pipeline task, short timeout).
- **Fail-fast:** `Settings`/startup with any of the four secrets empty raises at
  boot naming the var; all-present starts. (Offline — no live API.)
- **Health honesty:** with a recorded provider error in `app.state`, `/health`
  returns `degraded`; cleared → `ok`; DB down still → `db_unreachable`.
- **Live (human-run):** `voice_client.py` with the token against a running app —
  a real session works; a second concurrent client cleanly takes over; a killed
  client is reaped; a deliberately-wrong OpenAI key fails at startup.
