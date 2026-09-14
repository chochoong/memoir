// 낭독 — 서버가 만든 mp3 를 틀고, 끝나면 알려준다
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

/** 어르신이 낭독을 건너뛰었다. play() 의 약속은 finished=false 로 풀린다. */
export function stop(): void {
  if (el && !el.paused) el.pause()
}
