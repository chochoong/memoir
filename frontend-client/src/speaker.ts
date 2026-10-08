// 낭독 — 서버가 만든 mp3 를 틀고, 끝나면 알려준다
//
// **두 갈래다.** 평소(Azure)는 파일 하나를 <audio> 로 튼다 — play(). 서버가
// 흘려 읽기(TTS_STREAM)면 날 PCM 조각을 받는 대로 Web Audio 에 이어 붙인다 —
// playStream(). Gemini 는 다 만드는 데 2~3초라, 다 받고 틀면 늘 늦는다.
// 첫 조각은 1초 안팎에 온다.
//
// **iOS 사파리는 사용자 동작 없이 소리를 내주지 않는다.** 그래서 회차를 여는
// 탭에서 `unlock()` 을 한 번 부른다. 무음 wav 를 아주 잠깐 틀어 두면 그 뒤로는
// 같은 <audio> 요소로 언제든 소리를 낼 수 있다. 요소를 매번 새로 만들면 잠금이
// 풀리지 않으니, **하나를 만들어 끝까지 돌려쓴다.**
//
// 낭독이 끝나는 시각은 서버가 알 수 없다. 끝까지 튼 쪽이 여기라서, 여기서
// tts-done 을 올려야 T1 이 정확한 순간부터 돈다 — 몇백 밀리초 어긋나면
// 「무음 3초」가 무음 2.6초가 된다.
//
// **소리가 안 난 이유는 여기서 말해 줘야 한다.** 폰에는 열어 볼 콘솔이 없어서,
// 재생이 거부됐는지 · 중간에 멈췄는지 · 아예 시작도 못 했는지를 log.ts 로
// 흘려보낸다. 그 한 줄이 없으면 「소리가 안 나요」에서 더 나아갈 수가 없다.

import * as logbook from './log'

// 44바이트짜리 무음 wav. 잠금을 푸는 용도라 소리가 없어야 한다.
const SILENCE =
  'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA='

let el: HTMLAudioElement | null = null
let unlocked = false

// 흘려 읽기용. <audio> 와 따로 잠금을 풀어야 한다 — 사파리는 AudioContext 를
// 사용자 동작 안에서 resume 해야 소리를 낸다. 하나를 만들어 끝까지 돌려쓴다.
let ctx: AudioContext | null = null
/** 지금 흘려 읽는 중이면 그걸 끊는 함수. */
let streamStop: (() => void) | null = null

function audioCtx(): AudioContext {
  if (!ctx) {
    const AC = window.AudioContext
      ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    ctx = new AC()
  }
  return ctx
}

/**
 * AudioContext 잠금을 푼다. 사용자 동작 안에서 불려야 한다 (unlock 이 부른다).
 * 1표본짜리 무음 버퍼를 한 번 틀어 두는 것이 iOS 에서 확실한 방법이다.
 */
async function unlockCtx(): Promise<void> {
  try {
    const c = audioCtx()
    if (c.state !== 'running') await c.resume()
    const b = c.createBuffer(1, 1, 22050)
    const src = c.createBufferSource()
    src.buffer = b
    src.connect(c.destination)
    src.start(0)
  } catch (e) {
    logbook.warn('소리', `AudioContext 잠금 해제 실패 · ${why(e)}`)
  }
}

/** 지금 돌고 있는 재생의 뒷정리. 새 재생이 끼어들면 이걸로 먼저 매듭짓는다. */
let settle: ((finished: boolean) => void) | null = null

function element(): HTMLAudioElement {
  if (!el) {
    el = new Audio()
    el.preload = 'auto'
    // 화면이 꺼져도 이어 나오게 두지 않는다. 어르신이 앱을 덮었다는 뜻이다.
    el.autoplay = false
    // iOS 에서 요소가 전체화면 재생기로 튀지 않게 한다.
    el.setAttribute('playsinline', '')
  }
  return el
}

function why(e: unknown): string {
  if (e instanceof DOMException) return `${e.name} · ${e.message}`
  return e instanceof Error ? e.message : String(e)
}

