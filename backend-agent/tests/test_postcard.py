"""
엽서 검증 — 저장 키 · 저장 · 라우트

    python -m tests.test_postcard

DB 는 메모리로 흉내 내고 바이트는 로컬 저장소에 둔다. 여기서 지키는 것 셋.

    [1] 다시 저장하면 키가 바뀐다        주소가 같으면 브라우저가 옛 엽서를 보여 준다
    [2] 다시 저장하면 옛 바이트를 지운다  회차당 한 장이 저장소에서도 한 장이다
    [2] 행을 못 넣으면 바이트를 되돌린다  photo.save 와 같은 규칙이다
    [2] 저장 키는 화면에 안 나간다       주소는 이 서버의 경로뿐이다
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


def test_key():
    print("\n[1] 저장 키 — 다시 저장하면 바뀐다")

    a = postcard.storage_key(SID, b"one")
    png = postcard.storage_key(SID, b"one", "image/png")
    check("형식이 확장자를 따른다", png.endswith(".png") and photostore.check_key(png) == png, png)
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


# ---------------------------------------------------------------- 저장 · 라우트

class _Fake:
    """store 의 회차·엽서 함수를 메모리로 갈아 끼운다."""

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

    def __enter__(self):
        self._saved = (store.load_session, store.save_postcard, store.load_postcard)

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

        store.load_session, store.save_postcard, store.load_postcard = (
            load_session, save_postcard, load_postcard)
        return self

    def __exit__(self, *a):
        store.load_session, store.save_postcard, store.load_postcard = self._saved


def _blobs() -> list[Path]:
    return list(TMP.rglob("*.jpg")) if TMP.exists() else []


def _save(color: int) -> dict:
    return asyncio.run(postcard.save(
        SID, "kim", art(color=(90, 120, color)), "완행열차를 탔지", width=1500, height=1000))


def test_routes():
    print("\n[2] 저장 · 라우트 — 두고, 받고, 다시 둔다")

    from fastapi.testclient import TestClient

    from app.main import app

    shutil.rmtree(TMP, ignore_errors=True)
    kim = {"X-User-Id": "kim"}
    with _Env(AZURE_SPEECH_KEY="", PHOTO_STORE="local", PHOTO_DIR=str(TMP)), _Fake() as fake, NoDb():
        photostore.reset()
        with TestClient(app) as c:
            url = f"/api/sessions/{SID}/postcard"

            r = c.get(url, headers=kim)
            check("안 둔 엽서는 404", r.status_code == 404, str(r.status_code))
            rec = c.get(f"/api/sessions/{SID}/record", headers=kim).json()
            check("안 둔 엽서는 기록에 None", rec.get("postcard") is None, str(rec.get("postcard")))
            check("굽는 라우트는 없다", c.post(url, headers=kim).status_code == 405)

            first = _save(150)
            check("저장소에 한 장", len(_blobs()) == 1, f"{len(_blobs())}장")

            rec = c.get(f"/api/sessions/{SID}/record", headers=kim).json()
            pc = rec.get("postcard") or {}
            check("기록에 엽서가 딸려 온다", str(pc.get("url", "")).startswith(f"{url}?v="),
                  str(pc))
            check("기록에 저장 키는 안 나간다", "storage_key" not in pc)

            got = c.get(pc.get("url", url))
            check("쿠키만으로 받는다", got.status_code == 200
                  and got.headers.get("content-type", "").startswith("image/jpeg"),
                  f"{got.status_code} — <img src> 는 헤더를 못 싣는다")
            check("받은 바이트가 저장한 바이트", len(got.content) == first["bytes"])
            etag = got.headers.get("etag")
            again = c.get(url, headers={**kim, "If-None-Match": etag})
            check("ETag 가 맞으면 304", again.status_code == 304, str(again.status_code))

            c.cookies.clear()
            other = c.get(url, headers={"X-User-Id": "park"})
            check("남의 엽서는 404", other.status_code == 404, str(other.status_code))

            _save(140)
            rec2 = c.get(f"/api/sessions/{SID}/record", headers=kim).json()
            check("다시 저장하면 주소가 바뀐다",
                  (rec2.get("postcard") or {}).get("url") not in (None, pc.get("url")),
                  "주소가 같으면 브라우저가 옛 엽서를 보여 준다")
            check("옛 바이트를 지운다", len(_blobs()) == 1, f"{len(_blobs())}장")
            stale = c.get(url, headers={**kim, "If-None-Match": etag})
            check("옛 ETag 로는 304 가 안 난다", stale.status_code == 200, str(stale.status_code))

            fake.fail = True
            try:
                _save(130)
                check("행을 못 넣으면 오류가 올라간다", False, "통과했다")
            except store.StoreUnavailable:
                check("행을 못 넣으면 오류가 올라간다", True)
            check("새 바이트를 되돌린다", len(_blobs()) == 1, f"{len(_blobs())}장")
            fake.fail = False

    photostore.reset()
    shutil.rmtree(TMP, ignore_errors=True)


def test_all_checks_passed():
    """pytest 안전판 — test_flow.py 의 같은 함수 주석 참조."""
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 엽서 검증")
    test_key()
    test_routes()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
