"""
엽서 검증 — 굽기 · 저장 키 · 라우트

    python -m tests.test_postcard

모델은 부르지 않는다. write 를 갈아 끼우고 DB 는 메모리로 흉내 낸다.
여기서 지키는 것.

    [1] 사진은 자르지 않고, 글은 글꼴로 얹는다
    [5] 자료는 DB 기록에서 다시 세운다  사실은 그 말씀의 턴에 붙는다
    [6] 틀린 출처는 버리고 문장은 둔다  v3 「본문 출처」 · 로그만 남긴다
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
        self.writes = 0
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
                                 "created_at": "2026-09-24T10:20:00+09:00"} if card else None}

        async def save_postcard(rec):
            if self.fail:
                raise store.StoreUnavailable("일부러 실패")
            old = self.card["storage_key"] if self.card else None
            self.card = dict(rec)
            return old

        async def load_postcard(sid):
            return self.card if sid == SID else None

        async def write(data):
            if self.gate:
                await self.gate.wait()
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
    with _Env(AZURE_SPEECH_KEY="", PHOTO_STORE="local", PHOTO_DIR=str(TMP)), _Fake() as fake, NoDb():
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
            check("거절한 뒤에는 모델을 안 불렀다", fake.writes == 0, f"{fake.writes}번")

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
            check("제목도 딸려 온다", pc.get("title") == "완행열차", str(pc))
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
                check("굽는 중에 또 누르면 409 쪽 오류", False, "두 번 썼다")
            except postcard.PostcardNotReady:
                check("굽는 중에 또 누르면 409 쪽 오류", True)
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


def test_auto():
    """회차가 닫히면 엽서를 굽는다. 떠난 회차 · 힘든 기억은 굽지 않는다."""
    print("\n[4] 닫히면 자동으로 굽는다")
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
        if sid == "boom":
            raise RuntimeError("터졌다")
        if sid == "down":
            raise store.StoreUnavailable("DB 없음")
        return {}

    postcard.make = fake_make
    try:
        for reason in ("expired", "sensitive"):
            asyncio.run(postcard.auto("skip-" + reason, "u", reason))
        asyncio.run(postcard.auto("ok", "u", "finish"))
        err = None
        try:
            asyncio.run(postcard.auto("boom", "u", "abort"))
            asyncio.run(postcard.auto("down", "u", "info_complete"))
        except Exception as e:                                   # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
    finally:
        postcard.make = real
    check("떠난 회차 · 힘든 기억은 굽지 않는다",
          not any(s.startswith("skip-") for s in made), str(made))
    check("그 밖의 사유는 굽는다", "ok" in made, str(made))
    check("굽다 실패해도 예외가 새지 않는다", err is None, err or "")


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


def test_checked():
    print("\n[6] 출처 검사 — 문장은 그대로, 틀린 출처만 버린다")
    card = postcard.parse({
        "status": "completed", "title": "부산 환갑",
        "body": "부산에서 환갑 잔치를 했어요.\n온 식구가 모였어요.\n참 좋았어요.",
        "caption": "", "changed_fields": [], "confirmation_questions": [],
        "sources": [{"sentence": 0, "turns": [2]}, {"sentence": 1, "turns": [9]},
                    {"sentence": 2, "turns": [1, 2]}],
    })
    check("본문은 줄바꿈으로 나눈다", len(card.sentences) == 3, str(card.sentences))
    out = postcard.checked(card, {1, 2})
    check("없는 턴을 가리키는 문장도 남긴다", out.sentences == card.sentences, str(out.sentences))
    check("그 출처만 버린다", out.sources == [
        {"sentence": 0, "turns": [2]}, {"sentence": 2, "turns": [1, 2]}], str(out.sources))

    one = postcard.parse({"status": "completed", "title": "", "caption": "",
                          "body": "환갑이었어요. 부산이었어요.", "sources": []})
    check("한 줄로 오면 마침표에서 나눈다", len(one.sentences) == 2, str(one.sentences))
    check("근거가 하나도 없어도 굽는다", postcard.checked(one, {1}).sentences == one.sentences)
    try:
        postcard.checked(postcard.Card(title="", sentences=[], caption="", sources=[]), {1})
        check("본문이 비면 409 쪽 오류", False, "구웠다")
    except postcard.PostcardNotReady:
        check("본문이 비면 409 쪽 오류", True)
    try:
        postcard.parse({"status": "needs_confirmation", "confirmation_questions": ["?"]})
        check("자동 생성에서 확인 요청은 503 쪽 오류", False, "통과했다")
    except postcard.PostcardUnavailable:
        check("자동 생성에서 확인 요청은 503 쪽 오류", True)
    p = postcard._prompt()
    check("프롬프트는 문서의 코드 블록 안이다", p.startswith("목표") and "```" not in p, p[:20])


def test_all_checks_passed():
    """pytest 안전판 — test_flow.py 의 같은 함수 주석 참조."""
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 엽서 검증")
    test_compose()
    test_key()
    test_routes()
    test_auto()
    test_material()
    test_checked()
    test_closing()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
