"""
완성된 자서전의 사진 넣기 · 옮기기 · 빼기 (2026-11-25 업무지시서 「자서전 사진 추가·이동·삭제」, 018)

    python -m pytest tests/test_memoir_photos.py -q

DB · 모델 · 그림 API 없이 돈다 — test_memoir_illust_photos.world 의 합성 책 위에 배치 표를 메모리로 얹는다.
C1 ~ C8 은 업무지시서 7절 「완료 기준」 의 번호다.
"""

from __future__ import annotations

import asyncio
import copy
import io

import pytest

from app.session import memoir_illust_service as svc, memoir_photos as mp, photo, store
from tests._auth import AsHeader
from tests._nodb import NoDb
from tests.test_memoir_illust_photos import MID, ME, OTHER, P1, P2, Calls, world

P3 = "33333333-3333-4333-8333-333333333333"
ME_H, OTHER_H = {"X-User-Id": ME}, {"X-User-Id": OTHER}


def _jpeg(color=(120, 140, 160)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, "JPEG")
    return buf.getvalue()


class Book:
    """합성 책 + 메모리 배치 표 + 메모리 사진 행. 모델 · 그림 · 분석 호출은 부르면 실패한다."""

    def __init__(self, monkeypatch, tmp_path):
        # 1장 = 회차 A(사진 P1)의 말씀 2문단, 2장 = 회차 B(사진 없음)의 말씀 3문단 → 1장 사진 · 2장 AI 삽화
        self.photos = {P1: {"photo_id": P1, "user_id": ME, "status": "stored", "width": 800, "height": 600},
                       P2: {"photo_id": P2, "user_id": ME, "status": "stored", "width": 640, "height": 480},
                       P3: {"photo_id": P3, "user_id": OTHER, "status": "stored", "width": 10, "height": 10}}
        self.db = world(monkeypatch, tmp_path, {"A": (2, P1), "B": (3, None)}, [[[1], [2]], [[3], [4], [5]]], self.photos)
        asyncio.run(svc.run(MID, ME, select_call=Calls().select_call, image_call=Calls().image_call))
        self.rows: dict[str, dict] = {}
        self.saved_photos, self.deleted_photo_rows = [], []
        clock = iter(range(1, 10_000))

        async def list_photo_placements(mid, uid):
            return [copy.deepcopy(r) for r in sorted(self.rows.values(), key=lambda r: (r["created_at"], r["placement_id"]))
                    if r["memoir_id"] == mid and r["user_id"] == uid]

        async def save_photo_placement(rec):
            old = self.rows.get(rec["placement_id"])
            if old is not None and (old["memoir_id"], old["user_id"]) != (rec["memoir_id"], rec["user_id"]):
                return None
            row = {**(old or {"created_at": f"t{next(clock):05d}"}), **rec, "photo_id": str(rec["photo_id"])}
            if old is not None:                                       # 고칠 때는 자리 · 순서 · 숨김 · 회차만 (DB 와 같다)
                row = {**old, **{k: rec[k] for k in ("chapter_no", "after_paragraph", "display_order", "hidden")},
                       "sessions": rec.get("sessions") or old.get("sessions"),
                       "anchor_session": old.get("anchor_session") or rec.get("anchor_session")}
            self.rows[rec["placement_id"]] = row
            return copy.deepcopy(row)

        async def delete_photo_placement(pid, mid, uid):
            r = self.rows.get(pid)
            if r and (r["memoir_id"], r["user_id"], r["origin"]) == (mid, uid, "manual"):
                del self.rows[pid]
                return True
            return False

        async def save_photo(rec):
            self.saved_photos.append(rec["photo_id"])
            self.photos[rec["photo_id"]] = {**rec, "status": "stored"}

        async def delete_photo_row(pid):
            self.deleted_photo_rows.append(pid)

        def boom(*a, **k):
            raise AssertionError("모델 · 그림 · 분석 호출이 일어났다")

        for n, f in dict(list_photo_placements=list_photo_placements, save_photo_placement=save_photo_placement,
                         delete_photo_placement=delete_photo_placement, save_photo=save_photo,
                         delete_photo_row=delete_photo_row).items():
            monkeypatch.setattr(store, n, f)
        monkeypatch.setattr(photo, "analyze_later", boom)
        monkeypatch.setattr(svc, "SELECT_CALL", boom)
        monkeypatch.setattr(svc, "IMAGE_CALL", boom)
        monkeypatch.setattr(svc, "schedule", boom)
        monkeypatch.setattr(svc, "resume_if_stalled", lambda *a, **k: None)


