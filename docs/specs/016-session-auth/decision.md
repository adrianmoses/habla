# Decision Record: Session auth & single-session enforcement

| Field | Value |
|---|---|
| id | 016 |
| status | implemented |
| created | 2026-07-07 |
| spec | [spec.md](./spec.md) |

---

## Context

`/ws/session` was public and unauthenticated on `0.0.0.0:8000` — an open
cost-DoS on three metered paid APIs, and the one blocker to public deployment
(from the 2026-07-06 deployment-readiness assessment that created #016/#017).
Bundled were three same-path defects: the shared-LLM `register_function` clobber
corrupting `log_turn` routing under concurrent connections; startup fail-fast
covering only Anthropic (bad OpenAI/Cartesia config crashed on first turn); and a
`/health` that re-checked only the DB.

The implementation followed the spec's four-layer design closely. Two things
shaped the work beyond the spec:

1. **A constraint discovered during coding:** the secret fail-fast cannot live in
   `Settings` construction — CI and the whole test suite build `Settings()` with
   no real keys — so it had to run in the lifespan on the serving path only.
2. **Live-validation friction.** Exercising the spike surfaced a chain of
   environment/ergonomics gaps that had nothing to do with the auth code but
   blocked verification: the `db` container was down (startup fail-fast working as
   intended once the *real* cause — no DB — was found), an output-buffering red
   herring that made startup look hung, no test-audio on-ramp, and — the real
   one — the voice client never endpointed because neither it nor the generated
   WAV sent the trailing silence the VAD needs. Fixing these to unblock the spike
   added a small helper and a client fix to this branch (see Spec Divergence).

## Decision

Shipped the spec's layered design in full:

- **Layer 1 (remove the need for a lock):** per-session services
  (`build_session_services`) — each connection owns its LLM/STT/TTS, so the
  per-session `log_turn` handler cannot be clobbered by a concurrent connection.
  Concurrency is now *safe*, demoting the single-session cap from a correctness
  lock to a cost policy.
- **Layer 2 (preemptive cap):** one `app.state.active_session`; a new connection
  installs itself under a lock held only for the pointer swap, then evicts the
  incumbent (`task.cancel` + socket close) *outside* the lock. Newest wins, and
  the finally-clear is identity-guarded so an evicted session can't null its
  successor. A stale/half-open session can never block a new client, and no lock
  is ever held for a session's lifetime.
- **Layer 3 (reap):** `PipelineTask.idle_timeout_secs` set from
  `session_idle_timeout_secs` (was `None`).
- **Layer 4 (auth):** a shared secret checked with `secrets.compare_digest`
  before `accept()`; token via `Sec-WebSocket-Protocol` or `?token=`; fail-closed
  unless `session_auth_disabled`; never logged.
- **Fail-fast:** `require_cloud_secrets` in the lifespan raises at boot naming any
  empty cloud secret. **Reactive health:** the session error path records
  per-provider failures; `/health` returns `degraded` within a 60s window.

Verified by 341 passing offline tests (incl. 13 new auth/enforcement unit tests)
and a live end-to-end spike: a token-gated session streamed audio → STT → Claude
→ Cartesia and returned spoken Spanish (`out.wav`, 197 KB).

---

## Alternatives Considered

### Where to put the cloud-secret fail-fast

**Option A — a pydantic validator on `Settings`.**
- Pros: fails at construction, single choke point.
- Cons: **breaks every test and CI run** — they construct `Settings()` with no
  real keys. Would force test-wide patching or fake keys everywhere.

**Option B — an explicit `require_cloud_secrets(settings)` in the lifespan (chosen).**
- Pros: runs only on the serving path; tests/CI keep constructing `Settings()`
  freely; still boot-time (before `ready = True`).
- Cons: not enforced if some future entry point skips the lifespan.

**Chosen:** B. The serving path is the only place the secrets are actually
required, and it keeps the test surface unchanged. Covered by a direct unit test.

### Eviction: inside vs outside the swap lock

**Option A — cancel the incumbent while holding the swap lock.**
- Pros: strictly one active session at every instant.
- Cons: holds the lock for a potentially slow teardown (Cartesia websocket close),
  reintroducing exactly the "lock held too long" risk the design avoids.

**Option B — swap the pointer under the lock, evict outside it (chosen).**
- Pros: lock held for microseconds; the brief old+new overlap is harmless because
  Layer 1 made services per-session.
- Cons: a sub-second window where two pipelines exist.

**Chosen:** B — it's the concrete payoff of Layer 1, and it honors the spec's
"lock only for the pointer swap" rule.

### `/health` provider signal: reactive vs active

**Chosen: reactive** (spec Q2). The session path records provider errors;
`/health` reads them. Active timer-probing was rejected: it re-introduces API
spend on an idle box and adds a background task, for a marginally more truthful
signal. Trade-off accepted (see below).

---

## Tradeoffs

- **Reactive health is best-effort.** It only sees provider failures that surface
  as exceptions at the `session_ws` level. Errors that Pipecat swallows into
  `ErrorFrame`s inside the pipeline won't flip `/health` to `degraded`. Combined
  with the boot-time fail-fast (which catches the common misconfiguration), this
  is a coarse-but-cheap signal; precise live provider observability is #014.
- **Single shared secret, not identity.** Correct for the single-tenant product,
  but there is no per-user auth, revocation-per-user, or audit of *who*
  connected — rotating the one secret is the only control.
- **Token can reach intermediary logs via the query-param path.** The app never
  logs it, but a proxy might; the subprotocol path avoids this. Cleartext until
  TLS/`wss://` (#017).
- **Per-session services add a small per-connection cost** (new HTTP/websocket
  clients). Negligible (no model load), and the isolation is worth it.
- **Provider→exception classification is heuristic** (by SDK module name); an
  unrecognized error lands in an `unknown` bucket rather than being dropped.

---

### Spec Divergence

The four-layer design, fail-fast, and reactive health were built as specified,
with all four spec Open Questions resolved as agreed (fail-closed, reactive
health, all-three-services per-session, subprotocol/query token). Divergences are
additive — testability refactors and ergonomics needed to *run* the live spike:

| Spec Said | What Was Built | Reason |
|---|---|---|
| Wire the swap inline in `session_ws` | Extracted `_install_active` / `_clear_active` / `_evict` helpers | Deterministically unit-testable without a live pipeline (Pigecat `PipelineTask` doesn't expose its state cleanly) |
| (Live spike as validation) | Added `scripts/make_test_wav.py` + `voice_client.py --token` and a **trailing-silence** fix to both scripts | The spike was un-runnable otherwise: no test-audio existed, and the client never endpointed because it sent no trailing silence for the VAD |
| Token docs implied | Added the token block to `.env.example` + README, a "DB must be up first" README note, and `*.wav` to `.gitignore` | Surfaced while helping run the app/spike; onboarding correctness |
| (Not in scope) | Commented-out the stale `SMART_TURN_STOP_SECS=4.0` in `.env.example` (→ #013's tuned 3.0 default) | Incidental #013 debt found while editing `.env.example`; the active value silently reverted the re-tune |

No spec acceptance criterion was dropped or reinterpreted.

---

## Spec Gaps Exposed

- **`/health` reactive signal can't see pipeline-internal provider errors.** If a
  provider fails in a way Pipecat converts to an `ErrorFrame` (not a raised
  exception reaching `session_ws`), health stays `ok`. Genuine live provider
  health belongs to #014 (API resilience & cost) — flagged there.
- **The voice test harness had no working on-ramp.** The spec assumed a live
  spike was straightforward, but there was no test audio and the client didn't
  endpoint streamed WAVs. Both are now fixed on this branch; worth noting that a
  real-microphone client still does not exist (a possible future helper).
- **`voice_client.py` / `make_test_wav.py` are dev-only and untyped** (scripts/
  is outside the CI mypy scope), so their trailing-silence logic is covered only
  by manual/live use, not automated tests.

---

## Test Evidence

Offline suite (DB up, so the previously-skipped DB-dependent tests also ran):

```
$ uv run pytest -q
341 passed, 9 warnings in 17.08s

$ uv run pytest tests/test_session_auth.py -q
13 passed, 1 warning in 2.09s

$ uv run ruff check hable_ya/ api/ eval/agent/ tests/ scripts/
All checks passed!

$ uv run mypy hable_ya/ api/ eval/agent/
Success: no issues found in 56 source files
```

New `tests/test_session_auth.py` covers: `_authorized` (fail-closed when unset,
match/mismatch, dev-disabled), token extraction (query param / subprotocol / none),
provider classification, `require_cloud_secrets` (raises naming the missing vars),
and the swap/identity-guard/evict helpers (incumbent displacement, guarded clear,
cancel+close). `tests/test_health.py` gained `degraded`-on-recent-error and
expiry cases.

Live end-to-end spike (human-run, real APIs, DB up, `HABLE_YA_SESSION_AUTH_TOKEN`
set):

- App booted to `hable-ya ready` (fail-fast passed with all secrets present; the
  earlier "won't start" was correctly caused by the `db` service being down).
- `voice_client.py in.wav out.wav --token <secret>` over a token-gated session
  drove a full turn — streamed audio endpointed (trailing silence), STT → Claude
  → Cartesia — and returned a spoken Spanish reply (`out.wav`, ~197 KB
  non-empty). The auth gate + per-session pipeline + endpointing all work
  end-to-end.

Not exercised live (covered by the offline helper tests above): the two-client
preemption and killed-client idle-reap paths. The `_install_active` /
`_clear_active` / `_evict` logic and the `idle_timeout_secs` wiring are unit-
tested; a full concurrent live check remains an optional follow-up.
