// 화면에 찍는 기록 — 폰에는 콘솔이 없다
//
// 개발은 노트북에서 하지만 **실제 시험은 폰에서 한다.** 거기서는 개발자 도구를
// 열 수 없어서, 마이크가 언제 올라갔는지 · 상태가 언제 넘어갔는지 · 무엇이
// 터졌는지를 볼 데가 없다. 화면에 검은 창 하나를 두고 거기에 찍는다.
//
// 리액트 밖에 둔 이유는 **오디오 콜백과 fetch 안에서도 불러야 하기 때문**이다.
// 훅으로 만들면 그 자리에서는 못 부른다. 여기서는 모듈 하나가 목록을 들고,
// 화면은 useSyncExternalStore 로 붙어 본다.

export type Level = 'dim' | 'ok' | 'warn' | 'bad'

export interface Line {
  n: number            // 붙인 순서. 같은 밀리초에 두 줄이 들어와도 갈린다
  at: number
  tag: string
  msg: string
  level: Level
}

// 폰 메모리에 얹는 것이라 무한히 쌓을 수 없다. 오래된 줄부터 버린다 —
// 지금 무슨 일이 나는지가 궁금한 것이지 한 시간 전이 궁금한 게 아니다.
const MAX = 300

let lines: Line[] = []
let seq = 0
const subs = new Set<() => void>()

function push(tag: string, msg: string, level: Level): void {
  // 배열을 **갈아 끼운다.** useSyncExternalStore 는 참조가 같으면 다시 그리지
  // 않으므로, 밀어 넣기(push)로 고치면 화면이 영영 안 바뀐다.
  lines = [...lines, { n: ++seq, at: Date.now(), tag, msg, level }].slice(-MAX)
  subs.forEach(fn => fn())
}

/** 흔한 일. 눈에 덜 띄게 찍는다 (청크 업로드처럼 1초에 한 번씩 오는 것). */
export const dim = (tag: string, msg: string) => push(tag, msg, 'dim')
export const log = (tag: string, msg: string) => push(tag, msg, 'ok')
export const warn = (tag: string, msg: string) => push(tag, msg, 'warn')
export const fail = (tag: string, msg: string) => push(tag, msg, 'bad')

export function subscribe(fn: () => void): () => void {
  subs.add(fn)
  return () => { subs.delete(fn) }
}

export function snapshot(): Line[] {
  return lines
}

export function clear(): void {
  lines = []
  seq = 0
  subs.forEach(fn => fn())
}

export function hhmmss(at: number): string {
  const d = new Date(at)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

let installed = false

/**
 * 창 전체의 사고를 받아 적는다.
 *
 * 이게 없으면 **폰에서만 나는 오류가 조용히 사라진다.** 리액트 밖에서 터진
 * 예외나 삼켜진 약속(promise)은 화면 어디에도 흔적을 남기지 않는다.
 */
export function install(): void {
  if (installed) return
  installed = true
  window.addEventListener('error', e => fail('창', e.message || '알 수 없는 오류'))
  window.addEventListener('unhandledrejection', e => {
    const r = (e as PromiseRejectionEvent).reason
    fail('창', r instanceof Error ? r.message : String(r))
  })
}
