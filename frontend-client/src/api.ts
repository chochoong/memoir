// 백엔드 호출은 전부 여기를 지난다.
// 컴포넌트가 fetch 를 직접 부르기 시작하면 주소와 헤더가 흩어져 수습이 안 된다.

export type State = 'SPEAKING' | 'LISTENING' | 'PROCESSING' | 'CLOSED'

export interface Fragment {
  idx: number
  question: string | null
  answer: string
}

export interface Snapshot {
  session_id: string
  state: State
  turn: number
  max_turn: number        // 0 = 제한 없음. 끝은 AI 의 close 판단이 정한다
  turns_left: number      // 제한이 없으면 -1
  question_ready: boolean
  t2_expired: boolean
  fragments: Fragment[]
  next_question: string | null
  audio_bytes: number          // 지금 모여 있는 발화 오디오. 청크가 닿는지 눈으로 보려고 둔다
  question_audio: boolean      // 낭독할 소리가 준비됐나. false 면 글자만 띄운다
  closing_hint: string | null  // 마칠 때 띄울 한 줄. 진행 중에는 null
  timer_drift: { n?: number; max_ms?: number; avg_ms?: number }
}

// 구간별 지연 (FR-AD-314). stt 는 오디오가 붙기 전에 저장된 회차에는 없다.
export interface Span {
  stt?: number
  tts?: number
  save: number
  question: number
  deliver: number
  total: number
}

export interface Latency {
  turns: Span[]
  timer_drift: { n?: number; max_ms?: number; avg_ms?: number }
  fires: { name: string; drift_ms: number }[]
}

// ---------------------------------------------------------------- 저장된 기록
// 위의 Snapshot 은 지금 도는 회차(서버 메모리)고, 아래는 끝난 회차(DB)다.
// 서버를 재시작하면 위는 사라지고 아래는 남는다.

export interface SavedSession {
  session_id: string
  title: string
  state: State
  turn: number
  max_turn: number
  t2_seconds: number
  closed_reason: string | null   // finish(AI 판단) | abort | max_turn | null(진행 중)
  created_at: string
  closed_at: string | null
  fragment_count: number
}

export interface SavedFragment {
  idx: number
  question: string | null
  answer: string
  decision: { action?: string; reason?: string } | null   // FR-IV-006 근거
  latency: Span | null
  created_at: string
}

// ---------------------------------------------------------------- 사진
// 올린 뒤 돌아오는 것. `url` 은 **이 서버의 경로**지 스토리지 주소가 아니다
// (backend-agent/app/session/photostore.py 머리 참조).

export interface PhotoUp {
  photo_id: string
  url: string
  mime: string
  width: number
  height: number
  bytes: number
}

export type SessionRecord = Omit<SavedSession, 'fragment_count'> & {
  fragments: SavedFragment[]
}

// 개발 중에만 VITE_API_BASE 를 쓴다. **빌드본은 항상 같은 출처로 부른다.**
//
// 개발 중에는 Vite 개발 서버(5173)와 백엔드(8010)가 포트가 달라 주소가 필요하다.
// 그 주소가 빌드본에 따라가면 안 된다 — 빌드본은 남의 기기에서 열리고, 거기서
// localhost 는 그 기기 자신이라 요청이 갈 곳이 없다. https 로 서빙되면 mixed content
// 로 막히기까지 한다. 폰에서는 원인이 안 보이는 `TypeError: Load failed` 로만 나온다.
// 실기기 확인 때 실제로 이렇게 막혔다.
//
// PROD 를 조건으로 두면 빌드 시점에 접혀서 주소가 번들에 **남지도 않는다.**
// 환경 파일을 어떻게 두든 재현되지 않는다. 확인은 `grep 8010 web/assets/*.js` 로 한다.
//
// 빌드본을 백엔드와 다른 호스트에 올리게 되면 이 줄을 고친다. 그건 의도적인 변경이다.
const BASE = import.meta.env.PROD ? '' : (import.meta.env.VITE_API_BASE ?? '')

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': 'dev-user', // 구글 로그인이 붙으면 교체
      ...init?.headers,
    },
  })
  if (!res.ok) {
    // 409 는 정의되지 않은 상태 전이다. 조용히 무시하지 않고 화면에 드러낸다.
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? '요청에 실패했습니다')
  }
  return res.json()
}

