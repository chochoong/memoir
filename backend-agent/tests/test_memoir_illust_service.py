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
MOCK = json.loads((ROOT / "eval" / "illust_book_mock_B.json").read_text(encoding="utf-8"))          # 장면 방식(scene) 모의 후보
THEME = json.loads((ROOT / "eval" / "illust_theme_mock_D.json").read_text(encoding="utf-8"))["B"]  # 주제 방식(theme) 모의 계획
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
    """
    가짜 선정 · 그림 — 부른 장을 센다. 받은 자료의 모양으로 방식을 가려 그 방식의 합성 모의 응답을 돌려준다
    (주제: eval/illust_theme_mock_D.json 의 B · 장면: eval/illust_book_mock_B.json).
    """

    def __init__(self, image_fails=False):
        self.select, self.image, self.image_fails, self.policies = [], [], image_fails, []

    def select_call(self, system, user, *, model):
        payload = json.loads(user.split("\n", 1)[1])
        if "chapter" in payload:                                   # 주제 방식 — 장 하나의 본문 전체
            no = payload["chapter"]["chapter_no"]
            self.policies.append("theme")
            reply = THEME[str(no)]
        else:                                                      # 장면 방식 — 장 목록 · 문장 · 원문
            no = payload["chapters"][0]["chapter_no"]
            self.policies.append("scene")
            reply = MOCK["by_chapter"][f"c{no:02d}"]
        self.select.append((no, model))
        return {"text": json.dumps(reply, ensure_ascii=False), "usage": {"prompt": 10, "output": 5}, "model_version": model}

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


def test_a_session_photo_split_over_chapters_goes_to_one_representative_chapter():
    """
    2026-11-24 뜻이 바뀐 시험 — 앞서는 「여러 장에 걸친 회차의 사진은 어느 장에도 놓지 않는다」(session_in_many_chapters)를 확인했다.
    그 규칙이 사용자가 붙인 사진을 빠뜨리고 그 장들에 AI 삽화를 넣는 원인이라, 대표 장 한 곳에 놓는 규칙으로 바꿨다
    (자세한 사례는 tests/test_memoir_illust_photos.py).
    """
    row, _, photos = book()
    chapters = row["result"]["chapters"]
    tmap = [{"global_turn": 1, "session_id": "s-01", "turn": 1}, {"global_turn": 2, "session_id": "s-01", "turn": 2},
            {"global_turn": 3, "session_id": "s-03", "turn": 1}]
    # s-01 의 말씀이 1장(턴 1) · 2장(턴 2)에 한 턴씩 걸쳤다 — 같으면 그 회차의 앞선 턴을 쓴 1장
    placed, unplaced = svc.place_session_photos(chapters, tmap, {"s-01": photos[PHOTO]})
    assert unplaced == [] and list(placed) == [1] and placed[1][0]["placement"]["chapters"] == {"1": 1, "2": 1}
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


# ---------------------------------------------------------------- 방식 (목차 주제 기본 · 장면) · 실패한 장만 새 방식으로


def test_default_service_policy_is_chapter_theme_and_is_recorded_per_chapter(world):
    calls = Calls()
    doc = run(calls)
    assert calls.policies == ["theme", "theme"]
    sel = doc["chapters"]["2"]["select"]
    # v2 로 판이 바뀌었다 (지시문 v7 · 검사 theme_checks_v2) — 기본 방식이 장마다 기록된다는 뜻은 같다
    assert sel["policy_id"] == "chapter_theme_v2" and sel["prompt_file"] == "1_목차주제_v7.md" and sel["mode"] == "THEME"
    assert sel["checks_version"] == "theme_checks_v2"
    assert doc["settings"]["policy_id"] == "chapter_theme_v2"
    assert all("[이 장의 주제]" in p and "watercolor" not in p for p, _ in calls.image)       # 주제 방식의 한국어 지시문
    v = svc.view(MID, world.row["illustrations"])
    assert v["policy"] == "chapter_theme_v2"
    assert {c["no"]: c["policy"] for c in v["chapters"]} == {1: None, 2: "chapter_theme_v2", 3: "chapter_theme_v2"}


