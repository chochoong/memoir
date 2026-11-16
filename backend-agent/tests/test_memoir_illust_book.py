"""
자서전 한 권 — 목차별 자동 삽화 (memoir_illust_book · tools/memoir_illust_book.py · 로컬 실험)

    python -m pytest tests/test_memoir_illust_book.py -q

모델도 이미지 API 도 부르지 않는다 — 장면 선정과 그림 자리에 모의 응답을 끼운다. 자료는 합성(eval/illust_book_seed_B.json)이다.

제품 동작이 바뀌었다 (2026-11-15): 책 전체에서 장면 몇 개를 추천해 사람이 고르던 것 → 사진이 없는 목차마다 한 장씩 자동으로.
앞선 흐름의 시험(tests/test_memoir_illust.py)은 그대로 둔다 — 그 모듈의 한도(MAX_SCENES) · 사람 확인은 검토용 실행기에서 여전히 쓴다.
이 흐름은 그 한도와 사람 확인을 쓰지 않으며, 그것을 여기서 시험한다.
"""

from __future__ import annotations

import base64
import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_illust as il            # noqa: E402
from app.session import memoir_illust_book as book     # noqa: E402
from tools import memoir_illust as seltool             # noqa: E402
from tools import memoir_illust_book as tool           # noqa: E402
from tools import memoir_illust_image as img           # noqa: E402

SEED = json.loads((ROOT / "eval" / "illust_book_seed_B.json").read_text(encoding="utf-8"))
MOCK = json.loads((ROOT / "eval" / "illust_book_mock_B.json").read_text(encoding="utf-8"))["by_chapter"]
PIXELS = b"\xff\xd8\xff\xe0" + b"mock" * 30 + b"\xff\xd9"
NO_PHOTO = ["c02", "c03", "c05", "c07", "c08", "c10"]
PHOTO_BASE = ROOT / "eval"           # 합성 자료의 시험용 사진(illust_book_photos_B/ — 「TEST PHOTO」 라고 적힌 그림)이 있는 곳


def seed() -> dict:
    return copy.deepcopy(SEED)


def chapter(d: dict, key: str) -> dict:
    return next(c for c in d["memoir"]["chapters"] if c["chapter_key"] == key)


def sym(no: int, name: str, quote: str, kind: str = "object", focus: bool = False) -> dict:
    """
    사물 · 풍경 하나짜리 모의 후보. focus=True 면 지시문 v5 의 중심 내용(focus.core)에 그 요소를 원문 인용과 함께 적는다 —
    제목이 장소를 말하지 않는 항목(4 졸업 사진 · 9 결혼식)에서 장소가 중심이라는 근거다. 2026-11-15 부터 배경 하나뿐인 후보는
    「대표 그림 없음」 으로 실패하므로, 이 시험들의 모의 응답에 그 근거를 넣었다.
    """
    e = {"key": "x1", "kind": kind, "text": name, "turn": no, "quote": quote}
    if kind == "place":
        e["role"] = "setting"
    out = {"candidates": [{"chapter_no": no, "scene_title": name, "scene_summary": f"{name}.", "importance": "main",
                           "reason": "대표한다.", "elements": [e]}]}
    if focus:
        out["focus"] = {"summary": name, "core": [{"kind": kind, "text": name, "turn": no, "quote": quote}], "background": []}
    return out


ALL = {**MOCK,
       "c01": sym(1, "우물", "마을 한가운데에 우물이 있었어요"),
       # 4 · 9번은 사진이 있는 항목이라 대부분의 시험에서 쓰이지 않는다. 사진을 모두 뺀 시험에서는 with_drawn_objects 로
       # 원문 · 본문에 사물 문장을 더한다 — 2026-11-16 부터 모델 focus 만으로는 장소가 중심이 되지 않기 때문이다.
       # 더한 사물은 세 문장 가운데 한 번 나온다 — 2026-11-16 보완 3 부터 본문에 한 번 나온 것만으로는 중심이 아니어서,
       # 지시문 v5 응답처럼 focus.core 에 그 사물을 적는다(목차에 더 강한 중심이 없을 때 「본문 + 모델 제안」 이 중심 근거가 된다)
       "c04": sym(4, "졸업장", "졸업장을 둥글게 말아 들고 있었어요", focus=True),
       "c06": sym(6, "버스", "읍내 가는 버스는 하루에 두 번 왔어요"),
       "c09": sym(9, "족두리", "머리에 족두리를 썼어요", focus=True)}


def with_drawn_objects(d: dict) -> dict:
    """[시험용] 4 · 9번 항목의 원문과 본문에 그릴 사물 문장을 하나씩 더한다."""
    for key, turn, said, written in (("c04", 4, " 졸업장을 둥글게 말아 들고 있었어요.", " 졸업장을 둥글게 말아 들고 있었다."),
                                     ("c09", 9, " 머리에 족두리를 썼어요.", " 머리에 족두리를 썼다.")):
        d["source"]["utterances"][turn - 1]["elder"] += said
        chapter(d, key)["paragraphs"][-1]["sentences"][-1]["text"] += written
    return d


# 그림 지시문에서 어느 항목의 것인지 알아보는 낱말 (시험용)
WORD = {"c01": "우물", "c02": "장독", "c03": "모를 논에", "c04": "운동장", "c05": "연탄", "c06": "버스", "c07": "재봉틀",
        "c08": "라디오", "c09": "예식장", "c10": "호미"}


