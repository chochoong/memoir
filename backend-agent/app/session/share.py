"""
자서전 공유 링크 — 로그인 없이 책 한 권을 읽기만 하는 권한 (014)

    POST /api/shares                 자녀가 책을 보낸다 → {share_id, token, url}. 토큰은 여기서 한 번만
    GET  /api/shares                 내가 낸 공유 (토큰 없이)
    POST /api/shares/{id}/revoke     끈다. 그 뒤로 링크는 410
    GET  /api/b                      받은 사람. X-Share-Token 헤더 → 책
    GET  /b#<토큰>                   받은 사람이 여는 읽기 화면 (share_page.html)

**자서전은 저장하지 않는다** (7-C1 §4). 책은 자녀 기기에만 있고, 이 표에는 「링크로
공유」 를 누른 그 책 한 권만 들어간다. 그래서 본문은 화면이 보내 준다 — 서버가 가진
자서전 작업은 30분 뒤 사라지고, 책의 뒷장 일부는 서버가 다듬지 않은 엽서 글이다.

화면이 보낸 글을 그대로 남의 눈앞에 내놓는 것이라 **모양과 크기를 묶는다.** 글자만
받고(HTML 없음) 읽기 화면도 textContent 로만 그린다. 로그인한 사람만 낼 수 있고,
켜 둔 공유는 한 사람에 MAX_LIVE 개까지다.

토큰은 주소의 `#` 뒤에 있어 서버 로그에 남지 않는다 — 인터뷰 링크(link.py)와 같다.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid

from . import store
from .auth import AuthError
from .conf import env_int

log = logging.getLogger("share")

HEADER = "x-share-token"
PATH = "/b"

MAX_LIVE = 50                 # 한 사람이 켜 둘 수 있는 공유
MAX_CHAPTERS = 60
MAX_PARAS = 400               # 장 하나의 문단
MAX_SENTENCES = 200           # 문단 하나의 문장
MAX_TITLE = 200
MAX_LINE = 600                # 다듬은 글 · 안내 한 줄
MAX_CHARS = 300_000           # 책 전체의 글자


class ShareError(AuthError):
    """`{"detail", "code"}` 로 나간다 — main 의 AuthError 처리기가 그대로 받는다."""


def bad(detail: str) -> ShareError:
    return ShareError(400, "bad_book", detail)


def invalid() -> ShareError:
    return ShareError(404, "invalid_share", "공유 링크를 찾을 수 없어요")


def revoked() -> ShareError:
    return ShareError(410, "share_revoked", "공유가 꺼진 자서전이에요")


def too_many() -> ShareError:
    return ShareError(409, "too_many_shares", "켜 둔 공유가 너무 많아요. 쓰지 않는 공유를 꺼 주세요")


def unavailable() -> ShareError:
    return ShareError(503, "share_unavailable", "지금은 공유를 불러오지 못해요")


def max_live() -> int:
    return max(1, env_int("SHARE_MAX_LIVE", MAX_LIVE))


async def read(coro):
    """공유 표를 못 읽으면 503. 빈 결과로 바꾸지 않는다."""
    try:
        return await coro
    except store.StoreUnavailable as e:
        raise unavailable() from e


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------- 책 모양

def _text(v, limit: int, what: str, need: bool = False) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise bad(f"{what} 는 글이어야 해요")
    v = v.strip()
    if need and not v:
        raise bad(f"{what} 가 비었어요")
    if len(v) > limit:
        raise bad(f"{what} 가 너무 길어요")
    return v


def clean_book(body: dict) -> dict:
    """
    화면의 책(bookView 모양) → 저장할 책. 모르는 칸은 버리고, 모양이 틀리면 400 bad_book.

        {title, subtitle?, draft?, made?, chapters: [{title, paras: [[문장, …], …], draft?}]}
    """
    if not isinstance(body, dict):
        raise bad("책이 없어요")
    title = _text(body.get("title"), MAX_TITLE, "제목", need=True)
    chapters = body.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise bad("장이 없어요")
    if len(chapters) > MAX_CHAPTERS:
        raise bad("장이 너무 많아요")
    out, total = [], 0
    for i, ch in enumerate(chapters, 1):
        if not isinstance(ch, dict):
            raise bad("장의 모양이 틀려요")
        paras = ch.get("paras")
        if not isinstance(paras, list) or len(paras) > MAX_PARAS:
            raise bad("문단의 모양이 틀려요")
        clean = []
        for p in paras:
            if isinstance(p, str):
                p = [p]
            if not isinstance(p, list) or len(p) > MAX_SENTENCES:
                raise bad("문단의 모양이 틀려요")
            ss = [_text(s, MAX_LINE * 10, "문장") for s in p]
            ss = [s for s in ss if s]
            if ss:
                total += sum(len(s) for s in ss)
                clean.append(ss)
        if total > MAX_CHARS:
            raise bad("책이 너무 길어요")
        out.append({"no": i, "title": _text(ch.get("title"), MAX_TITLE, "장 제목"),
                    "paras": clean, "draft": bool(ch.get("draft"))})
    return {"title": title,
            "subtitle": _text(body.get("subtitle"), MAX_TITLE, "부제"),
            "draft": _text(body.get("draft"), MAX_LINE, "안내"),
            "made": _text(body.get("made"), 40, "만든 날"),
            "chapters": out}


# ---------------------------------------------------------------- 발급 · 읽기

async def issue(user_id: str, book_id: str, book: dict) -> tuple[dict, str]:
    """책 → 새 공유. 토큰 원문은 여기서 한 번만 나간다 (표에는 해시만)."""
    if await read(store.count_live_shares(user_id)) >= max_live():
        raise too_many()
    raw = secrets.token_urlsafe(24)
    rec = {"share_id": f"s_{uuid.uuid4().hex}", "token_hash": _hash(raw), "user_id": user_id,
           "book_id": book_id, "title": book["title"], "book": book}
    await read(store.create_share(rec))
    log.info("자서전 공유 %s (%d장)", rec["share_id"], len(book["chapters"]))
    return rec, raw


async def by_token(raw: str | None) -> dict:
    """받은 사람의 토큰 → 책. 모르는 토큰 404, 끈 공유 410 (본문 없이)."""
    if not raw or len(raw) > 200:
        raise invalid()
    rec = await read(store.load_share_by_token(_hash(raw)))
    if rec is None:
        raise invalid()
    if rec["revoked_at"] is not None:
        raise revoked()
    return rec


def summary(rec: dict) -> dict:
    """자녀에게 보이는 공유 한 줄. 토큰은 싣지 않는다 (다시 보여 줄 수 없다)."""
    return {"share_id": rec["share_id"], "book_id": rec.get("book_id") or "", "title": rec["title"],
            "chapters": len((rec.get("book") or {}).get("chapters") or []),
            "created_at": rec.get("created_at"), "revoked_at": rec.get("revoked_at"),
            "live": rec.get("revoked_at") is None}
