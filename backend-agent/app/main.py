"""
기억의 조각 — Phase 1 API (backend-agent)

    uvicorn app.main:app --reload --port 8010
    http://127.0.0.1:8010/docs

1주차 범위 — 오디오 없음. 텍스트로 전 흐름을 돌린다.
신원은 구글 로그인 뒤 서버가 준 앱 세션 쿠키에서만 나온다 (session/auth.py).
인터뷰 링크로 들어온 사람은 `/api/i/*` 만 쓴다 (session/link.py).

화면은 frontend-client 저장소에 있다. 두 가지 방식으로 붙는다.
  개발     Vite 개발 서버(5173) → CORS 로 허용
  실기기   frontend 를 빌드해 web/ 에 넣으면 이 서버가 직접 서빙 (터널 하나로 끝)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.session import controller as sc
from app.session import auth, limits, link, memoir, photo, photostore, postcard, prompt, store, stt, tts, words
from app.session import style as styles
from app.session.conf import env_flag, env_int, env_str
from app.session.machine import State, TransitionError
from app.session.question import gemini_question, warmup

load_dotenv()
# MEMOIR_DB=supabase 면 .env.supabase 의 PG_* 가 .env 를 덮는다 (run.ps1 -Supabase).
if os.environ.get("MEMOIR_DB") == "supabase":
    load_dotenv(".env.supabase", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(name)-9s %(message)s",
    datefmt="%H:%M:%S")

log = logging.getLogger("api")

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


def _secure(request: Request) -> bool:
    """
    쿠키에 Secure 를 붙일지. https 일 때만 켠다 — localhost(http)에서 켜면 브라우저가
    쿠키를 아예 저장하지 않아 로그인이 안 되고, 원인이 눈에 안 띈다.

    **프록시 뒤에서는 scheme 이 http 로 보인다.** 터널이 TLS 를 끝내고 평문으로
    넘겨주기 때문이다. 그래서 PUBLIC_ORIGIN 이 https 면 그것만으로도 켠다.
    COOKIE_SECURE=1 로 강제할 수도 있다.
    """
    return (env_flag("COOKIE_SECURE") or PUBLIC_ORIGIN.startswith("https://")
            or request.url.scheme == "https")


_SAFE = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    """
    상태를 바꾸는 요청은 **허용한 출처에서 온 것만** 받는다 (요청 위조 방지).

    로그인이 쿠키라서, 다른 사이트가 숨긴 폼으로 우리 API 에 POST 를 보내면
    브라우저가 쿠키를 실어 줄 수 있다. SameSite=Lax 가 대부분 막지만 한 겹 더 둔다.
    브라우저는 POST 에 Origin 을 반드시 싣는다. Origin 이 없는 요청(curl · 시험)은
    쿠키를 들고 있지 않은 한 신원이 없으니 지나가도 해가 없다.
    """
    origin = request.headers.get("origin")
    if (request.method not in _SAFE and origin and request.url.path.startswith("/api/")
            and origin not in _origins and origin != PUBLIC_ORIGIN
            and origin != f"{request.url.scheme}://{request.url.netloc}"):
        log.warning("다른 출처의 쓰기 요청을 거절 %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "허용하지 않은 곳에서 온 요청이에요", "code": "bad_origin"},
                            status_code=403)
    return await call_next(request)


@app.exception_handler(auth.AuthError)
async def _auth_error(request: Request, e: auth.AuthError):
    res = JSONResponse({"detail": e.detail, "code": e.code}, status_code=e.status)
    if e.code == "session_expired":
        res.delete_cookie(auth.COOKIE, path="/")
    return res


# ---------------------------------------------------------------- 모델

class StartReq(BaseModel):
    title: str
    # 가족이 적은 설명. **어르신의 말씀이 아니다** — 0번 조각에 남지만 대화 기록에
    # 「어르신:」으로 실리지 않고 [시작 자료]로 따로 간다 (question._start_material).
    seed: str = ""
    # 시작 자료 (C1). 가족이 고른 테마와 구체 주제 하나. 둘 다 없어도 연다 —
    # 지금 화면은 seed 만 보낸다. 모르는 테마·너무 긴 주제는 422 로 돌려보낸다.
    theme: Literal["family", "self", "hobby"] | None = None
    topic: str = Field("", max_length=100)
    pace: str = "normal"          # fast(3초) / normal(5초) / slow(7초)
    # 0 = 제한 없음. 대화가 어디서 끝날지는 AI 의 close 판단이 정한다.
    # 양을 미리 묶고 싶은 쪽(시험 도구 등)이 값을 준다.
    max_turn: int = 0
    # 회차를 여는 사진. 없이도 연다 — 씨앗만으로 도는 것이 원래 길이다.
    photo_id: str | None = None
    # 누구의 이야기인가 (「누구의 이야기를 남길까요?」 에서 고른 화자). 이 자녀의 화자여야 한다.
    # 지금은 없어도 연다 — 화면이 보내기 전까지. 없으면 화자 미지정 회차가 된다.
    elder_id: str | None = Field(None, max_length=64)


class ElderAssignReq(BaseModel):
    elder_id: str = Field(..., min_length=1, max_length=64)


class SpeechReq(BaseModel):
    text: str


class GoogleLoginReq(BaseModel):
    # Google Identity Services 콜백이 준 ID 토큰 (credential) 그대로.
    credential: str = Field(..., max_length=4096)


class ElderReq(BaseModel):
    # 「누구의 이야기를 남길까요?」에 적은 이름. 상세 프로필은 받지 않는다.
    name: str = Field(..., min_length=1, max_length=40)


class LinkStartReq(BaseModel):
    # 어르신이 낱말 카드에서 고른 낱말. 없으면 링크의 구체 주제로 연다 (예전 화면은 본문이 없다).
    # 허용 목록(app/session/words.py)에 없으면 422 — 길이는 그 앞에서 한 번 더 자른다.
    topic: str | None = Field(None, max_length=60)


class LinkReq(BaseModel):
    # 링크로 진행할 회차의 준비. StartReq 의 같은 이름 칸과 뜻이 같다.
    elder_id: str = Field(..., max_length=64)
    title: str = Field("", max_length=100)
    seed: str = Field("", max_length=4000)
    theme: Literal["family", "self", "hobby"] | None = None
    topic: str = Field("", max_length=100)
    photo_id: str | None = Field(None, max_length=64)


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


# ---------------------------------------------------------------- 로그인
#
# 화면은 user.name · elders[].name 으로 그린다. 이메일은 「누구로 로그인했는지」
# 보여 주는 데만 쓰고 식별에 쓰지 않는다.

def _me(login: dict, elders: list[dict]) -> dict:
    return {
        "user": {"user_id": login["user_id"], "name": login.get("name") or "",
                 "email": login.get("email") or ""},
        "elders": [{"elder_id": e["elder_id"], "name": e["display_name"]} for e in elders],
    }


async def _elders(user_id: str) -> list[dict]:
    try:
        return await store.list_elders(user_id)
    except store.StoreUnavailable as e:
        raise auth.AuthError(503, "auth_unavailable", "지금은 로그인을 확인할 수 없어요") from e


@app.post("/api/auth/google")
async def auth_google(req: GoogleLoginReq, request: Request):
    """
    구글 ID 토큰 → 앱 세션 쿠키. 토큰은 검증에만 쓰고 저장하지 않는다.

    **DB 가 없으면 로그인할 수 없다 (503).** 로그인을 기록하지 못하면 끊을 수도
    없기 때문이다. 메모리 전용으로 뜬 개발 서버는 로그인 화면에서 멈춘다.
    """
    claims = await auth.verify_google(req.credential)
    try:
        user_id, raw = await auth.login(claims)
        elders = await store.list_elders(user_id)
    except store.StoreUnavailable as e:
        raise auth.AuthError(503, "auth_unavailable", "지금은 로그인할 수 없어요") from e
    res = JSONResponse(_me({"user_id": user_id, "name": claims.get("name"),
                            "email": claims.get("email")}, elders))
    res.set_cookie(auth.COOKIE, raw, max_age=auth.max_hours() * 3600,
                   httponly=True, samesite="lax", path="/", secure=_secure(request))
    return res


@app.get("/api/auth/me")
async def auth_me(login: dict = Depends(auth.current_login)):
    """지금 누구로 로그인했는지. 앱을 열 때 한 번 부른다. 401 이면 로그인 화면이다."""
    return _me(login, await _elders(login["user_id"]))


@app.post("/api/auth/logout", status_code=204)
async def auth_logout(request: Request):
    """
    로그아웃. **쿠키가 없어도, 이미 끝난 로그인이어도 204 다** — 누른 결과는 같다.
    서버 표에 끝났다고 적으므로, 옛 쿠키를 들고 다시 와도 401 이다.
    """
    try:
        await auth.logout(request.cookies.get(auth.COOKIE))
    except store.StoreUnavailable as e:
        raise auth.AuthError(503, "auth_unavailable", "지금은 로그아웃할 수 없어요") from e
    res = Response(status_code=204)
    res.delete_cookie(auth.COOKIE, path="/")
    return res


@app.post("/api/elders", status_code=201)
async def create_elder(req: ElderReq, who: str = Depends(auth.current_user)):
    """
    화자(이야기의 주인공) 하나를 만든다. 첫 로그인에 화자가 없을 때 부른다.

    **이름이 같은 화자를 찾아 붙이지 않는다.** 같은 이름의 다른 분일 수 있다.
    부를 때마다 새 화자다 — 화면이 두 번 보내지 않게 막는다.
    """
    name = req.name.strip()
    if not name:
        raise HTTPException(422, "이름을 적어 주세요")
    try:
        e = await store.create_elder(who, name)
    except store.StoreUnavailable as err:
        raise HTTPException(503, "지금은 저장할 수 없어요") from err
    return {"elder_id": e["elder_id"], "name": e["display_name"]}


@app.post("/api/sessions")
async def create_session(req: StartReq, request: Request,
                         who: str = Depends(auth.current_user)):
    """
    회차를 연다. 씨앗이 0번 조각이 되고, 첫 질문을 든 SPEAKING 상태로 시작한다.

    로그인한 자녀만 연다 (auth.current_user).

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
    _open_checks(request, who)
    if req.elder_id and not await link.read(store.owns_elder(who, req.elder_id)):
        raise HTTPException(404, "화자를 찾을 수 없어요")

    ctl = sc.put(sc.SessionController(
        user_id=who, title=req.title, pace=req.pace, max_turn=req.max_turn,
        photo_id=req.photo_id, theme=req.theme, topic=req.topic.strip(),
        elder_id=req.elder_id,
        question_fn=gemini_question, closed_fn=postcard.on_closed))
    await ctl.start(req.seed)
    if not req.elder_id:
        # 필수로 바꾸기 전에 빠진 채 들어오는 화면이 남았는지 본다 (v0.42 부터 늘 보낸다)
        log.info("회차 %s 화자 없이 시작", ctl.session_id[:8])
    return ctl.snapshot()


