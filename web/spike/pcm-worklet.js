// Capture-side AudioWorkletProcessor.
//
// Converts Float32 mic samples to 16-bit signed PCM at 16 kHz and posts
// 20 ms chunks (320 samples / 640 bytes) back to the main thread, matching
// the wire format that scripts/voice_client.py sends to /ws/session.
//
// If the AudioContext's actual sample rate does not match TARGET_RATE, we
// do a minimal linear-interpolation resample on the way in. Chromium on
// Linux typically honors AudioContext({ sampleRate: 16000 }), so the fast
// path usually wins.

const TARGET_RATE = 16000;
const CHUNK_SAMPLES = 320; // 20 ms at 16 kHz

class PCMCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Int16Array(CHUNK_SAMPLES);
    this.filled = 0;
    this.resamplePos = 0; // fractional read pointer (input samples)
    this.lastSample = 0;  // last input sample (for interpolation across quanta)
    this.ratio = sampleRate / TARGET_RATE;
  }

  pushSample(s) {
    if (s > 1) s = 1;
    else if (s < -1) s = -1;
    this.buf[this.filled++] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff);
    if (this.filled === CHUNK_SAMPLES) {
      const out = new Int16Array(this.buf); // copy
      this.port.postMessage(out.buffer, [out.buffer]);
      this.filled = 0;
    }
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0] || input[0].length === 0) {
      return true;
    }
    const ch = input[0];

    if (Math.abs(this.ratio - 1) < 1e-6) {
      // Fast path: context is already at 16 kHz.
      for (let i = 0; i < ch.length; i++) this.pushSample(ch[i]);
      return true;
    }

    // Resample by linear interpolation to TARGET_RATE.
    // resamplePos is measured in input-sample units; advance by ratio each
    // target sample. When it crosses ch.length, stash the fractional offset
    // for the next quantum.
    let pos = this.resamplePos;
    while (pos < ch.length) {
      const idx = Math.floor(pos);
      const frac = pos - idx;
      const a = idx === 0 ? this.lastSample : ch[idx - 1];
      const b = ch[idx];
      this.pushSample(a + (b - a) * frac);
      pos += this.ratio;
    }
    this.lastSample = ch[ch.length - 1];
    this.resamplePos = pos - ch.length;
    return true;
  }
}

registerProcessor('pcm-capture', PCMCaptureProcessor);
