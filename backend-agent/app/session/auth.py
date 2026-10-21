"""
신원 — 구글 로그인과 앱 세션 (3-C1 §4 · P3-SV-02 · 03)

**두 단계는 다른 일이다.**

    구글 ID 토큰 검증     「이 사람이 구글 계정 sub 의 주인이다」   로그인 한 번
    앱 세션 쿠키 (msid)   「이 브라우저가 우리 user_id 로 로그인했다」 요청마다

ID 토큰을 쿠키에 넣어 요청마다 다시 검증하지 않는다. 한 시간이면 만료되고, 구글
공개키를 계속 받아 와야 하고, 무엇보다 끊을 수가 없다. 검증이 끝나면 새 무작위
값을 만들어 쿠키로 주고, DB 에는 그 sha256 만 둔다 (003 login_session.sid 주석).

**헤더 · 쿠키에 적힌 user_id 는 읽지 않는다.** 예전 X-User-Id 와 uid 쿠키는 누구나
바꿔 보낼 수 있었다. 이제 신원은 msid 한 곳에서만 나온다 — 라우트는 전부
`Depends(current_user)` 하나를 지난다. 개발용으로 되살리는 스위치도 두지 않는다.
시험은 FastAPI 의 dependency_overrides 로 계정을 꽂는다.

실패는 `{"detail", "code"}` 로 나간다 (엽서 409 와 같은 모양). 화면은 code 로 가른다.

    401 login_required     쿠키가 없거나 모르는 값
    401 session_expired    있던 로그인이 만료 · 로그아웃됐다
    401 invalid_token      ID 토큰의 서명 · aud · iss 가 틀렸다
    401 expired_token      ID 토큰이 만료됐다
    503 auth_unavailable   클라이언트 ID 가 없거나, 구글 · DB 에 닿지 못했다
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import Request

from . import store
from .conf import env_int, env_str

log = logging.getLogger("auth")

COOKIE = "msid"

# app_user.provider 에 적는 값.
PROVIDER = "google"


class AuthError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _login_required() -> AuthError:
    return AuthError(401, "login_required", "로그인이 필요해요")


def _expired() -> AuthError:
    return AuthError(401, "session_expired", "로그인이 끝났어요. 다시 로그인해 주세요")


# ---------------------------------------------------------------- 수명 (D3)
#
# **값은 팀이 아직 정하지 않았다** (3-C1 결정 기록 D3). 아래 기본값은 개발 중에
# 돌리기 위한 임시값이고 인수 시험의 정답이 아니다. 정해지면 .env 로 넣는다.

def max_hours() -> int:
    """로그인부터 최대 몇 시간. 0 이하는 받지 않는다."""
    return max(1, env_int("SESSION_MAX_HOURS", 24 * 7))


def idle_hours() -> int:
    """마지막 요청부터 몇 시간이면 끊는다. 0 이면 유휴 만료를 쓰지 않는다."""
    return max(0, env_int("SESSION_IDLE_HOURS", 24))


# ---------------------------------------------------------------- 구글 검증

def _verify_google(credential: str, client_id: str) -> dict:
    """
    서명 · aud · iss · exp 를 공식 라이브러리로 본다. 직접 JWT 를 풀어 믿지 않는다.

    동기 함수다 — 구글 공개키를 HTTP 로 받아 온다. 부르는 쪽이 스레드로 넘긴다.
    시험은 이 함수를 통째로 바꿔 끼운다 (네트워크 없이 aud · 만료를 흉내 낸다).
    """
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token
    return id_token.verify_oauth2_token(credential, g_requests.Request(), client_id,
                                        clock_skew_in_seconds=10)


def _classify(e: Exception) -> AuthError:
    """google-auth 는 실패를 ValueError 하나로 올린다. 문구로 만료만 가른다."""
    from google.auth import exceptions as gexc
    if isinstance(e, gexc.TransportError):
        log.warning("구글 공개키를 받지 못했다 (%s)", type(e).__name__)
        return AuthError(503, "auth_unavailable", "지금은 로그인할 수 없어요. 잠시 뒤에 다시 해 주세요")
    msg = str(e).lower()
    if "expired" in msg or "too late" in msg:
        return AuthError(401, "expired_token", "로그인 정보가 만료됐어요. 다시 로그인해 주세요")
    return AuthError(401, "invalid_token", "로그인 정보를 확인하지 못했어요")


async def verify_google(credential: str) -> dict:
    client_id = env_str("GOOGLE_CLIENT_ID")
    if not client_id:
        log.error("GOOGLE_CLIENT_ID 가 없다 — 로그인을 받지 않는다")
        raise AuthError(503, "auth_unavailable", "지금은 로그인할 수 없어요")
    if not credential or len(credential) > 4096:
        raise AuthError(401, "invalid_token", "로그인 정보를 확인하지 못했어요")
    try:
        claims = await asyncio.to_thread(_verify_google, credential, client_id)
    except Exception as e:                                   # noqa: BLE001
        err = _classify(e)
        # 토큰 · 이메일은 남기지 않는다. 왜 거절했는지만.
        log.info("구글 토큰 거절 %s (%s)", err.code, type(e).__name__)
        raise err from e
    if not claims.get("sub"):
        raise AuthError(401, "invalid_token", "로그인 정보를 확인하지 못했어요")
    return claims


# ---------------------------------------------------------------- 앱 세션

def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def login(claims: dict) -> tuple[str, str]:
    """검증된 구글 계정 → (user_id, 쿠키 원문). 원문은 여기서 한 번만 나간다."""
    user_id = await store.upsert_user(PROVIDER, str(claims["sub"]),
                                      claims.get("email"), claims.get("name"))
    raw = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=max_hours())
    await store.open_login(_hash(raw), user_id, expires)
    log.info("로그인 %s", user_id)
    return user_id, raw


async def logout(raw: str | None) -> None:
    if not raw:
        return
    h = _hash(raw)
    _cache.pop(h, None)
    await store.revoke_login(h)


# 폴링이 300ms 마다 온다. 요청마다 DB 를 보면 초당 세 번이다 — 잠깐 기억한다.
# **로그아웃은 이 프로세스 안에서 일어나므로 바로 지운다** (logout 참조). 워커는
# 하나뿐이다 (main._posture). 만료는 기억한 값으로도 판단한다.
_cache: dict[str, tuple[float, dict]] = {}
RECHECK_SECONDS = 30


def _alive(row: dict, now: datetime) -> bool:
    if row["revoked_at"] is not None or row["expires_at"] <= now:
        return False
    idle = idle_hours()
    seen = row["last_seen_at"] or row["created_at"]
    return not (idle and seen + timedelta(hours=idle) <= now)


async def _session(raw: str) -> dict:
    h = _hash(raw)
    now = datetime.now(timezone.utc)
    hit = _cache.get(h)
    if hit and time.monotonic() - hit[0] < RECHECK_SECONDS and _alive(hit[1], now):
        return hit[1]
    try:
        row = await store.load_login(h)
    except store.StoreUnavailable as e:
        raise AuthError(503, "auth_unavailable", "지금은 로그인을 확인할 수 없어요") from e
    if row is None:
        _cache.pop(h, None)
        raise _login_required()
    if not _alive(row, now):
        _cache.pop(h, None)
        raise _expired()
    try:
        await store.touch_login(h)
    except store.StoreUnavailable:
        pass                    # 마지막 사용 시각을 못 적은 것뿐이다. 요청은 계속 간다
    row = {**row, "last_seen_at": now}
    _cache[h] = (time.monotonic(), row)
    return row


async def current_login(request: Request) -> dict:
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise _login_required()
    return await _session(raw)


async def current_user(request: Request) -> str:
    """**모든 보호 라우트의 신원.** 이 함수 말고 user_id 를 얻는 길을 두지 않는다."""
    return (await current_login(request))["user_id"]
