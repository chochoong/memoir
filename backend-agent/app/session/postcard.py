"""
엽서 — 끝난 회차 하나를 제목 · 본문 · 사진 한 장으로 굽는다

    DB 기록 ─→ 자료 묶기 ─→ 카드 작성 (Gemini 글, CardAgent v3) ─→ 검사 ─→ 굽기 (Pillow) ─→ 저장
               사실·발화·사진분석   title · body · caption · sources     출처    회차 사진 + 글

**프롬프트는 `prompts/CardAgent_prompt_v3.md` 다.** 팀 문서의 한 절을 그대로 둔
파일이라, 코드는 그 안의 ``` 블록만 읽는다. 새 판이 오면 파일만 바꾸면 된다.

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

**회차가 닫히면 저절로 굽는다** (auto ← controller.closed_fn). 기록 화면의
「엽서 만들기」는 다시 굽거나, 자동으로 굽지 않은 회차를 구울 때 쓴다.
수정 요청(v3 의 revision_request)은 아직 받지 않는다.

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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import photostore, store
from .conf import env_float, env_str
from .question import _client
from .shared import _facts

log = logging.getLogger("postcard")

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "CardAgent_prompt_v3.md"

DEFAULT_TEXT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_TEXT_TIMEOUT = 15.0

# v3 「분량」. 넘으면 로그만 남긴다 — 잘라 내면 말씀의 뜻이 바뀐다.
TITLE_MAX, SENTENCE_MAX, CAPTION_MAX = 15, 30, 20

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
    """회차가 엽서를 만들 상태가 아니다. 라우트가 409 로 바꾼다."""


class PostcardUnavailable(PostcardError):
    """모델·글꼴·저장소 쪽 사정이다. 라우트가 503 으로 바꾼다."""


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


# ---------------------------------------------------------------- 만들기


async def make(session_id: str, user_id: str) -> dict:
    """
    회차 하나의 엽서를 굽고 저장한다. 저장된 행을 돌려준다.

    회차가 없거나 남의 것이면 None 대신 LookupError 다 — 라우트가 404 로 바꾼다.
    """
    rec = await store.load_session(session_id)
    if rec is None or rec["user_id"] != user_id:
        raise LookupError(session_id)
    if not rec["closed_at"]:
        raise PostcardNotReady("회차를 마친 뒤에 엽서를 만들 수 있습니다")

    said = [f for f in rec["fragments"] if f["idx"] > 0 and f["answer"].strip()]
    if not said:
        raise PostcardNotReady("남은 말씀이 없어 엽서를 만들 수 없습니다")

    if session_id in _busy:
        raise PostcardNotReady("엽서를 만드는 중입니다. 잠시 기다려 주세요")
    _busy.add(session_id)
    try:
        return await _make(rec, said)
    finally:
        _busy.discard(session_id)


# 닫혀도 엽서를 굽지 않는 사유.
#   expired    어르신이 떠나신 회차다. 아무도 보지 않을 엽서에 값을 쓰지 않는다.
#   sensitive  힘든 기억에서 멈추신 회차다. 그 이야기를 엽서로 먼저 내밀지 않는다.
# 둘 다 기록 화면의 「엽서 만들기」로는 여전히 구울 수 있다.
AUTO_SKIP = ("expired", "sensitive")


async def auto(session_id: str, user_id: str, reason: str) -> None:
    """
    회차가 닫히면 엽서를 굽는다 (controller.closed_fn). **예외를 올리지 않는다.**

    기다리는 사람이 없는 배경 일이라 실패는 로그로만 남는다. 못 구운 엽서는
    기록 화면에서 다시 누르면 된다.
    """
    if reason in AUTO_SKIP:
        log.info("엽서 %s — %s 로 닫혀 굽지 않는다", session_id[:8], reason)
        return
    try:
        await make(session_id, user_id)
    except PostcardNotReady as e:
        log.info("엽서 %s — 굽지 않는다 (%s)", session_id[:8], e)
    except LookupError:
        log.warning("엽서 %s — 회차 기록이 없다 (DB 없이 도는 중?)", session_id[:8])
    except (PostcardError, store.StoreUnavailable) as e:
        log.warning("엽서 %s — 자동 굽기 실패 (%s: %s)", session_id[:8], type(e).__name__, e)
    except Exception as e:                                   # noqa: BLE001
        log.error("엽서 %s — 자동 굽기 중 예외 (%s: %s)", session_id[:8], type(e).__name__, e)


async def _make(rec: dict, said: list[dict]) -> dict:
    session_id = rec["session_id"]
    font_path = _font_path()                 # 모델 값을 쓰기 전에 먼저 본다

    photo = await _photo(rec.get("photo_id"))
    card = await write(material(rec["fragments"], photo.clues if photo else None))
    card = checked(card, {f["idx"] for f in said})

    data, w, h = await asyncio.to_thread(
        _compose, photo.data if photo else None, card, _date(rec["created_at"]), font_path)

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
    }
    try:
        old = await store.save_postcard(row)
    except store.StoreUnavailable:
        # photo.save 와 같은 보상 삭제. 행이 없으면 이 바이트를 가리킬 것이 없다.
        await _forget(key)
        raise

    if old and old != key:
        await _forget(old)

    log.info("엽서 %s — %d×%d %.0fKB · 「%s」 %s",
             session_id[:8], w, h, len(data) / 1024, card.title, " / ".join(card.sentences))
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
    회차 사진의 바이트와 분석 단서. **없거나 못 읽으면 None 이다.**

    사진은 있으면 좋은 것이지 엽서의 조건이 아니다. 사진 없이 연 회차가 원래
    길이고, 그때 엽서는 종이 바탕에 글만 얹는다.
    """
    if not photo_id:
        return None
    try:
        meta = await store.load_photo(photo_id)
        if meta is None:
            return None
        data = await photostore.current().get(meta["storage_key"])
        return Photo(data=data, mime=meta["mime"], clues=meta.get("clues"))
    except (store.StoreUnavailable, photostore.PhotoStoreError) as e:
        log.warning("회차 사진을 못 읽었다 %s (%s) — 사진 없이 굽는다",
                    photo_id[:8], type(e).__name__)
        return None