def _open_checks(request: Request, who: str) -> None:
    """회차를 여는 두 입구(/api/sessions · /api/i/start)가 같은 상한을 지난다."""
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

    if sc.user_live(who) >= limits.user_cap():
        raise HTTPException(
            429, "이미 진행 중인 회차가 있습니다. 그 회차를 마치거나 중단해 주세요")


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, who: str = Depends(auth.current_user)):
    """
    현재 상태. 프론트가 300ms 마다 때린다.

    폴링이 필요한 이유는 **서버가 타이머로 상태를 바꾸기 때문**이다. 버튼을 누를 때만
    갱신하면 T1·T2 가 만료되는 걸 화면이 영영 모른다. 4일차에 WebSocket 으로 바꿔도
    이 엔드포인트는 남는다 — 첫 진입 시 1회 조회에 쓴다.

    남의 회차면 404 다 (_mine). 이 아래 진행 라우트가 전부 같다.
    """
    return _mine(session_id, who).snapshot()


@app.post("/api/sessions/{session_id}/tts-done")
async def tts_done(session_id: str, who: str = Depends(auth.current_user)):
    """
    낭독이 끝났다(또는 어르신이 탭해서 끊었다) → 수음 시작. 여기서부터 T1 이 돈다.

    낭독이 끝나는 시각은 서버가 알 수 없어 프론트가 알려준다. 2주차에 TTS 가 붙어도
    마찬가지다 — 오디오를 끝까지 튼 쪽은 프론트다.
    """
    return await _guard(_mine(session_id, who).tts_done())