@pytest.fixture
def env(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    book = Book(monkeypatch, tmp_path)
    with NoDb(), AsHeader(), TestClient(app) as c:
        yield book, c


def figs(c, no, who=ME_H):
    v = c.get(f"/api/memoirs/saved/{MID}/illustrations", headers=who).json()
    ch = next((x for x in v["chapters"] if x["no"] == no), {"figures": []})
    return ch["figures"]


def photos_of(c, no):
    return [(f["photo_id"], f["after_paragraph"], f["origin"]) for f in figs(c, no) if f["kind"] == "photo"]


def auto_pid(c):
    return next(f["placement_id"] for f in figs(c, 1) if f["kind"] == "photo")


def add(c, no, ap, body=None, **q):
    if body is None:
        return c.post(f"/api/memoirs/saved/{MID}/photos", params={"chapter_no": no, "after_paragraph": ap, **q},
                      content=_jpeg(), headers={**ME_H, "Content-Type": "image/jpeg"})
    return c.post(f"/api/memoirs/saved/{MID}/photos", json={"chapter_no": no, "after_paragraph": ap, **body}, headers=ME_H)


# ---------------------------------------------------------------- C1 같은 문단 뒤 두 장 — 배치 id · 안정된 순서

def test_C1_two_photos_after_the_same_paragraph_have_ids_and_a_stable_order(env):
    book, c = env
    a = add(c, 2, 1)
    b = add(c, 2, 1, body={"photo_id": P2})
    assert a.status_code == b.status_code == 201
    pa, pb = a.json()["placement"], b.json()["placement"]
    assert pa["origin"] == pb["origin"] == "manual" and pa["placement_id"] != pb["placement_id"]
    assert (pa["display_order"], pb["display_order"]) == (0, 1)
    got = [f for f in figs(c, 2) if f["kind"] == "photo"]
    assert [f["placement_id"] for f in got] == [pa["placement_id"], pb["placement_id"]]
    assert all(f["after_paragraph"] == 1 for f in got)
    # 같은 문단의 AI 삽화가 있어도 사진 뒤에 온다 · 몇 번을 읽어도 같은 순서
    assert [f["kind"] for f in figs(c, 2)][-1] == "illustration"
    assert figs(c, 2) == figs(c, 2)
    # 순서를 바꾸면 그대로 따른다
    assert c.patch(f"/api/memoirs/saved/{MID}/photos/{pb['placement_id']}", json={"display_order": -1},
                   headers=ME_H).status_code == 200
    assert [f["placement_id"] for f in figs(c, 2) if f["kind"] == "photo"] == [pb["placement_id"], pa["placement_id"]]
    # 새 사진은 분석하지 않았다 (analyze_later 가 불리면 실패) · 사진 행은 하나만 생겼다
    assert len(book.saved_photos) == 1


# ---------------------------------------------------------------- C2 자동 사진을 옮기면 재처리 · 다시 열기에도 그 자리

def test_C2_moved_auto_photo_stays_after_refresh_and_reopen(env):
    book, c = env
    assert photos_of(c, 1) == [(P1, 0, "auto")]
    pid = auto_pid(c)
    r = c.patch(f"/api/memoirs/saved/{MID}/photos/{pid}", json={"chapter_no": 2, "after_paragraph": 2}, headers=ME_H)
    assert r.status_code == 200 and r.json()["placement"]["origin"] == "auto"
    assert photos_of(c, 1) == [] and photos_of(c, 2) == [(P1, 2, "auto")]
    asyncio.run(svc.refresh_photos(MID, ME, apply=True))                      # 자동 배치를 다시 계산해도
    assert book.db.row["illustrations"]["chapters"]["1"]["state"] == "photo"  # 자동 문서는 예전 자리 그대로지만
    assert photos_of(c, 1) == [] and photos_of(c, 2) == [(P1, 2, "auto")]    # 화면에는 사용자가 고른 자리
    whole = c.get(f"/api/memoirs/saved/{MID}", headers=ME_H).json()["illustrations"]
    assert whole == c.get(f"/api/memoirs/saved/{MID}/illustrations", headers=ME_H).json()


# ---------------------------------------------------------------- C3 자동 사진을 빼도 엽서 · 사진은 그대로, 다시 나타나지 않는다

def test_C3_removed_auto_photo_keeps_the_original_and_never_comes_back(env):
    book, c = env
    pid = auto_pid(c)
    assert c.delete(f"/api/memoirs/saved/{MID}/photos/{pid}", headers=ME_H).status_code == 204
    assert photos_of(c, 1) == []
    assert P1 in book.photos and book.deleted_photo_rows == []                # 사진 행 · 회차의 photo_id 는 그대로
    asyncio.run(svc.refresh_photos(MID, ME, apply=True))
    assert photos_of(c, 1) == []
    assert c.delete(f"/api/memoirs/saved/{MID}/photos/{pid}", headers=ME_H).status_code == 404   # 이미 뺐다
    # 다시 넣으려면 「내 사진」 모양으로
    assert add(c, 1, 1, body={"photo_id": P1}).status_code == 201
    assert photos_of(c, 1) == [(P1, 1, "manual")]


# ---------------------------------------------------------------- C4 넣은 사진을 빼도 다른 참조는 그대로

def test_C4_removing_a_manual_photo_keeps_the_file_and_other_references(env):
    book, c = env
    one = add(c, 2, 0, body={"photo_id": P1}).json()["placement"]             # 1장 자동 사진과 같은 파일
    assert c.delete(f"/api/memoirs/saved/{MID}/photos/{one['placement_id']}", headers=ME_H).status_code == 204
    assert photos_of(c, 2) == [] and photos_of(c, 1) == [(P1, 0, "auto")]
    assert P1 in book.photos and book.deleted_photo_rows == []
    assert c.delete(f"/api/memoirs/saved/{MID}/photos/{one['placement_id']}", headers=ME_H).status_code == 404


# ---------------------------------------------------------------- C5 없는 장 · 틀린 문단 · 남의 것은 분명히 실패

@pytest.mark.parametrize("no, ap, code", [(9, 0, "no_such_chapter"), (1, 2, "no_such_paragraph"), (1, -1, "no_such_paragraph"),
                                          ("x", 0, "bad_position"), (None, 0, "bad_position")])
def test_C5_bad_positions_are_422(env, no, ap, code):
    book, c = env
    r = add(c, no, ap, body={"photo_id": P2})
    assert r.status_code == 422 and r.json()["code"] == code
    assert book.rows == {}


def test_C5_other_users_book_photo_and_placement_are_404(env):
    book, c = env
    assert add(c, 1, 0, body={"photo_id": P3}).json()["code"] == "photo_not_found"          # 남의 사진
    assert add(c, 1, 0, body={"photo_id": "not-a-uuid"}).status_code == 404
    r = c.post(f"/api/memoirs/saved/{MID}/photos", json={"photo_id": P2, "chapter_no": 1, "after_paragraph": 0},
               headers=OTHER_H)
    assert r.status_code == 404 and r.json()["code"] == "memoir_not_found"                  # 남의 책
    pid = add(c, 1, 0, body={"photo_id": P2}).json()["placement"]["placement_id"]
    assert c.patch(f"/api/memoirs/saved/{MID}/photos/{pid}", json={"after_paragraph": 1}, headers=OTHER_H).status_code == 404
    assert c.delete(f"/api/memoirs/saved/{MID}/photos/{pid}", headers=OTHER_H).status_code == 404
    assert c.patch(f"/api/memoirs/saved/{MID}/photos/p_nope", json={"after_paragraph": 1}, headers=ME_H).status_code == 404
    r = c.patch(f"/api/memoirs/saved/{MID}/photos/{pid}", json={"after_paragraph": 5}, headers=ME_H)
    assert r.status_code == 422 and r.json()["code"] == "no_such_paragraph"
    assert photos_of(c, 1)[-1] == (P2, 0, "manual")                                         # 실패한 요청은 아무것도 바꾸지 않았다


def test_C5_bad_image_and_limit(env, monkeypatch):
    book, c = env
    r = c.post(f"/api/memoirs/saved/{MID}/photos", params={"chapter_no": 1, "after_paragraph": 0},
               content=b"not an image", headers={**ME_H, "Content-Type": "image/jpeg"})
    assert r.status_code == 400 and book.saved_photos == []
    monkeypatch.setenv("MEMOIR_PHOTOS_MAX", "2")
    assert add(c, 1, 0).status_code == 201 and add(c, 1, 1).status_code == 201
    r = add(c, 2, 0)
    assert r.status_code == 422 and r.json()["code"] == "too_many_photos" and len(book.saved_photos) == 2


def test_duplicate_request_makes_one_placement_and_one_photo(env):
    book, c = env
    a = add(c, 1, 1, request_id="req-1")
    b = add(c, 1, 1, request_id="req-1")
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()["placement"]["placement_id"] == b.json()["placement"]["placement_id"]
    assert len(book.saved_photos) == 1 and len(book.rows) == 1


def test_placement_save_failure_rolls_back_the_new_photo(env, monkeypatch):
    book, c = env

    async def down(rec):
        raise store.StoreUnavailable("x")
    monkeypatch.setattr(store, "save_photo_placement", down)
    assert add(c, 1, 0).status_code == 503
    assert book.deleted_photo_rows == book.saved_photos and len(book.saved_photos) == 1


# ---------------------------------------------------------------- C6 기존 책 · 기존 figures 소비자

def test_C6_untouched_book_keeps_the_old_figures_and_only_adds_fields(env):
    book, c = env
    old = svc.view(MID, book.db.row["illustrations"])
    new = c.get(f"/api/memoirs/saved/{MID}/illustrations", headers=ME_H).json()
    keys = ("kind", "url", "after_paragraph", "width", "height", "ai_generated", "caption")
    assert [[{k: f[k] for k in keys} for f in ch["figures"]] for ch in new["chapters"]] == \
           [[{k: f[k] for k in keys} for f in ch["figures"]] for ch in old["chapters"]]
    assert {k for k in old} <= set(new)


def test_C6_book_without_illustrations_still_shows_added_photos(env):
    book, c = env
    book.db.row["illustrations"] = None                                     # 삽화가 꺼진 서버 · 처리 전의 책
    assert add(c, 2, 2, body={"photo_id": P2}).status_code == 201
    v = c.get(f"/api/memoirs/saved/{MID}/illustrations", headers=ME_H).json()
    assert [(ch["no"], [f["photo_id"] for f in ch["figures"]]) for ch in v["chapters"]] == [(2, [P2])]


# ---------------------------------------------------------------- C7 호출 0 — Book 이 모델 · 그림 · 분석을 부르면 실패하게 해 두었다

def test_C7_add_move_remove_list_refresh_make_no_model_calls(env):
    book, c = env
    pid = add(c, 1, 1).json()["placement"]["placement_id"]
    c.patch(f"/api/memoirs/saved/{MID}/photos/{pid}", json={"chapter_no": 2, "after_paragraph": 0}, headers=ME_H)
    c.delete(f"/api/memoirs/saved/{MID}/photos/{auto_pid(c)}", headers=ME_H)
    c.get(f"/api/memoirs/saved/{MID}", headers=ME_H)
    asyncio.run(svc.refresh_photos(MID, ME, apply=True))
    assert photos_of(c, 2) == [(book.saved_photos[0], 0, "manual")]


# ---------------------------------------------------------------- 순수 함수

def test_final_photos_order_is_paragraph_then_display_order_then_creation():
    rows = [{"placement_id": "p_b", "origin": "manual", "photo_id": P2, "chapter_no": 1, "after_paragraph": 0,
             "display_order": 0, "hidden": False, "created_at": "t2"},
            {"placement_id": "p_a", "origin": "manual", "photo_id": P1, "chapter_no": 1, "after_paragraph": 0,
             "display_order": 0, "hidden": False, "created_at": "t1"},
            {"placement_id": "p_c", "origin": "manual", "photo_id": P3, "chapter_no": 1, "after_paragraph": None,
             "display_order": 0, "hidden": False, "created_at": "t0"}]
    assert [p["placement_id"] for p in mp.final_photos(None, rows, MID)] == ["p_a", "p_b", "p_c"]
    assert mp.auto_id(MID, P1, "A") == mp.auto_id(MID, P1, "A") != mp.auto_id(MID, P1, "B")
    assert mp.auto_id(MID, P1, "A") != mp.auto_id("m_other", P1, "A")                       # 책마다 다르다
    assert mp.manual_id(MID, ME, "r") == mp.manual_id(MID, ME, "r") != mp.manual_id(MID, OTHER, "r")


# ---------------------------------------------------------------- 11/26 검토 보완 — 책마다 따로 · 회차 묶음이 바뀌어도 유지

MID_B = "m_" + "d" * 32


def _second_book(monkeypatch, book):
    """같은 인터뷰(같은 회차 · 같은 사진)로 만든 두 번째 책."""
    first = store.load_memoir

    async def load_memoir(mid, uid):
        if mid == MID_B and uid == ME:
            return {**copy.deepcopy(book.db.row), "memoir_id": MID_B}
        return await first(mid, uid)
    monkeypatch.setattr(store, "load_memoir", load_memoir)


def _figs(c, mid, no):
    v = c.get(f"/api/memoirs/saved/{mid}/illustrations", headers=ME_H).json()
    ch = next((x for x in v["chapters"] if x["no"] == no), {"figures": []})
    return [(f["photo_id"], f["after_paragraph"], f["placement_id"]) for f in ch["figures"] if f["kind"] == "photo"]


def test_two_books_from_the_same_interview_are_edited_independently(env, monkeypatch):
    book, c = env
    _second_book(monkeypatch, book)
    a_id, b_id = _figs(c, MID, 1)[0][2], _figs(c, MID_B, 1)[0][2]
    assert a_id != b_id                                                                     # 같은 사진 · 회차라도 책마다 다른 id
    assert c.patch(f"/api/memoirs/saved/{MID}/photos/{a_id}", json={"after_paragraph": 1}, headers=ME_H).status_code == 200
    r = c.delete(f"/api/memoirs/saved/{MID_B}/photos/{b_id}", headers=ME_H)
    assert r.status_code == 204                                                             # 앞선 판에서는 404 였다
    assert [x[:2] for x in _figs(c, MID, 1)] == [(P1, 1)] and _figs(c, MID_B, 1) == []
    assert c.patch(f"/api/memoirs/saved/{MID_B}/photos/{a_id}", json={"after_paragraph": 1}, headers=ME_H).status_code == 404


def _regroup(book, sessions, chapter="1"):
    book.db.row["illustrations"]["chapters"][chapter]["photos"][0]["sessions"] = sessions


def test_removed_auto_photo_stays_removed_when_its_session_group_changes(env):
    book, c = env
    _regroup(book, ["A", "B"])
    pid = auto_pid(c)
    assert c.delete(f"/api/memoirs/saved/{MID}/photos/{pid}", headers=ME_H).status_code == 204
    for group in (["B"], ["A"], ["B", "C"]):                                                 # 처음 회차가 빠져도 · 남아도 · 새 회차가 더해져도
        _regroup(book, group)
        assert photos_of(c, 1) == [], group
    _regroup(book, ["Z"])                                                                   # 회차가 하나도 이어지지 않으면 다른 사진 자리다
    assert photos_of(c, 1) == [(P1, 0, "auto")]


def test_moved_auto_photo_keeps_its_place_and_id_when_its_session_group_changes(env):
    book, c = env
    _regroup(book, ["A", "B"])
    pid = auto_pid(c)
    assert c.patch(f"/api/memoirs/saved/{MID}/photos/{pid}", json={"chapter_no": 2, "after_paragraph": 2},
                   headers=ME_H).status_code == 200
    _regroup(book, ["B"])
    got = [f for f in figs(c, 2) if f["kind"] == "photo"]
    assert [(f["photo_id"], f["after_paragraph"], f["placement_id"]) for f in got] == [(P1, 2, pid)]
    assert photos_of(c, 1) == []
    assert c.patch(f"/api/memoirs/saved/{MID}/photos/{pid}", json={"after_paragraph": 0}, headers=ME_H).status_code == 200


def test_hiding_one_auto_photo_does_not_hide_the_same_file_placed_elsewhere(env):
    book, c = env
    doc = book.db.row["illustrations"]
    doc["chapters"]["2"] = {**copy.deepcopy(doc["chapters"]["1"]), "no": 2}                 # 같은 사진을 다른 회차가 2장에
    doc["chapters"]["2"]["photos"][0].update(sessions=["B"], session_id="B")
    _regroup(book, ["A"])
    one = next(f["placement_id"] for f in figs(c, 1) if f["kind"] == "photo")
    assert c.delete(f"/api/memoirs/saved/{MID}/photos/{one}", headers=ME_H).status_code == 204
    assert photos_of(c, 1) == [] and photos_of(c, 2) == [(P1, 0, "auto")]


def test_records_saved_with_the_first_version_id_are_still_found(env):
    book, c = env
    old_id = mp.legacy_auto_id(P1, "A")                                                     # 11/25 판 — 책 없이 · 회차 없이 저장된 기록
    book.rows[old_id] = {"placement_id": old_id, "memoir_id": MID, "user_id": ME, "photo_id": P1, "origin": "auto",
                         "chapter_no": 1, "after_paragraph": 0, "display_order": 0, "hidden": True, "width": 800,
                         "height": 600, "sessions": None, "anchor_session": None, "created_at": "t00000"}
    assert photos_of(c, 1) == []                                                            # 뺀 상태가 그대로
    book.rows[old_id]["hidden"] = False
    book.rows[old_id]["after_paragraph"] = 1
    assert [x[1:] for x in _figs(c, MID, 1)] == [(1, old_id)]