def _date(created_at: str) -> str:
    at = datetime.fromisoformat(created_at)
    return f"{at.year}. {at.month}. {at.day}."


# ---------------------------------------------------------------- 자료


def material(fragments: list[dict], clues: dict | None) -> dict:
    """
    v3 의 「사용할 자료」를 DB 기록에서 다시 세운다.

    **turn N 의 decision 은 N-1 번째 말씀을 듣고 낸 판단이다.** 조각을 저장할 때
    ctl.last_decision 이 이 조각의 질문을 만든 판단이기 때문이다 (store.save_turn).
    그래서 그 판단에서 찾은 사실은 N-1 번 턴의 말씀에 붙인다. 0번은 씨앗이라
    어르신의 말씀이 아니다 — 거기 붙을 사실은 버린다 (v3 「실제 어르신 발화 턴」).

    **마지막 말씀에서 찾은 사실은 여기 없다.** 그 판단은 다음 조각이 없어 DB 에
    내려가지 않았다. 발화 원문은 있으니 모델이 원문에서 가져가면 된다.
    """
    said = [f for f in fragments if f["idx"] > 0 and (f.get("answer") or "").strip()]
    turns = {f["idx"] for f in said}

    confirmed: list[str] = []
    found: list[dict] = []
    for f in sorted(fragments, key=lambda f: f["idx"]):
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


_FENCE = re.compile(r"^```.*?$\n(.*?)^```", re.S | re.M)


@lru_cache(maxsize=1)
def _prompt() -> str:
    """문서 한 절이 통째로 든 파일이다. ``` 블록 안이 프롬프트다. 블록이 없으면 전부."""
    try:
        doc = PROMPT.read_text(encoding="utf-8")
    except OSError as e:
        raise PostcardUnavailable(f"엽서 프롬프트를 읽지 못했습니다: {PROMPT.name}") from e
    m = _FENCE.search(doc)
    return (m.group(1) if m else doc).strip()


def _input(data: dict) -> str:
    return (
        "[자료]\n"
        "shared_state 는 인터뷰가 모은 사실과 사진 분석이다. facts_found 의 turn 은 그 사실이 "
        "나온 어르신 발화의 턴 번호다.\n"
        "utterances 의 elder 가 어르신의 원 발화이고, asked 는 인터뷰 에이전트의 질문이다. "
        "turn 이 실제 턴 번호다.\n"
        "revision_request 는 없다. 자동 생성이다.\n\n"
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
    """v3 의 JSON 을 카드로. 자동 생성에서 확인 요청이 오면 규칙을 어긴 것이다."""
    if not isinstance(out, dict):
        log.error("엽서 글 응답이 객체가 아니다: %s", str(out)[:200])
        raise PostcardUnavailable("엽서 글을 만들지 못했습니다")
    status = _text(out.get("status"))
    if status != "completed":
        log.error("엽서 글이 완료되지 않았다 (status=%s) %s",
                  status, out.get("confirmation_questions"))
        raise PostcardUnavailable("엽서 글을 만들지 못했습니다")
    sources = [s for s in out.get("sources") or [] if isinstance(s, dict)]
    return Card(title=_text(out.get("title")),
                sentences=_sentences(_text(out.get("body"))),
                caption=_text(out.get("caption")),
                sources=sources)


def checked(card: Card, turns: set[int]) -> Card:
    """
    **근거를 댈 수 없는 문장은 뺀다** (v3 「본문 출처」). 모델이 적어 온 출처가
    이 회차에 실제로 있는 턴만 가리키는지 코드가 본다.

    문장을 빼면 번호가 당겨진다. sources 도 그 번호로 다시 매긴다.
    남는 문장이 없으면 엽서를 굽지 않는다.
    """
    by: dict[int, list[int]] = {}
    for s in card.sources:
        try:
            i = int(s.get("sentence"))
            ts = sorted({int(t) for t in s.get("turns") or []})
        except (TypeError, ValueError):
            continue
        if ts and all(t in turns for t in ts):
            by[i] = sorted(set(by.get(i, [])) | set(ts))

    kept, sources = [], []
    for i, sentence in enumerate(card.sentences):
        if i not in by:
            log.warning("엽서 문장에 근거가 없어 뺀다: 「%s」", sentence)
            continue
        sources.append({"sentence": len(kept), "turns": by[i]})
        kept.append(sentence)

    if not kept:
        raise PostcardNotReady("엽서에 담을 만큼 확실한 말씀이 없습니다")

    for label, text, limit in (("제목", card.title, TITLE_MAX),
                               ("사진 설명", card.caption, CAPTION_MAX),
                               *(("본문", s, SENTENCE_MAX) for s in kept)):
        if len(text) > limit:
            log.warning("엽서 %s 이 %d자다 (v3 한도 %d자): 「%s」", label, len(text), limit, text)

    return Card(title=card.title, sentences=kept, caption=card.caption, sources=sources)


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
        raise PostcardUnavailable("회차 사진을 읽지 못했습니다") from e
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
