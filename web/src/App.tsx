import { useState } from 'react';
import Home from './routes/Home';
import Session from './routes/Session';
import Progreso from './routes/Progreso';
import Historial from './routes/Historial';
import Ajustes from './routes/Ajustes';
import { useRoute } from './lib/router';
import type { SessionRequest } from './voice/types';

export default function App() {
  const route = useRoute();
  // The live session is state, not a route (spec OQ2): it holds a microphone
  // permission and an open paid-API socket, so a reload must never restore it.
  const [session, setSession] = useState<SessionRequest | null>(null);
  const [error, setError] = useState<string | undefined>(undefined);

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
