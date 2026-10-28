"""
엽서 — 끝난 회차 하나를 제목 · 본문 · 사진 한 장으로 굽는다

    DB 기록 ─→ 자료 묶기 ─→ 카드 작성 (Gemini 글, CardAgent v3) ─→ 검사 ─→ 굽기 (Pillow) ─→ 저장
               사실·발화·사진분석   title · body · caption · sources     출처    회차 사진 + 글

**프롬프트는 `첨부프롬프트_md/엽서_v3.md` 다.** 실행할 절(§2 · §5 · §5-1 · §7-4 ·
§8-2)만 담긴 문서를 roledoc 이 잇는다. 새 판이 오면 파일만 바꾸면 된다.

**그림은 그리지 않는다.** 회차를 연 사진이 있으면 그 사진을 얹고, 없으면 종이
바탕에 글만 얹는다. v3 는 「사진 속 인물 · 촬영 시점을 추측하지 않는다」를
원칙으로 둔다 — AI 가 새로 그린 장면은 그 자체가 추측이다.

**자료는 DB 에서 다시 모은다.** 회차는 닫히면 곧 메모리에서 지워지고, 기록
화면의 「엽서 만들기」는 며칠 뒤에도 눌린다. 그래서 공유 상태(ctl.state)가 아니라
turn.decision 에 턴마다 남은 facts_found · facts_retracted 를 순서대로 되감아
confirmed_facts 를 다시 세운다 (shared.merge 와 같은 규칙).

**글자는 Pillow 가 글꼴로 얹는다.** 본문이 DB 의 postcard.text 와 이미지 안에서
글자까지 같다는 보장이 여기서 나온다.

**모델의 출처(sources)를 믿지 않고 한 번 더 본다.** v3 는 「근거를 댈 수 없는 문장은
쓰지 않는다」가 원칙이다. 출처가 없거나 없는 턴을 가리키는 문장은 여기서 뺀다.

**회차가 닫혀도 굽지 않는다.** 기록 화면의 「엽서 만들기」(make)로만 굽는다.
고친 내용을 반영했거나 고칠 것이 없다고 확인한 뒤에 굽는다는 합의다 (P2-SV-01) —
닫히자마자 구우면 고치기 전 원문으로 만든 엽서가 먼저 저장된다.
수정 요청(revision_request)은 아직 받지 않는다.

**Pillow 는 to_thread 로 나간다.** photo.py 머리의 이유와 같다 — 이벤트 루프
하나가 모든 회차의 타이머를 돈다.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import photostore, roledoc, store, style as styles
from .conf import env_float, env_str
from .question import _client
from .shared import _facts

log = logging.getLogger("postcard")

PROMPT = Path(__file__).resolve().parents[2] / "첨부프롬프트_md" / "엽서_v3.md"

# 엽서.md §8-2 — 작성 공통 7키에 caption.
KEYS = ("status", "title", "body", "sources", "to_confirm",
        "missing_context", "coverage_notes", "caption")
READY, INSUFFICIENT = "ready", "insufficient_material"
NOT_FINAL = ("needs_confirmation", "needs_context")

DEFAULT_TEXT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_TEXT_TIMEOUT = 15.0

# POSTCARD_FAIL_INJECT · POSTCARD_INJECT_DELAY — 시험 서버에서만 켠다. 요청으로는
# 고를 수 없다. 화면의 busy · 실패 처리를 모델 값 없이 재현하는 자리다 (4-C1 §6).
INJECT_FAILED = "generation_failed"
_INJECTS = (INJECT_FAILED, INSUFFICIENT)
INJECT_DELAY_MAX = 120.0

# v3 「분량」. 넘으면 로그만 남긴다 — 잘라 내면 말씀의 뜻이 바뀐다.
TITLE_MAX, BODY_MAX, CAPTION_MAX = 15, 120, 20

# 엽서 한 장. 가로 3:2 — 우편엽서의 비율이다.
W, H = 1500, 1000
PHOTO_BOX = (1380, 540)         # 사진이 들어갈 칸. 사진은 자르지 않고 칸 안에 맞춘다
PHOTO_TOP = 60
PAPER = (247, 242, 232)
INK = (58, 48, 40)
FADED = (140, 128, 115)
MOUNT = (255, 255, 255)         # 사진 둘레의 흰 테 — 인화한 사진처럼
JPEG_QUALITY = 88
MARGIN = 110

# 글이 넘치면 글자를 줄인다. 이 아래로는 줄이지 않고 줄을 늘린다 —
# 어르신 눈에 34px 보다 작은 글은 엽서가 아니라 약관이다.
TITLE_SIZES = (56, 50, 44, 40)
BODY_SIZES = (44, 40, 36, 34)
CAPTION_SIZE = 28
BODY_LINES = 4

# 글꼴을 찾는 순서. POSTCARD_FONT 가 먼저다. 서버를 옮기면 거기에 맞는 경로를 준다.
FONT_CANDIDATES = (
    "C:/Windows/Fonts/NotoSerifKR-VF.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumMyeongjo.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
)


class PostcardError(RuntimeError):
    """엽서를 만들지 못했다."""


class PostcardNotReady(PostcardError):
    """
    회차가 엽서를 만들 상태가 아니다. 라우트가 409 로 바꾼다.

    409 는 원인이 넷이라 화면이 code 로 가른다 — not_closed · no_answers · busy ·
    insufficient_material(자서전과 같은 이름).
    """

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class PostcardUnavailable(PostcardError):
    """모델·글꼴·저장소 쪽 사정이다. 라우트가 503 으로 바꾼다."""


class PhotoUnavailable(PostcardUnavailable):
    """
    회차에 사진이 있는데 읽지 못했다. 503 · code photo_unavailable.

    「사진 없음」 으로 바꿔 종이 바탕으로 굽지 않는다 — 어르신이 올린 사진이 빠진
    엽서가 나가고, 그림 생성이 붙으면 모르는 그림이 대신 들어간다. 사진과 원문은
    그대로이므로 다시 누르면 된다.
    """

    code = "photo_unavailable"


class PostcardInsufficient(PostcardNotReady):
    """모델이 insufficient_material 로 답했다 — 쓸 원문이 없다. 409. 실패가 아니다."""

    def __init__(self):
        super().__init__("엽서에 담을 만큼 확실한 말씀이 없습니다", INSUFFICIENT)


class PostcardNotFinal(PostcardUnavailable):
    """
    모델이 needs_confirmation · needs_context 로 답했다. 저장하지 않는다.

    화면에는 503 하나로 나가지만 안에서는 둘을 가른다 — status 와 사유(to_confirm ·
    missing_context)를 들고 다니며 로그에 남긴다. needs_confirmation 이어도 다시
    묻지 않는다.
    """

    def __init__(self, status: str, reasons: list):
        super().__init__("엽서 글을 만들지 못했습니다")
        self.status = status
        self.reasons = reasons


@dataclass(frozen=True)
class Card:
    """v3 의 출력 중 엽서에 남는 것. sentences 는 본문을 문장으로 나눈 것이다."""
    title: str
    sentences: list[str]
    caption: str
    sources: list[dict] = field(default_factory=list)

    @property
    def body(self) -> str:
        return "\n".join(self.sentences)


@dataclass(frozen=True)
class Photo:
    data: bytes
    mime: str
    clues: dict | None


# 지금 굽고 있는 회차. 두 번 누르면 모델을 두 번 부르고 값도 두 번 나간다.
_busy: set[str] = set()


def inject() -> str:
    """지금 걸린 실패 주입. 모르는 값은 끈 것으로 읽고 로그에 남긴다 (memoir.inject 와 같다)."""
    v = env_str("POSTCARD_FAIL_INJECT").strip().lower()
    if v in ("", "off"):
        return ""
    if v not in _INJECTS:
        log.error("POSTCARD_FAIL_INJECT=%s 는 모르는 값이다 — 끈 것으로 읽는다", v)
        return ""
    return v


def inject_delay() -> float:
    """모델을 부르기 전에 쉴 초. 굽는 중(busy)인 시간을 늘려 겹친 요청을 재현한다."""
    return min(max(env_float("POSTCARD_INJECT_DELAY", 0.0), 0.0), INJECT_DELAY_MAX)


async def _injected() -> None:
    """
    모델을 부르기 바로 전 — 회차 · 말씀 검사와 busy 표시를 지난 자리다. 그래서 늦춘
    동안 같은 회차를 또 누르면 진짜와 같은 409 busy 가 난다.

    실패를 걸면 모델도 저장소도 건드리지 않는다. 옛 엽서는 그대로 남는다.
    늦추기만 걸면 그 뒤에 **실제 모델을 부른다** — 값이 든다.
    """
    delay = inject_delay()
    if delay:
        log.warning("POSTCARD_INJECT_DELAY — %.0f초 늦춘다", delay)
        await asyncio.sleep(delay)
    hook = inject()
    if hook == INJECT_FAILED:
        # 화면에는 실제 실패와 같은 문구가 나간다. 주입인 것은 로그로만 안다.
        log.warning("POSTCARD_FAIL_INJECT=generation_failed — 모델을 부르지 않고 실패한다")
        raise PostcardUnavailable("엽서 글을 만들지 못했습니다")
    if hook == INSUFFICIENT:
        raise PostcardInsufficient()


# ---------------------------------------------------------------- 만들기


async def make(session_id: str, user_id: str, style: str = styles.DEFAULT) -> dict:
    """
    회차 하나의 엽서를 굽고 저장한다. 저장된 행을 돌려준다.

    회차가 없거나 남의 것이면 None 대신 LookupError 다 — 라우트가 404 로 바꾼다.
    style 은 라우트가 styles.pick 으로 거른 값이다. 지금은 spoken 뿐이라 모델에
    보내지 않고 행에만 남긴다 (style.py 머리).
    """
    rec = await store.load_session(session_id)
    if rec is None or rec["user_id"] != user_id:
        raise LookupError(session_id)
    if not rec["closed_at"]:
        raise PostcardNotReady("회차를 마친 뒤에 엽서를 만들 수 있습니다", "not_closed")

    said = [f for f in rec["fragments"] if f["idx"] > 0 and f["answer"].strip()]
    if not said:
        raise PostcardNotReady("남은 말씀이 없어 엽서를 만들 수 없습니다", "no_answers")

    if session_id in _busy:
        raise PostcardNotReady("엽서를 만드는 중입니다. 잠시 기다려 주세요", "busy")
    _busy.add(session_id)
    try:
        return await _make(rec, said, style)
    finally:
        _busy.discard(session_id)


async def on_closed(session_id: str, user_id: str, reason: str) -> None:
    """
    회차가 닫혔다 (controller.closed_fn). **엽서는 굽지 않는다** — 머리 주석 참조.

    그래도 이 자리를 비우지 않는 것은 controller 가 closed_fn 이 있을 때만 마지막
    말씀의 판단을 회차 행에 남기기 때문이다 (_wrap_up). 그 판단이 있어야 나중에
    「엽서 만들기」가 마지막 말씀을 쓴다.
    """
    log.info("엽서 %s — %s 로 닫혔다. 「엽서 만들기」를 누를 때 굽는다", session_id[:8], reason)


async def _make(rec: dict, said: list[dict], style: str) -> dict:
    session_id = rec["session_id"]
    font_path = _font_path()                 # 모델 값을 쓰기 전에 먼저 본다
    t0 = time.perf_counter()

    photo = await _photo(rec.get("photo_id"))
    t1 = time.perf_counter()
    await _injected()
    card = await write(material(rec["fragments"], photo.clues if photo else None,
                                rec.get("closing_decision")))
    card = checked(card, {f["idx"] for f in said})
    t2 = time.perf_counter()

    data, w, h = await asyncio.to_thread(
        _compose, photo.data if photo else None, card, _date(rec["created_at"]), font_path)

    t3 = time.perf_counter()

    key = storage_key(session_id, data)
    ps = photostore.current()
    try:
        await ps.put(key, data, "image/jpeg")
    except photostore.PhotoStoreError as e:
        raise PostcardUnavailable("엽서를 저장하지 못했습니다") from e

    row = {
        "session_id": session_id,
        "user_id": rec["user_id"],
        "title": card.title,
        "text": card.body,
        "caption": card.caption,
        "sources": card.sources,
        "storage_key": key,
        "mime": "image/jpeg",
        "bytes": len(data),
        "width": w,
        "height": h,
        "photo_id": rec.get("photo_id") if photo else None,
        "text_model": _text_model(),
        "image_model": None,
        "style": style,
    }
    try:
        old, row["created_at"] = await store.save_postcard(row)
    except store.StoreUnavailable:
        # photo.save 와 같은 보상 삭제. 행이 없으면 이 바이트를 가리킬 것이 없다.
        await _forget(key)
        raise

    if old and old != key:
        await _forget(old)

    log.info("엽서 %s — %d×%d %.0fKB · 「%s」 %s",
             session_id[:8], w, h, len(data) / 1024, card.title, " / ".join(card.sentences))
    # 화면의 엽서 대기 한도 (CONFIG.card.waitMs) 를 실제 시간에 맞추는 근거
    t4 = time.perf_counter()
    log.info("엽서 %s 시간 %.0fms  (사진 %.0f · 글 %.0f · 합성 %.0f · 저장 %.0f)",
             session_id[:8], (t4 - t0) * 1000, (t1 - t0) * 1000, (t2 - t1) * 1000,
             (t3 - t2) * 1000, (t4 - t3) * 1000)
    return row


def storage_key(session_id: str, data: bytes, when: datetime | None = None) -> str:
    """사진 키와 같은 연·월 나눔. 마지막 조각은 바이트의 해시다 (photostore.KEY_OK)."""
    at = when or datetime.now(timezone.utc)
    digest = hashlib.sha256(data).hexdigest()[:16]
    return f"postcards/{at.year:04d}/{at.month:02d}/{session_id}/{digest}.jpg"


def version(key: str) -> str:
    """키의 마지막 조각(바이트 해시). 주소 꼬리와 ETag 에 쓴다."""
    return key.rsplit("/", 1)[-1].split(".", 1)[0]


async def _forget(key: str) -> None:
    try:
        await photostore.current().delete(key)
    except photostore.PhotoStoreError as e:
        log.error("엽서 바이트 정리 실패 %s (%s) — 고아 바이트가 남는다",
                  key, type(e).__name__)


async def _photo(photo_id: str | None) -> Photo | None:
    """
    회차 사진의 바이트와 분석 단서. **None 은 회차에 사진이 없다는 뜻 하나다.**

    사진 없이 연 회차가 원래 길이고, 그때 엽서는 종이 바탕에 글만 얹는다.
    사진이 있는데 못 읽으면 (행 없음 · DB · 저장소 · 깨진 바이트) PhotoUnavailable 이다.
    모델을 부르기 전에 여기서 걸러 실패할 엽서에 글 비용을 쓰지 않는다.
    """
    if not photo_id:
        return None
    try:
        meta = await store.load_photo(photo_id)
        if meta is None:
            raise PhotoUnavailable("회차 사진을 찾지 못했습니다")
        data = await photostore.current().get(meta["storage_key"])
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except PhotoUnavailable:
        log.warning("회차 사진 행이 없다 %s — 엽서를 굽지 않는다", photo_id[:8])
        raise
    except (store.StoreUnavailable, photostore.PhotoStoreError) as e:
        log.warning("회차 사진을 못 읽었다 %s (%s) — 엽서를 굽지 않는다",
                    photo_id[:8], type(e).__name__)
        raise PhotoUnavailable("회차 사진을 읽지 못했습니다") from e
    except Exception as e:                                   # noqa: BLE001 — PIL 은 여러 예외를 낸다
        log.warning("회차 사진이 깨졌다 %s (%s) — 엽서를 굽지 않는다",
                    photo_id[:8], type(e).__name__)
        raise PhotoUnavailable("회차 사진을 읽지 못했습니다") from e
    return Photo(data=data, mime=meta["mime"], clues=meta.get("clues"))


def _date(created_at: str) -> str:
    at = datetime.fromisoformat(created_at)
    return f"{at.year}. {at.month}. {at.day}."


# ---------------------------------------------------------------- 자료


def material(fragments: list[dict], clues: dict | None,
             closing: dict | None = None) -> dict:
    """
    v3 의 「사용할 자료」를 DB 기록에서 다시 세운다.

    **turn N 의 decision 은 N-1 번째 말씀을 듣고 낸 판단이다.** 조각을 저장할 때
    ctl.last_decision 이 이 조각의 질문을 만든 판단이기 때문이다 (store.save_turn).
    그래서 그 판단에서 찾은 사실은 N-1 번 턴의 말씀에 붙인다. 0번은 씨앗이라
    어르신의 말씀이 아니다 — 거기 붙을 사실은 버린다 (v3 「실제 어르신 발화 턴」).

    **마지막 말씀의 판단은 closing 이다.** 다음 조각이 없어 턴 행에 못 들어가고
    회차 행에 따로 남는다 (controller._wrap_up). 마지막 조각 다음 자리에 있는
    것처럼 끼워 넣으면 위 규칙이 그대로 마지막 말씀에 붙인다.
    """
    said = [f for f in fragments if f["idx"] > 0 and (f.get("answer") or "").strip()]
    turns = {f["idx"] for f in said}

    rows = sorted(fragments, key=lambda f: f["idx"])
    if closing and rows:
        rows.append({"idx": rows[-1]["idx"] + 1, "decision": closing})

    confirmed: list[str] = []
    found: list[dict] = []
    for f in rows:
        d = f.get("decision") or {}
        if not isinstance(d, dict):
            continue
        # shared.merge 와 같은 규칙 — 덧붙이고, 아니라고 하신 것은 지운다.
        new = _facts(d.get("facts_found"))
        for fact in new:
            if fact not in confirmed:
                confirmed.append(fact)
        gone = [g for g in _facts(d.get("facts_retracted")) if len(g) > 1]
        if gone:
            confirmed = [c for c in confirmed if not any(g in c or c in g for g in gone)]
        at = f["idx"] - 1
        if new and at in turns:
            found.append({"turn": at, "facts": new})

    # 지워진 사실은 facts_found 에서도 뺀다. v3 는 둘 다 작성 자료로 쓴다.
    alive = set(confirmed)
    found = [{"turn": x["turn"], "facts": [f for f in x["facts"] if f in alive]}
             for x in found]
    found = [x for x in found if x["facts"]]

    shared_state = {"confirmed_facts": confirmed, "facts_found": found}
    if clues:
        shared_state["photo_analyses"] = [clues]
    return {
        "shared_state": shared_state,
        # 질문은 인터뷰 에이전트의 말이다. 어르신 말씀과 한 칸에 섞지 않는다.
        "utterances": [{"turn": f["idx"], "asked": f.get("question") or "",
                        "elder": f["answer"].strip()} for f in said],
    }


# ---------------------------------------------------------------- 모델


def _text_model() -> str:
    return env_str("POSTCARD_TEXT_MODEL") or env_str("GEMINI_MODEL", DEFAULT_TEXT_MODEL)


@lru_cache(maxsize=1)
def _prompt() -> str:
    """엽서.md 에서 실행할 절만 잇는다 (roledoc). 엽서 역할 절은 §5-1."""
    try:
        return roledoc.assemble(PROMPT.read_text(encoding="utf-8"), "5-1")
    except (OSError, ValueError) as e:
        raise PostcardUnavailable(f"엽서 프롬프트를 읽지 못했습니다: {PROMPT.name} ({e})") from e


def _input(data: dict) -> str:
    return (
        "[자료]\n"
        "shared_state 는 인터뷰가 모은 사실과 사진 분석이다. facts_found 의 turn 은 그 사실이 "
        "나온 어르신 발화의 턴 번호다.\n"
        "utterances 의 elder 가 어르신의 원 발화이고, asked 는 인터뷰 에이전트의 질문이다. "
        "turn 이 실제 턴 번호다.\n"
        "revision_request 는 없다.\n"
        "승인 버전 값은 전달하지 않는다 — 버전을 비교하지 않는다. 원문이 빠졌거나 서로 "
        "어긋날 때만 needs_context 다.\n"
        "length_config 는 없다 — 문서의 기본 분량을 쓴다.\n\n"
        + json.dumps(data, ensure_ascii=False, indent=1)
    )


async def write(data: dict) -> Card:
    """자료로 카드를 쓴다 (CardAgent v3). 시험이 갈아 끼우는 자리다."""
    client = _client()
    if client is None:
        raise PostcardUnavailable("GEMINI_API_KEY 가 없어 엽서를 만들 수 없습니다")

    from google.genai import types

    cfg = types.GenerateContentConfig(
        system_instruction=_prompt(),
        response_mime_type="application/json",
        # 꾸미지 않고 옮겨 적는 일이다. 매번 다른 말이 나올 이유가 없다.
        temperature=0.3,
        max_output_tokens=1200,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    timeout = env_float("POSTCARD_TEXT_TIMEOUT", DEFAULT_TEXT_TIMEOUT)
    try:
        res = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=_text_model(), contents=_input(data), config=cfg),
            timeout=timeout)
        out = json.loads((res.text or "").strip())
    except asyncio.TimeoutError as e:
        raise PostcardUnavailable(f"엽서 글이 {timeout:.0f}초 안에 오지 않았습니다") from e
    except Exception as e:                                   # noqa: BLE001
        log.error("엽서 글 실패 (%s: %s)", type(e).__name__, str(e)[:200])
        raise PostcardUnavailable("엽서 글을 만들지 못했습니다") from e
    return parse(out)


def _text(v) -> str:
    return str(v or "").strip().strip('"“”')


def _sentences(body: str) -> list[str]:
    """
    v3 는 본문 문장 사이를 줄바꿈으로 둔다 (「문장 사이 줄바꿈은 제외」). 한 줄로
    오면 마침표 뒤에서 나눈다 — sources 의 sentence 번호가 이 순서를 가리킨다.
    """
    lines = [s.strip() for s in body.splitlines() if s.strip()]
    if len(lines) > 1:
        return lines
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+", body) if s.strip()]


def parse(out) -> Card:
    """
    엽서.md §8-2 의 8키 JSON 을 카드로. 굽는 것은 ready 뿐이다.

        insufficient_material              PostcardInsufficient (409) — 쓸 원문이 없다
        needs_confirmation · needs_context PostcardNotFinal (503) — 저장하지 않는다
        그 밖의 값                          PostcardUnavailable (503)

    키가 8개와 다르면 로그만 남긴다. 굽는 데 쓰는 키는 title · body · caption · sources 다.
    """
    if not isinstance(out, dict):
        log.error("엽서 글 응답이 객체가 아니다: %s", str(out)[:200])
        raise PostcardUnavailable("엽서 글을 만들지 못했습니다")
    if set(out) != set(KEYS):
        log.warning("엽서 글 응답의 키가 §8-2 와 다르다: %s", sorted(out))
    status = _text(out.get("status"))
    if status == INSUFFICIENT:
        log.info("엽서 글 — 자료 부족 %s", out.get("coverage_notes"))
        raise PostcardInsufficient()
    if status in NOT_FINAL:
        reasons = out.get("to_confirm" if status == "needs_confirmation" else "missing_context")
        log.error("엽서 글이 최종본이 아니다 (status=%s) %s", status, reasons)
        raise PostcardNotFinal(status, reasons if isinstance(reasons, list) else [])
    if status != READY:
        log.error("엽서 글의 status 를 모른다: %r", status)
        raise PostcardUnavailable("엽서 글을 만들지 못했습니다")
    sources = [s for s in out.get("sources") or [] if isinstance(s, dict)]
    return Card(title=_text(out.get("title")),
                sentences=_sentences(_text(out.get("body"))),
                caption=_text(out.get("caption")),
                sources=sources)


def checked(card: Card, turns: set[int]) -> Card:
    """
    출처(v3 「본문 출처」)와 분량을 본다. **문장은 빼지 않고 로그만 남긴다** —
    엽서 글은 에이전트가 쓴 그대로다.

    sources 에는 이 회차에 실제로 있는 턴만 가리키는 항목만 남긴다.
    본문이 비었으면 엽서를 굽지 않는다.
    """
    if not card.sentences:
        raise PostcardInsufficient()

    by: dict[int, list[int]] = {}
    for s in card.sources:
        try:
            i = int(s.get("sentence"))
            ts = sorted({int(t) for t in s.get("turns") or []})
        except (TypeError, ValueError):
            log.warning("엽서 출처를 읽지 못했다: %s", s)
            continue
        if not ts or not all(t in turns for t in ts):
            log.warning("엽서 출처가 이 회차의 턴이 아니다: %s (턴 %s)", s, sorted(turns))
            continue
        by[i] = sorted(set(by.get(i, [])) | set(ts))

    for i, sentence in enumerate(card.sentences):
        if i not in by:
            log.warning("엽서 문장에 근거가 없다: 「%s」 (받은 출처 %s)", sentence, card.sources)

    for label, text, limit in (("제목", card.title, TITLE_MAX),
                               ("사진 설명", card.caption, CAPTION_MAX),
                               ("본문", "".join(card.sentences), BODY_MAX)):
        if len(text) > limit:
            log.warning("엽서 %s 이 %d자다 (v3 한도 %d자): 「%s」", label, len(text), limit, text)

    sources = [{"sentence": i, "turns": ts} for i, ts in sorted(by.items())]
    return Card(title=card.title, sentences=card.sentences, caption=card.caption, sources=sources)


# ---------------------------------------------------------------- 굽기


def _font_path() -> str:
    """글꼴 파일. **없으면 굽기 전에 멈춘다** — 기본 글꼴은 한글을 네모로 찍는다."""
    for path in (env_str("POSTCARD_FONT"), *FONT_CANDIDATES):
        if path and Path(path).is_file():
            return path
    raise PostcardUnavailable("엽서에 쓸 한글 글꼴이 없습니다 (POSTCARD_FONT)")


def _font(path: str, size: int, weight: int = 500) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(path, size)
    try:
        # 가변 글꼴이면 굵기를 준다. 기본값이 가는 굵기라 종이 위에서 흐리다.
        font.set_variation_by_axes([weight])
    except (OSError, AttributeError, ValueError):
        pass                                 # 가변 글꼴이 아니다
    return font


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """띄어쓰기에서 끊는다. 한 낱말이 칸보다 길 때만 글자 사이에서 끊는다."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if font.getlength(trial) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = ""
        for ch in word:
            if font.getlength(line + ch) > width and line:
                lines.append(line)
                line = ""
            line += ch
    if line:
        lines.append(line)
    return lines