/**
 * 사용자 동작 안에서 불러야 한다. 실패해도 조용히 넘어간다 — 버튼은 남아 있다.
 *
 * **음소거로 풀면 안 된다.** 예전에는 `muted = true` 로 틀었는데, 사파리는
 * 음소거 재생을 잠금 해제로 쳐주지 않는다. 소리 없는 wav 라 그냥 틀어도
 * 들리는 것은 없다.
 */
export async function unlock(): Promise<boolean> {
  // 흘려 읽기 쪽은 매번 확인한다. 화면을 덮었다 열면 사파리가 다시 재운다.
  if (!ctx || ctx.state !== 'running') void unlockCtx()
  if (unlocked) return true
  const a = element()
  // 낭독이 돌고 있으면 손대지 않는다. src 를 갈아 끼우면 그 재생이 죽는다.
  if (!a.paused) return unlocked
  try {
    a.src = SILENCE
    a.muted = false
    a.volume = 1
    await a.play()
    a.pause()
    unlocked = true
    logbook.log('소리', '잠금 해제')
  } catch (e) {
    // 사파리가 거부했다. 다음 탭에서 다시 시도된다.
    logbook.warn('소리', `잠금 해제 실패 · ${why(e)}`)
  }
  return unlocked
}

export function isUnlocked(): boolean {
  return unlocked
}

export interface Spoken {
  /** 끝까지 틀었으면 true, 중간에 끊겼으면 false. */
  finished: boolean
}

/**
 * mp3 한 덩어리를 끝까지 튼다.
 *
 * 되돌려주는 약속은 **소리가 끝나야** 풀린다. 부르는 쪽은 그때 tts-done 을
 * 올리면 된다. 재생 자체가 거부되면(잠금이 안 풀렸다) 예외로 알린다 —
 * 조용히 성공한 척하면 화면이 영영 LISTENING 으로 넘어가지 않는다.
 */
export function play(blob: Blob): Promise<Spoken> {
  // 앞의 재생이 아직 안 끝났으면 여기서 매듭짓는다. 안 그러면 src 를 갈아 끼우는
  // 순간 그쪽 약속이 영영 안 풀려, 화면이 「읽는 중」에 붙박인다.
  settle?.(false)

  const a = element()
  const url = URL.createObjectURL(blob)

  return new Promise<Spoken>((resolve, reject) => {
    const cleanup = () => {
      a.onended = null; a.onerror = null; a.onpause = null; a.onplaying = null
      settle = null
      URL.revokeObjectURL(url)
    }
    const done = (finished: boolean) => { cleanup(); resolve({ finished }) }
    const fail = (e: unknown) => { cleanup(); reject(e instanceof Error ? e : new Error(String(e))) }
    settle = done

    a.onended = () => done(true)
    a.onerror = () => fail(new Error(`재생 오류 · code ${a.error?.code ?? '?'}`))
    // stop() 으로 끊긴 경우. 어르신이 「낭독 끝」을 눌렀다는 뜻이라 성공으로 본다.
    a.onpause = () => { if (!a.ended) done(false) }
    // **소리가 실제로 나기 시작한 자리다.** 이 줄이 안 찍히면 재생이 시작조차
    // 못 한 것이고, 찍혔는데 안 들린다면 기기 쪽(음소거 스위치·통화용 수화기로
    // 흘러나감)을 봐야 한다. 둘은 완전히 다른 문제다.
    a.onplaying = () => logbook.dim(
      '낭독', `재생 시작 · ${isFinite(a.duration) ? a.duration.toFixed(1) + '초' : '길이 미상'}`
      + ` · 음량 ${a.volume}${a.muted ? ' · 음소거됨' : ''}`)

    a.src = url
    a.muted = false
    a.volume = 1
    // **currentTime 을 건드리지 않는다.** 아직 아무것도 안 읽은 요소에 쓰면
    // 사파리가 InvalidStateError 를 던져, 소리가 나기도 전에 낭독이 실패한다.
    a.play().catch(e => fail(new Error(`재생 거부 · ${why(e)}`)))
  })
}

