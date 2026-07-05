// App shell
const { useState: useStateApp, useEffect: useEffectApp } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "screen": "home",
  "orbVariant": "A",
  "recapVariant": "A",
  "transcript": true
}/*EDITMODE-END*/;

function App() {
  const [state, setState] = useStateApp(() => {
    // hydrate from localStorage if present
    try {
      const saved = JSON.parse(localStorage.getItem('hableya') || 'null');
      return { ...TWEAK_DEFAULTS, ...(saved || {}) };
    } catch { return TWEAK_DEFAULTS; }
  });

  useEffectApp(() => {
    localStorage.setItem('hableya', JSON.stringify(state));
  }, [state]);

  const goto = (screen) => setState((s) => ({ ...s, screen }));

  return (
    <div data-screen-label={`${state.screen}`}>
      {state.screen === 'home' && (
        <Home onStart={() => goto('session')} goto={goto} />
      )}
      {state.screen === 'session' && (
        <Session
          onEnd={() => goto('recap')}
          variant={state.orbVariant}
          transcript={state.transcript}
        />
      )}
      {state.screen === 'recap' && (
        <Recap variant={state.recapVariant} onDone={() => goto('home')} />
      )}
      {state.screen === 'profile' && (
        <Profile onBack={() => goto('home')} />
      )}

      <TweaksPanel state={state} setState={setState} />
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