def test_scene_policy_is_still_available_by_setting(world, monkeypatch):
    monkeypatch.setenv("MEMOIR_ILLUST_POLICY", "scene")
    calls = Calls()
    doc = run(calls)
    assert calls.policies == ["scene", "scene"]
    assert doc["chapters"]["2"]["select"]["policy_id"] == "scene_v5"
    monkeypatch.setenv("MEMOIR_ILLUST_POLICY", "story")
    with pytest.raises(Exception):
        svc.policy()


def _old_production_like(world):
    """이 변경 전의 기록처럼 — 1장은 앞선 방식으로 넣은 삽화, 2 · 3장은 앞선 방식으로 실패 (방식 칸 없음)."""
    world.row["result"]["run"]["session_ids"] = ["s-01", "s-02", "s-03"]
    world.sessions["s-01"]["photo_id"] = None                     # 1장도 사진 없이
    run(Calls())
    doc = world.row["illustrations"]
    for k, ch in doc["chapters"].items():
        for rec in (ch.get("select") or {}, ):
            for f in ("policy", "policy_id", "prompt_file", "style_hash"):
                rec.pop(f, None)
        ch.pop("policy", None)
    for k in ("2", "3"):
        doc["chapters"][k].update(state=svc.FAILED, failure=["no_representative_candidate"], image=None, insertion=None)
        doc["chapters"][k]["select"]["selection"] = {"status": "failed", "reasons": ["no_representative_candidate"]}
    doc["status"] = svc.PARTIAL
    doc["settings"].pop("policy_id", None)
    return doc


def test_reprocess_marks_only_failed_chapters_and_keeps_the_illustrated_one(world):
    old = _old_production_like(world)
    key1 = old["chapters"]["1"]["image"]["storage_key"]
    assert [t["no"] for t in svc.reprocess_targets(old, "theme")] == [2, 3]
    assert all(t["from_policy"] == "scene_v5" and t["to_policy"] == "chapter_theme_v2" for t in svc.reprocess_targets(old))
    calls_before = dict(old["calls"])

    assert asyncio.run(svc.prepare_reprocess(MID, ME, "theme"))["refused"] == "chapters_required"     # 장을 이름 대지 않으면 하지 않는다
    done = asyncio.run(svc.prepare_reprocess(MID, ME, "theme", [2, 3]))
    assert done["changed"] and done["calls_expected"] == {"select": 2, "image": 2}
    doc = world.row["illustrations"]
    assert doc["status"] == svc.RUNNING and doc["calls"] == calls_before        # 표시만 — 부르지 않았고 횟수도 그대로
    for k in ("2", "3"):
        ch = doc["chapters"][k]
        assert ch["state"] == svc.PENDING and ch["policy"] == "theme"
        assert ch["history"][0]["policy_id"] == "scene_v5" and ch["history"][0]["failure"] == ["no_representative_candidate"]
    assert doc["chapters"]["1"]["state"] == svc.ILLUSTRATED and "history" not in doc["chapters"]["1"]

    calls = Calls()
    after = run(calls)
    assert [no for no, _ in calls.select] == [2, 3] and len(calls.image) == 2   # 1장은 부르지 않는다
    assert after["chapters"]["1"]["image"]["storage_key"] == key1
    assert {k: c["state"] for k, c in after["chapters"].items()} == {"1": "illustrated", "2": "illustrated", "3": "illustrated"}
    assert after["chapters"]["2"]["select"]["policy_id"] == "chapter_theme_v2"
    assert after["calls"] == {"select": calls_before["select"] + 2, "image": calls_before["image"] + 2}
    v = svc.view(MID, world.row["illustrations"])
    assert [c["policy"] for c in v["chapters"]] == ["scene_v5", "chapter_theme_v2", "chapter_theme_v2"]   # 1장은 앞선 방식의 그림이다


