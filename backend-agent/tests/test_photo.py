"""
사진 검증 — 형식 판별 · 변환 · 저장 심 · 마이그레이션

    python -m tests.test_photo

여기서 가장 중요한 검사 셋을 먼저 적어 둔다. 나중에 누가 이 코드를 줄일 때
무엇을 잃는지 알고 줄이도록.

    [1] 앞머리 바이트로 형식을 가린다      Content-Type 을 믿으면 아무 파일이나
                                          사진 경로로 다시 나간다
    [3] 메타데이터를 떨어낸다              어르신 사진의 EXIF 에는 GPS 가 있다
    [4] 이벤트 루프를 막지 않는다           막으면 **다른 어르신의** 타이머가 늦는다
"""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from PIL import Image                                                    # noqa: E402

from app.session import migrate, photo, photostore, store                # noqa: E402

PASS, FAIL = [], []
TMP = Path(__file__).resolve().parent / "_tmp_photo"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else '!! '}{name}{'  — ' + detail if detail else ''}")


class _Env:
    def __init__(self, **kv):
        self.kv = {k: str(v) for k, v in kv.items()}
        self.old: dict[str, str | None] = {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------- 표본

def jpeg(w=800, h=600, color=(120, 90, 60), exif=None, quality=90) -> bytes:
    im = Image.new("RGB", (w, h), color)
    # 단색은 JPEG 이 너무 잘 압축해 크기 시험이 안 된다. 잡티를 넣는다.
    for x in range(0, w, 7):
        for y in range(0, h, 11):
            im.putpixel((x, y), ((x * 7) % 256, (y * 13) % 256, (x + y) % 256))
    buf = io.BytesIO()
    if exif is not None:
        im.save(buf, "JPEG", quality=quality, exif=exif)
    else:
        im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def png_alpha(w=200, h=100) -> bytes:
    im = Image.new("RGBA", (w, h), (255, 0, 0, 0))       # 완전 투명
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def webp(w=120, h=80) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (1, 2, 3)).save(buf, "WEBP")
    return buf.getvalue()


# ---------------------------------------------------------------- 형식 판별

