"""
인터뷰 링크 검증 — 발급 · 미리보기 · 시작 · 진행 · 종료 · 회수 (3-C1 §5 · P3-SV-04 · 05)

    python -m tests.test_link

**모의 시험이다.** 링크 · 계정 표는 메모리로 바꿔 끼우고 (DB 없음), 질문은 키 없이
도는 고정 질문이다. 구글 로그인도 test_auth 의 가짜 검증을 쓴다. 신원 경로
(msid · 링크 토큰 · mlink 쿠키)는 진짜를 쓴다.

    [발급]     자기 화자 · 자기 사진만 · 토큰은 한 번만 나가고 표에는 해시만
    [A3]       미리보기는 몇 번 열어도 아무것도 바꾸지 않는다
    [A5]       연속 시작 · 재시도 · 동시 시작 → 회차 하나 · 다른 기기는 409
    [진행]     기기 쿠키로 진행 · 본문의 session_id 는 무시
    [A6 · A7]  링크 권한과 자녀 권한이 섞이지 않는다
    [종료]     끝난 뒤 읽기 전용 대화 · 0번 조각 없음 · 끊김
    [엽서]     링크로 마친 회차는 발급한 자녀가 굽는다 · 다른 자녀 404 · 어르신 기기 401
    [A4]       만료 · 회수 · 재발급 · 진행 중에는 만료되지 않는다
    [상한]     꽉 찼으면 링크를 소모하지 않는다
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from fastapi.responses import Response                                   # noqa: E402

from app.session import auth, link, store                                # noqa: E402
from app.session import controller as sc                                 # noqa: E402
from app.session.machine import State                                    # noqa: E402
from tests._nodb import NoDb                                              # noqa: E402
from tests.test_auth import CLIENT_ID, _Env, _FakeAccounts, _login       # noqa: E402

PASS, FAIL = [], []
H = link.HEADER


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else '!! '}{name}{'  — ' + detail if detail else ''}")


def _now():
    return datetime.now(timezone.utc)


class _FakeLinks:
    """store 의 링크 · 사진 · 회차 읽기를 메모리로. 조건부 시작(claim)은 DB 와 같은 조건을 본다."""

    NAMES = ("owns_elder", "create_link", "load_link_by_token", "load_link_by_device",
             "load_link", "list_links", "claim_link", "end_link", "revoke_link",
             "load_photo", "load_session")

    def __init__(self, acc):
        self.acc = acc

    def __enter__(self):
        self.links: dict[str, dict] = {}
        self.photos: dict[str, dict] = {}
        self.claims = 0
        self.old = {n: getattr(store, n) for n in self.NAMES}
        links, acc = self.links, self.acc

        def row(r):
            return {k: v for k, v in r.items() if k != "token_hash"} if r else None

        async def owns_elder(user_id, elder_id):
            return any(e["user_id"] == user_id and e["elder_id"] == elder_id for e in acc.elders)

        async def create_link(rec):
            links[rec["link_id"]] = {**rec, "session_id": None, "device_hash": None,
                                     "created_at": _now(), "revoked_at": None,
                                     "started_at": None, "ended_at": None}

        async def load_link_by_token(h):
            return row(next((r for r in links.values() if r["token_hash"] == h), None))

        async def load_link_by_device(h):
            return row(next((r for r in links.values() if r["device_hash"] == h), None))

        async def load_link(link_id):
            return row(links.get(link_id))

        async def list_links(user_id, elder_id, limit):
            rs = [r for r in links.values() if r["user_id"] == user_id
                  and (elder_id is None or r["elder_id"] == elder_id)]
            return [row(r) for r in sorted(rs, key=lambda r: r["created_at"], reverse=True)][:limit]

        async def claim_link(link_id, session_id, device_hash):
            r = links.get(link_id)
            if (r is None or r["session_id"] is not None or r["revoked_at"] is not None
                    or r["expires_at"] <= _now()):
                return False
            self.claims += 1
            r.update(session_id=session_id, device_hash=device_hash, started_at=_now())
            return True

        async def end_link(session_id):
            for r in links.values():
                if r["session_id"] == session_id and r["ended_at"] is None:
                    r["ended_at"] = _now()

        async def revoke_link(link_id):
            if links[link_id]["revoked_at"] is None:
                links[link_id]["revoked_at"] = _now()

        async def load_photo(photo_id):
            return self.photos.get(photo_id)

        async def load_session(session_id):
            ctl = sc.get(session_id)
            return {"fragments": list(ctl.fragments)} if ctl else self.saved.get(session_id)

        self.saved: dict[str, dict] = {}
        for n in self.NAMES:
            setattr(store, n, locals()[n])
        return self

    def __exit__(self, *a):
        for n, f in self.old.items():
            setattr(store, n, f)

    def by_session(self, session_id):
        return next(r for r in self.links.values() if r["session_id"] == session_id)


def _client():
    from fastapi.testclient import TestClient

    from app.main import app
    # https 로 연다 — 배포 .env(PUBLIC_ORIGIN=https://…)면 쿠키에 Secure 가 붙고,
    # http 시험 클라이언트는 그 쿠키를 다시 싣지 않아 로그인이 끊긴 것처럼 보인다.
    return TestClient(app, base_url="https://testserver")


def _parent(sub, elder_name="어머니"):
    """로그인한 자녀 + 화자 하나."""
    c = _client().__enter__()
    _login(c, sub)
    elder = c.post("/api/elders", json={"name": elder_name}).json()
    return c, elder["elder_id"]


def _issue(c, elder_id, **kw):
    body = {"elder_id": elder_id, "theme": "family", "topic": "딸의 초등학교 입학",
            "seed": "자녀가 적은 시작 자료", **kw}
    return c.post("/api/links", json=body)


async def _together(token):
    """두 요청을 한 이벤트 루프에서 정말로 겹치게 보낸다. 시작 기록을 일부러 늦춘다."""
    import httpx

    from app.main import app
    real = store.claim_link

    async def slow(*a):
        await asyncio.sleep(0.05)
        return await real(*a)

    store.claim_link = slow
    try:
        t = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=t, base_url="https://testserver") as c1,                 httpx.AsyncClient(transport=t, base_url="https://testserver") as c2:
            return await asyncio.gather(c1.post("/api/i/start", headers={H: token}),
                                        c2.post("/api/i/start", headers={H: token}))
    finally:
        store.claim_link = real


def _mine(fl, session_id):
    return sum(1 for r in fl.links.values() if r["session_id"] == session_id)


def run():
    with _Env(GOOGLE_CLIENT_ID=CLIENT_ID, AZURE_SPEECH_KEY="", GEMINI_API_KEY="",
              TTS_PROVIDER="azure", MAX_LIVE_SESSIONS="50", USER_LIVE_MAX="20",
              RATE_LIMIT_PER_WINDOW="1000"), \
            NoDb(), _FakeAccounts() as acc, _FakeLinks(acc) as fl:
        a, elder_a = _parent("A")
        b, elder_b = _parent("B", "아버지")

        # ------------------------------------------------------------ 발급
        print("\n[발급] 자기 화자 · 자기 사진만")
        r = _issue(a, elder_b)
        check("남의 화자로는 발급하지 않는다 → 404", r.status_code == 404, r.text[:80])
        fl.photos["p_b"] = {"photo_id": "p_b", "user_id": "u_B", "status": "stored"}
        # 단서가 이미 있는 사진 — 시작할 때 사진 분석(모델)을 다시 부르지 않는다
        fl.photos["p_a"] = {"photo_id": "p_a", "user_id": "u_A", "status": "stored",
                            "clues": {"summary": "입학식 사진"}}
        r = _issue(a, elder_a, photo_id="p_b")
        check("남의 사진으로는 발급하지 않는다 → 404", r.status_code == 404, r.text[:80])
        check("거절된 발급은 링크를 만들지 않았다", not fl.links)
        with _client() as anon:
            r = _issue(anon, elder_a)
            check("로그인 없이 발급 → 401", r.status_code == 401, r.text[:80])

        r = _issue(a, elder_a, photo_id="p_a")
        body = r.json()
        tok = body.get("token", "")
        check("발급 → 201 · 토큰 · /i#토큰 주소 · ready", r.status_code == 201 and tok
              and body["url"].endswith(f"/i#{tok}") and body["state"] == "ready", r.text[:160])
        rec = fl.links[body["link_id"]]
        check("표에는 토큰 원문이 없고 해시만 있다",
              tok not in str(rec) and rec["token_hash"] == link._hash(tok))
        check("발급만으로는 회차가 열리지 않는다", rec["session_id"] is None)
        listed = a.get("/api/links").json()["links"]
        check("목록에 토큰은 없다", len(listed) == 1 and "token" not in listed[0]
              and "token_hash" not in listed[0] and "device_hash" not in listed[0], str(listed)[:160])
        check("B 의 목록에는 A 의 링크가 없다", b.get("/api/links").json()["links"] == [])

        # ------------------------------------------------------------ A3 미리보기
        print("\n[A3] 미리보기는 아무것도 바꾸지 않는다")
        before = len(sc.all_sessions())
        with _client() as g:
            views = [g.get("/api/i/preview", headers={H: tok}) for _ in range(3)]
            check("세 번 열어도 같은 200 ready", all(v.status_code == 200 for v in views)
                  and len({v.text for v in views}) == 1, views[0].text[:120])
            v = views[0].json()
            check("테마 · 주제 · 사진 주소를 준다", v == {"state": "ready", "theme": "family",
                  "topic": "딸의 초등학교 입학", "photo_url": "/api/i/photo"}, str(v))
            check("화자 · 발급자 · 시작 자료는 싣지 않는다",
                  "어머니" not in views[0].text and "u_A" not in views[0].text
                  and "시작 자료" not in views[0].text)
            check("미리보기는 회차를 열지 않았다", len(sc.all_sessions()) == before
                  and rec["session_id"] is None and link.COOKIE not in g.cookies)
            r = g.get("/api/i/preview")
            check("토큰 없이 → 404 invalid_link", r.status_code == 404
                  and r.json().get("code") == "invalid_link", r.text[:80])
            r = g.get("/api/i/preview", headers={H: "made-up-token"})
            check("지어낸 토큰 → 404 invalid_link", r.status_code == 404
                  and r.json().get("code") == "invalid_link", r.text[:80])

        # ------------------------------------------------------------ A5 시작
        print("\n[A5] 시작 — 한 링크는 한 회차")
        dev = _client().__enter__()
        r = dev.post("/api/i/start", headers={H: tok})
        s1 = r.json()
        sid = s1.get("session_id")
        cookie = r.headers.get("set-cookie", "")
        check("시작 → 200 snapshot + 준비 내용", r.status_code == 200 and sid
              and s1.get("state") == "in_progress" and s1.get("photo_url") == "/api/i/photo"
              and "next_question" in s1, r.text[:160])
        check("기기 쿠키 mlink · Path=/api/i · HttpOnly",
              link.COOKIE in dev.cookies and "path=/api/i" in cookie.lower()
              and "httponly" in cookie.lower(), cookie[:120])
        check("링크에 회차가 묶였다", rec["session_id"] == sid and rec["started_at"] is not None)
        ctl = sc.get(sid)
        check("회차의 주인은 발급한 자녀 · 화자는 링크의 화자 · 주제는 링크의 것",
              ctl.user_id == "u_A" and ctl.elder_id == elder_a and ctl.topic == "딸의 초등학교 입학")
        check("시작 자료는 0번 조각으로 들어갔다", ctl.fragments[0]["answer"] == "자녀가 적은 시작 자료")

        for _ in range(2):
            r = dev.post("/api/i/start", headers={H: tok})
        check("같은 기기에서 다시 누르면 같은 회차", r.status_code == 200
              and r.json()["session_id"] == sid, r.text[:80])
        with _client() as other:
            r = other.post("/api/i/start", headers={H: tok})
            check("다른 기기 → 409 in_progress_elsewhere", r.status_code == 409
                  and r.json().get("code") == "in_progress_elsewhere", r.text[:80])
            check("다른 기기는 진행 경로에도 못 닿는다 → 404",
                  other.get("/api/i/session").status_code == 404)
        check("회차는 하나 · 시작 기록도 한 번", _mine(fl, sid) == 1 and fl.claims == 1,
              f"claims={fl.claims}")
        check("미리보기는 in_progress", dev.get("/api/i/preview", headers={H: tok}).json()["state"]
              == "in_progress")

        # 동시 시작 — 같은 링크로 시작 두 개가 한꺼번에 들어온다 (두 번 누름)
        tok2 = _issue(a, elder_a).json()["token"]
        rec2 = next(x for x in fl.links.values() if x["token_hash"] == link._hash(tok2))
        claims0 = fl.claims
        r1, r2 = asyncio.run(_together(tok2))
        codes = sorted([r1.status_code, r2.status_code])
        late = r2 if r2.status_code == 409 else r1
        check("동시에 두 번 → 200 하나 · 409 in_progress_elsewhere 하나",
              codes == [200, 409] and late.json().get("code") == "in_progress_elsewhere",
              f"{r1.status_code} {r1.text[:60]} / {r2.status_code} {r2.text[:60]}")
        check("동시에 두 번 → 회차 하나 · 시작 기록 한 번",
              fl.claims == claims0 + 1 and rec2["session_id"] is not None
              and sum(1 for c_ in sc.all_sessions() if c_.session_id == rec2["session_id"]) == 1,
              f"claims={fl.claims - claims0}")
        check("시작 잠금은 쓰고 나면 비운다", not link._starting)

        # ------------------------------------------------------------ 진행
        print("\n[진행] 기기 쿠키로")
        r = dev.get("/api/i/session")
        check("GET /api/i/session → 같은 회차", r.status_code == 200
              and r.json()["session_id"] == sid, r.text[:80])
        r = dev.post("/api/i/session/tts-done")
        check("낭독 끝 → 200", r.status_code == 200, r.text[:80])
        other_ctl = sc.put(sc.SessionController(user_id="u_B", title="B 의 회차"))
        r = dev.post("/api/i/session/speech",
                     json={"text": "1996년에 딸이 입학했어요", "session_id": other_ctl.session_id})
        check("본문의 session_id 는 무시하고 링크의 회차로 간다", r.status_code == 200
              and r.json()["session_id"] == sid and other_ctl.machine.turn == 0
              and "1996" in ctl._buffer, r.text[:80])
        r = dev.get("/api/i/session/question/audio")
        check("질문 소리 경로 (소리 없음 → 204)", r.status_code in (200, 204), str(r.status_code))
        r = dev.get("/api/i/session/latency")
        check("링크에는 지연 계측 경로가 없다", r.status_code in (404, 405), str(r.status_code))

        # 사진
        import app.main as m
        real_bytes = m._photo_bytes
        served = []

        async def fake_bytes(rec_, request):
            served.append(rec_["photo_id"])
            return Response(b"PIC", media_type="image/jpeg")

        m._photo_bytes = fake_bytes
        r = dev.get("/api/i/photo")
        check("시작한 기기는 쿠키로 보조 사진을 받는다", r.status_code == 200
              and served == ["p_a"], r.text[:40])
        with _client() as g:
            r = g.get("/api/i/photo", headers={H: tok})
            check("토큰 헤더로도 받는다 (시작 전 화면)", r.status_code == 200, str(r.status_code))
            r = g.get("/api/i/photo")
            check("아무것도 없으면 404", r.status_code == 404, str(r.status_code))
            r = g.get("/api/i/photo", headers={H: tok2})
            check("사진이 없는 링크 → 404", r.status_code == 404, str(r.status_code))
        check("링크에 지정된 사진 말고는 나가지 않았다", set(served) == {"p_a"}, str(served))
        m._photo_bytes = real_bytes

        # ------------------------------------------------------------ A6 · A7
        print("\n[A6 · A7] 권한을 합치지 않는다")
        # dev 는 mlink 만 있다 — 자녀 경로에 신원이 없어야 한다
        for method, path in [("get", "/api/sessions"), ("get", f"/api/sessions/{sid}"),
                             ("get", f"/api/sessions/{sid}/record"), ("get", "/api/links"),
                             ("post", f"/api/sessions/{sid}/done"), ("post", "/api/photos"),
                             ("post", f"/api/sessions/{sid}/postcard"),
                             ("get", "/api/i/../sessions")]:
            r = getattr(dev, method)(path)
            check(f"mlink 만으로 {method.upper()} {path} → 401", r.status_code == 401, str(r.status_code))
        # 문체 생성(4차)도 자녀 경로다 — 링크로는 문체를 실어도 401, 모델 앞까지 가지 않는다
        from app.session import memoir, postcard
        calls: list[str] = []

        async def _no_make(*a, **k):
            calls.append("postcard")

        async def _no_preview(*a, **k):
            calls.append("memoir")

        real_make, real_preview = postcard.make, memoir.preview
        postcard.make, memoir.preview = _no_make, _no_preview
        try:
            for style in (None, "spoken", "novel"):
                body = {} if style is None else {"style": style}
                r = dev.post(f"/api/sessions/{sid}/postcard", json=body)
                check(f"mlink 만으로 엽서 굽기 (style={style}) → 401", r.status_code == 401, str(r.status_code))
                r = dev.post("/api/memoirs/preview", json={"session_ids": [sid] * 3, **body})
                check(f"mlink 만으로 자서전 미리보기 (style={style}) → 401",
                      r.status_code == 401, str(r.status_code))
            r = dev.get(f"/api/sessions/{sid}/postcard")
            check("mlink 만으로 엽서 그림 → 401", r.status_code == 401, str(r.status_code))
        finally:
            postcard.make, memoir.preview = real_make, real_preview
        check("링크로 온 생성 요청은 엽서 · 자서전 모델을 부르지 않았다", calls == [], str(calls))
        # a 는 msid 만 있다 — 링크 경로에 신원이 없어야 한다
        r = a.get("/api/i/session")
        check("msid 만으로 /api/i/session → 404 invalid_link", r.status_code == 404
              and r.json().get("code") == "invalid_link", r.text[:80])
        r = a.post("/api/i/start")
        check("msid 만으로 /api/i/start → 404", r.status_code == 404, r.text[:80])
        # 같은 브라우저에 둘 다 — 한 요청은 한 주체
        both = _client().__enter__()
        _login(both, "B")
        both.cookies.set(link.COOKIE, dev.cookies.get(link.COOKIE), path="/api/i")
        r = both.get(f"/api/sessions/{sid}")
        check("msid(B) + mlink(A 의 링크) 로 자녀 경로 → B 로만 본다 → 404",
              r.status_code == 404, str(r.status_code))
        r = both.get("/api/i/session")
        check("같은 클라이언트의 링크 경로는 링크의 회차 하나만", r.status_code == 200
              and r.json()["session_id"] == sid, str(r.status_code))
        r = b.post(f"/api/links/{rec['link_id']}/revoke")
        check("B 는 A 의 링크를 회수하지 못한다 → 404", r.status_code == 404
              and rec["revoked_at"] is None, str(r.status_code))
        r = b.post(f"/api/links/{rec['link_id']}/reissue")
        check("B 는 A 의 링크를 재발급하지 못한다 → 404", r.status_code == 404, str(r.status_code))
        r = a.get(f"/api/sessions/{sid}")
        check("발급한 자녀는 자기 경로로 그 회차를 본다", r.status_code == 200, str(r.status_code))

        # ------------------------------------------------------------ 종료 · 대화
        print("\n[종료] 끝난 뒤 읽기 전용 대화 (D6)")
        r = dev.get("/api/i/transcript", headers={H: tok})
        check("끝나기 전 → 409 not_ended", r.status_code == 409
              and r.json().get("code") == "not_ended", r.text[:80])
        ctl.fragments.append({"idx": 1, "question": "이 주제로 어떤 이야기를 나누고 싶으세요?",
                              "answer": "1996년에 딸이 초등학교에 들어갔어요."})
        r = dev.post("/api/i/session/abort")
        check("중단 → CLOSED", r.status_code == 200 and r.json()["state"] == "CLOSED", r.text[:80])
        r = dev.get("/api/i/session")
        check("닫힌 뒤에도 화면은 마지막 상태를 받는다", r.status_code == 200
              and r.json()["state"] == "CLOSED", r.text[:80])
        for _ in range(40):
            if rec["ended_at"]:
                break
            time.sleep(0.05)
        check("닫히면 링크에 끝났다고 적는다", rec["ended_at"] is not None)
        check("미리보기 → ended", dev.get("/api/i/preview", headers={H: tok}).json()["state"] == "ended")
        r = dev.post("/api/i/start", headers={H: tok})
        check("끝난 링크로 시작 → 409 ended", r.status_code == 409
              and r.json().get("code") == "ended", r.text[:80])
        r = dev.post("/api/i/session/speech", json={"text": "더"})
        check("닫힌 회차에 말 → 409", r.status_code == 409, str(r.status_code))
        with _client() as g:
            r = g.get("/api/i/transcript", headers={H: tok})
            t = r.json()
            check("대화 → 200 {theme, topic, turns:[{question, answer}]}", r.status_code == 200
                  and set(t) == {"theme", "topic", "turns"}
                  and t["turns"] == [{"question": "이 주제로 어떤 이야기를 나누고 싶으세요?",
                                      "answer": "1996년에 딸이 초등학교에 들어갔어요."}], r.text[:200])
            check("0번 조각(시작 자료)은 싣지 않는다", "시작 자료" not in r.text)
            check("읽기 전용 — 쓰는 경로가 없다",
                  g.post("/api/i/transcript", headers={H: tok}).status_code == 405)
        fl.saved[sid] = {"fragments": list(ctl.fragments)}
        sc._sessions.pop(sid, None)
        r = _client().get("/api/i/transcript", headers={H: tok})
        check("회차가 메모리에서 빠진 뒤에도 끝난 대화는 DB 에서 읽는다", r.status_code == 200
              and len(r.json()["turns"]) == 1, r.text[:80])
        r = dev.get("/api/i/session")
        check("메모리에서 빠진 끝난 회차의 진행 경로 → 409 ended", r.status_code == 409
              and r.json().get("code") == "ended", r.text[:80])

        # 링크로 마친 회차의 엽서 — 발급한 자녀가 자기 로그인으로 굽는다.
        # 회차 행의 주인은 컨트롤러가 링크에서 받은 user_id 다 (DB 에도 그 값이 들어간다).
        # 모델 · 그림은 _make 를 바꿔 끼워 건너뛰고, 주인 · 닫힘 · 말씀 검사는 진짜 make 가 본다.
        print("\n[엽서] 링크로 마친 회차를 자녀가 굽는다")
        from app.session import postcard
        me_a = a.get("/api/auth/me").json()["user"]["user_id"]
        check("링크 회차의 주인은 링크를 발급한 자녀", ctl.user_id == me_a, f"{ctl.user_id} / {me_a}")
        fl.saved[sid] = {"session_id": sid, "user_id": ctl.user_id, "closed_at": _now(),
                         "created_at": _now(), "photo_id": None, "closing_decision": None,
                         "fragments": list(ctl.fragments)}
        baked: list[tuple[str, list]] = []

        async def _fake_make(rec, said, style):
            baked.append((rec["session_id"], [f["answer"] for f in said]))
            return {"storage_key": f"postcards/{rec['session_id']}/x.jpg", "title": "",
                    "text": "모의 엽서", "caption": "", "width": 1500, "height": 1000,
                    "bytes": 1, "style": style, "created_at": _now().isoformat()}

        real_make = postcard._make
        postcard._make = _fake_make
        try:
            r = dev.post(f"/api/sessions/{sid}/postcard", json={})
            check("어르신 기기(mlink)로는 여전히 401", r.status_code == 401, str(r.status_code))
            r = b.post(f"/api/sessions/{sid}/postcard", json={})
            check("다른 자녀(B)는 404 — 회차가 있는지도 알려 주지 않는다", r.status_code == 404, r.text[:80])
            check("거절한 요청은 굽지 않았다", baked == [], str(baked))
            r = a.post(f"/api/sessions/{sid}/postcard", json={})
            check("발급한 자녀(A)는 자기 로그인으로 굽는다 · 200 · style spoken",
                  r.status_code == 200 and r.json().get("style") == "spoken", r.text[:120])
            check("구운 자료는 링크로 받은 어르신의 말씀",
                  baked == [(sid, ["1996년에 딸이 초등학교에 들어갔어요."])], str(baked))
        finally:
            postcard._make = real_make

        # 끊김 — 시작했는데 메모리에서 사라졌고 끝난 기록이 없다 (서버 재시작)
        tok3 = _issue(a, elder_a).json()["token"]
        dev3 = _client().__enter__()
        sid3 = dev3.post("/api/i/start", headers={H: tok3}).json()["session_id"]
        lost = sc._sessions.pop(sid3)
        lost.release()
        check("끊김: 미리보기 → interrupted",
              dev3.get("/api/i/preview", headers={H: tok3}).json().get("state") == "interrupted")
        r = dev3.post("/api/i/start", headers={H: tok3})
        check("끊김: 시작 → 409 interrupted · 새 회차를 만들지 않는다", r.status_code == 409
              and r.json().get("code") == "interrupted" and _mine(fl, sid3) == 1, r.text[:80])
        r = dev3.get("/api/i/session")
        check("끊김: 진행 → 409 interrupted", r.status_code == 409
              and r.json().get("code") == "interrupted", r.text[:80])

        # ------------------------------------------------------------ A4 만료 · 회수
        print("\n[A4] 만료 · 회수 · 재발급")
        tok4 = _issue(a, elder_a).json()["token"]
        rec4 = next(x for x in fl.links.values() if x["token_hash"] == link._hash(tok4))
        rec4["expires_at"] = _now() - timedelta(seconds=1)
        with _client() as g:
            for method, path in [("get", "/api/i/preview"), ("post", "/api/i/start"),
                                 ("get", "/api/i/transcript")]:
                r = getattr(g, method)(path, headers={H: tok4})
                check(f"만료된 링크 {path} → 410 expired · 준비 내용 없음",
                      r.status_code == 410 and r.json().get("code") == "expired"
                      and "입학" not in r.text, r.text[:80])
        check("만료된 링크는 회차를 만들지 않았다", rec4["session_id"] is None)

        tok5 = _issue(a, elder_a).json()["token"]
        dev5 = _client().__enter__()
        sid5 = dev5.post("/api/i/start", headers={H: tok5}).json()["session_id"]
        rec5 = fl.by_session(sid5)
        rec5["expires_at"] = _now() - timedelta(seconds=1)
        r = dev5.get("/api/i/session")
        check("시작한 링크는 기한이 지나도 진행된다 (D4)", r.status_code == 200, r.text[:80])
        check("미리보기도 in_progress",
              dev5.get("/api/i/preview", headers={H: tok5}).json().get("state") == "in_progress")
        r = a.post(f"/api/links/{rec5['link_id']}/revoke")
        check("자녀가 회수 → 200 revoked", r.status_code == 200
              and r.json()["state"] == "revoked", r.text[:80])
        check("회수하면 진행 중 회차를 중단한다", sc.get(sid5).machine.state is State.CLOSED)
        for method, path, kw in [("get", "/api/i/session", {}),
                                 ("post", "/api/i/session/speech", {"json": {"text": "x"}}),
                                 ("get", "/api/i/preview", {"headers": {H: tok5}}),
                                 ("post", "/api/i/start", {"headers": {H: tok5}}),
                                 ("get", "/api/i/photo", {})]:
            r = getattr(dev5, method)(path, **kw)
            check(f"회수 뒤 {method.upper()} {path} → 410 revoked", r.status_code == 410
                  and r.json().get("code") == "revoked", r.text[:80])
        r = a.post(f"/api/links/{rec5['link_id']}/revoke")
        check("이미 회수한 링크를 다시 회수해도 200", r.status_code == 200, str(r.status_code))

        tok6 = _issue(a, elder_a, topic="첫 직장").json()["token"]
        rec6 = next(x for x in fl.links.values() if x["token_hash"] == link._hash(tok6))
        r = a.post(f"/api/links/{rec6['link_id']}/reissue")
        new = r.json()
        check("재발급 → 201 새 토큰 · 같은 준비", r.status_code == 201
              and new["token"] != tok6 and new["topic"] == "첫 직장", r.text[:120])
        check("재발급하면 이전 링크는 회수된다", rec6["revoked_at"] is not None)
        with _client() as g:
            check("이전 토큰 → 410 revoked",
                  g.get("/api/i/preview", headers={H: tok6}).status_code == 410)
            check("새 토큰 → ready", g.get("/api/i/preview", headers={H: new["token"]})
                  .json().get("state") == "ready")
        r = a.post(f"/api/links/{rec['link_id']}/reissue")
        check("시작한 링크는 재발급하지 않는다 → 409 already_started", r.status_code == 409
              and r.json().get("code") == "already_started", r.text[:80])

        # ------------------------------------------------------------ 상한
        print("\n[상한] 꽉 찼으면 링크를 소모하지 않는다")
        tok7 = _issue(a, elder_a).json()["token"]
        rec7 = next(x for x in fl.links.values() if x["token_hash"] == link._hash(tok7))
        with _Env(MAX_LIVE_SESSIONS=str(len(sc.live_sessions()))), _client() as g:
            r = g.post("/api/i/start", headers={H: tok7})
            check("동시 회차 상한 → 503 · 링크는 시작 전 그대로", r.status_code == 503
                  and rec7["session_id"] is None and link.COOKIE not in g.cookies, r.text[:80])

        for s_ in list(sc._sessions):
            sc._sessions.pop(s_).release()
        for c in (a, b, dev, both, dev3, dev5):
            c.__exit__(None, None, None)


def test_all_checks_passed():
    """pytest 안전판 — test_flow.py 의 같은 함수 주석 참조."""
    run_once()
    assert not FAIL, "실패: " + ", ".join(FAIL)


_ran = False


def run_once():
    global _ran
    if not _ran:
        _ran = True
        run()


def main() -> int:
    print("기억의 조각 — 인터뷰 링크 검증 (모의)")
    run_once()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
