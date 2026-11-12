(function () {
  'use strict';
  /* srv-audio — 질문 소리 틀기(speaker) · 마이크 녹음(startRecorder)
     운영 index.html v0.54 에서 그대로 옮겼다. 고치지 않았다. */
  const log = window.Srv.log;
  const SILENCE = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=';
  const speaker = (function () {
    let el = null, unlocked = false, settle = null;
    // 흘려 읽기용 (src/speaker.ts 의 playStream 을 옮긴 것). <audio> 와 따로 잠금을 풀어야
    // 한다 — 사파리는 AudioContext 를 사용자 동작 안에서 resume 해야 소리를 낸다.
    // 하나를 만들어 끝까지 돌려쓴다.
    let ctx = null, streamStop = null;
    function audioCtx() {
      if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
      return ctx;
    }
    // 1표본짜리 무음 버퍼를 한 번 틀어 두는 것이 iOS 에서 확실한 방법이다.
    async function unlockCtx() {
      try {
        const c = audioCtx();
        if (c.state !== 'running') await c.resume();
        const src = c.createBufferSource();
        src.buffer = c.createBuffer(1, 1, 22050);
        src.connect(c.destination);
        src.start(0);
      } catch (e) { log('소리', 'AudioContext 잠금 해제 실패 · ' + e); }
    }
    function element() {
      if (!el) {
        el = new Audio();
        el.preload = 'auto';
        el.autoplay = false;
        el.setAttribute('playsinline', '');
      }
      return el;
    }
    return {
      isUnlocked: () => unlocked,
      // 반드시 사용자 동작(클릭) 안에서 부른다. 브라우저 자동재생 차단을 푼다.
      async unlock() {
        // 흘려 읽기 쪽은 매번 확인한다. 화면을 덮었다 열면 사파리가 다시 재운다.
        if (!ctx || ctx.state !== 'running') void unlockCtx();
        if (unlocked) return true;
        const a = element();
        if (!a.paused) return unlocked;
        try {
          a.src = SILENCE; a.muted = false; a.volume = 1;
          await a.play(); a.pause();
          unlocked = true; log('소리', '잠금 해제');
        } catch (e) { log('소리', '잠금 해제 실패 · ' + e); }
        return unlocked;
      },
      play(blob) {
        const a = element();
        if (settle) { settle(false); settle = null; }
        const url = URL.createObjectURL(blob);
        return new Promise((resolve) => {
          const finish = (finished) => {
            a.onended = a.onerror = null;
            URL.revokeObjectURL(url);
            settle = null;
            resolve({ finished });
          };
          settle = finish;
          a.onended = () => finish(true);
          a.onerror = () => finish(false);
          a.src = url;
          a.play().catch((e) => { log('낭독', '재생 거부 · ' + e); finish(false); });
        });
      },
      /**
       * 흘려 오는 낭독을 받는 대로 튼다. 약속은 play() 와 같다 — **마지막 조각까지 다 틀어야**
       * 풀린다. 받기는 재생보다 먼저 끝나므로, 그 시각에 tts-done 을 올리면 아직 말이 남았는데
       * 수음이 열려 스피커 소리가 첫마디로 들어간다.
       * 조각 사이가 비면(언더런) 그만큼 늦춰 이어 틀고, 몇 번 났는지 로그에 남긴다.
       */
      async playStream(res) {
        if (settle) { settle(false); settle = null; }
        if (streamStop) streamStop();
        const c = audioCtx();
        if (c.state !== 'running') { try { await c.resume(); } catch (_) { /* 아래에서 말한다 */ } }
        if (c.state !== 'running') throw new Error('재생 거부 · AudioContext ' + c.state);

        const m = /rate=(\d+)/.exec(res.headers.get('content-type') || '');
        const rate = Number(m ? m[1] : 24000);
        const reader = res.body.getReader();
        const sources = [];
        const LEAD = 0.06;            // 첫 조각 앞 여유(초). 스케줄이 지금보다 앞서면 앞이 잘린다
        const t0 = performance.now();
        let next = 0, gaps = 0, stopped = false;
        let odd = null;               // 조각 경계가 표본 한가운데 걸리면 남는 1바이트
        const stop = () => {
          if (stopped) return;
          stopped = true;
          reader.cancel().catch(() => {});
          for (const s of sources) { try { s.stop(); } catch (_) { /* 아직 시작 전 */ } }
        };
        streamStop = stop;

        try {
          for (;;) {
            const { value, done } = await reader.read();
            if (done || stopped) break;
            let bytes = value;
            if (odd) {
              const j = new Uint8Array(odd.length + bytes.length);
              j.set(odd); j.set(bytes, odd.length);
              bytes = j; odd = null;
            }
            if (bytes.length % 2) { odd = bytes.slice(-1); bytes = bytes.subarray(0, bytes.length - 1); }
            if (!bytes.length) continue;

            const n = bytes.length / 2;
            const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
            const buf = c.createBuffer(1, n, rate);
            const ch = buf.getChannelData(0);
            for (let i = 0; i < n; i++) ch[i] = view.getInt16(i * 2, true) / 32768;

            const src = c.createBufferSource();
            src.buffer = buf;
            src.connect(c.destination);
            const now = c.currentTime;
            if (!next) {
              next = now + LEAD;
              log('낭독', `첫 소리 · 받기 시작 후 ${(performance.now() - t0).toFixed(0)}ms`
                + ` · ${rate}Hz · ${res.headers.get('x-speech-source') || '?'}`);
            } else if (next < now + 0.005) {
              gaps++;
              next = now + 0.02;
            }
            src.start(next);
            next += buf.duration;
            sources.push(src);
          }
        } catch (e) {
          if (!stopped) { stop(); streamStop = null; throw new Error('받다 끊김 · ' + (e.message || e)); }
        }

        // 받기는 끝났다. 마지막 조각이 다 울릴 때까지 기다린다.
        const last = sources[sources.length - 1];
        if (last && !stopped) {
          await new Promise((r) => {
            last.onended = () => r();
            // 끊기면(stop) onended 가 바로 온다. 혹시 안 와도 매달리지 않게 시계로 한 번 더.
            setTimeout(r, Math.max(0, (next - c.currentTime) * 1000) + 500);
          });
        }
        if (streamStop === stop) streamStop = null;
        log('낭독', `흘려 읽기 · ${sources.length}조각${gaps ? ` · 끊김 ${gaps}번` : ''}`);
        return { finished: !stopped };
      },
      stop() {
        const a = element(); try { a.pause(); } catch (_) {}
        if (settle) { settle(false); settle = null; }
        if (streamStop) streamStop();
      },
    };
  })();

  /* ═══════════════════════════════════════════════════════════════
     recorder — 소리가 있는 구간만 16kHz PCM 으로 올린다
     (src/recorder.ts 를 그대로 옮긴 것. 상수 이름도 같다)

     ※ 브라우저 기본 녹음(MediaRecorder)을 쓰지 않는 이유:
       잘라낸 webm 조각은 이어 붙지 않아 첫 조각만 남는다.
       머리 없는 PCM 은 이어 붙이는 것이 곧 이어 붙이는 것이다.
     ═══════════════════════════════════════════════════════════════ */
  const RATE = 16000;
  const MIME = `audio/pcm;rate=${RATE}`;
  const FRAME = 4096;
  const PREROLL_MS = 300;
  const CLOSE_MS = 600;
  const FLUSH_MS = 1000;
  // 말머리만은 빨리 올린다 (recorder.ts FIRST_FLUSH_MS 와 같다). 서버는 무음 3초로 말씀을
  // 확정한 뒤에도 질문이 나가기 전까지는 이어진 말씀을 받아 확정을 물린다(이어 듣기).
  // 그 창이 T2(3초)뿐이라, 첫 조각을 1초 뒤에 올리면 다시 시작하신 말이 창을 넘긴다.
  const FIRST_FLUSH_MS = 300;
  const FLOOR_MIN = 0.004;
  const OPEN_MULT = 3.5;
  const CLOSE_MULT = 2.0;
  const OPEN_MULT_MIN = 2.0;
  const OPEN_MULT_MAX = 6.0;
  const PEAK_RATIO_MIN = 3.0;
  const PEAK_RISE = 0.2;
  const PEAK_FALL = 0.997;

  class Resampler {
    constructor(from, to) { this.from = from; this.to = to; this.cursor = 0; this.prev = 0; this.started = false; }
    push(input) {
      const ratio = this.from / this.to, n = input.length;
      if (n === 0) return new Float32Array(0);
      const out = [];
      let c = this.started ? this.cursor : 0;
      while (c < n - 1) {
        const i = Math.floor(c);
        const a = i < 0 ? this.prev : input[i];
        const b = input[i + 1];
        out.push(a + (b - a) * (c - i));
        c += ratio;
      }
      this.prev = input[n - 1];
      this.started = true;
      this.cursor = c - n;
      return Float32Array.from(out);
    }
  }

  function toPcm16(frames) {
    const total = frames.reduce((s, f) => s + f.length, 0);
    const out = new Int16Array(total);
    let o = 0;
    for (const f of frames) {
      for (let i = 0; i < f.length; i++) {
        const v = Math.max(-1, Math.min(1, f[i]));
        out[o++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      }
    }
    return out.buffer;
  }

  async function startRecorder(opts) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('이 주소에서는 마이크를 쓸 수 없습니다 (https 또는 localhost 가 필요합니다)');
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    await ctx.resume();
    const src = ctx.createMediaStreamSource(stream);
    const node = ctx.createScriptProcessor(FRAME, 1, 1);
    const mute = ctx.createGain();
    mute.gain.value = 0;
    const rs = new Resampler(ctx.sampleRate, RATE);

    let floor = 0.02, peak = 0, voiced = false;
    let belowMs = 0, sinceFlush = 0;
    let headSent = false;       // 이 구간의 말머리를 올렸나 (FIRST_FLUSH_MS)
    let pending = [], preroll = [], prerollMs = 0;
    let stopped = false, active = false;

    const gates = () => {
      const sep = floor > 0 ? peak / floor : 0;
      const auto = sep >= PEAK_RATIO_MIN;
      const mult = auto ? Math.min(OPEN_MULT_MAX, Math.max(OPEN_MULT_MIN, Math.sqrt(sep))) : OPEN_MULT;
      return {
        auto,
        open: Math.max(floor * mult, FLOOR_MIN),
        close: Math.max(floor * mult * (CLOSE_MULT / OPEN_MULT), FLOOR_MIN * 0.6),
      };
    };

    const flush = () => {
      if (!pending.length) return;
      const buf = toPcm16(pending);
      pending = []; sinceFlush = 0;
      if (buf.byteLength) opts.onChunk(buf);
    };

    node.onaudioprocess = (e) => {
      if (stopped) return;
      e.outputBuffer.getChannelData(0).fill(0);
      const input = e.inputBuffer.getChannelData(0);
      const durMs = (input.length / ctx.sampleRate) * 1000;

      let sum = 0;
      for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
      const rms = Math.sqrt(sum / input.length);

      if (!active) {
        rs.push(input);
        const g = gates();
        if (opts.onLevel) opts.onLevel({ rms, voiced: false, floor, peak, open: g.open, auto: g.auto });
        return;
      }

      peak = rms > peak ? peak * (1 - PEAK_RISE) + rms * PEAK_RISE : peak * PEAK_FALL;
      const g = gates();
      const res = rs.push(input);

      if (!voiced) {
        floor = rms < floor ? floor * 0.85 + rms * 0.15 : floor * 0.99 + rms * 0.01;
        preroll.push(res);
        prerollMs += durMs;
        while (prerollMs > PREROLL_MS && preroll.length > 1) {
          prerollMs -= (preroll.shift().length / RATE) * 1000;
        }
        if (rms > g.open) {
          voiced = true; belowMs = 0; sinceFlush = 0; headSent = false;
          pending = preroll; preroll = []; prerollMs = 0;
        }
      } else {
        pending.push(res);
        sinceFlush += durMs;
        belowMs = rms < g.close ? belowMs + durMs : 0;
        if (belowMs >= CLOSE_MS) { voiced = false; flush(); }
        else if (sinceFlush >= (headSent ? FLUSH_MS : FIRST_FLUSH_MS)) { headSent = true; flush(); }
      }
      if (opts.onLevel) opts.onLevel({ rms, voiced, floor, peak, open: g.open, auto: g.auto });
    };

    src.connect(node); node.connect(mute); mute.connect(ctx.destination);

    return {
      // 듣는 동안에만 켠다. 낭독 중에 켜 두면 스피커 소리가 마이크로 되돌아와
      // T1 이 영영 리셋된다.
      setActive(on) {
        if (!on) { voiced = false; pending = []; preroll = []; prerollMs = 0; belowMs = 0; sinceFlush = 0; }
        active = on;
      },
      // 모아 둔 소리를 지금 올린다. 「녹음 정지」 직전에 부른다 — setActive(false) 는
      // 모아 둔 것을 버리므로, 그 전에 부르지 않으면 말 끝의 최대 1초(FLUSH_MS)가 사라진다.
      flushNow() { if (active) flush(); },
      stop() {
        if (stopped) return;
        stopped = true;
        flush();
        node.onaudioprocess = null;
        try { src.disconnect(); node.disconnect(); mute.disconnect(); } catch (_) {}
        stream.getTracks().forEach(t => t.stop());
        ctx.close();
      },
    };
  }
  window.SrvAudio = { speaker, startRecorder, MIME, RATE };
}());
