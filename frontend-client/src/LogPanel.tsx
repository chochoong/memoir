import { useEffect, useRef, useSyncExternalStore } from 'react'
import { clear, hhmmss, snapshot, subscribe, type Line } from './log'

/**
 * 검은 창. 폰에서 여는 콘솔이다.
 *
 * **바닥에 붙여 두되, 올려다보는 중이면 붙잡지 않는다.** 새 줄이 올 때마다
 * 무조건 끌어내리면 방금 지나간 오류를 읽을 수가 없다. 바닥 근처에 있을 때만
 * 따라 내려간다.
 */
export default function LogPanel() {
  const lines = useSyncExternalStore(subscribe, snapshot, snapshot)
  const box = useRef<HTMLDivElement | null>(null)
  const stick = useRef(true)

  useEffect(() => {
    const el = box.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [lines])

  const onScroll = () => {
    const el = box.current
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }

  return (
    <section>
      <div className="row logbar">
        <h2>⑥ 기록</h2>
        <button className="ghost mini" onClick={clear} disabled={lines.length === 0}>
          지우기
        </button>
      </div>
      <div className="console" ref={box} onScroll={onScroll}
           role="log" aria-live="off">
        {lines.length === 0
          ? <p className="empty">아직 찍힌 것이 없습니다.</p>
          : lines.map((l: Line) => (
              <p key={l.n} className={l.level}>
                <span className="t">{hhmmss(l.at)}</span>
                <span className="g">{l.tag}</span>
                <span className="m">{l.msg}</span>
              </p>
            ))}
      </div>
    </section>
  )
}
