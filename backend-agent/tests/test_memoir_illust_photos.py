"""
자서전 사진 배치 — 회차 사진이 빠지고 AI 삽화로 바뀌던 문제의 회귀 시험 (2026-11-24)

    python -m pytest tests/test_memoir_illust_photos.py -q

원인: memoir_illust_service.place_session_photos 가 「회차 말씀이 정확히 한 장에만 쓰였을 때만」 사진을 놓았다(len(nos) == 1).
여러 장에 걸친 회차의 사진은 session_in_many_chapters 로 빠졌고, 모든 장이 「사진 없음 확인」 이라 그 장들에 AI 삽화가 들어갔다.

DB · 모델 · 그림 API 없이 돈다 — store 를 메모리로, 그림 저장소를 임시 폴더로, 선정 · 그림 호출을 가짜로 바꿔 끼운다. 자료는 합성이다.
표의 T1 ~ T12 는 작업 지시의 회귀 시험 번호다.
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

from app.session import memoir_illust_book as book, memoir_illust_service as svc, photostore, store   # noqa: E402

ME, OTHER = "u_me", "u_other"
MID = "m_" + "b" * 32
P1, P2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


def _jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 32), (180, 170, 150)).save(buf, "JPEG")
    return buf.getvalue()


def world(monkeypatch, tmp_path, sessions: dict, chapters: list, photos: dict | None = None):
    """
    합성 책. sessions = {회차: (말씀 수, 사진 id | None)} — 회차 순서대로 전역 턴이 1부터 이어진다.
    chapters = [[문단의 출처 턴 목록, …], …] — 장 번호는 1부터, 문단마다 문장 하나.
    """
    recs, g = {}, 0
    for i, (sid, (n, pid)) in enumerate(sessions.items(), start=1):
        recs[sid] = {"session_id": sid, "user_id": ME, "created_at": f"2026-02-{i:02d}T09:00:00+00:00", "closing_decision": None,
                     "photo_id": pid,
                     "fragments": [{"idx": 0, "question": None, "answer": "씨앗", "decision": None}]
                     + [{"idx": k, "question": f"질문 {k}", "answer": f"{sid} 회차의 말씀 {k}", "decision": None} for k in range(1, n + 1)]}
        g += n
    result = {"status": "ready", "style": "essay", "title": "합성 책", "run": {"session_ids": list(sessions)},
              "chapters": [{"no": no, "title": f"{no}장", "status": "ready",
                            "paragraphs": [{"sentences": [{"text": f"{no}장 {pi}문단", "turns": list(turns)}]}
                                           for pi, turns in enumerate(paras)]}
                           for no, paras in enumerate(chapters, start=1)]}
    row = {"memoir_id": MID, "user_id": ME, "elder_id": None, "style": "essay", "engine": "pipeline", "status": "ready",
           "title": "합성 책", "created_at": "2026-02-10T00:00:00+00:00", "session_ids": list(sessions), "result": result,
           "illustrations": None}
    photos = photos if photos is not None else {pid: {"photo_id": pid, "user_id": ME, "status": "stored", "width": 800, "height": 600}
                                                for _, pid in sessions.values() if pid}
    db = type("Db", (), {"row": row, "saves": 0})()

    async def load_memoir(mid, uid):
        return copy.deepcopy(db.row) if mid == MID and uid == ME else None

    async def save_memoir_illustrations(mid, uid, doc):
        db.row["illustrations"] = json.loads(json.dumps(doc, default=str))
        db.saves += 1

    async def load_session(sid):
        return copy.deepcopy(recs.get(sid))

    async def load_photo(pid):
        return copy.deepcopy(photos.get(pid))

    for n, f in dict(load_memoir=load_memoir, save_memoir_illustrations=save_memoir_illustrations, load_session=load_session,
                     load_photo=load_photo).items():
        monkeypatch.setattr(store, n, f)
    monkeypatch.setattr(photostore, "_store", photostore.LocalStore(tmp_path / "blobs"))
    return db


class Calls:
    """가짜 선정 · 그림 — 부른 장을 센다. 계획은 뜻 없는 합성 계획이다 (v2 는 모양만 본다)."""

    def __init__(self):
        self.select, self.image = [], []

    def select_call(self, system, user, *, model):
        no = json.loads(user.split("\n", 1)[1])["chapter"]["chapter_no"]
        self.select.append(no)
        return {"text": json.dumps({"chapter_no": no, "theme": f"{no}장의 주제", "theme_short": f"{no}장",
                                    "subjects": [{"text": "합성 소재", "kind": "object", "role": "main", "anchor": None}]},
                                   ensure_ascii=False), "usage": None, "model_version": model}

    def image_call(self, prompt, *, model):
        self.image.append(prompt)
        return {"status": "completed", "output_image": {"type": "image", "mime_type": "image/jpeg",
                                                        "data": base64.b64encode(_jpeg()).decode()}}


def run(calls):
    return asyncio.run(svc.run(MID, ME, select_call=calls.select_call, image_call=calls.image_call))


def placement(chapters, sessions):
    """place_session_photos 만 — sessions = {회차: (턴 수, 사진 id)}."""
    tm, g = [], 0
    for sid, (n, _) in sessions.items():
        for k in range(1, n + 1):
            g += 1
            tm.append({"global_turn": g, "session_id": sid, "turn": k})
    chs = [{"no": no, "paragraphs": [{"sentences": [{"text": "x", "turns": list(turns)}]} for turns in paras]}
           for no, paras in enumerate(chapters, start=1)]
    photos = {sid: {"photo_id": pid, "width": 1, "height": 1} for sid, (_, pid) in sessions.items() if pid}
    return svc.place_session_photos(chs, tm, photos)


# ---------------------------------------------------------------- 배치 규칙 (T1 ~ T6 · T9)

def test_T1_session_used_in_one_chapter_is_placed_as_before():
    placed, unplaced = placement([[[1]], [[3]]], {"A": (2, P1), "B": (1, None)})
    assert unplaced == [] and list(placed) == [1]
    assert placed[1][0]["after_paragraph"] == 0 and placed[1][0]["placement"]["rule"] == "single_chapter"


def test_T2_session_split_over_two_chapters_goes_to_one_representative_chapter():
    # 회차 A(턴 1 ~ 3): 1장은 턴 1, 2장은 턴 2 · 3 — 2장이 서로 다른 턴을 더 많이 쓴다
    placed, unplaced = placement([[[1]], [[4], [2, 3]]], {"A": (3, P1), "B": (1, None)})
    assert unplaced == [] and list(placed) == [2]
    assert placed[2][0]["after_paragraph"] == 1                  # 그 장에서 A 의 말씀이 처음 나오는 문단 뒤
    assert placed[2][0]["placement"] == {"rule": "most_distinct_turns", "chapters": {"1": 1, "2": 2}}


def test_T3_three_or_more_chapters_pick_deterministically():
    # A(턴 1 ~ 4)가 1 · 2 · 3장에 한 턴씩, 3장은 두 턴 → 3장
    placed, _ = placement([[[1]], [[2]], [[3, 4]]], {"A": (4, P1)})
    assert list(placed) == [3]
    # 사용량이 같으면 그 회차의 가장 앞선 턴을 쓴 장 → 턴 1 을 쓴 2장
    placed, _ = placement([[[3]], [[1]], [[2]]], {"A": (3, P1)})
    assert list(placed) == [2]
    # 가장 앞선 턴까지 같으면(같은 턴을 두 장이 씀) 장 번호가 작은 쪽
    placed, _ = placement([[[9]], [[1]], [[1]]], {"A": (1, P1), "B": (8, None)})
    assert list(placed) == [2]
    # 몇 번을 돌려도 같다
    assert all(list(placement([[[1]], [[2]], [[3, 4]]], {"A": (4, P1)})[0]) == [3] for _ in range(5))


def test_T4_the_same_turn_quoted_many_times_counts_once():
    # 1장은 턴 1 을 문장 다섯 개가 인용, 2장은 서로 다른 턴 2 · 3 → 2장 (인용 횟수로 부풀지 않는다)
    placed, _ = placement([[[1], [1], [1], [1], [1, 1]], [[2], [3]]], {"A": (3, P1)})
    assert list(placed) == [2] and placed[2][0]["placement"]["chapters"] == {"1": 1, "2": 2}


def test_T5_same_photo_registered_in_two_sessions_keeps_both_links():
    # 같은 사진을 회차 A · B 에 붙였고 이야기는 서로 다른 장에 쓰였다 → 두 장 모두에 놓는다
    placed, unplaced = placement([[[1]], [[2]]], {"A": (1, P1), "B": (1, P1)})
    assert unplaced == [] and sorted(placed) == [1, 2]
    assert placed[1][0]["sessions"] == ["A"] and placed[2][0]["sessions"] == ["B"]
    # 두 회차가 같은 장에 쓰였으면 그 장에는 한 번만 보이고, 두 회차의 연결은 함께 남는다
    placed, unplaced = placement([[[1], [2]]], {"A": (1, P1), "B": (1, P1)})
    assert unplaced == [] and len(placed[1]) == 1 and placed[1][0]["sessions"] == ["A", "B"]


def test_T6_several_photos_in_one_chapter_are_all_kept_in_paragraph_order():
    placed, unplaced = placement([[[2], [1]]], {"A": (1, P1), "B": (1, P2)})
    assert unplaced == [] and [x["photo_id"] for x in placed[1]] == [P2, P1]          # B 는 0문단, A 는 1문단
    assert [x["after_paragraph"] for x in placed[1]] == [0, 1]


def test_T9_photo_without_any_source_is_not_forced_into_a_chapter():
    placed, unplaced = placement([[[2]], [[2]]], {"A": (1, P1), "B": (1, None)})
    assert placed == {} and unplaced[0]["reason"] == "session_not_cited" and unplaced[0]["chapters"] == []
    assert unplaced[0]["diagnosis"] == "session_turns_not_cited"


# ---------------------------------------------------------------- 서비스 — 사진 장 · AI 삽화 조건 (T7 · T8 · T9 · T11 · T12)

def test_T7_T8_photo_chapter_makes_no_image_call_and_other_chapters_keep_the_ai_policy(monkeypatch, tmp_path):
    # A(턴 1 ~ 3, 사진)가 1 · 2장에 걸침(2장이 대표) · B(턴 4, 사진 없음)는 3장
    db = world(monkeypatch, tmp_path, {"A": (3, P1), "B": (1, None)}, [[[1]], [[2], [3]], [[4]]])
    calls = Calls()
    doc = run(calls)
    states = {k: c["state"] for k, c in doc["chapters"].items()}
    assert states == {"1": "illustrated", "2": "photo", "3": "illustrated"}
    assert calls.select == [1, 3] and len(calls.image) == 2                 # 사진 장(2장)은 선정도 그림도 부르지 않는다
    v = svc.view(MID, db.row["illustrations"])
    figs = {c["no"]: [(f["kind"], f["after_paragraph"]) for f in c["figures"]] for c in v["chapters"]}
    assert figs == {1: [("illustration", 0)], 2: [("photo", 0)], 3: [("illustration", 0)]}
    assert v["unplaced_photos"] == []


def test_T9_uncited_photo_makes_only_sourceless_chapters_unknown(monkeypatch, tmp_path):
    # A(사진)의 말씀은 어느 장에도 쓰이지 않았다. 1장은 B 의 턴을 쓰고, 2장은 출처가 없다(집필 · 편집에서 빠졌을 수 있다)
    db = world(monkeypatch, tmp_path, {"A": (1, P1), "B": (1, None)}, [[[2]], [[]]])
    calls = Calls()
    doc = run(calls)
    assert doc["chapters"]["1"]["state"] == "illustrated"                   # 출처가 있는 장은 그대로 — 사진 한 장 때문에 끄지 않는다
    assert doc["chapters"]["2"]["state"] == "photo_unknown" and calls.select == [1]
    v = svc.view(MID, db.row["illustrations"])
    u = v["unplaced_photos"][0]
    assert u["reason"] == "session_not_cited" and u["diagnosis"] == "session_turns_not_cited" and u["url"] == f"/api/photos/{P1}"
    assert "근거가 없어" in u["detail"]


def test_T9_book_without_any_sources_does_not_turn_a_photo_into_ai_pictures(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (1, P1)}, [[[]], [[]]])
    calls = Calls()
    doc = run(calls)
    assert {k: c["state"] for k, c in doc["chapters"].items()} == {"1": "photo_unknown", "2": "photo_unknown"}
    assert calls.select == [] and calls.image == []
    assert db.row["illustrations"]["unplaced_photos"][0]["diagnosis"] == "memoir_has_no_sources"


@pytest.mark.parametrize("photo_row, reason", [(None, "photo_missing"),
                                               ({"photo_id": P1, "user_id": OTHER, "status": "stored"}, "photo_not_owned"),
                                               ({"photo_id": P1, "user_id": ME, "status": "pending"}, "photo_not_stored")])
def test_T11_registered_but_unusable_photo_is_reported_and_its_chapter_gets_no_ai_picture(monkeypatch, tmp_path, photo_row, reason):
    photos = {P1: photo_row} if photo_row else {}
    db = world(monkeypatch, tmp_path, {"A": (2, P1), "B": (1, None)}, [[[1], [2]], [[3]]], photos=photos)
    calls = Calls()
    doc = run(calls)
    assert doc["chapters"]["1"]["state"] == "photo_unknown" and doc["chapters"]["2"]["state"] == "illustrated"
    assert calls.select == [2]
    u = svc.view(MID, db.row["illustrations"])["unplaced_photos"][0]
    assert u["reason"] == reason and u["url"] is None and u["chapters"] == [1]


def test_T11_session_started_without_a_photo_has_nothing_to_place(monkeypatch, tmp_path):
    """화면은 8초 안에 사진을 못 올리면 「사진은 아직 올라가지 않아 빼고 시작해요」 라고 알리고 photo_id 없이 회차를 연다 — 안내와 같게 사진 없음."""
    db = world(monkeypatch, tmp_path, {"A": (1, None)}, [[[1]]])
    calls = Calls()
    run(calls)
    assert db.row["illustrations"]["unplaced_photos"] == [] and calls.select == [1]


def test_T12_server_figures_carry_every_placed_photo_with_a_valid_paragraph(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (2, P1), "B": (2, P1), "C": (1, P2)}, [[[1], [5]], [[2], [3, 4]]])
    run(Calls())
    v = svc.view(MID, db.row["illustrations"])
    paras = {c["no"]: len(c["paragraphs"]) for c in db.row["result"]["chapters"]}
    shown = [(c["no"], f["url"]) for c in v["chapters"] for f in c["figures"] if f["kind"] == "photo"]
    # A · C 는 1장, B 는 2장 — 같은 사진(P1)이 A · B 로 두 장에, C 의 사진(P2)은 1장에
    assert sorted(shown) == sorted([(1, f"/api/photos/{P1}"), (1, f"/api/photos/{P2}"), (2, f"/api/photos/{P1}")])
    assert all(0 <= f["after_paragraph"] < paras[c["no"]] for c in v["chapters"] for f in c["figures"])
    assert all(c["state"] == "photo" for c in v["chapters"])                # 사진이 놓인 장 — AI 삽화 없음


def test_T12_route_returns_the_same_figures_and_unplaced_photos(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (1, P1), "B": (1, None)}, [[[2]], [[]]])
    run(Calls())
    from fastapi.testclient import TestClient
    from app.main import app
    from tests._auth import AsHeader
    from tests._nodb import NoDb
    with NoDb(), AsHeader(), TestClient(app) as c:
        light = c.get(f"/api/memoirs/saved/{MID}/illustrations", headers={"X-User-Id": ME}).json()
        full = c.get(f"/api/memoirs/saved/{MID}", headers={"X-User-Id": ME}).json()["illustrations"]
    assert light == full == svc.view(MID, db.row["illustrations"])
    assert light["unplaced_photos"][0]["reason"] == "session_not_cited"


# ---------------------------------------------------------------- 이미 만든 자서전 (T10)

def _old_book(monkeypatch, tmp_path):
    """앞선 규칙으로 처리된 책처럼 — A(사진)가 1 · 2장에 걸쳐 사진이 빠지고 두 장 모두 AI 삽화가 들어갔다."""
    db = world(monkeypatch, tmp_path, {"A": (3, P1), "B": (1, None)}, [[[1]], [[2], [3]], [[4]]])
    real_place = svc.place_session_photos

    def old_rule(chapters, turn_map, photos, unavailable=None, utterances=None):
        placed, unplaced = real_place(chapters, turn_map, {}, unavailable, utterances)
        return placed, unplaced + [{"photo_id": p["photo_id"], "session_id": s, "reason": "session_in_many_chapters", "chapters": [1, 2]}
                                   for s, p in photos.items()]
    monkeypatch.setattr(svc, "place_session_photos", old_rule)
    run(Calls())
    monkeypatch.setattr(svc, "place_session_photos", real_place)
    return db


def test_T10_existing_book_is_not_changed_until_asked_and_refresh_makes_no_calls(monkeypatch, tmp_path):
    db = _old_book(monkeypatch, tmp_path)
    before = copy.deepcopy(db.row["illustrations"])
    assert {k: c["state"] for k, c in before["chapters"].items()} == {"1": "illustrated", "2": "illustrated", "3": "illustrated"}
    saves = db.saves
    # 보기 — 바뀔 것만 보이고 저장하지 않는다
    plan = asyncio.run(svc.refresh_photos(MID, ME, apply=False))
    assert plan["calls"] == 0 and [c["no"] for c in plan["changes"]] == [2] and plan["changes"][0]["image_kept"] is True
    assert db.row["illustrations"] == before and db.saves == saves
    # 적용 — 2장은 사진이 먼저, 앞서 만든 AI 삽화 기록은 지우지 않는다. 1 · 3장은 그대로
    asyncio.run(svc.refresh_photos(MID, ME, apply=True))
    after = db.row["illustrations"]
    assert {k: c["state"] for k, c in after["chapters"].items()} == {"1": "illustrated", "2": "photo", "3": "illustrated"}
    assert after["chapters"]["2"]["image"] == before["chapters"]["2"]["image"]          # 그림 기록 · 저장 키 그대로
    assert after["chapters"]["2"]["photo_over_illustration"]["image_kept"] is True
    assert after["status"] == before["status"] and after["calls"] == before["calls"]    # running 으로 두지 않고 호출 수도 그대로
    v = svc.view(MID, after)
    assert [f["kind"] for f in next(c for c in v["chapters"] if c["no"] == 2)["figures"]] == ["photo"]
    # 그 뒤 책을 다시 처리해도(다른 장을 재처리 · 재접속) 부르지 않는다
    calls = Calls()
    run(calls)
    assert calls.select == [] and calls.image == []


def test_T10_recompute_never_hides_an_existing_ai_picture_when_photo_info_becomes_unknown(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (1, P1), "B": (1, None)}, [[[2]], [[]]])
    run(Calls())
    doc = db.row["illustrations"]
    # 앞선 규칙으로는 2장(출처 없음)에 AI 삽화가 들어갔던 것처럼
    doc["chapters"]["2"] = copy.deepcopy(doc["chapters"]["1"]) | {"no": 2, "title": "2장"}
    asyncio.run(svc.refresh_photos(MID, ME, apply=True))
    assert db.row["illustrations"]["chapters"]["2"]["state"] == "illustrated"          # 「모름」 이 돼도 있던 그림은 숨기지 않는다


def test_T10_reprocess_tool_refresh_is_explicit_and_calls_nothing(monkeypatch, tmp_path, capsys):
    from tools import memoir_illust_reprocess as tool
    db = _old_book(monkeypatch, tmp_path)

    async def nothing():
        return None

    async def find(store_mod, prefix):
        return [{"memoir_id": MID, "user_id": ME, "title": "t", "illustrations": json.dumps(db.row["illustrations"])}]

    monkeypatch.setattr(store, "open_pool", nothing)
    monkeypatch.setattr(store, "enabled", lambda: True)
    monkeypatch.setattr(tool, "_find", find)
    before = copy.deepcopy(db.row["illustrations"])
    assert tool.main(["--memoir", "m_bbbb", "--refresh-photos"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["refresh_photos"]["applied"] is False and [c["no"] for c in out["refresh_photos"]["changes"]] == [2]
    assert db.row["illustrations"] == before
    assert tool.main(["--memoir", "m_bbbb", "--refresh-photos", "--apply"]) == 0
    assert db.row["illustrations"]["chapters"]["2"]["state"] == "photo"
