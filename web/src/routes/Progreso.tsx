// Progreso — what the learner model knows, in the learner's own language.
//
// Reads #019's profile and band-history endpoints. The register is María's, not
// a metrics dashboard: raw field names (`l1_reliance`, `error_counts`) never
// reach the screen, and errors are framed as what the learner is working on
// rather than a defect list — the same non-explicit-correction stance the tutor
// itself takes.

import AppShell from '../components/AppShell';
import {
  Empty,
  ErrorNotice,
  Eyebrow,
  Meter,
  page,
  Panel,
  PageTitle,
} from '../components/ui';
import {
  errorLabel,
  formatRelative,
  toPercent,
  vocabByProduction,
} from '../lib/format';
import { useBandHistory, useLearnerProfile } from '../lib/learner';
import type { BandChange } from '../lib/types';

function bandChangeLine(change: BandChange): string {
  switch (change.reason) {
    case 'placement':
      return `Empezaste en ${change.to_band}`;
    case 'auto_promote':
      return `Subiste de ${change.from_band ?? '—'} a ${change.to_band}`;
    case 'auto_demote':
      return `Ajusté tu nivel a ${change.to_band} para que practiques con calma`;
    default:
      return `Tu nivel pasó a ${change.to_band}`;
  }
}

export default function Progreso() {
  const profile = useLearnerProfile();
  const bands = useBandHistory();

  const p = profile.data;

  const title = p
    ? p.is_calibrated
      ? `Estás en ${p.band}.`
      : 'Todavía te estoy conociendo.'
    : 'Tu progreso';

  const subtitle = p
    ? p.is_calibrated
      ? `Llevas ${p.stable_sessions_at_band} ${
          p.stable_sessions_at_band === 1 ? 'sesión' : 'sesiones'
        } en este nivel, y ${p.sessions_completed} en total.`
      : 'Después de unas cuantas conversaciones sabré en qué nivel te sientes cómoda.'
    : undefined;

  return (
    <AppShell current="progreso">
      <section style={page}>
        <PageTitle title={title} subtitle={subtitle} />

        {profile.error && (
          <div style={{ marginBottom: 32 }}>
            <ErrorNotice>
              No pude cargar tu progreso. Vuelve a intentarlo en un momento.
            </ErrorNotice>
          </div>
        )}

        {p && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 24,
              marginBottom: 24,
            }}
          >
            <Panel>
              <Eyebrow>Tu español</Eyebrow>
              {/* Both signals are computed over a trailing 20-turn window, so
                  with no turns the API returns a neutral 0.5 for each. Drawing
                  those as half-full meters would invent progress the learner
                  has not made — say nothing instead. */}
              {p.sessions_completed === 0 ? (
                <Empty>
                  Cuando hablemos un poco, aquí verás cómo va tu español.
                </Empty>
              ) : (
                <div style={{ display: 'grid', gap: 22 }}>
                  <Meter
                    value={100 - toPercent(p.l1_reliance)}
                    hint={
                      p.l1_reliance <= 0.15
                        ? 'Casi todo lo dices en español.'
                        : 'Cada vez recurres menos al inglés.'
                    }
                  />
                  <Meter
                    value={toPercent(p.speech_fluency)}
                    hint={
                      p.speech_fluency >= 0.7
                        ? 'Hablas con soltura, en frases completas.'
                        : 'Tu fluidez va creciendo sesión a sesión.'
                    }
                  />
                </div>
              )}
            </Panel>

            <Panel>
              <Eyebrow>En lo que estás trabajando</Eyebrow>
              {p.top_errors.length === 0 ? (
                <Empty>
                  Todavía no he visto patrones — hablemos un poco más.
                </Empty>
              ) : (
                <div style={{ display: 'grid', gap: 10 }}>
                  {p.top_errors.slice(0, 5).map((e) => (
                    <div
                      key={e.category}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'baseline',
                        gap: 16,
                      }}
                    >
                      <span style={{ fontSize: 14, color: 'var(--ink)' }}>
                        {errorLabel(e.category)}
                      </span>
                      <span
                        style={{
                          fontFamily: 'var(--mono)',
                          fontSize: 12,
                          color: 'var(--muted)',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {e.count} {e.count === 1 ? 'vez' : 'veces'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>
        )}

        {p && (
          <div style={{ marginBottom: 24 }}>
            <Panel>
              <Eyebrow>Palabras que ya produces</Eyebrow>
              {p.top_vocab.length === 0 ? (
                <Empty>Aún no hay vocabulario registrado.</Empty>
              ) : (
                <div
                  style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}
                >
                  {vocabByProduction(p.top_vocab).map((v) => (
                    <span
                      key={v.lemma}
                      style={{
                        padding: '7px 13px',
                        borderRadius: 100,
                        border: '1px solid var(--line)',
                        background: 'var(--cream-2)',
                        fontSize: 13,
                        color: 'var(--ink)',
                      }}
                    >
                      {v.lemma}
                      <span
                        style={{
                          fontFamily: 'var(--mono)',
                          fontSize: 11,
                          color: 'var(--muted)',
                          marginLeft: 8,
                        }}
                      >
                        ×{v.production_count}
                      </span>
                    </span>
                  ))}
                </div>
              )}
            </Panel>
          </div>
        )}

        <Panel>
          <Eyebrow>Tu recorrido</Eyebrow>
          {bands.error ? (
            <ErrorNotice>No pude cargar tu recorrido de niveles.</ErrorNotice>
          ) : bands.data && bands.data.band_history.length === 0 ? (
            <Empty>
              Tu nivel se fijará después de la primera conversación.
            </Empty>
          ) : (
            <div style={{ display: 'grid', gap: 16 }}>
              {(bands.data?.band_history ?? []).map((change) => (
                <div
                  key={change.id}
                  style={{ display: 'flex', gap: 14, alignItems: 'baseline' }}
                >
                  <span
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: '50%',
                      background: 'var(--clay)',
                      flexShrink: 0,
                    }}
                  />
                  <span style={{ fontSize: 14, color: 'var(--ink)', flex: 1 }}>
                    {bandChangeLine(change)}
                  </span>
                  <span
                    style={{
                      fontFamily: 'var(--mono)',
                      fontSize: 11,
                      color: 'var(--muted)',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {formatRelative(change.changed_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </section>
    </AppShell>
  );
}