def test_reprocess_does_not_repeat_a_chapter_already_tried_with_the_new_policy(world):
    _old_production_like(world)
    asyncio.run(svc.prepare_reprocess(MID, ME, "theme", [2, 3]))
    failing = Calls(image_fails=True)
    run(failing)                                                   # 새 방식으로도 그림이 실패했다
    doc = world.row["illustrations"]
    assert {k: c["state"] for k, c in doc["chapters"].items() if k != "1"} == {"2": "failed", "3": "failed"}
    assert svc.reprocess_targets(doc, "theme") == []               # 기록을 옮겨 다시 부르게 하지 않는다
    again = asyncio.run(svc.prepare_reprocess(MID, ME, "theme", [2, 3]))
    assert all(r["why"].startswith("지금 판(chapter_theme_v2)") for r in again["refused_chapters"])
    assert again["changed"] is False
    calls = Calls()
    run(calls)
    assert calls.select == [] and calls.image == []


def test_reprocess_leaves_photo_and_unknown_chapters_alone(world):
    doc = svc.new_doc()
    doc["chapters"] = {"1": {"no": 1, "state": svc.PHOTO}, "2": {"no": 2, "state": svc.UNKNOWN, "failure": ["photo_info_missing"]},
                       "3": {"no": 3, "state": svc.HELD, "select": {"attempted_at": "x"}},
                       "4": {"no": 4, "state": svc.FAILED, "failure": ["error_input"]}}
    assert [t["no"] for t in svc.reprocess_targets(doc, "theme")] == [4]   # 부르기 전에 실패한 장은 어느 방식으로도 부른 적이 없다