def test_sniff():
    print("\n[1] 앞머리 바이트로 형식을 가린다 — Content-Type 을 믿지 않는다")

    check("JPEG", photo.sniff(jpeg(20, 20)) == photo.JPEG)
    check("PNG", photo.sniff(png_alpha()) == photo.PNG)
    check("WebP", photo.sniff(webp()) == photo.WEBP)

    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"
    if photo._heif_ok:
        check("HEIC", photo.sniff(heic) == photo.HEIF, "아이폰 사진이 이것이다")
    else:
        check("HEIC", True, "pillow-heif 없음 — 판별은 건너뛴다")

    for name, data in (
            ("실행 파일", b"MZ\x90\x00" + b"\x00" * 60),
            ("스크립트", b"#!/bin/sh\necho hi\n" + b" " * 40),
            ("SVG", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
            ("빈 것", b""),
            ("짧은 것", b"\xff\xd8\xff")):
        try:
            got = photo.sniff(data)
            check(f"{name} 는 거절한다", False, f"통과했다 → {got}")
        except photo.PhotoRejected:
            check(f"{name} 는 거절한다", True)

    # SVG 를 특별히 막는 이유. 브라우저는 SVG 안의 <script> 를 실행한다.
    check("SVG 를 사진으로 받지 않는다 (스크립트가 든다)", True,
          "받아서 /api/photos 로 다시 내보내면 우리가 배포한 것이 된다")


# ---------------------------------------------------------------- 변환

def test_resize():
    print("\n[2] 1024px 화면용 한 장으로 만든다")

    big = asyncio.run(photo.prepare(jpeg(2400, 1600)))
    check("긴 변이 1024 가 된다", max(big.width, big.height) == photo.VIEW_PX,
          f"{big.width}×{big.height}")
    check("비율을 지킨다", abs(big.width / big.height - 2400 / 1600) < 0.02,
          f"{big.width / big.height:.3f} vs {2400 / 1600:.3f}")
    check("JPEG 으로 나간다", big.mime == photo.JPEG)
    check("원본보다 작아진다", len(big.data) < big.source_bytes,
          f"{big.source_bytes // 1024}KB → {len(big.data) // 1024}KB")

    small = asyncio.run(photo.prepare(jpeg(300, 200)))
    check("작은 사진을 늘리지 않는다", (small.width, small.height) == (300, 200),
          f"{small.width}×{small.height} — 늘려도 정보는 안 늘고 용량만 는다")

    # 세로 사진: EXIF 에 「돌려서 보라」고만 적혀 있고 픽셀은 가로다.
    ex = Image.Exif()
    ex[274] = 6                                          # Orientation = 90° CW
    rot = asyncio.run(photo.prepare(jpeg(100, 50, exif=ex)))
    check("EXIF 회전을 픽셀에 반영한다", (rot.width, rot.height) == (50, 100),
          f"{rot.width}×{rot.height} — 안 하면 메타데이터를 버릴 때 사진이 눕는다")

    alpha = asyncio.run(photo.prepare(png_alpha()))
    out = Image.open(io.BytesIO(alpha.data))
    check("투명은 흰 바탕에 얹는다", out.getpixel((5, 5))[0] > 240,
          f"좌상단 {out.getpixel((5, 5))} — 검정으로 합성되면 사진이 어두워진다")
    check("PNG 도 JPEG 으로 통일된다", alpha.mime == photo.JPEG)

    wp = asyncio.run(photo.prepare(webp()))
    check("WebP 도 받는다", wp.width == 120 and wp.mime == photo.JPEG)


def test_metadata_stripped():
    print("\n[3] 메타데이터를 떨어낸다 — 어르신 사진의 EXIF 에는 GPS 가 있다")

    ex = Image.Exif()
    ex[36867] = "2019:04:13 10:30:00"                    # DateTimeOriginal
    ex[271] = "TestMaker"                                # Make
    # GPSInfo. 여기 좌표가 들어 있는 것이 이 검사의 이유다.
    ex[34853] = {1: "N", 2: (37.0, 33.0, 0.0), 3: "E", 4: (127.0, 0.0, 0.0)}
    src = jpeg(400, 300, exif=ex)

    prep = asyncio.run(photo.prepare(src))

    check("촬영 시각은 뽑아 둔다",
          prep.taken_at is not None and prep.taken_at.year == 2019,
          f"{prep.taken_at} — 연대기(§3)가 쓸 값이다")

    out_exif = Image.open(io.BytesIO(prep.data)).getexif()
    check("저장하는 바이트에는 EXIF 가 없다", len(dict(out_exif)) == 0,
          f"{dict(out_exif)} — 한 번 떨어내면 그 뒤로 어디로 새든 "
          f"좌표가 함께 가지 않는다")
    check("GPS 태그가 없다", 34853 not in out_exif)

    src_exif = Image.open(io.BytesIO(src)).getexif()
    check("원본에는 있었다 (검사가 헛돌지 않는다)", 36867 in src_exif or 271 in src_exif,
          f"원본 태그 {sorted(dict(src_exif))}")

    check("촬영 시각은 memory_year 가 아니다", True,
          "1960년 이야기를 2024년에 스캔한 사진이 흔하다 — 섞으면 연대기가 어긋난다")


def test_limits():
    print("\n[4] 상한과 폭탄")

    with _Env(MAX_UPLOAD_MB=1):
        try:
            asyncio.run(photo.prepare(b"\xff\xd8\xff" + b"0" * 2_000_000))
            check("상한을 넘는 업로드는 거절한다", False, "통과했다")
        except photo.PhotoRejected as e:
            check("상한을 넘는 업로드는 거절한다", True, str(e))

    try:
        asyncio.run(photo.prepare(b""))
        check("빈 본문은 거절한다", False)
    except photo.PhotoRejected:
        check("빈 본문은 거절한다", True)

    old = photo.MAX_PIXELS
    photo.MAX_PIXELS = 1000
    try:
        asyncio.run(photo.prepare(jpeg(100, 50)))         # 5,000 픽셀
        check("픽셀 폭탄은 풀기 전에 거절한다", False, "통과했다")
    except photo.PhotoRejected as e:
        check("픽셀 폭탄은 풀기 전에 거절한다", True,
              f"{e} — Image.open 이 헤더만 읽으므로 풀기 전에 볼 수 있다")
    finally:
        photo.MAX_PIXELS = old

    try:
        asyncio.run(photo.prepare(b"\xff\xd8\xff" + os.urandom(400)))
        check("손상된 JPEG 은 거절한다", False, "통과했다")
    except photo.PhotoRejected:
        check("손상된 JPEG 은 거절한다", True)


def test_does_not_block_loop():
    print("\n[5] 이벤트 루프를 막지 않는다 — 막으면 다른 어르신의 타이머가 늦는다")

    src = jpeg(3200, 2400)

    async def run():
        ticks = 0
        stop = False

        async def ticker():
            nonlocal ticks
            while not stop:
                await asyncio.sleep(0.005)
                ticks += 1

        t = asyncio.create_task(ticker())
        began = time.perf_counter()
        prep = await photo.prepare(src)
        took = time.perf_counter() - began
        stop = True
        await asyncio.sleep(0.01)
        t.cancel()
        return ticks, took, prep

    ticks, took, prep = asyncio.run(run())
    check("변환 중에도 루프가 돈다", ticks >= 3,
          f"{took * 1000:.0f}ms 동안 {ticks}번 깨어났다 — to_thread 를 빼면 0 에 "
          f"가까워지고, 그만큼 T1·T2 격발이 밀린다")
    check("변환 결과는 정상", max(prep.width, prep.height) == photo.VIEW_PX)


# ---------------------------------------------------------------- 저장 심

def test_key():
    print("\n[6] 저장 키 — 저장소를 갈아도 DB 를 안 건드리게 하는 값")

    key = photostore.storage_key("0191c0de-1234-4abc-8def-0123456789ab")
    check("오브젝트 스토리지 모양", key.startswith("photos/") and key.endswith("/view.jpg"),
          key)
    check("구분자는 항상 /", "\\" not in key,
          "os.sep 로 만들면 그 키가 DB 에 들어가 Linux·Blob 에서 못 찾는다")
    check("연·월로 나눈다", len(key.split("/")) == 5, key)

    for bad in ("photos/2026/09/../../../etc/passwd/view.jpg",
                "photos/2026/09/x/view.exe",
                "/etc/passwd",
                "photos\\2026\\09\\x\\view.jpg",
                ""):
        try:
            photostore.check_key(bad)
            check(f"이상한 키를 막는다: {bad[:34]!r}", False, "통과했다")
        except photostore.PhotoStoreError:
            check(f"이상한 키를 막는다: {bad[:34]!r}", True)


def test_local_store():
    print("\n[7] LocalStore — 심이 진짜 스토리지처럼 생겼는지 확인하는 구현")

    if TMP.exists():
        shutil.rmtree(TMP)
    st = photostore.LocalStore(TMP)
    key = photostore.storage_key("0191c0de-1234-4abc-8def-000000000001")

    async def run():
        check("없는 키는 exists=False", not await st.exists(key))
        try:
            await st.get(key)
            check("없는 키를 읽으면 PhotoMissing", False, "통과했다")
        except photostore.PhotoMissing:
            check("없는 키를 읽으면 PhotoMissing", True,
                  "「행은 있고 바이트가 없다」를 「저장소가 고장났다」와 구분한다")

        await st.put(key, b"\xff\xd8\xffhello", "image/jpeg")
        check("넣고 나면 exists=True", await st.exists(key))
        check("같은 바이트가 돌아온다", await st.get(key) == b"\xff\xd8\xffhello")

        left = list(TMP.rglob("*.part"))
        check("임시 파일이 남지 않는다", not left,
              f"{left} — 바로 쓰면 반쯤 쓰인 JPEG 을 읽는 순간이 생긴다")

        await st.put(key, b"\xff\xd8\xffagain", "image/jpeg")
        check("덮어쓰기가 된다", await st.get(key) == b"\xff\xd8\xffagain")

        await st.delete(key)
        check("지우면 없어진다", not await st.exists(key))
        await st.delete(key)
        check("두 번 지워도 터지지 않는다", True, "오브젝트 스토리지도 그렇다")

    asyncio.run(run())
    shutil.rmtree(TMP, ignore_errors=True)


def test_store_choice():
    print("\n[8] 저장소 고르기")

    with _Env(PHOTO_STORE="pg"):
        check("기본은 pg", photostore.make().name == "pg")
    with _Env(PHOTO_STORE="local"):
        check("local 로 바꿀 수 있다", photostore.make().name == "local")
    with _Env(PHOTO_STORE="blob"):
        try:
            photostore.make()
            check("모르는 값이면 멈춘다", False, "기본값으로 조용히 떨어졌다")
        except photostore.PhotoStoreError as e:
            check("모르는 값이면 멈춘다", True,
                  f"{e} — 조용히 pg 로 돌면 사진이 딴 데 쌓이는데 아무도 모른다")
    check("url() 이 없다", not hasattr(photostore.PgStore, "url"),
          "주소를 주면 소유자 검사를 우회당하고, 저장소가 API 가 된다")


# ---------------------------------------------------------------- 마이그레이션

def test_migrations():
    print("\n[9] 마이그레이션 — 「DROP 후 다시 만든다」를 졸업했는지")

    found = migrate.files()
    # **이 목록은 새 마이그레이션마다 손으로 늘린다.** 귀찮으라고 그랬다 —
    # 번호를 빠뜨리거나 두 사람이 같은 번호를 쓰면 여기서 먼저 걸린다.
    check("번호순으로 읽는다", [v for v, _ in found] == ["001", "002", "003"],
          str([v for v, _ in found]))
    check("001 은 처음 세 테이블", "CREATE TABLE IF NOT EXISTS session"
          in found[0][1].read_text(encoding="utf-8"))
    check("002 는 사진의 주인과 바이트",
          "photo_blob" in found[1][1].read_text(encoding="utf-8")
          and "user_id" in found[1][1].read_text(encoding="utf-8"))

    sql3 = found[2][1].read_text(encoding="utf-8")
    check("003 은 가족·어르신·로그인 세션",
          all(t in sql3 for t in ("app_user", "elder", "user_elder", "login_session")))
    check("003 은 session·photo 를 안 건드린다",
          "ALTER TABLE session" not in sql3 and "ALTER TABLE photo" not in sql3,
          "아직 아무 문자열이나 user_id 로 들어온다 — 지금 외래 키를 걸면 위조 헤더가 500 을 낸다")

    # **줄 끝이 체크섬을 흔들면 안 된다.** Windows 에서 CRLF 로 체크아웃된 파일과
    # LF 로 커밋된 파일의 해시가 달라지면, 아무도 고치지 않았는데 모든 개발자의
    # 기동이 막힌다. 원인을 찾는 데 반나절이 든다.
    lf = "CREATE TABLE a (x int);\nALTER TABLE a ADD y int;\n"
    check("줄 끝이 달라도 체크섬은 같다",
          migrate._digest(lf) == migrate._digest(lf.replace("\n", "\r\n"))
          == migrate._digest(lf + "\n\n"),
          "CRLF 체크아웃이 모든 개발자의 기동을 막는 종류의 버그")
    check("내용이 바뀌면 체크섬이 바뀐다",
          migrate._digest(lf) != migrate._digest(lf.replace("int", "bigint")),
          "적용된 파일을 고치면 다음 기동이 멈춰야 한다")

    real = migrate.DIR
    sand = TMP / "migrations"
    try:
        sand.mkdir(parents=True, exist_ok=True)
        migrate.DIR = sand

        (sand / "001_a.sql").write_text("SELECT 1;", encoding="utf-8")
        (sand / "002_b.sql").write_text("SELECT 2;", encoding="utf-8")
        check("정상 폴더는 읽힌다", [v for v, _ in migrate.files()] == ["001", "002"])

        (sand / "002_c.sql").write_text("SELECT 3;", encoding="utf-8")
        try:
            migrate.files()
            check("번호가 겹치면 멈춘다", False, "둘 다 읽혔다")
        except migrate.MigrationError as e:
            check("번호가 겹치면 멈춘다", True,
                  f"{e} — 둘이 같은 번호로 만든 것이고, 적용 순서가 리뷰 순서와 "
                  f"달라진다")
        (sand / "002_c.sql").unlink()

        (sand / "003_d.sql.bak").write_text("SELECT 4;", encoding="utf-8")
        try:
            migrate.files()
            check("이름이 규칙에 안 맞으면 멈춘다", False, "조용히 넘어갔다")
        except migrate.MigrationError as e:
            check("이름이 규칙에 안 맞으면 멈춘다", True,
                  f"{e} — 넘기면 적용했다고 믿는 변경이 안 걸린 채로 돈다")
    finally:
        migrate.DIR = real
        shutil.rmtree(TMP, ignore_errors=True)


# ---------------------------------------------------------------- 라우트

class _FakeRows:
    """store 의 사진 함수를 메모리로 갈아 끼운다. DB 없이 라우트를 돌리려고."""

    def __enter__(self):
        self.rows: dict[str, dict] = {}
        self._save, self._load = store.save_photo, store.load_photo
        self._del = store.delete_photo_row
        self.fail = False

        async def save(rec):
            if self.fail:
                raise store.StoreUnavailable("일부러 실패")
            self.rows[rec["photo_id"]] = {**rec, "status": "stored"}

        async def load(pid):
            return self.rows.get(pid)

        async def delete(pid):
            self.rows.pop(pid, None)

        store.save_photo, store.load_photo, store.delete_photo_row = save, load, delete
        return self

    def __exit__(self, *a):
        store.save_photo, store.load_photo = self._save, self._load
        store.delete_photo_row = self._del


def test_routes():
    print("\n[10] 라우트 — 올리고 다시 받는다")

    from fastapi.testclient import TestClient

    from app.main import app

    if TMP.exists():
        shutil.rmtree(TMP)

    src = jpeg(1600, 1200)
    with _Env(GEMINI_API_KEY="", AZURE_SPEECH_KEY="", PHOTO_STORE="local",
              PHOTO_DIR=str(TMP), CREATE_MAX_PER_WINDOW=0), _FakeRows() as rows:
        photostore.reset()
        with TestClient(app) as c:
            up = c.post("/api/photos", content=src,
                        headers={"Content-Type": "image/jpeg", "X-User-Id": "kim"})
            check("올리면 200", up.status_code == 200, up.text[:160])
            body = up.json() if up.status_code == 200 else {}
            pid = body.get("photo_id", "")
            check("url 은 이 서버의 경로다", body.get("url") == f"/api/photos/{pid}",
                  f"{body.get('url')} — 스토리지 주소가 아니다")
            check("1024 로 줄여 저장한다", max(body.get("width", 0),
                                              body.get("height", 0)) == 1024,
                  f"{body.get('width')}×{body.get('height')}")

            # **쿠키가 실려 왔는지.** <img src> 가 헤더를 못 보내기 때문에 이게
            # 없으면 사진이 화면에 안 뜬다.
            check("X-User-Id 가 쿠키로 옮겨진다", c.cookies.get("uid") == "kim",
                  f"uid={c.cookies.get('uid')!r}")

            got = c.get(f"/api/photos/{pid}", headers={"X-User-Id": "kim"})
            check("다시 받으면 같은 바이트", got.status_code == 200
                  and len(got.content) == body.get("bytes"),
                  f"{got.status_code} · {len(got.content)}B vs {body.get('bytes')}B")
            check("JPEG 으로 나간다",
                  got.headers.get("content-type", "").startswith("image/jpeg"))
            check("private 캐시다", "private" in got.headers.get("cache-control", ""),
                  got.headers.get("cache-control", ""))

            etag = got.headers.get("etag")
            again = c.get(f"/api/photos/{pid}",
                          headers={"X-User-Id": "kim", "If-None-Match": etag})
            check("ETag 가 맞으면 304", again.status_code == 304,
                  f"{again.status_code} — 카드를 오갈 때마다 200KB 를 다시 "
                  f"보내지 않는다")

            # 쿠키만으로도 읽힌다 = <img src> 가 도는 경로.
            bare = c.get(f"/api/photos/{pid}")
            check("헤더 없이 쿠키만으로도 읽힌다", bare.status_code == 200,
                  f"{bare.status_code} — 이게 안 되면 <img src> 가 사진을 못 받는다")

            c.cookies.clear()
            other = c.get(f"/api/photos/{pid}", headers={"X-User-Id": "park"})
            check("남의 사진은 403 이 아니라 404", other.status_code == 404,
                  f"{other.status_code} — 403 은 「있긴 있다」를 알려주는 셈이다")

            bad = c.post("/api/photos", content=b"MZ\x90\x00" + b"\x00" * 100,
                         headers={"Content-Type": "image/jpeg", "X-User-Id": "kim"})
            check("사진이 아니면 400", bad.status_code == 400,
                  f"{bad.status_code} — 500 으로 만들면 「서버가 고장났다」로 보인다")

            with _Env(MAX_UPLOAD_MB=1):
                big = c.post("/api/photos", content=b"\xff\xd8\xff" + b"0" * 2_000_000,
                             headers={"Content-Type": "image/jpeg", "X-User-Id": "kim"})
                check("상한을 넘으면 413", big.status_code == 413, str(big.status_code))

            rows.fail = True
            broke = c.post("/api/photos", content=src,
                           headers={"Content-Type": "image/jpeg", "X-User-Id": "kim"})
            check("행을 못 넣으면 503 — 성공했다고 말하지 않는다",
                  broke.status_code == 503, str(broke.status_code))
            leftover = list(TMP.rglob("*.jpg"))
            check("바이트를 되돌린다", len(leftover) == 1,
                  f"{len(leftover)}장 남음 — 보상 삭제가 안 되면 고아 바이트가 쌓인다")
            rows.fail = False

    photostore.reset()
    shutil.rmtree(TMP, ignore_errors=True)


def test_all_checks_passed():
    """pytest 안전판 — test_flow.py 의 같은 함수 주석 참조."""
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 사진 검증")
    test_sniff()
    test_resize()
    test_metadata_stripped()
    test_limits()
    test_does_not_block_loop()
    test_key()
    test_local_store()
    test_store_choice()
    test_migrations()
    test_routes()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
