import { describe, expect, it } from 'vitest';
import { withRequest } from './client';

const WS = 'wss://habla.example.com/ws/session';

describe('withRequest', () => {
  it('leaves the default open request as a bare socket URL', () => {
    expect(withRequest(WS, { mode: 'open' })).toBe(WS);
  });

  it('carries mode and topic (spec #023)', () => {
    expect(withRequest(WS, { mode: 'debate', topic: 'el teletrabajo' })).toBe(
      `${WS}?mode=debate&topic=el+teletrabajo`,
    );
  });

  it('carries a handoff as an opaque id and nothing more (spec #033)', () => {
    const url = withRequest(WS, { mode: 'open', handoff: 'sess_2x9c' });

    expect(url).toBe(`${WS}?handoff=sess_2x9c`);
    // The consigna, structures and target stay server-side. If they ever
    // appeared here, a learner could rewrite the tutor's instructions by
    // editing a URL — and the id would stop being the only thing the WebSocket
    // trusts.
    expect(url).not.toContain('text');
    expect(url).not.toContain('structures');
  });

  it('never sends the session token in the URL', () => {
    // #016 puts the secret on the subprotocol handshake, out of access logs.
    // A handoff must not have quietly reopened the query-string path.
    expect(withRequest(WS, { mode: 'open', handoff: 'sess_2x9c' })).not.toContain(
      'token',
    );
  });
});
