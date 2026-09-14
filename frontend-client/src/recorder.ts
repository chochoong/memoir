// 마이크 — 소리가 있는 구간만 16kHz PCM 으로 올려보낸다
//
// 판정을 여기 두는 이유는 서버에 이미 T1 이 있기 때문이다. T1 은 「무음 3초」의
// 정의이고, 아무것도 보내지 않는 것이 곧 무음 신호다. 서버에서 또 판정하면 둘이
// 어긋날 때 원인을 찾을 수 없다. 그래서 **무음까지 올리면 T1 이 영원히 리셋되어
// 발화가 확정되지 않는다** — 이 파일이 틀리면 대화가 멈춘다.
//
// tools/replay.py 의 _voiced() 가 초안이었다. 다만 거기엔 없던 셋을 더했다.
//   · 잡음 바닥 추정 — 조용한 방과 시끄러운 방에서 같은 임계값은 쓸 수 없다
//   · 이력(hysteresis) — 임계값 하나면 경계에서 켜졌다 꺼졌다 하며 말을 썬다
//   · 목소리 봉우리 추정 — 아래 「문턱을 스스로 정하는 법」 참조
//
// MediaRecorder 를 쓰지 않는 이유는 app/session/audio.py 에 적어 두었다.
// 요약하면, 잘라낸 webm 조각은 이어 붙지 않고 첫 조각만 남는다.
//
// ── 문턱을 스스로 정하는 법 ──────────────────────────────────────────────
//
// 오래 문턱은 `잡음 바닥 × 3.5` 였다. 그 3.5 는 「목소리는 잡음보다 3.5배 클
// 것이다」라는 **추측**이다. 어르신이 작게 말씀하시거나 폰에서 멀리 계시면 실제
// 비율이 2배도 안 되고, 그러면 게이트가 영영 열리지 않아 말씀이 통째로 사라진다.
// 반대로 잡음이 큰 방에서는 3.5 로도 모자라 잡음이 계속 올라가고, 그러면 T1 이
// 영영 리셋되어 대화가 멈춘다. 한 숫자로 둘 다 맞출 수 없다.
//
// 그래서 잡음뿐 아니라 **목소리도 잰다.** 잴 수 있는 이유는 rms 가 게이트와
// 무관하게 매 프레임 계산되기 때문이다 — 게이트가 걷어찬 소리도 rms 흐름에는
// 남아 있다. 봉우리(peak)는 그 흐름에서 바로 뽑는다.
//
//     바닥 floor ──┐
//                  ├── 문턱 = √(floor × peak)   ← dB 로 치면 둘의 한가운데
//     봉우리 peak ─┘
//
// 배수로 고쳐 쓰면 √(peak/floor) 다. 둘이 12배 떨어져 있으면 3.46 — 예전 3.5 와
// 거의 같다. 어르신 목소리가 작아 5배뿐이면 2.24 로 알아서 내려간다.
//
// 다만 **봉우리를 믿을 수 있을 때만** 쓴다. 아무도 말하지 않는 동안은 peak 이
// floor 로 내려앉는데 그때 기하평균을 쓰면 문턱이 바닥에 붙어 잡음이 다 통과한다.
// 그래서 둘이 PEAK_RATIO_MIN 배 이상 떨어져 있을 때만 — 즉 목소리를 실제로 한 번
// 본 뒤에만 — 자동 문턱을 쓰고, 아니면 예전 OPEN_MULT 로 돌아간다. 자동 배수에도
// 위아래 울타리를 친다. 잘못 배워도 예전 값 언저리를 벗어나지 못한다.
//
// 한 가지 더. getUserMedia 의 autoGainControl 이 켜져 있어서 rms 는 물리량이
// 아니다 — 조용하면 브라우저가 알아서 키운다. 여기 숫자가 이상하게 굴면 그것부터
// 의심할 것.

const RATE = 16000
export const MIME = `audio/pcm;rate=${RATE}`

const FRAME = 4096          // ScriptProcessor 한 묶음. 48kHz 에서 85ms
const PREROLL_MS = 300      // 판정이 열리기 전 말머리. 없으면 「어」가 잘린다
const CLOSE_MS = 600        // 이만큼 조용하면 한 구간을 닫는다 (T1 3초와는 다른 층이다)
const FLUSH_MS = 1000       // 말이 길어도 1초마다 올린다 — T1 이 계속 리셋되어야 한다
const FLOOR_MIN = 0.004     // 절대 바닥. 완전한 무음실에서 바닥이 0 으로 수렴하는 것을 막는다
const OPEN_MULT = 3.5       // 봉우리를 아직 못 봤을 때 쓰는 배수 (예전 고정값)
const CLOSE_MULT = 2.0      // 이력. OPEN_MULT 와의 비(0.57)만 의미가 있다