export const api = {
  // photoId 는 선택이다. 주면 서버가 배경에서 한 번 분석해 사진 단서를
  // 만들고, 그 뒤의 질문에 쓴다 (controller._analyze_photo). 회차 시작을
  // 기다리게 하지 않는다.
  start: (postcard: string, pace: string, photoId?: string) =>
    call<Snapshot>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ title: '시험', postcard, pace, photo_id: photoId }),
    }),

  get: (id: string) => call<Snapshot>(`/sessions/${id}`),

  ttsDone: (id: string) => call<Snapshot>(`/sessions/${id}/tts-done`, { method: 'POST' }),

  speech: (id: string, text: string) =>
    call<Snapshot>(`/sessions/${id}/speech`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),

  // 오디오는 JSON 으로 감싸지 않는다. base64 로 3분의 4가 되는 데다 폰에서
  // 인코딩 비용까지 든다. 본문은 바이트 그대로, mime 은 Content-Type 으로.
  audio: (id: string, pcm: ArrayBuffer, mime: string) =>
    call<Snapshot>(`/sessions/${id}/speech/audio`, {
      method: 'POST', body: pcm, headers: { 'Content-Type': mime },
    }),

  // 지금 질문을 읽은 mp3. **소리가 없으면 204 라 null 이 온다** — 오류가 아니다.
  // 「질문은 있는데 소리는 없다」는 정상 상태이고, 화면은 글자만 띄우면 된다.
  questionAudio: async (id: string): Promise<Blob | null> => {
    const res = await fetch(`${BASE}/api/sessions/${id}/question/audio`,
                            { headers: { 'X-User-Id': 'dev-user' } })
    if (res.status === 204) return null
    if (!res.ok) throw new ApiError(res.status, '소리를 받지 못했습니다')
    const blob = await res.blob()
    return blob.size ? blob : null
  },

  done: (id: string) => call<Snapshot>(`/sessions/${id}/done`, { method: 'POST' }),

  abort: (id: string) => call<Snapshot>(`/sessions/${id}/abort`, { method: 'POST' }),

  latency: (id: string) => call<Latency>(`/sessions/${id}/latency`),

  // 지난 회차 목록. DB 를 못 읽으면 빈 목록이 아니라 503 이 온다 — 화면은
  // 「없다」와 「못 읽었다」를 다르게 말해야 한다.
  list: (limit = 20) => call<{ sessions: SavedSession[] }>(`/sessions?limit=${limit}`),

  record: (id: string) => call<SessionRecord>(`/sessions/${id}/record`),

  // 사진도 오디오와 같다 — 본문은 **바이트 그대로**다. call() 을 안 쓰는 이유는
  // 그쪽이 Content-Type: application/json 을 박기 때문이다. 여기서 보내는 type 은
  // 참고값일 뿐이고, 형식은 서버가 앞머리 바이트로 다시 가린다.
  //
  // session_id 는 선택이다. 어르신이 회차를 열기 전에 사진을 고를 수 있어야 한다.
  photo: async (file: File, sessionId?: string): Promise<PhotoUp> => {
    const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
    const res = await fetch(`${BASE}/api/photos${q}`, {
      method: 'POST',
      body: file,
      headers: {
        'Content-Type': file.type || 'application/octet-stream',
        'X-User-Id': 'dev-user',
      },
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }))
      throw new ApiError(res.status, body.detail ?? '사진을 올리지 못했습니다')
    }
    return res.json()
  },

  // <img src> 가 쓸 주소.
  //
  // **이 요청에는 X-User-Id 를 실을 수 없다** — <img> 에 커스텀 헤더를 붙일
  // 방법이 없다. 서버가 그래서 신원을 `uid` 쿠키에 한 벌 적어 둔다 (main.py 의
  // mirror_uid). 빌드본은 같은 출처라 그 쿠키가 따라가지만, **개발 서버(5173)
  // 에서는 포트가 달라 남의 쿠키가 되어 안 따라간다.** 사진 확인은 빌드본으로
  // 한다.
  photoSrc: (photoId: string) => `${BASE}/api/photos/${photoId}`,
}
