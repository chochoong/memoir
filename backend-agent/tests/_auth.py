"""
시험 전용 신원 — X-User-Id 헤더를 로그인한 자녀로 읽는다.

**앱에는 이 길이 없다.** 앱의 신원은 구글 로그인 뒤의 msid 쿠키에서만 나온다
(app/session/auth.py). 라우트의 소유 · 상한 검사를 보는 시험이 구글과 DB 없이
돌도록, FastAPI 의 dependency_overrides 로 신원 함수 하나만 바꿔 끼운다.
헤더가 없으면 앱과 같은 401 login_required 다.

진짜 로그인 경로(토큰 검증 · 쿠키 · 만료 · 계정 격리)는 tests/test_auth.py 가 본다.
"""

from __future__ import annotations

from fastapi import Request

from app.session import auth


async def _from_header(request: Request) -> str:
    who = (request.headers.get("x-user-id") or "").strip()
    if not who:
        raise auth.AuthError(401, "login_required", "로그인이 필요해요")
    return who


class AsHeader:
    """app 은 들어갈 때 가져온다 — test_limits 가 app.main 을 reload 하면 app 이 새 객체다."""

    def __enter__(self):
        from app.main import app
        self.app = app
        app.dependency_overrides[auth.current_user] = _from_header
        return self

    def __exit__(self, *a):
        self.app.dependency_overrides.pop(auth.current_user, None)
