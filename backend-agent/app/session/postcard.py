"""
엽서 — 끝난 회차 하나를 그림과 문장 한 장으로 남긴 것의 저장

    구운 바이트 ─→ PhotoStore (postcards/…) ─→ postcard 행 (회차당 한 장)

여기는 **굽지 않는다.** 문장과 그림을 만드는 쪽이 다 구운 바이트를 save 에
넘긴다. 저장은 사진과 같은 PhotoStore 에 하고, 행은 그 키를 가리킨다.

**다시 저장하면 덮어쓰고 옛 바이트를 지운다.** 회차당 한 장이 저장소에서도
한 장이어야 한다. 키의 끝은 바이트의 해시라서, 다시 저장하면 주소와 ETag 가
바뀌어 브라우저가 옛 엽서를 캐시에서 꺼내 보이지 않는다.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from . import photostore, store

log = logging.getLogger("postcard")


class PostcardUnavailable(RuntimeError):
    """저장소 쪽 사정으로 엽서를 두지 못했다. 503 에 해당한다."""


async def save(session_id: str, user_id: str, data: bytes, text: str, *,
               width: int, height: int, mime: str = "image/jpeg",
               photo_id: str | None = None, text_model: str | None = None,
               image_model: str | None = None) -> dict:
    """
    구운 엽서를 저장하고 저장된 행을 돌려준다.

    바이트를 먼저 두고 행을 넣는다. 행을 못 넣으면 방금 둔 바이트를 지운다 —
    photo.save 와 같은 보상 삭제다. 행을 덮어썼으면 옛 바이트를 지운다.
    """
    if mime not in photostore.EXT:
        raise ValueError(f"엽서로 둘 수 없는 형식: {mime}")
    key = storage_key(session_id, data, mime)
    try:
        await photostore.current().put(key, data, mime)
    except photostore.PhotoStoreError as e:
        raise PostcardUnavailable("엽서를 저장하지 못했습니다") from e

    row = {
        "session_id": session_id,
        "user_id": user_id,
        "text": text,
        "storage_key": key,
        "mime": mime,
        "bytes": len(data),
        "width": width,
        "height": height,
        "photo_id": photo_id,
        "text_model": text_model,
        "image_model": image_model,
    }
    try:
        old = await store.save_postcard(row)
    except store.StoreUnavailable:
        await _forget(key)
        raise

    if old and old != key:
        await _forget(old)

    log.info("엽서 %s — %d×%d %.0fKB · 「%s」",
             session_id[:8], width, height, len(data) / 1024, text)
    return row


def storage_key(session_id: str, data: bytes, mime: str = "image/jpeg",
                when: datetime | None = None) -> str:
    """사진 키와 같은 연·월 나눔. 마지막 조각은 바이트의 해시다 (photostore.KEY_OK)."""
    at = when or datetime.now(timezone.utc)
    digest = hashlib.sha256(data).hexdigest()[:16]
    return f"postcards/{at.year:04d}/{at.month:02d}/{session_id}/{digest}.{photostore.EXT[mime]}"


def version(key: str) -> str:
    """키의 마지막 조각(바이트 해시). 주소 꼬리와 ETag 에 쓴다."""
    return key.rsplit("/", 1)[-1].split(".", 1)[0]


async def _forget(key: str) -> None:
    try:
        await photostore.current().delete(key)
    except photostore.PhotoStoreError as e:
        log.error("엽서 바이트 정리 실패 %s (%s) — 고아 바이트가 남는다",
                  key, type(e).__name__)
