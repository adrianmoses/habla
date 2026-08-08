# Spec: La Libreta speaking-session handoff

| Field | Value |
|---|---|
| id | 033 |
| status | implemented |
| created | 2026-08-08 |
| upstream contract | `la-libreta/docs/specs/012-deep-links/companion-interface.md` |

---

## Why

La Libreta has an **Enviar a Habla** action for speaking prompts. That action
cannot currently hand a prompt to Habla: Habla exposes only the live
`/ws/session` connection, creates an ephemeral session id after the socket
opens, and deliberately keeps the active session as in-memory UI state at `/`.
There is no HTTP create endpoint, durable external prompt, or addressable
session route.

La Libreta feature 012 defines the companion-side contract it needs before it
can wire the action. Habla must accept an authenticated server-to-server push,
create or recover a durable session handoff, and return a browser URL that
survives navigation and authentication. The handoff must preserve La Libreta's
prompt verbatim and must be safe to retry.

This spec records that contract on the Habla side. The upstream document remains
the integration source; incompatible wire-format changes require coordination
with La Libreta rather than a unilateral Habla change.

### Consumer Impact

- **La Libreta server.** It can create a speaking session and redirect the
  browser to the returned URL. Repeated requests for the same daily prompt are
  safe.
- **Habla learner.** Opening the returned URL starts a session steered by the
  supplied prompt, grammar structures, and target instead of a Habla-selected
  topic.
- **Habla operator.** A separate integration secret can be rotated without
  changing the end-user session credential.
- **La Libreta activity tracking.** If a callback URL was supplied, completing
  the session can stamp the corresponding speaking activity automatically.

### Roadmap Fit

This is the Habla companion to La Libreta feature 012. It builds on Habla #016
(session authentication), #018/#020 (deployed frontend and routing), and #023
(targeted conversations), but introduces a different trust boundary and a
durable pre-session resource.

---

## What

### HTTP create contract

Habla exposes:

```http
POST /api/sessions
Authorization: Bearer <LA_LIBRETA_API_TOKEN>
Content-Type: application/json
```

Request body:

```json
{
  "source": "la-libreta",
  "sourceRef": "p02",
  "mode": "speaking",
  "text": "Describe una decisión que habrías tomado de otra forma si hubieras sabido entonces lo que sabes ahora.",
  "structures": [
    "condicional compuesto",
    "pluscuamperfecto de subjuntivo"
  ],
  "target": "monólogo de 3 minutos",
  "date": "2026-05-02",
  "callbackUrl": "https://la-libreta.fly.dev/api/companion-callback"
}
```

| Field | Required | Contract |
|---|---|---|
| `source` | yes | External app identifier. Only `"la-libreta"` is accepted initially. |
| `sourceRef` | yes | Stable La Libreta prompt id. Opaque to Habla. |
| `mode` | yes | Only `"speaking"` is accepted initially. Unknown values return `400`. |
| `text` | yes | Speaking prompt. Stored and rendered verbatim. |
| `structures` | yes | Array of target grammar structures. Stored and rendered verbatim. |
| `target` | yes | Spanish duration/length hint. Stored and rendered verbatim; Habla does not parse it. |
| `date` | yes | ISO `YYYY-MM-DD`, computed by La Libreta in `Europe/Madrid`. Part of the idempotency key. |
| `callbackUrl` | no | HTTPS completion receiver. See Callback contract and SSRF requirements. |

Unknown top-level fields are ignored. Unknown enum values are rejected rather
than silently mapped to a fallback. Required strings must not be blank;
`structures` must be an array of strings; and malformed dates or URLs return
`400` without creating a row.

The endpoint returns `201 Created` for a new handoff and `200 OK` when the
idempotency key already exists. Both responses have the same body:

```json
{
  "id": "sess_2x9c...",
  "url": "https://habla.example.com/session/sess_2x9c...",
  "createdAt": "2026-05-02T07:14:22.000Z"
}
```

- `id` is an opaque, non-guessable Habla identifier.
- `url` is an absolute browser-facing URL, built from configured public origin,
  never inferred from an untrusted `Host` or forwarded header.
- `createdAt` is the original creation timestamp and does not change on replay.

Errors:

- `400` for an invalid body or unsupported enum value.
- `401` for a missing or invalid integration bearer token. The response and
  logs must not reveal the expected token.
- `5xx` for an unexpected server failure. No partial handoff may be returned.

### Idempotency and persistence

The database enforces uniqueness on `(source, source_ref, source_date)`. The
create operation is race-safe: two concurrent matching requests produce one
row and return the same `id`, `url`, and `createdAt`.

The first successfully stored payload wins. A later request with the same key
returns the existing handoff even if its non-key fields differ; Habla does not
silently mutate an already-created session. A structured warning may record a
payload mismatch, but it must not include the bearer token. This behavior makes
re-entry deterministic and avoids changing the learner's prompt behind an
existing deep link.

The persisted handoff includes every contract field, its generated id and
creation timestamp, callback delivery state, and enough lifecycle state to
distinguish created, started, and completed. Schema changes are delivered as an
Alembic migration with a working downgrade in line with #031.

