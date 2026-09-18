"""
회차 생성 상한 — 요금에 천장을 씌운다

`POST /api/sessions` 는 인증이 없다. 터널 URL 하나가 알려지면 누구나 회차를 무한히
열 수 있고, 회차 하나는 턴마다 Gemini 1회 + Azure 전사 1회 + 합성 1회를 부른다.
악의가 없어도 요금이 새고, 악의가 있으면 API 키가 소진된다. **인증이 없는 동안
이 라우트가 지출의 유일한 입구라서**, 천장은 여기 있어야 한다.

막는 것은 둘이다.

    IP 당 생성 횟수     창(기본 10분) 안에 열 수 있는 회차 수      ← 실제 천장
    사용자당 동시 회차   닫히지 않은 채로 들고 있을 수 있는 회차 수  ← 예의

**두 번째는 보안이 아니다.** user_id 는 X-User-Id 헤더를 그대로 믿는 값이라 바꿔
넣으면 통과한다. 탭을 여러 개 띄워 둔 경우를 막는 정도이고, 로그인이 붙으면 그때
비로소 실효를 가진다. 그래서 진짜 상한은 첫 번째다.

상태는 프로세스 메모리다. 인스턴스를 늘리면 상한도 인스턴스 수만큼 늘어난다 —
그때는 Redis 로 옮겨야 한다. 지금은 한 프로세스라 이것으로 맞는다.
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque

from fastapi import Request

from .conf import env_float, env_int

log = logging.getLogger("limits")

DEFAULT_WINDOW = 600.0        # 10분
DEFAULT_MAX = 10              # 같은 IP 가 그 10분에 열 수 있는 회차
DEFAULT_USER_LIVE = 3         # 한 사용자가 동시에 들고 있을 수 있는 회차

# _hits 가 이보다 커지면 한 번 훑어 창 밖의 IP 를 버린다. 아래 _prune 참조.
PRUNE_AT = 1000

# IP -> 그 IP 가 회차를 연 시각들 (창 안의 것만 남는다)
_hits: dict[str, deque[float]] = {}


class Rejected(RuntimeError):
    """상한에 걸렸다. retry_after 는 초 단위이고 Retry-After 헤더로 나간다."""

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


OFF = ("", "0", "false", "no", "off")
XFF = ("1", "true", "yes", "on", "xff")   # 1/true 는 이 값이 flag 이던 시절의 표기다

# 모르는 값을 매 요청 경고하면 로그가 그것으로 덮인다. 값마다 한 번만 말한다.
_warned: set[str] = set()


def proxy_mode() -> str:
    """off | cf | xff — client_ip 가 어느 주소를 세는지 정한다."""
    raw = (os.environ.get("TRUST_PROXY") or "").strip().lower()
    if raw in OFF:
        return "off"
    if raw in XFF:
        return "xff"
    if raw == "cf":
        return "cf"
    if raw not in _warned:
        _warned.add(raw)
        log.warning("TRUST_PROXY=%r 는 모르는 값이다 (off/cf/xff) — off 로 돈다. "
                    "프록시 뒤라면 상한이 프록시 주소 하나만 센다", raw)
    return "off"


def client_ip(request: Request) -> str:
    """
    요청을 세는 단위.

    **기본은 소켓 주소다.** 전달 헤더는 누구나 붙일 수 있어서, 확인 없이 믿는
    순간 상한이 없는 것과 같아진다 — 매 요청에 다른 값을 넣으면 끝이다.
    앞에 프록시가 있어 실제 주소가 헤더에만 있을 때 TRUST_PROXY 로 켠다.

        off   소켓 주소 (기본)
        cf    CF-Connecting-IP — Cloudflare Tunnel 뒤
        xff   X-Forwarded-For 의 **맨 뒤** 값 — 일반 역프록시 뒤

    **맨 뒤인 것이 핵심이다.** X-Forwarded-For 는 지나온 순서대로 쌓이고,
    클라이언트가 이미 넣어 보낸 값이 있으면 프록시는 그 **뒤에 덧붙인다.**
    그래서 맨 앞은 클라이언트가 쓴 글씨이고, 맨 뒤가 바로 앞 홉이 쓴 글씨다.
    앞을 믿으면 「X-Forwarded-For: 아무거나」 한 줄로 상한이 무력해진다.
    Cloudflare 도 덧붙이는 쪽이라 cf 모드가 따로 있다 — CF-Connecting-IP 는
    엣지가 **덮어쓰므로** 클라이언트가 채워 보내도 남지 않는다.

    전제는 하나다. **그 헤더를 붙이는 프록시만 이 서버에 닿을 수 있어야 한다.**
    8010 포트가 인터넷에 직접 열려 있으면 어느 모드든 소용없다 — 터널만 열고
    포트는 막아 두는 이유다 (docs/배포.md).
    """
    mode = proxy_mode()
    if mode == "cf":
        ip = (request.headers.get("cf-connecting-ip") or "").strip()
        if ip:
            return ip
        # 헤더가 없다 = 터널을 거치지 않았다. 소켓으로 떨어진다 (보통 127.0.0.1).
    elif mode == "xff":
        hops = [h.strip() for h in
                (request.headers.get("x-forwarded-for") or "").split(",") if h.strip()]
        if hops:
            return hops[-1]
    return (request.client.host if request.client else "") or "unknown"


def user_cap() -> int:
    return env_int("USER_LIVE_MAX", DEFAULT_USER_LIVE)


def take(ip: str) -> None:
    """
    회차 생성 한 번을 센다. 창을 넘었으면 Rejected 를 던진다.

    **검사와 기록을 한 함수로 둔다.** 나누면 「검사만 하고 기록을 잊은」 호출
    경로가 생기고, 그 경로는 상한이 없는 것과 같은데 아무 표시도 나지 않는다.
    """
    window = env_float("CREATE_WINDOW_SECONDS", DEFAULT_WINDOW)
    limit = env_int("CREATE_MAX_PER_WINDOW", DEFAULT_MAX)
    if limit <= 0 or window <= 0:
        return                                  # 일부러 끈 것이다 (시험·내부용)

    now = time.monotonic()
    if len(_hits) > PRUNE_AT:
        _prune(now, window)

    q = _hits.setdefault(ip, deque())
    while q and now - q[0] >= window:
        q.popleft()

    if len(q) >= limit:
        wait = int(window - (now - q[0])) + 1
        log.warning("회차 생성 상한 — %s 가 %.0f초 안에 %d회 열었다", ip, window, len(q))
        raise Rejected(
            f"회차를 너무 자주 열었습니다. {wait}초 뒤에 다시 시도해 주세요", wait)

    q.append(now)


def _prune(now: float, window: float) -> None:
    """
    창을 벗어난 IP 를 버린다.

    이게 없으면 _hits 자체가 메모리 누수다 — IP 를 바꿔 가며 때리면 항목이
    계속 쌓인다. 매 요청에 훑으면 그 훑는 일이 비용이 되므로, dict 가 커졌을
    때만 한 번 돈다.
    """
    dead = [ip for ip, q in _hits.items() if not q or now - q[-1] >= window]
    for ip in dead:
        _hits.pop(ip, None)
    log.info("생성 기록 정리 — %d개 버리고 %d개 남음", len(dead), len(_hits))


def counted() -> int:
    """지금 세고 있는 IP 수. /api/health 에서 본다."""
    return len(_hits)


def reset() -> None:
    """시험용. 창을 기다리지 않고 비운다."""
    _hits.clear()
