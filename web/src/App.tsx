import { useState } from 'react';
import Home from './routes/Home';
import Session from './routes/Session';

type Route = 'home' | 'session';
type AppState = { route: Route; error?: string };

export default function App() {
  const [state, setState] = useState<AppState>({ route: 'home' });

  if (state.route === 'session') {
    return (
      <Session
        onExit={(reason, msg) =>
          setState({
            route: 'home',
            error: reason === 'error' ? msg : undefined,
          })
        }
      />
    );
  }

  return (
    <Home
      onStart={() => setState({ route: 'session' })}
      error={state.error}
    />
  );
}
