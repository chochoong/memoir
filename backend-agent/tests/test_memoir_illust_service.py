"""
자서전 삽화 — 서비스 연결 (memoir_illust_service · 017 · 라우트)

    python -m pytest tests/test_memoir_illust_service.py -q

DB · 모델 · 그림 API 없이 돈다 — store 함수를 메모리로, 그림 저장소를 임시 폴더(LocalStore)로, 장면 선정 · 그림 호출을
가짜로 바꿔 끼운다. 원고 · 원문은 합성 자료(eval/illust_book_seed_B.json)의 앞 세 장이다 — 1장은 회차 사진이 있고 2 · 3장은 없다.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_illust_service as svc, memoir_jobs, photostore, store   # noqa: E402
from tests._auth import AsHeader                                                       # noqa: E402
from tests._nodb import NoDb                                                           # noqa: E402

SEED = json.loads((ROOT / "eval" / "illust_book_seed_B.json").read_text(encoding="utf-8"))
MOCK = json.loads((ROOT / "eval" / "illust_book_mock_B.json").read_text(encoding="utf-8"))
ME, OTHER = "u_me", "u_other"
MID = "m_" + "a" * 32
PHOTO = "11111111-1111-4111-8111-111111111111"


def _jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 32), (200, 180, 150)).save(buf, "JPEG")
    return buf.getvalue()


def book(nos=(1, 2, 3), photo_sessions=("s-01",)):
    """서비스가 저장하는 모양의 자서전 행 · 회차 · 사진 (합성)."""
    chapters = [dict({k: v for k, v in copy.deepcopy(ch).items() if k not in ("photos", "chapter_key")}, status="ready")
                for ch in SEED["memoir"]["chapters"] if ch["no"] in nos]
    utts = {u["session_id"]: u for u in SEED["source"]["utterances"]}
    sids = [f"s-{n:02d}" for n in nos]
    sessions = {sid: {"session_id": sid, "user_id": ME, "created_at": f"2026-01-{i:02d}T09:00:00+00:00",
                      "closing_decision": None, "photo_id": PHOTO if sid in photo_sessions else None,
                      "fragments": [{"idx": 0, "question": None, "answer": "씨앗", "decision": None},
                                    {"idx": 1, "question": utts[sid]["asked"], "answer": utts[sid]["elder"], "decision": None}]}
                for i, sid in enumerate(sids, start=1)}
    result = {"status": "ready", "style": "essay", "title": SEED["memoir"]["title"], "chapters": chapters,
              "run": {"session_ids": sids}}
    row = {"memoir_id": MID, "user_id": ME, "elder_id": None, "style": "essay", "engine": "pipeline", "status": "ready",
           "title": result["title"], "created_at": "2026-01-10T00:00:00+00:00", "session_ids": sids,
           "result": result, "illustrations": None}
    photos = {PHOTO: {"photo_id": PHOTO, "user_id": ME, "status": "stored", "width": 800, "height": 600, "mime": "image/jpeg"}}
    return row, sessions, photos


class FakeDb:
    def __init__(self, monkeypatch, row, sessions, photos):
        self.row, self.sessions, self.photos, self.saves = row, sessions, photos, 0

        async def load_memoir(mid, uid):
            return copy.deepcopy(self.row) if mid == self.row["memoir_id"] and uid == self.row["user_id"] else None

        async def save_memoir_illustrations(mid, uid, doc):
            assert mid == self.row["memoir_id"] and uid == self.row["user_id"]
            self.row["illustrations"] = json.loads(json.dumps(doc, default=str))
            self.saves += 1

        async def load_session(sid):
            return copy.deepcopy(self.sessions.get(sid))

        async def load_photo(pid):
            return copy.deepcopy(self.photos.get(pid))

        for n, f in dict(load_memoir=load_memoir, save_memoir_illustrations=save_memoir_illustrations,
                         load_session=load_session, load_photo=load_photo).items():
            monkeypatch.setattr(store, n, f)


class Calls:
    """가짜 장면 선정 · 그림 — 부른 장을 센다. 합성 모의 후보(eval/illust_book_mock_B.json)를 장 번호로 돌려준다."""

    def __init__(self, image_fails=False):
        self.select, self.image, self.image_fails = [], [], image_fails

    def select_call(self, system, user, *, model):
        no = json.loads(user.split("\n", 1)[1])["chapters"][0]["chapter_no"]
        self.select.append((no, model))
        return {"text": json.dumps(MOCK["by_chapter"][f"c{no:02d}"], ensure_ascii=False), "usage": {"prompt": 10, "output": 5},
                "model_version": model}

    def image_call(self, prompt, *, model):
        self.image.append((prompt, model))
        if self.image_fails:
            raise RuntimeError("그림 API 실패 (시험)")
        return {"status": "completed", "usage": {"total_tokens": 1},
                "output_image": {"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(_jpeg()).decode()}}


@pytest.fixture
def world(monkeypatch, tmp_path):
    row, sessions, photos = book()
    db = FakeDb(monkeypatch, row, sessions, photos)
    monkeypatch.setattr(photostore, "_store", photostore.LocalStore(tmp_path / "blobs"))
    return db


def run(calls: Calls):
    return asyncio.run(svc.run(MID, ME, select_call=calls.select_call, image_call=calls.image_call))


def test_photo_chapter_keeps_photo_and_photo_less_chapters_get_one_illustration_each(world):
    calls = Calls()
    doc = run(calls)
    chs = doc["chapters"]
    assert chs["1"]["state"] == svc.PHOTO and chs["1"]["photos"][0]["photo_id"] == PHOTO
    assert chs["1"]["photos"][0]["after_paragraph"] == 0          # 그 회차 말씀이 처음 나오는 문단 뒤
    assert [no for no, _ in calls.select] == [2, 3]               # 사진 있는 장은 장면 선정도 그림도 부르지 않는다
    assert len(calls.image) == 2
    assert all(m == svc.DEFAULT_SELECT_MODEL for _, m in calls.select) and all(m == svc.DEFAULT_IMAGE_MODEL for _, m in calls.image)
    for k in ("2", "3"):
        assert chs[k]["state"] == svc.ILLUSTRATED
        key = chs[k]["image"]["storage_key"]
        assert key.startswith(f"illusts/") and f"/{MID}/c{k}-" in key
        assert asyncio.run(photostore.current().get(key)) == _jpeg()
        assert isinstance(chs[k]["insertion"]["after_paragraph"], int)
    assert doc["status"] == svc.COMPLETE and doc["calls"] == {"select": 2, "image": 2}
    assert doc["automatic"] is True and doc["human_reviewed"] is False and doc["user_approved"] is False
    # 원고는 그대로다 — 삽화 상태만 따로 적는다
    assert world.row["result"] == book()[0]["result"]

    v = svc.view(MID, world.row["illustrations"])
    figs = {c["no"]: c["figures"] for c in v["chapters"]}
    assert [f["kind"] for f in figs[1]] == ["photo"] and figs[1][0]["url"] == f"/api/photos/{PHOTO}"
    assert [f["kind"] for f in figs[2]] == ["illustration"] and figs[2][0]["ai_generated"] is True
    assert figs[2][0]["url"].startswith(f"/api/memoirs/saved/{MID}/illustrations/2")
    assert "storage_key" not in json.dumps(v)                     # 저장 키는 화면에 나가지 않는다


def test_rerun_keeps_images_without_new_calls_or_duplicates(world):
    first = run(Calls())
    again = Calls()
    second = run(again)
    assert again.select == [] and again.image == []
    for k in ("2", "3"):
        assert second["chapters"][k]["image"]["storage_key"] == first["chapters"][k]["image"]["storage_key"]
    v = svc.view(MID, world.row["illustrations"])
    assert all(len(c["figures"]) == 1 for c in v["chapters"])     # 장마다 한 장 — 두 번 들어가지 않는다
    assert second["calls"] == {"select": 2, "image": 2}


def test_image_failure_keeps_the_text_and_leaves_a_failed_state_without_retry(world):
    calls = Calls(image_fails=True)
    doc = run(calls)
    assert doc["chapters"]["2"]["state"] == svc.FAILED and doc["chapters"]["2"]["failure"] == ["image_call_error"]
    assert doc["status"] == svc.PARTIAL
    assert world.row["result"] == book()[0]["result"]
    v = svc.view(MID, world.row["illustrations"])
    assert {c["no"]: c["state"] for c in v["chapters"]} == {1: "photo", 2: "failed", 3: "failed"}
    assert [len(c["figures"]) for c in v["chapters"]] == [1, 0, 0]
    again = Calls()
    run(again)
    assert again.select == [] and again.image == []              # 실패한 장도 저절로 다시 부르지 않는다


def test_interrupted_calls_are_not_repeated_after_a_restart(world):
    run_doc = svc.new_doc()
    run_doc["chapters"] = {"2": {"no": 2, "title": "장독대", "state": "selecting",
                                 "select": {"attempted_at": "2026-11-16T00:00:00+00:00"}},
                           "3": {"no": 3, "title": "모내기", "state": "drawing",
                                 "select": {"attempted_at": "x", "selection": {"status": "selected", "mode": "OBJECT",
                                                                              "scene": {"scene_title": "t"}, "prompt": {"text": "p"}}},
                                 "image": {"attempted_at": "2026-11-16T00:00:01+00:00"}}}
    world.row["illustrations"] = run_doc
    calls = Calls()
    doc = run(calls)
    assert calls.select == [] and calls.image == []
    assert doc["chapters"]["2"]["failure"] == ["select_attempt_without_result"]
    assert doc["chapters"]["3"]["failure"] == ["image_attempt_without_result"]
    assert doc["chapters"]["1"]["state"] == svc.PHOTO


def test_a_session_photo_counts_only_for_the_one_chapter_it_belongs_to():
    row, _, photos = book()
    chapters = row["result"]["chapters"]
    tmap = [{"global_turn": 1, "session_id": "s-01", "turn": 1}, {"global_turn": 2, "session_id": "s-01", "turn": 2},
            {"global_turn": 3, "session_id": "s-03", "turn": 1}]
    # s-01 의 말씀이 1장 · 2장에 걸쳤다 — 어느 장의 사진으로도 치지 않는다
    placed, unplaced = svc.place_session_photos(chapters, tmap, {"s-01": photos[PHOTO]})
    assert placed == {} and unplaced[0]["reason"] == "session_in_many_chapters" and unplaced[0]["chapters"] == [1, 2]
    placed, unplaced = svc.place_session_photos(chapters, tmap, {"s-09": photos[PHOTO]})
    assert placed == {} and unplaced[0]["reason"] == "session_not_cited"


def test_mixed_session_photo_is_not_shown_and_that_chapter_is_illustrated(monkeypatch, tmp_path):
    row, sessions, photos = book(nos=(1, 2, 3), photo_sessions=("s-02",))
    # 2장 문장이 1번 턴(s-01)도 근거로 든다 — s-02 의 사진은 2장에만 쓰였으므로 2장에 놓인다
    row["result"]["chapters"][1]["paragraphs"][0]["sentences"][0]["turns"] = [1, 2]
    FakeDb(monkeypatch, row, sessions, photos)
    monkeypatch.setattr(photostore, "_store", photostore.LocalStore(tmp_path / "blobs"))
    calls = Calls()
    doc = asyncio.run(svc.run(MID, ME, select_call=calls.select_call, image_call=calls.image_call))
    assert doc["chapters"]["2"]["state"] == svc.PHOTO
    assert [no for no, _ in calls.select] == [1, 3]


def test_not_ready_memoir_is_left_alone(world):
    world.row["result"] = {"status": "insufficient_material", "chapters": [], "title": ""}
    calls = Calls()
    doc = run(calls)
    assert doc["status"] == svc.BROKEN and doc["error"] == "memoir_not_ready" and calls.select == []


def test_schedule_needs_a_key_and_is_off_by_setting(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert svc.enabled() is False and svc.schedule(MID, ME) is None
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("MEMOIR_ILLUST", "off")
    assert svc.enabled() is False
    monkeypatch.setenv("MEMOIR_ILLUST", "auto")
    assert svc.enabled() is True


def test_keep_starts_illustrations_for_a_ready_memoir_only(monkeypatch):
    started = []
    monkeypatch.setattr(store, "enabled", lambda: True)

    async def save_memoir(rec):
        return None
    monkeypatch.setattr(store, "save_memoir", save_memoir)
    monkeypatch.setattr(svc, "schedule", lambda mid, uid: started.append((mid, uid)))
    mid = asyncio.run(memoir_jobs.keep({"status": "ready", "title": "t"}, ["s"], ME, "essay"))
    assert started == [(mid, ME)]
    asyncio.run(memoir_jobs.keep({"status": "insufficient_material", "title": ""}, ["s"], ME, "essay"))
    assert len(started) == 1


def test_routes_show_figures_and_serve_the_image_only_to_the_owner(world):
    asyncio.run(svc.run(MID, ME, select_call=Calls().select_call, image_call=Calls().image_call))
    from fastapi.testclient import TestClient
    from app.main import app
    with NoDb(), AsHeader(), TestClient(app) as c:
        r = c.get(f"/api/memoirs/saved/{MID}", headers={"X-User-Id": ME})
        assert r.status_code == 200
        body = r.json()
        assert body["result"]["title"] == SEED["memoir"]["title"] and body["illustrations"]["status"] == "done"
        url = next(f["url"] for ch in body["illustrations"]["chapters"] for f in ch["figures"] if f["kind"] == "illustration")
        img = c.get(url, headers={"X-User-Id": ME})
        assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg" and img.content == _jpeg()
        assert c.get(url, headers={"X-User-Id": ME, "If-None-Match": img.headers["etag"]}).status_code == 304
        assert c.get(url, headers={"X-User-Id": OTHER}).status_code == 404
        assert c.get(f"/api/memoirs/saved/{MID}/illustrations/1", headers={"X-User-Id": ME}).status_code == 404   # 1장은 사진이다
        light = c.get(f"/api/memoirs/saved/{MID}/illustrations", headers={"X-User-Id": ME}).json()
        assert light == body["illustrations"]
