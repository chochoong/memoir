"""
안전 천장 검증 — 세션 수명 · 턴 천장 · 생성 상한

    python -m tests.test_limits

여기서 재는 것은 기능이 아니라 **사고가 났을 때 멈추는지**다. 그래서 검사마다
「이게 없으면 무엇이 일어나는가」를 적어 둔다 — 나중에 누군가 이 상한을 거추장
스럽다고 느껴 지울 때 그 줄을 먼저 읽게 된다.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows 콘솔은 기본이 cp949 라 한글 출력에서 UnicodeEncodeError 로 죽는다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app.session import controller as sc                                 # noqa: E402
from app.session import limits, store                                    # noqa: E402
from app.session.controller import SessionController                     # noqa: E402
from app.session.machine import Event, State                             # noqa: E402
from tests._auth import AsHeader                                          # noqa: E402
from tests._nodb import NoDb                                              # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else '!! '}{name}{'  — ' + detail if detail else ''}")


# ---------------------------------------------------------------- 도구

class _Env:
    """환경변수를 잠깐 바꾼다. 상한 값은 함수 안에서 읽히므로 이것으로 충분하다."""

    def __init__(self, **kv):
        self.kv = {k: str(v) for k, v in kv.items()}
        self.old: dict[str, str | None] = {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class _Reasons:
    """store.update_session 을 가로채 closed_reason 만 모은다."""

    def __enter__(self):
        self.seen: list[str | None] = []
        self._real = store.update_session

        async def fake(ctl, closed_reason=None):
            self.seen.append(closed_reason)

        store.update_session = fake
        return self

    def __exit__(self, *a):
        store.update_session = self._real


async def _silent_tts(text: str) -> bytes:
    return b""


async def _one_question(ctl) -> str | None:
    return "그다음에는 어떻게 되었어요?"


def _fresh(**kw) -> SessionController:
    kw.setdefault("user_id", "t")
    kw.setdefault("title", "시험")
    kw.setdefault("pace", "fast")
    kw.setdefault("tts_fn", _silent_tts)
    kw.setdefault("question_fn", _one_question)
    return SessionController(**kw)


async def _turn(ctl: SessionController, text: str) -> None:
    """낭독 끝 → 발화 → 「다 말했어요」 한 바퀴. T1·T2 를 건너뛴다."""
    if ctl.machine.state is State.SPEAKING:
        await ctl.tts_done()
    await ctl.speech(text)
    await ctl.done_button()
    await asyncio.sleep(0.05)              # _make_question 태스크가 돌 틈


# ---------------------------------------------------------------- 턴 천장

def test_turn_cap():
    print("\n[1] 턴 천장 — 무제한은 「AI 가 정한다」지 「영원히」가 아니다")

    ctl = _fresh()
    check("max_turn 을 안 주면 천장이 씌워진다", ctl.turn_cap() == 60,
          f"turn_cap()={ctl.turn_cap()} — 0 이면 회차가 무한히 흐른다")

    with _Env(TURN_CAP=7):
        check(".env 로 천장을 바꿀 수 있다", _fresh().turn_cap() == 7)

    ctl2 = _fresh(max_turn=3)
    check("요청이 정한 max_turn 이 천장을 이긴다", ctl2.turn_cap() == 3,
          "요청의 끝을 천장이 덮으면 replay 도구가 못 돈다")

    with _Env(TURN_CAP=0):
        check("천장을 0 으로 끌 수 있다", _fresh().turn_cap() == 0)

    async def run_to_cap():
        with _Env(TURN_CAP=2), _Reasons() as r:
            ctl = _fresh()
            await ctl.start("씨앗입니다")
            await _turn(ctl, "첫 번째 말씀입니다")
            mid = ctl.machine.state
            await _turn(ctl, "두 번째 말씀입니다")
            return ctl, mid, r.seen

    ctl3, mid, reasons = asyncio.run(run_to_cap())
    check("천장 전에는 회차가 계속된다", mid is State.SPEAKING,
          f"1턴 뒤 상태 {mid.value}")
    check("천장에 닿으면 CLOSED", ctl3.machine.state is State.CLOSED,
          f"턴 {ctl3.machine.turn} · 상태 {ctl3.machine.state.value}")
    check("이유가 turn_cap 으로 남는다", reasons and reasons[-1] == "turn_cap",
          f"{reasons} — max_turn 과 같은 이름으로 적으면 「AI 가 마무리를 "
          f"못 골랐다」를 나중에 셀 수 없다")

    async def run_max_turn():
        with _Reasons() as r:
            ctl = _fresh(max_turn=1)
            await ctl.start("씨앗입니다")
            await _turn(ctl, "한 마디만 하겠습니다")
            return ctl, r.seen

    ctl4, reasons4 = asyncio.run(run_max_turn())
    check("요청이 정한 끝은 max_turn 으로 남는다",
          ctl4.machine.state is State.CLOSED and reasons4[-1] == "max_turn",
          f"{reasons4}")


# ---------------------------------------------------------------- 세션 수명

def test_sweep():
    print("\n[2] 세션 스윕 — 떠난 회차를 메모리에서 지운다")

    sc._sessions.clear()                   # 레지스트리는 모듈 전역이다

    async def run():
        with _Env(SESSION_IDLE_SECONDS=10, SESSION_CLOSED_SECONDS=2), _Reasons() as r:
            live_old = sc.put(_fresh())            # 진행 중 · 오래됨
            live_new = sc.put(_fresh())            # 진행 중 · 방금
            closed_old = sc.put(_fresh())          # 닫힘 · 오래됨
            closed_new = sc.put(_fresh())          # 닫힘 · 방금

            for ctl in (closed_old, closed_new):
                ctl.machine.fire(Event.ABORT)

            now = time.monotonic()
            live_old.last_active = now - 60
            closed_old.last_active = now - 60
            live_old.timers.reset_t1()             # 버려진 회차에서 도는 타이머

            gone = await sc.sweep()
            return gone, live_old, live_new, closed_old, closed_new, r.seen

    gone, live_old, live_new, closed_old, closed_new, reasons = asyncio.run(run())

    check("오래된 회차 둘만 지워진다", gone == 2, f"{gone}개 지움")
    check("진행 중 · 오래됨 → 지워진다", sc.get(live_old.session_id) is None,
          "이게 없으면 fragments 와 발화 오디오가 프로세스가 죽을 때까지 남는다")
    check("진행 중 · 방금 → 남는다", sc.get(live_new.session_id) is live_new,
          "어르신이 생각하시는 중일 수 있다 — 잘못 지우면 404 가 된다")
    check("닫힘 · 오래됨 → 지워진다", sc.get(closed_old.session_id) is None)
    check("닫힘 · 방금 → 남는다", sc.get(closed_new.session_id) is closed_new,
          "화면이 300ms 폴링으로 마지막 상태를 받아 갈 틈")

    check("버려진 회차의 타이머가 끊긴다",
          live_old.timers._t1 is None or live_old.timers._t1.cancelled()
          or live_old.timers._t1.done(),
          "안 끊으면 아무도 없는 회차에서 T1 이 계속 돈다")
    check("버려진 회차는 CLOSED 가 된다", live_old.machine.state is State.CLOSED)
    check("이유가 expired 로 남는다", reasons == ["expired"],
          f"{reasons} — 안 남기면 DB 에서 영원히 「진행 중」이라 "
          f"이탈한 회차를 셀 수 없다")

    sc._sessions.clear()


def test_closed_reason_not_overwritten():
    print("\n[3] 이미 닫힌 회차의 이유를 덮지 않는다")

    sc._sessions.clear()

    async def run():
        with _Env(SESSION_CLOSED_SECONDS=1), _Reasons() as r:
            ctl = sc.put(_fresh())
            ctl.machine.fire(Event.ABORT)          # 어르신이 「중단」을 눌렀다
            ctl.last_active = time.monotonic() - 60
            await sc.sweep()
            return r.seen

    seen = asyncio.run(run())
    check("닫힌 회차를 지울 때는 DB 를 안 건드린다", seen == [],
          f"{seen} — expired 를 또 쓰면 COALESCE 가 abort 를 덮어써 "
          f"왜 끝났는지를 잃는다")

    sc._sessions.clear()


def test_polling_is_not_activity():
    print("\n[4] 폴링은 활동이 아니다")

    ctl = _fresh()
    asyncio.run(ctl.tts_done())            # SPEAKING → LISTENING (발화를 받는 상태)
    ctl.last_active = time.monotonic() - 100

    before = ctl.last_active
    ctl.snapshot()
    check("조회는 수명을 늘리지 않는다", ctl.last_active == before,
          "늘리면 열어 둔 채 잊은 탭이 영원히 살아 스윕이 무의미해진다")

    asyncio.run(ctl.speech("말씀하셨습니다"))
    check("발화는 수명을 늘린다", ctl.idle_seconds() < 1,
          f"{ctl.idle_seconds():.0f}초 — 늘리지 않으면 말씀 중에 지워진다")
    ctl.timers.cancel_all()


def test_live_count():
    print("\n[5] 동시 회차 셈")

    sc._sessions.clear()
    a = sc.put(_fresh(user_id="갑"))
    sc.put(_fresh(user_id="갑"))
    sc.put(_fresh(user_id="을"))
    a.machine.fire(Event.ABORT)

    check("닫힌 회차는 live 에서 빠진다", len(sc.live_sessions()) == 2,
          f"{len(sc.live_sessions())} / 전체 {len(sc.all_sessions())}")
    check("사용자별로 센다", sc.user_live("갑") == 1 and sc.user_live("을") == 1,
          f"갑 {sc.user_live('갑')} · 을 {sc.user_live('을')}")

    with _Env(MAX_LIVE_SESSIONS=5):
        check(".env 로 상한을 바꿀 수 있다", sc.max_live() == 5)

    sc._sessions.clear()


# ---------------------------------------------------------------- 생성 상한

def test_rate_limit():
    print("\n[6] 생성 상한 — 인증이 없는 동안 지출의 유일한 입구")

    limits.reset()
    with _Env(CREATE_WINDOW_SECONDS=600, CREATE_MAX_PER_WINDOW=3):
        ok = 0
        blocked = None
        for _ in range(5):
            try:
                limits.take("1.2.3.4")
                ok += 1
            except limits.Rejected as e:
                blocked = e
                break
        check("창 안에서 정해진 횟수만 통과한다", ok == 3, f"{ok}회 통과")
        check("넘으면 Rejected", blocked is not None)
        check("얼마나 기다릴지 알려준다", blocked is not None and blocked.retry_after > 0,
              f"retry_after={getattr(blocked, 'retry_after', None)} — "
              f"Retry-After 헤더로 나간다")

        limits.take("5.6.7.8")
        check("IP 마다 따로 센다", True, "다른 IP 는 막히지 않는다")

    limits.reset()
    with _Env(CREATE_MAX_PER_WINDOW=0):
        for _ in range(50):
            limits.take("1.2.3.4")
        check("0 은 「상한 없음」이다", True, "시험·내부용으로 끌 수 있어야 한다")

    limits.reset()
    with _Env(CREATE_WINDOW_SECONDS=0.05, CREATE_MAX_PER_WINDOW=1):
        limits.take("9.9.9.9")
        time.sleep(0.1)
        try:
            limits.take("9.9.9.9")
            check("창이 지나면 다시 열린다", True)
        except limits.Rejected:
            check("창이 지나면 다시 열린다", False, "창이 안 미끄러진다")
    limits.reset()


def test_prune():
    print("\n[7] 생성 기록 자체가 누수가 되지 않는다")

    # _prune 자체는 시계와 무관하게 확인한다.
    limits.reset()
    limits._hits["1.1.1.1"] = deque([time.monotonic()])          # 창 안
    limits._hits["2.2.2.2"] = deque([time.monotonic() - 100.0])  # 창 밖
    limits._hits["3.3.3.3"] = deque()                            # 빈 것
    limits._prune(time.monotonic(), window=10.0)
    check("창을 벗어난 IP 는 버려진다",
          set(limits._hits) == {"1.1.1.1"},
          f"{sorted(limits._hits)} — 안 버리면 IP 를 바꿔 가며 때리는 "
          f"것만으로 메모리가 찬다")

    # take() 쪽은 「줄어드는가」가 아니라 **묶여 있는가**를 본다.
    #
    # 「한 번 더 부르면 반드시 줄어든다」로 적었더니 20번에 3번 깨졌다.
    # take() 는 len(_hits) > PRUNE_AT 일 때만 훑는데, 1010개를 넣는 동안 이미
    # 훑혀서 978개로 내려와 있으면 그 다음 호출은 훑지 않는다. 버그가 아니라
    # 설계대로다 — 훑기는 dict 가 커졌을 때만 돈다. 실제로 지켜야 하는 것은
    # 「IP 를 바꿔 가며 때려도 항목 수가 선형으로 늘지 않는다」 하나다.
    limits.reset()
    with _Env(CREATE_WINDOW_SECONDS=0.01, CREATE_MAX_PER_WINDOW=5):
        for i in range(limits.PRUNE_AT * 3):
            limits.take(f"10.{i // 65536}.{(i // 256) % 256}.{i % 256}")
        check("IP 를 바꿔 가며 때려도 항목이 묶여 있다",
              limits.counted() <= limits.PRUNE_AT + 1,
              f"{limits.PRUNE_AT * 3}개를 서로 다른 IP 로 넣었는데 "
              f"{limits.counted()}개만 남았다")
    limits.reset()


# ------------------------------------------------------- 프록시 뒤의 주소

class _Req:
    """limits.client_ip 가 보는 것만 흉내 낸 요청."""

    class _C:
        def __init__(self, host):
            self.host = host

    def __init__(self, host, xff=None, cf=None):
        self.client = self._C(host)
        self.headers = {}
        if xff:
            self.headers["x-forwarded-for"] = xff
        if cf:
            self.headers["cf-connecting-ip"] = cf


def test_client_ip():
    print("\n[8] 전달 헤더를 확인 없이 믿지 않는다")

    # 공격자가 "1.1.1.1" 을 심어 보냈고, 프록시가 그 뒤에 진짜 주소를 덧붙인 모양.
    attacked = _Req("10.0.0.1", xff="1.1.1.1, 203.0.113.9")

    check("기본은 소켓 주소", limits.client_ip(attacked) == "10.0.0.1",
          "헤더를 믿으면 매 요청에 다른 값을 넣어 상한을 통째로 지날 수 있다")

    with _Env(TRUST_PROXY="xff"):
        got = limits.client_ip(attacked)
        check("xff 는 맨 **뒤** 값을 쓴다", got == "203.0.113.9", got)
        # 이 한 줄이 이 절의 이유다. X-Forwarded-For 는 클라이언트가 넣어 보낸
        # 값 뒤에 프록시가 덧붙이는 구조라, 맨 앞은 공격자가 쓴 글씨다.
        check("맨 앞(공격자가 쓴 값)을 쓰지 않는다", got != "1.1.1.1",
              "앞을 읽으면 헤더 한 줄로 IP 상한이 사라진다")

    with _Env(TRUST_PROXY="1"):
        check("예전 표기 1 은 xff 로 읽는다",
              limits.client_ip(attacked) == "203.0.113.9")

    with _Env(TRUST_PROXY="cf"):
        req = _Req("127.0.0.1", xff="1.1.1.1", cf="203.0.113.7")
        check("cf 는 CF-Connecting-IP 를 쓴다",
              limits.client_ip(req) == "203.0.113.7",
              "엣지가 덮어쓰는 헤더라 클라이언트가 채워 보내도 남지 않는다")
        check("cf 모드에서 X-Forwarded-For 는 보지 않는다",
              limits.client_ip(req) != "1.1.1.1")
        check("cf 인데 헤더가 없으면 소켓으로 떨어진다",
              limits.client_ip(_Req("127.0.0.1", xff="1.1.1.1")) == "127.0.0.1",
              "터널을 안 거치고 들어온 요청이다")

    with _Env(TRUST_PROXY="yes"):
        check("켜졌는데 헤더가 없으면 소켓으로 떨어진다",
              limits.client_ip(_Req("10.0.0.2")) == "10.0.0.2")

    with _Env(TRUST_PROXY="maybe"):
        check("오타는 꺼진 것으로 읽는다", limits.client_ip(attacked) == "10.0.0.1",
              "안전한 쪽으로 넘어지게 해 둔 것이다")

    for off in ("0", "off", "false", ""):
        with _Env(TRUST_PROXY=off):
            check(f"TRUST_PROXY={off!r} 는 경고 없이 off", limits.proxy_mode() == "off",
                  "기본값이 「모르는 값」으로 잡히면 기동마다 경고가 뜬다")

    check("주소를 못 알아내도 죽지 않는다",
          limits.client_ip(_Req(None)) == "unknown")


def test_posture():
    print("\n[9] 공개 주소를 적으면 개발용 편의가 닫힌다")

    import importlib

    import app.main as m

    def rebuilt(**env):
        with _Env(**env):
            return importlib.reload(m)

    try:
        pub = rebuilt(PUBLIC_ORIGIN="https://memoa.example.com", ALLOWED_ORIGINS="")
        check("/docs 가 닫힌다", pub.app.docs_url is None,
              "인터넷에 API 스키마를 펼쳐 두지 않는다")
        check("/openapi.json 도 닫힌다", pub.app.openapi_url is None)
        check("개발용 CORS 허용이 빠진다",
              not any("5173" in o for o in pub._origins),
              f"{pub._origins} — 화면을 이 서버가 내므로 같은 출처다")
        check("워커 수를 읽는다", pub._workers() == 1)

        docs_on = rebuilt(PUBLIC_ORIGIN="https://memoa.example.com", DOCS="1")
        check("DOCS=1 이면 되살아난다", docs_on.app.docs_url == "/docs")

        # _workers() 는 부를 때 환경을 읽는다 — _Env 안에서 불러야 한다.
        with _Env(WEB_CONCURRENCY="4"):
            check("워커가 여럿이면 알아챈다", m._workers() == 4,
                  "회차가 프로세스 메모리에 있어 폴링이 다른 워커로 가면 404 가 난다")
    finally:
        # 이 모듈은 전역이다. 다른 시험이 쓰기 전에 개발 상태로 되돌려 놓는다.
        with _Env(PUBLIC_ORIGIN="", DOCS="", WEB_CONCURRENCY=""):
            importlib.reload(m)


# ---------------------------------------------------------------- 라우트

def test_route_limits():
    """
    라우트에서 실제로 막히는지. 여기만 앱을 띄운다.

    로그인 전에는 회차를 열지 못한다. 예전에는 모두가 dev-user 로 들어와서
    사용자별 상한을 끌 수밖에 없었다 — 이제 신원이 갈리므로 모두에게 건다.
    """
    print("\n[10] 라우트 — 실제 응답 코드")

    from fastapi.testclient import TestClient

    from app.main import app

    sc._sessions.clear()
    limits.reset()
    body = {"title": "시험", "seed": "씨앗 한 줄", "pace": "fast"}

    with _Env(GEMINI_API_KEY="", AZURE_SPEECH_KEY="",
              CREATE_MAX_PER_WINDOW=99, USER_LIVE_MAX=1), NoDb(), AsHeader(), TestClient(app) as c:
        anon = [c.post("/api/sessions", json=body).status_code for _ in range(2)]
        check("로그인 전에는 회차를 열지 못한다", anon == [401] * 2, f"{anon}")
        check("거절한 요청은 회차를 만들지 않았다", not sc._sessions, f"{len(sc._sessions)}개")

        real = [c.post("/api/sessions", json=body,
                       headers={"X-User-Id": "real-user"}).status_code
                for _ in range(2)]
        check("사용자별 상한이 산다", real == [200, 429], f"{real}")
        c.headers["X-User-Id"] = "kim"

        limits.reset()
        with _Env(CREATE_MAX_PER_WINDOW=1):
            c.post("/api/sessions", json=body)
            r = c.post("/api/sessions", json=body)
            check("생성 상한은 429 + Retry-After",
                  r.status_code == 429 and r.headers.get("retry-after"),
                  f"{r.status_code} · Retry-After={r.headers.get('retry-after')}")

        limits.reset()
        with _Env(CREATE_MAX_PER_WINDOW=99, MAX_LIVE_SESSIONS=1):
            r = c.post("/api/sessions", json=body)
            check("서버가 꽉 차면 429 가 아니라 503", r.status_code == 503,
                  f"{r.status_code} — 어르신 잘못이 아니라서 화면이 다르게 "
                  f"말해야 한다")

        # 시작 자료 (C1) — 테마·주제는 선택이고, 받으면 회차까지 간다
        sc._sessions.clear()
        limits.reset()
        r = c.post("/api/sessions", json={"title": "시험", "theme": "family",
                                          "topic": "  가족과 함께 이사한 기억 "})
        ctl = sc.get(r.json()["session_id"]) if r.status_code == 200 else None
        check("테마·주제가 회차에 닿는다",
              ctl is not None and ctl.theme == "family"
              and ctl.topic == "가족과 함께 이사한 기억",
              f"{r.status_code} {ctl and (ctl.theme, ctl.topic)}")
        check("seed 없이도 연다", r.status_code == 200)
        check("주제가 있으면 여는 말은 주제다",
              "가족과 함께 이사한 기억" in (r.json().get("next_question") or ""),
              str(r.json().get("next_question")))
        bad = c.post("/api/sessions", json={"title": "시험", "theme": "travel"})
        check("모르는 테마는 422", bad.status_code == 422, str(bad.status_code))
        long = c.post("/api/sessions", json={"title": "시험", "topic": "가" * 101})
        check("너무 긴 주제는 422", long.status_code == 422, str(long.status_code))

    sc._sessions.clear()
    limits.reset()


def test_replace_on_user_cap():
    """
    이 기기 시작이 계정 상한에 걸리면 429 대신 활동이 오래된 이 계정 회차를 닫고 연다 (승우 10-30 제안).
    링크 회차 · 최근에 활동한 회차는 닫지 않는다. 응답의 closed_session_ids 로 화면이 알린다.
    """
    print("\n[11] 상한에 걸리면 오래된 회차를 닫고 연다")

    from fastapi.testclient import TestClient

    from app.main import app
    from app.session.machine import State

    sc._sessions.clear()
    limits.reset()
    body = {"title": "시험", "seed": "씨앗 한 줄", "pace": "fast"}

    with _Env(GEMINI_API_KEY="", AZURE_SPEECH_KEY="", CREATE_MAX_PER_WINDOW=99, USER_LIVE_MAX=2,
              SESSION_REPLACE_IDLE_SECONDS=120), NoDb(), AsHeader(), TestClient(app) as c:
        c.headers["X-User-Id"] = "kim"
        a = c.post("/api/sessions", json=body).json()
        b = c.post("/api/sessions", json=body).json()
        check("상한 안이면 닫은 회차 없음 (빈 목록)", a["closed_session_ids"] == [] and b["closed_session_ids"] == [],
              f"{a.get('closed_session_ids')} {b.get('closed_session_ids')}")

        r = c.post("/api/sessions", json=body)
        check("둘 다 방금 활동했으면 닫지 않고 429 — 다른 기기에서 진행 중일 수 있다", r.status_code == 429,
              str(r.status_code))

        old = sc.get(a["session_id"])
        old.last_active -= 1000
        r = c.post("/api/sessions", json=body)
        got = r.json() if r.status_code == 200 else {}
        check("오래된 회차를 닫고 연다 · 닫은 번호를 알린다",
              r.status_code == 200 and got.get("closed_session_ids") == [a["session_id"]],
              f"{r.status_code} {got.get('closed_session_ids')}")
        check("닫힌 회차는 CLOSED", old.machine.state is State.CLOSED, str(old.machine.state))
        check("계정의 진행 중 회차는 상한 그대로", sc.user_live("kim") == 2, str(sc.user_live("kim")))

        # 링크 회차는 오래돼도 닫지 않는다
        for x in sc.live_sessions():
            if x.user_id == "kim":
                x.via_link = True
                x.last_active -= 1000
        r = c.post("/api/sessions", json=body)
        check("남은 것이 링크 회차뿐이면 닫지 않고 429", r.status_code == 429, str(r.status_code))
        check("링크 회차는 그대로 진행 중", all(x.machine.state is not State.CLOSED
                                                for x in sc.live_sessions() if x.via_link) and sc.user_live("kim") == 2)

        # 다른 계정의 회차는 건드리지 않는다
        sc._sessions.clear()
        limits.reset()
        mine = c.post("/api/sessions", json=body).json()["session_id"]
        other = c.post("/api/sessions", json=body, headers={"X-User-Id": "lee"}).json()["session_id"]
        sc.get(other).last_active -= 1000
        c.post("/api/sessions", json=body)
        r = c.post("/api/sessions", json=body)
        check("다른 계정의 오래된 회차는 닫지 않는다",
              r.status_code == 429 and sc.get(other).machine.state is not State.CLOSED and sc.get(mine) is not None,
              str(r.status_code))

    sc._sessions.clear()
    limits.reset()


def test_all_checks_passed():
    """pytest 안전판 — test_flow.py 의 같은 함수 주석 참조."""
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 안전 천장 검증")
    test_turn_cap()
    test_sweep()
    test_closed_reason_not_overwritten()
    test_polling_is_not_activity()
    test_live_count()
    test_rate_limit()
    test_prune()
    test_client_ip()
    test_posture()
    test_route_limits()
    test_replace_on_user_cap()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
