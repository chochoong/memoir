"""
사진 받아들이기 — 검증 · 변환 · 저장

세 가지를 한다.

    1. 믿지 않는다     Content-Type 이 아니라 **바이트 앞머리**로 형식을 가린다
    2. 한 장으로 만든다  HEIC → JPEG, EXIF 회전 적용, 1024px, 메타데이터 제거
    3. 넣는다          바이트 먼저, 행 나중 (아래 save 참조)

**Pillow 작업은 전부 asyncio.to_thread 로 나간다.** 이 서버는 이벤트 루프 하나로
모든 회차의 T1·T2 를 돈다. 1024px 리샘플링은 수십~수백 ms 인데, 그 동안 루프가
멈추면 **다른 어르신의** 타이머가 그만큼 늦게 격발한다. timers.py 가 격발 오차를
재고 200ms 를 넘으면 경고하는데, 사진 한 장이 그 경고를 만들 수 있다.

원본은 남기지 않는다. 화면용 1024px 한 장만 저장한다.

    저장량      장당 150~250KB. 원본까지 두면 13배쯤 된다
    유출 피해    원본에는 얼굴이 크게, 그리고 GPS 가 들어 있다
    분석         Gemini 에 싣는 것도 1024px 로 충분하다

**메타데이터를 통째로 버리는 것이 중요하다.** 어르신 사진의 EXIF 에는 촬영 장소
좌표가 들어 있을 수 있다. 저장하기 전에 한 번 떨어내면 그 뒤로는 어디로 새든
좌표가 함께 가지 않는다. 촬영 시각만 따로 뽑아 photo.exif_taken_at 에 남긴다 —
그건 연대기(§3)에 쓸 값이고, 좌표와 달리 한 칸짜리 정보다.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from . import photo_analyze, photostore, store
from .conf import env_int

log = logging.getLogger("photo")

# 화면용 긴 변. 어르신 폰의 논리 해상도가 대개 390~430px 이고 DPR 3 이면 1290px
# 이지만, 사진은 화면 가득이 아니라 카드 안에 들어간다. 1024 면 충분하다.
VIEW_PX = 1024
JPEG_QUALITY = 82

# 픽셀 수 상한 (decompression bomb). 40M 은 8000×5000 쯤이라 스캔한 사진도 든다.
# 이걸 안 막으면 헤더만 몇 KB 인 파일이 풀릴 때 수 GB 를 먹는다.
MAX_PIXELS = 40_000_000

# 받아들이는 형식. 앞머리 바이트로 가린다 (아래 sniff 참조).
JPEG, PNG, WEBP, HEIF = "image/jpeg", "image/png", "image/webp", "image/heif"

_heif_ok = False
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    _heif_ok = True
except Exception as e:                                       # noqa: BLE001
    # 아이폰 사진이 HEIC 다. 이게 없으면 그 사진들이 거절된다 — 조용히 넘기지
    # 않고 기동 로그에 남긴다. requirements.txt 에 pillow-heif 가 있다.
    log.warning("pillow-heif 를 못 읽었다 (%s) — HEIC 사진을 받지 못한다",
                type(e).__name__)

from PIL import Image, ImageOps  # noqa: E402

# 우리 손으로도 픽셀 수를 보지만 (아래 _render), Pillow 의 가드도 켜 둔다.
# 헤더가 거짓을 말하는 파일은 load() 중에야 드러난다.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class PhotoRejected(ValueError):
    """어르신이 고친 뒤 다시 하면 되는 실패. 라우트가 400 으로 바꾼다."""


@dataclass(frozen=True)
class Prepared:
    """저장할 준비가 된 한 장. 바이트와 그걸 설명하는 값들."""
    data: bytes
    mime: str
    width: int
    height: int
    sha256: str                  # **원본**의 해시. 같은 사진을 두 번 올리면 같다
    source_mime: str
    source_bytes: int
    taken_at: datetime | None


# ---------------------------------------------------------------- 검증


def sniff(data: bytes) -> str:
    """
    앞머리 바이트로 형식을 가린다. **Content-Type 을 믿지 않는다.**

    헤더는 올리는 쪽이 정하는 값이다. `image/jpeg` 라고 적고 실행 파일을 올릴 수
    있고, 그 파일이 사진으로 저장되어 사진 경로로 다시 나가면 그때는 우리가
    배포한 것이 된다. 앞머리는 파일 자신이 말하는 것이라 그 거짓말이 안 통한다.
    """
    if len(data) < 12:
        raise PhotoRejected("사진 파일이 너무 작습니다")
    if data[:3] == b"\xff\xd8\xff":
        return JPEG
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return PNG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    # ISO-BMFF: 4바이트 크기 + 'ftyp' + 브랜드. HEIC·HEIF·AVIF 가 여기 든다.
    if data[4:8] == b"ftyp" and data[8:12].lower() in (
            b"heic", b"heix", b"hevc", b"heim", b"heis", b"hevm", b"mif1", b"msf1"):
        if not _heif_ok:
            raise PhotoRejected(
                "이 서버가 HEIC 사진을 처리할 수 없습니다. JPEG 으로 저장해 올려 주세요")
        return HEIF
    raise PhotoRejected("사진 파일로 읽을 수 없습니다 (JPEG·PNG·WebP·HEIC)")


# ---------------------------------------------------------------- 변환


def _taken_at(im: Image.Image) -> datetime | None:
    """
    EXIF 촬영 시각. **없는 것이 정상이다** — 스캔한 옛 사진에는 없다.

    photo.exif_taken_at 의 주석대로 이 값은 「스캔·촬영 시각」이고
    「기억의 연도(memory_year)」가 아니다. 1960년의 이야기를 2024년에 스캔한
    사진이 흔하다. 둘을 섞으면 연대기가 통째로 어긋난다.
    """
    try:
        exif = im.getexif()
    except Exception:                                        # noqa: BLE001
        return None
    raw = exif.get(36867) or exif.get(306)                   # DateTimeOriginal, DateTime
    if not isinstance(raw, str):
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def _render(data: bytes, source_mime: str) -> Prepared:
    """
    **블로킹 함수다.** 직접 부르지 않는다 — 아래 prepare() 가 스레드로 보낸다.

    Image.open 은 헤더만 읽고 픽셀은 손대지 않는다. 그래서 크기를 **풀기 전에**
    볼 수 있고, 여기가 decompression bomb 을 막는 자리다. 이 검사를 load() 뒤로
    옮기면 막으려던 그 일이 이미 일어난 뒤가 된다.
    """
    digest = hashlib.sha256(data).hexdigest()
    try:
        im = Image.open(io.BytesIO(data))
    except Exception as e:                                   # noqa: BLE001
        raise PhotoRejected("사진을 열 수 없습니다 (파일이 손상된 것 같습니다)") from e

    with im:
        w, h = im.size
        if w * h > MAX_PIXELS:
            raise PhotoRejected(
                f"사진이 너무 큽니다 ({w}×{h}). 1억 화소 이하로 줄여 주세요"
                if w * h > 100_000_000 else
                f"사진이 너무 큽니다 ({w}×{h})")

        taken = _taken_at(im)

        try:
            # 세로로 찍은 사진은 픽셀이 가로인 채 EXIF 에 「돌려서 보라」고
            # 적혀 있다. 그 표시를 지금 픽셀에 반영해야 한다 — 아래에서
            # 메타데이터를 버리기 때문에, 안 하면 사진이 눕는다.
            im = ImageOps.exif_transpose(im)

            if im.mode in ("RGBA", "LA", "P", "PA"):
                # JPEG 은 투명을 담지 못한다. 검정으로 합성되면 어르신 사진이
                # 어두워지므로 흰 바탕에 얹는다.
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")

            # thumbnail 은 **줄이기만 한다.** 작은 사진을 1024 로 늘리지 않는다 —
            # 늘려도 정보는 안 늘고 용량만 는다.
            im.thumbnail((VIEW_PX, VIEW_PX), Image.LANCZOS)

            out = io.BytesIO()
            # exif 를 넘기지 않는다 = GPS 를 포함한 메타데이터가 떨어진다.
            im.save(out, format="JPEG", quality=JPEG_QUALITY,
                    optimize=True, progressive=True)
        except PhotoRejected:
            raise
        except Exception as e:                               # noqa: BLE001
            raise PhotoRejected("사진을 변환하지 못했습니다") from e

        return Prepared(
            data=out.getvalue(), mime=JPEG,
            width=im.width, height=im.height,
            sha256=digest, source_mime=source_mime,
            source_bytes=len(data), taken_at=taken)


async def prepare(data: bytes) -> Prepared:
    """
    검증 + 변환. **CPU 를 쓰는 부분이 스레드로 나간다** (모듈 머리 참조).

    sniff 는 앞머리 12바이트만 보므로 루프에서 해도 된다. 거절되는 파일이
    스레드를 쓰지 않고 끝나는 쪽이 낫다.
    """
    cap = photostore.max_bytes()
    if len(data) > cap:
        raise PhotoRejected(f"사진이 {cap // (1024 * 1024)}MB 를 넘습니다")
    if not data:
        raise PhotoRejected("사진이 비어 있습니다")

    source_mime = sniff(data)
    return await asyncio.to_thread(_render, data, source_mime)


# ---------------------------------------------------------------- 저장


async def save(prepared: Prepared, *, user_id: str,
               session_id: str | None = None) -> dict:
    """
    바이트를 저장소에, 표지를 photo 행에. **순서가 중요하다.**

        바이트 먼저 → 행 나중

    거꾸로 하면 행은 있고 바이트가 없는 상태가 생긴다. 그 사진은 목록에
    **보이면서** 열리지 않는다 — 어르신 화면에 깨진 그림이 뜬다. 이 순서면
    실패의 잔해가 「아무도 가리키지 않는 바이트 몇백 KB」라서 눈에 띄지 않고,
    나중에 키 목록과 photo 행을 맞춰 보면 찾아서 지울 수 있다.

    행을 못 넣으면 바이트를 되돌리고 올린다. **성공했다고 말하지 않는다** —
    store.py 의 사진 절 주석 참조.
    """
    photo_id = str(uuid.uuid4())
    key = photostore.storage_key(photo_id, mime=prepared.mime)
    ps = photostore.current()

    await ps.put(key, prepared.data, prepared.mime)

    rec = {
        "photo_id": photo_id,
        "session_id": session_id,
        "user_id": user_id,
        "storage_key": key,
        "mime": prepared.mime,
        "bytes": len(prepared.data),
        "sha256": prepared.sha256,
        "width": prepared.width,
        "height": prepared.height,
        "exif_taken_at": prepared.taken_at,
    }
    try:
        await store.save_photo(rec)
    except Exception:
        # 보상 삭제. 둘 다 최선 노력이고, 실패해도 어르신에게 돌려줄 답은
        # 이미 「저장하지 못했습니다」로 정해졌다.
        try:
            await ps.delete(key)
        except Exception as e:                               # noqa: BLE001
            log.error("사진 바이트 정리 실패 %s (%s) — 고아 바이트가 남는다",
                      key, type(e).__name__)
        raise

    log.info("사진 저장 %s — %s %d×%d %.0fKB (원본 %s %.0fKB)",
             photo_id[:8], ps.name, prepared.width, prepared.height,
             len(prepared.data) / 1024, prepared.source_mime,
             prepared.source_bytes / 1024)
    return rec


def cache_seconds() -> int:
    """
    화면이 사진을 얼마나 들고 있어도 되나.

    photo_id 하나가 가리키는 바이트는 바뀌지 않으므로 길게 줘도 된다. 다만
    `private` 과 함께 나간다 — 중간 캐시가 남의 사진을 들고 있게 두지 않는다.
    """
    return env_int("PHOTO_CACHE_SECONDS", 86400)


# ---------------------------------------------------------------- 올릴 때 분석

# 도는 분석들. **참조를 들고 있지 않으면 파이썬이 중간에 거둬 간다** —
# create_task 가 돌려준 Task 를 아무도 안 붙잡으면 GC 대상이 되고, 그러면
# 분석이 소리 없이 사라진다.
_running: set[asyncio.Task] = set()


def analyze_later(rec: dict) -> None:
    """
    사진을 올린 그 자리에서 §2 를 걸어 둔다. **기다리지 않는다.**

    회차를 열 때 분석하면 늦는다. 분석은 1.6~3.9초가 걸리는데 여는 말에는 그
    시간이 숨을 T2 침묵이 없어서, 첫 마디는 사진을 보지 않은 고정 문장이 될
    수밖에 없었다. 사진은 시작 단추보다 먼저 올라오므로 — 고르고, 보고, 그다음에
    누르신다 — 그 사이에 분석을 끝내 두면 여는 말부터 사진 질문으로 열 수 있다.

    **올린 사람을 기다리게 하지 않는다.** 업로드 응답은 바로 나간다. 분석이
    늦거나 실패해도 어르신이 보는 것은 달라지지 않는다 — 회차를 열 때 단서가
    없으면 controller 가 그때 다시 분석한다 (controller._analyze_photo).
    """
    task = asyncio.create_task(_analyze(rec))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _analyze(rec: dict) -> None:
    """
    §2 를 부르고 photo.clues 에 적는다. **어떤 실패도 위로 올리지 않는다** —
    부른 쪽은 이미 어르신께 「저장했습니다」를 돌려준 뒤라 더 할 수 있는 일이 없다.

    조용히 지나가지는 않는다. 사진을 올렸는데 사진 질문이 안 나오면 그 까닭이
    로그에 있어야 한다.
    """
    pid = rec["photo_id"][:8]
    try:
        data = await photostore.current().get(rec["storage_key"])
        clues = await photo_analyze.analyze_photo(data, rec["mime"])
    except asyncio.CancelledError:
        raise
    except Exception as e:                                   # noqa: BLE001
        log.error("사진 분석 실패 %s (%s: %s) — 회차를 열 때 다시 해 본다",
                  pid, type(e).__name__, str(e)[:120])
        return

    if not clues:
        log.error("사진 %s 에서 단서를 얻지 못했다 — 회차를 열 때 다시 해 본다", pid)
        return

    await store.save_photo_analysis(rec["photo_id"], clues)
    log.info("올릴 때 사진 단서 %s — 사물 %d개 · 여쭐 것 %d개", pid,
             len(clues.get("objects") or []), len(clues.get("questions") or []))