// 자동 문턱의 울타리. 봉우리를 잘못 배워도 이 밖으로는 못 나간다.
const OPEN_MULT_MIN = 2.0
const OPEN_MULT_MAX = 6.0
// 봉우리가 바닥보다 이만큼 떨어져 있어야 「목소리를 봤다」고 친다.
// 3.0 이면 자동 배수의 하한은 √3 ≈ 1.73 이라 OPEN_MULT_MIN 이 실질 하한이 된다.
const PEAK_RATIO_MIN = 3.0
// 봉우리는 빠르게 오르고 느리게 내린다 — 바닥의 거울상이다.
// 0.2 면 ~0.4초에 따라붙어 한 음절짜리 딸깍은 못 올리고 말씀은 올린다.
// 0.997 이면 반감기 ~20초. 한동안 조용하면 봉우리를 잊고 고정 배수로 돌아간다.
const PEAK_RISE = 0.2
const PEAK_FALL = 0.997

/** 화면에 띄우는 판정 속 숫자. 자동 보정이 맞게 도는지는 이걸로만 볼 수 있다. */
export interface Level {
  rms: number
  voiced: boolean
  floor: number
  peak: number
  open: number
  /** 자동 문턱이 적용 중인가. false 면 OPEN_MULT 로 돌고 있다는 뜻. */
  auto: boolean
}

export interface RecorderOpts {
  onChunk: (pcm: ArrayBuffer) => void
  onLevel?: (l: Level) => void
}

export interface Recorder {
  stop: () => void
  /**
   * 듣는 동안에만 켠다.
   *
   * 끄면 판정을 멈추고 모아 둔 것도 버린다. **낭독 중에 이걸 안 끄면**
   * 스피커에서 나온 질문이 마이크로 되돌아와 판정이 열린 채로 남고, 수음이
   * 시작되는 순간 그 꼬리가 어르신의 첫마디인 양 올라간다.
   */
  setActive: (on: boolean) => void
}

/** 표본율 변환. 프레임 경계에서 끊기지 않도록 커서와 직전 표본을 들고 간다. */
class Resampler {
  private cursor = 0
  private prev = 0
  private started = false
  constructor(private from: number, private to: number) {}

  push(input: Float32Array): Float32Array {
    const ratio = this.from / this.to
    const n = input.length
    if (n === 0) return new Float32Array(0)
    const out: number[] = []
    let c = this.started ? this.cursor : 0
    while (c < n - 1) {
      const i = Math.floor(c)
      const a = i < 0 ? this.prev : input[i]
      const b = input[i + 1]
      out.push(a + (b - a) * (c - i))
      c += ratio
    }
    this.prev = input[n - 1]
    this.started = true
    this.cursor = c - n              // 다음 프레임의 좌표로 옮긴다 (>= -1)
    return Float32Array.from(out)
  }
}

function toPcm16(frames: Float32Array[]): ArrayBuffer {
  const total = frames.reduce((s, f) => s + f.length, 0)
  const out = new Int16Array(total)
  let o = 0
  for (const f of frames) {
    for (let i = 0; i < f.length; i++) {
      const v = Math.max(-1, Math.min(1, f[i]))
      out[o++] = v < 0 ? v * 0x8000 : v * 0x7fff
    }
  }
  return out.buffer
}

