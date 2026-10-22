"""
인증 검증 — 구글 로그인 · 앱 세션 · 두 계정 격리 (3-C1 · P3-SV-02 · 03)

    python -m tests.test_auth

**모의 시험이다.** 구글 서명 검증(_verify_google)과 DB 계정 함수를 메모리로 바꿔
끼운다. 실제 구글 클라이언트 · 테스트 계정으로 한 시험이 아니다 (3-R1 에 그렇게 적는다).
앱의 신원 경로(msid 쿠키 → current_user)는 진짜를 쓴다 — 시험용 헤더 신원
(tests/_auth.py)은 여기서 쓰지 않는다.

    [A1] 토큰      성공 · 서명 틀림 · aud 다름 · 만료 · 모양 틀림 · 설정 없음
    [A1] 앱 세션   쿠키 원문은 DB 에 없다 · 로그아웃 뒤 옛 쿠키 401 · 만료 · 유휴 만료
    [A2] 격리      계정 B · 미인증이 A 의 회차 · 기록 · 사진 · 엽서 · 자서전에 닿지 못한다
    [A2] 우회      X-User-Id 헤더 · uid 쿠키 · 지어낸 msid 로는 신원이 생기지 않는다
    [CSRF]         다른 출처의 쓰기 요청은 403
    [화자]         이름으로 화자를 만들고 /me 에 name 으로 나온다
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app.session import auth, memoir, postcard, store                      # noqa: E402
from app.session import controller as sc                                 # noqa: E402
from app.session import limits                                           # noqa: E402
from tests._nodb import NoDb                                              # noqa: E402

PASS, FAIL = [], []
CLIENT_ID = "test-client.apps.googleusercontent.com"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else '!! '}{name}{'  — ' + detail if detail else ''}")


class _Env:
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


def _fake_verify(credential: str, client_id: str) -> dict:
    """
    google-auth 의 verify_oauth2_token 흉내. 토큰 모양은 `종류:sub[:aud]` 다.
    실패 문구는 google-auth 가 실제로 올리는 ValueError 문구를 따랐다.
    """
    kind, _, rest = credential.partition(":")
    sub, _, aud = rest.partition(":")
    if kind == "forged":
        raise ValueError("Could not verify token signature.")
    if kind == "expired":
        raise ValueError("Token expired, 1700000000 < 1800000000")
    if kind != "ok":
        raise ValueError("Wrong number of segments in token")
    if (aud or client_id) != client_id:
        raise ValueError(f"Token has wrong audience {aud}, expected one of [{client_id!r}]")
    return {"sub": sub, "iss": "https://accounts.google.com", "aud": client_id,
            "email": f"{sub}@example.test", "name": f"이름{sub}"}


class _FakeAccounts:
    """store 의 계정 함수들을 메모리로. login_session 의 sid 는 해시만 들어온다."""

    NAMES = ("upsert_user", "open_login", "load_login", "touch_login", "revoke_login",
             "list_elders", "create_elder")

    def __enter__(self):
        self.users: dict[tuple, dict] = {}
        self.logins: dict[str, dict] = {}
        self.elders: list[dict] = []
        self.old = {n: getattr(store, n) for n in self.NAMES}
        self.old_verify = auth._verify_google

        async def upsert_user(provider, subject, email, name):
            u = self.users.setdefault((provider, subject), {"user_id": f"u_{subject}"})
            u.update(email=email, name=name)
            return u["user_id"]

        async def open_login(sid_hash, user_id, expires_at):
            self.logins[sid_hash] = {"user_id": user_id, "expires_at": expires_at,
                                     "created_at": datetime.now(timezone.utc),
                                     "last_seen_at": datetime.now(timezone.utc),
                                     "revoked_at": None}

        async def load_login(sid_hash):
            row = self.logins.get(sid_hash)
            if row is None:
                return None
            u = next(u for u in self.users.values() if u["user_id"] == row["user_id"])
            return {**row, "name": u["name"], "email": u["email"]}

        async def touch_login(sid_hash):
            self.logins[sid_hash]["last_seen_at"] = datetime.now(timezone.utc)

        async def revoke_login(sid_hash):
            if sid_hash in self.logins:
                self.logins[sid_hash]["revoked_at"] = datetime.now(timezone.utc)

        async def list_elders(user_id):
            return [{"elder_id": e["elder_id"], "display_name": e["display_name"]}
                    for e in self.elders if e["user_id"] == user_id]

        async def create_elder(user_id, display_name):
            e = {"elder_id": f"e_{len(self.elders) + 1}", "display_name": display_name,
                 "user_id": user_id}
            self.elders.append(e)
            return {"elder_id": e["elder_id"], "display_name": display_name}

        for n in self.NAMES:
            setattr(store, n, locals()[n])
        auth._verify_google = _fake_verify
        auth._cache.clear()
        return self

    def __exit__(self, *a):
        for n, f in self.old.items():
            setattr(store, n, f)
        auth._verify_google = self.old_verify
        auth._cache.clear()


def _client():
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def _login(c, sub):
    return c.post("/api/auth/google", json={"credential": f"ok:{sub}"})


# ---------------------------------------------------------------- A1

def test_login():
    print("\n[A1] 구글 토큰 → 앱 세션")
    with _Env(GOOGLE_CLIENT_ID=CLIENT_ID, AZURE_SPEECH_KEY="", GEMINI_API_KEY=""), \
            NoDb(), _FakeAccounts() as acc, _client() as c:
        r = _login(c, "111")
        body = r.json()
        check("검증된 토큰은 200 · user · elders", r.status_code == 200
              and body["user"]["user_id"] == "u_111" and body["elders"] == [], r.text[:120])
        check("화면이 쓰는 칸 이름 — user.name", body["user"].get("name") == "이름111", str(body["user"]))
        raw = c.cookies.get(auth.COOKIE)
        check("앱 세션 쿠키를 준다", bool(raw))
        sc_header = r.headers.get("set-cookie", "")
        check("쿠키는 HttpOnly · SameSite=Lax", "httponly" in sc_header.lower()
              and "samesite=lax" in sc_header.lower(), sc_header[:120])
        check("ID 토큰은 쿠키가 아니다", raw != "ok:111")
        check("DB 에는 쿠키 원문이 없고 해시만 있다",
              raw not in acc.logins and auth._hash(raw) in acc.logins)
        me = c.get("/api/auth/me")
        check("/me 는 같은 사람", me.status_code == 200 and me.json()["user"]["user_id"] == "u_111",
              me.text[:120])

        for cred, code, label in [("forged:222", "invalid_token", "서명이 틀린 토큰"),
                                  (f"ok:222:other-client", "invalid_token", "aud 가 다른 토큰"),
                                  ("expired:222", "expired_token", "만료된 토큰"),
                                  ("garbage", "invalid_token", "모양이 틀린 토큰")]:
            with _client() as c2:
                r = c2.post("/api/auth/google", json={"credential": cred})
                check(f"{label} → 401 {code} · 쿠키 없음",
                      r.status_code == 401 and r.json().get("code") == code
                      and auth.COOKIE not in c2.cookies, f"{r.status_code} {r.text[:80]}")
        check("거절한 토큰은 계정을 만들지 않았다", ("google", "222") not in acc.users)

        r = c.post("/api/auth/google", json={"credential": "x" * 5000})
        check("너무 긴 토큰은 검증에 넘기지 않는다", r.status_code == 422, str(r.status_code))

        # 로그아웃
        r = c.post("/api/auth/logout")
        check("로그아웃은 204 · 쿠키를 지운다", r.status_code == 204
              and auth.COOKIE not in c.cookies, str(r.status_code))
        check("서버 표에 끝났다고 적었다", acc.logins[auth._hash(raw)]["revoked_at"] is not None)
        c.cookies.set(auth.COOKIE, raw)
        r = c.get("/api/auth/me")
        check("옛 쿠키를 다시 들고 오면 401 session_expired",
              r.status_code == 401 and r.json().get("code") == "session_expired", r.text[:80])
        check("로그아웃은 쿠키가 없어도 204", _client().post("/api/auth/logout").status_code == 204)

    with _Env(GOOGLE_CLIENT_ID=""), NoDb(), _FakeAccounts(), _client() as c:
        r = _login(c, "111")
        check("클라이언트 ID 가 없으면 503 auth_unavailable — 로그인 성공으로 바꾸지 않는다",
              r.status_code == 503 and r.json().get("code") == "auth_unavailable", r.text[:80])


def test_expiry():
    print("\n[A1] 앱 세션 만료 · 유휴 만료")
    with _Env(GOOGLE_CLIENT_ID=CLIENT_ID, SESSION_IDLE_HOURS="2"), NoDb(), \
            _FakeAccounts() as acc, _client() as c:
        _login(c, "111")
        raw = c.cookies.get(auth.COOKIE)
        h = auth._hash(raw)
        now = datetime.now(timezone.utc)

        acc.logins[h]["expires_at"] = now - timedelta(seconds=1)
        auth._cache.clear()
        r = c.get("/api/auth/me")
        check("절대 수명이 지나면 401 session_expired", r.status_code == 401
              and r.json().get("code") == "session_expired", r.text[:80])

        acc.logins[h]["expires_at"] = now + timedelta(hours=10)
        acc.logins[h]["last_seen_at"] = now - timedelta(hours=3)
        auth._cache.clear()
        c.cookies.set(auth.COOKIE, raw)         # 만료 응답이 쿠키를 지웠다 — 다시 싣는다
        r = c.get("/api/auth/me")
        check("유휴 시간이 지나면 401 session_expired", r.status_code == 401
              and r.json().get("code") == "session_expired", r.text[:80])

        acc.logins[h]["last_seen_at"] = now - timedelta(hours=1)
        auth._cache.clear()
        c.cookies.set(auth.COOKIE, raw)
        r = c.get("/api/auth/me")
        check("유휴 시간 안이면 그대로 로그인", r.status_code == 200, r.text[:80])

        with _client() as c2:
            r = c2.get("/api/auth/me")
            check("쿠키가 없으면 401 login_required", r.status_code == 401
                  and r.json().get("code") == "login_required", r.text[:80])
            c2.cookies.set(auth.COOKIE, "made-up-value")
            r = c2.get("/api/auth/me")
            check("모르는 쿠키는 401 login_required", r.status_code == 401
                  and r.json().get("code") == "login_required", r.text[:80])


# ---------------------------------------------------------------- A2

def test_isolation():
    print("\n[A2] 두 계정 격리 · 우회 차단")
    calls = {"postcard": [], "memoir": [], "photo_bytes": 0}
    real = (postcard.make, memoir.preview, store.load_session, store.load_photo,
            store.load_postcard, store.list_sessions)

    async def fake_make(session_id, who, style="spoken"):
        calls["postcard"].append(who)
        raise LookupError(session_id)           # 남의 회차 — postcard.make 의 실제 동작

    async def fake_preview(ids, who, style="spoken"):
        calls["memoir"].append(who)
        raise memoir.NotFound("남의 것")

    async def fake_load_session(session_id):
        return {"session_id": session_id, "user_id": "u_A", "postcard": None, "fragments": []}

    async def fake_load_photo(photo_id):
        return {"photo_id": photo_id, "user_id": "u_A", "status": "stored", "sha256": "ab" * 16,
                "storage_key": "k", "mime": "image/jpeg"}

    async def fake_load_postcard(session_id):
        return {"session_id": session_id, "user_id": "u_A", "storage_key": "pc/k", "mime": "image/jpeg"}

    listed = []

    async def fake_list(user_id, limit=20, has_postcard=False):
        listed.append(user_id)
        return []

    postcard.make, memoir.preview = fake_make, fake_preview
    store.load_session, store.load_photo = fake_load_session, fake_load_photo
    store.load_postcard, store.list_sessions = fake_load_postcard, fake_list
    sc._sessions.clear()
    limits.reset()
    try:
        with _Env(GOOGLE_CLIENT_ID=CLIENT_ID, AZURE_SPEECH_KEY="", GEMINI_API_KEY="",
                  CREATE_MAX_PER_WINDOW=99), NoDb(), _FakeAccounts(), \
                _client() as a, _client() as b, _client() as anon:
            _login(a, "A")
            _login(b, "B")
            r = a.post("/api/sessions", json={"title": "A 의 회차", "seed": "씨앗", "pace": "fast"})
            sid = r.json().get("session_id", "")
            check("A 는 회차를 연다", r.status_code == 200 and sc.get(sid).user_id == "u_A", r.text[:80])
            check("A 는 자기 회차 상태를 본다", a.get(f"/api/sessions/{sid}").status_code == 200)

            routes = [
                ("GET", f"/api/sessions/{sid}", None),
                ("POST", f"/api/sessions/{sid}/tts-done", None),
                ("POST", f"/api/sessions/{sid}/speech", {"text": "남의 회차에 말하기"}),
                ("POST", f"/api/sessions/{sid}/speech/audio", b"\x00" * 10),
                ("GET", f"/api/sessions/{sid}/question/audio", None),
                ("POST", f"/api/sessions/{sid}/done", None),
                ("POST", f"/api/sessions/{sid}/abort", None),
                ("GET", f"/api/sessions/{sid}/latency", None),
                ("GET", f"/api/sessions/{sid}/record", None),
                ("GET", f"/api/photos/0191c0de-1234-4abc-8def-0123456789ab", None),
                ("GET", f"/api/sessions/{sid}/postcard", None),
                ("POST", f"/api/sessions/{sid}/postcard", None),
            ]

            def hit(c, method, path, body, **kw):
                if isinstance(body, bytes):
                    return c.request(method, path, content=body,
                                     headers={"Content-Type": "audio/webm", **kw.get("headers", {})})
                return c.request(method, path, json=body, **kw)

            before = (sc.get(sid).machine.state, len(sc.get(sid).fragments))
            for method, path, body in routes:
                rb = hit(b, method, path, body)
                ra = hit(anon, method, path, body)
                short = path.replace(sid, "{A}")
                check(f"B → {method} {short} 404", rb.status_code == 404, f"{rb.status_code} {rb.text[:60]}")
                check(f"미인증 → {method} {short} 401", ra.status_code == 401, f"{ra.status_code}")
            after = (sc.get(sid).machine.state, len(sc.get(sid).fragments))
            check("거절된 요청은 A 의 회차를 바꾸지 않았다", before == after, f"{before} → {after}")
            check("B 의 엽서 요청은 B 의 신원으로만 넘어갔다 (주인 검사는 postcard.make)",
                  calls["postcard"] == ["u_B"], str(calls["postcard"]))

            r = b.post("/api/memoirs/preview", json={"session_ids": [sid] * 3})
            check("B → 자서전 미리보기 404 · B 의 신원으로만", r.status_code == 404
                  and calls["memoir"] == ["u_B"], f"{r.status_code} {calls['memoir']}")
            check("미인증 → 자서전 미리보기 401",
                  anon.post("/api/memoirs/preview", json={"session_ids": [sid] * 3}).status_code == 401)
            check("미인증 → 사진 올리기 401",
                  anon.post("/api/photos", content=b"\xff\xd8\xff").status_code == 401)
            check("미인증 → 회차 열기 401 · 회차가 늘지 않는다",
                  anon.post("/api/sessions", json={"title": "x"}).status_code == 401
                  and len(sc._sessions) == 1, f"{len(sc._sessions)}개")
            check("거절 뒤 모델 · 저장소를 부르지 않았다",
                  calls["memoir"] == ["u_B"] and calls["postcard"] == ["u_B"])

            b.get("/api/sessions")
            a.get("/api/sessions")
            check("목록은 각자의 신원으로 거른다", listed == ["u_B", "u_A"], str(listed))

            # 우회 — 예전 신원 운반 수단은 전부 무시한다
            r = b.get(f"/api/sessions/{sid}", headers={"X-User-Id": "u_A"})
            check("X-User-Id 로 A 를 사칭해도 404", r.status_code == 404, str(r.status_code))
            r = anon.get(f"/api/sessions/{sid}", headers={"X-User-Id": "u_A"})
            check("로그인 없이 X-User-Id 만으로는 401", r.status_code == 401, str(r.status_code))
            anon.cookies.set("uid", "u_A")
            r = anon.get(f"/api/sessions/{sid}")
            check("uid 쿠키만으로는 401", r.status_code == 401, str(r.status_code))
            anon.cookies.set(auth.COOKIE, "u_A")
            r = anon.get(f"/api/sessions/{sid}")
            check("user_id 를 msid 에 넣어도 401", r.status_code == 401, str(r.status_code))
            r = anon.get("/api/sessions", headers={"X-User-Id": "dev-user"})
            check("dev-user 우회가 꺼져 있다", r.status_code == 401, str(r.status_code))

            check("A 는 여전히 자기 회차를 본다", a.get(f"/api/sessions/{sid}").status_code == 200)
            r = a.get("/api/photos/0191c0de-1234-4abc-8def-0123456789ab",
                      headers={"If-None-Match": '"' + "ab" * 16 + '"'})
            check("A 는 자기 사진에 304 를 받는다 (B · 미인증은 위에서 404 · 401)",
                  r.status_code == 304, str(r.status_code))
    finally:
        (postcard.make, memoir.preview, store.load_session, store.load_photo,
         store.load_postcard, store.list_sessions) = real
        sc._sessions.clear()
        limits.reset()


# ---------------------------------------------------------------- 요청 위조 · 화자

def test_origin_and_elders():
    print("\n[CSRF · 화자]")
    with _Env(GOOGLE_CLIENT_ID=CLIENT_ID, AZURE_SPEECH_KEY="", GEMINI_API_KEY=""), \
            NoDb(), _FakeAccounts() as acc, _client() as c:
        _login(c, "111")
        r = c.post("/api/elders", json={"name": "어머니"}, headers={"Origin": "https://evil.example"})
        check("다른 출처의 쓰기 요청은 403 bad_origin", r.status_code == 403
              and r.json().get("code") == "bad_origin", r.text[:80])
        check("거절한 요청은 화자를 만들지 않았다", acc.elders == [])
        r = c.post("/api/auth/google", json={"credential": "ok:999"},
                   headers={"Origin": "https://evil.example"})
        check("로그인 요청도 다른 출처면 403", r.status_code == 403, str(r.status_code))

        r = c.post("/api/elders", json={"name": "  어머니 "}, headers={"Origin": "http://testserver"})
        check("같은 출처면 화자를 만든다 · 201 · name", r.status_code == 201
              and r.json().get("name") == "어머니" and r.json().get("elder_id"), r.text[:80])
        r2 = c.post("/api/elders", json={"name": "어머니"})
        check("같은 이름이어도 기존 화자에 붙이지 않는다 (새 화자)",
              r2.status_code == 201 and r2.json()["elder_id"] != r.json()["elder_id"])
        me = c.get("/api/auth/me").json()
        check("/me 의 elders 는 elder_id · name", me["elders"][0] == r.json(), str(me["elders"]))
        check("빈 이름은 422", c.post("/api/elders", json={"name": "   "}).status_code == 422)
        check("미인증은 화자를 만들 수 없다",
              _client().post("/api/elders", json={"name": "x"}).status_code == 401)
        with _client() as other:
            _login(other, "222")
            check("다른 계정의 /me 에는 남의 화자가 없다", other.get("/api/auth/me").json()["elders"] == [])


def test_all_checks_passed():
    """pytest 안전판 — test_flow.py 의 같은 함수 주석 참조."""
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 인증 검증 (모의)")
    test_login()
    test_expiry()
    test_isolation()
    test_origin_and_elders()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
