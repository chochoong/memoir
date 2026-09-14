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
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.session import controller as sc
from app.session import store, stt, tts
from app.session.machine import TransitionError
from app.session.question import gemini_question, warmup

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(name)-9s %(message)s",
    datefmt="%H:%M:%S")

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
    """
    await store.open_pool()
    asyncio.create_task(warmup())
    asyncio.create_task(stt.warmup())
    asyncio.create_task(tts.warmup())
    yield
    await stt.aclose()
    await tts.aclose()
    await store.close_pool()


app = FastAPI(title="기억의 조각 API", version="0.1.0", lifespan=lifespan)

# ---------------------------------------------------------------- CORS
# 개발 중에는 Vite 개발 서버가 다른 포트에서 붙는다.
# 터널 URL 은 .env 의 ALLOWED_ORIGINS 에 쉼표로 추가한다 (끝 슬래시 없이).
_origins = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    *[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()],
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- 모델

class StartReq(BaseModel):
    title: str
    postcard: str
    pace: str = "normal"          # fast(3초) / normal(5초) / slow(7초)
    # 0 = 제한 없음. 대화가 어디서 끝날지는 AI 의 close 판단이 정한다.
    # 양을 미리 묶고 싶은 쪽(시험 도구 등)이 값을 준다.
    max_turn: int = 0


class SpeechReq(BaseModel):
    text: str


# ---------------------------------------------------------------- API
#
# 모든 엔드포인트가 같은 snapshot 한 덩어리를 돌려준다. 프론트는 타입이 하나면 되고
# (api.ts 의 Snapshot), 응답마다 무엇이 오는지 외울 필요가 없다.
#
# 상태를 바꾸는 것은 전부 _guard 를 지난다. 정의되지 않은 전이는 409 로 끊는다.


@app.get("/api/health")
async def health():
    """
    살아 있는지 + 지금 CORS 가 무엇을 허용하는지.

    origins 를 굳이 실어 보내는 이유 — CORS 는 브라우저가 막는 것이라 서버 로그에
    아무것도 남지 않는다. .env 의 ALLOWED_ORIGINS 가 실제로 먹었는지 눈으로 볼 데가
    여기 말고 없다. 터널 URL 을 넣었는데 이 값이 그대로면 .env 를 못 읽은 것이다.
    """
    return {"ok": True, "sessions": len(sc.all_sessions()), "origins": _origins}


@app.post("/api/sessions")
async def create_session(req: StartReq, x_user_id: str = Header(default="dev-user")):
    """
    회차를 연다. 엽서가 0번 조각이 되고, 첫 질문을 든 SPEAKING 상태로 시작한다.

    X-User-Id 는 받아만 두고 검사하지 않는다. 구글 로그인이 붙으면 여기서 토큰을 풀어
    user_id 를 얻는다 — 그때 고칠 곳이 이 인자 하나로 끝나도록 해 둔 것이다.

    여기만 _guard 를 지나지 않는다. 상태 머신이 이제 막 생겨 전이랄 게 없다.

    question_fn 을 **여기서** 꽂는다. SessionController 의 기본값은 fixed_questions 로
    두었다 — 그래야 tests/test_flow.py 가 네트워크도 API 키도 없이 돈다. 실제 Gemini 는
    앱을 띄울 때만 붙는다. 키가 없으면 gemini_question 이 알아서 고정 질문으로 돈다.
    """
    ctl = sc.put(sc.SessionController(
        user_id=x_user_id, title=req.title, pace=req.pace, max_turn=req.max_turn,
        question_fn=gemini_question))
    await ctl.start(req.postcard)
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


# ---------------------------------------------------------------- 보조

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