/**
 * 흘려 오는 낭독을 받는 대로 튼다. 응답 본문은 날 PCM 16비트 모노 리틀엔디언,
 * rate 는 Content-Type 의 `rate=` 다.
 *
 * 되돌려주는 약속은 play() 와 같다 — **마지막 조각까지 다 틀어야** 풀린다.
 * 다 받은 때가 아니다. 받기는 재생보다 먼저 끝나므로, 그 시각에 tts-done 을
 * 올리면 어르신 귀에는 아직 말이 남았는데 수음이 열려 스피커 소리가 첫마디로
 * 들어간다.
 *
 * **조각 사이가 비면(언더런) 그만큼 늦춰 이어 튼다.** 조각이 재생보다 늦게
 * 온 것이다. 실측에서는 없었지만 망이 흔들리면 생길 수 있어, 몇 번 났는지
 * 로그에 남긴다 — 말이 중간에 끊겨 들렸다면 여기 숫자가 올라가 있다.
 */
export async function playStream(res: Response): Promise<Spoken> {
  settle?.(false)
  streamStop?.()

  const c = audioCtx()
  if (c.state !== 'running') {
    try { await c.resume() } catch { /* 아래에서 말한다 */ }
  }
  if (c.state !== 'running') throw new Error(`재생 거부 · AudioContext ${c.state}`)

  const rate = Number(/rate=(\d+)/.exec(res.headers.get('content-type') ?? '')?.[1] ?? 24000)
  const reader = res.body!.getReader()
  const sources: AudioBufferSourceNode[] = []
  const LEAD = 0.06              // 첫 조각 앞 여유(초). 스케줄이 지금보다 앞서면 앞이 잘린다
  const t0 = performance.now()
  let next = 0
  let gaps = 0
  let stopped = false
  let odd: Uint8Array | null = null   // 조각 경계가 표본 한가운데 걸리면 남는 1바이트

  const stop = () => {
    if (stopped) return
    stopped = true
    reader.cancel().catch(() => {})
    for (const s of sources) { try { s.stop() } catch { /* 아직 시작 전 */ } }
  }
  streamStop = stop

  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done || stopped) break
      let bytes = value
      if (odd) {
        const m = new Uint8Array(odd.length + bytes.length)
        m.set(odd); m.set(bytes, odd.length)
        bytes = m; odd = null
      }
      if (bytes.length % 2) { odd = bytes.slice(-1); bytes = bytes.subarray(0, bytes.length - 1) }
      if (!bytes.length) continue

      const n = bytes.length / 2
      const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
      const buf = c.createBuffer(1, n, rate)
      const ch = buf.getChannelData(0)
      for (let i = 0; i < n; i++) ch[i] = view.getInt16(i * 2, true) / 32768

      const src = c.createBufferSource()
      src.buffer = buf
      src.connect(c.destination)
      const now = c.currentTime
      if (!next) {
        next = now + LEAD
        logbook.dim('낭독', `첫 소리 · 받기 시작 후 ${(performance.now() - t0).toFixed(0)}ms`
          + ` · ${rate}Hz · ${res.headers.get('x-speech-source') ?? '?'}`)
      } else if (next < now + 0.005) {
        gaps++
        next = now + 0.02
      }
      src.start(next)
      next += buf.duration
      sources.push(src)
    }
  } catch (e) {
    if (!stopped) { stop(); streamStop = null; throw new Error(`받다 끊김 · ${why(e)}`) }
  }

  // 받기는 끝났다. 마지막 조각이 다 울릴 때까지 기다린다.
  const last = sources[sources.length - 1]
  if (last && !stopped) {
    await new Promise<void>(r => {
      last.onended = () => r()
      // 끊기면(stop) onended 가 바로 온다. 혹시 안 와도 매달리지 않게 시계로 한 번 더.
      window.setTimeout(r, Math.max(0, (next - c.currentTime) * 1000) + 500)
    })
  }
  if (streamStop === stop) streamStop = null
  logbook.log('낭독', `흘려 읽기 · ${sources.length}조각${gaps ? ` · 끊김 ${gaps}번` : ''}`)
  return { finished: !stopped }
}

/** 어르신이 낭독을 건너뛰었다. play() 의 약속은 finished=false 로 풀린다. */
export function stop(): void {
  if (el && !el.paused) el.pause()
  streamStop?.()
}
