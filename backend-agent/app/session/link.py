"""
인터뷰 링크 — 로그인 없이 회차 하나만 진행하는 권한 (3-C1 §5 · P3-SV-04 · 05)

자녀가 회차를 준비하고 링크를 받는다. 받은 사람은 그 링크로 **그 회차 하나만**
진행한다. 자녀의 기록 · 사진 · 엽서 · 자서전에는 닿지 않는다.

    링크 토큰 (X-Interview-Token)   「이 준비로 회차를 열어도 된다」   미리보기 · 시작 · 대화 읽기
    기기 쿠키 (mlink)               「이 기기가 그 회차를 시작했다」     진행 · 질문 소리 · 보조 사진

토큰은 주소의 `#` 뒤에 있어 서버 로그에 남지 않는다. 화면이 읽어 헤더로 보낸다.
기기 쿠키는 시작할 때 한 번 준다 — `<audio>` · `<img>` 는 헤더를 못 싣기 때문이고,
D5 「진행은 시작한 기기에서만」을 이 쿠키로 가른다.

**권한을 합치지 않는다.** `/api/i/*` 는 이 둘만 본다 (msid 를 읽지 않는다). 자녀
경로는 msid 만 본다 — mlink 는 Path=/api/i 라 애초에 실려 가지 않는다.

상태는 DB enum 이 아니다. 매번 표와 메모리의 회차를 보고 판단한다 (state_of).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from . import controller as sc
from . import postcard, store
from .auth import AuthError
from .conf import env_int
from .machine import State

log = logging.getLogger("link")

COOKIE = "mlink"
HEADER = "x-interview-token"
COOKIE_PATH = "/api/i"

# 기기 쿠키의 수명. 진행 중 회차는 활동이 없으면 스윕이 닫으므로 (controller) 이보다
# 오래 이어질 일이 없다. 끝난 뒤의 대화 읽기는 쿠키가 아니라 링크 토큰으로 한다.
DEVICE_HOURS = 24

# 화면이 보조 사진을 받는 주소. 링크에 지정된 사진 한 장뿐이라 id 가 없다.
PHOTO_URL = "/api/i/photo"


class LinkError(AuthError):
    """`{"detail", "code"}` 로 나간다 — main 의 AuthError 처리기가 그대로 받는다."""


# ---------------------------------------------------------------- 수명 (D4)
#
# **시작 전 유효 기간은 팀이 아직 정하지 않았다** (3-C1 결정 기록 D4). 기본값은
# 개발 중에 돌리기 위한 임시값이다. 정해지면 .env 로 넣는다.

def link_hours() -> int:
    return max(1, env_int("LINK_HOURS", 72))


# ---------------------------------------------------------------- 오류

def invalid() -> LinkError:
    return LinkError(404, "invalid_link", "열 수 없는 링크예요. 보내 준 분께 다시 받아 주세요")


_GONE = {
    "revoked": LinkError(410, "revoked", "더 이상 쓸 수 없는 링크예요. 보내 준 분께 새 링크를 받아 주세요"),
    "expired": LinkError(410, "expired", "기한이 지난 링크예요. 보내 준 분께 새 링크를 받아 주세요"),
}
_STUCK = {
    "ended": LinkError(409, "ended", "이미 마친 인터뷰예요"),
    "interrupted": LinkError(409, "interrupted",
                             "인터뷰가 중간에 끊겼어요. 보내 준 분께 새 링크를 부탁해 주세요"),
    "in_progress_elsewhere": LinkError(409, "in_progress_elsewhere",
                                       "다른 기기에서 진행 중인 인터뷰예요"),
    "not_ended": LinkError(409, "not_ended", "아직 마치지 않은 인터뷰예요"),
}


def stuck(code: str) -> LinkError:
    return _STUCK[code]


def unavailable() -> LinkError:
    return LinkError(503, "link_unavailable", "지금은 링크를 확인할 수 없어요. 잠시 뒤에 다시 해 주세요")


def now() -> datetime:
    return datetime.now(timezone.utc)


async def read(coro):
    """링크 · 화자 표를 못 읽으면 503 link_unavailable. 빈 결과로 바꾸지 않는다."""
    try:
        return await coro
    except store.StoreUnavailable as e:
        raise unavailable() from e


# ---------------------------------------------------------------- 발급

def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def issue(user_id: str, prep: dict) -> tuple[dict, str]:
    """준비 → 새 링크. 토큰 원문은 여기서 한 번만 나간다 (표에는 해시만)."""
    raw = secrets.token_urlsafe(32)
    rec = {
        "link_id": f"l_{uuid.uuid4().hex}", "token_hash": _hash(raw), "user_id": user_id,
        "elder_id": prep["elder_id"], "title": prep["title"], "seed": prep["seed"],
        "theme": prep["theme"], "topic": prep["topic"], "photo_id": prep["photo_id"],
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=link_hours()),
    }
    await read(store.create_link(rec))
    log.info("링크 발급 %s (화자 %s)", rec["link_id"], prep["elder_id"])
    return {**rec, "session_id": None, "device_hash": None, "created_at": datetime.now(timezone.utc),
            "revoked_at": None, "started_at": None, "ended_at": None}, raw


# ---------------------------------------------------------------- 상태

def state_of(link: dict, now: datetime | None = None) -> str:
    """
    ready · in_progress · ended · interrupted · expired · revoked

    **시작한 링크는 진행 중에 만료되지 않는다** (D4). 기한은 시작 전, 그리고 끝난
    뒤의 대화 읽기에만 걸린다.

    끊김(interrupted)은 시작했는데 회차가 메모리에 없고 끝났다는 기록도 없는 것이다 —
    서버가 다시 떴다. 진행 중 회차는 메모리에만 있어서 되살리지 않는다.
    """
    now = now or datetime.now(timezone.utc)
    if link["revoked_at"] is not None:
        return "revoked"
    if link["session_id"] is None:
        return "expired" if link["expires_at"] <= now else "ready"
    ctl = sc.get(link["session_id"])
    if ctl is not None and ctl.machine.state is not State.CLOSED and link["ended_at"] is None:
        return "in_progress"
    done = "ended" if (link["ended_at"] is not None or ctl is not None) else "interrupted"
    return "expired" if link["expires_at"] <= now else done


def gone(state: str) -> None:
    """회수 · 만료는 어느 입구에서나 410 이고 준비 내용을 싣지 않는다."""
    if state in _GONE:
        raise _GONE[state]


async def by_token(raw: str | None) -> dict:
    if not raw or len(raw) > 200:
        raise invalid()
    link = await read(store.load_link_by_token(_hash(raw)))
    if link is None:
        raise invalid()
    return link


async def by_device(raw: str | None) -> dict:
    if not raw or len(raw) > 200:
        raise invalid()
    link = await read(store.load_link_by_device(_hash(raw)))
    if link is None:
        raise invalid()
    return link


def view(link: dict, state: str) -> dict:
    """미리보기 · 시작 응답에 같이 싣는 준비 내용. 화자 · 발급자는 싣지 않는다."""
    return {"state": state, "theme": link["theme"], "topic": link["topic"],
            "photo_url": PHOTO_URL if link["photo_id"] else None}


def summary(link: dict) -> dict:
    """자녀 화면의 링크 목록 한 줄. 토큰은 없다 — 표에도 해시만 있다."""
    return {
        "link_id": link["link_id"], "elder_id": link["elder_id"], "title": link["title"],
        "theme": link["theme"], "topic": link["topic"], "state": state_of(link),
        "session_id": link["session_id"],
        "created_at": link["created_at"].isoformat(), "expires_at": link["expires_at"].isoformat(),
    }


# ---------------------------------------------------------------- 시작 · 종료

# 시작을 링크마다 줄 세운다. 두 번 누른 요청이 동시에 오면 늦은 쪽이 「묶였는데
# 회차가 아직 메모리에 없는」 순간을 읽어 끊김으로 오판한다. 워커는 하나라
# (main._posture) 프로세스 안의 잠금으로 충분하다. DB 의 조건부 UPDATE 는 그대로 둔다.
_starting: dict[str, asyncio.Lock] = {}


class starting:
    """`async with starting(link_id):` — 그 링크의 시작 하나만 들어간다."""

    def __init__(self, link_id: str):
        self.link_id = link_id
        self.lock = _starting.setdefault(link_id, asyncio.Lock())

    async def __aenter__(self):
        await self.lock.acquire()

    async def __aexit__(self, *a):
        self.lock.release()
        if not self.lock.locked() and _starting.get(self.link_id) is self.lock:
            _starting.pop(self.link_id, None)


async def claim(link: dict, session_id: str) -> str | None:
    """시작 전 링크에 회차를 묶는다. 성공하면 기기 쿠키 원문, 이미 누가 묶었으면 None."""
    raw = secrets.token_urlsafe(32)
    ok = await read(store.claim_link(link["link_id"], session_id, _hash(raw)))
    return raw if ok else None


def device_matches(raw: str | None, device_hash: str | None) -> bool:
    return bool(raw) and bool(device_hash) and secrets.compare_digest(_hash(raw), device_hash)


async def on_closed(session_id: str, user_id: str, reason: str) -> None:
    """링크로 연 회차가 닫혔다 (controller.closed_fn). 끝났다고 적고 엽서 쪽 뒷일을 잇는다."""
    try:
        await store.end_link(session_id)
    except store.StoreUnavailable:
        # 메모리의 회차가 남아 있는 동안은 상태가 ended 로 보인다. 스윕 뒤에는
        # interrupted 로 보인다 — 대화는 DB 에 있으나 링크로는 읽지 못한다.
        log.error("링크 종료를 적지 못했다 %s", session_id[:8])
    await postcard.on_closed(session_id, user_id, reason)
