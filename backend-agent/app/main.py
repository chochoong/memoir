"""
기억의 조각 — Phase 1 API (backend-agent)

    uvicorn app.main:app --reload --port 8010
    http://127.0.0.1:8010/docs

1주차 범위 — 오디오 없음. 텍스트로 전 흐름을 돌린다.
인증도 없다. X-User-Id 헤더를 받는 척만 하고, 구글 로그인은 나중에 갈아 끼운다.

화면은 frontend-client 저장소에 있다. 두 가지 방식으로 붙는다.
  개발     Vite 개발 서버(5173) → CORS 로 허용
  실기기   frontend 를 빌드해 web/ 에 넣으면 이 서버가 직접 서빙 (터널 하나로 끝)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.session import controller as sc
from app.session import limits, photo, photostore, prompt, store, stt, tts
from app.session.conf import env_flag, env_int, env_str
from app.session.machine import TransitionError
from app.session.question import gemini_question, warmup

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(name)-9s %(message)s",
    datefmt="%H:%M:%S")

log = logging.getLogger("api")

# 로그인이 없을 때 X-User-Id 에 실려 오는 값. 프론트가 **모두에게** 이것을 보낸다
# (frontend-client/src/api.ts). 그래서 이 값은 신원이 아니라 「신원이 없다」는 표시다.
# 사용자별 상한이 이 값을 걸러야 하는 이유가 아래 create_session 에 있다.
ANON_USER = "dev-user"

# 신원을 담는 쿠키. **헤더만으로는 사진을 내보낼 수 없어서 생겼다.**
UID_COOKIE = "uid"

# 신원으로 받아들이는 모양. 구글 로그인의 sub 는 숫자열이고, 지금은 dev-user 다.
# 아무 문자열이나 받으면 그것이 로그와 DB 에 그대로 실려 다닌다.
UID_OK = re.compile(r"^[A-Za-z0-9._@|-]{1,128}$")


def uid(request: Request) -> str:
    """
    이 요청의 신원. **헤더가 먼저, 없으면 쿠키다.**

    쿠키가 필요한 이유는 사진 한 줄에 있다 —

        <img src="/api/photos/{id}">

    브라우저가 이 요청을 보낼 때 **커스텀 헤더를 실을 방법이 없다.** fetch 로
    받아 Blob URL 로 바꾸면 헤더를 실을 수 있지만, 그러면 화면이 사진마다
    수동으로 받아 관리해야 하고 브라우저 캐시도 못 쓴다. 신원을 쿠키에 한 벌
    더 두는 쪽이 훨씬 작다.

    **헤더를 먼저 보는 것이 중요하다.** 기존 라우트(회차 생성·목록·기록)는
    지금도 X-User-Id 로 돌고, 그 동작을 바꾸지 않는 것이 이번 변경을 작게
    유지하는 방법이다. 쿠키는 헤더가 없을 때만, 즉 사실상 <img> 와 <audio> 에서만
    쓰인다.

    로그인이 붙으면 고칠 곳은 이 함수 하나다. 토큰을 풀어 user_id 를 얻고,
    헤더·쿠키를 둘 다 무시하면 된다. 그때까지 이 값은 **위조할 수 있다** —
    신원의 「운반」을 정리한 것이고 「증명」은 아직 없다.
    """
    head = (request.headers.get("x-user-id") or "").strip()
    if head:
        return head if UID_OK.match(head) else ANON_USER
    cookie = (request.cookies.get(UID_COOKIE) or "").strip()
    return cookie if UID_OK.match(cookie) else ANON_USER


def _workers() -> int:
    """이 서버가 몇 벌 뜨려는지. 모르면 1 로 읽는다."""
    n = env_int("WEB_CONCURRENCY", 0)
    if "--workers" in sys.argv:
        try:
            n = max(n, int(sys.argv[sys.argv.index("--workers") + 1]))
        except (IndexError, ValueError):
            pass
    return n or 1


def _posture() -> None:
    """
    기동 한 줄로 **지금 어떤 자세로 서 있는지** 남긴다.

    배포에서 틀리는 것들은 전부 조용하다. CORS 가 열려 있어도, 상한이 프록시
    주소 하나만 세고 있어도, 쿠키에 Secure 가 안 붙어도 화면은 멀쩡하다.
    그래서 로그 첫 줄에 적어 둔다 — 나중에 「그때 어떻게 떠 있었나」를 묻게 된다.

    워커가 둘 이상이면 **경고가 아니라 사고다.** 회차 레지스트리(_sessions)가
    프로세스 메모리라, 2번 워커가 받은 폴링은 1번 워커가 연 회차를 못 찾는다 —
    어르신 화면에 회차가 무작위로 사라진다. 상한(limits._hits)도 워커 수만큼
    늘어난다. 지금 구조에서 워커는 반드시 하나다 (controller.py 레지스트리 주석).
    """
    workers = _workers()
    if workers > 1:
        log.error("워커가 %d 개다 — 이 서버는 워커 하나로만 맞다. 회차는 프로세스 "
                  "메모리에 있어서 폴링이 다른 워커로 가면 404 가 난다", workers)
    log.info("자세 — 공개주소=%s · CORS허용=%s · docs=%s · 프록시=%s · 워커=%d",
             PUBLIC_ORIGIN or "(없음·개발)", _origins or "(없음·동일출처)",
             "열림" if _docs else "닫힘", limits.proxy_mode(), workers)
    if PUBLIC_ORIGIN and limits.proxy_mode() == "off":
        log.warning("공개 주소로 도는데 TRUST_PROXY 가 off 다 — 생성 상한이 모든 "
                    "요청을 프록시 주소 하나로 세어 전체가 10분에 10회로 묶인다")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    기동 시 Gemini 와 Azure STT·TTS 를 예열한다. 안 하면 첫 어르신이 콜드 스타트를
    낸다 — Gemini 실측 +1.9초, Azure 는 첫 호출 1655ms 대 이후 200~900ms 였다.

    create_task 로 던지고 기다리지 않는다 — 예열은 최적화일 뿐이라 서버 기동을
    막을 이유가 없고, 예열 전에 첫 요청이 와도 그냥 조금 느릴 뿐 동작한다.

    load_dotenv() 는 import 시점에 이미 끝났고 lifespan 은 그보다 한참 뒤에 도니
    여기서는 .env 가 확실히 읽혀 있다.

    DB 는 **기다린다.** 붙는 데 실패해도 메모리 전용으로 그냥 뜬다 —
    DB 가 없다고 서버가 안 뜨면 프론트 작업이 Postgres 셋업을 기다리게 된다.

    프롬프트 문서는 **반대다. 못 읽으면 여기서 죽는다.** DB 가 없으면 기록이
    안 남을 뿐이지만 프롬프트가 없으면 어르신께 이상한 질문이 나가고, 그건
    화면에도 로그에도 표시가 안 난다. 조용히 망가지는 쪽을 막는다.

    **세션 스윕은 예열과 다르다.** 예열은 없으면 조금 느릴 뿐이지만, 스윕이 안
    돌면 떠난 회차가 메모리에 영원히 쌓인다 (controller.py 의 레지스트리 주석
    참조). 그래서 태스크를 붙잡아 두고 종료할 때 취소한다 — 던져 놓고 잊으면
    reload 로 여러 번 뜬 뒤에 스윕이 몇 개 도는지 알 수 없게 된다.
    """
    _posture()
    prompt.load()
    await store.open_pool()
    asyncio.create_task(warmup())
    asyncio.create_task(stt.warmup())
    asyncio.create_task(tts.warmup())
    sweeper = asyncio.create_task(sc.sweep_forever())
    yield
    sweeper.cancel()
    await stt.aclose()
    await tts.aclose()
    await store.close_pool()