### Browser route and session startup

Habla exposes `GET /session/:id` through the SPA fallback. The frontend resolves
the handoff before opening the microphone or the paid-provider WebSocket.

- A known, usable id renders a pre-session view containing the prompt,
  structures, and target verbatim. Starting from that view opens the existing
  live voice session with an opaque handoff identifier; the browser does not
  resend authoritative prompt text.
- An unknown id renders a clear not-found state and does not fall back to Home
  as though the route were `/`.
- Reloading or revisiting the URL never starts microphone capture or paid API
  work automatically. The learner must explicitly start.
- The handoff payload is incorporated into the server-built session prompt. It
  does not replace Habla's system instructions and is treated as untrusted
  external content, not executable instructions.
- The existing single-active-session/preemption policy continues to apply.

Habla currently has shared-secret end-user session auth rather than a login
page. Therefore the upstream requirement to preserve `/session/:id` through an
auth round trip means: if the end-user token is absent or rejected, the UI asks
for it without navigating away from the deep link, then resumes the same
pre-session view after successful authentication. A future real login flow must
carry an encoded relative redirect to the same route and reject open redirects.

The integration token authenticating `POST /api/sessions` is never sent to or
stored in the browser. Starting the WebSocket remains protected by the existing
end-user `HABLE_YA_SESSION_AUTH_TOKEN`; the two credentials are not
interchangeable.

### Callback contract

When a handoff-backed session reaches Habla's explicit completed state and the
create payload included `callbackUrl`, Habla sends:

```http
POST <callbackUrl>
Authorization: Bearer <LA_LIBRETA_API_TOKEN>
Content-Type: application/json
```

```json
{
  "source": "la-libreta",
  "sourceRef": "p02",
  "date": "2026-05-02",
  "modality": "speaking",
  "completedAt": "2026-05-02T07:32:11.000Z"
}
```

Callback delivery is best-effort and never blocks or reverses local session
completion. Habla attempts delivery once and retries once only after a `5xx` or
transport failure. It does not retry a `4xx`. Attempts use bounded connect/read
timeouts and are observable without logging the authorization header.

