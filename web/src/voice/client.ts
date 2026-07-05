// Browser voice client for /ws/session. Port of web/spike/spike.js into an
// imperative class whose lifecycle survives React re-renders.
//
// Wire protocol: 16 kHz mono 16-bit PCM, raw binary frames both directions.
// Must be paired with hable_ya.pipeline.serializer.RawPCMSerializer server-side.

const TARGET_RATE = 16000;
const WORKLET_URL = '/pcm-worklet.js';

export type VoiceStatus = 'idle' | 'connecting' | 'connected' | 'closed' | 'error';

export type VoiceClientOpts = {
  wsUrl?: string;
  onStatus?: (status: VoiceStatus) => void;
  onClose?: (ev: CloseEvent) => void;
  onError?: (err: unknown) => void;
  onLog?: (msg: string) => void;
};

function defaultWsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/ws/session`;
}

export class VoiceClient {
  private readonly wsUrl: string;
  private readonly onStatus?: (s: VoiceStatus) => void;
  private readonly onClose?: (ev: CloseEvent) => void;
  private readonly onError?: (err: unknown) => void;
  private readonly onLog?: (msg: string) => void;

  private stream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private captureNode: AudioWorkletNode | null = null;
  private muteGain: GainNode | null = null;
  private playbackGain: GainNode | null = null;
  private ws: WebSocket | null = null;

  private _micAnalyser: AnalyserNode | null = null;
  private _playbackAnalyser: AnalyserNode | null = null;

  private muted = false;
  private disposed = false;
  private nextPlaybackTime = 0;
  private playbackScratch: Float32Array<ArrayBuffer> = new Float32Array(
    new ArrayBuffer(0),
  );

  constructor(opts: VoiceClientOpts = {}) {
    this.wsUrl = opts.wsUrl ?? defaultWsUrl();
    this.onStatus = opts.onStatus;
    this.onClose = opts.onClose;
    this.onError = opts.onError;
    this.onLog = opts.onLog;
  }

  get micAnalyser(): AnalyserNode | null {
    return this._micAnalyser;
  }

  get playbackAnalyser(): AnalyserNode | null {
    return this._playbackAnalyser;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
  }

  async connect(): Promise<void> {
    if (this.disposed) throw new Error('VoiceClient already disposed');
    this.onStatus?.('connecting');
    this.log('requesting microphone…');

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: TARGET_RATE,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: false,
      },
    });
    this.stream = stream;

    const audioContext = new AudioContext({ sampleRate: TARGET_RATE });
    this.audioContext = audioContext;
    this.log(
      `AudioContext: requested ${TARGET_RATE} Hz, actual ${audioContext.sampleRate} Hz`,
    );

    await audioContext.audioWorklet.addModule(WORKLET_URL);

    // Capture chain
    const source = audioContext.createMediaStreamSource(stream);
    const micAnalyser = audioContext.createAnalyser();
    micAnalyser.fftSize = 512;
    source.connect(micAnalyser);
    this._micAnalyser = micAnalyser;

    const captureNode = new AudioWorkletNode(audioContext, 'pcm-capture', {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
    });
    source.connect(captureNode);
    const muteGain = audioContext.createGain();
    muteGain.gain.value = 0;
    captureNode.connect(muteGain);
    muteGain.connect(audioContext.destination);
    this.captureNode = captureNode;
    this.muteGain = muteGain;

    // Playback chain
    const playbackGain = audioContext.createGain();
    playbackGain.gain.value = 1;
    const playbackAnalyser = audioContext.createAnalyser();
    playbackAnalyser.fftSize = 512;
    playbackGain.connect(playbackAnalyser);
    playbackAnalyser.connect(audioContext.destination);
    this.playbackGain = playbackGain;
    this._playbackAnalyser = playbackAnalyser;

    // WebSocket
    this.log(`connecting to ${this.wsUrl}…`);
    const ws = new WebSocket(this.wsUrl);
    ws.binaryType = 'arraybuffer';
    this.ws = ws;

    ws.addEventListener('open', () => {
      this.log('WS open');
      this.onStatus?.('connected');
    });

    ws.addEventListener('message', (ev) => {
      if (!(ev.data instanceof ArrayBuffer)) return;
      this.schedulePlayback(ev.data);
    });

    ws.addEventListener('close', (ev) => {
      this.log(`WS close · code=${ev.code} reason=${ev.reason || '(none)'}`);
      this.onStatus?.('closed');
      this.onClose?.(ev);
    });

    ws.addEventListener('error', (err) => {
      this.onStatus?.('error');
      this.onError?.(err);
    });

    captureNode.port.onmessage = (msg: MessageEvent<ArrayBuffer>) => {
      if (this.muted) return;
      const buf = msg.data;
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(buf);
      }
    };
  }

  private schedulePlayback(data: ArrayBuffer): void {
    const audioContext = this.audioContext;
    const playbackGain = this.playbackGain;
    if (!audioContext || !playbackGain) return;

    const int16 = new Int16Array(data);
    if (this.playbackScratch.length < int16.length) {
      this.playbackScratch = new Float32Array(new ArrayBuffer(int16.length * 4));
    }
    const f32 = this.playbackScratch;
    for (let i = 0; i < int16.length; i++) {
      const v = int16[i] ?? 0;
      f32[i] = v / 0x8000;
    }

    const buffer = audioContext.createBuffer(1, int16.length, TARGET_RATE);
    buffer.copyToChannel(
      f32.length === int16.length ? f32 : f32.subarray(0, int16.length),
      0,
    );
    const src = audioContext.createBufferSource();
    src.buffer = buffer;
    src.connect(playbackGain);
    const startAt = Math.max(audioContext.currentTime, this.nextPlaybackTime);
    src.start(startAt);
    this.nextPlaybackTime = startAt + buffer.duration;
  }

  async disconnect(reason = 'client stop'): Promise<void> {
    if (this.disposed) return;
    this.disposed = true;
    this.log(`disconnect (${reason})`);

    try {
      if (this.captureNode) this.captureNode.port.onmessage = null;
    } catch {}
    try {
      this.captureNode?.disconnect();
    } catch {}
    try {
      this.muteGain?.disconnect();
    } catch {}
    try {
      this.playbackGain?.disconnect();
    } catch {}

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.close(1000, reason);
      } catch {}
    }

    if (this.stream) {
      for (const track of this.stream.getTracks()) {
        try {
          track.stop();
        } catch {}
      }
    }

    if (this.audioContext) {
      try {
        await this.audioContext.close();
      } catch {}
    }

    this._micAnalyser = null;
    this._playbackAnalyser = null;
  }

  private log(msg: string): void {
    this.onLog?.(msg);
  }
}
