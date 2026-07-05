import { useEffect, useRef, useState } from 'react';
import type { VoiceClient } from './client';
import type { Speaker } from './types';

// TODO: tune against real turn-taking.
const MIC_THRESHOLD = 0.03;
const PB_THRESHOLD = 0.02;

const SMOOTHING = 0.12;
const AMP_STATE_EPSILON = 0.01;

function rms(analyser: AnalyserNode, buf: Float32Array<ArrayBuffer>): number {
  analyser.getFloatTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = buf[i] ?? 0;
    sum += v * v;
  }
  return Math.sqrt(sum / buf.length);
}

function makeBuf(size: number): Float32Array<ArrayBuffer> {
  return new Float32Array(new ArrayBuffer(size * 4));
}

export function useAmplitude(
  client: VoiceClient | null,
): { amp: number; speaker: Speaker } {
  const [state, setState] = useState<{ amp: number; speaker: Speaker }>({
    amp: 0.3,
    speaker: 'idle',
  });
  const ampRef = useRef(0.3);
  const tRef = useRef(0);
  const micBufRef = useRef<Float32Array<ArrayBuffer> | null>(null);
  const pbBufRef = useRef<Float32Array<ArrayBuffer> | null>(null);
  const lastPushedRef = useRef<{ amp: number; speaker: Speaker }>({
    amp: 0.3,
    speaker: 'idle',
  });

  useEffect(() => {
    let raf = 0;
    let last = performance.now();

    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      tRef.current += dt;
      const t = tRef.current;

      let speaker: Speaker = 'idle';
      let target = 0.5 + 0.1 * Math.sin((t * 0.5 * Math.PI * 2) / 2);

      const mic = client?.micAnalyser ?? null;
      const pb = client?.playbackAnalyser ?? null;

      if (mic && pb) {
        if (!micBufRef.current || micBufRef.current.length !== mic.fftSize) {
          micBufRef.current = makeBuf(mic.fftSize);
        }
        if (!pbBufRef.current || pbBufRef.current.length !== pb.fftSize) {
          pbBufRef.current = makeBuf(pb.fftSize);
        }
        const micR = rms(mic, micBufRef.current);
        const pbR = rms(pb, pbBufRef.current);

        if (pbR > PB_THRESHOLD) {
          speaker = 'agent';
          const v = 0.55 + 0.25 * Math.sin(t * 4.2) + 0.1 * Math.sin(t * 8.1);
          target = Math.max(0.4, Math.min(1, v * (0.7 + pbR * 6)));
        } else if (micR > MIC_THRESHOLD) {
          speaker = 'user';
          const v =
            0.5 +
            0.35 * Math.sin(t * 6) * Math.sin(t * 2.3) +
            0.15 * Math.sin(t * 11);
          target = Math.max(0.35, Math.min(1, Math.abs(v) + 0.15));
        }
      }

      ampRef.current = ampRef.current + (target - ampRef.current) * SMOOTHING;

      const prev = lastPushedRef.current;
      if (
        speaker !== prev.speaker ||
        Math.abs(ampRef.current - prev.amp) > AMP_STATE_EPSILON
      ) {
        const next = { amp: ampRef.current, speaker };
        lastPushedRef.current = next;
        setState(next);
      }

      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [client]);

  return state;
}