# ------------------------------------------------------------ 배포 자세
# PUBLIC_ORIGIN 이 있으면 「공개 주소로 서비스 중」이다 (예: https://memoa.kr).
# 이 한 값이 개발용 편의 둘을 **자동으로 닫는다** — 끄는 것을 잊게 두지 않으려고
# 따로 스위치를 만들지 않았다. 배포 절차는 docs/배포.md 에 있다.
#
#   개발 CORS 허용   localhost:5173 을 허용 목록에서 뺀다
#   /docs · /openapi 인터넷에 스키마를 펼쳐 두지 않는다 (DOCS=1 로 되살린다)
#
# 프로덕션에서 화면은 이 서버가 web/ 에서 직접 낸다. **같은 출처라 CORS 가 아예
# 필요 없다** — 허용 목록이 비어 있는 것이 정상이다.
PUBLIC_ORIGIN = env_str("PUBLIC_ORIGIN")
_public = bool(PUBLIC_ORIGIN)
_docs = "/docs" if (not _public or env_flag("DOCS")) else None

app = FastAPI(title="기억의 조각 API", version="0.1.0", lifespan=lifespan,
              docs_url=_docs, redoc_url=None,
              openapi_url="/openapi.json" if _docs else None)

# ---------------------------------------------------------------- CORS
# 개발 중에는 Vite 개발 서버가 다른 포트에서 붙는다.
# 다른 출처에서 붙일 주소는 .env 의 ALLOWED_ORIGINS 에 쉼표로 더한다 (끝 슬래시 없이).
_dev_origins = [] if _public else ["http://localhost:5173", "http://127.0.0.1:5173"]
_origins = [
    *_dev_origins,
    *[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()],
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def mirror_uid(request: Request, call_next):
    """
    X-User-Id 를 쿠키에 한 벌 적어 둔다. 위 uid() 의 짝이다.

    화면은 아무것도 안 해도 된다는 것이 이 미들웨어의 값이다. 이미 모든 API
    호출에 X-User-Id 를 싣고 있으니 (frontend-client/src/api.ts), 첫 호출의
    응답에 쿠키가 실려 오고 그 뒤로 <img src> 가 그걸 들고 간다.

    **이미 있는 쿠키와 같으면 다시 안 보낸다.** 화면이 300ms 마다 폴링하므로,
    이 검사를 빼면 Set-Cookie 가 초당 세 번씩 오간다.

    Secure 는 https 일 때만 켠다. localhost(http)에서 켜면 브라우저가 쿠키를
    아예 저장하지 않아 개발 중에 사진이 안 보이고, 원인이 눈에 안 띈다.

    **프록시 뒤에서는 scheme 이 http 로 보인다.** 터널이 TLS 를 끝내고 평문으로
    넘겨주기 때문이다. uvicorn 을 --proxy-headers 로 띄우면 X-Forwarded-Proto 를
    읽어 https 로 잡아 주지만, 그 옵션을 잊는 것이 흔한 사고라 PUBLIC_ORIGIN 이
    https 면 그것만으로도 켠다. COOKIE_SECURE=1 로 강제할 수도 있다.
    """
    response = await call_next(request)
    who = (request.headers.get("x-user-id") or "").strip()
    if who and UID_OK.match(who) and request.cookies.get(UID_COOKIE) != who:
        response.set_cookie(
            UID_COOKIE, who,
            max_age=30 * 24 * 3600, httponly=True, samesite="lax", path="/",
            secure=(env_flag("COOKIE_SECURE")
                    or PUBLIC_ORIGIN.startswith("https://")
                    or request.url.scheme == "https"))
    return response


# ---------------------------------------------------------------- 모델

class StartReq(BaseModel):
    title: str
    seed: str
    pace: str = "normal"          # fast(3초) / normal(5초) / slow(7초)
    # 0 = 제한 없음. 대화가 어디서 끝날지는 AI 의 close 판단이 정한다.
    # 양을 미리 묶고 싶은 쪽(시험 도구 등)이 값을 준다.
    max_turn: int = 0
    # 회차를 여는 사진. 없이도 연다 — 씨앗만으로 도는 것이 원래 길이다.
    photo_id: str | None = None


class SpeechReq(BaseModel):
    text: str


# ---------------------------------------------------------------- API
#
# 모든 엔드포인트가 같은 snapshot 한 덩어리를 돌려준다. 프론트는 타입이 하나면 되고
# (api.ts 의 Snapshot), 응답마다 무엇이 오는지 외울 필요가 없다.
#
# 상태를 바꾸는 것은 전부 _guard 를 지난다. 정의되지 않은 전이는 409 로 끊는다.


@app.get("/api/health")
async def health(request: Request):
    """
    살아 있는지 + 지금 CORS 가 무엇을 허용하는지.

    origins 를 굳이 실어 보내는 이유 — CORS 는 브라우저가 막는 것이라 서버 로그에
    아무것도 남지 않는다. .env 의 ALLOWED_ORIGINS 가 실제로 먹었는지 눈으로 볼 데가
    여기 말고 없다. 터널 URL 을 넣었는데 이 값이 그대로면 .env 를 못 읽은 것이다.
    """
    return {
        "ok": True,
        # sessions 는 메모리에 남은 전부, live 는 그중 아직 안 닫힌 것.
        # 둘의 차가 계속 벌어지면 스윕이 안 돌고 있다는 뜻이다.
        "sessions": len(sc.all_sessions()),
        "live": len(sc.live_sessions()),
        "max_live": sc.max_live(),
        "rate_tracked": limits.counted(),
        "origins": _origins,
        # 배포 자세. 터널 너머에서 이 셋을 확인하면 「지금 어떻게 서 있는지」가 보인다.
        # client_ip 가 진짜 방문자 주소를 잡고 있는지 여기서 확인한다 — 집에서
        # 열어 보고 내 주소가 아니라 127.0.0.1 이 나오면 TRUST_PROXY 가 틀린 것이다.
        "public": PUBLIC_ORIGIN or None,
        "proxy": limits.proxy_mode(),
        "client_ip": limits.client_ip(request),
        # /docs 가 닫혔는지는 **주소로 확인할 수 없다.** 닫으면 그 경로가 사라지고,
        # 사라진 경로는 아래 SPA 캐치올이 받아 화면(index.html)을 200 으로 준다.
        # 스키마가 나가지는 않지만 눈으로는 「열려 있는 것」과 구별이 안 된다.
        "docs": bool(_docs),
    }


@app.post("/api/sessions")
async def create_session(req: StartReq, request: Request,
                         x_user_id: str = Header(default=ANON_USER)):
    """
    회차를 연다. 씨앗이 0번 조각이 되고, 첫 질문을 든 SPEAKING 상태로 시작한다.

    X-User-Id 는 받아만 두고 검사하지 않는다. 구글 로그인이 붙으면 여기서 토큰을 풀어
    user_id 를 얻는다 — 그때 고칠 곳이 이 인자 하나로 끝나도록 해 둔 것이다.

    여기만 _guard 를 지나지 않는다. 상태 머신이 이제 막 생겨 전이랄 게 없다.

    question_fn 을 **여기서** 꽂는다. SessionController 의 기본값은 fixed_questions 로
    두었다 — 그래야 tests/test_flow.py 가 네트워크도 API 키도 없이 돈다. 실제 Gemini 는
    앱을 띄울 때만 붙는다. 키가 없으면 gemini_question 이 알아서 고정 질문으로 돈다.

    **여는 자리에만 상한이 있다.** 인증이 없어서 이 라우트 하나가 요금과 메모리의
    유일한 입구다 — 회차가 열리면 그 뒤의 턴은 타이머가 알아서 돌고, 턴마다
    Gemini·Azure 호출이 나간다 (limits.py 참조).

    세 상한이 서로 다른 답을 내는 것은 일부러다. 화면이 어르신께 다르게 말해야
    한다 —

        429 너무 자주      「잠시 뒤에 다시 해 보세요」   시간이 지나면 풀린다
        429 이미 진행 중    「그 회차를 마치거나 중단해 주세요」  할 일이 있다
        503 서버가 꽉 찼다  「지금은 열 수 없습니다」      어르신 잘못이 아니다

    한 코드로 뭉치면 화면이 이 셋을 구분할 수 없고, 어르신은 자기가 무엇을 해야
    하는지 알 수 없게 된다.
    """
    try:
        limits.take(limits.client_ip(request))
    except limits.Rejected as e:
        raise HTTPException(429, str(e),
                            headers={"Retry-After": str(e.retry_after)}) from e

    if len(sc.live_sessions()) >= sc.max_live():
        # 어르신 잘못이 아니라 서버가 꽉 찬 것이다. ERROR 로 남긴다 —
        # 이 줄이 보이면 상한을 올릴 때가 아니라 왜 안 줄어드는지 볼 때다.
        log.error("동시 회차 상한 %d 에 닿았다 — 새 회차를 열지 않는다", sc.max_live())
        raise HTTPException(503, "지금은 회차를 열 수 없습니다. 잠시 뒤에 다시 시도해 주세요")

    # **user_id 가 아직 신원이 아니다.** 프론트가 모두에게 'dev-user' 를 보내므로
    # 이 검사를 그대로 켜면 「사용자당 3회차」가 아니라 「서버 전체 3회차」가 되어,
    # 네 번째 어르신이 회차를 열 수 없다. 그 실패는 화면에 「이미 진행 중인 회차가
    # 있습니다」로 나타나는데 그 어르신은 회차를 연 적이 없어, 원인을 찾기까지
    # 오래 걸리는 종류의 버그다. 로그인이 붙어 user_id 가 실제로 갈릴 때 이 검사가
    # 저절로 살아난다 — 그때 지울 것은 아래 조건 앞부분 하나다.
    if x_user_id != ANON_USER and sc.user_live(x_user_id) >= limits.user_cap():
        raise HTTPException(
            429, "이미 진행 중인 회차가 있습니다. 그 회차를 마치거나 중단해 주세요")

    ctl = sc.put(sc.SessionController(
        user_id=x_user_id, title=req.title, pace=req.pace, max_turn=req.max_turn,
        photo_id=req.photo_id, question_fn=gemini_question))
    await ctl.start(req.seed)
    return ctl.snapshot()


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """
    현재 상태. 프론트가 300ms 마다 때린다.

    폴링이 필요한 이유는 **서버가 타이머로 상태를 바꾸기 때문**이다. 버튼을 누를 때만
    갱신하면 T1·T2 가 만료되는 걸 화면이 영영 모른다. 4일차에 WebSocket 으로 바꿔도
    이 엔드포인트는 남는다 — 첫 진입 시 1회 조회에 쓴다.

    소유자 검사가 없다. session_id 만 알면 남의 조각이 보인다. 1주차 한정이고,
    로그인이 붙을 때 x_user_id 와 ctl.user_id 를 맞춰 막는다.
    """
    return _need(session_id).snapshot()


@app.post("/api/sessions/{session_id}/tts-done")
async def tts_done(session_id: str):
    """
    낭독이 끝났다(또는 어르신이 탭해서 끊었다) → 수음 시작. 여기서부터 T1 이 돈다.

    낭독이 끝나는 시각은 서버가 알 수 없어 프론트가 알려준다. 2주차에 TTS 가 붙어도
    마찬가지다 — 오디오를 끝까지 튼 쪽은 프론트다.
    """
    return await _guard(_need(session_id).tts_done())


@app.post("/api/sessions/{session_id}/speech")
async def speech(session_id: str, req: SpeechReq):
    """
    유효 발화 수신 → T1 리셋. 올 때마다 발화 확정이 3초씩 미뤄진다.

    오디오는 아래 `/speech/audio` 로 갔다. 이 텍스트 경로는 **남겨 둔다** —
    마이크도 키도 없이 FSM·타이머를 돌려볼 수 있어야 하고, tests/test_flow.py 가
    이 길로 돈다.
    """
    return await _guard(_need(session_id).speech(req.text))


@app.post("/api/sessions/{session_id}/speech/audio")
async def speech_audio(session_id: str, request: Request):
    """
    오디오 청크 수신 → T1 리셋. 위 `/speech` 의 오디오판이고 자리는 똑같다.

    본문은 오디오 바이트 그대로다. JSON 으로 감싸 base64 로 넣지 않는다 —
    3분의 4로 부푸는 데다 폰 쪽에서 인코딩 비용까지 든다. mime 은
    Content-Type 헤더로 받는다 (사파리는 audio/mp4, 크롬은 audio/webm).

    **소리가 있는 청크만 올리는 것은 프론트의 몫이다.** 무음까지 올라오면 T1 이
    영원히 리셋되어 발화가 확정되지 않는다. 서버는 「아무것도 안 왔다」를 무음으로
    읽는다 — T1 이 이미 그 정의다.

    전사는 여기서 하지 않는다. 청크마다 부르면 회차당 수십 번이 되고, 무엇보다
    말이 잘린 조각을 전사하면 정확도가 떨어진다. 발화가 확정되는 순간
    (controller._confirm) 모아서 한 번에 보낸다.
    """
    data = await request.body()
    mime = request.headers.get("content-type") or "audio/webm"
    return await _guard(_need(session_id).audio_chunk(data, mime))


@app.get("/api/sessions/{session_id}/question/audio")
async def question_audio(session_id: str):
    """
    지금 질문을 읽은 mp3. 아직 합성 중이면 잠깐 기다렸다가 준다.

    **소리가 없으면 204 다. 404 도 500 도 아니다.** 「질문은 있는데 소리는
    없다」는 정상 상태이고, 화면은 글자를 띄운 채 「낭독 끝」 버튼으로 넘어간다.
    오류로 만들면 화면이 그걸 실패로 그려서, 소리가 안 나는 것과 회차가 끊긴
    것을 어르신이 구분할 수 없게 된다.

    합성 자체는 여기서 시작하지 않는다. 질문이 준비되는 순간(controller._speak)
    이미 걸려서 T2 안에서 돌고 있다. 여기는 받아 가는 자리일 뿐이다.
    """
    audio = await _need(session_id).question_audio()
    if not audio:
        return Response(status_code=204)
    return Response(content=audio, media_type="audio/mpeg",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/sessions/{session_id}/done")
async def done(session_id: str):
    """
    「다 말했어요」 — T1·T2 를 둘 다 건너뛰고 즉시 확정한다.

    **지연이 그대로 드러나는 유일한 경로다.** 평소엔 질문 생성이 T2(3~7초) 안에 숨지만
    이 버튼에는 숨을 곳이 없다. NFR-PF-001 을 잴 때 여기를 본다.
    """
    return await _guard(_need(session_id).done_button())


@app.post("/api/sessions/{session_id}/abort")
async def abort(session_id: str):
    """
    사용자 중단. 타이머를 모두 끄고 대기 중인 질문 생성 태스크도 취소한 뒤 CLOSED 로 간다.

    ABORT 만은 전이표를 거치지 않는다 — machine.fire 가 accepts() 검사보다 **먼저**
    처리한다. 그래서 이미 CLOSED 인 세션에 또 걸어도 409 가 아니라 200 이 나간다.
    「정의되지 않은 전이는 409」 원칙의 유일한 예외다. 중단을 두 번 눌러도 결과가 같은
    건 맞지만, 의도한 설계인지는 확인이 필요하다.
    """
    return await _guard(_need(session_id).abort())


@app.get("/api/sessions/{session_id}/latency")
async def latency(session_id: str):
    """
    FR-AD-314 — 구간별 지연(저장 · 질문 · 전달)과 타이머 격발 오차.

    snapshot 에 넣지 않고 따로 뺐다. 300ms 폴링마다 실어 보낼 것이 아니고, 볼 때는
    회차가 끝난 뒤 한 번에 몰아서 본다.

    turns 에는 **마지막 턴이 빠진다.** 회차를 닫는 턴은 다음 질문을 내보내지 않아
    잴 구간 자체가 없다 — AI 가 close 를 고른 턴, 그리고 턴 제한을 둔 회차에서
    최대 턴에 닿은 턴이 그렇다.

    **이 숫자는 localhost 에서만 의미가 있다.** 터널을 끼면 왕복이 섞여 우리 코드가
    느린 건지 릴레이가 느린 건지 가릴 수 없다.
    """
    ctl = _need(session_id)
    return {
        "turns": ctl.latencies,
        "timer_drift": ctl.timers.drift_report(),
        "fires": [{"name": f.name, "drift_ms": round(f.drift_ms, 1)} for f in ctl.timers.fires],
    }


# ---------------------------------------------------------------- 읽기
#
# 여기까지가 「지금 도는 회차」였다. 아래는 **끝난 회차를 다시 꺼내는** 경로다.
#
# 둘은 다른 자료를 본다. 위는 메모리의 SessionController 를, 아래는 DB 를 본다.
# 그래서 서버를 재시작하면 위는 404 가 되고 아래는 그대로 남는다.
#
# 일부러 합치지 않았다. 재시작 뒤에 조각을 **보는** 것과 회차를 **이어서 하는**
# 것은 전혀 다른 일이다. 이어 하려면 상태 머신과 타이머까지 되살려야 하는데,
# 서버가 내려간 동안 어르신 쪽 화면도 이미 멈춰 있었다. 그 상태로 T1 을 다시
# 거는 건 위험하다. 지금은 보는 것까지만 한다.


@app.get("/api/sessions")
async def list_sessions(limit: int = 20, x_user_id: str = Header(default="dev-user")):
    """
    지난 회차 목록. 최근 순.

    DB 를 못 읽으면 **빈 목록이 아니라 503 이다.** 빈 목록을 주면 화면에
    「기록이 없습니다」가 뜨고, 그건 어르신에게 조각이 사라졌다는 말이 된다.
    없는 것과 못 읽은 것은 다른 사건이라 화면도 다르게 말해야 한다.
    """
    return {"sessions": await _read(store.list_sessions(x_user_id, _limit(limit)))}


@app.get("/api/sessions/{session_id}/record")
async def session_record(session_id: str, x_user_id: str = Header(default="dev-user")):
    """
    저장된 회차 하나. 조각·근거(FR-IV-006)·구간별 지연(FR-AD-314)까지 전부.

    `/api/sessions/{id}` 와 헷갈리기 쉬운데 보는 자료가 다르다.
    위는 메모리라 진행 중에만 있고, 여기는 DB 라 끝난 뒤에도 남는다.

    **여기는 소유자를 확인한다.** 남의 것이면 403 이 아니라 404 로 답한다 —
    403 은 「있긴 있다」를 알려주는 셈이라 id 를 넣어 보며 존재를 확인할 수 있다.
    다만 지금은 X-User-Id 를 그대로 믿으므로 실제로 막아 주지는 못한다.
    헤더를 바꾸면 통과한다. 로그인이 붙으면 이 줄이 그대로 실효를 가진다.
    """
    rec = await _read(store.load_session(session_id))
    if rec is None or rec["user_id"] != x_user_id:
        raise HTTPException(404, "회차를 찾을 수 없습니다")
    return rec


# ---------------------------------------------------------------- 사진
#
# 사진은 **언제나 이 서버를 지나서** 나간다. 스토리지 주소를 화면에 주지 않는
# 이유는 photostore.py 머리에 적어 두었다 — 주소를 아는 사람은 누구나 보게 되고,
# 사진은 얼굴이다.


@app.post("/api/photos")
async def upload_photo(request: Request, session_id: str | None = None):
    """
    사진 한 장. 본문은 **바이트 그대로**다 (`/speech/audio` 와 같은 모양).

    JSON 에 base64 로 감싸지 않는다 — 3분의 4로 부풀고 폰에서 인코딩 비용까지
    든다. 형식은 Content-Type 이 아니라 **앞머리 바이트로** 가린다 (photo.sniff).

    돌려주는 `url` 은 **이 서버의 경로**다. 팀 문서의 「저장 주소(URL)가 있어야
    사진 분석 AI 가 그 사진을 볼 수 있다」와 다른데, 우리 구조에서는 분석
    에이전트가 서버 안에서 돌고 바이트를 저장소에서 직접 읽어 Gemini 에 인라인으로
    싣기 때문이다. 밖에서 닿는 주소가 필요한 쪽은 브라우저뿐이고, 브라우저에는
    이 경로가 그 역할을 한다.

    `session_id` 는 선택이다 — 어르신이 회차를 열기 전에 사진을 고를 수 있어야
    한다. 그래서 photo.session_id 가 NULL 을 허용하고, 읽을 때의 주인은 회차가
    아니라 photo.user_id 가 정한다 (002 마이그레이션 주석 참조).
    """
    who = uid(request)
    data = await _body_capped(request, photostore.max_bytes())

    if session_id:
        # 남의 회차에 내 사진을 달아 두지 못하게 막는다. 메모리에 없는 회차는
        # 지나간다 — 읽기 권한은 photo.user_id 가 정하므로 해가 없다.
        live = sc.get(session_id)
        if live is not None and live.user_id != who:
            raise HTTPException(404, "회차를 찾을 수 없습니다")

    try:
        prepared = await photo.prepare(data)
    except photo.PhotoRejected as e:
        # 400 이다. 어르신이 다른 사진을 고르면 되는 실패라 화면이 그렇게 말해야
        # 한다 — 500 으로 만들면 「서버가 고장났다」로 보인다.
        raise HTTPException(400, str(e)) from e

    try:
        rec = await photo.save(prepared, user_id=who, session_id=session_id)
    except (store.StoreUnavailable, photostore.PhotoStoreError) as e:
        raise HTTPException(503, "지금은 사진을 저장하지 못했습니다") from e

    # §2 분석을 여기서 걸어 둔다 — 회차가 열릴 때 단서가 이미 있게 한다.
    # 기다리지 않으므로 응답 시간은 그대로다 (photo.analyze_later 참조).
    photo.analyze_later(rec)

    return {
        "photo_id": rec["photo_id"],
        "url": f"/api/photos/{rec['photo_id']}",
        "mime": rec["mime"],
        "width": rec["width"],
        "height": rec["height"],
        "bytes": rec["bytes"],
    }


@app.get("/api/photos/{photo_id}")
async def get_photo(photo_id: str, request: Request):
    """
    사진 바이트. `<img src>` 가 직접 물어 오는 자리다.

    **남의 것이면 403 이 아니라 404 다.** /record 와 같은 이유다 — 403 은
    「있긴 있다」를 알려주는 셈이라 id 를 넣어 보며 존재를 확인할 수 있다.

    ETag 를 붙이는 것은 인심이 아니다. 어르신이 카드를 오갈 때마다 200KB 를
    다시 보내면 폰의 데이터와 배터리를 쓴다. photo_id 가 가리키는 바이트는
    바뀌지 않으므로 304 가 항상 옳다.
    """
    rec = await _read(store.load_photo(photo_id))
    if rec is None or rec["user_id"] != uid(request):
        raise HTTPException(404, "사진을 찾을 수 없습니다")
    if rec["status"] != "stored":
        # 행은 있는데 아직 바이트가 없다. 지금 흐름에서는 생기지 않지만,
        # 「없다」와 섞어 404 로 답하면 나중에 두 단계 저장을 넣을 때 구분이
        # 사라진다.
        raise HTTPException(409, "사진이 아직 저장되지 않았습니다")

    etag = f'"{(rec["sha256"] or rec["photo_id"])[:32]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    try:
        data = await photostore.current().get(rec["storage_key"])
    except photostore.PhotoMissing as e:
        # 행은 있고 바이트가 없다. photo.save 의 순서(바이트 먼저) 때문에
        # 정상 흐름에서는 생길 수 없다 — 생겼다면 저장소에서 지워진 것이다.
        log.error("사진 바이트가 없다 %s key=%s", photo_id, rec["storage_key"])
        raise HTTPException(404, "사진을 찾을 수 없습니다") from e
    except photostore.PhotoStoreError as e:
        raise HTTPException(503, "지금은 사진을 불러오지 못했습니다") from e

    return Response(
        content=data, media_type=rec["mime"],
        headers={
            # private — 중간 캐시가 남의 사진을 들고 있게 두지 않는다.
            "Cache-Control": f"private, max-age={photo.cache_seconds()}",
            "ETag": etag,
        })


# ---------------------------------------------------------------- 보조

async def _body_capped(request: Request, cap: int) -> bytes:
    """
    본문을 상한까지만 읽는다. 넘으면 413 으로 **끊는다.**

    `await request.body()` 를 쓰지 않는 이유 — 그건 본문을 전부 메모리에 올린
    뒤에 돌려준다. 200MB 를 보내면 200MB 를 다 받고 나서 거절하게 되고, 동시에
    몇 개만 와도 프로세스가 죽는다. (오디오 라우트가 아직 그 모양이다 —
    MAX_AUDIO_BYTES 검사가 본문을 다 읽은 뒤에 있다. 따로 고쳐야 한다.)

    Content-Length 를 먼저 보는 것은 **거절을 싸게 하려는 것뿐이다.** 그 값은
    보내는 쪽이 정하므로 믿고 끝낼 수 없다. 아래 누적 검사가 진짜 상한이다.
    """
    declared = request.headers.get("content-length") or ""
    mb = cap // (1024 * 1024)
    if declared.isdigit() and int(declared) > cap:
        raise HTTPException(413, f"{mb}MB 이하로 올려 주세요")

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > cap:
            raise HTTPException(413, f"{mb}MB 이하로 올려 주세요")
        chunks.append(chunk)
    return b"".join(chunks)


def _need(session_id: str) -> sc.SessionController:
    ctl = sc.get(session_id)
    if ctl is None:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    return ctl


async def _guard(coro):
    try:
        return await coro
    except TransitionError as e:
        raise HTTPException(409, str(e)) from e     # 조용히 넘기지 않는다


def _limit(n: int) -> int:
    """목록 크기를 묶는다. limit=100000 하나로 DB 를 훑게 두지 않는다."""
    return max(1, min(n, 100))


async def _read(coro):
    """
    읽기 실패를 503 으로 올린다. **빈 결과로 바꾸지 않는다.**

    store 의 쓰기 함수들은 실패를 삼킨다 — 인터뷰가 끊기면 안 되기 때문이다.
    읽기는 반대다. 조용히 빈 값을 주면 화면이 「기록이 없습니다」라고 말하게
    되고, 그건 있는 조각을 없다고 하는 것이다. 503 이면 화면이 「지금은 못
    불러옵니다」라고 다르게 말할 수 있다.
    """
    try:
        return await coro
    except store.StoreUnavailable as e:
        raise HTTPException(503, str(e)) from e


# ---------------------------------------------------------------- 프론트 서빙 (선택)
# frontend-client 를 빌드해 web/ 에 넣으면 이 서버가 직접 내보낸다.
# 실기기 확인 때 터널을 하나만 열면 되고, 같은 출처라 CORS 도 필요 없다.
# 반드시 API 라우트 **뒤에** 마운트한다 — 앞에 두면 /api 까지 삼킨다.

_web = Path(__file__).resolve().parents[1] / "web"
if (_web / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_web / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """
        SPA 라우팅 — 어떤 경로로 들어와도 index.html 을 돌려준다.

        단 /api 로 시작하는데 위에서 안 걸린 것은 **없는 API 경로**다.
        여기서 index.html 을 주면 프론트는 JSON 을 기대하다가 HTML 을 받고,
        "JSON 파싱 실패"라는 엉뚱한 오류로 원인을 찾게 된다. 404 로 끊는다.
        """
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, "없는 API 경로입니다")
        return FileResponse(_web / "index.html")