@app.post("/api/sessions/{session_id}/speech")
async def speech(session_id: str, req: SpeechReq, who: str = Depends(auth.current_user)):
    """
    유효 발화 수신 → T1 리셋. 올 때마다 발화 확정이 3초씩 미뤄진다.

    오디오는 아래 `/speech/audio` 로 갔다. 이 텍스트 경로는 **남겨 둔다** —
    마이크도 키도 없이 FSM·타이머를 돌려볼 수 있어야 하고, tests/test_flow.py 가
    이 길로 돈다.
    """
    return await _guard(_mine(session_id, who).speech(req.text))


@app.post("/api/sessions/{session_id}/speech/audio")
async def speech_audio(session_id: str, request: Request, who: str = Depends(auth.current_user)):
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
    return await _chunk(_mine(session_id, who), request)


async def _chunk(ctl: sc.SessionController, request: Request):
    data = await request.body()
    mime = request.headers.get("content-type") or "audio/webm"
    return await _guard(ctl.audio_chunk(data, mime))


@app.get("/api/sessions/{session_id}/question/audio")
async def question_audio(session_id: str, who: str = Depends(auth.current_user)):
    """
    지금 질문을 읽은 mp3. 아직 합성 중이면 잠깐 기다렸다가 준다.

    **소리가 없으면 204 다. 404 도 500 도 아니다.** 「질문은 있는데 소리는
    없다」는 정상 상태이고, 화면은 글자를 띄운 채 「낭독 끝」 버튼으로 넘어간다.
    오류로 만들면 화면이 그걸 실패로 그려서, 소리가 안 나는 것과 회차가 끊긴
    것을 어르신이 구분할 수 없게 된다.

    합성 자체는 여기서 시작하지 않는다. 질문이 준비되는 순간(controller._speak)
    이미 걸려서 T2 안에서 돌고 있다. 여기는 받아 가는 자리일 뿐이다.
    """
    return await _question_audio(_mine(session_id, who))


async def _question_audio(ctl: sc.SessionController) -> Response:
    audio = await ctl.question_audio()
    if not audio:
        return Response(status_code=204)
    # Gemini 갈래는 wav 를 준다 (tts.py). 형식을 앞머리로 가린다 — 사파리는
    # mime 이 틀리면 재생을 거부한다.
    mime = "audio/wav" if audio[:4] == b"RIFF" else "audio/mpeg"
    return Response(content=audio, media_type=mime,
                    headers={"Cache-Control": "no-store"})


@app.get("/api/sessions/{session_id}/question/stream")
async def question_stream(session_id: str, who: str = Depends(auth.current_user)):
    """
    지금 질문의 낭독을 **조각으로 흘려보낸다.** 날 PCM 16비트 모노 —
    rate 는 Content-Type 에 실린다. 스냅샷의 question_audio_stream 이 참일 때
    화면이 여기로 온다 (TTS_STREAM=1).

    **첫 소리가 올 때까지는 머리를 보내지 않는다.** 그래야 소리 없이 끝난
    경우에 위 /question/audio 와 똑같이 204 로 말할 수 있다. 한번 200 을
    보내면 「소리가 없다」를 알릴 길이 빈 본문뿐이다.

    합성은 여기서 시작하지 않는다. 질문이 준비되는 순간(controller._speak)
    이미 걸려서 조각이 쌓이고 있다. 늦게 온 요청은 쌓인 것부터 받는다.

    **중간 프록시가 모아 보내면 스트리밍이 아니다.** X-Accel-Buffering 은
    nginx 계열에 「모으지 말라」는 표시다. 터널(Tailscale · Cloudflare)을
    거쳐서도 첫 소리가 당겨지는지는 화면 로그의 「첫 소리」 줄로 본다.
    """
    return await _question_stream(_mine(session_id, who))


async def _question_stream(ctl: sc.SessionController) -> Response:
    speech = ctl.question_speech()
    if speech is None or not await speech.wait_first(timeout=3.0):
        return Response(status_code=204)
    return StreamingResponse(
        speech.iter_chunks(),
        media_type=f"audio/L16;rate={speech.rate};channels=1",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no",
                 "X-Speech-Source": speech.source or "none"})


