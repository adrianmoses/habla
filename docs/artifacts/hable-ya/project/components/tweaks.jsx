// Tweaks panel
const { useState: useStateTweaks, useEffect: useEffectTweaks } = React;

function TweaksPanel({ tweakable, state, setState }) {
  const [active, setActive] = useStateTweaks(false);

  useEffectTweaks(() => {
    const handler = (e) => {
      if (e.data?.type === '__activate_edit_mode') setActive(true);
      if (e.data?.type === '__deactivate_edit_mode') setActive(false);
    };
    window.addEventListener('message', handler);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', handler);
  }, []);

  if (!active) return null;

  const persist = (key, value) => {
    setState({ ...state, [key]: value });
    window.parent.postMessage({
      type: '__edit_mode_set_keys',
      edits: { [key]: value },
    }, '*');
  };

  return (
    <div className="tweaks-panel">
      <h4>⚙ TWEAKS — hable ya</h4>

      <div className="tweaks-row">
        <label className="tweaks-label">Vista</label>
        <div className="tweaks-segments">
          {['home', 'session', 'recap', 'profile'].map((s) => (
            <button key={s}
              className={'tweaks-seg ' + (state.screen === s ? 'active' : '')}
              onClick={() => persist('screen', s)}>{s}</button>
          ))}
        </div>
      </div>

      <div className="tweaks-row">
        <label className="tweaks-label">Orbe en sesión</label>
        <div className="tweaks-segments">
          {[['A', 'halo'], ['B', 'bars'], ['C', 'liquid']].map(([v, name]) => (
            <button key={v}
              className={'tweaks-seg ' + (state.orbVariant === v ? 'active' : '')}
              onClick={() => persist('orbVariant', v)}>{name}</button>
          ))}
        </div>
      </div>

      <div className="tweaks-row">
        <label className="tweaks-label">Recap</label>
        <div className="tweaks-segments">
          {[['A', 'editorial'], ['B', 'dashboard'], ['C', 'letter']].map(([v, name]) => (
            <button key={v}
              className={'tweaks-seg ' + (state.recapVariant === v ? 'active' : '')}
              onClick={() => persist('recapVariant', v)}>{name}</button>
          ))}
        </div>
      </div>

      <div className="tweaks-row">
        <div className="tweaks-toggle">
          <label className="tweaks-label" style={{ margin: 0 }}>Mostrar transcripción</label>
          <div
            className={'toggle-pill ' + (state.transcript ? 'on' : '')}
            onClick={() => persist('transcript', !state.transcript)} />
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { TweaksPanel });