class Run:
    """한 권을 모의로 돌린다 — 장면 선정과 그림 호출을 센다."""

    def __init__(self, out: Path, by: dict | None = None, fail_images: tuple = (), select_error: tuple = ()):
        self.out, self.by = out, ALL if by is None else by
        self.select_calls, self.image_calls = [], []
        self.fail_images, self.select_error = fail_images, select_error

    def select_for(self, t):
        def call(system, user):
            self.select_calls.append(t["ident"])
            if t["ident"] in self.select_error:
                raise RuntimeError("select down")
            assert "목차" in system or "항목" in system                 # v4 지시문을 쓴다
            return json.dumps(self.by.get(str(t["ident"]), {"candidates": []}), ensure_ascii=False)
        return call

    def image_call(self, prompt, *, model, size, aspect, key):
        ident = next((k for k, word in WORD.items() if word in prompt), "?")
        self.image_calls.append(ident)
        if ident in self.fail_images:
            raise RuntimeError("image down")
        return {"id": "mock", "status": "completed",
                "output_image": {"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(PIXELS).decode()}}

    def go(self, data: dict, images: bool = True, select: bool = True, reprocess: bool = False):
        items, calls = tool.process(data, self.out, select_for=self.select_for if select else None,
                                    image_call=self.image_call if images else None, mock=True, image_model="mock",
                                    base_dir=PHOTO_BASE, reprocess_stale=reprocess)
        summary = tool.write_outputs(data, self.out, items, True, PHOTO_BASE)
        doc = json.loads((self.out / "book_illustrated.json").read_text(encoding="utf-8"))
        return {it["ident"]: it for it in items}, calls, summary, doc


def pictures(doc: dict) -> list[int]:
    return [sum(1 for b in c["blocks"] if b["type"] == "illustration") for c in doc["chapters"]]


def photos(doc: dict) -> list[int]:
    return [sum(1 for b in c["blocks"] if b["type"] == "photo") for c in doc["chapters"]]


# ---------------------------------------------------------------- 목차와 사진

def test_toc_is_the_chapter_list_with_existing_identifiers():
    t = book.toc(seed())
    assert [x["ident"] for x in t] == [f"c{n:02d}" for n in range(1, 11)] and t[0]["title"] == "우물가"
    d = seed()
    for c in d["memoir"]["chapters"]:
        c.pop("chapter_key")
    assert [x["ident"] for x in book.toc(d)] == list(range(1, 11)) and book.toc(d)[0]["key"] is None    # 식별자를 지어 붙이지 않는다


def test_photo_state_counts_only_photos_placed_in_that_item():
    st = book.photo_states(seed())
    assert [st[f"c{n:02d}"]["state"] for n in range(1, 11)] == [
        "has_photo", "no_photo_confirmed", "no_photo_confirmed", "has_photo", "no_photo_confirmed",
        "has_photo", "no_photo_confirmed", "no_photo_confirmed", "has_photo", "no_photo_confirmed"]
    assert len(st["c04"]["photos"]) == 3
    # 같은 회차(s-08)에서 올린 사진 ph-08x 는 8번 항목에 놓인 사진이 아니다
    assert st["c08"]["state"] == "no_photo_confirmed" and st["c08"]["same_session_photos_not_counted"] == ["ph-08x"]
    assert st["c02"]["photos"] == []                                    # 1번 항목의 사진이 2번 항목으로 넘어오지 않는다


def test_photo_linked_from_the_book_level_list():
    d = seed()
    chapter(d, "c02").pop("photos")
    d["photos"].append({"photo_id": "ph-02", "session_id": None, "turns": [], "clues": None, "chapter_keys": ["c02"]})
    st = book.photo_states(d)
    assert st["c02"]["state"] == "has_photo" and st["c02"]["photos"][0]["link"] == "photos[].chapter"
    d["photos"][-1]["chapter_keys"] = ["c05"]                           # 다른 항목을 가리키면 2번 항목의 사진이 아니다
    assert book.photo_states(d)["c02"]["state"] == "unknown"


def test_unknown_is_not_turned_into_no_photo():
    d = seed()
    chapter(d, "c02").pop("photos")                                     # 2번 항목에 사진이 놓였는지 입력에 없다
    assert book.photo_states(d)["c02"]["state"] == "unknown"
    d["photo_placement"] = {"complete": True}                           # 서비스가 「놓인 사진은 다 적었다」 고 하면 없음이다
    assert book.photo_states(d)["c02"]["state"] == "no_photo_confirmed"
    d = seed()
    d["photos"] = None
    for c in d["memoir"]["chapters"]:
        c.pop("photos", None)
    assert {v["state"] for v in book.photo_states(d).values()} == {"unknown"}
    chapter(d, "c02")["photos"] = "없음"
    with pytest.raises(il.IllustError):
        book.photo_states(d)


# ---------------------------------------------------------------- 한 권 흐름

def test_every_item_has_a_photo_means_nothing_is_generated(tmp_path):
    d = seed()
    for c in d["memoir"]["chapters"]:
        c["photos"] = c.get("photos") or [{"photo_id": f"ph-{c['chapter_key']}"}]
    r = Run(tmp_path)
    items, calls, summary, doc = r.go(d)
    assert calls == {"select": 0, "image": 0} and r.select_calls == [] and r.image_calls == []
    assert summary["status"] == "complete" and summary["counts"]["targets"] == 0 and pictures(doc) == [0] * 10
    assert all(it["status"] == "kept_photo" and it["target"] is False for it in items.values())


def test_no_item_has_a_photo_means_one_picture_each_without_the_old_limit(tmp_path):
    """사진 없는 항목이 열 개여도 열 장이다 — 앞선 흐름의 「책 전체 최대 3개」 가 여기에는 없다."""
    d = seed()
    for c in d["memoir"]["chapters"]:
        c["photos"] = []
    for p in d["photos"]:
        p.pop("chapter_keys", None)
    with_drawn_objects(d)
    r = Run(tmp_path)
    items, calls, summary, doc = r.go(d)
    assert calls == {"select": 10, "image": 10} and pictures(doc) == [1] * 10
    assert summary["status"] == "complete" and summary["counts"]["inserted"] == 10 and il.MAX_SCENES == 3
    assert all(it["status"] == "inserted" for it in items.values())


def test_mixed_book_gets_pictures_only_where_there_is_no_photo(tmp_path):
    r = Run(tmp_path)
    items, calls, summary, doc = r.go(seed())
    assert pictures(doc) == [0, 1, 1, 0, 1, 0, 1, 1, 0, 1] and photos(doc) == [1, 0, 0, 3, 0, 1, 0, 0, 1, 0]
    assert calls == {"select": 6, "image": 6} and sorted(r.select_calls) == NO_PHOTO
    assert summary == {"status": "complete", "incomplete_reasons": [], "counts": {
        "toc_items": 10, "has_photo": 4, "no_photo_confirmed": 6, "photo_unknown": 0, "already_illustrated": 0, "targets": 6,
        "selected": 6, "images": 6, "inserted": 6, "failed": 0, "held": 0, "pending": 0, "needs_reprocess": 0,
        "photos_in": 6, "photos_relocated": 0, "photo_errors": 0, "photos_out": 6}}
    assert items["c04"]["status"] == "kept_photo" and len(items["c04"]["photo"]["photos"]) == 3      # 여러 장이어도 삽화는 없다
    assert doc["mock"] is True and doc["automatic"] is True


def test_item_result_carries_everything_and_claims_no_human_decision(tmp_path):
    items, _, _, doc = Run(tmp_path).go(seed())
    it = items["c03"]
    assert (it["key"], it["title"], it["photo"]["state"], it["target"], it["status"]) == ("c03", "모내기", "no_photo_confirmed", True, "inserted")
    assert it["automatic"] is True and it["user_selected"] is False and it["user_approved"] is False
    sel = it["selection"]
    assert (sel["status"], sel["mode"], sel["source"]) == ("selected", "SCENE", "candidate")
    assert {e["text"] for e in sel["scene"]["evidence"]} == {"모를 논에 심었다", "제가", "아버지", "모", "논"}
    assert all(e["quote"] and e["turn"] == 3 for e in sel["scene"]["evidence"]) and sel["scene"]["source_refs"][0]["session_id"] == "s-03"
    auto = sel["auto_checks"]
    assert auto["automatic"] is True and auto["human_confirmed"] is False
    assert [p["human"] for p in auto["people"]] == ["not_reviewed", "not_reviewed"]            # 자동으로 통과시킨 것을 confirmed 로 적지 않는다
    assert [p["code"] for p in auto["people"]] == ["structure_ok", "structure_ok"] and auto["participants_review_human"] == "not_reviewed"
    assert "확인하기 전" not in sel["prompt"]["text"] and "(인물 칸의 사람들이 함께 한다)" in sel["prompt"]["scene_block"]
    assert it["image"]["status"] == "mock_generated" and (tmp_path / it["image"]["path"]).read_bytes() == PIXELS
    assert it["insertion"]["status"] == "inserted" and it["insertion"]["after_paragraph"] == 1       # 「아버지와 둘이서 모를 논에 심었다」 문단 뒤
    run = json.loads((tmp_path / "items" / "c03" / "image" / "run.json").read_text(encoding="utf-8"))
    assert run["generation"] == {"user_selected": False, "user_selected_by": None, "automatic": True,
                                 "image_status": "generated", "user_approved": False}
    block = next(b for b in doc["chapters"][2]["blocks"] if b["type"] == "illustration")
    assert block["ai_generated"] is True and block["automatic"] is True and block["mock"] is True


def test_original_text_and_photos_are_kept(tmp_path):
    d = seed()
    before = json.dumps(d, ensure_ascii=False, sort_keys=True)
    _, _, _, doc = Run(tmp_path).go(d)
    assert json.dumps(d, ensure_ascii=False, sort_keys=True) == before                              # 원고를 건드리지 않는다
    for raw, ch in zip(d["memoir"]["chapters"], doc["chapters"]):
        assert [b["text"] for b in ch["blocks"] if b["type"] == "paragraph"] == [p["sentences"][0]["text"] for p in raw["paragraphs"]]
        own = [p["photo_id"] for p in raw.get("photos") or []] or [p["photo_id"] for p in d["photos"]
                                                                  if raw["chapter_key"] in p.get("chapter_keys", [])]
        assert [b["photo_id"] for b in ch["blocks"] if b["type"] == "photo"] == own
    md = (tmp_path / "book_illustrated.md").read_text(encoding="utf-8")
    page = (tmp_path / "preview.html").read_text(encoding="utf-8")
    assert md.count("AI 삽화 · 모의") == 6 and "모의 실행" in md
    assert page.count("<img class='illustration'") == 6 and page.count("<img class='existing-photo'") == 6   # 삽화 6 · 기존 사진 6
    assert page.count("data:image/jpeg;base64,") == 12 and "모의 실행 결과입니다" in page


# ---------------------------------------------------------------- 자동 검사 — 사람 확인을 대신하지 않는다

def test_scene_with_people_is_used_only_when_the_structure_holds(tmp_path):
    items, _, _, _ = Run(tmp_path).go(seed())
    c07 = items["c07"]["selection"]                                     # 관계 칸 없는 사람 → 사람을 빼고 그린다
    assert (c07["mode"], c07["source"]) == ("SYMBOLIC", "derived_symbolic") and "person_relation_missing" in c07["tried"][0]["blocking"]
    assert "어머니" not in c07["prompt"]["text"] and "- 인물: 그리지 않는다" in c07["prompt"]["scene_block"]
    assert c07["scene"]["scene_title"] == "재봉틀 · 마루" and {e["text"] for e in c07["scene"]["evidence"]} == {"재봉틀", "마루"}


def test_missing_companion_blocks_the_scene_and_is_not_filled_in(tmp_path):
    """「아버지랑 둘이서」 인데 아버지가 후보에 없다 — 혼자 심는 그림을 자동으로 만들지 않는다. 채워 넣지도 않는다."""
    by = copy.deepcopy(ALL)
    c = by["c03"]["candidates"][0]
    c["elements"] = [e for e in c["elements"] if e["text"] != "아버지"]
    c["scene_summary"] = "모를 논에 심었다."
    by["c03"]["candidates"] = [c]
    sel = Run(tmp_path, by).go(seed())[0]["c03"]["selection"]
    assert "possible_participant_omitted" in sel["tried"][0]["blocking"]
    assert (sel["mode"], sel["source"]) == ("SYMBOLIC", "derived_symbolic") and "아버지" not in sel["prompt"]["text"]


def test_item_that_cannot_be_drawn_fails_and_the_book_is_not_complete(tmp_path):
    by = copy.deepcopy(ALL)
    by["c02"] = {"candidates": []}                                      # 모델이 그릴 것을 내지 않았다
    by["c05"] = {"candidates": [dict(by["c05"]["candidates"][0], elements=[
        {"key": "o1", "kind": "object", "text": "난로", "turn": 5, "quote": "난로 위에 주전자가 끓었어요"}])]}    # 지어낸 인용
    by["c08"] = {"scenes": []}                                          # 모양이 다른 응답
    r = Run(tmp_path, by)
    items, calls, summary, doc = r.go(seed())
    assert (items["c02"]["status"], items["c02"]["failure"]) == ("failed", ["no_candidate"])
    assert items["c05"]["status"] == "failed" and items["c08"]["failure"] == ["model_output"]
    assert summary["status"] == "incomplete" and summary["counts"]["failed"] == 3 and "실패 3개" in summary["incomplete_reasons"]
    assert pictures(doc) == [0, 0, 1, 0, 0, 0, 1, 0, 0, 1] and calls["image"] == 3     # 실패한 항목은 그림을 부르지 않는다
    assert all(items[k]["user_selected"] is False for k in items)                      # 사용자에게 고르라고 넘기지 않는다
    assert "삽화 failed" in (tmp_path / "preview.html").read_text(encoding="utf-8")


def test_sensitive_item_is_held_not_drawn(tmp_path):
    d = seed()
    d["source"]["utterances"][9]["elder"] += " 그해 아버지가 병원에 오래 계셨어요."
    items, _, summary, doc = Run(tmp_path).go(d)
    assert (items["c10"]["status"], items["c10"]["failure"]) == ("held", ["sensitive"]) and items["c10"]["image"]["status"] == "not_requested"
    assert summary["status"] == "incomplete" and summary["counts"]["held"] == 1 and pictures(doc)[9] == 0


def test_unknown_photo_item_is_recorded_as_missing_data_not_generated(tmp_path):
    d = seed()
    chapter(d, "c02").pop("photos")
    r = Run(tmp_path)
    items, calls, summary, doc = r.go(d)
    assert (items["c02"]["status"], items["c02"]["target"], items["c02"]["failure"]) == ("photo_unknown", False, ["photo_info_missing"])
    assert "c02" not in r.select_calls and pictures(doc)[1] == 0 and calls["image"] == 5
    assert summary["status"] == "incomplete" and summary["counts"]["photo_unknown"] == 1


# ---------------------------------------------------------------- 다시 돌리기 · 복구

def test_rerun_generates_and_inserts_nothing_twice(tmp_path):
    r = Run(tmp_path)
    _, _, _, first = r.go(seed())
    again, calls, summary, second = r.go(seed())
    assert calls == {"select": 0, "image": 0} and len(r.select_calls) == 6 and len(r.image_calls) == 6
    assert second == first and pictures(second) == [0, 1, 1, 0, 1, 0, 1, 1, 0, 1] and summary["status"] == "complete"
    assert all(again[k]["selection_reused"] and again[k]["image"]["reused"] for k in NO_PHOTO)


def test_already_illustrated_input_is_left_alone(tmp_path):
    d = seed()
    chapter(d, "c02")["illustrations"] = [{"type": "illustration", "image": "old/c02.jpg", "after_paragraph": 0}]
    r = Run(tmp_path)
    items, calls, summary, doc = r.go(d)
    assert items["c02"]["status"] == "already_illustrated" and "c02" not in r.select_calls and calls["image"] == 5
    assert pictures(doc)[1] == 1 and summary["counts"]["already_illustrated"] == 1 and summary["status"] == "complete"


def test_moved_paragraph_is_followed_and_unrelated_edits_do_not_reprocess(tmp_path):
    """문단이 자리만 옮겼으면 그 문단을 따라간다. 그 장면과 상관없는 곳이 바뀐 것은 다시 처리할 까닭이 아니다."""
    r = Run(tmp_path)
    r.go(seed())
    d = seed()
    chapter(d, "c03")["paragraphs"].insert(0, {"sentences": [{"text": "새로 넣은 머리 문단이다.", "turns": []}]})   # 같은 항목에 새 문단
    chapter(d, "c05")["paragraphs"][1]["sentences"][0]["text"] = "연탄집게로 연탄을 갈아 넣었다."                    # 장면과 다른 문단을 고침
    d["source"]["utterances"][0]["elder"] += " 물맛이 좋았어요."                                                    # 다른 항목(사진 있는 1번)의 원문
    chapter(d, "c06")["title"] = "읍내 가는 버스"
    items, calls, summary, doc = r.go(d)
    assert calls == {"select": 0, "image": 0} and summary["status"] == "complete" and summary["counts"]["needs_reprocess"] == 0
    assert items["c03"]["body_changed"] is True
    assert (items["c03"]["insertion"]["after_paragraph"], items["c03"]["insertion"]["locate"]) == (2, "moved")
    assert items["c05"]["status"] == "inserted" and items["c05"]["body_changed"] is True          # 그 장면의 문단(0)은 그대로다
    assert pictures(doc) == [0, 1, 1, 0, 1, 0, 1, 1, 0, 1]


def test_removed_item_takes_its_picture_nowhere(tmp_path):
    r = Run(tmp_path)
    r.go(seed())
    d = seed()
    d["memoir"]["chapters"] = [c for c in d["memoir"]["chapters"] if c["chapter_key"] != "c03"]
    items, calls, _, doc = r.go(d)
    assert "c03" not in items and sum(pictures(doc)) == 5 and calls == {"select": 0, "image": 0}


def test_insert_failure_is_recovered_from_the_saved_picture(tmp_path, monkeypatch):
    r = Run(tmp_path)
    real = tool.INSERT

    def broken(data, item, placement):
        if item["ident"] == "c05":
            raise OSError("cannot write")
        return real(data, item, placement)
    monkeypatch.setattr(tool, "INSERT", broken)
    items, calls, summary, doc = r.go(seed())
    assert (items["c05"]["status"], items["c05"]["failure"]) == ("failed", ["insert_insert_error"])
    assert items["c05"]["image"]["status"] == "mock_generated" and pictures(doc)[4] == 0 and summary["status"] == "incomplete"
    assert all(items[k]["status"] == "inserted" for k in NO_PHOTO if k != "c05")                    # 다른 항목은 그대로 성공이다
    monkeypatch.setattr(tool, "INSERT", real)
    items, calls, summary, doc = r.go(seed())
    assert calls == {"select": 0, "image": 0} and r.image_calls.count("c05") == 1                   # 그림을 다시 만들지 않았다
    assert items["c05"]["status"] == "inserted" and pictures(doc)[4] == 1 and summary["status"] == "complete"


def test_one_failed_picture_does_not_spoil_the_others_and_is_not_retried(tmp_path):
    r = Run(tmp_path, fail_images=("c05",))
    items, calls, summary, doc = r.go(seed())
    assert (items["c05"]["status"], items["c05"]["failure"]) == ("failed", ["image_error"]) and calls["image"] == 6
    assert [items[k]["status"] for k in NO_PHOTO if k != "c05"] == ["inserted"] * 5 and pictures(doc) == [0, 1, 1, 0, 0, 0, 1, 1, 0, 1]
    assert summary["status"] == "incomplete" and summary["counts"]["failed"] == 1
    r.fail_images = ()
    items, calls, summary, _ = r.go(seed())                             # 다시 돌려도 실패한 항목을 스스로 다시 부르지 않는다
    assert calls == {"select": 0, "image": 0} and r.image_calls.count("c05") == 1 and items["c05"]["status"] == "failed"
    assert [items[k]["status"] for k in NO_PHOTO if k != "c05"] == ["inserted"] * 5


def test_select_error_fails_only_that_item(tmp_path):
    r = Run(tmp_path, select_error=("c08",))
    items, calls, summary, _ = r.go(seed())
    assert items["c08"]["failure"] == ["select_call_error"] and summary["counts"]["inserted"] == 5 and calls["image"] == 5
    assert r.go(seed())[1] == {"select": 0, "image": 0}


def test_picture_generation_can_be_resumed_after_selection_only(tmp_path):
    r = Run(tmp_path)
    items, calls, summary, doc = r.go(seed(), images=False)
    assert calls == {"select": 6, "image": 0} and summary["status"] == "incomplete" and summary["counts"]["pending"] == 6
    assert pictures(doc) == [0] * 10
    items, calls, summary, doc = r.go(seed())
    assert calls == {"select": 0, "image": 6} and summary["status"] == "complete"


# ---------------------------------------------------------------- 실행기

@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "RUNS", tmp_path / "runs")
    seed_path, mock_path = tmp_path / "seed.json", tmp_path / "mock.json"
    seed_path.write_text(json.dumps(SEED, ensure_ascii=False), encoding="utf-8")
    mock_path.write_text(json.dumps({"by_chapter": MOCK}, ensure_ascii=False), encoding="utf-8")
    shutil.copytree(PHOTO_BASE / "illust_book_photos_B", tmp_path / "illust_book_photos_B")
    return type("Cli", (), {"tmp": tmp_path, "out": tmp_path / "runs" / "o",
                            "base": ["--input", str(seed_path), "--out", str(tmp_path / "runs" / "o")], "mock": str(mock_path)})


def test_cli_dry_run_plans_without_calling(cli, capsys):
    assert tool.main(cli.base + ["--dry-run"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["targets"] == NO_PHOTO and d["limit"] is None and d["calls_if_live"] == {"select": 6, "image_at_most": 6}
    assert d["photo_states"] == {"has_photo": 4, "no_photo_confirmed": 6, "unknown": 0}
    assert d["api_called"] is False and d["live_approved"] is False and not cli.out.exists()


def test_cli_mock_run_writes_the_book_and_preview(cli, capsys):
    assert tool.main(cli.base + ["--mock-select", cli.mock, "--mock-images"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["mock"] is True and shown["summary"]["status"] == "complete" and shown["calls"] == {"select": 6, "image": 6}
    assert {p.name for p in cli.out.iterdir()} == {"state.json", "items.json", "book_illustrated.json", "book_illustrated.md",
                                                   "preview.html", "items"}
    table = json.loads((cli.out / "items.json").read_text(encoding="utf-8"))
    assert table["mock"] is True and [r["status"] for r in table["items"]].count("inserted") == 6
    run = json.loads((cli.out / "items" / "c02" / "image" / "run.json").read_text(encoding="utf-8"))
    assert run["mock"] is True and run["model"] == "mock"                                           # 모의 그림이라고 적힌다
    assert tool.main(cli.base + ["--mock-select", cli.mock, "--mock-images"]) == 0
    assert json.loads(capsys.readouterr().out)["calls"] == {"select": 0, "image": 0}


def test_cli_refuses_live_without_every_condition_and_never_calls(cli, capsys, monkeypatch):
    called = []
    monkeypatch.setattr(seltool, "LIVE_CALL", lambda *a, **k: called.append("select") or {"text": "{}"})
    monkeypatch.setattr(img, "LIVE_CALL", lambda *a, **k: called.append("image") or {})
    assert tool.main(cli.base) == 2 and tool.main(cli.base + ["--live"]) == 2
    assert tool.main(cli.base + ["--live", "--confirm", "wrong", "--env-file", "x", "--authorized-by", "가", "--authorization-note", "나"]) == 2
    assert tool.main(cli.base + ["--live", "--mock-images"]) == 2
    assert tool.main(["--input", cli.base[1], "--out", str(cli.tmp / "elsewhere"), "--dry-run"]) == 2      # git 제외 경로 밖
    capsys.readouterr()
    assert called == [] and not cli.out.exists()


def test_cli_live_wiring_calls_once_per_item_with_fakes(cli, capsys, monkeypatch):
    """실제 호출의 배선만 가짜로 본다 — 항목마다 장면 선정 한 번 · 그림 한 번. 실제 API 를 부르지 않는다."""
    sel, pics = [], []

    def fake_select(system, user, *, model, key):
        ident = next(k for k in MOCK if f'"chapter_no": {int(k[1:])},' in user)
        sel.append((ident, model, key))
        return {"text": json.dumps(MOCK[ident], ensure_ascii=False)}

    def fake_image(prompt, *, model, size, aspect, key):
        pics.append((model, size, aspect, key))
        return {"id": "x", "status": "completed",
                "output_image": {"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(PIXELS).decode()}}
    monkeypatch.setattr(seltool, "LIVE_CALL", fake_select)
    monkeypatch.setattr(img, "LIVE_CALL", fake_image)
    (cli.tmp / "k.env").write_text("GEMINI_API_KEY=test-key-not-real\n", encoding="utf-8")
    assert tool.main(cli.base + ["--dry-run"]) == 0
    token = json.loads(capsys.readouterr().out)["live_confirm"]
    assert tool.main(cli.base + ["--live", "--confirm", token, "--env-file", str(cli.tmp / "k.env"),
                                 "--authorized-by", "시험", "--authorization-note", "시험용"]) == 0
    shown = capsys.readouterr().out
    assert sorted(x[0] for x in sel) == NO_PHOTO and len(pics) == 6 and "test-key-not-real" not in shown
    assert set(pics) == {("gemini-3.1-flash-image", "1K", "5:4", "test-key-not-real")}
    doc = json.loads((cli.out / "book_illustrated.json").read_text(encoding="utf-8"))
    assert doc["mock"] is False and pictures(doc) == [0, 1, 1, 0, 1, 0, 1, 1, 0, 1]
    run = json.loads((cli.out / "items" / "c03" / "image" / "run.json").read_text(encoding="utf-8"))
    assert run["approval"]["mode"] == "automatic" and run["approval"]["batch_authorization"]["authorized_by"] == "시험"
    assert run["generation"]["user_selected"] is False and run["generation"]["user_approved"] is False
    everything = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in cli.out.rglob("*") if p.is_file())
    assert "test-key-not-real" not in everything


def test_old_flow_keeps_its_limit_and_new_flow_does_not_use_it():
    """앞선 검토 흐름(il.run)의 한도는 그대로다. 목차별 흐름은 pick=False 로 그 한도와 겹침 덜기를 쓰지 않는다."""
    d = seed()
    for c in d["memoir"]["chapters"]:
        c["photos"] = []
    d["photos"] = []
    cands = [ALL[k]["candidates"][0] for k in ("c01", "c02", "c05", "c06", "c08")]
    reply = json.dumps({"candidates": cands}, ensure_ascii=False)
    old = il.run(d, call=lambda s, u: reply)
    new = il.run(d, call=lambda s, u: reply, pick=False)
    assert [s["decision"] for s in old["scenes"]].count("not_selected") == 2 and old["limits"]["max_scenes"] == 3
    assert [s["decision"] for s in new["scenes"]] == ["eligible"] * 5 and new["limits"]["max_scenes"] is None


# ---------------------------------------------------------------- 다시 돌릴 때 — 달라진 원문에 앞선 결과가 붙지 않는다

def corrected() -> dict:
    """「뒤꼍에 장독대가 있었어요」 를 「뒤꼍에 장독대는 없었어요」 로 정정한 책 (원문과 그 본문 문장)."""
    d = seed()
    d["source"]["utterances"][1]["elder"] = "뒤꼍에 장독대는 없었어요. 큰 장독이 여섯 개 나란히 놓여 있었어요."
    chapter(d, "c02")["paragraphs"][0]["sentences"][0]["text"] = "뒤꼍에 장독대는 없었다."
    return d


def test_corrected_source_does_not_get_the_old_picture_back(tmp_path):
    """수정 전에는 같은 목차 식별자라는 것만으로 앞선 「뒤꼍의 장독대」 그림이 다시 들어갔다."""
    r = Run(tmp_path)
    r.go(seed())
    old = (tmp_path / "items" / "c02" / "image" / "image.jpg").read_bytes()
    items, calls, summary, doc = r.go(corrected())
    c02 = items["c02"]
    assert c02["status"] == "needs_reprocess" and c02["failure"] == ["source_changed", "memoir_paragraph_changed"]
    assert c02["stale"]["reasons"][0]["turns"] == [2] and c02["stale"]["previous_selection"] == "뒤꼍의 장독대"
    assert pictures(doc)[1] == 0 and c02["insertion"]["status"] == "not_applicable"       # 앞선 그림을 넣지 않는다
    assert calls == {"select": 0, "image": 0}                                            # 스스로 다시 만들지도 않는다
    assert (tmp_path / "items" / "c02" / "image" / "image.jpg").read_bytes() == old       # 앞선 파일은 그대로 둔다
    assert summary["status"] == "incomplete" and summary["counts"]["needs_reprocess"] == 1
    assert [items[k]["status"] for k in NO_PHOTO if k != "c02"] == ["inserted"] * 5       # 상관없는 항목은 다시 만들지 않는다
    assert pictures(doc) == [0, 0, 1, 0, 1, 0, 1, 1, 0, 1]
    assert "다시 처리 필요 1" in (tmp_path / "preview.html").read_text(encoding="utf-8")


def test_stale_item_is_reprocessed_only_when_asked_and_old_files_are_kept(tmp_path):
    by = copy.deepcopy(ALL)
    by["c02"] = sym(2, "장독", "큰 장독이 여섯 개 나란히 놓여 있었어요")                 # 정정된 원문에서 나온 새 후보 (장독대 없이)
    r = Run(tmp_path, by)
    r.go(seed())
    r.go(corrected())
    items, calls, summary, doc = r.go(corrected(), reprocess=True)
    assert calls == {"select": 1, "image": 1} and r.select_calls.count("c02") == 2       # 그 항목만 다시 묻고 다시 만든다
    assert items["c02"]["status"] == "inserted" and items["c02"]["selection"]["scene"]["scene_title"] == "장독"
    assert items["c02"]["reprocessed"]["previous_files"] == "items/_stale/c02-1"
    assert (tmp_path / "items" / "_stale" / "c02-1" / "image" / "image.jpg").is_file()    # 앞선 그림은 옮겨 두었다
    assert "장독대" not in items["c02"]["selection"]["prompt"]["text"]
    assert summary["status"] == "complete" and pictures(doc)[1] == 1
    assert r.go(corrected(), reprocess=True)[1] == {"select": 0, "image": 0}             # 다시 켜도 멀쩡한 항목은 건드리지 않는다


@pytest.mark.parametrize("change,reason", [
    (lambda d: d["memoir"].update(memoir_id="another-book"), "book_changed"),
    (lambda d: (d["source"]["utterances"][1].update(session_id="s-99"), d["source"]["turn_map"][1].update(session_id="s-99")),
     "source_changed"),
    (lambda d: d["source"]["turn_map"][1].update(turn=7), "source_changed"),
    (lambda d: chapter(d, "c02")["paragraphs"][0]["sentences"][0].update(text="뒤꼍에는 큰 장독대가 있었다."), "memoir_paragraph_changed"),
])
def test_reuse_is_refused_when_what_the_scene_rested_on_changed(tmp_path, change, reason):
    r = Run(tmp_path)
    r.go(seed())
    d = seed()
    change(d)
    items, calls, _, doc = r.go(d)
    assert reason in items["c02"]["failure"] and items["c02"]["status"] == "needs_reprocess"
    assert pictures(doc)[1] == 0 and calls == {"select": 0, "image": 0}


def test_changed_prompt_or_image_settings_mark_every_reused_item(tmp_path, monkeypatch):
    r = Run(tmp_path)
    r.go(seed())
    monkeypatch.setattr(tool, "IMAGE_ASPECT", "1:1")
    items, calls, summary, _ = r.go(seed())
    assert all(items[k]["failure"] == ["image_settings_changed"] for k in NO_PHOTO) and calls == {"select": 0, "image": 0}
    monkeypatch.setattr(tool, "IMAGE_ASPECT", "5:4")
    assert r.go(seed())[2]["status"] == "complete"                                        # 설정이 되돌아오면 앞선 결과를 그대로 쓴다
    monkeypatch.setattr(book, "prompt_hash", lambda: "another-prompt")
    items, _, summary, _ = r.go(seed())
    assert all(items[k]["failure"] == ["select_prompt_changed"] for k in NO_PHOTO) and summary["counts"]["needs_reprocess"] == 6


def test_old_state_without_a_basis_is_not_trusted(tmp_path):
    r = Run(tmp_path)
    r.go(seed())
    st = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    st["items"]["c02"].pop("basis")
    (tmp_path / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    items, calls, _, doc = r.go(seed())
    assert items["c02"]["failure"] == ["no_basis"] and pictures(doc)[1] == 0 and calls == {"select": 0, "image": 0}


def test_failed_item_is_marked_for_reprocess_when_its_source_changes(tmp_path):
    by = copy.deepcopy(ALL)
    by["c02"] = {"candidates": []}
    r = Run(tmp_path, by)
    assert r.go(seed())[0]["c02"]["status"] == "failed"
    assert r.go(seed())[0]["c02"]["status"] == "failed"                                   # 달라진 것이 없으면 실패 그대로다
    assert r.go(corrected())[0]["c02"]["status"] == "needs_reprocess"


# ---------------------------------------------------------------- 모의 실행과 실제 실행

def test_mock_folder_is_refused_for_a_real_run_before_any_call(cli, capsys, monkeypatch):
    """수정 전에는 모의 폴더를 실제 실행에 넘기면 호출 없이 「실제 · complete」 로 끝나고 책에는 모의 그림이 들어 있었다."""
    called = []
    monkeypatch.setattr(seltool, "LIVE_CALL", lambda *a, **k: called.append("select") or {"text": "{}"})
    monkeypatch.setattr(img, "LIVE_CALL", lambda *a, **k: called.append("image") or {})
    (cli.tmp / "k.env").write_text("GEMINI_API_KEY=test-key-not-real\\n", encoding="utf-8")
    assert tool.main(cli.base + ["--mock-select", cli.mock, "--mock-images"]) == 0
    before = (cli.out / "book_illustrated.json").read_text(encoding="utf-8")
    capsys.readouterr()
    assert tool.main(cli.base + ["--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["existing_state"] == "mock"
    code = tool.main(cli.base + ["--live", "--confirm", plan["live_confirm"], "--env-file", str(cli.tmp / "k.env"),
                                 "--authorized-by", "시험", "--authorization-note", "시험용"])
    err = capsys.readouterr().err
    assert code == 2 and "모의 실행의 것" in err and called == []
    assert (cli.out / "book_illustrated.json").read_text(encoding="utf-8") == before      # 모의 결과를 실제 결과로 덮어쓰지 않는다


def test_process_refuses_the_other_mode_in_both_directions(tmp_path):
    r = Run(tmp_path)
    r.go(seed())
    with pytest.raises(il.IllustError) as e:
        tool.process(seed(), tmp_path, select_for=r.select_for, image_call=r.image_call, mock=False, base_dir=PHOTO_BASE)
    assert e.value.kind == "mode" and len(r.image_calls) == 6
    live = tmp_path / "live"
    tool.process(seed(), live, select_for=r.select_for, image_call=r.image_call, mock=False, image_model="m", base_dir=PHOTO_BASE)
    with pytest.raises(il.IllustError):
        tool.process(seed(), live, select_for=r.select_for, image_call=r.image_call, mock=True, image_model="m", base_dir=PHOTO_BASE)


def test_mock_picture_never_counts_in_a_real_run(tmp_path):
    """상태 파일의 모드 표시가 바뀌어 있어도(손으로 고쳤거나 옛 파일) 그림마다의 기록으로 다시 본다."""
    r = Run(tmp_path)
    r.go(seed())
    st = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    st["mock"] = False
    for it in st["items"].values():
        if it.get("basis"):
            it["basis"]["image"]["model"] = "mock"
    (tmp_path / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    items, calls = tool.process(seed(), tmp_path, select_for=r.select_for, image_call=r.image_call, mock=False,
                                image_model="mock", base_dir=PHOTO_BASE)
    summary = tool.write_outputs(seed(), tmp_path, items, False, PHOTO_BASE)
    assert all(it["failure"] == ["image_mode_mismatch"] for it in items if it["target"])
    assert calls == {"select": 0, "image": 0} and len(r.image_calls) == 6                 # 검사에 걸렸다고 다시 부르지 않는다
    assert summary["status"] == "incomplete" and summary["counts"]["inserted"] == 0


def test_saved_picture_must_exist_and_match_its_record(tmp_path):
    r = Run(tmp_path)
    r.go(seed())
    (tmp_path / "items" / "c02" / "image" / "image.jpg").write_bytes(b"\\xff\\xd8 someone replaced this file")   # 기록과 다른 파일
    (tmp_path / "items" / "c05" / "image" / "image.jpg").unlink()                         # 파일만 없어졌다 — 응답은 있다
    (tmp_path / "items" / "c08" / "image" / "image.jpg").unlink()                         # 파일도 응답도 없다
    (tmp_path / "items" / "c08" / "image" / "response.json").unlink()
    items, calls, summary, doc = r.go(seed())
    assert items["c02"]["failure"] == ["image_file_mismatch"] and items["c08"]["failure"] == ["image_file_missing"]
    assert items["c05"]["status"] == "inserted" and (tmp_path / "items" / "c05" / "image" / "image.jpg").read_bytes() == PIXELS
    assert calls == {"select": 0, "image": 0} and len(r.image_calls) == 6                 # 다시 부르지 않는다
    assert pictures(doc) == [0, 0, 1, 0, 1, 0, 1, 0, 0, 1] and summary["status"] == "incomplete" and summary["counts"]["failed"] == 2


# ---------------------------------------------------------------- 기존 사진을 빼지 않는다

def photo_blocks(doc: dict, no: int) -> list[dict]:
    return [b for b in doc["chapters"][no - 1]["blocks"] if b["type"] == "photo"]


@pytest.mark.parametrize("position", [7, -1, "둘째", 1.5, True])
def test_photo_with_an_unusable_position_is_moved_not_dropped(tmp_path, position):
    """수정 전에는 자리가 범위를 벗어난 사진이 결과에서 조용히 사라졌고 책은 complete 였다."""
    d = seed()
    chapter(d, "c04")["photos"][0]["after_paragraph"] = position
    _, _, summary, doc = Run(tmp_path).go(d)
    shown = photo_blocks(doc, 4)
    assert [b["photo_id"] for b in shown] == ["ph-04b", "ph-04c", "ph-04a"]               # 세 장 다 있다 — 옮긴 것은 항목 끝에
    assert shown[2]["position_basis"] == "default_end_invalid_position" and "빼지 않고" in shown[2]["position_note"]
    assert [b["position_basis"] for b in shown[:2]] == ["given", "given"]                 # 멀쩡한 자리는 그대로다
    blocks = doc["chapters"][3]["blocks"]
    assert blocks[-1]["photo_id"] == "ph-04a"
    assert summary["counts"]["photos_in"] == summary["counts"]["photos_out"] == 6 and summary["counts"]["photos_relocated"] == 1
    assert summary["status"] == "complete"                                                # 빠진 사진이 없다 — 옮긴 것은 기록으로 남는다


def test_photos_survive_a_deleted_paragraph_on_rerun(tmp_path):
    r = Run(tmp_path)
    r.go(seed())
    d = seed()
    chapter(d, "c04")["paragraphs"].pop()                               # 문단 2개 → 1개. 사진 둘의 자리(after_paragraph 1)가 없어졌다
    _, _, summary, doc = r.go(d)
    shown = photo_blocks(doc, 4)
    assert sorted(b["photo_id"] for b in shown) == ["ph-04a", "ph-04b", "ph-04c"]
    assert [b["position_basis"] for b in shown] == ["given", "default_end_invalid_position", "default_end_invalid_position"]
    assert summary["counts"]["photos_out"] == 6 and summary["counts"]["photos_relocated"] == 2 and summary["status"] == "complete"


def test_photo_without_a_position_goes_to_the_start_of_its_item(tmp_path):
    d = seed()
    chapter(d, "c01")["photos"][0].pop("after_paragraph")
    doc = Run(tmp_path).go(d)[3]
    first = doc["chapters"][0]["blocks"][0]
    assert (first["type"], first["photo_id"], first["position_basis"]) == ("photo", "ph-01", "default_start_no_position")


def test_unreadable_photo_is_an_error_and_the_book_is_not_complete(tmp_path):
    d = seed()
    chapter(d, "c06")["photos"][0]["path"] = "illust_book_photos_B/없는-사진.jpg"
    items, _, summary, doc = Run(tmp_path).go(d)
    assert items["c06"]["status"] == "kept_photo" and items["c06"]["failure"] == ["photo_file_unreadable"]
    block = photo_blocks(doc, 6)[0]
    assert block["error"] == "photo_file_unreadable" and block["photo_id"] == "ph-06"     # 자리는 지킨다 — 조용히 빼지 않는다
    assert summary["status"] == "incomplete" and summary["counts"]["photo_errors"] == 1 and "읽지 못한 사진 1장" in summary["incomplete_reasons"]
    page = (tmp_path / "preview.html").read_text(encoding="utf-8")
    assert "사진 파일을 읽지 못했다 — ph-06" in page and page.count("<img class='existing-photo'") == 5


def test_missing_photo_block_would_not_be_called_complete():
    """사진 수가 맞지 않으면 complete 가 아니다 — 조립이 잘못돼도 요약이 잡는다."""
    items = [{"photo": {"state": "has_photo", "photos": [{"photo_id": "a"}, {"photo_id": "b"}]}, "target": False, "status": "kept_photo",
              "selection": None, "image": {"status": "not_requested"}, "insertion": {"status": "not_applicable"}}]
    doc = {"chapters": [{"blocks": [{"type": "photo", "photo_id": "a"}]}]}
    s = book.summarize(items, False, doc)
    assert s["status"] == "incomplete" and "사진이 빠졌다" in s["incomplete_reasons"][0]


# ---------------------------------------------------------------- 미리보기에 사진이 보인다

def test_preview_shows_each_photo_and_each_picture_exactly_once(tmp_path):
    _, _, _, doc = Run(tmp_path).go(seed())
    page = (tmp_path / "preview.html").read_text(encoding="utf-8")
    ids = [x.split("'")[0] for x in page.split("<img class='existing-photo' data-photo-id='")[1:]]
    assert ids == ["ph-01", "ph-04a", "ph-04b", "ph-04c", "ph-06", "ph-09"]              # 기존 사진 6장 — 빠짐도 겹침도 없다
    assert "ph-08x" not in ids and "실제 사진 자리" not in page                          # 어느 항목에도 놓이지 않은 사진은 넣지 않는다
    assert page.count("<img class='illustration'") == 6 and page.count("MOCK") == 0      # 모의 삽화 6장 (글자는 그림 안에 있다)
    for pid in ids:                                                     # 박아 넣은 것이 그 사진 파일의 바이트다
        raw = base64.b64encode((PHOTO_BASE / "illust_book_photos_B" / f"{pid}.jpg").read_bytes()).decode()
        assert page.count(raw) == 1
    assert page.count(base64.b64encode(PIXELS).decode()) == 6
    assert photos(doc) == [1, 0, 0, 3, 0, 1, 0, 0, 1, 0] and pictures(doc) == [0, 1, 1, 0, 1, 0, 1, 1, 0, 1]


def test_photo_linked_from_the_book_level_list_keeps_its_file(tmp_path):
    """9번 항목의 사진은 책 전체 사진 목록에서 이어진다 — 경로와 자리가 중간에 사라지지 않는다."""
    items, _, _, doc = Run(tmp_path).go(seed())
    p = items["c09"]["photo"]["photos"][0]
    assert (p["link"], p["path"], p["after_paragraph"], p["file"]) == ("photos[].chapter", "illust_book_photos_B/ph-09.jpg", 1, "readable")
    block = photo_blocks(doc, 9)[0]
    assert block["path"] == "illust_book_photos_B/ph-09.jpg" and block["position_basis"] == "given"
    assert doc["chapters"][8]["blocks"][-1]["photo_id"] == "ph-09"      # 둘째 문단 뒤


def test_photo_given_by_url_or_with_no_file_info(tmp_path):
    d = seed()
    chapter(d, "c01")["photos"] = [{"photo_id": "ph-url", "url": "https://example.invalid/p.jpg", "after_paragraph": 0}]
    chapter(d, "c06")["photos"] = [{"photo_id": "ph-none", "after_paragraph": 0}]
    items, _, summary, _ = Run(tmp_path).go(d)
    page = (tmp_path / "preview.html").read_text(encoding="utf-8")
    assert "data-photo-id='ph-url' src='https://example.invalid/p.jpg'" in page          # 주소가 있으면 그 주소로 보인다
    assert "사진 파일 경로 · 주소가 입력에 없다 — ph-none" in page                        # 없으면 없다고 적는다 (빼지 않는다)
    assert items["c01"]["photo"]["photos"][0]["file"] == "url_not_checked" and items["c06"]["photo"]["photos"][0]["file"] == "no_file_info"
    assert summary["status"] == "complete" and summary["counts"]["photos_out"] == 6


# ---------------------------------------------------------------- 실제 한 항목 시험 준비 — 장면 선정 호출의 재시도 · 실행 정보

SELECT_SCRIPT = """
import json, sys
sys.path.insert(0, sys.argv[1])
from tools import memoir_illust as seltool
try:
    r = seltool.gemini_call("system text", sys.argv[3], model="m-sel", key="test-key-not-real", base_url=sys.argv[2])
    print(json.dumps({"ok": True, **r}))
except Exception as e:
    print(json.dumps({"ok": False, "type": type(e).__name__}))
"""


class _GenServer:
    def __init__(self, status: int, body: dict):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        self.hits, outer = [], self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):                      # noqa: N802
                n = int(self.headers.get("content-length") or 0)
                outer.hits.append({"path": self.path, "body": json.loads(self.rfile.read(n) or b"{}")})
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"


def _select_sdk(server) -> dict:
    """실제 SDK 로 이 컴퓨터의 가짜 서버를 부른다 — 다른 프로세스에서(이 프로세스는 conftest 가 클라이언트 생성을 막는다)."""
    import os
    import subprocess
    try:
        done = subprocess.run([sys.executable, "-c", SELECT_SCRIPT, str(ROOT), server.url, "user text 자료"], capture_output=True,
                              text=True, encoding="utf-8", timeout=60, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    finally:
        server.httpd.shutdown()
    assert done.returncode == 0, done.stderr[-400:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_select_sdk_sends_one_request_and_returns_run_info():
    server = _GenServer(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": "{\"candidates\": []}"}]},
                                              "finishReason": "STOP"}],
                              "usageMetadata": {"promptTokenCount": 2600, "candidatesTokenCount": 800, "totalTokenCount": 3400},
                              "modelVersion": "m-sel-001", "responseId": "resp-123"})
    got = _select_sdk(server)
    assert got["ok"] and got["text"] == '{"candidates": []}'
    assert (got["model_requested"], got["model_version"], got["response_id"]) == ("m-sel", "m-sel-001", "resp-123")
    assert got["usage"] == {"prompt": 2600, "output": 800, "thoughts": None, "total": 3400} and got["retries"] == "off (attempts=1)"
    assert len(server.hits) == 1 and server.hits[0]["path"].endswith("/models/m-sel:generateContent")
    body = server.hits[0]["body"]
    assert body["contents"][0]["parts"][0]["text"] == "user text 자료" and "tools" not in body      # 보낸 것은 지시문과 자료뿐이다
    assert body["systemInstruction"]["parts"][0]["text"] == "system text"


@pytest.mark.parametrize("status", [503, 429, 500, 408])
def test_select_sdk_does_not_retry_on_errors(status):
    server = _GenServer(status, {"error": {"code": status, "message": "try later", "status": "UNAVAILABLE"}})
    got = _select_sdk(server)
    assert got["ok"] is False and len(server.hits) == 1


def test_select_run_info_is_saved_and_an_interrupted_select_is_not_called_again(cli, capsys, monkeypatch):
    sel, pics = [], []

    def fake_select(system, user, *, model, key):
        ident = next(k for k in MOCK if f'"chapter_no": {int(k[1:])},' in user)
        sel.append(ident)
        return {"text": json.dumps(MOCK[ident], ensure_ascii=False), "model_requested": model, "model_version": "m-sel-001",
                "response_id": f"resp-{ident}", "usage": {"prompt": 2600, "output": 800, "total": 3400},
                "finish": "STOP", "retries": "off (attempts=1)"}

    def fake_image(prompt, *, model, size, aspect, key):
        pics.append(1)
        return {"id": "x", "status": "completed",
                "output_image": {"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(PIXELS).decode()}}
    monkeypatch.setattr(seltool, "LIVE_CALL", fake_select)
    monkeypatch.setattr(img, "LIVE_CALL", fake_image)
    (cli.tmp / "k.env").write_text("GEMINI_API_KEY=test-key-not-real\n", encoding="utf-8")
    # 앞선 실행이 c05 의 장면 선정을 부르다 멈춘 것처럼 — 부른 기록만 있고 결과가 없다
    (cli.out / "items" / "c05").mkdir(parents=True)
    (cli.out / "items" / "c05" / "select_attempt.json").write_text("{}", encoding="utf-8")
    assert tool.main(cli.base + ["--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["retries"] == {"select": "off (attempts=1)", "image": "off (SDK · HTTP)"}
    assert [x["toc_item"] for x in plan["sent_if_live"]] == NO_PHOTO and plan["sent_if_live"][0]["source_turns"] == [2]
    code = tool.main(cli.base + ["--live", "--confirm", plan["live_confirm"], "--env-file", str(cli.tmp / "k.env"),
                                 "--authorized-by", "시험", "--authorization-note", "시험용"])
    capsys.readouterr()
    assert code == 1 and "c05" not in sel and len(sel) == 5 and len(pics) == 5      # c05 는 다시 부르지 않고 실패로 남는다
    run = json.loads((cli.out / "items" / "c03" / "select_run.json").read_text(encoding="utf-8"))
    assert (run["model_requested"], run["model_version"], run["response_id"]) == ("gemini-3.5-flash-lite", "m-sel-001", "resp-c03")
    assert run["usage"]["total"] == 3400 and run["mock"] is False and run["started_at"] <= run["finished_at"]
    state = json.loads((cli.out / "state.json").read_text(encoding="utf-8"))["items"]
    assert state["c03"]["select_run"]["response_id"] == "resp-c03" and state["c05"]["failure"] == ["select_attempt_without_result"]
    assert "test-key-not-real" not in "".join(p.read_text(encoding="utf-8", errors="ignore") for p in cli.out.rglob("*.json"))


# ---------------------------------------------------------------- 지시문 v5 · 후보 비교 — 목차의 중심 내용을 담는 그림을 고른다

# 실제 원문 · 실제 모델 응답(git 제외 경로)으로 돌리던 회귀 시험은 공유본에서 뺐다 — 실험 기록에만 남는다.
# 같은 규칙은 아래의 합성 자료 시험과 tests/test_memoir_illust_types.py 가 확인한다.


def cand5(no, title, elements, central=None, importance="main"):
    c = {"chapter_no": no, "scene_title": title, "scene_summary": f"{title}.", "importance": importance,
         "reason": "대표한다.", "elements": elements}
    if central:
        c["central_action"] = central
    return c


def choose(d, ident, candidates, focus=None):
    doc = {"candidates": candidates}
    if focus is not None:
        doc["focus"] = focus
    return book.choose(d, ident, json.dumps(doc, ensure_ascii=False))


def el5(key, kind, text, turn, quote, **extra):
    return {"key": key, "kind": kind, "text": text, "turn": turn, "quote": quote, **extra}


def rel5(action, role, turn, *quotes):
    return {"action": action, "role": role, "evidence": [{"turn": turn, "quote": q} for q in quotes]}


RICE_FIELD = cand5(3, "봄의 논", [el5("s1", "place", "논", 3, "온 식구가 논에 나갔어요", role="setting")])


def planting(*, father=True, me_evidence="제가 아버지랑 둘이서 모를 논에 심었어요"):
    els = [el5("a1", "action", "모를 논에 심었다", 3, "제가 아버지랑 둘이서 모를 논에 심었어요"),
           el5("p1", "person", "제가", 3, "제가 아버지랑 둘이서 모를 논에 심었어요", relation=rel5("a1", "actor", 3, me_evidence)),
           el5("o1", "object", "모", 3, "모를 논에 심었어요", relation=rel5("a1", "acted_on", 3, "모를 논에 심었어요")),
           el5("s1", "place", "논", 3, "모를 논에 심었어요", role="setting")]
    if father:
        els.insert(2, el5("p2", "person", "아버지", 3, "아버지랑 둘이서",
                          relation=rel5("a1", "co_actor", 3, "제가 아버지랑 둘이서 모를 논에 심었어요")))
    return cand5(3, "모를 심다", els, central="a1")


def by_source(sel) -> dict:
    return {(c["source"], c["candidate_index"]): c for c in sel["comparison"]}


def test_person_scene_rejected_but_the_central_object_is_kept(tmp_path):
    """함께 한 아버지가 빠진 장면은 막히고, 모델이 따로 낸 「봄의 논」(배경) 대신 그 장면의 사물(모)을 지킨 그림을 고른다."""
    sel = choose(seed(), "c03", [planting(father=False), RICE_FIELD])
    assert (sel["mode"], sel["source"]) == ("SYMBOLIC", "derived_symbolic")
    assert sel["prompt"]["composition"]["center"] == ["모"] and "아버지" not in sel["prompt"]["text"]
    rows = by_source(sel)
    assert "possible_participant_omitted" in rows[("candidate", 0)]["blocking"]
    assert rows[("candidate", 1)]["accepted"] and not rows[("candidate", 1)]["represent"]["represents"]
    assert sel["choice_reason"].startswith("선택")


def test_background_only_candidate_loses_to_a_central_object_even_if_marked_main():
    kitchen = cand5(5, "부엌", [el5("s1", "place", "부엌", 5, "겨울에는 부엌에 연탄을 쌓아 두었어요", role="setting")], importance="main")
    briquette = cand5(5, "연탄", [el5("o1", "object", "연탄", 5, "부엌에 연탄을 쌓아 두었어요"),
                                  el5("s1", "place", "부엌", 5, "부엌에 연탄을 쌓아 두었어요", role="setting")], importance="minor")
    sel = choose(seed(), "c05", [kitchen, briquette])
    assert (sel["candidate_index"], sel["source"]) == (1, "candidate")              # 모델의 main 표시가 아니라 담은 것으로 고른다
    assert by_source(sel)[("candidate", 0)]["importance_from_model"] == "main"
    assert "- 배경: 부엌 — 중심 소재 뒤에 옅게" in sel["prompt"]["scene_block"]


def test_only_background_offered_fails_instead_of_filling_the_slot():
    kitchen = cand5(5, "부엌", [el5("s1", "place", "부엌", 5, "겨울에는 부엌에 연탄을 쌓아 두었어요", role="setting")])
    sel = choose(seed(), "c05", [kitchen])
    assert (sel["status"], sel["reasons"]) == ("failed", ["no_representative_candidate"])
    assert "빈칸을 채우지 않는다" in sel["detail"] and by_source(sel)[("candidate", 0)]["accepted"] is True
    # 모델이 중심 내용을 적어 두었으면 그것이 무엇인지 실패 사유에 남긴다
    sel = choose(seed(), "c05", [kitchen], focus={"summary": "연탄", "core": [
        {"kind": "object", "text": "연탄집게", "turn": 5, "quote": "연탄집게로 연탄을 갈았어요"}], "background": []})
    assert sel["status"] == "failed" and "연탄집게" in sel["detail"]


def test_metaphorical_title_does_not_create_an_object():
    d = seed()
    chapter(d, "c08")["title"] = "마음의 등불"
    lamp = cand5(8, "등불", [el5("o1", "object", "등불", 8, "마음의 등불")])            # 제목에서 만든 사물 — 원문에 없다
    radio = cand5(8, "라디오", [el5("o1", "object", "라디오", 8, "안방에서 라디오를 틀었어요")])
    sel = choose(d, "c08", [lamp, radio], focus={"summary": "x", "core": [
        {"kind": "object", "text": "등불", "turn": 8, "quote": "마음의 등불"}]})
    assert sel["prompt"]["composition"]["center"] == ["라디오"] and "등불" not in sel["prompt"]["text"]
    assert by_source(sel)[("candidate", 0)]["accepted"] is False
    assert sel["focus"]["model_focus"]["core"][0]["verified"] is False and "등불" not in sel["focus"]["core"]
    assert choose(d, "c08", [lamp])["status"] == "failed"


def test_negated_object_is_never_the_center():
    d = seed()
    d["source"]["utterances"][1]["elder"] = "뒤꼍에 장독대는 없었어요. 큰 장독은 부엌 옆에 두었어요."
    chapter(d, "c02")["paragraphs"] = [{"sentences": [{"text": "뒤꼍에 장독대는 없었다.", "turns": [2]}]},
                                       {"sentences": [{"text": "큰 장독은 부엌 옆에 두었다.", "turns": [2]}]}]
    platform = cand5(2, "장독대", [el5("o1", "object", "장독대", 2, "뒤꼍에 장독대는 없었어요")])
    jar = cand5(2, "장독", [el5("o1", "object", "장독", 2, "큰 장독은 부엌 옆에 두었어요")])
    focus = {"summary": "장독대", "core": [{"kind": "object", "text": "장독대", "turn": 2, "quote": "뒤꼍에 장독대는 없었어요"}]}
    sel = choose(d, "c02", [platform, jar], focus=focus)
    assert sel["prompt"]["composition"]["center"] == ["장독"] and "장독대" not in sel["prompt"]["text"]
    assert by_source(sel)[("candidate", 0)]["accepted"] is False
    assert sel["focus"]["model_focus"]["core"][0]["status"] == "blocked"           # 부정된 것을 중심으로 받지 않는다
    assert choose(d, "c02", [platform])["status"] == "failed"


def test_thin_quote_does_not_prove_who_did_it():
    """「제가 아버지랑」 은 사람은 가리키지만 행동을 받치지 않는다 — 문장 전체를 인용하면 받친다."""
    thin = choose(seed(), "c03", [planting(me_evidence="제가 아버지랑")])
    rows = by_source(thin)
    assert "person_relation_evidence_thin" in rows[("candidate", 0)]["blocking"]
    assert thin["source"] == "derived_symbolic" and "- 인물: 그리지 않는다" in thin["prompt"]["scene_block"]
    full = choose(seed(), "c03", [planting()])
    assert (full["mode"], full["source"]) == ("SCENE", "candidate")
    assert [p["evidence_thin"] for p in full["auto_checks"]["people"]] == [False, False]
    assert "- 중심 소재: 모 — 화면의 중심에" in full["prompt"]["scene_block"]
    assert "(인물 칸의 사람들이 함께 한다)" in full["prompt"]["scene_block"]
    # 사람을 가리키는 낱말 하나(2자)는 인용으로도 받지 않는다 (원문 대조 최소 길이)
    tiny = choose(seed(), "c03", [planting(me_evidence="제가")])
    assert "person_relation_evidence_not_found" in by_source(tiny)[("candidate", 0)]["blocking"]


def test_scene_keeps_the_age_and_symbolic_drops_it():
    d = seed()
    d["source"]["utterances"][2]["elder"] = "봄이면 온 식구가 논에 나갔어요. 제가 열 살쯤 아버지랑 둘이서 모를 논에 심었어요."
    quote = "제가 열 살쯤 아버지랑 둘이서 모를 논에 심었어요"
    c = planting(me_evidence=quote)
    for e in c["elements"]:
        if e["key"] in ("a1", "p1"):
            e["quote"] = quote
        if e["key"] == "p2":
            e["relation"]["evidence"][0]["quote"] = quote
    c["elements"].append(el5("t1", "time", "열 살쯤", 3, "제가 열 살쯤"))
    scene = choose(d, "c03", [c])
    assert scene["mode"] == "SCENE" and "- 때: 열 살쯤" in scene["prompt"]["scene_block"]
    c["elements"] = [e for e in c["elements"] if e["key"] != "p2"]                 # 아버지를 빼면 막히고, 사람을 뺀 그림에서 나이도 빠진다
    sym_ = choose(d, "c03", [c])
    assert sym_["source"] == "derived_symbolic" and "열 살쯤" not in sym_["prompt"]["scene_block"]
    assert sym_["scene"]["dropped_for_picture"] == [{"kind": "time", "text": "열 살쯤", "why": "사람을 그리지 않는 그림이라 나이는 그림과 관계없다"}]


def test_composition_is_recorded_apart_from_facts():
    sel = choose(seed(), "c05", [cand5(5, "연탄", [el5("o1", "object", "연탄", 5, "부엌에 연탄을 쌓아 두었어요"),
                                                    el5("o2", "object", "연탄집게", 5, "연탄집게로 연탄을 갈았어요"),
                                                    el5("s1", "place", "부엌", 5, "부엌에 연탄을 쌓아 두었어요", role="setting")])])
    comp = sel["prompt"]["composition"]
    assert comp["center"] == ["연탄", "연탄집게"] and comp["background"] == ["부엌"]
    assert [f["text"] for f in comp["facts"]] == ["연탄", "연탄집게", "부엌"] and all(f["quote"] for f in comp["facts"])
    assert any("보조로만" in c for c in comp["choices"])
    assert "- 그 밖의 사물: " + il.FOCUS_OTHER_THINGS in sel["prompt"]["scene_block"]


def test_select_prompt_is_v5_and_older_versions_are_kept():
    text = book.select_prompt()
    assert book.SELECT_FILE == "1_장면선정_v5_목차중심.md"
    for v in ("1_장면선정_v1.md", "1_장면선정_v2.md", "1_장면선정_v3.md", "1_장면선정_v4_목차대표.md"):
        assert (il.PROMPTS / v).is_file()
    for must in ('"focus"', "core", "background", "배경만 남긴 후보는 대안이 되지 않습니다", "요소 이름 한 낱말만 옮기지 않습니다",
                 "「제가」 처럼 사람을 가리키는 낱말 하나만으로는 근거가 되지 않습니다", "한 문장을 통째로 옮겨도 됩니다",
                 "제목이 비유이면"):
        assert must in text


# ---------------------------------------------------------------- 모델의 focus 는 제안이다 — 혼자서는 배경을 중심으로 올리지 못한다

def item(sel, text) -> dict:
    return next(v for v in sel["focus"]["items"] if v["text"] == text)


def seaside(title: str = "바닷가 마을") -> dict:
    """[합성] 풍경 자체가 주제인 항목 — 6번 항목을 바꿨다. 본문 세 문장 모두 바닷가를 이야기한다(1인칭 화자도 나온다)."""
    d = seed()
    c = chapter(d, "c06")
    c.update(title=title, photos=[])
    c["paragraphs"] = [{"sentences": [{"text": t, "turns": [6]}]} for t in
                       ("우리 마을은 바닷가에 있었다.", "나는 바닷가 모래밭을 자주 걸었다.", "저녁이면 바닷가가 붉게 물들었다.")]
    d["source"]["utterances"][5]["elder"] = ("우리 마을은 바닷가에 있었어요. 저는 바닷가 모래밭을 자주 걸었어요. "
                                            "저녁이면 바닷가가 붉게 물들었어요.")
    return d


SEA = cand5(6, "바닷가", [el5("s1", "place", "바닷가", 6, "우리 마을은 바닷가에 있었어요", role="setting")])
SEA_FOCUS = {"summary": "바닷가 마을", "core": [{"kind": "place", "text": "바닷가", "turn": 6, "quote": "저녁이면 바닷가가 붉게 물들었어요"},
                                              {"kind": "person", "text": "나", "turn": 6, "quote": "저는 바닷가 모래밭을 자주 걸었어요"}],
             "background": [{"kind": "object", "text": "모래밭", "turn": 6, "quote": "바닷가 모래밭을 자주 걸었어요"}]}


def test_landscape_theme_is_chosen_with_the_chapters_own_evidence():
    sel = choose(seaside(), "c06", [SEA])                                               # 제목 + 본문 비율 — 모델 focus 없이도
    assert sel["status"] == "selected" and sel["prompt"]["composition"]["landscape"] is True
    assert "- 중심 소재: 바닷가 — 풍경 자체가 이 그림의 주제다" in sel["prompt"]["scene_block"]
    sea = item(sel, "바닷가")
    assert sea["tier"] == "core" and set(sea["why"]) == {"title", "body_share"} and sea["body_share"] == 1.0


def test_landscape_theme_with_a_metaphorical_title_needs_a_second_signal():
    """제목이 장소를 말하지 않으면 — 본문 비율(목차 근거)에 모델 focus(인용 대조)가 더해져야 한다. 화자는 비교 대상이 아니다."""
    d = seaside("그해 저녁")
    sel = choose(d, "c06", [SEA], focus=SEA_FOCUS)
    assert sel["status"] == "selected" and set(item(sel, "바닷가")["why"]) == {"body_share", "model_focus_core"}
    assert [r["text"] for r in sel["focus"]["rivals"]] == ["모래밭"]                       # 「나」 는 넣지 않았다 · 모래밭은 1/3
    assert choose(d, "c06", [SEA])["status"] == "failed"                                # 본문 비율 하나뿐이면 중심이 아니다


def test_place_beside_a_more_prominent_object_is_not_the_center_even_if_the_model_says_so():
    """
    두 문장짜리 8번 항목 — 안방은 한 문장(절반), 라디오는 두 문장 모두에 나온다. 모델이 안방을 중심이라 적고 라디오를 배경이라 적어도,
    목차 근거로는 라디오가 더 강하다 — 안방만 그린 그림은 대표가 아니다.

    기준 변경 (2026-11-16 보완 3): 앞선 판은 「본문 비율」 신호에 두 문장 이상을 요구해, 제목이 「안방」 이고 모델이 중심이라 적으면 골랐다.
    짧은 글의 풍경이 한 번만 나왔다는 이유로 떨어지지 않게 두 문장 조건을 뺐고, 대신 제목의 장소도 본문 비율이 더 높은
    사물 · 행동 · 인물과 견준다 — 그래서 이 경우는 이제 실패다.
    """
    d = seed()
    chapter(d, "c08")["title"] = "저녁의 소리"
    room = cand5(8, "안방", [el5("s1", "place", "안방", 8, "저녁이면 안방에서 라디오를 틀었어요", role="setting")])
    focus = {"summary": "안방", "core": [{"kind": "place", "text": "안방", "turn": 8, "quote": "안방에서 라디오를 틀었어요"}],
             "background": [{"kind": "object", "text": "라디오", "turn": 8, "quote": "라디오에서 연속극이 나왔어요"}]}
    sel = choose(d, "c08", [room], focus=focus)
    assert sel["status"] == "failed" and item(sel, "안방")["model_proposed"] == "core" and item(sel, "안방")["tier"] == "background"
    assert "본문 비율이 더 높은 라디오" in item(sel, "안방")["rule"] and "라디오" in sel["detail"]
    chapter(d, "c08")["title"] = "안방"                                                  # 제목 + 모델 focus 여도 — 라디오가 더 강하다
    assert choose(d, "c08", [room], focus=focus)["status"] == "failed"
    fake = dict(focus, core=[{"kind": "place", "text": "안방", "turn": 8, "quote": "안방에 등잔불이 켜져 있었어요"}])
    assert item(choose(d, "c08", [room], focus=fake), "안방")["model_proposed"] is None   # 원문에 없는 인용은 신호가 아니다
    # [한계] 후보에도 모델 focus 에도 라디오가 없으면 코드는 라디오를 모른다 — 제목 + 본문 절반으로 안방을 중심으로 본다
    assert choose(d, "c08", [room])["status"] == "selected"


def test_title_place_still_competes_fairly_with_objects():
    """제목에 장소와 사물이 다 있는 항목 — 둘 다 중심이고, 더 많이 담은 그림이 이긴다."""
    d = seed()
    chapter(d, "c10")["title"] = "텃밭과 호미"
    plot = cand5(10, "텃밭", [el5("s1", "place", "텃밭", 10, "집 뒤 텃밭에 상추를 심었어요", role="setting")])
    hoe = cand5(10, "호미", [el5("o1", "object", "호미", 10, "호미로 풀을 매 주었어요"),
                             el5("s1", "place", "텃밭", 10, "집 뒤 텃밭에 상추를 심었어요", role="setting")])
    sel = choose(d, "c10", [plot, hoe], focus={"summary": "텃밭", "core": [{"kind": "place", "text": "텃밭", "turn": 10,
                                                                          "quote": "집 뒤 텃밭에 상추를 심었어요"}]})
    assert item(sel, "텃밭")["tier"] == "core" and sel["candidate_index"] == 1