@app.post("/api/sessions/{session_id}/done")
async def done(session_id: str, who: str = Depends(auth.current_user)):
    """
    「다 말했어요」 — T1·T2 를 둘 다 건너뛰고 즉시 확정한다.

    **지연이 그대로 드러나는 유일한 경로다.** 평소엔 질문 생성이 T2(3~7초) 안에 숨지만
    이 버튼에는 숨을 곳이 없다. NFR-PF-001 을 잴 때 여기를 본다.
    """
    return await _guard(_mine(session_id, who).done_button())


@app.post("/api/sessions/{session_id}/abort")
async def abort(session_id: str, who: str = Depends(auth.current_user)):
    """
    사용자 중단. 타이머를 모두 끄고 대기 중인 질문 생성 태스크도 취소한 뒤 CLOSED 로 간다.

    ABORT 만은 전이표를 거치지 않는다 — machine.fire 가 accepts() 검사보다 **먼저**
    처리한다. 그래서 이미 CLOSED 인 세션에 또 걸어도 409 가 아니라 200 이 나간다.
    「정의되지 않은 전이는 409」 원칙의 유일한 예외다. 중단을 두 번 눌러도 결과가 같은
    건 맞지만, 의도한 설계인지는 확인이 필요하다.
    """
    return await _guard(_mine(session_id, who).abort())


@app.get("/api/sessions/{session_id}/latency")
async def latency(session_id: str, who: str = Depends(auth.current_user)):
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
    ctl = _mine(session_id, who)
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
async def list_sessions(limit: int = 20, has_postcard: bool = False,
                        elder_id: str | None = None,
                        who: str = Depends(auth.current_user)):
    """
    지난 회차 목록. 최근 순. 회차마다 has_postcard · postcard_title 을 싣는다.

    `?has_postcard=1` 이면 엽서가 있는 회차만 준다. `?elder_id=` 면 그 화자의 회차만.
    회차마다 elder_id 가 실린다 — None 이면 화자 미지정이다.

    DB 를 못 읽으면 **빈 목록이 아니라 503 이다.** 빈 목록을 주면 화면에
    「기록이 없습니다」가 뜨고, 그건 어르신에게 조각이 사라졌다는 말이 된다.
    없는 것과 못 읽은 것은 다른 사건이라 화면도 다르게 말해야 한다.
    """
    return {"sessions": await _read(store.list_sessions(who, _limit(limit), has_postcard, elder_id))}


@app.put("/api/sessions/{session_id}/elder")
async def assign_elder(session_id: str, req: ElderAssignReq,
                       who: str = Depends(auth.current_user)):
    """
    화자 미지정 회차에 화자를 정한다. 자서전에 넣기 전에 자녀가 한 번 고른다.

    화자가 한 명뿐인 계정이어도 서버가 알아서 정하지 않는다 — 화면이 그 화자를
    미리 골라 보여 주고, 자녀가 확인하면 이 요청이 온다.

    남의 회차 · 남의 화자는 404, 이미 다른 화자로 정해진 회차는 409 elder_already_set.
    """
    got = await _read(store.assign_elder(session_id, who, req.elder_id))
    if got == "no_session":
        raise HTTPException(404, "회차를 찾을 수 없습니다")
    if got == "no_elder":
        raise HTTPException(404, "화자를 찾을 수 없어요")
    if got == "taken":
        return JSONResponse({"detail": "이미 다른 분의 이야기로 정해진 기록이에요.",
                             "code": "elder_already_set"}, status_code=409)
    return {"session_id": session_id, "elder_id": req.elder_id}


@app.get("/api/sessions/{session_id}/record")
async def session_record(session_id: str, who: str = Depends(auth.current_user)):
    """
    저장된 회차 하나. 조각·근거(FR-IV-006)·구간별 지연(FR-AD-314)까지 전부.

    `/api/sessions/{id}` 와 헷갈리기 쉬운데 보는 자료가 다르다.
    위는 메모리라 진행 중에만 있고, 여기는 DB 라 끝난 뒤에도 남는다.

    **여기는 소유자를 확인한다.** 남의 것이면 403 이 아니라 404 로 답한다 —
    403 은 「있긴 있다」를 알려주는 셈이라 id 를 넣어 보며 존재를 확인할 수 있다.
    """
    rec = await _read(store.load_session(session_id))
    if rec is None or rec["user_id"] != who:
        raise HTTPException(404, "회차를 찾을 수 없습니다")
    if rec["postcard"]:
        # 저장 키는 화면에 내보내지 않는다 (photostore.py 머리). 주소로 바꿔 준다.
        pc = rec["postcard"]
        pc["url"] = _postcard_url(session_id, pc)
        del pc["storage_key"]
    return rec


# ---------------------------------------------------------------- 사진
#
# 사진은 **언제나 이 서버를 지나서** 나간다. 스토리지 주소를 화면에 주지 않는
# 이유는 photostore.py 머리에 적어 두었다 — 주소를 아는 사람은 누구나 보게 되고,
# 사진은 얼굴이다.