Because `callbackUrl` causes the server to make an outbound request, production
configuration must constrain destinations to an explicit HTTPS origin allowlist
(initially La Libreta's configured public origin). Redirects are disabled. Loopback,
link-local, private-network, credential-bearing, non-HTTPS, and otherwise
unapproved destinations are rejected at create time. DNS resolution at delivery
must not provide a rebinding path around the policy.

Repeating a UI completion action or reconnecting must not create duplicate
successful callbacks. Delivery state is persisted, and a successfully delivered
callback is terminal.

### Configuration

Habla adds server-only configuration for:

- `LA_LIBRETA_API_TOKEN`: required to authorize La Libreta creates and callback
  requests. It is separate from `HABLE_YA_SESSION_AUTH_TOKEN`.
- `HABLE_YA_PUBLIC_BASE_URL`: canonical externally reachable origin used to
  build the response `url`.
- A callback-origin allowlist, defaulting to no allowed callbacks unless
  explicitly configured.

Production startup fails closed if the integration route is enabled without a
non-empty integration token or canonical public base URL. Local development may
disable the integration explicitly; an unset token never makes the endpoint
public.

### Acceptance Criteria

- [x] `POST /api/sessions` implements the exact request, response, status, and
      forward-compatibility contract above.
- [x] Integration auth uses a dedicated bearer secret and constant-time token
      comparison; missing or invalid credentials return `401`.
- [x] `(source, sourceRef, date)` idempotency is enforced in the database and
      remains correct under concurrent requests.
- [x] The stored first payload wins on idempotent replays; replay does not alter
      `createdAt` or callback state.
- [x] Response URLs use a configured canonical public origin and opaque ids.
- [x] `GET /session/:id` is a real deep link with pre-session, not-found, and
      end-user-auth states; reload never auto-starts microphone or providers.
- [x] Starting the session resolves the server-owned handoff and steers the
      system-built conversation prompt with its verbatim prompt, structures,
      and target.
- [x] The browser never receives the La Libreta integration token and cannot
      substitute authoritative handoff content.
- [x] Completing a handoff-backed session persists one completion timestamp and
      performs the optional callback without blocking the learner experience.
- [x] Callback delivery retries once on `5xx`/transport failure, never on `4xx`,
      uses bounded timeouts, and cannot deliver twice successfully.
- [x] Callback URL validation and delivery prevent SSRF and redirects as
      described above.
- [x] Logs and errors contain no bearer tokens; lifecycle and callback failures
      remain diagnosable by handoff id and source reference.
- [x] Alembic upgrade and downgrade tests cover the new persistence schema.
- [x] API tests cover validation, unknown-field tolerance, auth, idempotency,
      concurrency, payload mismatch, and canonical response URLs.
- [x] Frontend tests cover direct navigation, reload, unknown ids, auth recovery,
      explicit start, and rendering contract fields verbatim.
- [x] Callback tests cover absence, success, timeout, one retry on `5xx`, no
      retry on `4xx`, duplicate completion, and rejected destinations.
- [x] Existing WebSocket authentication, single-session preemption, targeted
      conversations, and ordinary Home-started sessions continue to pass.
- [x] `ruff`, `mypy`, Python tests, and frontend tests/build pass.

### Non-Goals

- Multi-tenant OAuth, user delegation, or mapping La Libreta users to Habla
  users. All apps remain single-operator deployments.
- General-purpose session creation for arbitrary third parties. Only the
  `la-libreta` source and `speaking` mode are accepted initially.
- Importing or synchronizing La Libreta's prompt catalog. Each request is an
  ad-hoc handoff.
- Letting La Libreta bypass Habla's end-user session authentication.
- Parsing `target` into a timer or enforcing its duration.
- Making callback success part of Habla session completion.
- Replacing the existing voice pipeline, session preemption policy, or learner
  model.

### Open Questions

1. **What event means “completed”?** The upstream contract says “when the user
   marks the session complete,” while the current UI has only close/exit and
   WebSocket teardown. Implementation must define an explicit completion action
   distinct from disconnect, error, timeout, or preemption; otherwise callbacks
   will over-report practice.

2. **How does the WebSocket identify the handoff?** The preferred shape is an
   opaque `handoff=<id>` query value resolved server-side after end-user auth.
   It keeps prompt content out of the URL and prevents browser tampering. The
   exact parameter name is internal, but its authorization and lookup semantics
   must be tested.

3. **What is the production La Libreta origin?** It must be explicitly
   configured before callbacks can be enabled. The example
   `https://la-libreta.fly.dev` is documentation, not an implicit allowlist.

---

## How

### Proposed approach

**1. Add the durable handoff model**

Create an Alembic migration for an external-session-handoff table. Use a UUID or
equivalent random public identifier, a unique constraint on the three-part
source key, JSON-capable storage where it preserves forward-compatible payload
data, explicit lifecycle timestamps, and callback attempt/delivery fields.

**2. Add a narrow integration router**

Keep `POST /api/sessions` separate from `api/routes/session.py`'s live WebSocket
handler so server-to-server authentication and end-user session authentication
cannot be accidentally conflated. Validate with a dedicated request model that
forbids no unknown fields (ignore extras) but strictly checks known fields and
enums. Implement insert-or-select idempotency around the database constraint.

**3. Resolve handoffs at the server boundary**

Add an authenticated read/start path needed by the frontend and WebSocket. The
server loads the handoff and converts it into a targeted conversation input.
Extend prompt construction with a typed external-speaking context whose strings
are clearly delimited as learner material, retaining Habla's system policy and
tool instructions.

**4. Make `/session/:id` a first-class frontend route**

Extend the minimal router rather than adding a routing dependency solely for
one parameterized path. Render a preflight surface, preserve the route while the
session token is entered, and pass only the opaque handoff id when the learner
starts. Keep the existing explicit microphone start behavior.

**5. Persist completion and deliver callbacks out of band**

Add an explicit completion action. Commit completion locally before attempting
the callback. A small delivery service applies allowlist/SSRF validation,
timeouts, retry policy, and idempotent state transitions. Callback failure is
recorded and logged but never returned as failure to the learner's completion
action.

**6. Verify both sides of the trust boundary**

Use API integration tests for authentication and races, frontend tests for deep
links and no-auto-start behavior, prompt tests proving handoff data steers but
does not replace system instructions, and a fake HTTP transport for callback
policy. Reintroduce at least the duplicate-create race and duplicate-completion
defects to demonstrate that the corresponding tests fail.

### Confidence

**Level:** Medium

**Rationale:** The external wire contract is explicit and Habla has clear
extension points for API routing, PostgreSQL persistence, prompt construction,
and frontend navigation. The unresolved completion event is a product decision,
and safe callback delivery adds meaningful security and lifecycle behavior. Both
should be resolved at approval before implementation begins.

### Key decisions proposed for approval

1. **Model the created object as a durable handoff, not a live voice session.**
   `POST /api/sessions` must return the name required by the external contract,
   but internally the row exists before microphone consent or a WebSocket. This
   avoids claiming that paid session work has begun and lets deep links survive
   reloads.

2. **Keep integration auth and learner auth separate.** La Libreta may create a
   handoff but cannot use that authority to open a learner's microphone or paid
   provider connection. This preserves #016's trust boundary.

3. **First payload wins for an idempotency key.** Returning an existing row
   while mutating it would make an old deep link change meaning. Rejecting a
   mismatch would undermine the upstream requirement to return the existing
   session. Stable replay with an observable warning is deterministic.

4. **Allowlist callback origins.** The upstream payload supplies a URL, but
   unrestricted server-side fetching would create an SSRF primitive. A
   single-operator integration has no need for arbitrary callback destinations.

5. **Never auto-start on a deep link.** This preserves Habla #020's safety
   rationale: a bookmark or reload must not silently acquire the microphone or
   incur paid API work.
