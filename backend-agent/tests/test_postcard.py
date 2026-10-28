"""
엽서 검증 — 굽기 · 저장 키 · 라우트

    python -m tests.test_postcard

모델은 부르지 않는다. write 를 갈아 끼우고 DB 는 메모리로 흉내 낸다.
여기서 지키는 것.

    [1] 사진은 자르지 않고, 글은 글꼴로 얹는다
    [5] 자료는 DB 기록에서 다시 세운다  사실은 그 말씀의 턴에 붙는다
    [4] 닫혀도 굽지 않는다              수정 반영 · 무수정 확인 뒤 「엽서 만들기」로만
    [6] 틀린 출처는 버리고 문장은 둔다  v3 「본문 출처」 · 로그만 남긴다
    [6] 굽는 것은 ready 뿐이다          엽서.md §8-2 의 상태값
    [7] 마지막 말씀의 판단도 남긴다    턴 행이 없어 회차 행에 둔다
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
from tests._auth import AsHeader                                          # noqa: E402
from tests._nodb import NoDb                                              # noqa: E402

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

CARD = postcard.Card(title="완행열차", sentences=["그해 여름 완행열차는 참 더웠지."],
                     caption="기차 앞의 가족", sources=[{"sentence": 0, "turns": [1]}])


def _paper(px) -> bool:
    return all(abs(a - b) < 8 for a, b in zip(px, postcard.PAPER))


def test_compose():
    print("\n[1] 굽기 — 사진 위, 글 아래")

    font = postcard._font_path()
    data, w, h = postcard._compose(art(), CARD, "2026. 9. 24.", font)
    with Image.open(io.BytesIO(data)) as im:
        check("JPEG 한 장", im.format == "JPEG", im.format)
        check("가로 3:2 엽서", im.size == (postcard.W, postcard.H) == (w, h), str(im.size))
        mid = im.getpixel((postcard.W // 2, postcard.PHOTO_TOP + 200))
        band = im.getpixel((10, postcard.H - 10))
    check("위에 사진이 있다", mid[2] > mid[0], str(mid))
    check("바탕은 종이색", _paper(band), str(band))

    tall, _, _ = postcard._compose(art(600, 900), CARD, "2026. 9. 24.", font)
    with Image.open(io.BytesIO(tall)) as im:
        side = im.getpixel((200, postcard.PHOTO_TOP + 200))
    check("세로 사진은 자르지 않고 칸 안에 맞춘다 (옆은 종이)", _paper(side), str(side))

    bare, _, _ = postcard._compose(None, CARD, "2026. 9. 24.", font)
    with Image.open(io.BytesIO(bare)) as im:
        top = im.getpixel((postcard.W // 2, 20))
    check("사진이 없으면 종이 바탕에 글만", _paper(top), str(top))

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
        postcard._compose(b"not an image", CARD, "2026. 9. 24.", font)
        check("사진이 깨졌으면 503 쪽 오류", False, "통과했다")
    except postcard.PostcardUnavailable:
        check("사진이 깨졌으면 503 쪽 오류", True)

    with _Env(POSTCARD_FONT="Z:/없는/글꼴.ttf"):
        check("POSTCARD_FONT 가 없으면 후보로 넘어간다", postcard._font_path() != "Z:/없는/글꼴.ttf")


def test_photo_branches():
    """
    P5-SV-03 — None 은 「회차에 사진 없음」 하나다. 사진이 있는데 못 읽으면 종이로
    바꿔 굽지 않고 PhotoUnavailable (503 · photo_unavailable) 이다 (태헌 결정 10-26 · 5-C1).
    """
    print("\n[1b] 사진 분기 — 없음은 종이 · 못 읽음은 실패")
    PID = "0191c0de-0000-4abc-8def-0123456789ab"
    good = art(64, 48)

    class _Ps:
        def __init__(self, data=None, err=None):
            self.data, self.err, self.calls = data, err, 0

        async def get(self, key):
            self.calls += 1
            if self.err:
                raise self.err
            return self.data

    def run(photo_id, meta=None, meta_err=None, ps=None):
        old_load, old_cur = store.load_photo, photostore.current

        async def load(pid):
            if meta_err:
                raise meta_err
            return meta
        store.load_photo = load
        photostore.current = lambda: ps or _Ps(good)
        try:
            return asyncio.run(postcard._photo(photo_id))
        finally:
            store.load_photo, photostore.current = old_load, old_cur

    def fails(**kw) -> bool:
        try:
            run(PID, **kw)
        except postcard.PhotoUnavailable as e:
            return e.code == "photo_unavailable"
        return False

    meta = {"storage_key": "photos/x.png", "mime": "image/png", "clues": {"scene": "잔칫상"}}
    p = run(PID, meta)
    check("사진 정상 → 바이트 · 단서", p is not None and p.data == good and p.clues == {"scene": "잔칫상"})
    check("회차에 사진 없음 (photo_id 없음) → None (종이 바탕)", run(None) is None)
    check("사진 행 없음 → photo_unavailable", fails(meta=None))
    check("사진 행 읽기 실패 (DB) → photo_unavailable", fails(meta_err=store.StoreUnavailable("x")))
    ps = _Ps(err=photostore.PhotoStoreError("x"))
    check("사진 바이트 읽기 실패 (저장소) → photo_unavailable", fails(meta=meta, ps=ps) and ps.calls == 1)
    check("바이트는 왔는데 깨짐 → photo_unavailable (모델 전에)", fails(meta=meta, ps=_Ps(b"not an image")))
    check("PhotoUnavailable 은 PostcardUnavailable 이다 (기존 503 경로)",
          issubclass(postcard.PhotoUnavailable, postcard.PostcardUnavailable))

    font = postcard._font_path()
    try:
        postcard._compose(b"not an image", CARD, "2026. 9. 24.", font)
        check("합성에서 깨짐 → PhotoUnavailable", False, "통과했다")
    except postcard.PhotoUnavailable:
        check("합성에서 깨짐 → PhotoUnavailable", True)


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
    """store 의 회차·엽서 함수를 메모리로, write 를 가짜로 갈아 끼운다."""

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
        self.insufficient = False
        self.writes = 0
        self.saves = 0
        self.gate: asyncio.Event | None = None

    def __enter__(self):
        self._saved = (store.load_session, store.save_postcard, store.load_postcard,
                       postcard.write)

        async def load_session(sid):
            if sid != SID:
                return None
            card = self.card
            return {**self.session, "fragments": list(self.session["fragments"]),
                    "postcard": {"title": card["title"], "text": card["text"],
                                 "caption": card["caption"], "storage_key": card["storage_key"],
                                 "style": card["style"] or "spoken",
                                 "created_at": card["created_at"]} if card else None}

        async def save_postcard(rec):
            if self.fail:
                raise store.StoreUnavailable("일부러 실패")
            old = self.card["storage_key"] if self.card else None
            self.saves += 1
            at = f"2026-09-24T10:{20 + self.saves:02d}:00+09:00"     # DB 의 now() 흉내
            self.card = {**rec, "created_at": at}
            return old, at

        async def load_postcard(sid):
            return self.card if sid == SID else None

        async def write(data):
            if self.gate:
                await self.gate.wait()
            if self.insufficient:
                raise postcard.PostcardInsufficient()
            self.writes += 1
            return postcard.Card(title="완행열차", sentences=[f"완행열차를 탔지 {self.writes}."],
                                 caption="", sources=[{"sentence": 0, "turns": [1]}])

        store.load_session, store.save_postcard, store.load_postcard = (
            load_session, save_postcard, load_postcard)
        postcard.write = write
        return self

    def __exit__(self, *a):
        (store.load_session, store.save_postcard, store.load_postcard,
         postcard.write) = self._saved


def _blobs() -> list[Path]:
    return list(TMP.rglob("*.jpg")) if TMP.exists() else []


def test_routes():
    print("\n[3] 라우트 — 굽고, 다시 받고, 다시 굽는다")

    from fastapi.testclient import TestClient

    from app.main import app

    shutil.rmtree(TMP, ignore_errors=True)
    kim = {"X-User-Id": "kim"}
    with _Env(AZURE_SPEECH_KEY="", PHOTO_STORE="local", PHOTO_DIR=str(TMP)), _Fake() as fake, NoDb(), AsHeader():
        photostore.reset()
        with TestClient(app) as c:
            url = f"/api/sessions/{SID}/postcard"

            fake.session["closed_at"] = None
            r = c.post(url, headers=kim)
            check("안 끝난 회차는 409 · code not_closed",
                  r.status_code == 409 and r.json().get("code") == "not_closed",
                  f"{r.status_code} {r.text[:80]}")
            check("409 본문에 detail 은 그대로 있다", bool(r.json().get("detail")), r.text[:80])
            fake.session["closed_at"] = "2026-09-24T10:10:00+09:00"

            frs = fake.session["fragments"]
            fake.session["fragments"] = frs[:1]
            r = c.post(url, headers=kim)
            check("말씀이 없으면 409 · code no_answers",
                  r.status_code == 409 and r.json().get("code") == "no_answers",
                  f"{r.status_code} {r.text[:80]}")
            fake.session["fragments"] = frs

            r = c.post(url, headers={"X-User-Id": "park"})
            check("남의 회차는 404", r.status_code == 404, str(r.status_code))
            check("거절한 뒤에는 모델을 안 불렀다", fake.writes == 0, f"{fake.writes}번")

            fake.insufficient = True
            r = c.post(url, headers=kim)
            check("자료 부족은 409 · code insufficient_material · 저장 안 함",
                  r.status_code == 409 and r.json().get("code") == "insufficient_material"
                  and fake.card is None, f"{r.status_code} {r.text[:80]}")
            fake.insufficient = False

            r = c.post(url, headers=kim)
            check("구우면 200", r.status_code == 200, r.text[:160])
            first = r.json() if r.status_code == 200 else {}
            check("주소는 이 서버의 경로에 버전 꼬리", str(first.get("url", "")).startswith(
                f"{url}?v="), str(first.get("url")))
            check("저장 키는 안 나간다", "storage_key" not in first)
            check("엽서 크기", (first.get("width"), first.get("height")) == (1500, 1000))
            check("저장소에 한 장", len(_blobs()) == 1, f"{len(_blobs())}장")

            bare = c.get(first.get("url", url))
            check("신원 없이 오면 401", bare.status_code == 401, str(bare.status_code))
            got = c.get(first.get("url", url), headers=kim)
            check("주인은 받는다", got.status_code == 200
                  and got.headers.get("content-type", "").startswith("image/jpeg"),
                  f"{got.status_code}")
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
            check("제목도 딸려 온다", pc.get("title") == "완행열차", str(pc))
            check("기록에도 저장 키는 안 나간다", "storage_key" not in pc)
            check("본문 없이 구우면 구어체 · 응답과 기록에 style", first.get("style") == "spoken"
                  and pc.get("style") == "spoken", f"{first.get('style')} {pc.get('style')}")
            check("POST 응답의 created_at 이 기록의 created_at 과 같다 (busy 뒤 판단 기준)",
                  bool(first.get("created_at")) and first.get("created_at") == pc.get("created_at"),
                  f"{first.get('created_at')} {pc.get('created_at')}")

            r2 = c.post(url, headers=kim)
            second = r2.json() if r2.status_code == 200 else {}
            check("다시 구우면 주소가 바뀐다", second.get("url") not in (None, first.get("url")),
                  "주소가 같으면 브라우저가 옛 엽서를 보여 준다")
            check("옛 바이트를 지운다", len(_blobs()) == 1, f"{len(_blobs())}장")
            stale = c.get(url, headers={**kim, "If-None-Match": etag})
            check("옛 ETag 로는 304 가 안 난다", stale.status_code == 200, str(stale.status_code))
            check("다시 구우면 created_at 이 바뀐다",
                  second.get("created_at") not in (None, first.get("created_at")),
                  f"{first.get('created_at')} → {second.get('created_at')}")

            r = c.post(url, json={"style": "spoken"}, headers=kim)
            check("style spoken 을 보내면 200 · spoken", r.status_code == 200
                  and r.json().get("style") == "spoken", f"{r.status_code} {r.text[:80]}")

            # 지원하지 않는 문체 — 모델을 부르지 않고, 옛 엽서를 건드리지 않는다.
            writes, kept = fake.writes, dict(fake.card)
            for v in ("novel", "cyworld", "essay", "Spoken", "", 3, ["spoken"]):
                r = c.post(url, json={"style": v}, headers=kim)
                check(f"style {v!r} → 400 · code unsupported_style",
                      r.status_code == 400 and r.json() == {
                          "detail": "지원하지 않는 문체예요.", "code": "unsupported_style"},
                      f"{r.status_code} {r.text[:80]}")
            check("거절한 문체로는 모델을 안 불렀다", fake.writes == writes, f"{fake.writes - writes}번")
            check("거절한 뒤 옛 엽서가 그대로다", fake.card == kept)

            r = c.post(url, content=b"{not json", headers={**kim, "Content-Type": "application/json"})
            check("깨진 본문 → 400 · code 없음", r.status_code == 400
                  and "code" not in r.json(), f"{r.status_code} {r.text[:80]}")
            r = c.post(url, json=["spoken"], headers=kim)
            check("객체가 아닌 본문 → 400 · code 없음", r.status_code == 400
                  and "code" not in r.json(), f"{r.status_code} {r.text[:80]}")

            fake.fail = True
            r3 = c.post(url, headers=kim)
            check("행을 못 넣으면 503", r3.status_code == 503, str(r3.status_code))
            check("새 바이트를 되돌린다", len(_blobs()) == 1, f"{len(_blobs())}장")
            fake.fail = False

            # 사진을 못 읽으면 종이로 바꿔 굽지 않는다 — 모델 전에 멈추고 옛 엽서를 둔다.
            real_photo, writes, kept = postcard._photo, fake.writes, dict(fake.card)

            async def unreadable(photo_id):
                raise postcard.PhotoUnavailable("회차 사진을 읽지 못했습니다")
            postcard._photo = unreadable
            try:
                r = c.post(url, headers=kim)
            finally:
                postcard._photo = real_photo
            check("사진을 못 읽으면 503 · code photo_unavailable",
                  r.status_code == 503 and r.json().get("code") == "photo_unavailable",
                  f"{r.status_code} {r.text[:80]}")
            check("사진을 못 읽으면 모델을 안 부르고 옛 엽서가 그대로다",
                  fake.writes == writes and fake.card == kept and len(_blobs()) == 1)

        async def twice():
            fake.gate = asyncio.Event()
            a = asyncio.create_task(postcard.make(SID, "kim"))
            await asyncio.sleep(0.05)
            try:
                await postcard.make(SID, "kim")
                check("굽는 중에 또 누르면 409 쪽 오류", False, "두 번 썼다")
            except postcard.PostcardNotReady as e:
                check("굽는 중에 또 누르면 409 쪽 오류 · code busy", e.code == "busy", e.code)
            fake.gate.set()
            await a
            fake.gate = None
        asyncio.run(twice())

    # 키가 없으면 물러서지 않는다 — 가짜 write 를 빼고 진짜를 부른다.
    with _Env(GEMINI_API_KEY=""):
        import app.session.question as q
        q._CLIENT = None
        try:
            asyncio.run(postcard.write({"utterances": []}))
            check("키가 없으면 503 쪽 오류", False, "고정 문장으로 물러섰다")
        except postcard.PostcardUnavailable:
            check("키가 없으면 503 쪽 오류", True)

    photostore.reset()
    shutil.rmtree(TMP, ignore_errors=True)


def test_inject():
    """시험 서버의 실패 · 지연 주입. 모델 값 없이 화면의 busy · 실패 처리를 본다 (4-C1 §6)."""
    print("\n[S6] 실패 · 지연 주입")

    from fastapi.testclient import TestClient

    from app.main import app

    shutil.rmtree(TMP, ignore_errors=True)
    kim = {"X-User-Id": "kim"}
    url = f"/api/sessions/{SID}/postcard"
    with _Env(AZURE_SPEECH_KEY="", PHOTO_STORE="local", PHOTO_DIR=str(TMP),
              POSTCARD_FAIL_INJECT="off", POSTCARD_INJECT_DELAY="0"), _Fake() as fake, NoDb(), AsHeader():
        photostore.reset()
        with TestClient(app) as c:
            first = c.post(url, headers=kim).json()
            kept, writes = dict(fake.card), fake.writes

            with _Env(POSTCARD_FAIL_INJECT="generation_failed"):
                r = c.post(url, headers=kim)
                check("generation_failed → 503", r.status_code == 503, f"{r.status_code} {r.text[:80]}")
                check("503 안내는 실제 실패와 같다 — 주입 이름이 새지 않는다",
                      "INJECT" not in r.text, r.text[:80])
            with _Env(POSTCARD_FAIL_INJECT="insufficient_material"):
                r = c.post(url, headers=kim)
                check("insufficient_material → 409 · code insufficient_material",
                      r.status_code == 409 and r.json().get("code") == "insufficient_material",
                      f"{r.status_code} {r.text[:80]}")
            check("주입한 실패는 모델을 안 부른다", fake.writes == writes, f"{fake.writes - writes}번")
            check("주입한 실패 뒤 옛 엽서가 그대로다 (행 · 바이트)",
                  fake.card == kept and len(_blobs()) == 1, f"{len(_blobs())}장")
            rec = c.get(f"/api/sessions/{SID}/record", headers=kim).json()["postcard"]
            check("기록은 옛 엽서의 created_at · 주소 · 문체를 준다",
                  (rec["created_at"], rec["url"], rec["style"])
                  == (first["created_at"], first["url"], "spoken"), str(rec))

            with _Env(POSTCARD_FAIL_INJECT="generation_failed"):
                r = c.post(url, json={"style": "novel"}, headers=kim)
                check("문체 거절이 주입보다 먼저다 (400)", r.status_code == 400
                      and r.json().get("code") == "unsupported_style", f"{r.status_code}")

        async def overlap():
            """늦추는 동안 또 누르면 busy, 첫 요청은 걸어 둔 실패로 끝난다."""
            a = asyncio.create_task(postcard.make(SID, "kim"))
            await asyncio.sleep(0.1)
            try:
                await postcard.make(SID, "kim")
                check("늦추는 동안 또 누르면 busy", False, "두 번 들어갔다")
            except postcard.PostcardNotReady as e:
                check("늦추는 동안 또 누르면 busy", e.code == "busy", e.code)
            try:
                await a
                check("늦춘 뒤 걸어 둔 실패로 끝난다", False, "성공했다")
            except postcard.PostcardUnavailable:
                check("늦춘 뒤 걸어 둔 실패로 끝난다", True)
            check("끝나면 busy 가 풀린다", SID not in postcard._busy)

        with _Env(POSTCARD_FAIL_INJECT="generation_failed", POSTCARD_INJECT_DELAY="0.4"):
            asyncio.run(overlap())
        check("겹친 요청도 모델을 안 부른다", fake.writes == writes, f"{fake.writes - writes}번")

    with _Env(POSTCARD_FAIL_INJECT="nonsense"):
        check("모르는 주입 값은 끈 것으로 읽는다", postcard.inject() == "")
    for v, want in (("999", postcard.INJECT_DELAY_MAX), ("-5", 0.0), ("", 0.0)):
        with _Env(POSTCARD_INJECT_DELAY=v):
            check(f"늦추기 {v!r} → {want}초", postcard.inject_delay() == want, str(postcard.inject_delay()))

    photostore.reset()
    shutil.rmtree(TMP, ignore_errors=True)


def test_auto():
    """회차가 닫히면 closed_fn 이 불린다. 서버의 closed_fn(on_closed)은 엽서를 굽지 않는다."""
    print("\n[4] 닫혀도 굽지 않는다")
    from app.session.controller import SessionController

    async def run():
        closed: list[tuple[str, str, str]] = []

        async def on_closed(sid, uid, reason):
            closed.append((sid, uid, reason))

        async def no_tts(text):
            return b""

        # 「중단」 — 두 번 눌러도 한 번만
        a = SessionController(user_id="u", title="시험", pace="fast",
                              tts_fn=no_tts, closed_fn=on_closed)
        await a.start("씨앗")
        await a.abort()
        await a.abort()

        # AI 의 마무리 — question_fn 이 None 을 돌려준다
        async def close_now(ctl):
            ctl.last_decision = {"end_reason": "user_request"}
            return None

        b = SessionController(user_id="u", title="시험", pace="fast",
                              tts_fn=no_tts, question_fn=close_now, closed_fn=on_closed)
        await b.start("씨앗")
        await asyncio.sleep(0.05)
        await b.tts_done()
        await b.speech("이제 그만할래")
        await b.done_button()
        for _ in range(40):
            if b.machine.state.value == "CLOSED":
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.05)
        a.release()
        b.release()
        return a, b, closed

    a, b, closed = asyncio.run(run())
    check("중단하면 한 번 불린다",
          [c for c in closed if c[0] == a.session_id] == [(a.session_id, "u", "abort")],
          str(closed))
    check("마무리하면 사유와 함께 불린다",
          [c for c in closed if c[0] == b.session_id] == [(b.session_id, "u", "user_request")],
          str(closed))

    made: list[str] = []
    real = postcard.make

    async def fake_make(sid, uid):
        made.append(sid)
        return {}

    postcard.make = fake_make
    try:
        for reason in ("abort", "user_request", "info_complete", "max_turn", "expired", "sensitive"):
            asyncio.run(postcard.on_closed("s-" + reason, "u", reason))
    finally:
        postcard.make = real
    check("어떤 사유로 닫혀도 굽지 않는다", made == [], str(made))

    import app.main as main
    check("서버는 on_closed 를 건다 — 마지막 말씀의 판단은 그대로 남긴다",
          "closed_fn=postcard.on_closed" in Path(main.__file__).read_text(encoding="utf-8"))


def test_material():
    print("\n[5] 자료 — DB 기록에서 다시 세운다")
    frs = [
        {"idx": 0, "question": None, "answer": "잔치 사진", "decision": None},
        {"idx": 1, "question": "무슨 사진이에요?", "answer": "칠순 잔치야",
         "decision": {"facts_found": ["씨앗에서 나온 사실"]}},
        {"idx": 2, "question": "어디서요?", "answer": "아니 칠순 아니고 환갑이야. 부산에서",
         "decision": {"facts_found": ["칠순 잔치를 했다"]}},
        {"idx": 3, "question": "누구와요?", "answer": "",
         "decision": {"facts_found": ["환갑 잔치를 했다", "부산에서 했다"],
                      "facts_retracted": ["칠순 잔치"]}},
    ]
    m = postcard.material(frs, {"scene": "잔칫상"})
    st = m["shared_state"]
    check("아니라고 하신 사실은 빠진다", "칠순 잔치를 했다" not in st["confirmed_facts"],
          str(st["confirmed_facts"]))
    check("사실은 그 말씀의 턴(N-1)에 붙는다",
          {"turn": 2, "facts": ["환갑 잔치를 했다", "부산에서 했다"]} in st["facts_found"],
          str(st["facts_found"]))
    check("씨앗(0번)에서 나온 사실은 턴이 없다",
          all(x["turn"] > 0 for x in st["facts_found"]), str(st["facts_found"]))
    check("사진 분석이 실린다", st.get("photo_analyses") == [{"scene": "잔칫상"}])
    check("빈 말씀과 씨앗은 발화에 없다",
          [u["turn"] for u in m["utterances"]] == [1, 2], str(m["utterances"]))
    check("사진이 없으면 photo_analyses 도 없다",
          "photo_analyses" not in postcard.material(frs, None)["shared_state"])

    last = [
        {"idx": 0, "question": None, "answer": "", "decision": None},
        {"idx": 1, "question": "무슨 이야기요?", "answer": "고양이", "decision": None},
        {"idx": 2, "question": "고양이요?", "answer": "나비라고 불렀어",
         "decision": {"facts_found": ["고양이"]}},
    ]
    st = postcard.material(last, None, {"facts_found": ["이름은 나비"]})["shared_state"]
    check("마지막 말씀의 판단은 마지막 턴에 붙는다",
          {"turn": 2, "facts": ["이름은 나비"]} in st["facts_found"], str(st["facts_found"]))
    check("없으면 마지막 턴의 사실도 없다",
          all(x["turn"] != 2 for x in
              postcard.material(last, None)["shared_state"]["facts_found"]))


def test_closing():
    """닫힐 때 마지막 말씀의 판단을 남긴다. 없으면 한 번 더 받는다."""
    print("\n[7] 마지막 말씀의 판단")
    from app.session import store
    from app.session.controller import SessionController

    async def run(wait_question: bool):
        asked: list[int] = []
        saved: list[dict] = []

        async def ask(ctl):
            n = ctl.fragments[-1]["idx"]
            asked.append(n)
            ctl.last_decision = {"facts_found": [f"말씀 {n}"]}
            return f"질문 {n}"

        async def keep(ctl, decision):
            saved.append(decision)

        async def no_tts(text):
            return b""

        async def on_closed(sid, uid, reason):
            pass

        real, store.save_closing_decision = store.save_closing_decision, keep
        try:
            c = SessionController(user_id="u", title="시험", pace="fast", tts_fn=no_tts,
                                  question_fn=ask, closed_fn=on_closed)
            await c.start("씨앗")
            await asyncio.sleep(0.05)
            await c.tts_done()
            await c.speech("고양이")
            await c.done_button()
            if wait_question:
                for _ in range(40):
                    if c.machine.state.value == "SPEAKING":
                        break
                    await asyncio.sleep(0.05)
            await c.abort()
            for _ in range(40):
                if saved:
                    break
                await asyncio.sleep(0.05)
            c.release()
        finally:
            store.save_closing_decision = real
        return asked, saved

    asked, saved = asyncio.run(run(wait_question=True))
    check("판단이 있으면 다시 부르지 않는다", asked == [1], str(asked))
    check("있는 판단을 남긴다", saved == [{"facts_found": ["말씀 1"]}], str(saved))

    asked, saved = asyncio.run(run(wait_question=False))
    check("말씀 직후 중단이면 한 번 더 받아 남긴다",
          saved == [{"facts_found": ["말씀 1"]}] and asked[-1] == 1, f"{asked} {saved}")


def _out(**kv) -> dict:
    """엽서.md §8-2 의 8키 응답. 기본은 ready."""
    out = {"status": "ready", "title": "", "body": "", "sources": [], "to_confirm": [],
           "missing_context": [], "coverage_notes": [], "caption": ""}
    out.update(kv)
    return out


def test_checked():
    print("\n[6] 출처 검사 — 문장은 그대로, 틀린 출처만 버린다")
    card = postcard.parse(_out(
        title="부산 환갑",
        body="부산에서 환갑 잔치를 했어요.\n온 식구가 모였어요.\n참 좋았어요.",
        sources=[{"sentence": 0, "turns": [2]}, {"sentence": 1, "turns": [9]},
                 {"sentence": 2, "turns": [1, 2]}],
    ))
    check("본문은 줄바꿈으로 나눈다", len(card.sentences) == 3, str(card.sentences))
    out = postcard.checked(card, {1, 2})
    check("없는 턴을 가리키는 문장도 남긴다", out.sentences == card.sentences, str(out.sentences))
    check("그 출처만 버린다", out.sources == [
        {"sentence": 0, "turns": [2]}, {"sentence": 2, "turns": [1, 2]}], str(out.sources))

    one = postcard.parse(_out(body="환갑이었어요. 부산이었어요."))
    check("한 줄로 오면 마침표에서 나눈다", len(one.sentences) == 2, str(one.sentences))
    check("근거가 하나도 없어도 굽는다", postcard.checked(one, {1}).sentences == one.sentences)
    try:
        postcard.checked(postcard.Card(title="", sentences=[], caption="", sources=[]), {1})
        check("본문이 비면 409 쪽 오류", False, "구웠다")
    except postcard.PostcardInsufficient as e:
        check("본문이 비면 409 쪽 오류 · 자료 부족과 같은 code", e.code == "insufficient_material")

    print("\n[6] 굽는 것은 ready 뿐이다")
    try:
        postcard.parse(_out(status="insufficient_material", coverage_notes=["말씀이 없음"]))
        check("자료 부족은 409 쪽 · 실패와 다른 오류", False, "통과했다")
    except postcard.PostcardInsufficient:
        check("자료 부족은 409 쪽 · 실패와 다른 오류", True)
    for status, key in (("needs_confirmation", "to_confirm"), ("needs_context", "missing_context")):
        reasons = [{"issue": "누구의 일인지", "turns": [2]}] if key == "to_confirm" else ["원문 없음"]
        try:
            postcard.parse(_out(status=status, **{key: reasons}))
            got = None
        except postcard.PostcardNotFinal as e:
            got = e
        check(f"{status} — 503 쪽 오류 · 상태와 사유를 구분해 들고 간다",
              isinstance(got, postcard.PostcardUnavailable) and got.status == status
              and got.reasons == reasons, repr(got))
    for status in ("completed", ""):
        try:
            postcard.parse(_out(status=status))
            check(f"모르는 status {status!r} 는 503 쪽 오류", False, "통과했다")
        except postcard.PostcardNotFinal:
            check(f"모르는 status {status!r} 는 503 쪽 오류", False, "확인 필요로 읽었다")
        except postcard.PostcardUnavailable:
            check(f"모르는 status {status!r} 는 503 쪽 오류", True)

    p = postcard._prompt()
    check("프롬프트는 엽서_v3.md 의 실행 절이다 (§2 · §5 · §5-1 · §7-4 · §8-2)",
          postcard.PROMPT.name == "엽서_v3.md"
          and p.startswith("당신은 한국어 인생기록 서비스") and "사진 속 기억을 담은" in p
          and "위 8개 키만 반환한다" in p and "문자 수는 NFC" in p and "상태 우선순위" in p, p[:30])
    check("다른 역할 절은 싣지 않는다", "자서전 담당" not in p)
    check("울타리 줄(``` · ~~~)은 싣지 않는다", "~~~" not in p and "```" not in p)


def test_list():
    """목록은 has_postcard · postcard_title 을 싣고, ?has_postcard=1 이면 엽서 있는 회차만 준다."""
    print("\n[8] 목록에서 엽서 있는 회차 거르기")
    from fastapi.testclient import TestClient

    from app.main import app

    rows = [{"session_id": "a", "has_postcard": True, "postcard_title": "처음 연 가게"},
            {"session_id": "b", "has_postcard": False, "postcard_title": None}]
    got: list[tuple] = []
    real = store.list_sessions

    async def fake_list(user_id, limit=20, has_postcard=False, elder_id=None):
        got.append((user_id, limit, has_postcard))
        return [r for r in rows if r["has_postcard"]] if has_postcard else rows

    store.list_sessions = fake_list
    try:
        with _Env(AZURE_SPEECH_KEY=""), NoDb(), AsHeader(), TestClient(app) as c:
            kim = {"X-User-Id": "kim"}
            r = c.get("/api/sessions", headers=kim)
            check("옵션이 없으면 예전처럼 전부 · 회차마다 has_postcard",
                  r.status_code == 200 and r.json()["sessions"] == rows and got[-1] == ("kim", 20, False),
                  f"{r.status_code} {got[-1:]}")
            r = c.get("/api/sessions?has_postcard=1&limit=50", headers=kim)
            check("has_postcard=1 이면 엽서 있는 회차만",
                  r.status_code == 200 and [s["session_id"] for s in r.json()["sessions"]] == ["a"]
                  and got[-1] == ("kim", 50, True), f"{r.status_code} {got[-1:]}")
            check("엽서가 없어도 postcard_title 칸은 빠지지 않고 null 이다",
                  all("postcard_title" in s for s in c.get("/api/sessions", headers=kim).json()["sessions"])
                  and c.get("/api/sessions", headers=kim).json()["sessions"][1]["postcard_title"] is None)
    finally:
        store.list_sessions = real

    sql = Path(store.__file__).read_text(encoding="utf-8")
    check("거르는 것은 DB 다 — limit 안에서 거르면 다시 밀린다",
          "AND p.session_id IS NOT NULL" in sql)
    check("엽서 제목은 목록 SQL 이 엽서 표에서 같이 읽는다 (/record 의 postcard.title 과 같은 열)",
          "p.title AS postcard_title" in sql and '"postcard_title": r["postcard_title"]' in sql)


def test_all_checks_passed():
    """pytest 안전판 — test_flow.py 의 같은 함수 주석 참조."""
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 엽서 검증")
    test_compose()
    test_photo_branches()
    test_key()
    test_routes()
    test_inject()
    test_auto()
    test_material()
    test_checked()
    test_closing()
    test_list()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