@app.post("/api/photos")
async def upload_photo(request: Request, session_id: str | None = None,
                       who: str = Depends(auth.current_user)):
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
async def get_photo(photo_id: str, request: Request, who: str = Depends(auth.current_user)):
    """
    사진 바이트. `<img src>` 가 직접 물어 오는 자리다.

    **남의 것이면 403 이 아니라 404 다.** /record 와 같은 이유다 — 403 은
    「있긴 있다」를 알려주는 셈이라 id 를 넣어 보며 존재를 확인할 수 있다.

    ETag 를 붙이는 것은 인심이 아니다. 어르신이 카드를 오갈 때마다 200KB 를
    다시 보내면 폰의 데이터와 배터리를 쓴다. photo_id 가 가리키는 바이트는
    바뀌지 않으므로 304 가 항상 옳다.
    """
    rec = await _read(store.load_photo(photo_id))
    if rec is None or rec["user_id"] != who:
        raise HTTPException(404, "사진을 찾을 수 없습니다")
    return await _photo_bytes(rec, request)


async def _photo_bytes(rec: dict, request: Request) -> Response:
    """사진 한 장을 내보낸다. **주인 검사는 부르는 쪽이 이미 했다.**"""
    photo_id = rec["photo_id"]
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


# ---------------------------------------------------------------- 엽서
#
# 회차당 한 장이라 주소에 엽서 id 가 없다. 회차 id 가 곧 엽서의 주소다.
# 바이트는 사진과 같은 이유로 언제나 이 서버를 지나서 나간다.


@app.post("/api/sessions/{session_id}/postcard")
async def make_postcard(session_id: str, request: Request, who: str = Depends(auth.current_user)):
    """
    끝난 회차의 엽서를 굽는다. 이미 있으면 새로 구워 덮어쓴다.

    **기다리는 요청이다.** 카드 글을 쓰고 굽기가 끝나야 답이 간다 (수 초).
    폴링을 두지 않은 것은 누르는 사람이 결과를 보려고 누르는 것이기 때문이다 —
    화면은 그동안 「그리는 중」을 띄우면 된다.

    409 는 어르신이 다른 것을 하면 되는 경우(회차가 안 끝났다 · 말씀이 없다 ·
    이미 굽는 중 · 담을 말씀이 부족하다), 503 은 서버 쪽 사정이다. 화면이 둘을
    다르게 말해야 한다. 409 의 네 원인은 본문의 code 로 가른다.

    본문은 없어도 된다. 있으면 `{"style": ...}` 이고, 없으면 구어체다 (style.py).
    응답의 created_at 은 DB 가 찍은 값이다 — 화면은 busy 뒤에 이 값이 바뀌었는지로
    새 엽서를 알아본다 (4-C1 §6).
    """
    try:
        body = json.loads(await _body_capped(request, 1024) or b"{}")
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, "요청을 읽지 못했어요.")
    try:
        chosen = styles.pick(body.get("style"))
    except styles.UnsupportedStyle:
        return _unsupported_style()
    try:
        rec = await postcard.make(session_id, who, chosen)
    except LookupError as e:
        raise HTTPException(404, "회차를 찾을 수 없습니다") from e
    except postcard.PostcardNotReady as e:
        return JSONResponse({"detail": str(e), "code": e.code}, status_code=409)
    except postcard.PhotoUnavailable as e:
        # 다른 503 과 화면 안내가 다르다 — 「사진을 불러오지 못했어요. 다시 만들어 주세요」
        return JSONResponse({"detail": str(e), "code": e.code}, status_code=503)
    except postcard.PostcardUnavailable as e:
        raise HTTPException(503, str(e)) from e
    except store.StoreUnavailable as e:
        raise HTTPException(503, "지금은 엽서를 만들 수 없습니다") from e
    return {
        "url": _postcard_url(session_id, rec),
        "title": rec.get("title") or "",
        "text": rec["text"],
        "caption": rec.get("caption") or "",
        "width": rec["width"],
        "height": rec["height"],
        "bytes": rec["bytes"],
        "style": rec["style"],
        "created_at": rec["created_at"],
    }


def _unsupported_style() -> JSONResponse:
    """엽서 · 자서전이 같은 모양으로 거절한다. 400 의 다른 원인과는 code 로 갈린다."""
    return JSONResponse({"detail": styles.SAYS, "code": styles.CODE}, status_code=400)


@app.get("/api/sessions/{session_id}/postcard")
async def get_postcard(session_id: str, request: Request, who: str = Depends(auth.current_user)):
    """
    엽서 바이트. `<img src>` 가 직접 물어 오는 자리다. 로그인 쿠키가 같이 온다.

    ETag 는 저장 키다. 다시 구우면 키가 바뀌므로 옛 엽서가 304 로 남지 않는다.
    """
    rec = await _read(store.load_postcard(session_id))
    if rec is None or rec["user_id"] != who:
        raise HTTPException(404, "엽서를 찾을 수 없습니다")

    etag = f'"{postcard.version(rec["storage_key"])}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    try:
        data = await photostore.current().get(rec["storage_key"])
    except photostore.PhotoMissing as e:
        log.error("엽서 바이트가 없다 %s key=%s", session_id, rec["storage_key"])
        raise HTTPException(404, "엽서를 찾을 수 없습니다") from e
    except photostore.PhotoStoreError as e:
        raise HTTPException(503, "지금은 엽서를 불러오지 못했습니다") from e

    return Response(
        content=data, media_type=rec["mime"],
        headers={"Cache-Control": f"private, max-age={photo.cache_seconds()}",
                 "ETag": etag})


def _postcard_url(session_id: str, rec: dict) -> str:
    """
    엽서 주소. **키의 해시를 꼬리에 단다.** 주소가 같으면 브라우저가 max-age 동안
    묻지도 않고 옛 엽서를 보여 준다. 다시 구운 뒤에는 주소 자체가 달라야 한다.
    """
    return f"/api/sessions/{session_id}/postcard?v={postcard.version(rec['storage_key'])}"


