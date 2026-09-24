import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type Latency, type PhotoUp, type SavedSession, type SessionRecord, type Snapshot } from './api'
import { MIME, startRecorder, type Level, type Recorder } from './recorder'
import * as speaker from './speaker'
import * as logbook from './log'
import LogPanel from './LogPanel'

// 상태는 서버가 타이머로 바꾸므로 폴링한다.
// 4일차에 WebSocket 으로 교체하면 이 훅만 갈아 끼우면 된다.
const POLL_MS = 300

const PACES = [
  { key: 'fast', label: '빠름', hint: 'T2 3초' },
  { key: 'normal', label: '보통', hint: 'T2 5초' },
  { key: 'slow', label: '느긋', hint: 'T2 7초' },
]

// 지난 회차는 최신 몇 개만. 전부 끌어오면 폰에서 읽을 수 없는 목록이 되고,
// 여기서 필요한 건 「방금 것들」이지 전부가 아니다.
const SAVED_LIMIT = 5

const STATE_LABEL: Record<string, string> = {
  SPEAKING: '질문 낭독 중',
  LISTENING: '듣고 있어요',
  PROCESSING: '정리하는 중',
  CLOSED: '마쳤습니다',
}

export default function App() {
  const [snap, setSnap] = useState<Snapshot | null>(null)
  const [lat, setLat] = useState<Latency | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [seed, setSeed] = useState('')
  // 빈 칸으로 연다. 「말한다」는 칸의 글자를 전사 결과인 척 밀어 넣는 개발용
  // 길이라, 미리 적어 두면 한 번 누르는 것만으로 그 글이 그대로 턴의 답이 된다.
  const [utter, setUtter] = useState('')
  const timer = useRef<number | null>(null)
  const [saved, setSaved] = useState<SavedSession[] | null>(null)
  const [savedErr, setSavedErr] = useState<string | null>(null)
  const [rec, setRec] = useState<SessionRecord | null>(null)
  const [showSaved, setShowSaved] = useState(false)
  const [baking, setBaking] = useState(false)
  const [cardErr, setCardErr] = useState<string | null>(null)
  const [mic, setMic] = useState(false)
  const [micErr, setMicErr] = useState<string | null>(null)
  // 마이크 판정 속 숫자. 문턱은 recorder 가 스스로 정하므로 (recorder.ts 의
  // 「문턱을 스스로 정하는 법」) 맞게 도는지 보려면 이걸 눈으로 봐야 한다.
  const [level, setLevel] = useState<Level>(
    { rms: 0, voiced: false, floor: 0, peak: 0, open: 0, auto: false })
  const [voice, setVoice] = useState(true)        // 낭독을 틀 것인가
  const [reading, setReading] = useState(false)   // 지금 낭독 중인가
  const [voiceNote, setVoiceNote] = useState<string | null>(null)
  // 이미 읽은 질문. 폴링이 같은 스냅샷을 여러 번 물어와도 두 번 읽지 않는다.
  const spoken = useRef<string | null>(null)
  const rec_ = useRef<Recorder | null>(null)
  const [photos, setPhotos] = useState<PhotoUp[]>([])
  const [photoErr, setPhotoErr] = useState<string | null>(null)
  const [picking, setPicking] = useState(false)
  const sessionRef = useRef<string | null>(null)
  const listeningRef = useRef(false)
  // 청크 업로드는 줄을 세운다. 겹쳐 보내면 서버에 닿는 순서가 뒤집혀
  // 어르신의 말이 뒤섞인 채로 전사된다.
  const queue = useRef<Promise<unknown>>(Promise.resolve())

  const run = useCallback(async (fn: () => Promise<Snapshot>) => {
    setError(null)
    // iOS 는 사용자 동작 안에서만 소리를 허락한다. 버튼을 누른 지금이 그 자리다.
    void speaker.unlock()
    try {
      setSnap(await fn())
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status} · ${e.message}` : String(e)
      logbook.fail('요청', msg)
      setError(msg)
    }
  }, [])

  // 저장된 기록을 읽는다.
  //
  // **503 과 빈 목록을 다르게 말한다.** 못 읽은 것을 「기록이 없습니다」로
  // 표시하면 어르신에게는 조각이 사라졌다는 말이 된다. 조각은 DB 에 그대로 있다.
  const loadSaved = useCallback(async () => {
    setSavedErr(null)
    try {
      setSaved((await api.list(SAVED_LIMIT)).sessions)
    } catch (e) {
      setSaved(null)
      setSavedErr(
        e instanceof ApiError && e.status === 503
          ? '지금은 기록을 불러올 수 없습니다. 조각은 그대로 있습니다.'
          : e instanceof ApiError ? `${e.status} · ${e.message}` : String(e))
    }
  }, [])

  const openRecord = useCallback(async (sessionId: string) => {
    setSavedErr(null)
    setCardErr(null)
    try {
      setRec(await api.record(sessionId))
    } catch (e) {
      setRec(null)
      setSavedErr(e instanceof ApiError ? `${e.status} · ${e.message}` : String(e))
    }
  }, [])

  // 엽서 굽기. 답이 올 때까지 기다린다 (api.makePostcard).
  //
  // **기록을 다시 읽지 않고 받은 것을 끼워 넣는다.** 다시 읽으면 요청이 하나
  // 더 들고, 그 사이에 DB 가 비틀거리면 방금 구운 엽서가 화면에서 사라진다.
  const bake = useCallback(async (sessionId: string) => {
    setCardErr(null)
    setBaking(true)
    const t0 = performance.now()
    try {
      const pc = await api.makePostcard(sessionId)
      logbook.log('엽서', `${((performance.now() - t0) / 1000).toFixed(1)}초 · 「${pc.text}」`)
      setRec(r => r && r.session_id === sessionId
        ? { ...r, postcard: { url: pc.url, text: pc.text, created_at: new Date().toISOString() } }
        : r)
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status} · ${e.message}` : String(e)
      logbook.fail('엽서', msg)
      setCardErr(msg)
    } finally {
      setBaking(false)
    }
  }, [])

  // 사진 한 장.
  //
  // 회차가 열려 있으면 그 회차에 매단다. 안 열려 있어도 올라간다 — 어르신이
  // 사진을 먼저 고르고 그 사진을 보며 이야기를 시작할 수 있어야 해서,
  // photo.session_id 가 NULL 을 허용한다.
  const pickPhoto = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    // **고른 값을 비운다.** 안 비우면 같은 사진을 두 번 고를 때 change 가
    // 안 온다 — 값이 안 바뀌었기 때문이다. 폰에서 「한 번은 되는데 두 번째는
    // 아무 일도 안 난다」로 나타난다.
    e.target.value = ''
    if (!file) return

    setPhotoErr(null)
    setPicking(true)
    logbook.log('사진', `${file.name || '이름없음'} ${(file.size / 1024).toFixed(0)}KB ${file.type || '형식미상'}`)
    try {
      const up = await api.photo(file, sessionRef.current ?? undefined)
      setPhotos(list => [up, ...list])
      logbook.log('사진', `${up.photo_id.slice(0, 8)} 저장 ${up.width}×${up.height} ${(up.bytes / 1024).toFixed(0)}KB`)
    } catch (err) {
      const msg = err instanceof ApiError ? `${err.status} · ${err.message}` : String(err)
      logbook.fail('사진', msg)
      setPhotoErr(msg)
    } finally {
      setPicking(false)
    }
  }, [])

  // 펼칠 때만 읽는다. 접혀 있으면 DB 도 건드리지 않는다 — 마이크를 시험하는
  // 동안에는 화면도 네트워크도 조용한 편이 낫다.
  const toggleSaved = useCallback(() => {
    setShowSaved(v => {
      if (!v) void loadSaved()
      else { setRec(null); setSavedErr(null) }
      return !v
    })
  }, [loadSaved])

  // 폴링
  useEffect(() => {
    if (!snap || snap.state === 'CLOSED') {
      if (timer.current) window.clearInterval(timer.current)
      return
    }
    timer.current = window.setInterval(async () => {
      try {
        setSnap(await api.get(snap.session_id))
      } catch { /* 폴링 실패는 무시하고 다음 주기에 재시도 */ }
    }, POLL_MS)
    return () => { if (timer.current) window.clearInterval(timer.current) }
  }, [snap?.session_id, snap?.state])

  // 마치면 지연 기록을 불러온다
  useEffect(() => {
    if (snap?.state !== 'CLOSED' || !snap) return
    api.latency(snap.session_id).then(setLat).catch(() => {})
    if (showSaved) void loadSaved()   // 펼쳐 둔 경우에만. 방금 끝낸 회차가 바로 보여야 한다
  }, [snap?.state, snap?.session_id, loadSaved, showSaved])

  // 창 밖에서 터진 것까지 받아 적는다. 폰에는 열어 볼 콘솔이 없다.
  useEffect(() => {
    logbook.install()
    // 「소리가 안 나요」를 갈라 보려면 어느 기기인지부터 알아야 한다.
    logbook.dim('기기', navigator.userAgent)
  }, [])

  // **스냅샷의 차이만 찍는다.** 폴링이 300ms 마다 같은 값을 물어오므로
  // 들어오는 대로 찍으면 기록이 같은 줄로 뒤덮여 아무것도 안 보인다.
  const seen = useRef<Snapshot | null>(null)
  useEffect(() => {
    const p = seen.current
    seen.current = snap
    if (!snap) return
    if (!p || p.session_id !== snap.session_id) {
      logbook.log('회차', `${snap.session_id.slice(0, 8)} 열림`)
    } else {
      if (p.state !== snap.state) logbook.log('상태', `${p.state} → ${snap.state}`)
      if (p.turn !== snap.turn) logbook.log('턴', `${p.turn} → ${snap.turn}`)
    }
    if (snap.fragments.length > (p?.fragments.length ?? 0)) {
      const f = snap.fragments[snap.fragments.length - 1]
      // 전사 결과가 여기 찍힌다. 마이크를 시험할 때 가장 보고 싶은 한 줄이다.
      logbook.log('조각', `[${f.idx}] ${f.answer}`)
    }
    if (snap.next_question && snap.next_question !== p?.next_question) {
      logbook.log('질문', snap.next_question)
    }
    if (snap.state === 'CLOSED' && p?.state !== 'CLOSED') {
      logbook.warn('회차', snap.closing_hint ?? '마쳤습니다')
    }
  }, [snap])

  const id = snap?.session_id
  const listening = snap?.state === 'LISTENING'

  // 콜백은 오디오 스레드에서 불린다. 거기서 snap 을 읽으면 켤 때의 값에 붙박이므로
  // ref 로 흘려 넣는다.
  sessionRef.current = id ?? null
  listeningRef.current = listening

  const toggleMic = useCallback(async () => {
    setMicErr(null)
    if (rec_.current) {
      rec_.current.stop(); rec_.current = null
      setMic(false)
      setLevel({ rms: 0, voiced: false, floor: 0, peak: 0, open: 0, auto: false })
      logbook.log('마이크', '껐습니다')
      return
    }
    try {
      rec_.current = await startRecorder({
        onLevel: setLevel,
        onChunk: pcm => {
          // 낭독 중이나 정리 중에 들어온 소리는 버린다. 스피커에서 나온 질문이
          // 그대로 되돌아와 T1 을 리셋하면 발화가 영영 확정되지 않는다.
          const sid = sessionRef.current
          if (!sid || !listeningRef.current) return
          queue.current = queue.current
            .then(() => api.audio(sid, pcm, MIME))
            .then(snapshot => {
              setSnap(snapshot)
              logbook.dim('올림', `${(pcm.byteLength / 32000).toFixed(1)}초`)
            })
            .catch(e => {
              // 청크 하나는 놓쳐도 된다. 다음 청크가 T1 을 다시 민다.
              // 다만 **놓쳤다는 사실은 남긴다** — 이게 쌓이면 전사가 비는 이유가 된다.
              logbook.warn('올림', e instanceof ApiError ? `${e.status} · ${e.message}` : String(e))
            })
        },
      })
      setMic(true)
      logbook.log('마이크', '켰습니다')
    } catch (e) {
      // NotAllowedError = 거부, NotFoundError = 장치 없음. 둘을 구분해 말한다.
      const name = e instanceof DOMException ? e.name : ''
      const msg =
        name === 'NotAllowedError' ? '마이크 사용을 허용해 주세요 (주소창의 자물쇠 → 마이크)'
        : name === 'NotFoundError' ? '마이크를 찾지 못했습니다'
        : e instanceof Error ? e.message : String(e)
      logbook.fail('마이크', msg)
      setMicErr(msg)
    }
  }, [])

  useEffect(() => () => { rec_.current?.stop(); rec_.current = null }, [])

  /**
   * 소리 시험 — 지금 질문의 소리를 **직접 눌러서** 틀어 본다.
   *
   * 자동 재생과 갈라 보기 위한 버튼이다. 눌러서 들리면 브라우저의 자동 재생
   * 정책 문제이고, 눌러도 안 들리면 기기 쪽(음소거 스위치, 또는 마이크가 켜져
   * 있어 소리가 통화용 수화기로 흘러나가는 경우)이다. 둘은 고칠 자리가 다르다.
   */
  const testSound = useCallback(async () => {
    const sid = sessionRef.current
    if (!sid) return
    logbook.log('시험', `잠금 ${speaker.isUnlocked() ? '풀림' : '아직'} · 눌러서 틀어 봅니다`)
    await speaker.unlock()
    try {
      const blob = await api.questionAudio(sid)
      if (!blob) { logbook.warn('시험', '받을 소리가 없습니다 (204)'); return }
      logbook.log('시험', `${(blob.size / 1024).toFixed(1)}KB 받았습니다`)
      const r = await speaker.play(blob)
      logbook.log('시험', r.finished ? '끝까지 났습니다' : '중간에 멈췄습니다')
    } catch (e) {
      logbook.fail('시험', e instanceof Error ? e.message : String(e))
    }
  }, [])

  // 듣는 동안에만 마이크 판정을 켠다. 낭독 중에 켜 두면 스피커 소리가 마이크로
  // 되돌아와, 수음이 열리는 순간 그 꼬리가 어르신의 첫마디인 양 올라간다.
  useEffect(() => { rec_.current?.setActive(listening) }, [listening, mic])

  // 낭독 — 질문이 나오면 읽어 주고, 다 읽으면 스스로 수음을 연다.
  //
  // **tts-done 을 여기서 올리는 이유**는 낭독이 끝나는 시각을 서버가 알 수 없기
  // 때문이다. 끝까지 튼 쪽이 화면이라, 여기서 올려야 T1 이 정확한 순간부터 돈다.
  // **회차가 바뀌면 지운다.** 여는 말은 늘 같은 문장이라, 지우지 않으면 두
  // 번째 회차의 여는 말이 「이미 읽은 말」로 걸려 낭독이 통째로 건너뛰어진다.
  // 그러면 tts-done 이 안 올라가고, 서버는 낭독이 끝난 줄을 몰라 수음을 열지
  // 않는다 — 회차가 SPEAKING 에 멈춘 채 화면만 계속 물어보게 된다.
  // 실제로 그렇게 멈춘 회차가 셋 있었다 (폴링 84회 · 오디오 0바이트).
  useEffect(() => { spoken.current = null }, [id])

  useEffect(() => {
    if (!id || snap?.state !== 'SPEAKING') return
    const q = snap.next_question
    if (!q || !voice || spoken.current === q) return
    spoken.current = q

    let cancelled = false
    void (async () => {
      setVoiceNote(null)
      const t0 = performance.now()
      try {
        const blob = await api.questionAudio(id)
        if (!blob) {
          // 소리가 없는 것은 실패가 아니다. 글자는 그대로 있고 버튼도 남아 있다.
          logbook.warn('소리', '없음 — 글자로만 나갑니다')
          setVoiceNote('소리 없이 글자로만 나갑니다')
          return
        }
        logbook.log('소리', `${(blob.size / 1024).toFixed(1)}KB · 받는 데 ${(performance.now() - t0).toFixed(0)}ms`)
        if (cancelled) return
        setReading(true)
        const t1 = performance.now()
        await speaker.play(blob)
        logbook.log('낭독', `${((performance.now() - t1) / 1000).toFixed(1)}초 읽었습니다`)
        if (cancelled) return
        await run(() => api.ttsDone(id))
      } catch (e) {
        // 잠금이 안 풀렸거나 재생이 거부됐다. 「낭독 끝」을 눌러 넘어가면 된다.
        logbook.fail('낭독', e instanceof Error ? e.message : String(e))
        setVoiceNote('소리를 틀지 못했습니다. 「낭독 끝」을 눌러 주세요')
      } finally {
        if (!cancelled) setReading(false)
      }
    })()
    return () => { cancelled = true }
  }, [id, snap?.state, snap?.next_question, voice, run])

  // 열어 본 회차에 읽을 것이 하나도 없나. 질문도 답도 없는 조각만 있는 경우다 —
  // 씨앗 없이 열고 첫 말씀 전에 끝난 회차가 그렇다. 제목만 덩그러니 남기지 않는다.
  const recEmpty = !!rec && rec.fragments.every(f => !f.answer.trim() && !f.question)

  return (
    <main>
      <header>
        <h1>기억의 조각</h1>
        <p className="sub">1주차 · 오디오 없이 상태 머신과 타이머를 확인합니다</p>
      </header>

      {error && <div className="error" role="alert">{error}</div>}

      <section>
        <h2>① 회차 시작</h2>
        <label htmlFor="seed">씨앗 (0번 조각)</label>
        <input id="seed" value={seed} onChange={e => setSeed(e.target.value)}
               placeholder="비워 두면 어르신 말씀만으로 시작합니다 (인명·지명은 전사에 도움이 됩니다)" />
        <p className="note">
          {photos.length > 0
            ? `아래 ②에서 마지막에 올린 사진(${photos[0].photo_id.slice(0, 8)})이 함께 갑니다.`
            : '사진을 먼저 올리면(②) 그 사진이 함께 갑니다. 없어도 씨앗만으로 시작합니다.'}
        </p>
        <div className="row">
          {PACES.map(p => (
            <button key={p.key}
                    onClick={() => run(() => api.start(seed, p.key, photos[0]?.photo_id))}>
              {p.label}<small>{p.hint}</small>
            </button>
          ))}
        </div>
      </section>

      <section>
        <h2>② 사진</h2>
        <p className="note">
          올리면 서버가 1024px JPEG 한 장으로 줄이고 위치 정보를 떼어냅니다.
          아래 그림은 그러고 나서 <b>다시 받은 바이트</b>라, 보이면 올리기와
          내려받기가 둘 다 돌아간 것입니다.
        </p>
        <div className="row">
          <label className={`pick ${picking ? 'busy' : ''}`}>
            {picking ? '올리는 중…' : '사진 고르기'}
            <small>{sessionRef.current ? '지금 회차에 매달린다' : '회차 없이도 올라간다'}</small>
            <input type="file" accept="image/*" hidden disabled={picking}
                   onChange={e => void pickPhoto(e)} />
          </label>
        </div>
        {photoErr && <div className="error" role="alert">{photoErr}</div>}
        {photos.length > 0 && (
          <ul className="photos">
            {photos.map(ph => (
              <li key={ph.photo_id}>
                <img src={api.photoSrc(ph.photo_id)} alt="" loading="lazy" />
                <span className="meta">{ph.width}×{ph.height} · {(ph.bytes / 1024).toFixed(0)}KB</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {snap && (
        <section>
          <h2>③ 대화</h2>
          <div className="statebar">
            <span className={`chip ${snap.state.toLowerCase()}`}>{STATE_LABEL[snap.state]}</span>
            <span className="meta">턴 {snap.turn}{snap.max_turn > 0 ? `/${snap.max_turn}` : ''}</span>
            <span className="meta">질문 {snap.question_ready ? '✓' : '–'}</span>
            <span className="meta">T2 {snap.t2_expired ? '✓' : '–'}</span>
            {reading && <span className="meta reading">읽는 중</span>}
          </div>

          <p className="question">{snap.next_question ?? '—'}</p>
          {/* 마칠 때 모델이 실어 보낸 한 줄 (§1 closing_hint). 없으면 위 칩의
              「마쳤습니다」로 돈다 — 문구가 안 와도 화면은 멀쩡해야 한다. */}
          {snap.state === 'CLOSED' && snap.closing_hint && (
            <p className="note closing">{snap.closing_hint}</p>
          )}

          <div className="row">
            <button className={mic ? '' : 'ghost'} onClick={() => void toggleMic()}>
              {mic ? '마이크 끄기' : '마이크 켜기'}
              <small>{mic ? '듣는 동안에만 올린다' : 'https 필요'}</small>
            </button>
            <button className={voice ? '' : 'ghost'}
                    onClick={() => { setVoice(v => !v); speaker.stop() }}>
              {voice ? '낭독 끄기' : '낭독 켜기'}
              <small>{voice ? '읽고 나서 수음' : '버튼으로 넘어간다'}</small>
            </button>
            <button className="ghost" onClick={() => void testSound()}>
              소리 시험<small>직접 눌러 듣기</small>
            </button>
          </div>
          {voiceNote && <p className="note">{voiceNote}</p>}
          {micErr && <div className="error" role="alert">{micErr}</div>}
          {mic && (
            <div className="mic">
              <div className="level" aria-hidden="true">
                <i className={level.voiced && listening ? 'on' : ''}
                   style={{ width: `${Math.min(100, level.rms * 400)}%` }} />
                {/* 문턱 눈금. 막대가 이 선을 넘어야 소리가 올라간다 —
                    어르신 목소리가 선에 얼마나 못 미치는지가 여기서 보인다. */}
                <b style={{ left: `${Math.min(100, level.open * 400)}%` }} />
              </div>
              <span className="meta">
                {!listening ? '대기' : level.voiced ? '말씀 중' : '조용함'}
                {' · '}올린 소리 {(snap.audio_bytes / 32000).toFixed(1)}초
              </span>
              {/* 자동 보정이 도는지 보는 창. auto 가 꺼져 있으면 아직 목소리를
                  한 번도 못 본 것이라 예전 고정 배수로 돌고 있다는 뜻이다. */}
              <span className="meta nums">
                지금 {level.rms.toFixed(4)}
                {' · '}바닥 {level.floor.toFixed(4)}
                {' · '}문턱 {level.open.toFixed(4)}
                {' · '}봉우리 {level.peak.toFixed(4)}
                {' · '}{level.auto
                  ? `자동 ×${(level.floor > 0 ? level.open / level.floor : 0).toFixed(1)}`
                  : '고정 ×3.5'}
              </span>
            </div>
          )}

          <div className="row">
            <button disabled={snap.state !== 'SPEAKING'}
                    onClick={() => { speaker.stop(); void run(() => api.ttsDone(id!)) }}>
              낭독 끝<small>{reading ? '지금 넘어가기' : '수음 시작'}</small>
            </button>
            <button className="ghost" disabled={!listening} onClick={() => run(() => api.speech(id!, utter))}>
              말한다<small>T1 리셋</small>
            </button>
            <button className="ghost" disabled={!listening} onClick={() => run(() => api.done(id!))}>
              다 말했어요<small>즉시 확정</small>
            </button>
            <button className="ghost" disabled={snap.state === 'CLOSED'} onClick={() => run(() => api.abort(id!))}>
              중단
            </button>
          </div>

          <label htmlFor="utter">어르신의 말</label>
          <input id="utter" value={utter} onChange={e => setUtter(e.target.value)}
                 placeholder="비워 두고 「다 말했어요」를 누르면 턴이 소모되지 않습니다" />
        </section>
      )}

      {snap && snap.fragments.length > 0 && (
        <section>
          <h2>④ 조각</h2>
          <ol className="fragments">
            {snap.fragments.map(f => (
              <li key={f.idx}>
                {f.question && <p className="q">{f.question}</p>}
                <p className="a">{f.answer}</p>
              </li>
            ))}
          </ol>
        </section>
      )}

      {lat && lat.turns.length > 0 && (
        <section>
          <h2>⑤ 지연</h2>
          <table>
            <thead><tr><th>턴</th><th>전사</th><th>저장</th><th>질문</th><th>낭독</th><th>전달</th><th>합계</th></tr></thead>
            <tbody>
              {lat.turns.map((t, i) => (
                <tr key={i}>
                  <td>{i + 1}</td>
                  <td>{t.stt === undefined ? '–' : t.stt.toFixed(0)}</td>
                  <td>{t.save.toFixed(0)}</td>
                  <td>{t.question.toFixed(0)}</td>
                  <td>{!t.tts ? '–' : t.tts.toFixed(0)}</td>
                  <td>{t.deliver.toFixed(0)}</td>
                  <td><b>{t.total.toFixed(0)}ms</b></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="note">
            「전사」와 「질문」이 T2 안에 들어가야 어르신이 지연을 느끼지 않습니다.
            「전달」은 그러고도 남아 T2 를 기다린 시간이라, 이 값이 크다는 건
            처리가 침묵 안에 잘 숨었다는 뜻입니다. 「낭독」이 「전달」보다 작으면
            소리도 침묵 안에서 다 만들어진 것입니다. 오디오 이전 회차는 「–」입니다.
            타이머 오차 최대 {lat.timer_drift.max_ms?.toFixed(0) ?? '–'}ms (허용 200ms)
          </p>
        </section>
      )}
      <section>
        <div className="row">
          <button className="ghost" onClick={toggleSaved}>
            {showSaved ? '지난 회차 접기' : '⑥ 지난 회차'}
            <small>{showSaved ? '화면을 비운다' : 'DB 에서 읽는다'}</small>
          </button>
          {showSaved && (
            <button className="ghost" onClick={loadSaved}>새로 고침<small>다시 읽는다</small></button>
          )}
        </div>

        {showSaved && (<>
        {savedErr && <div className="error" role="alert">{savedErr}</div>}

        {!savedErr && saved?.length === 0 && (
          <p className="note">아직 저장된 회차가 없습니다.</p>
        )}

        {saved && saved.length > 0 && (
          <ol className="records">
            {saved.map(s => (
              <li key={s.session_id}>
                <button className="ghost" onClick={() => openRecord(s.session_id)}>
                  {new Date(s.created_at).toLocaleString('ko-KR')}
                  <small>
                    {/* 초가 같은 회차가 나란히 설 수 있다. 시각만으로는 어느 줄을
                        눌렀는지 알 수 없어 id 앞자리를 같이 낸다. */}
                    {s.session_id.slice(0, 6)} · 조각 {s.fragment_count} · {s.closed_reason ?? '진행 중'}
                  </small>
                </button>
              </li>
            ))}
          </ol>
        )}

        {rec && (
          <>
            <h3>{new Date(rec.created_at).toLocaleString('ko-KR')} · {rec.closed_reason ?? '진행 중'}</h3>
            {recEmpty && (
              <p className="note">남은 내용이 없습니다 · 조각 {rec.fragments.length}개</p>
            )}
            {rec.closed_at && !recEmpty && (
              <div className="postcard">
                {rec.postcard && (
                  <img src={api.postcardSrc(rec.postcard.url)} alt={rec.postcard.text} />
                )}
                <button className={baking ? 'ghost busy' : 'ghost'} disabled={baking}
                        onClick={() => bake(rec.session_id)}>
                  {baking ? '엽서를 그리는 중' : rec.postcard ? '엽서 다시 만들기' : '엽서 만들기'}
                  <small>{baking ? '수십 초 걸릴 수 있습니다' : '문장을 뽑고 그림을 그립니다'}</small>
                </button>
                {cardErr && <div className="error" role="alert">{cardErr}</div>}
              </div>
            )}
            {!recEmpty && (
            <ol className="fragments">
              {rec.fragments.map(f => (
                <li key={f.idx}>
                  {f.question && <p className="q">{f.question}</p>}
                  {/* **빈 답을 빈 <p> 로 두지 않는다.** 0번 씨앗은 빈 채로 열리므로
                      (start 의 seed) 그대로 그리면 번호만 찍힌 줄이 남고, 조각이
                      그것 하나뿐인 회차는 눌러도 아무것도 안 나온 것처럼 보인다.
                      **없는 것과 비어 있는 것은 다른 사건이라 화면도 다르게 말한다.** */}
                  {f.answer.trim()
                    ? <p className="a">{f.answer}</p>
                    : <p className="note">{f.idx === 0 ? '씨앗 없이 연 회차입니다' : '(빈 칸)'}</p>}
                  {f.decision?.reason && (
                    <p className="note">근거 · {f.decision.reason}</p>
                  )}
                  {f.latency && (
                    <p className="note">지연 {f.latency.total.toFixed(0)}ms</p>
                  )}
                </li>
              ))}
            </ol>
            )}
          </>
        )}
        </>)}
      </section>

      <LogPanel />
    </main>
  )
}
