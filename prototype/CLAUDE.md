# memoir — 기억의 조각

어르신의 이야기를 목소리로 듣고 한 장의 엽서로 남기는 서비스. 지금은 MVP 시연 준비 단계.

## 이 저장소의 구성

```
backend-agent/     FastAPI 서버 — 대화 · 질문 생성(Gemini) · 전사/낭독(Azure) · 사진
frontend-client/   리액트 화면 (팀원 담당. 시연 이후의 본 화면)
prototype/         시연용 HTML 한 장 (내 담당) ← 이 저장소에서 내가 고치는 곳
```

**나는 프론트엔드를 맡고 있고, 다루는 파일은 `prototype/index.html` 과 `prototype/README.md` 뿐이다.**

## 지켜야 할 것

1. **백엔드 코드(`backend-agent/`)를 고치지 않는다.** 백엔드 담당 팀원이 따로 있다.
   고쳐야 할 이유가 보이면 **코드를 바꾸지 말고 무엇을 왜 바꿔야 하는지 말로 설명**한다.
   그대로 팀원에게 전달할 수 있는 형태(엔드포인트 · 요청/응답 모양)로 적어 준다.
2. **`frontend-client/` 도 고치지 않는다.** 읽고 참고하는 것은 좋다 —
   `src/api.ts` · `src/recorder.ts` · `src/speaker.ts` 가 프로토타입의 원본이다.
3. **`.env` 는 절대 커밋하지 않고, 내용을 화면에 출력하지도 않는다.** API 키가 들어 있다.
4. **커밋과 푸시는 내가 명시적으로 요청할 때만 한다.**
5. **줄바꿈(CRLF/LF)만 바뀐 대량 변경은 커밋하지 않는다.** 이 저장소는 윈도우에서
   작업해서 `git status` 에 수십 개 파일이 수정됨으로 잡히는 일이 있다. 내용 차이가
   없으면(`git diff --ignore-all-space` 가 비어 있으면) 되돌리고 진행한다.
6. `backend-agent/web/` 은 `.gitignore` 에 있다. **원본은 언제나 `prototype/index.html`**
   이고, `web/` 에는 실행할 때 복사만 한다.
7. 대화는 한국어로 한다. 나는 프로그래밍 초보이므로 **전문 용어를 쓰면 한 줄로 풀어 준다.**

## 실행 방법 (PowerShell, 윈도우)

```powershell
cd backend-agent
copy ..\prototype\index.html web\index.html   # 고칠 때마다 다시
.\run.ps1 -Dev                                 # http://127.0.0.1:8010
```

- 처음 한 번: `pip install -r requirements.txt`, `.env` 준비, `mkdir web\assets`
- 브라우저에서 새로고침은 `Ctrl + Shift + R` (예전 화면이 남는 것을 막는다)
- 서버가 켜진 PowerShell 창은 닫지 않는다. 끌 때는 `Ctrl + C`

## 백엔드와의 계약 (화면이 쓰는 것만)

모든 응답은 같은 `snapshot` 한 덩어리다.

| 엔드포인트 | 쓰임 |
|---|---|
| `POST /api/sessions` `{title, postcard, pace, max_turn, photo_id?}` | 회차 열기 |
| `GET /api/sessions/{id}` | 0.3초마다 폴링. 화면 전환의 유일한 기준 |
| `GET /api/sessions/{id}/question/audio` | 질문 mp3. **소리가 없으면 204** (오류 아님) |
| `POST /api/sessions/{id}/tts-done` | 낭독이 끝났다 → 수음 시작 |
| `POST /api/sessions/{id}/speech/audio` | 목소리. **16kHz PCM16**, `Content-Type: audio/pcm;rate=16000` |
| `POST /api/sessions/{id}/done` / `abort` | 즉시 확정 / 회차 종료 |
| `POST /api/photos` | 사진. 본문은 바이트 그대로. 서버가 받자마자 §2 분석을 건다 |

`snapshot.state` 는 `SPEAKING · LISTENING · PROCESSING · CLOSED` 넷이다.
`snapshot.fragments[]` 의 `idx 0` 은 씨앗 문장이고 1번부터가 어르신의 말씀이다.

**용어 주의** — 백엔드의 `postcard` 는 회차를 여는 **씨앗 문장**이다.
우리가 만드는 결과물(엽서/작품)이 아니다. 헷갈리면 결과물은 "카드"라고 부른다.

### 아직 없는 것

- **AI 가 엽서 글을 쓰는 기능**(기획서 §4 카드 작성 에이전트)이 없다.
  지금 엽서 글은 `index.html` 안의 규칙 기반 임시 정리(`polish()`)다.
  서버 API 가 생기면 `CONFIG.card.server` 를 켜면 된다.

## prototype/index.html 안내

파일 하나에 전부 들어 있다. `<script>` 맨 위 **`CONFIG`** 가 손잡이다.

| 구역 | 내용 |
|---|---|
| `CONFIG` | 주소 · 버튼 이름(`ui.labels`) · 사진 · 엽서 저장 · 버전 |
| `api` | 백엔드 호출. 이름과 경로를 `frontend-client/src/api.ts` 와 같게 맞춰 둔다 |
| `speaker` | 질문 mp3 재생 (`src/speaker.ts` 를 옮긴 것) |
| `startRecorder` | 소리 있는 구간만 PCM 으로 올린다 (`src/recorder.ts` 를 옮긴 것) |
| `polish` | 엽서 글 임시 정리 (서버 카드 API 가 생기면 뒤로 물러난다) |
| `applySnapshot` / `renderControls` | 서버 상태 하나로 화면 전체를 맞춘다 |
| `buildPostcardCanvas` | 엽서를 PNG 로 그려 내려받는다 |

**화면을 고치면 `CONFIG.version` 의 숫자를 올린다.** 시작 화면 아래에 찍혀서,
"고친 게 반영이 안 된 것 같다"를 눈으로 가릴 수 있다.

## 어르신을 위한 화면 원칙 (사용자 피드백에서 나온 것)

- **타이머 숫자를 보여주지 않는다.** 심문받는 느낌이 든다는 피드백이 있었다.
- 버튼은 화면당 **하나**가 기본. 보조 버튼은 작고 연하게.
- 글씨는 크게. 질문은 한 번에 하나만.
- **다듬어지지 않은 전사 원문을 그대로 보여주지 않는다.** 엽서는 정리된 글이어야 한다.
- 녹음 중인지 대기 중인지 한눈에 갈리게 한다 (붉은 테 · 칩 · 목소리 막대).

## 확인하는 법

- 화면 오른쪽 위 **톱니(⚙)** → 개발용 패널. 상태 · 턴 · 기록이 보이고,
  **마이크 없이 글자로 발화를 보낼 수 있다** (`POST /speech`). 시험할 때 이걸 쓴다.
- 서버를 띄운 PowerShell 창에 전사 결과와 상태 전이가 찍힌다.
- 회차는 **10분에 10번**까지만 열 수 있다(서버 상한). 여러 번 시험할 때는
  `.env` 에 `CREATE_MAX_PER_WINDOW=0` 을 넣고, **시연 전에 지운다.**