# ---------------------------------------------------------------- 자서전
#
# 엽서가 있는 회차 3~5개를 골라 초안 하나를 받는다. 저장하지 않는다 — 다시 보려면
# 다시 만든다. 무엇을 하는지는 memoir.py 머리에 있다.

# 화면이 그대로 보여 주는 말이다 (해요체). 안쪽 사정은 로그에만 남긴다.
_MEMOIR_SAYS = {
    400: "선택한 엽서를 확인해 주세요. 3~5장을 고를 수 있어요.",
    404: "선택한 엽서를 찾을 수 없어요. 목록에서 다시 골라 주세요.",
    422: "선택한 엽서의 이야기 자료를 불러오지 못했어요.",
    502: "자서전을 만드는 중 문제가 생겼어요. 엽서 선택 화면으로 돌아가 주세요.",
    503: "지금은 자서전을 만들 수 없어요. 엽서 선택 화면으로 돌아가 주세요.",
    504: "정해진 시간 안에 자서전을 받지 못했어요. 엽서 선택 화면으로 돌아가 주세요.",
}
# code 는 화면이 HTTP 숫자보다 먼저 보는 갈래다. 모르는 code 면 화면은 숫자로 고른다.
# needs_confirmation · needs_context 는 화면이 나누지 않으므로 not_final 하나다.
_MEMOIR_STATUS = (
    (memoir.BadSelection, 400, None), (memoir.NotFound, 404, "not_found"),
    (memoir.SourceUnavailable, 422, "source_unavailable"),
    (memoir.GenerationTimeout, 504, "generation_timeout"),
    (memoir.GenerationFailed, 502, "invalid_model_output"), (memoir.NotFinal, 503, "not_final"),
)


@app.post("/api/memoirs/preview")
async def memoir_preview(request: Request, who: str = Depends(auth.current_user)):
    """
    고른 회차로 자서전 초안을 쓴다. **기다리는 요청이다** — 다 쓰거나 실패해야 답이 간다.

    본문은 `{"session_ids": [...], "style": ...}` 다. style 은 없으면 구어체다.
    누구의 요청인지는 로그인으로 안다.
    본문을 pydantic 으로 받지 않는 것은 모양이 틀렸을 때 FastAPI 가 422 를
    내기 때문이다 — 여기서 422 는 「자료를 못 읽었다」는 다른 뜻이다.

    자료 부족은 200 의 insufficient_material 이고 실패가 아니다. 실패는 상태 코드와
    `{"detail": 안내, "code": 갈래}` 로만 나간다. 둘을 서로 바꿔 내보내지 않는다.
    """
    try:
        body = json.loads(await _body_capped(request, 16 * 1024) or b"null")
    except ValueError:
        body = None
    ids = body.get("session_ids") if isinstance(body, dict) else None
    try:
        chosen = styles.pick(body.get("style") if isinstance(body, dict) else None)
    except styles.UnsupportedStyle:
        return _unsupported_style()
    try:
        return await memoir.preview(ids, who, chosen)
    except memoir.MemoirError as e:
        status, code = next((s, c) for kind, s, c in _MEMOIR_STATUS if isinstance(e, kind))
        code = code or e.code      # 400 은 갈래가 여럿이다 — bad_selection · mixed_speakers · speaker_unassigned
        log.warning("자서전 %d %s — %s", status, type(e).__name__, str(e)[:200])
        return JSONResponse({"detail": _MEMOIR_SAYS[status], "code": code}, status_code=status)


# ---------------------------------------------------------------- 인터뷰 링크 (자녀)
#
# 자녀가 회차를 준비해 링크를 받는다. 링크를 연 사람이 할 수 있는 일은 아래
# `/api/i/*` 에 있다. 무엇이 무엇을 보는지는 link.py 머리에 있다.

async def _my_link(link_id: str, who: str) -> dict:
    rec = await link.read(store.load_link(link_id))
    if rec is None or rec["user_id"] != who:
        raise HTTPException(404, "링크를 찾을 수 없어요")
    return rec


def _issued(rec: dict, raw: str) -> dict:
    """
    발급 응답. **토큰 원문은 여기서 한 번만 나간다** — 표에는 해시만 있어 다시 보여
    줄 수 없다. 잃어버리면 재발급한다.
    """
    return {**link.summary(rec), "token": raw, "url": f"{PUBLIC_ORIGIN}/i#{raw}"}


@app.post("/api/links", status_code=201)
async def create_link(req: LinkReq, who: str = Depends(auth.current_user)):
    """
    회차 준비 → 인터뷰 링크. 회차는 아직 열지 않는다 — 받은 사람이 「시작」을
    누를 때 열린다. 그래서 링크를 몇 번 열어 봐도 아무것도 소모되지 않는다.

    화자와 사진은 **이 자녀의 것이어야 한다.** 남의 것이면 404 다.
    """
    if not await link.read(store.owns_elder(who, req.elder_id)):
        raise HTTPException(404, "화자를 찾을 수 없어요")
    if req.photo_id:
        rec = await _read(store.load_photo(req.photo_id))
        if rec is None or rec["user_id"] != who:
            raise HTTPException(404, "사진을 찾을 수 없어요")
    topic = req.topic.strip()
    rec, raw = await link.issue(who, {
        "elder_id": req.elder_id, "title": req.title.strip() or topic or "인터뷰",
        "seed": req.seed, "theme": req.theme, "topic": topic, "photo_id": req.photo_id})
    return _issued(rec, raw)


