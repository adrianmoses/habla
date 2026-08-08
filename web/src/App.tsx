import { useState } from 'react';
import Home from './routes/Home';
import Handoff from './routes/Handoff';
import Session from './routes/Session';
import Progreso from './routes/Progreso';
import Historial from './routes/Historial';
import Ajustes from './routes/Ajustes';
import { useHandoffId, useRoute } from './lib/router';
import { useHealth } from './lib/health';
import { useAuthGuard } from './lib/learner';
import type { SessionRequest } from './voice/types';

export default function App() {
  const route = useRoute();
  const handoffId = useHandoffId();
  // One rule for every authed screen: no token means Home, where the prompt is.
  // `/session/:id` is the exception and says so in `useAuthGuard` — it asks for
  // the token without navigating, so a La Libreta link survives the round trip.
  useAuthGuard(route);
  // The live session is state, not a route (spec OQ2): it holds a microphone
  // permission and an open paid-API socket, so a reload must never restore it.
  // A #033 deep link does not change that — `/session/:id` addresses the
  // durable handoff, and the session it can start is still this state.
  const [session, setSession] = useState<SessionRequest | null>(null);
  const [error, setError] = useState<string | undefined>(undefined);
  const health = useHealth();

  if (session) {
    return (
      <Session
        request={session}
        onExit={(reason, msg) => {
          setSession(null);
          setError(reason === 'error' ? msg : undefined);
        }}
      />
    );
  }

  switch (route) {
    case 'handoff':
      return (
        <Handoff
          id={handoffId}
          ready={health === 'ready'}
          onStart={(request) => {
            setError(undefined);
            setSession(request);
          }}
        />
      );
    case 'progreso':
      return <Progreso />;
    case 'historial':
      return <Historial />;
    case 'ajustes':
      return <Ajustes />;
    default:
      return (
        <Home
          onStart={(request) => {
            setError(undefined);
            setSession(request);
          }}
          error={error}
        />
      );
  }
}
