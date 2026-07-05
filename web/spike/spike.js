// Browser voice-client spike for /ws/session.
//
// Mirrors scripts/voice_client.py: 16 kHz mono 16-bit PCM, raw binary frames
// in both directions, no framing. Chromium-only — see plan notes.

const DEFAULT_URL = 'ws://localhost:8000/ws/session';
const DEFAULT_HEALTH_URL = 'http://localhost:8000/health';
const TARGET_RATE = 16000;

const els = {
  urlInput: document.getElementById('wsUrl'),
  healthUrlInput: document.getElementById('healthUrl'),
  button: document.getElementById('startStop'),
  status: document.getElementById('status'),
  micMeter: document.getElementById('micMeter'),
  playbackMeter: document.getElementById('playbackMeter'),
  log: document.getElementById('log'),
};

let state = null;
let rafHandle = null;
let healthTimer = null;

function log(msg) {
  const t = new Date().toISOString().slice(11, 23);
  const line = document.createElement('div');
  line.textContent = `[${t}] ${msg}`;
  els.log.appendChild(line);
  els.log.scrollTop = els.log.scrollHeight;
  console.log(msg);
}

function setStatus(text, cls = '') {
  els.status.textContent = text;
  els.status.className = cls;
}

// ---------- health polling ----------

async function pollHealth() {
  // Informational only — if the spike page is served from a different origin
  // than the API (it usually is), this fetch fails CORS. We don't gate the
  // button on it; the WS itself closes with 1013 when the server is warming
  // up, and we surface that in the log.
  const url = els.healthUrlInput.value.trim() || DEFAULT_HEALTH_URL;
  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (res.ok) {
      setStatus(`health: 200 ok · ready`, 'ok');
    } else if (res.status === 503) {
      setStatus(`health: 503 warming up · María está despertando…`, 'warming');
    } else {
      setStatus(`health: ${res.status} (unexpected)`, 'warn');
    }
  } catch (err) {
    setStatus(`health: unreachable via CORS (ok — relying on WS 1013 instead)`, 'warn');
  }
  els.button.disabled = false;
}

function startHealthPolling() {
  pollHealth();
  healthTimer = setInterval(pollHealth, 2000);
}

function stopHealthPolling() {
  if (healthTimer) clearInterval(healthTimer);
  healthTimer = null;
}

// ---------- metering ----------

function rms(analyser, buf) {
  analyser.getFloatTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
  return Math.sqrt(sum / buf.length);
}

function tickMeters() {
  if (!state) return;
  const micR = rms(state.micAnalyser, state.micBuf);
  const pbR = rms(state.playbackAnalyser, state.playbackBuf);
  // Normalize 0..1 into a generous visual range.
  const micPct = Math.min(100, micR * 300);
  const pbPct = Math.min(100, pbR * 300);
  els.micMeter.style.width = `${micPct}%`;
  els.playbackMeter.style.width = `${pbPct}%`;
  rafHandle = requestAnimationFrame(tickMeters);
}

// ---------- session lifecycle ----------