@app.get("/api/links")
async def list_links(elder_id: str | None = None, limit: int = 20,
                     who: str = Depends(auth.current_user)):
    """내가 발급한 링크. 최근 순. 토큰은 싣지 않는다 (다시 보여 줄 수 없다)."""
    rows = await link.read(store.list_links(who, elder_id, _limit(limit)))
    return {"links": [link.summary(r) for r in rows]}


@app.post("/api/links/{link_id}/revoke")
async def revoke_link(link_id: str, who: str = Depends(auth.current_user)):
    """
    링크를 거둔다. 그 뒤로 링크의 모든 요청은 410 이다. 이미 거둔 링크도 200 이다.

    **진행 중이면 회차를 중단한다** (D4 — 자녀가 회수할 수 있다). 거두었는데 회차가
    계속 돌면 회수가 아니다. 이미 내려받은 소리 · 사진을 지운다고 약속하지는 않는다.
    """
    rec = await _my_link(link_id, who)
    await link.read(store.revoke_link(link_id))
    ctl = sc.get(rec["session_id"]) if rec["session_id"] else None
    if ctl is not None and ctl.machine.state is not State.CLOSED:
        await ctl.abort()
    log.info("링크 회수 %s", link_id)
    return link.summary({**rec, "revoked_at": rec["revoked_at"] or link.now()})


@app.post("/api/links/{link_id}/reissue", status_code=201)
async def reissue_link(link_id: str, who: str = Depends(auth.current_user)):
    """
    같은 준비로 새 링크. **이전 링크는 거둔다** (D4). 링크를 잃어버렸거나 기한이
    지났을 때 쓴다.

    시작한 링크는 다시 내지 않는다 (409 already_started) — 그 링크는 이미 회차 하나와
    묶였다. 새 인터뷰는 새로 준비한다.
    """
    old = await _my_link(link_id, who)
    if old["session_id"] is not None:
        return JSONResponse({"detail": "이미 시작한 인터뷰의 링크예요", "code": "already_started"},
                            status_code=409)
    await link.read(store.revoke_link(link_id))
    rec, raw = await link.issue(who, old)
    return _issued(rec, raw)


# ---------------------------------------------------------------- 인터뷰 링크 (받은 사람)
#
# **여기는 msid 를 읽지 않는다.** 링크 토큰(헤더)과 기기 쿠키(mlink)만 본다.
# 본문의 session_id · user_id 도 받지 않는다 — 회차는 링크가 정한다.
# 진행 라우트는 위 /api/sessions/{id}/... 와 같은 처리 함수를 부른다.

def _token(request: Request) -> str | None:
    return request.headers.get(link.HEADER)


@app.get("/api/i/preview")
async def link_preview(request: Request):
    """
    링크를 열었다. **아무것도 바꾸지 않는다** — 몇 번 열어도 같다.
    회수 · 만료는 410, 모르는 링크는 404 이고 준비 내용을 싣지 않는다.
    """
    rec = await link.by_token(_token(request))
    state = link.state_of(rec)
    link.gone(state)
    return link.view(rec, state)


@app.post("/api/i/start")
async def link_start(request: Request, body: LinkStartReq | None = None):
    """
    「시작」. 처음이면 회차를 열고 기기 쿠키를 준다. 응답은 진행 라우트와 같은
    snapshot 에 state · theme · topic · photo_url 을 더한 것이다.

    **한 링크는 한 회차다.** 같은 기기에서 다시 누르면 같은 회차를 돌려준다.
    쿠키 없이 다시 오면 (다른 기기 · 동시에 두 번 누름) 409 in_progress_elsewhere —
    회차가 둘 생기지 않는다 (link.starting · store.claim_link).

    상한은 /api/sessions 와 같다 (_open_checks). 회차를 여는 입구가 하나 더 생긴 것뿐이다.

    **낱말 카드** — 본문 { topic } 은 어르신이 고른 낱말이다. 허용 목록(카드 + 링크의 구체
    주제)에 있을 때만 그 낱말로 연다. 없으면 422 topic_not_allowed 이고 링크는 소모되지
    않는다. 이미 진행 중인 회차를 돌려줄 때는 보지 않는다 — 중간에 주제가 바뀌지 않는다.
    """
    rec = await link.by_token(_token(request))
    device = request.cookies.get(link.COOKIE)
    async with link.starting(rec["link_id"]):
        # 기다리는 동안 다른 요청이 시작했을 수 있다 — 잠근 뒤에 다시 읽는다.
        rec = await link.by_token(_token(request))
        state = link.state_of(rec)
        link.gone(state)
        if state in ("ended", "interrupted"):
            raise link.stuck(state)
        if state == "in_progress":
            if not link.device_matches(device, rec["device_hash"]):
                raise link.stuck("in_progress_elsewhere")
            return {**sc.get(rec["session_id"]).snapshot(), **link.view(rec, state)}

        picked = None
        if body and body.topic and body.topic.strip():
            picked = words.allowed(body.topic, rec["topic"])
            if picked is None:
                raise link.topic_not_allowed()
            if picked == rec["topic"]:
                picked = None               # 자녀가 적은 주제 그대로 — 고른 것이 없는 것과 같다

        _open_checks(request, rec["user_id"])
        session_id = str(uuid.uuid4())
        raw = await link.claim(rec, session_id, picked)
        if raw is None:
            # 이 프로세스 밖에서 먼저 묶였다 (DB 의 조건부 UPDATE 가 막았다).
            raise link.stuck("in_progress_elsewhere")
        ctl = sc.put(sc.SessionController(
            user_id=rec["user_id"], title=rec["title"], session_id=session_id,
            photo_id=rec["photo_id"], theme=rec["theme"], topic=picked or rec["topic"],
            elder_id=rec["elder_id"], question_fn=gemini_question, closed_fn=link.on_closed))
        # 다른 낱말을 고르셨으면 자녀의 시작 자료(seed)는 쓰지 않는다 — 다른 주제의 자료가
        # 0번 조각으로 들어가 질문을 그쪽으로 끌고 간다
        await ctl.start(picked if picked else rec["seed"])
    log.info("링크 %s → 회차 %s 시작", rec["link_id"], session_id[:8])
    res = JSONResponse(jsonable_encoder({**ctl.snapshot(), **link.view(rec, "in_progress")}))
    res.set_cookie(link.COOKIE, raw, max_age=link.DEVICE_HOURS * 3600, httponly=True,
                   samesite="lax", path=link.COOKIE_PATH, secure=_secure(request))
    return res