export async function startRecorder(opts: RecorderOpts): Promise<Recorder> {
  // 보안 컨텍스트가 아니면 mediaDevices 자체가 없다. 사파리는 여기서 조용히
  // undefined 라 「마이크 거부」가 아니라 「기능이 없음」으로 터진다.
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('이 주소에서는 마이크를 쓸 수 없습니다 (https 가 필요합니다)')
  }

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  })

  const ctx = new AudioContext()
  await ctx.resume()                       // iOS 는 사용자 동작 뒤에만 열린다
  const src = ctx.createMediaStreamSource(stream)

  // ScriptProcessor 는 폐기 예정이지만 iOS 사파리를 포함해 어디서나 돈다.
  // AudioWorklet 으로 옮기는 건 별도 모듈 파일이 필요해 지금은 미룬다.
  //
  // 출력 채널이 1인 이유: 크롬은 목적지에 닿지 않은 ScriptProcessor 를 돌리지
  // 않는데, 출력 0짜리는 애초에 목적지에 붙지 못한다("cannot connect a
  // ScriptProcessorNode with 0 output channels"). 그래서 채널을 하나 두고
  // 아래에서 gain 0 으로 막는다 — 마이크 소리가 스피커로 되돌아 나가면
  // 그게 다시 마이크로 들어와 T1 이 영영 리셋된다.
  const node = ctx.createScriptProcessor(FRAME, 1, 1)
  const mute = ctx.createGain()
  mute.gain.value = 0
  const rs = new Resampler(ctx.sampleRate, RATE)

  let floor = 0.02
  let peak = 0                 // 0 이면 「아직 목소리를 못 봤다」 — 고정 배수로 시작한다
  let voiced = false
  let belowMs = 0
  let sinceFlush = 0
  let pending: Float32Array[] = []
  let preroll: Float32Array[] = []
  let prerollMs = 0
  let stopped = false
  let active = false

  /**
   * 지금의 열림·닫힘 문턱. 위 「문턱을 스스로 정하는 법」이 여기 한 곳에 있다.
   *
   * 이력비(CLOSE_MULT/OPEN_MULT)는 자동이든 아니든 그대로 지킨다. 열림만 내리고
   * 닫힘을 그대로 두면 둘이 붙어 경계에서 말이 썰린다.
   */
  const gates = () => {
    const sep = floor > 0 ? peak / floor : 0
    const auto = sep >= PEAK_RATIO_MIN
    const mult = auto
      ? Math.min(OPEN_MULT_MAX, Math.max(OPEN_MULT_MIN, Math.sqrt(sep)))
      : OPEN_MULT
    return {
      auto,
      open: Math.max(floor * mult, FLOOR_MIN),
      close: Math.max(floor * mult * (CLOSE_MULT / OPEN_MULT), FLOOR_MIN * 0.6),
    }
  }

  const flush = () => {
    if (!pending.length) return
    const buf = toPcm16(pending)
    pending = []
    sinceFlush = 0
    if (buf.byteLength) opts.onChunk(buf)
  }

  node.onaudioprocess = (e: AudioProcessingEvent) => {
    if (stopped) return
    e.outputBuffer.getChannelData(0).fill(0)   // gain 0 위에 한 겹 더. 새어 나갈 길을 두지 않는다
    const input = e.inputBuffer.getChannelData(0)
    const durMs = (input.length / ctx.sampleRate) * 1000

    let sum = 0
    for (let i = 0; i < input.length; i++) sum += input[i] * input[i]
    const rms = Math.sqrt(sum / input.length)

    if (!active) {
      // 바닥도 봉우리도 여기서는 재지 않는다. 낭독이 흘러나오는 중이라, 그 소리를
      // 잡음 바닥으로 배우면 정작 어르신 목소리가 무음으로 판정되고, 목소리
      // 봉우리로 배우면 문턱이 TTS 크기까지 올라가 어르신이 묻힌다.
      rs.push(input)                            // 커서는 계속 굴린다
      const g = gates()
      opts.onLevel?.({ rms, voiced: false, floor, peak, open: g.open, auto: g.auto })
      return
    }

    // 봉우리는 게이트와 **무관하게** 잰다. 게이트가 걷어찬 소리도 rms 에는 남아
    // 있고, 「어르신 목소리가 문턱에 못 미친다」는 사실은 거기서만 보인다.
    peak = rms > peak ? peak * (1 - PEAK_RISE) + rms * PEAK_RISE : peak * PEAK_FALL

    const { open, close, auto } = gates()
    const res = rs.push(input)

    if (!voiced) {
      // 바닥은 조용할 때만 다시 잰다. 말하는 동안 올리면 바닥이 목소리를 따라
      // 올라가 문장 뒤쪽이 통째로 무음으로 판정된다.
      floor = rms < floor ? floor * 0.85 + rms * 0.15 : floor * 0.99 + rms * 0.01

      preroll.push(res)
      prerollMs += durMs
      while (prerollMs > PREROLL_MS && preroll.length > 1) {
        prerollMs -= (preroll.shift()!.length / RATE) * 1000
      }
      if (rms > open) {
        voiced = true
        belowMs = 0
        sinceFlush = 0
        pending = preroll        // 말머리를 함께 보낸다
        preroll = []
        prerollMs = 0
      }
    } else {
      pending.push(res)
      sinceFlush += durMs
      belowMs = rms < close ? belowMs + durMs : 0
      if (belowMs >= CLOSE_MS) {
        voiced = false
        flush()                  // 꼬리 침묵까지 붙여 보낸다 — 끝음이 잘리지 않는다
      } else if (sinceFlush >= FLUSH_MS) {
        flush()
      }
    }
    opts.onLevel?.({ rms, voiced, floor, peak, open, auto })
  }

  src.connect(node)
  node.connect(mute)
  mute.connect(ctx.destination)

  return {
    setActive(on: boolean) {
      if (!on) {
        voiced = false
        pending = []
        preroll = []
        prerollMs = 0
        belowMs = 0
        sinceFlush = 0
        // floor 와 peak 은 지우지 않는다. 방도 어르신 목소리도 낭독 한 번에
        // 바뀌지 않는다 — 지우면 매 턴 처음부터 다시 배운다.
      }
      active = on
    },

    stop() {
      if (stopped) return
      stopped = true
      flush()
      node.onaudioprocess = null
      try { src.disconnect(); node.disconnect(); mute.disconnect() } catch { /* 이미 끊겼다 */ }
      stream.getTracks().forEach(t => t.stop())
      void ctx.close()
    },
  }
}
