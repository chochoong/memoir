"""
엽서 — 끝난 회차 하나를 그림과 문장 한 장으로 굽는다

    조각 ─→ 문장 뽑기 (Gemini 글)  ─→ 그림 (Gemini 이미지) ─→ 굽기 (Pillow) ─→ 저장
            text · scene                 scene (+ 회차 사진)       그림 + 문장

**글자는 그림 모델에게 쓰게 하지 않는다.** 이미지 모델이 그린 한글은 획이 틀리거나
없는 글자가 나온다. 어르신 말씀이 엽서에서 틀린 글자로 나오면 그건 기록이 틀린
것이다. 그래서 그림은 글자 없이 받고, 문장은 Pillow 가 글꼴로 얹는다. 문장이
DB 의 postcard.text 와 이미지 안에서 글자까지 같다는 보장이 여기서 나온다.

**한 단계다.** 뽑은 문장을 보여 주고 고치게 하지 않는다. 다시 구우면 문장과
그림이 둘 다 새로 나온다.

**키가 없으면 고정 문장으로 물러서지 않는다.** question.py 는 물러선다 — 거기는
회차가 끊기면 안 되는 자리다. 여기는 그림이 결과물의 전부라 물러설 자리가 없고,
503 을 주면 어르신은 나중에 다시 누르시면 된다.

**Pillow 는 to_thread 로 나간다.** photo.py 머리의 이유와 같다 — 이벤트 루프
하나가 모든 회차의 타이머를 돈다.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import photostore, store
from .conf import env_float, env_str
from .question import _client

log = logging.getLogger("postcard")

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "postcard_v1.txt"

DEFAULT_TEXT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"
# 그림은 수 초에서 수십 초가 걸린다. 터널(Cloudflare)이 100초에 끊으므로 그 안쪽이다.
DEFAULT_TEXT_TIMEOUT = 15.0
DEFAULT_IMAGE_TIMEOUT = 60.0

# 엽서 한 장. 가로 3:2 — 우편엽서의 비율이다.
W, H = 1500, 1000
ART_H = 760                     # 위는 그림, 아래 240px 은 문장 띠
PAPER = (247, 242, 232)
INK = (58, 48, 40)
FADED = (140, 128, 115)
JPEG_QUALITY = 88

# 문장이 넘치면 글자를 줄인다. 이 아래로는 줄이지 않고 줄을 늘린다 —
# 어르신 눈에 34px 보다 작은 글은 엽서가 아니라 약관이다.
FONT_SIZES = (50, 46, 42, 38, 34)
MAX_LINES = 2

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
class Picked:
    text: str
    scene: str


# 지금 굽고 있는 회차. 두 번 누르면 그림이 두 번 그려지고 값도 두 번 나간다.
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


async def _make(rec: dict, said: list[dict]) -> dict:
    session_id = rec["session_id"]
    font_path = _font_path()                 # 그림 값을 쓰기 전에 먼저 본다

    picked = await pick(said)
    ref = await _reference(rec.get("photo_id"))
    art = await draw(picked.scene, ref)

    data, w, h = await asyncio.to_thread(
        _compose, art, picked.text, _date(rec["created_at"]), font_path)

    key = storage_key(session_id, data)
    ps = photostore.current()
    try:
        await ps.put(key, data, "image/jpeg")
    except photostore.PhotoStoreError as e:
        raise PostcardUnavailable("엽서를 저장하지 못했습니다") from e

    row = {
        "session_id": session_id,
        "user_id": rec["user_id"],
        "text": picked.text,
        "storage_key": key,
        "mime": "image/jpeg",
        "bytes": len(data),
        "width": w,
        "height": h,
        "photo_id": rec.get("photo_id") if ref else None,
        "text_model": _text_model(),
        "image_model": _image_model(),
    }
    try:
        old = await store.save_postcard(row)
    except store.StoreUnavailable:
        # photo.save 와 같은 보상 삭제. 행이 없으면 이 바이트를 가리킬 것이 없다.
        await _forget(key)
        raise

    if old and old != key:
        await _forget(old)

    log.info("엽서 %s — %d×%d %.0fKB · 「%s」",
             session_id[:8], w, h, len(data) / 1024, picked.text)
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


async def _reference(photo_id: str | None) -> tuple[bytes, str] | None:
    """
    회차 사진의 바이트. 그림의 참고로 준다. **없거나 못 읽으면 None 이다.**

    사진은 있으면 좋은 것이지 엽서의 조건이 아니다. 사진 없이 연 회차가 원래
    길이고, 그때 그림은 문장에서 나온 장면만 보고 그린다.
    """
    if not photo_id:
        return None
    try:
        meta = await store.load_photo(photo_id)
        if meta is None:
            return None
        return await photostore.current().get(meta["storage_key"]), meta["mime"]
    except (store.StoreUnavailable, photostore.PhotoStoreError) as e:
        log.warning("참고 사진을 못 읽었다 %s (%s) — 사진 없이 그린다",
                    photo_id[:8], type(e).__name__)
        return None


def _date(created_at: str) -> str:
    at = datetime.fromisoformat(created_at)
    return f"{at.year}. {at.month}. {at.day}."


# ---------------------------------------------------------------- 모델


def _text_model() -> str:
    return env_str("POSTCARD_TEXT_MODEL") or env_str("GEMINI_MODEL", DEFAULT_TEXT_MODEL)


def _image_model() -> str:
    return env_str("POSTCARD_IMAGE_MODEL", DEFAULT_IMAGE_MODEL)


@lru_cache(maxsize=1)
def _prompt() -> str:
    try:
        return PROMPT.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise PostcardUnavailable(f"엽서 프롬프트를 읽지 못했습니다: {PROMPT.name}") from e


def _transcript(said: list[dict]) -> str:
    lines = []
    for f in said:
        if f["question"]:
            lines.append(f"질문: {f['question']}")
        lines.append(f"어르신: {f['answer'].strip()}")
    return "\n".join(lines)


async def pick(said: list[dict]) -> Picked:
    """조각에서 엽서 문장과 그릴 장면을 뽑는다. 시험이 갈아 끼우는 자리다."""
    client = _client()
    if client is None:
        raise PostcardUnavailable("GEMINI_API_KEY 가 없어 엽서를 만들 수 없습니다")

    from google.genai import types

    cfg = types.GenerateContentConfig(
        system_instruction=_prompt(),
        response_mime_type="application/json",
        temperature=0.7,
        max_output_tokens=400,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    timeout = env_float("POSTCARD_TEXT_TIMEOUT", DEFAULT_TEXT_TIMEOUT)
    try:
        res = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=_text_model(),
                contents=f"[대화]\n{_transcript(said)}",
                config=cfg),
            timeout=timeout)
        data = json.loads((res.text or "").strip())
    except asyncio.TimeoutError as e:
        raise PostcardUnavailable(f"엽서 문장이 {timeout:.0f}초 안에 오지 않았습니다") from e
    except Exception as e:                                   # noqa: BLE001
        log.error("엽서 문장 실패 (%s: %s)", type(e).__name__, str(e)[:200])
        raise PostcardUnavailable("엽서 문장을 만들지 못했습니다") from e

    text = str((data or {}).get("text") or "").strip().strip('"“”')
    scene = str((data or {}).get("scene") or "").strip()
    if not text or not scene:
        log.error("엽서 문장 응답에 빈 칸이 있다: %s", str(data)[:200])
        raise PostcardUnavailable("엽서 문장을 만들지 못했습니다")
    return Picked(text=text, scene=scene)


def _draw_prompt(scene: str, with_photo: bool) -> str:
    ref = ("함께 준 사진은 그 시절의 참고 자료입니다. 장소와 분위기, 옷차림을 따르되 "
           "사진을 그대로 옮기지 말고 그림으로 새로 그립니다.\n") if with_photo else ""
    return (
        "옛 기억을 담은 엽서의 그림을 그립니다.\n"
        f"장면: {scene}\n"
        f"{ref}"
        "따뜻하고 부드러운 수채화 풍으로, 빛바랜 옛 사진 같은 색감입니다.\n"
        "그림 안에 글자, 숫자, 간판 문구, 서명, 테두리를 넣지 않습니다.\n"
        "사람은 뒷모습이나 멀리 있는 모습으로 그리고 얼굴을 가까이 그리지 않습니다."
    )


async def draw(scene: str, ref: tuple[bytes, str] | None) -> bytes:
    """장면을 그림 한 장으로. 이미지 바이트를 돌려준다. 시험이 갈아 끼우는 자리다."""
    client = _client()
    if client is None:
        raise PostcardUnavailable("GEMINI_API_KEY 가 없어 엽서를 만들 수 없습니다")

    from google.genai import types

    cfg = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        # 그림 칸이 1500×760 (약 2:1) 이다. 가장 가까운 16:9 로 받아 위아래를 조금 자른다.
        image_config=types.ImageConfig(aspect_ratio="16:9"),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    parts = [types.Part.from_text(text=_draw_prompt(scene, ref is not None))]
    if ref:
        parts.append(types.Part.from_bytes(data=ref[0], mime_type=ref[1]))

    timeout = env_float("POSTCARD_IMAGE_TIMEOUT", DEFAULT_IMAGE_TIMEOUT)
    try:
        res = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=_image_model(),
                contents=[types.Content(role="user", parts=parts)],
                config=cfg),
            timeout=timeout)
    except asyncio.TimeoutError as e:
        raise PostcardUnavailable(f"엽서 그림이 {timeout:.0f}초 안에 오지 않았습니다") from e
    except Exception as e:                                   # noqa: BLE001
        log.error("엽서 그림 실패 (%s: %s)", type(e).__name__, str(e)[:200])
        raise PostcardUnavailable("엽서 그림을 그리지 못했습니다") from e

    for cand in res.candidates or []:
        for part in (cand.content.parts if cand.content else None) or []:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data

    # 안전 필터에 걸리면 그림 없이 끝난다. 까닭은 finish_reason 에 있다.
    why = [str(c.finish_reason) for c in res.candidates or []]
    log.error("엽서 그림 응답에 이미지가 없다 (finish=%s)", why)
    raise PostcardUnavailable("엽서 그림을 그리지 못했습니다")


# ---------------------------------------------------------------- 굽기


def _font_path() -> str:
    """글꼴 파일. **없으면 굽기 전에 멈춘다** — 기본 글꼴은 한글을 네모로 찍는다."""
    for path in (env_str("POSTCARD_FONT"), *FONT_CANDIDATES):
        if path and Path(path).is_file():
            return path
    raise PostcardUnavailable("엽서에 쓸 한글 글꼴이 없습니다 (POSTCARD_FONT)")


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(path, size)
    try:
        # 가변 글꼴이면 굵기를 중간으로. 기본값이 가는 굵기라 종이 위에서 흐리다.
        font.set_variation_by_axes([500])
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


def _compose(art: bytes, text: str, date: str, font_path: str) -> tuple[bytes, int, int]:
    """그림을 위에 채우고 아래 띠에 문장과 날짜를 얹는다. JPEG 바이트와 크기."""
    try:
        with Image.open(io.BytesIO(art)) as im:
            pic = ImageOps.fit(im.convert("RGB"), (W, ART_H), Image.Resampling.LANCZOS)
    except Exception as e:                                   # noqa: BLE001
        raise PostcardUnavailable("엽서 그림을 읽지 못했습니다") from e

    card = Image.new("RGB", (W, H), PAPER)
    card.paste(pic, (0, 0))
    ink = ImageDraw.Draw(card)

    margin = 90
    band_top, band_h = ART_H, H - ART_H
    for size in FONT_SIZES:
        font = _font(font_path, size)
        lines = _wrap(text, font, W - margin * 2)
        if len(lines) <= MAX_LINES:
            break

    lead = int(size * 1.45)
    block = lead * len(lines)
    y = band_top + (band_h - block) // 2 - 12
    for line in lines:
        ink.text((W // 2, y + lead // 2), line, font=font, fill=INK, anchor="mm")
        y += lead

    small = _font(font_path, 26)
    ink.text((W - 40, H - 30), date, font=small, fill=FADED, anchor="rs")

    buf = io.BytesIO()
    card.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue(), W, H