def test_reprocess_tool_prints_the_plan_and_only_marks(world, monkeypatch, capsys):
    from tools import memoir_illust_reprocess as tool
    _old_production_like(world)

    async def nothing():
        return None

    async def find(store_mod, prefix):
        assert prefix == "m_aaaa"
        return [{"memoir_id": MID, "user_id": ME, "title": "t", "illustrations": json.dumps(world.row["illustrations"])}]

    monkeypatch.setattr(store, "open_pool", nothing)
    monkeypatch.setattr(store, "enabled", lambda: True)
    monkeypatch.setattr(tool, "_find", find)
    assert tool.main(["--memoir", "m_aaaa"]) == 0
    plan = json.loads(capsys.readouterr().out)
    # 보기 — 다시 할 수 있는 장을 보이지만, 장을 이름 대기 전에는 대상이 없다
    assert plan["eligible"] == [2, 3] and plan["targets"] == [] and plan["prepared"] is False
    assert plan["calls_expected"] == {"select": 0, "image": 0} and world.row["illustrations"]["status"] == svc.PARTIAL
    assert tool.main(["--memoir", "m_aaaa", "--chapter", "1", "--chapter", "2"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert [t["no"] for t in plan["targets"]] == [2] and [r["no"] for r in plan["refused"]] == [1] and plan["untouched"] == [1, 3]
    assert plan["calls_expected"] == {"select": 1, "image": 1}
    assert tool.main(["--memoir", "m_aaaa", "--prepare"]) == 2                     # 장을 이름 대지 않으면 거부
    capsys.readouterr()
    assert tool.main(["--memoir", "m_aaaa", "--chapter", "2", "--chapter", "3", "--prepare"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["prepared"] is True and world.row["illustrations"]["status"] == svc.RUNNING


def test_a_chapter_failed_under_theme_v1_can_be_redone_once_with_v2_only_when_named(world):
    """운영 책 m_d1571e8e 의 경우 — 2 · 3장은 v1 으로 넣었고 1장은 v1 의 낱말 차단으로 실패했다. 1장만 이름 대서 v2 로 한 번 다시 한다."""
    world.sessions["s-01"]["photo_id"] = None                     # 세 장 모두 사진 없이
    run(Calls())
    doc = world.row["illustrations"]
    for k in ("1", "2", "3"):                                     # 앞선 판(v1)의 기록처럼
        doc["chapters"][k]["select"]["policy_id"] = "chapter_theme_v1"
        doc["chapters"][k]["state"] = svc.ILLUSTRATED if k != "1" else doc["chapters"][k]["state"]
    doc["chapters"]["1"] = {"no": 1, "title": "우물가", "state": svc.FAILED, "failure": ["theme_negated"], "policy": "theme",
                            "select": {"attempted_at": "2026-11-18T00:00:00+00:00", "finished_at": "2026-11-18T00:00:03+00:00",
                                       "policy_id": "chapter_theme_v1", "status": "failed",
                                       "selection": {"status": "failed", "policy": "chapter_theme_v1", "reasons": ["theme_negated"]}}}
    doc["status"] = svc.PARTIAL
    keys = {k: doc["chapters"][k]["image"]["storage_key"] for k in ("2", "3")}
    calls_before = dict(doc["calls"])

    assert [t["no"] for t in svc.reprocess_targets(doc, "theme")] == [1]                 # 다시 할 수 있는 장은 1장뿐
    assert svc.reprocess_targets(doc, "theme", [2, 3]) == []                            # 넣은 장은 이름을 대도 건드리지 않는다
    assert [r["no"] for r in svc.refused_chapters(doc, [2, 3])] == [2, 3]
    done = asyncio.run(svc.prepare_reprocess(MID, ME, "theme", [1]))
    assert done["changed"] and [t["no"] for t in done["targets"]] == [1] and done["targets"][0]["from_policy"] == "chapter_theme_v1"
    ch1 = world.row["illustrations"]["chapters"]["1"]
    assert ch1["history"][0]["policy_id"] == "chapter_theme_v1" and ch1["history"][0]["failure"] == ["theme_negated"]

    calls = Calls()
    after = run(calls)
    assert [no for no, _ in calls.select] == [1] and len(calls.image) == 1               # 1장만 — 선정 1 · 그림 1
    assert {k: c["state"] for k, c in after["chapters"].items()} == {"1": "illustrated", "2": "illustrated", "3": "illustrated"}
    assert {k: after["chapters"][k]["image"]["storage_key"] for k in ("2", "3")} == keys      # 2 · 3장 그림 그대로
    assert after["chapters"]["1"]["select"]["policy_id"] == "chapter_theme_v2"
    assert after["calls"] == {"select": calls_before["select"] + 1, "image": calls_before["image"] + 1}
    v = svc.view(MID, world.row["illustrations"])
    assert [c["policy"] for c in v["chapters"]] == ["chapter_theme_v2", "chapter_theme_v1", "chapter_theme_v1"]   # 앞선 그림은 v1 그대로
    assert svc.reprocess_targets(world.row["illustrations"], "theme", [1]) == []        # 이제 v2 로 불렀다 — 다시 표시되지 않는다


def test_a_select_failure_under_v2_is_not_retried_and_records_the_reason(world, monkeypatch):
    class BadReply(Calls):
        def select_call(self, system, user, *, model):
            super().select_call(system, user, model=model)
            return {"text": "모양이 틀린 응답", "usage": None, "model_version": model}
    calls = BadReply()
    doc = run(calls)
    assert {k: (c["state"], c.get("failure")) for k, c in doc["chapters"].items() if k != "1"} == \
        {"2": ("failed", ["model_output"]), "3": ("failed", ["model_output"])}
    assert calls.image == [] and world.row["result"] == book()[0]["result"]        # 그림을 부르지 않았고 본문은 그대로
    again = Calls()
    run(again)
    assert again.select == [] and again.image == []                               # 저절로 다시 부르지 않는다