async function startSession() {
  const wsUrl = els.urlInput.value.trim() || DEFAULT_URL;

  log('requesting microphone…');
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: TARGET_RATE,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: false,
      },
    });
  } catch (err) {
    log(`mic permission denied or unavailable: ${err.message}`);
    return;
  }

  const audioContext = new AudioContext({ sampleRate: TARGET_RATE });
  log(`AudioContext: requested ${TARGET_RATE} Hz, actual ${audioContext.sampleRate} Hz`);
  if (audioContext.sampleRate !== TARGET_RATE) {
    log(`NOTE: context rate differs — worklet will resample on the way in.`);
  }

  await audioContext.audioWorklet.addModule('pcm-worklet.js');

  // --- capture chain ---
  const source = audioContext.createMediaStreamSource(stream);
  const micAnalyser = audioContext.createAnalyser();
  micAnalyser.fftSize = 512;
  source.connect(micAnalyser);

  const captureNode = new AudioWorkletNode(audioContext, 'pcm-capture', {
    numberOfInputs: 1,
    numberOfOutputs: 1,
    outputChannelCount: [1],
  });
  source.connect(captureNode);
  // Connect worklet to destination through a muted gain so process() keeps running.
  const muteGain = audioContext.createGain();
  muteGain.gain.value = 0;
  captureNode.connect(muteGain);
  muteGain.connect(audioContext.destination);

  // --- playback chain ---
  const playbackGain = audioContext.createGain();
  playbackGain.gain.value = 1;
  const playbackAnalyser = audioContext.createAnalyser();
  playbackAnalyser.fftSize = 512;
  playbackGain.connect(playbackAnalyser);
  playbackAnalyser.connect(audioContext.destination);

  // --- websocket ---
  log(`connecting to ${wsUrl}…`);
  const ws = new WebSocket(wsUrl);
  ws.binaryType = 'arraybuffer';

  const wsOpenedAt = { t: 0 };
  const firstFrameSeen = { flag: false };
  let nextPlaybackTime = 0;
  let sentBytes = 0;
  let recvBytes = 0;

  ws.addEventListener('open', () => {
    wsOpenedAt.t = performance.now();
    log(`WS open`);
  });

  ws.addEventListener('message', (ev) => {
    if (!(ev.data instanceof ArrayBuffer)) {
      log(`WS recv: non-binary message ignored (${typeof ev.data})`);
      return;
    }
    if (!firstFrameSeen.flag) {
      firstFrameSeen.flag = true;
      const ms = Math.round(performance.now() - wsOpenedAt.t);
      log(`first audio frame received, ${ms} ms after WS open (${ev.data.byteLength} bytes)`);
    }
    recvBytes += ev.data.byteLength;

    const int16 = new Int16Array(ev.data);
    const f32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 0x8000;

    const buffer = audioContext.createBuffer(1, f32.length, TARGET_RATE);
    buffer.copyToChannel(f32, 0);
    const src = audioContext.createBufferSource();
    src.buffer = buffer;
    src.connect(playbackGain);
    const startAt = Math.max(audioContext.currentTime, nextPlaybackTime);
    src.start(startAt);
    nextPlaybackTime = startAt + buffer.duration;
  });

  ws.addEventListener('close', (ev) => {
    log(`WS close · code=${ev.code} reason=${ev.reason || '(none)'}`);
    if (ev.code === 1013) {
      log(`server rejected with 1013 (warming up) — wait for /health to return 200 and retry.`);
    }
    if (state) stopSession('ws closed');
  });

  ws.addEventListener('error', (err) => {
    log(`WS error event (see console)`);
    console.error(err);
  });

  // Capture worklet → WS send.
  captureNode.port.onmessage = (msg) => {
    const buf = msg.data;
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(buf);
      sentBytes += buf.byteLength;
    }
  };

  state = {
    stream,
    audioContext,
    ws,
    micAnalyser,
    playbackAnalyser,
    micBuf: new Float32Array(micAnalyser.fftSize),
    playbackBuf: new Float32Array(playbackAnalyser.fftSize),
    stats: { sentBytes, recvBytes },
    started: performance.now(),
  };

  // Reuse captureNode reference so we can update stats readout later if needed.
  state.captureNode = captureNode;
  state.muteGain = muteGain;

  els.button.textContent = 'Stop';
  tickMeters();
}

async function stopSession(reason = 'user') {
  if (!state) return;
  const started = state.started;
  log(`stopping (reason: ${reason})…`);
  const { stream, audioContext, ws } = state;

  if (rafHandle) cancelAnimationFrame(rafHandle);
  rafHandle = null;

  try { state.captureNode.port.onmessage = null; } catch {}
  try { state.captureNode.disconnect(); } catch {}
  try { state.muteGain.disconnect(); } catch {}

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.close(1000, 'client stop');
  }

  for (const track of stream.getTracks()) track.stop();

  try { await audioContext.close(); } catch (err) {
    log(`audioContext.close error: ${err.message}`);
  }

  els.micMeter.style.width = '0%';
  els.playbackMeter.style.width = '0%';
  els.button.textContent = 'Start session';

  const elapsed = Math.round(performance.now() - started);
  log(`stopped · elapsed=${elapsed} ms`);
  state = null;
}

// ---------- wire up UI ----------

els.urlInput.value = DEFAULT_URL;
els.healthUrlInput.value = DEFAULT_HEALTH_URL;

els.button.addEventListener('click', async () => {
  if (state) {
    await stopSession('user');
  } else {
    els.button.disabled = true;
    try {
      await startSession();
    } catch (err) {
      log(`startSession failed: ${err.message}`);
      console.error(err);
    } finally {
      els.button.disabled = false;
    }
  }
});

startHealthPolling();
window.addEventListener('beforeunload', () => {
  stopHealthPolling();
  if (state) stopSession('unload');
});