def _fit(texts: list[str], path: str, sizes: tuple[int, ...], width: int,
         max_lines: int, weight: int = 500) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """들어갈 때까지 글자를 줄인다. 가장 작은 크기에서도 넘치면 줄을 늘린다."""
    for size in sizes:
        font = _font(path, size, weight)
        lines = [ln for t in texts for ln in _wrap(t, font, width)]
        if len(lines) <= max_lines:
            break
    return font, lines


def _mounted(photo: bytes) -> Image.Image:
    """사진을 **자르지 않고** 칸 안에 맞추고 흰 테를 두른다. 가족사진의 머리를 자르지 않는다."""
    border = 14
    box = (PHOTO_BOX[0] - border * 2, PHOTO_BOX[1] - border * 2)
    try:
        with Image.open(io.BytesIO(photo)) as im:
            pic = ImageOps.contain(ImageOps.exif_transpose(im).convert("RGB"),
                                   box, Image.Resampling.LANCZOS)
    except Exception as e:                                   # noqa: BLE001
        raise PhotoUnavailable("회차 사진을 읽지 못했습니다") from e
    return ImageOps.expand(pic, border=border, fill=MOUNT)


def _compose(photo: bytes | None, card: Card, date: str,
             font_path: str) -> tuple[bytes, int, int]:
    """
    사진이 있으면 위에 사진과 설명, 아래에 제목과 본문. 없으면 가운데에 제목과 본문.
    JPEG 바이트와 크기를 돌려준다.
    """
    sheet = Image.new("RGB", (W, H), PAPER)
    ink = ImageDraw.Draw(sheet)
    width = W - MARGIN * 2

    top = MARGIN
    if photo is not None:
        pic = _mounted(photo)
        sheet.paste(pic, ((W - pic.width) // 2, PHOTO_TOP))
        top = PHOTO_TOP + pic.height + 16
        if card.caption:
            cap = _font(font_path, CAPTION_SIZE)
            ink.text((W // 2, top), card.caption, font=cap, fill=FADED, anchor="ma")
            top += int(CAPTION_SIZE * 1.5)
        top += 20

    tfont, tlines = _fit([card.title] if card.title else [], font_path,
                         TITLE_SIZES, width, 1, weight=700)
    room = BODY_LINES if photo is None else 3
    bfont, blines = _fit(card.sentences, font_path, BODY_SIZES, width, room)

    tlead = int(tfont.size * 1.35)
    blead = int(bfont.size * 1.5)
    gap = int(bfont.size * 0.6) if tlines else 0
    block = tlead * len(tlines) + gap + blead * len(blines)

    bottom = H - 60
    y = top + max(0, (bottom - top - block) // 2)
    for line in tlines:
        ink.text((W // 2, y), line, font=tfont, fill=INK, anchor="ma")
        y += tlead
    y += gap
    for line in blines:
        ink.text((W // 2, y), line, font=bfont, fill=INK, anchor="ma")
        y += blead

    small = _font(font_path, 26)
    ink.text((W - 40, H - 30), date, font=small, fill=FADED, anchor="rs")

    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue(), W, H
