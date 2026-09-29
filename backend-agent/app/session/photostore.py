"""
사진 바이트 저장 — 나중에 Blob 으로 옮길 때 **파일 복사로 끝나게** 하는 심(seam)

001 의 photo 테이블은 이미 `storage_key` 를 들고 있었다. 그 한 열이 이 파일의
근거다 — 바이트가 어디 있든 DB 에는 **키**만 남으니, 저장소를 갈아도 스키마
마이그레이션이 필요 없다. 옮기는 일이 「모든 (키, 바이트) 쌍을 새 저장소에
복사하고 환경변수를 바꾼다」가 된다.

    지금       PgStore     photo_blob 표. 키 → 바이트
    개발       LocalStore  파일 한 장씩. 키가 곧 경로다
    서비스     BlobStore   같은 키로 컨테이너에 올린다 (아직 없다)

키 규칙은 오브젝트 스토리지의 것을 그대로 쓴다.

    photos/2026/09/{photo_id}/view.jpg

**구분자는 항상 `/` 다.** Windows 에서 os.sep 로 만들면 그 키가 DB 에 들어가고,
같은 행을 Linux 나 Blob 에서 읽을 때 찾을 수 없게 된다. 연·월로 나누는 것은
파일 저장소에서 한 폴더에 수만 개가 쌓이는 것을 막기 위해서이고, Blob 에서는
목록 조회의 접두사가 된다.


**url() 이 없다. 일부러 없다.**

스토리지 주소를 화면에 주면 두 가지를 잃는다.

    소유자 검사    주소를 아는 사람은 누구나 본다. 사진은 얼굴이다
    갈아 끼울 자유  SAS 서명 URL 과 로컬 경로는 서로 대체되지 않는다.
                   화면이 한 번 그 모양에 기대면 저장소가 API 가 된다

그래서 사진은 **언제나** `GET /api/photos/{photo_id}` 로 나간다. 팀 문서의
「저장 주소(URL)가 있어야 사진 분석 AI 가 그 사진을 볼 수 있다」는 우리 구조에서는
성립하지 않는다 — 분석 에이전트는 서버 안에서 돌고, 바이트를 여기서 직접 읽어
Gemini 에 인라인으로 싣는다. 외부에서 닿는 주소가 필요한 쪽이 아무도 없다.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from . import store
from .conf import env_int

log = logging.getLogger("photo")

# 키에 허용하는 모양. 이 밖의 문자는 만들지도, 받지도 않는다 —
# LocalStore 가 키를 경로로 쓰기 때문에 `..` 하나가 곧 경로 탈출이다.
#
# 엽서도 같은 저장소에 든다 (postcard.py). 엽서의 마지막 조각은 변형 이름이 아니라
# 바이트의 해시다 — 다시 구울 때마다 키가 바뀌어야 옛 엽서가 캐시에 남지 않는다.
KEY_OK = re.compile(
    r"^(photos/\d{4}/\d{2}/[0-9a-f-]{36}/[a-z]+"
    r"|postcards/\d{4}/\d{2}/[0-9a-f-]{36}/[0-9a-f]{16})\.(jpg|png|webp)$")

EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class PhotoStoreError(RuntimeError):
    """바이트를 넣거나 꺼내지 못했다. 라우트가 503 으로 바꾼다."""


class PhotoMissing(PhotoStoreError):
    """키가 가리키는 바이트가 없다. 행은 있는데 바이트가 없는 상태다."""


def storage_key(photo_id: str, when: datetime | None = None,
                variant: str = "view", mime: str = "image/jpeg") -> str:
    """
    저장 키 하나. 연·월은 **올린 시각**으로 나눈다.

    사진에 적힌 촬영 시각(exif_taken_at)으로 나누지 않는다. 1960년대 사진이
    1960/03 에 들어가면 폴더가 수십 년에 걸쳐 흩어지는데, 이 값의 목적은 한
    폴더에 너무 많이 쌓이지 않게 하는 것뿐이다. 그리고 EXIF 는 없을 때가 많다.
    """
    at = when or datetime.now(timezone.utc)
    ext = EXT.get(mime, "jpg")
    return f"photos/{at.year:04d}/{at.month:02d}/{photo_id}/{variant}.{ext}"


def check_key(key: str) -> str:
    """키를 쓰기 전에 모양을 확인한다. 저장소마다 다시 하지 않도록 여기 한 곳."""
    if not KEY_OK.match(key):
        raise PhotoStoreError(f"저장 키가 규칙에 맞지 않습니다: {key[:80]!r}")
    return key


# ---------------------------------------------------------------- 인터페이스


@runtime_checkable
class PhotoStore(Protocol):
    """
    키 → 바이트. 오브젝트 스토리지가 하는 일만 담는다.

    `url()` 이 없는 이유는 이 파일 머리에 적어 두었다. 목록·통계도 없다 —
    그건 photo 테이블이 answer 할 질문이고, 스토리지에 물으면 저장소마다
    다른 답이 온다.
    """

    name: str

    async def put(self, key: str, data: bytes, mime: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...


# ---------------------------------------------------------------- Postgres


class PgStore:
    """
    photo_blob 표에 넣는다. 지금의 기본값이다.

    이 규모에서 가장 단순하다는 것이 고른 이유다. 화면용 1024px JPEG 이 장당
    150~250KB 라 사진 1,000장이 200~300MB 다. 그리고 이것으로 네 가지가 한꺼번에
    사라진다 —

        백업을 맞출 일     pg_dump 하나에 사진까지 들어온다. 「같은 순간의
                           DB 와 파일」을 따로 맞출 필요가 없다
        파일과 행의 어긋남  같은 트랜잭션 경계 안에 있다
        단일 인스턴스 제약  로컬 디스크와 달리 어느 프로세스에서나 읽힌다
        키 관리            연결 문자열 하나 말고 더 들 것이 없다

    **photo 테이블을 참조하지 않는다.** 002 의 주석에 이유를 적어 두었다 —
    오브젝트 스토리지에는 외래 키가 없고, 여기만 다르게 행동하면 Blob 으로
    옮길 때 그 차이가 전부 버그가 된다.
    """

    name = "pg"

    async def put(self, key: str, data: bytes, mime: str) -> None:
        check_key(key)
        try:
            async with store.pool().acquire() as con:
                await con.execute(
                    """
                    INSERT INTO photo_blob (storage_key, mime, bytes)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (storage_key) DO UPDATE
                       SET mime = EXCLUDED.mime, bytes = EXCLUDED.bytes
                    """, key, mime, data)
        except Exception as e:                               # noqa: BLE001
            raise PhotoStoreError(f"사진을 넣지 못했습니다 ({type(e).__name__})") from e

    async def get(self, key: str) -> bytes:
        check_key(key)
        try:
            async with store.pool().acquire() as con:
                row = await con.fetchrow(
                    "SELECT bytes FROM photo_blob WHERE storage_key = $1", key)
        except Exception as e:                               # noqa: BLE001
            raise PhotoStoreError(f"사진을 읽지 못했습니다 ({type(e).__name__})") from e
        if row is None:
            raise PhotoMissing(f"바이트가 없습니다: {key}")
        return bytes(row["bytes"])

    async def delete(self, key: str) -> None:
        check_key(key)
        try:
            async with store.pool().acquire() as con:
                await con.execute("DELETE FROM photo_blob WHERE storage_key = $1", key)
        except Exception as e:                               # noqa: BLE001
            raise PhotoStoreError(f"사진을 지우지 못했습니다 ({type(e).__name__})") from e

    async def exists(self, key: str) -> bool:
        check_key(key)
        async with store.pool().acquire() as con:
            return bool(await con.fetchval(
                "SELECT 1 FROM photo_blob WHERE storage_key = $1", key))


# ---------------------------------------------------------------- 로컬 디스크


class LocalStore:
    """
    파일 한 장씩. **개발용이다.**

    서비스에서 쓰지 않는 이유는 성능이 아니라 운영이다 — 인스턴스가 둘이 되면
    한 쪽이 넣은 사진을 다른 쪽이 못 읽고, 백업이 「DB 덤프 + 파일 트리」 두 벌이
    되어 같은 순간을 맞춰 떠야 한다. 그래도 남겨 두는 까닭은 이 구현이 심이
    진짜 스토리지처럼 생겼는지 확인해 주기 때문이다. PgStore 하나만 있으면
    Postgres 에 기대는 가정이 슬그머니 심 안으로 들어온다.

    쓰기는 **임시 파일 → rename** 이다. 바로 쓰면 반쯤 쓰인 JPEG 을 읽는 순간이
    생기고, 그건 「사진이 깨졌다」로 보인다. rename 은 같은 파일시스템 안에서
    원자적이다.
    """

    name = "local"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.environ.get("PHOTO_DIR") or "photos").resolve()

    def _path(self, key: str) -> Path:
        check_key(key)
        # 키는 이미 KEY_OK 를 지났지만 한 번 더 막는다. 경로 탈출은 조용히
        # 실패하지 않고 파일시스템을 건드리는 종류의 사고다.
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise PhotoStoreError(f"저장 경로가 루트를 벗어납니다: {key[:80]!r}")
        return path

    async def put(self, key: str, data: bytes, mime: str) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(path)
        except OSError as e:
            raise PhotoStoreError(f"사진을 넣지 못했습니다 ({type(e).__name__})") from e

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise PhotoMissing(f"바이트가 없습니다: {key}")
        try:
            return path.read_bytes()
        except OSError as e:
            raise PhotoStoreError(f"사진을 읽지 못했습니다 ({type(e).__name__})") from e

    async def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError as e:
            raise PhotoStoreError(f"사진을 지우지 못했습니다 ({type(e).__name__})") from e

    async def exists(self, key: str) -> bool:
        return self._path(key).is_file()


# ---------------------------------------------------------------- 고르기

_BACKENDS = {"pg": PgStore, "local": LocalStore}
_store: PhotoStore | None = None


def make(kind: str | None = None) -> PhotoStore:
    """
    환경변수 PHOTO_STORE 가 고른다. 기본은 pg.

    **모르는 값이면 기본값으로 떨어지지 않고 멈춘다.** PHOTO_STORE=blob 이라고
    적어 두고 조용히 pg 로 돌면, 사진이 어디 있는지 아무도 모르는 상태로 서비스가
    돈다. 오타 하나가 「사진이 안 보인다」가 아니라 「사진이 딴 데 쌓인다」로
    나타나는 종류의 실수다.
    """
    name = (kind or os.environ.get("PHOTO_STORE") or "pg").strip().lower()
    cls = _BACKENDS.get(name)
    if cls is None:
        raise PhotoStoreError(
            f"PHOTO_STORE={name!r} 를 모릅니다 (쓸 수 있는 값: "
            f"{', '.join(sorted(_BACKENDS))})")
    return cls()


def current() -> PhotoStore:
    """한 번 만들어 재사용한다. 라우트가 부르는 자리다."""
    global _store
    if _store is None:
        _store = make()
        log.info("사진 저장소 — %s", _store.name)
    return _store


def reset() -> None:
    """시험에서 저장소를 바꿔 끼울 때. 운영 코드가 부르는 자리는 없다."""
    global _store
    _store = None


def max_bytes() -> int:
    """받아들일 원본 상한. 라우트와 photo.py 가 같은 값을 보게 한 자리."""
    return env_int("MAX_UPLOAD_MB", 20) * 1024 * 1024