async def _link_session(request: Request) -> sc.SessionController:
    """
    진행 라우트의 회차. 기기 쿠키 → 링크 → 메모리의 회차.

    닫힌 회차도 메모리에 있는 동안은 돌려준다 — 화면이 마지막 상태(CLOSED)를 받아
    가야 한다. 닫힌 회차에 말을 보내면 상태 머신이 409 로 끊는다.
    **회수된 링크는 메모리에 회차가 있어도 410 이다.** 진행 중에는 기한을 보지 않는다 (D4).
    """
    rec = await link.by_device(request.cookies.get(link.COOKIE))
    state = link.state_of(rec)
    if state == "revoked":
        link.gone(state)
    ctl = sc.get(rec["session_id"]) if rec["session_id"] else None
    if ctl is not None:
        return ctl
    link.gone(state)
    raise link.stuck("ended" if state == "ended" else "interrupted")


@app.get("/api/i/session")
async def link_get(request: Request):
    return (await _link_session(request)).snapshot()


@app.post("/api/i/session/tts-done")
async def link_tts_done(request: Request):
    return await _guard((await _link_session(request)).tts_done())


@app.post("/api/i/session/speech")
async def link_speech(req: SpeechReq, request: Request):
    return await _guard((await _link_session(request)).speech(req.text))


@app.post("/api/i/session/speech/audio")
async def link_speech_audio(request: Request):
    return await _chunk(await _link_session(request), request)


@app.get("/api/i/session/question/audio")
async def link_question_audio(request: Request):
    return await _question_audio(await _link_session(request))


@app.get("/api/i/session/question/stream")
async def link_question_stream(request: Request):
    return await _question_stream(await _link_session(request))


@app.post("/api/i/session/done")
async def link_done(request: Request):
    return await _guard((await _link_session(request)).done_button())


@app.post("/api/i/session/abort")
async def link_abort(request: Request):
    return await _guard((await _link_session(request)).abort())


@app.get("/api/i/photo")
async def link_photo(request: Request):
    """
    링크에 지정된 보조 사진 한 장. 시작 전에는 토큰 헤더로 (화면이 받아 blob 으로
    띄운다), 시작한 뒤에는 기기 쿠키로 (`<img src>`) 받는다. 다른 사진에는 닿지 않는다.
    """
    token = _token(request)
    rec = await (link.by_token(token) if token
                 else link.by_device(request.cookies.get(link.COOKIE)))
    link.gone(link.state_of(rec))
    if not rec["photo_id"]:
        raise HTTPException(404, "사진을 찾을 수 없습니다")
    pic = await _read(store.load_photo(rec["photo_id"]))
    if pic is None or pic["user_id"] != rec["user_id"]:
        raise HTTPException(404, "사진을 찾을 수 없습니다")
    return await _photo_bytes(pic, request)


@app.get("/api/i/transcript")
async def link_transcript(request: Request):
    """
    끝난 인터뷰의 대화를 읽기 전용으로 (D6). 끝나기 전에는 409 not_ended.

    **그때 하신 말씀 그대로다.** 회차의 질문과 답만 싣는다. 0번 조각(자녀가 적은
    시작 자료) · 엽서 · 자서전 · 모델 판단 · 화자 · 발급자는 싣지 않는다.
    답하지 않은 마지막 질문은 저장되지 않으므로 나오지 않는다.
    """
    rec = await link.by_token(_token(request))
    state = link.state_of(rec)
    link.gone(state)
    if state != "ended":
        raise link.stuck("not_ended")
    saved = await _read(store.load_session(rec["session_id"]))
    turns = [{"question": f["question"] or "", "answer": f["answer"]}
             for f in (saved["fragments"] if saved else []) if f["idx"] > 0]
    return {"theme": rec["theme"], "topic": rec["topic"], "turns": turns}


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


def _mine(session_id: str, who: str) -> sc.SessionController:
    """
    진행 중인 **내** 회차. 남의 것이면 없는 것과 같은 404 다 — 있는지조차 알려
    주지 않는다 (/record 와 같은 이유).
    """
    ctl = sc.get(session_id)
    if ctl is None or ctl.user_id != who:
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
        # **화면은 늘 새로 받게 한다.** Cache-Control 이 없으면 브라우저가 Last-Modified 로
        # 스스로 신선도를 어림해 예전 화면을 다시 쓴다 — 화면을 바꾼 뒤에도 링크를 연
        # 어르신에게 옛 버전이 뜬다(v0.45 낱말 카드가 안 나온 일). no-cache 는 저장은 하되
        # 쓸 때마다 서버에 물어본다 — 바뀌지 않았으면 304 라 비용은 거의 없다.
        return FileResponse(_web / "index.html", headers={"Cache-Control": "no-cache"})
