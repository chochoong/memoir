"""
엽서 검증 — 굽기 · 저장 키 · 라우트

    python -m tests.test_postcard

모델은 부르지 않는다. pick · draw 를 갈아 끼우고 DB 는 메모리로 흉내 낸다.
여기서 지키는 것 넷.

    [1] 문장은 글꼴로 얹는다        그림 모델이 쓴 한글은 틀린 글자가 나온다
    [3] 다시 구우면 옛 바이트를 지운다  회차당 한 장이 저장소에서도 한 장이다
    [3] 행을 못 넣으면 바이트를 되돌린다 photo.save 와 같은 규칙이다
    [3] 저장 키는 화면에 안 나간다     주소는 이 서버의 경로뿐이다
"""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from PIL import Image                                                    # noqa: E402

from app.session import photostore, postcard, store                      # noqa: E402

PASS, FAIL = [], []
TMP = Path(__file__).resolve().parent / "_tmp_postcard"

SID = "0191c0de-1234-4abc-8def-0123456789ab"


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


def art(w=1344, h=768, color=(90, 120, 150)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- 굽기

def test_compose():
    print("\n[1] 굽기 — 그림 위, 문장 아래")

    font = postcard._font_path()
    data, w, h = postcard._compose(art(), "그해 여름 완행열차는 참 더웠지.", "2026. 9. 24.", font)
    with Image.open(io.BytesIO(data)) as im:
        check("JPEG 한 장", im.format == "JPEG", im.format)
        check("가로 3:2 엽서", im.size == (postcard.W, postcard.H) == (w, h), str(im.size))
        top = im.getpixel((postcard.W // 2, 10))
        band = im.getpixel((10, postcard.H - 10))
    check("위는 그림이 채운다", top[2] > top[0], str(top))
    check("아래 띠는 종이색", all(abs(a - b) < 8 for a, b in zip(band, postcard.PAPER)),
          str(band))

    f = postcard._font(font, 46)
    long = "열아홉에 고향을 떠나 서울로 올라왔지. 큰형이 영등포역까지 마중을 나왔어."
    lines = postcard._wrap(long, f, 1320)
    check("칸을 넘는 줄이 없다", all(f.getlength(ln) <= 1320 for ln in lines),
          f"{len(lines)}줄")
    check("글자를 잃지 않는다", "".join(lines).replace(" ", "") == long.replace(" ", ""))
    check("띄어쓰기에서 끊는다", all(not ln.startswith(" ") for ln in lines))

    one = postcard._wrap("가" * 80, f, 400)
    check("낱말이 칸보다 길면 글자 사이에서 끊는다",
          len(one) > 1 and all(f.getlength(ln) <= 400 for ln in one), f"{len(one)}줄")

    try:
        postcard._compose(b"not an image", "문장", "2026. 9. 24.", font)
        check("그림이 깨졌으면 503 쪽 오류", False, "통과했다")
    except postcard.PostcardUnavailable:
        check("그림이 깨졌으면 503 쪽 오류", True)

    with _Env(POSTCARD_FONT="Z:/없는/글꼴.ttf"):
        check("POSTCARD_FONT 가 없으면 후보로 넘어간다", postcard._font_path() != "Z:/없는/글꼴.ttf")


def test_key():
    print("\n[2] 저장 키 — 다시 구우면 바뀐다")

    a = postcard.storage_key(SID, b"one")
    b = postcard.storage_key(SID, b"two")
    check("저장소 규칙을 지난다", photostore.check_key(a) == a, a)
    check("바이트가 다르면 키가 다르다", a != b,
          "같은 키를 덮어쓰면 브라우저 캐시에 옛 엽서가 남는다")
    check("버전은 해시 16자리", len(postcard.version(a)) == 16, postcard.version(a))
    for bad in (f"postcards/2026/09/{SID}/../../x.jpg",
                f"postcards/2026/09/{SID}/view.jpg",
                f"postcards/2026/09/{SID}/0123456789abcdef.exe"):
        try:
            photostore.check_key(bad)
            check(f"이상한 엽서 키를 막는다: {bad[-24:]!r}", False, "통과했다")
        except photostore.PhotoStoreError:
            check(f"이상한 엽서 키를 막는다: {bad[-24:]!r}", True)


# ---------------------------------------------------------------- 라우트

class _Fake:
    """store 의 회차·엽서 함수를 메모리로, pick·draw 를 가짜로 갈아 끼운다."""

    def __init__(self):
        self.session = {
            "session_id": SID, "user_id": "kim", "title": "시험", "photo_id": None,
            "state": "CLOSED", "turn": 2, "max_turn": 0, "t2_seconds": 5.0,
            "closed_reason": "finish", "created_at": "2026-09-24T10:00:00+09:00",
            "closed_at": "2026-09-24T10:10:00+09:00",
            "fragments": [
                {"idx": 0, "question": None, "answer": ""},
                {"idx": 1, "question": "어디 가셨어요?", "answer": "서울 가는 완행열차를 탔지."},
            ],
        }
        self.card: dict | None = None
        self.fail = False
        self.draws = 0
        self.gate: asyncio.Event | None = None

    def __enter__(self):
        self._saved = (store.load_session, store.save_postcard, store.load_postcard,
                       postcard.pick, postcard.draw)

        async def load_session(sid):
            if sid != SID:
                return None
            card = self.card
            return {**self.session, "fragments": list(self.session["fragments"]),
                    "postcard": {"text": card["text"], "storage_key": card["storage_key"],
                                 "created_at": "2026-09-24T10:20:00+09:00"} if card else None}

        async def save_postcard(rec):
            if self.fail:
                raise store.StoreUnavailable("일부러 실패")
            old = self.card["storage_key"] if self.card else None
            self.card = dict(rec)
            return old

        async def load_postcard(sid):
            return self.card if sid == SID else None

        async def pick(said):
            return postcard.Picked(text=f"완행열차를 탔지 {self.draws}", scene="기차")

        async def draw(scene, ref):
            if self.gate:
                await self.gate.wait()
            self.draws += 1
            return art(color=(90, 120, 150 - self.draws))

        store.load_session, store.save_postcard, store.load_postcard = (
            load_session, save_postcard, load_postcard)
        postcard.pick, postcard.draw = pick, draw
        return self

    def __exit__(self, *a):
        (store.load_session, store.save_postcard, store.load_postcard,
         postcard.pick, postcard.draw) = self._saved


def _blobs() -> list[Path]:
    return list(TMP.rglob("*.jpg")) if TMP.exists() else []


def test_routes():
    print("\n[3] 라우트 — 굽고, 다시 받고, 다시 굽는다")

    from fastapi.testclient import TestClient

    from app.main import app

    shutil.rmtree(TMP, ignore_errors=True)
    kim = {"X-User-Id": "kim"}
    with _Env(AZURE_SPEECH_KEY="", PHOTO_STORE="local", PHOTO_DIR=str(TMP)), _Fake() as fake:
        photostore.reset()
        with TestClient(app) as c:
            url = f"/api/sessions/{SID}/postcard"

            fake.session["closed_at"] = None
            r = c.post(url, headers=kim)
            check("안 끝난 회차는 409", r.status_code == 409, f"{r.status_code} {r.text[:80]}")
            fake.session["closed_at"] = "2026-09-24T10:10:00+09:00"

            frs = fake.session["fragments"]
            fake.session["fragments"] = frs[:1]
            r = c.post(url, headers=kim)
            check("말씀이 없으면 409", r.status_code == 409, f"{r.status_code} {r.text[:80]}")
            fake.session["fragments"] = frs

            r = c.post(url, headers={"X-User-Id": "park"})
            check("남의 회차는 404", r.status_code == 404, str(r.status_code))
            check("거절한 뒤에는 그림을 안 그렸다", fake.draws == 0, f"{fake.draws}번")

            r = c.post(url, headers=kim)
            check("구우면 200", r.status_code == 200, r.text[:160])
            first = r.json() if r.status_code == 200 else {}
            check("주소는 이 서버의 경로에 버전 꼬리", str(first.get("url", "")).startswith(
                f"{url}?v="), str(first.get("url")))
            check("저장 키는 안 나간다", "storage_key" not in first)
            check("엽서 크기", (first.get("width"), first.get("height")) == (1500, 1000))
            check("저장소에 한 장", len(_blobs()) == 1, f"{len(_blobs())}장")

            got = c.get(first.get("url", url))
            check("쿠키만으로 받는다", got.status_code == 200
                  and got.headers.get("content-type", "").startswith("image/jpeg"),
                  f"{got.status_code} — <img src> 는 헤더를 못 싣는다")
            check("받은 바이트가 저장한 바이트", len(got.content) == first.get("bytes"))
            etag = got.headers.get("etag")
            again = c.get(url, headers={**kim, "If-None-Match": etag})
            check("ETag 가 맞으면 304", again.status_code == 304, str(again.status_code))

            c.cookies.clear()
            other = c.get(url, headers={"X-User-Id": "park"})
            check("남의 엽서는 404", other.status_code == 404, str(other.status_code))

            rec = c.get(f"/api/sessions/{SID}/record", headers=kim).json()
            pc = rec.get("postcard") or {}
            check("기록에 엽서가 딸려 온다", pc.get("url") == first.get("url"), str(pc))
            check("기록에도 저장 키는 안 나간다", "storage_key" not in pc)

            r2 = c.post(url, headers=kim)
            second = r2.json() if r2.status_code == 200 else {}
            check("다시 구우면 주소가 바뀐다", second.get("url") not in (None, first.get("url")),
                  "주소가 같으면 브라우저가 옛 엽서를 보여 준다")
            check("옛 바이트를 지운다", len(_blobs()) == 1, f"{len(_blobs())}장")
            stale = c.get(url, headers={**kim, "If-None-Match": etag})
            check("옛 ETag 로는 304 가 안 난다", stale.status_code == 200, str(stale.status_code))

            fake.fail = True
            r3 = c.post(url, headers=kim)
            check("행을 못 넣으면 503", r3.status_code == 503, str(r3.status_code))
            check("새 바이트를 되돌린다", len(_blobs()) == 1, f"{len(_blobs())}장")
            fake.fail = False

        async def twice():
            fake.gate = asyncio.Event()
            a = asyncio.create_task(postcard.make(SID, "kim"))
            await asyncio.sleep(0.05)
            try:
                await postcard.make(SID, "kim")
                check("굽는 중에 또 누르면 409 쪽 오류", False, "두 번 그렸다")
            except postcard.PostcardNotReady:
                check("굽는 중에 또 누르면 409 쪽 오류", True)
            fake.gate.set()
            await a
            fake.gate = None
        asyncio.run(twice())

    # 키가 없으면 물러서지 않는다 — 가짜 pick 을 빼고 진짜를 부른다.
    with _Env(GEMINI_API_KEY=""):
        import app.session.question as q
        q._CLIENT = None
        try:
            asyncio.run(postcard.pick([{"idx": 1, "question": None, "answer": "말씀"}]))
            check("키가 없으면 503 쪽 오류", False, "고정 문장으로 물러섰다")
        except postcard.PostcardUnavailable:
            check("키가 없으면 503 쪽 오류", True)

    photostore.reset()
    shutil.rmtree(TMP, ignore_errors=True)


def test_all_checks_passed():
    """pytest 안전판 — test_flow.py 의 같은 함수 주석 참조."""
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 엽서 검증")
    test_compose()
    test_key()
    test_routes()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
