"""
자서전 삽화 장면 선정 (memoir_illust · 로컬 실험)

    python -m pytest tests/test_memoir_illust.py -q

모델을 부르지 않는다 — run 의 call 자리에 모의 응답을 끼운다. 자료는 합성(eval/illust_seed_A.json)이다.
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_illust as il     # noqa: E402
from tools import memoir_illust as tool         # noqa: E402

SEED = json.loads((ROOT / "eval" / "illust_seed_A.json").read_text(encoding="utf-8"))
MOCK = json.loads((ROOT / "eval" / "illust_mock_A.json").read_text(encoding="utf-8"))


def seed() -> dict:
    return copy.deepcopy(SEED)


def cand(elements, chapter_no=1, title="장면", importance="main") -> dict:
    return {"chapter_no": chapter_no, "scene_title": title, "scene_summary": "요약", "importance": importance,
            "reason": "까닭", "elements": [dict(zip(("kind", "text", "turn", "quote"), e)) for e in elements]}


TEST_REVIEWER = "시험용 확인(사람 아님)"


def raw_run(data, cands, confirmations=None) -> dict:
    """확인 기록 없이(또는 준 것만으로) 돌린다 — 사람이 아무것도 확인하지 않은 실제 상태."""
    reply = json.dumps({"candidates": cands}, ensure_ascii=False)
    return il.run(data, call=lambda system, user: reply, confirmations=confirmations)


def scene_ids(result) -> dict:
    return {s["participants_review"]["scene_review_id"]: "complete" for s in result["scenes"]}


def run(data, cands) -> dict:
    """
    대부분의 시험은 사진 · 겹침 · 인용 같은 다른 규칙을 본다. 그래서 「빠진 참여자가 없다」 는 장면 단위 확인만
    시험용으로 미리 넣고 돌린다 (인물별 관계 확인은 넣지 않는다). 확인이 없는 상태는 raw_run 으로 본다.
    """
    first = raw_run(data, cands)
    return raw_run(data, cands, {"reviewer": TEST_REVIEWER, "relations": {}, "scenes": scene_ids(first)})


def one(data, elements, **kw) -> dict:
    return run(data, [cand(elements, **kw)])["scenes"][0]


def confirmed_run(data, cands, verdict="confirmed") -> dict:
    """인물별 관계와 장면 단위(빠진 참여자 없음)를 모두 시험용으로 확인해 돌린다."""
    first = raw_run(data, cands)
    ids = {r["relation_id"]: verdict for s in first["scenes"] for r in s["people_review"]}
    return raw_run(data, cands, {"reviewer": TEST_REVIEWER, "relations": ids, "scenes": scene_ids(first)})


def one_confirmed(data, elements, **kw) -> dict:
    return confirmed_run(data, [cand(elements, **kw)])["scenes"][0]


OPEN = "- 인물(행동과의 관계를 사람이 확인하기 전 — 생성에 쓰지 않는다): "

APPLE = [("action", "사과 궤짝을 리어카에 싣고 장터까지 끌고 간다", 2, "형이랑 둘이서 사과 궤짝을 리어카에 싣고 장터까지 끌고 갔어요"),
         ("object", "사과 궤짝", 2, "사과 궤짝을 리어카에 싣고"),
         ("place", "장터", 2, "장터까지 끌고 갔어요")]
SPOON = [("object", "놋숟가락", 7, "할머니가 쓰시던 놋숟가락이 아직 있어요")]


@pytest.fixture(scope="module")
def full() -> dict:
    return il.run(seed(), call=lambda s, u: json.dumps(MOCK, ensure_ascii=False))


def by_title(result: dict, title: str) -> dict:
    return next(s for s in result["scenes"] if s["scene_title"] == title)


# ---------------------------------------------------------------- 입력

@pytest.mark.parametrize("break_it", [
    lambda d: d.update(schema_version="x"),
    lambda d: d["memoir"].update(chapters=[]),
    lambda d: d["memoir"]["chapters"][0].update(paragraphs="글"),
    lambda d: d["source"]["utterances"].pop(3),                                   # 턴이 1부터 차례가 아니다
    lambda d: d["source"]["turn_map"][0].update(session_id="s-z"),
    lambda d: d["memoir"]["chapters"][0]["paragraphs"][0]["sentences"][0].update(turns=[99]),
    lambda d: d["photos"][0].update(photo_id=3),
    lambda d: d["photos"][0].update(turns=[99]),
])
def test_bad_input_is_refused(break_it):
    d = seed()
    break_it(d)
    with pytest.raises(il.IllustError) as e:
        il.check_input(d)
    assert e.value.kind == "input"


def test_input_is_not_an_object():
    with pytest.raises(il.IllustError):
        il.check_input([1, 2])


def test_pipeline_shape_is_accepted():
    """파이프라인 결과 모양 — chapter_key · title 이 객체 · 문단이 문장 목록."""
    d = seed()
    d["memoir"]["chapters"] = [{"chapter_key": "ch-1", "title": {"text": "사과 궤짝", "kind": "editorial"},
                                "paragraphs": [[{"text": "가을이면 장터에 갔다.", "kind": "supported", "facts": ["f1"], "turns": [2]}]]}]
    s = one(d, APPLE)
    assert (s["chapter_key"], s["chapter_no"], s["verification"]) == ("ch-1", 1, "verified")


@pytest.mark.parametrize("reply", [
    "글입니다", "[]", '{"scenes": []}',
    json.dumps({"candidates": [{"chapter_no": "1"}]}),
    json.dumps({"candidates": [cand(APPLE) | {"importance": "big"}]}, ensure_ascii=False),
    json.dumps({"candidates": [cand([("weather", "눈", 2, "눈이 왔어요")])]}, ensure_ascii=False),
    json.dumps({"candidates": [cand(APPLE) | {"scene_title": "가" * 41}]}, ensure_ascii=False),
])
def test_bad_model_output_is_refused(reply):
    with pytest.raises(il.IllustError) as e:
        il.run(seed(), call=lambda s, u: reply)
    assert e.value.kind == "model_output"


def test_real_model_call_is_not_available():
    with pytest.raises(il.IllustError) as e:
        il.run(seed())
    assert e.value.kind == "not_approved"


# ---------------------------------------------------------------- 원문 대조

def test_verified_scene_is_ready_with_sources():
    s = one(seed(), APPLE)
    assert (s["visual_mode"], s["verification"], s["decision"]) == ("SCENE", "verified", "eligible")
    assert s["generation"]["candidate"] == "eligible" and s["experience_basis"] == "direct"
    assert s["source_turns"] == [2]
    assert s["source_refs"] == [{"turn": 2, "session_id": "s-a", "session_turn": 2}]
    assert s["has_real_photo"] is False and s["generation_prompt"] and s["draft_prompt"] is None


def test_fabricated_quote_is_rejected_and_scene_goes_to_review():
    s = one(seed(), APPLE + [("person", "어머니", 3, "어머니가 손을 흔들어 주셨어요")])
    e = s["elements"][-1]
    assert (e["status"], e["flags"]) == ("rejected", ["quote_not_in_source"])
    assert (s["verification"], s["decision"], s["generation_prompt"]) == ("partial", "review", None)
    assert "어머니" not in s["draft_prompt"]["scene_block"]


def test_quote_from_another_turn_is_rejected():
    s = one(seed(), [("object", "놋숟가락", 2, "할머니가 쓰시던 놋숟가락이 아직 있어요")], chapter_no=2)
    assert s["elements"][0]["status"] == "rejected" and s["decision"] == "skip"
    assert (s["verification"], s["decision_reasons"]) == ("unverified", ["no_evidence"])


def test_unknown_turn_and_short_quote_are_rejected():
    s = one(seed(), [("object", "놋숟가락", 99, "놋숟가락이 아직 있어요"), ("object", "형", 2, "형")])
    assert [e["flags"] for e in s["elements"]] == [["turn_missing"], ["quote_not_in_source"]]


def test_negated_thing_is_not_drawn():
    """「장화는 없었어요」 — 인용은 맞지만 장화를 그리면 안 된다."""
    s = one(seed(), [("object", "장화", 4, "장화는 없었어요"), ("object", "고무신", 4, "고무신 신고 다녔지요")])
    boots, shoes = s["elements"]
    assert (boots["status"], boots["flags"]) == ("blocked", ["negation_in_source"])
    assert shoes["status"] == "quoted"
    assert (s["visual_mode"], s["verification"], s["decision"]) == ("SYMBOLIC", "partial", "review")
    assert "장화" not in s["draft_prompt"]["scene_block"] and "고무신" in s["draft_prompt"]["scene_block"]


def test_hearsay_is_kept_for_review_not_dropped():
    """남에게 들은 이야기 — 버리지 않되 후보로 확정하지도 않는다. 직접 겪은 것과 구분해 적는다."""
    s = one(seed(), [("object", "소", 6, "예전엔 소도 팔았대요"), ("place", "장터", 6, "장터 얘기는 형한테 들었는데")])
    assert all("hearsay" in e["flags"] for e in s["elements"])
    assert (s["visual_mode"], s["verification"], s["decision"]) == ("SYMBOLIC", "partial", "review")
    assert s["decision_reasons"] == ["verification_partial", "hearsay"] and s["experience_basis"] == "hearsay"
    assert s["checks"]["hearsay"] == {"state": "found", "elements": ["e1", "e2"], "nearby": []}
    assert s["generation_prompt"] is None and s["draft_prompt"] and s["generation"]["review_required"] is True


def test_direct_and_hearsay_mixed_is_marked():
    s = one(seed(), APPLE + [("object", "소", 6, "예전엔 소도 팔았대요")])
    assert (s["experience_basis"], s["decision"]) == ("mixed", "review") and "hearsay" in s["decision_reasons"]


def test_renamed_element_is_paraphrased_not_verified():
    """인용은 원문에 있어도 이름을 바꿔 달면(리어카 → 손수레) 확인된 요소가 아니다."""
    s = one(seed(), APPLE + [("object", "낡은 손수레", 2, "사과 궤짝을 리어카에 싣고")])
    assert s["elements"][-1]["status"] == "paraphrased"
    assert s["verification"] == "partial" and "손수레" not in s["draft_prompt"]["text"]


def test_uncertain_time_is_kept_as_said():
    s = one(seed(), APPLE + [("time", "열 살쯤", 2, "내가 열 살쯤이었나")])
    assert s["verification"] == "verified" and "- 때: 열 살쯤" in s["generation_prompt"]["scene_block"]


def test_turn_outside_the_chapter_is_partial():
    s = one(seed(), SPOON, chapter_no=1)
    assert (s["memoir_link"], s["verification"], s["decision"]) == ("outside_chapter", "partial", "review")


def test_memoir_without_turns_is_partial():
    """소설체처럼 문장에 출처 턴이 없으면 원문 인용이 맞아도 자동 생성 대상이 아니다."""
    d = seed()
    for ch in d["memoir"]["chapters"]:
        for p in ch["paragraphs"]:
            for x in p["sentences"]:
                x["turns"] = []
    s = one(d, APPLE)
    assert (s["memoir_link"], s["verification"], s["decision"]) == ("chapter_has_no_turns", "partial", "review")


def test_no_source_means_unverified_and_no_prompt():
    d = seed()
    d["source"] = None
    r = run(d, [cand(APPLE)])
    s = r["scenes"][0]
    assert r["source_state"] == "missing"
    assert (s["verification"], s["decision"], s["memoir_link"]) == ("unverified", "review", "no_source")
    assert s["generation_prompt"] is None and s["draft_prompt"] is None and s["source_turns"] == [2]
    assert all(e["status"] == "unchecked" for e in s["elements"])


def test_unknown_chapter_is_skipped_not_invented():
    s = one(seed(), APPLE, chapter_no=9)
    assert (s["decision"], s["chapter_key"], s["chapter_title"]) == ("skip", None, None)
    assert "unknown_chapter" in s["decision_reasons"]


# ---------------------------------------------------------------- 방식

def test_object_only_is_symbolic_without_people():
    d = seed()
    d["photos"] = []
    s = one(d, SPOON + [("person", "할머니", 7, "할머니가 쓰시던")], chapter_no=2)
    assert (s["visual_mode"], s["decision"]) == ("SYMBOLIC", "eligible")
    assert "- 인물: 그리지 않는다" in s["generation_prompt"]["scene_block"]
    assert "할머니" not in s["generation_prompt"]["scene_block"]


def test_emotion_alone_is_skipped():
    s = one(seed(), [("emotion", "서러웠다", 5, "그때는 참 서러웠어요")])
    assert (s["visual_mode"], s["decision_reasons"]) == ("SKIP", ["no_visual_basis"])


def test_sensitive_memory_is_skipped():
    s = one(seed(), [("place", "병원", 13, "병원에 오래 계셨어요"), ("action", "병원에 오래 계셨다", 13, "병원에 오래 계셨어요")], chapter_no=3)
    assert (s["decision"], s["visual_mode"], s["mode_if_released"]) == ("held", "SKIP", "SCENE")
    assert s["decision_reasons"] == ["sensitive"] and "병원" in s["checks"]["sensitive"]["words"]
    assert s["generation"] == {"candidate": "held", "review_required": True, "user_selected": False,
                               "image_status": "not_requested", "user_approved": False}
    assert s["generation_prompt"] is None and s["draft_prompt"] is None      # 보류 중에는 지시문도 만들지 않는다
    assert any("보류" in n for n in s["risk_notes"])


def test_held_scene_does_not_take_a_slot():
    d = seed()
    d["photos"] = []
    r = run(d, [cand([("place", "병원", 13, "병원에 오래 계셨어요")], chapter_no=3, title="보류"),
                cand(APPLE, title="가"), cand(SPOON, chapter_no=2, title="나"),
                cand([("object", "고무신", 4, "고무신 신고 다녔지요")], title="다")])
    assert [s["decision"] for s in r["scenes"]] == ["held", "eligible", "eligible", "eligible"]


# ---------------------------------------------------------------- 사진

GRAD = [("action", "교문 앞에서 어머니랑 찍었다", 9, "교문 앞에서 어머니랑 사진을 찍었어요"), ("place", "교문 앞", 9, "졸업식 날 교문 앞에서")]


def test_scene_with_linked_photo_is_skipped():
    s = one(seed(), GRAD, chapter_no=2)
    assert (s["has_real_photo"], s["decision"], s["decision_reasons"]) == (True, "skip", ["real_photo"])
    assert s["photo_check"]["photos"] == [{"photo_id": "ph-1", "relation": "confirmed", "why": "linked_turns"}]


def test_same_session_photo_alone_is_review_not_skip():
    d = seed()
    d["photos"] = [{"photo_id": "ph-9", "session_id": "s-a", "clues": {"scene": "마당", "objects": ["빨랫줄"]}}]
    s = one(d, APPLE)
    assert (s["visual_mode"], s["has_real_photo"], s["decision"]) == ("SCENE", None, "review")
    assert s["decision_reasons"] == ["photo_same_session"] and s["generation_prompt"] is None and s["draft_prompt"]


def test_photo_clue_overlap_is_review():
    d = seed()
    d["photos"] = [{"photo_id": "ph-9", "session_id": "s-a", "clues": {"scene": "흙길", "objects": ["나무 리어카"]}}]
    s = one(d, APPLE + [("object", "리어카", 2, "사과 궤짝을 리어카에 싣고")])
    assert s["photo_check"]["state"] == "possible_overlap" and s["decision"] == "review"
    assert s["photo_check"]["photos"][0]["why"] == "clue_words:리어카"


def test_photo_linked_elsewhere_or_other_session_does_not_block():
    """ph-1 은 사람이 9턴에 이은 사진, ph-2 는 다른 회차 — 7턴의 놋숟가락과 상관없다."""
    s = one(seed(), SPOON, chapter_no=2)
    assert (s["photo_check"]["state"], s["has_real_photo"], s["decision"]) == ("none", False, "eligible")


def test_photos_not_provided_is_review():
    d = seed()
    d["photos"] = None
    r = run(d, [cand(APPLE)])
    assert r["photos_state"] == "not_provided"
    assert (r["scenes"][0]["has_real_photo"], r["scenes"][0]["decision_reasons"]) == (None, ["photo_not_provided"])


# ---------------------------------------------------------------- 고르기

def test_zero_candidates_is_a_normal_result():
    r = run(seed(), [])
    assert r["scenes"] == [] and r["summary"]["candidates"] == 0 and r["images_generated"] is False
    assert r["summary"]["decision"] == {"eligible": 0, "review": 0, "held": 0, "not_selected": 0, "skip": 0}


def test_duplicate_scene_is_skipped():
    r = run(seed(), [cand(APPLE, title="하나"), cand(APPLE[:2], title="둘")])
    assert [s["decision"] for s in r["scenes"]] == ["eligible", "skip"]
    assert r["scenes"][1]["decision_reasons"] == ["duplicate"]


def test_at_most_three_and_spread_over_chapters():
    # 이 한도(MAX_SCENES)는 앞선 검토 흐름(책 전체에서 몇 장면을 추천해 사람이 고른다)의 것이다. 2026-11-15 제품 동작이
    # 「사진 없는 목차마다 한 장」 으로 바뀌어 새 흐름(memoir_illust_book)은 이 한도를 쓰지 않는다 — 그쪽 시험은
    # tests/test_memoir_illust_book.py 에 있다. 이 시험은 검토용 실행기가 여전히 쓰는 옛 동작을 고정한다.
    d = seed()
    d["photos"] = []
    r = run(d, [cand(APPLE, title="가"),
                cand([("action", "형이 앞에서 끌고 나는 뒤에서 민다", 3, "형이 앞에서 끌고 나는 뒤에서 밀었지요"),
                      ("object", "리어카", 3, "리어카가 자꾸 기울었어요")], title="나"),
                cand([("object", "고무신", 4, "고무신 신고 다녔지요")], title="다", importance="minor"),
                cand(SPOON, chapter_no=2, title="라", importance="minor"),
                cand([("action", "기차를 타고 서울로 올라간다", 11, "스무 살에 기차 타고 서울로 올라갔어요"),
                      ("object", "기차", 11, "기차 타고 서울로")], chapter_no=3, title="마", importance="minor")])
    picked = [s["scene_title"] for s in r["scenes"] if s["decision"] in ("eligible", "review")]
    assert picked == ["가", "라", "마"]                       # 장마다 하나씩 — 1장의 「나」 가 주요여도 밀린다
    rest = [s for s in r["scenes"] if s["scene_title"] in ("나", "다")]
    assert all(s["decision"] == "not_selected" and s["generation_prompt"] is None for s in rest)
    assert r["summary"]["decision"] == {"eligible": 3, "review": 0, "held": 0, "not_selected": 2, "skip": 0}


# ---------------------------------------------------------------- 그림 지시문

def test_prompt_is_built_only_from_verified_elements_and_fixed_style():
    s = one_confirmed(seed(), APPLE + [("person", "형", 2, "형이랑 둘이서")])
    p = s["generation_prompt"]
    blocks = il.style_blocks()
    assert p["style_id"] == "watercolor-recall-v1" and all(b in p["text"] for b in blocks.values())
    assert "- 인물: 형" in p["scene_block"] and "- 배경: 장터" in p["scene_block"]
    assert "요약" not in p["text"] and "까닭" not in p["text"]          # 모델이 쓴 문장은 들어가지 않는다
    assert p["elements_used"] == ["e1", "e2", "e3", "e4"] and s["prompt_checks"] == []


def test_narrator_is_named_as_self_without_age_or_looks():
    s = one(seed(), APPLE + [("person", "형", 2, "형이랑 둘이서"), ("person", "나", 3, "나는 뒤에서 밀었지요"),
                             ("action", "형이 앞에서 끌고 나는 뒤에서 민다", 3, "형이 앞에서 끌고 나는 뒤에서 밀었지요")])
    assert OPEN + f"형, {il.SELF_LABEL}" in s["draft_prompt"]["scene_block"]
    assert "central_action_missing" in s["decision_reasons"]             # 행동이 둘이다 — 무엇을 그릴지 정하지 않았다


def test_prompt_says_unknown_place_and_time_are_not_to_be_fixed():
    d = seed()
    d["photos"] = []
    p = one(d, SPOON, chapter_no=2)["generation_prompt"]["scene_block"]
    assert "- 배경: 특정하지 않는다" in p and "- 때: 특정하지 않는다" in p


def test_check_prompt_catches_tampering():
    els = [{"id": "e1", "kind": "object", "text": "놋숟가락", "turn": 7, "quote": "놋숟가락이 아직 있어요", "status": "quoted", "flags": []}]
    p = il.build_prompt("SYMBOLIC", els)
    assert il.check_prompt(p, "SYMBOLIC", els) == []
    p2 = dict(p, scene_block=p["scene_block"] + "\n- 때: 1962년 겨울")
    assert "number_not_in_source" in il.check_prompt(p2, "SYMBOLIC", els)
    assert "style_block_missing" in il.check_prompt(dict(p, text=p["scene_block"]), "SYMBOLIC", els)
    assert "scene_without_action" in il.check_prompt(p, "SCENE", els)
    assert "unverified_element_used" in il.check_prompt(p, "SYMBOLIC", [dict(els[0], status="paraphrased")])


def test_label_that_claims_a_photo_or_likeness_is_blocked():
    s = one(seed(), SPOON + [("object", "할머니 초상", 7, "할머니가 쓰시던 놋숟가락이")], chapter_no=2)
    assert s["elements"][-1]["flags"] == ["banned_label"] and "초상" not in s["draft_prompt"]["scene_block"]


# ---------------------------------------------------------------- 전체 · 구조 · 독립성

def test_full_mock_run(full):
    got = {s["scene_title"]: (s["visual_mode"], s["verification"], s["decision"]) for s in full["scenes"]}
    assert got == {
        "사과 궤짝을 싣고 장터로": ("SCENE", "verified", "review"),     # 인물 관계를 사람이 확인하기 전 · 행동이 둘
        "기우는 리어카": ("SKIP", "verified", "skip"),
        "장화와 고무신": ("SYMBOLIC", "partial", "not_selected"),      # 검토 대상이지만 3개 한도 · 장 균형에서 밀린다
        "서러웠던 마음": ("SKIP", "verified", "skip"),
        "소를 팔던 장터": ("SYMBOLIC", "partial", "not_selected"),    # 전언 — 검토 대상이지만 한도에서 밀린다
        "찬장 위의 놋숟가락": ("SYMBOLIC", "verified", "eligible"),
        "졸업식 날 교문 앞": ("SKIP", "partial", "skip"),
        "서울로 가던 날": ("SCENE", "partial", "review"),
        "아버지의 병실": ("SKIP", "verified", "held"),                # 민감 — 자동 보류, 사람이 풀 수 있다
    }
    seoul = by_title(full, "서울로 가던 날")
    assert seoul["decision_reasons"] == ["verification_partial", "summary_person_not_in_elements",
                                         "participants_completeness_not_human_confirmed",   # 이 묶음은 확인 없이 돌린다
                                         "photo_possible_overlap"]       # 요약의 「어머니」 가 요소에 없다(지어낸 인용이라 버려졌다)
    assert "눈" not in seoul["draft_prompt"]["scene_block"] and "어머니" not in seoul["draft_prompt"]["scene_block"]
    assert sum(1 for s in full["scenes"] if s["decision"] in ("eligible", "review")) <= il.MAX_SCENES
    assert full["model"] == {"source": "mock", "calls": 1} and full["images_generated"] is False


def test_only_verified_scenes_get_a_generation_prompt(full):
    for s in full["scenes"]:
        assert (s["generation_prompt"] is not None) == (s["decision"] == "eligible")
        if s["decision"] == "eligible":
            assert s["verification"] == "verified" and s["has_real_photo"] is False


def test_nothing_is_selected_generated_or_approved(full):
    """후보로 적합하다는 것이 만들라는 뜻이 아니다 — 사용자 선택 · 생성 · 승인은 모두 「아직」 이다."""
    assert full["images_generated"] is False and full["image_api_called"] is False
    for s in full["scenes"]:
        g = s["generation"]
        assert "auto_generate" not in s
        assert (g["user_selected"], g["image_status"], g["user_approved"]) == (False, "not_requested", False)
        assert g["candidate"] == il.CANDIDATE[s["decision"]]
        assert g["review_required"] == (s["decision"] in ("review", "held"))


# ---------------------------------------------------------------- 항목별 검증 (인용 일치 ≠ 사실 검증)

def test_checks_separate_quote_match_from_meaning(full):
    s = by_title(full, "사과 궤짝을 싣고 장터로")
    c = s["checks"]
    assert s["verification"] == "verified" and "사실 검증이 아니다" in full["verification_meaning"]
    assert c["quote_match"] == {"state": "all", "matched": 8, "total": 8} and c["label_in_quote"]["state"] == "all"
    assert c["people_and_action"]["state"] == "not_checked"            # 코드가 볼 수 없는 것은 확인했다고 적지 않는다
    assert c["negation"]["state"] == c["hearsay"]["state"] == c["later_correction"]["state"] == "marker_not_found"
    assert c["uncertainty"] == {"state": "found", "elements": ["e8"], "nearby": []}  # 「열 살쯤이었나」 — 때는 말씀 그대로 쓴다
    assert c["memoir_link"]["state"] == "turns" and c["photo"]["state"] == "none"
    assert all(v["state"] != "verified" and v["state"] != "ok" for v in c.values())


def test_checks_show_negation_and_partial_quote_match(full):
    assert by_title(full, "장화와 고무신")["checks"]["negation"] == {"state": "found", "elements": ["e1"], "nearby": [], "partial_scope": []}
    seoul = by_title(full, "서울로 가던 날")["checks"]
    assert seoul["quote_match"] == {"state": "some", "matched": 2, "total": 4}


def test_later_correction_marker_sends_scene_to_review():
    d = seed()
    d["source"]["utterances"][4]["elder"] = "아니, 다시 생각하니 리어카가 아니라 지게였어요."
    s = one(d, APPLE + [("object", "리어카", 2, "사과 궤짝을 리어카에 싣고")])
    assert s["elements"][-1]["flags"] == ["possible_later_correction"]
    assert s["checks"]["later_correction"]["state"] == "found" and s["checks"]["later_correction"]["elements"] == ["e4"]
    assert (s["verification"], s["decision"]) == ("partial", "review")
    assert "possible_later_correction" in s["decision_reasons"]


def test_correction_in_another_session_is_not_seen():
    """다른 회차의 정정은 보지 않는다 — 그래서 상태는 「없다」 가 아니라 marker_not_found 다."""
    d = seed()
    d["source"]["utterances"][7]["elder"] = "아니, 리어카가 아니라 지게였어요."          # 8턴 · 회차 s-b
    s = one(d, APPLE + [("object", "리어카", 2, "사과 궤짝을 리어카에 싣고")])
    assert s["checks"]["later_correction"]["state"] == "marker_not_found" and s["decision"] == "eligible"


def test_no_source_checks_are_not_checked():
    d = seed()
    d["source"] = None
    c = one(d, APPLE)["checks"]
    assert c["quote_match"] == {"state": "not_checked", "matched": None, "total": 3}
    assert all(c[k]["state"] == "not_checked" for k in ("label_in_quote", "negation", "uncertainty", "hearsay",
                                                         "later_correction", "people_and_action"))
    assert c["memoir_link"]["state"] == "no_source"


# ---------------------------------------------------------------- 장 단위 출처 (문장에 턴이 없는 원고)

def chapter_sourced() -> dict:
    """문장 출처는 없고 장(수필)마다 이야기 번호만 아는 원고 — 실제 실험 원고(book.json)의 모양."""
    d = seed()
    for ch in d["memoir"]["chapters"]:
        ch["source_turns"] = sorted({t for p in ch["paragraphs"] for x in p["sentences"] for t in x["turns"]})
        for p in ch["paragraphs"]:
            for x in p["sentences"]:
                x["turns"] = []
    return d


def test_chapter_level_source_is_traceable():
    s = one(chapter_sourced(), APPLE)
    assert (s["memoir_link"], s["verification"], s["decision"]) == ("chapter_turns", "verified", "eligible")
    assert (s["placement"]["basis"], s["placement"]["paragraph_index"]) == ("label_match", 1)


def test_chapter_level_source_still_rejects_other_chapters_turns():
    s = one(chapter_sourced(), SPOON, chapter_no=1)
    assert (s["memoir_link"], s["verification"]) == ("outside_chapter", "partial")


def test_chapter_source_turn_must_exist():
    d = seed()
    d["memoir"]["chapters"][0]["source_turns"] = [99]
    with pytest.raises(il.IllustError):
        il.check_input(d)


# ---------------------------------------------------------------- 삽화 위치

def test_placement_points_to_the_paragraph_that_cites_the_turns():
    s = one(seed(), APPLE)
    pl = s["placement"]
    assert (pl["chapter_no"], pl["chapter_key"], pl["chapter_title"]) == (1, None, "사과 궤짝")
    assert (pl["paragraph_index"], pl["paragraph_count"], pl["basis"]) == (1, 3, "turns")
    assert pl["anchor"]["text"].startswith("가을이면 형과 둘이서") and len(pl["anchor"]["hash"]) == 16
    assert il.locate(SEED["memoir"], pl) == {"state": "exact", "chapter_no": 1, "paragraph_index": 1}


def test_placement_survives_inserted_paragraph_and_spacing():
    pl = one(seed(), APPLE)["placement"]
    d = seed()
    paras = d["memoir"]["chapters"][0]["paragraphs"]
    paras.insert(0, {"sentences": [{"text": "새로 넣은 머리말이다.", "turns": []}]})
    paras[2]["sentences"][0]["text"] = paras[2]["sentences"][0]["text"].replace(" ", "  ")     # 띄어쓰기만 바뀜
    assert il.locate(d["memoir"], pl) == {"state": "moved", "chapter_no": 1, "paragraph_index": 2}


def test_placement_follows_paragraph_to_a_renumbered_chapter():
    pl = one(seed(), APPLE)["placement"]
    d = seed()
    d["memoir"]["chapters"].insert(0, {"no": 1, "title": "머리말", "paragraphs": [{"sentences": [{"text": "책을 연다.", "turns": []}]}]})
    for i, ch in enumerate(d["memoir"]["chapters"], start=1):
        ch["no"] = i
    assert il.locate(d["memoir"], pl) == {"state": "moved", "chapter_no": 2, "paragraph_index": 1}


def test_placement_falls_back_to_chapter_when_text_changed():
    pl = one(seed(), APPLE)["placement"]
    d = seed()
    d["memoir"]["chapters"][0]["paragraphs"][1]["sentences"][0]["text"] = "가을마다 형과 장에 갔다."
    assert il.locate(d["memoir"], pl) == {"state": "chapter_only", "chapter_no": 1, "paragraph_index": None}


def test_placement_is_lost_when_chapter_is_gone():
    pl = one(seed(), APPLE)["placement"]
    d = seed()
    d["memoir"]["chapters"] = d["memoir"]["chapters"][1:]
    assert il.locate(d["memoir"], pl)["state"] == "lost"
    assert il.locate(SEED["memoir"], None)["state"] == "lost"


def test_placement_uses_chapter_key_when_given():
    d = seed()
    d["memoir"]["chapters"][0]["chapter_key"] = "ch-1"
    pl = one(d, APPLE)["placement"]
    d["memoir"]["chapters"][0]["title"] = "제목을 바꿨다"
    assert pl["chapter_key"] == "ch-1" and il.locate(d["memoir"], pl)["state"] == "exact"


def test_placement_without_any_basis_is_chapter_only():
    d = chapter_sourced()
    d["memoir"]["chapters"][0]["paragraphs"] = [{"sentences": [{"text": "어린 날의 가을이었다.", "turns": []}]}]
    pl = one(d, APPLE)["placement"]
    assert (pl["basis"], pl["paragraph_index"], pl["anchor"]) == ("chapter_only", None, None)
    assert il.locate(d["memoir"], pl)["state"] == "chapter_only"


SCENE_KEYS = {"scene_id", "chapter_no", "chapter_key", "chapter_title", "scene_title", "scene_summary", "source_turns",
              "source_refs", "source_excerpt", "elements", "visual_mode", "verification", "memoir_link",
              "verification_scope", "has_real_photo", "photo_check", "decision", "generation", "decision_reasons",
              "mode_if_released", "checks", "experience_basis", "placement",
              "central_action", "people_review", "object_relations", "participants_review", "verification_review",
              "importance", "recommendation_reason", "risk_notes", "generation_prompt", "draft_prompt", "prompt_checks"}


def test_result_shape_is_stable(full):
    again = il.run(seed(), call=lambda s, u: json.dumps(MOCK, ensure_ascii=False))
    assert again == full                                             # 같은 입력 · 같은 후보 → 같은 결과
    assert all(set(s) == SCENE_KEYS for s in full["scenes"])
    assert [s["scene_id"] for s in full["scenes"]] == ["il-1-1", "il-1-2", "il-1-3", "il-1-4", "il-1-5",
                                                       "il-2-1", "il-2-2", "il-3-1", "il-3-2"]
    assert all(s["visual_mode"] in il.MODES and s["verification"] in ("verified", "partial", "unverified")
               and s["decision"] in ("eligible", "review", "held", "not_selected", "skip") for s in full["scenes"])
    json.dumps(full, ensure_ascii=False)


def test_every_used_quote_is_in_the_source(full):
    src = {u["turn"]: "".join(u["elder"].split()) for u in SEED["source"]["utterances"]}
    for s in full["scenes"]:
        for x in s["source_excerpt"]:
            assert "".join(x["quote"].split()) in src[x["turn"]]


def test_report_lists_every_scene(full):
    text = il.report(full)
    assert all(s["scene_id"] in text for s in full["scenes"]) and "이미지는 만들지 않았다" in text


def test_module_is_independent_of_the_memoir_pipeline():
    """다른 자서전 모듈 · DB · 모델 SDK 를 import 하지 않는다 — 표준 라이브러리뿐이다."""
    tree = ast.parse(Path(il.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "상대 import 가 있다"
            names.add((node.module or "").split(".")[0])
    assert names <= {"__future__", "hashlib", "json", "re", "pathlib", "typing"}


# ---------------------------------------------------------------- 실행기

def test_tool_dry_run_and_refusals(tmp_path, capsys):
    seed_path = str(ROOT / "eval" / "illust_seed_A.json")
    assert tool.main(["--input", seed_path, "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["model_called"] is False
    assert tool.main(["--input", seed_path]) == 2                                # 모의 응답 없이는 돌지 않는다
    real = seed()
    real.pop("synthetic")
    p = tmp_path / "real.json"
    p.write_text(json.dumps(real, ensure_ascii=False), encoding="utf-8")
    assert tool.main(["--input", str(p), "--dry-run"]) == 2                      # 합성이 아니면 eval/exp 밖에서 거부
    assert tool.main(["--input", str(tmp_path / "none.json"), "--dry-run"]) == 2


def test_tool_writes_result_and_report(tmp_path, capsys):
    code = tool.main(["--input", str(ROOT / "eval" / "illust_seed_A.json"),
                      "--mock", str(ROOT / "eval" / "illust_mock_A.json"), "--out", str(tmp_path)])
    capsys.readouterr()
    assert code == 0
    res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert res["schema_version"] == "illust-result-v1" and (tmp_path / "report.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 실제 원문 · 원고 변환기 (합성 글로 시험한다)

from tools import memoir_illust_prepare as prep     # noqa: E402

STORIES = "1.\n형이랑 둘이서 사과 궤짝을 리어카에 싣고 장터까지 끌고 갔어요.\n\n2.\n할머니가 쓰시던 놋숟가락이 아직 있어요.\n"
BOOK = {"title": "합성 책", "essays": [
    {"key": "e01", "no": 1, "title": "사과 궤짝", "stories": [1], "paragraphs": ["가을마다 장터에 갔다.", "사과 궤짝은 무거웠다."]},
    {"key": "e02", "no": 2, "title": "놋숟가락", "stories": [2],
     "paragraphs": [[{"text": "놋숟가락이 아직 있다.", "turns": [2]}, {"text": "", "turns": [2]}]]},
    {"key": "e03", "no": 3, "title": "원문 밖", "stories": [3], "paragraphs": ["원문을 받지 못한 수필이다."]}]}


def _prep(tmp_path, monkeypatch, stories=STORIES, book=BOOK, extra=()):
    monkeypatch.setattr(prep, "PRIVATE", tmp_path / "exp")
    (tmp_path / "stories.txt").write_text(stories, encoding="utf-8")
    (tmp_path / "book.json").write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "exp" / "in.json"
    code = prep.main(["--stories", str(tmp_path / "stories.txt"), "--book", str(tmp_path / "book.json"),
                      "--out", str(out), *extra])
    return code, out


def test_prepare_keeps_numbers_and_invents_nothing(tmp_path, monkeypatch, capsys):
    code, out = _prep(tmp_path, monkeypatch)
    shown = capsys.readouterr().out
    assert code == 0 and "사과" not in shown                           # 화면에는 개수만 — 본문을 찍지 않는다
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["synthetic"] is False and d["photos"] is None and "turn_map" not in d["source"]
    assert [u["turn"] for u in d["source"]["utterances"]] == [1, 2]    # 이야기 번호 그대로
    assert d["source"]["utterances"][0]["session_id"] == "file:stories.txt"
    chs = d["memoir"]["chapters"]
    assert [(c["chapter_key"], c["source_turns"]) for c in chs] == [("e01", [1]), ("e02", [2])]   # e03 은 원문이 없어 뺐다
    assert chs[0]["paragraphs"][0] == {"sentences": [{"text": "가을마다 장터에 갔다.", "turns": []}]}
    assert chs[1]["paragraphs"] == [{"sentences": [{"text": "놋숟가락이 아직 있다.", "turns": [2]}]}]   # 있던 출처만 옮긴다
    s = one(d, [("object", "사과 궤짝", 1, "사과 궤짝을 리어카에 싣고")])
    assert (s["memoir_link"], s["chapter_key"], s["decision_reasons"]) == ("chapter_turns", "e01", ["photo_not_provided"])
    assert s["source_refs"] == []                                      # 회차 · 원래 턴은 모른다 — 만들지 않는다


def test_prepare_refuses_bad_numbering_and_public_output(tmp_path, monkeypatch, capsys):
    assert _prep(tmp_path, monkeypatch, stories="1.\n하나\n\n3.\n셋\n")[0] == 2
    monkeypatch.setattr(prep, "PRIVATE", tmp_path / "elsewhere")
    assert prep.main(["--stories", str(tmp_path / "stories.txt"), "--book", str(tmp_path / "book.json"),
                      "--out", str(tmp_path / "exp" / "in.json")]) == 2
    capsys.readouterr()


def test_prepare_refuses_sentence_citing_unknown_story(tmp_path, monkeypatch, capsys):
    book = {"title": "책", "essays": [{"key": "e01", "title": "가", "stories": [1], "paragraphs": [[{"text": "글", "turns": [9]}]]}]}
    assert _prep(tmp_path, monkeypatch, book=book)[0] == 2
    capsys.readouterr()


def test_prepare_no_photos_flag_and_manuscript_check(tmp_path, monkeypatch, capsys):
    (tmp_path / "m.md").write_text("# 합성 책\n\n가을마다  장터에 갔다.\n\n놋숟가락이 아직 있다.\n", encoding="utf-8")
    code, out = _prep(tmp_path, monkeypatch, extra=["--no-photos", "--manuscript", str(tmp_path / "m.md")])
    shown = json.loads(capsys.readouterr().out)
    assert code == 0 and json.loads(out.read_text(encoding="utf-8"))["photos"] == []
    assert shown["manuscript_check"] == {"paragraphs": 3, "found_in_manuscript": 2} and shown["model_called"] is False


# ---------------------------------------------------------------- 3차 — 표지의 자리 · 한 이야기 안의 여러 장면 · 범위 · 실제 호출 잠금

def long_story() -> dict:
    """긴 이야기 하나(한 턴)에 장면이 여럿인 합성 자료 — 실제 원문(이야기 한 편이 한 턴)의 모양."""
    d = seed()
    d["photos"] = []
    d["source"]["utterances"][1]["elder"] = (
        "내가 열 살쯤이었는데 형이랑 둘이서 사과 궤짝을 리어카에 싣고 장터까지 끌고 갔어요. "
        "궤짝이 무거워서 둘이 밀어도 얼마 못 가서 세워 놓고 쉬었지요. "
        "아버지는 사다리에 올라가 사과를 땄어요.")
    return d


def test_marker_outside_the_quote_does_not_block_but_sends_to_review():
    """「둘이 밀어도 얼마 못 가서」 — 인용 밖의 「못」 때문에 사물(궤짝)을 지우지 않는다. 다만 사람이 본다."""
    s = one(long_story(), APPLE + [("person", "형", 2, "형이랑 둘이서"), ("object", "궤짝", 2, "궤짝이 무거워서")])
    brother, crate = s["elements"][3], s["elements"][4]
    assert (brother["status"], brother["flags"]) == ("quoted", ["uncertain_nearby"])
    assert (crate["status"], crate["flags"]) == ("quoted", ["negation_nearby"])
    assert s["checks"]["negation"] == {"state": "nearby", "elements": [], "nearby": ["e5"], "partial_scope": []}
    assert (s["verification"], s["decision"]) == ("partial", "review")
    assert OPEN + "형" in s["draft_prompt"]["scene_block"] and "궤짝" in s["draft_prompt"]["scene_block"]


def test_negation_in_an_earlier_clause_is_kept_with_a_review_reason():
    """「얼마 못 가서 / 세워 놓고 / 쉬었지요」 — 못 한 것(멀리 가기)과 실제로 한 것(세워 놓고 쉬기)이 함께 있다."""
    s = one(long_story(), APPLE + [("action", "얼마 못 가서 세워 놓고 쉬었다", 2, "얼마 못 가서 세워 놓고 쉬었지요")])
    e = s["elements"][-1]
    assert (e["status"], e["flags"]) == ("quoted", ["negation_partial_scope"])
    assert s["checks"]["negation"]["partial_scope"] == ["e4"] and "negation_scope_unclear" in s["decision_reasons"]
    assert s["decision"] == "review" and "얼마 못 가서 세워 놓고 쉬었다" in s["draft_prompt"]["scene_block"]


def test_negation_in_the_final_clause_blocks():
    d = long_story()
    d["source"]["utterances"][1]["elder"] += " 형은 힘들다고 장터에는 안 갔어요."
    s = one(d, APPLE + [("person", "형", 2, "형은 힘들다고 장터에는 안 갔어요")])
    assert (s["elements"][-1]["status"], s["elements"][-1]["flags"]) == ("blocked", ["negation_in_source"])


def test_affirmative_label_made_of_the_negated_clause_blocks():
    """인용 뒤 마디가 긍정이어도, 이름이 부정된 마디의 말을 긍정으로 바꾼 것이면 막는다."""
    d = long_story()
    d["source"]["utterances"][1]["elder"] += " 장터에는 못 들어가고 길에서 팔았어요."
    s = one(d, APPLE + [("action", "장터에 들어간다", 2, "장터에는 못 들어가고 길에서 팔았어요")])
    assert (s["elements"][-1]["status"], s["elements"][-1]["flags"]) == ("blocked", ["negation_in_source"])


def test_hedged_narrator_is_not_dropped_from_the_picture():
    """「내가 열 살쯤이었는데」 의 「쯤」 때문에 본인이 그림에서 빠지면 그것이 왜곡이다 — 쓰되 검토로 보낸다."""
    s = one(long_story(), APPLE + [("person", "내", 2, "내가 열 살쯤이었는데")])
    assert s["elements"][-1]["flags"] == ["uncertain"] and s["decision"] == "review"
    assert il.SELF_LABEL in s["draft_prompt"]["scene_block"]


def test_two_scenes_in_one_turn_are_not_duplicates():
    ladder = [("action", "사다리에 올라가 사과를 땄다", 2, "아버지는 사다리에 올라가 사과를 땄어요"),
              ("object", "사다리", 2, "사다리에 올라가"), ("person", "아버지", 2, "아버지는 사다리에 올라가")]
    r = run(long_story(), [cand(APPLE, title="장터 가는 길"), cand(ladder, title="사다리 위의 아버지"),
                           cand(APPLE[:2], title="같은 장면")])
    skipped = [(s["scene_title"], s["decision_reasons"]) for s in r["scenes"] if s["decision"] == "skip"]
    assert skipped == [("같은 장면", ["duplicate"])]
    assert r["scenes"][1]["source_turns"] == r["scenes"][0]["source_turns"] == [2]


def test_scope_sends_only_the_chosen_chapter_and_its_turns():
    msg = json.loads(il.select_message(seed(), only=[2]).split("\n", 1)[1])
    assert [c["chapter_no"] for c in msg["chapters"]] == [2]
    assert [u["turn"] for u in msg["utterances"]] == [7, 8, 9, 10]
    assert [p["turns"] for p in msg["photo_clues"]] == [[9]]            # 그 턴에 이은 사진만
    whole = json.loads(il.select_message(seed()).split("\n", 1)[1])
    assert len(whole["utterances"]) == 14 and len(whole["chapters"]) == 3


def test_scope_by_key_and_unknown_chapter():
    d = seed()
    d["memoir"]["chapters"][1]["chapter_key"] = "e02"
    assert il.scope(d, ["e02"])["turns"] == [7, 8, 9, 10]
    with pytest.raises(il.IllustError):
        il.scope(d, ["e99"])
    for ch in d["memoir"]["chapters"]:
        for p in ch["paragraphs"]:
            for x in p["sentences"]:
                x["turns"] = []
    with pytest.raises(il.IllustError):                                 # 출처 턴이 없는 장은 통째로 보내지 않는다
        il.scope(d, [1])


def test_candidate_outside_the_sent_scope_is_not_accepted():
    reply = json.dumps({"candidates": [cand(SPOON, chapter_no=2), cand(APPLE)]}, ensure_ascii=False)
    r = il.run(seed(), call=lambda s, u: reply, only=[2])
    assert r["scope"] == {"whole_book": False, "chapter_nos": [2], "chapter_keys": [None], "turns": [7, 8, 9, 10]}
    assert [(s["decision"], s["decision_reasons"]) for s in r["scenes"]] == [("eligible", []), ("skip", ["outside_scope"])]


def test_placement_points_to_a_sentence_inside_the_paragraph():
    pl = one(seed(), [("object", "고무신", 4, "고무신 신고 다녔지요")])["placement"]
    assert (pl["paragraph_index"], pl["sentence_index"], pl["sentence_count"]) == (1, 2, 3)
    assert pl["sentence_anchor"]["text"].startswith("장화가 없어") and len(pl["sentence_anchor"]["hash"]) == 16


SEED_PATH = str(ROOT / "eval" / "illust_seed_A.json")
MOCK_PATH = str(ROOT / "eval" / "illust_mock_A.json")


def test_tool_keeps_raw_candidates_apart_from_the_verdict(tmp_path, capsys):
    assert tool.main(["--input", SEED_PATH, "--chapter", "3", "--mock", MOCK_PATH, "--out", str(tmp_path)]) == 0
    capsys.readouterr()
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {"request.json", "response.raw.txt", "candidates.json", "result.json", "report.md",
                     "human_review.json", "run.json"}
    raw = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    assert len(raw["candidates"]) == 9 and "decision" not in raw["candidates"][0]      # 모델이 낸 그대로
    res = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert sum(1 for s in res["scenes"] if s["decision_reasons"] == ["outside_scope"]) >= 1
    run_doc = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert (run_doc["source"], run_doc["calls"], run_doc["image_api_called"]) == ("mock", 0, False)
    sheet = json.loads((tmp_path / "human_review.json").read_text(encoding="utf-8"))
    assert len(sheet["scenes"]) == 9 and set(sheet["scenes"][0]["items"]) == set(tool.REVIEW_ITEMS)
    assert all(i["verdict"] == "not_reviewed" for s in sheet["scenes"] for i in s["items"].values())
    assert all(s["human_semantic_check"] == "not_reviewed" for s in sheet["scenes"])


def _live_args(tmp_path, capsys):
    env = tmp_path / "k.env"
    env.write_text("GEMINI_API_KEY=test-key-not-real\n", encoding="utf-8")
    base = ["--input", SEED_PATH, "--chapter", "2", "--model", "m-test"]
    assert tool.main(base + ["--dry-run"]) == 0
    token = json.loads(capsys.readouterr().out)["live_confirm"]
    return base + ["--live", "--env-file", str(env), "--out", str(tmp_path / "out")], token, str(env)


def test_live_is_refused_without_every_condition(tmp_path, capsys, monkeypatch):
    called = []
    monkeypatch.setattr(tool, "LIVE_CALL", lambda *a, **k: called.append(1) or {"text": "{}"})
    args, token, env = _live_args(tmp_path, capsys)
    out = ["--out", str(tmp_path / "out")]
    assert tool.main(args) == 2                                                    # --confirm 없음
    assert tool.main(args + ["--confirm", "wrong"]) == 2
    assert tool.main(["--input", SEED_PATH, "--live", "--model", "m-test", "--env-file", env,
                      "--confirm", token] + out) == 2                             # 책 전체는 보내지 않는다
    assert tool.main(["--input", SEED_PATH, "--chapter", "2", "--model", "m-other", "--live", "--env-file", env,
                      "--confirm", token] + out) == 2                             # 모델이 바뀌면 승인도 다시
    assert tool.main(["--input", SEED_PATH, "--chapter", "2", "--model", "m-test", "--live",
                      "--env-file", str(tmp_path / "none.env"), "--confirm", token] + out) == 2      # 키 없음
    assert tool.main(args + ["--confirm", token, "--mock", MOCK_PATH]) == 2
    capsys.readouterr()
    assert called == [] and not (tmp_path / "out").exists()


def test_live_calls_once_and_runs_the_same_checks(tmp_path, capsys, monkeypatch):
    seen = []

    def fake(system, user, *, model, key):
        seen.append((model, key, "놋숟가락" in user, "사과 궤짝을 리어카" in user))
        text = json.dumps({"candidates": [cand(SPOON, chapter_no=2), cand(GRAD, chapter_no=2, title="졸업식")]},
                          ensure_ascii=False)
        return {"text": text, "finish": "STOP", "usage": {"prompt": 10, "output": 5, "total": 15}}

    monkeypatch.setattr(tool, "LIVE_CALL", fake)
    args, token, _ = _live_args(tmp_path, capsys)
    assert tool.main(args + ["--confirm", token]) == 0
    shown = capsys.readouterr().out
    assert seen == [("m-test", "test-key-not-real", True, False)]                 # 한 번 · 범위 밖 원문은 보내지 않는다
    assert "test-key-not-real" not in shown
    out = tmp_path / "out"
    run_doc = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert (run_doc["source"], run_doc["calls"], run_doc["model"], run_doc["failure"]) == ("live", 1, "m-test", None)
    assert "test-key-not-real" not in "".join(p.read_text(encoding="utf-8") for p in out.iterdir())
    res = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert [s["decision"] for s in res["scenes"]] == ["eligible", "skip"] and res["model"]["source"] == "live"
    assert all(s["generation"]["user_selected"] is False and s["generation"]["image_status"] == "not_requested"
               and s["generation"]["user_approved"] is False for s in res["scenes"])


@pytest.mark.parametrize("reply", [{"text": "죄송하지만 JSON 으로 드릴 수 없습니다"}, RuntimeError("boom")])
def test_live_failure_is_recorded_and_not_retried(tmp_path, capsys, monkeypatch, reply):
    calls = []

    def fake(system, user, *, model, key):
        calls.append(1)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(tool, "LIVE_CALL", fake)
    args, token, _ = _live_args(tmp_path, capsys)
    assert tool.main(args + ["--confirm", token]) == 1
    capsys.readouterr()
    run_doc = json.loads((tmp_path / "out" / "run.json").read_text(encoding="utf-8"))
    assert calls == [1] and run_doc["calls"] == 1 and run_doc["failure"]["kind"] in ("model_output", "model_call")
    assert not (tmp_path / "out" / "result.json").exists()


# ---------------------------------------------------------------- 실제 호출 1회에서 찾은 것 — 본인을 「나」 로 적었는데 원문은 「제가」

def polite_story() -> dict:
    d = seed()
    d["photos"] = []
    d["source"]["utterances"][1]["elder"] = "제가 형이랑 둘이서 사과 궤짝을 리어카에 싣고 장터까지 끌고 갔어요. 저희 집은 장터에서 멀었어요."
    return d


def test_narrator_written_as_na_matches_polite_je_in_the_source():
    s = one_confirmed(polite_story(), APPLE + [("person", "나", 2, "제가 형이랑 둘이서")])
    assert s["elements"][-1]["status"] == "quoted" and s["decision"] == "eligible"
    assert il.SELF_LABEL in s["generation_prompt"]["scene_block"]


def test_our_house_is_not_proof_that_the_narrator_was_there():
    s = one(polite_story(), APPLE + [("person", "나", 2, "저희 집은 장터에서 멀었어요")])
    assert s["elements"][-1]["status"] == "paraphrased" and il.SELF_LABEL not in s["draft_prompt"]["scene_block"]


# ---------------------------------------------------------------- 4차 — 함께 한 사람 · 행동의 목적어 · 때의 확실성 · 배경과 자리

def carry_story() -> dict:
    """합성 — 한 이야기(한 턴)에 여러 순간. 실제 원문 한 항목과 같은 짜임이지만 내용은 지어낸 것이다."""
    d = seed()
    d["photos"] = []
    d["source"]["utterances"][1]["elder"] = (
        "과수원이 우리 집 바로 뒤에 있었어요. "
        "제가 열 살쯤 되던 해였는데 형이랑 둘이서 사과 궤짝을 창고까지 날랐어요. "
        "아버지는 사다리에 올라가 사과를 땄어요. "
        "일이 끝나면 할머니께서 저한테 삶은 고구마를 주셨어요. "
        "사촌들 몫은 안 남기셨어요.")
    return d


def cand2(elements, summary, chapter_no=1, title="장면") -> dict:
    out = []
    for e in elements:
        x = dict(zip(("kind", "text", "turn", "quote"), e[:4]))
        if len(e) > 4:
            x["role"] = e[4]
        out.append(x)
    return {"chapter_no": chapter_no, "scene_title": title, "scene_summary": summary, "importance": "main",
            "reason": "까닭", "elements": out}


def one2(data, elements, summary, **kw) -> dict:
    return run(data, [cand2(elements, summary, **kw)])["scenes"][0]


# v2 지시문을 따른 응답 — 함께 한 두 사람 · 목적어와 방향이 있는 행동 · 「쯤」 을 지킨 때 · 배경으로 적은 장소
GOOD = [("action", "사과 궤짝을 창고까지 날랐다", 2, "형이랑 둘이서 사과 궤짝을 창고까지 날랐어요"),
        ("person", "나", 2, "제가 열 살쯤 되던 해였는데 형이랑 둘이서"),
        ("person", "형", 2, "형이랑 둘이서 사과 궤짝을"),
        ("object", "사과 궤짝", 2, "사과 궤짝을 창고까지 날랐어요"),
        ("time", "열 살쯤", 2, "제가 열 살쯤 되던 해였는데"),
        ("place", "과수원", 2, "과수원이 우리 집 바로 뒤에 있었어요", "setting")]
GOOD_SUMMARY = "열 살쯤 형과 둘이서 사과 궤짝을 창고까지 날랐다."


def test_v2_contract_shared_action_object_hedged_age_and_unfixed_spot():
    s = one2(carry_story(), GOOD, GOOD_SUMMARY)
    block = s["draft_prompt"]["scene_block"]
    assert OPEN + "이야기하는 본인(열 살쯤의 어린아이 · 생김새를 정하지 않는다), 형" in block     # 두 사람이 다 들어간다 (확인 전 표시)
    assert "- 행동: 사과 궤짝을 창고까지 날랐다" in block                 # 무엇을 · 어디로
    assert "- 때: 열 살쯤" in block                                      # 「쯤」 을 지킨다
    assert "- 배경: 과수원" in block and "- 행동이 벌어진 자리: 원문에서 확인되지 않았다" in block
    c = s["checks"]
    assert c["summary_consistency"]["state"] == "marker_not_found" and c["action_detail"]["state"] == "has_object"
    assert c["place_role"] == {"state": "setting_only", "spots": []}
    assert c["same_moment"]["state"] == "not_checked" and c["same_moment"]["elements_from_other_sentences"] == []
    assert c["people_and_action"]["state"] == "not_checked"            # 여전히 코드가 확인한 것이 아니다
    # 불확실 표지(쯤)가 본인 인용 안에 있어 검토에 남는다 — 사람이 보고 넘긴다
    # 「열 살쯤」 의 추정은 나이에만 붙어 있고 때 요소 · 요약이 지켰다 — 그것만으로는 검토 사유가 되지 않는다
    assert (s["decision"], s["decision_reasons"]) == ("review", [
        "person_relation_missing", "person_relation_not_human_confirmed"])
    assert s["verification"] == "partial" and s["verification_review"]["effective"] == "no_open_cause"
    assert s["generation"]["user_selected"] is False and s["generation"]["image_status"] == "not_requested"


def test_companion_only_in_the_summary_is_flagged_not_filled_in():
    """요약에만 「형과 함께」 — 실제 호출에서 요약에만 함께 한 사람이 나온 일이 있었다. 코드는 알릴 뿐 요소를 채우지 않는다."""
    els = [e for e in GOOD if e[1] != "형"]
    s = one2(carry_story(), els, "열 살쯤 형과 함께 사과 궤짝을 창고까지 날랐다.")
    assert s["checks"]["summary_consistency"]["persons_not_in_elements"] == ["형"]
    assert "summary_person_not_in_elements" in s["decision_reasons"] and s["decision"] == "review"
    assert "형" not in s["draft_prompt"]["scene_block"]                  # 원문에서 끌어다 채우지 않는다
    assert any("형" in n and "코드가 채우지 않는다" in n for n in s["risk_notes"])


def test_one_word_action_is_flagged():
    els = [("action", "날랐어", 2, "사과 궤짝을 창고까지 날랐어요")] + GOOD[1:]
    s = one2(carry_story(), els, GOOD_SUMMARY)
    assert s["checks"]["action_detail"] == {"state": "short", "elements": ["e1"]}
    assert "action_too_short" in s["decision_reasons"]


def test_age_stated_without_its_hedge_is_not_used():
    """원문은 「열 살쯤」 — 이름을 「열 살」 로 적으면 확실하지 않은 것을 확실하게 만든 것이다."""
    els = [e if e[0] != "time" else ("time", "열 살", 2, "제가 열 살쯤 되던 해였는데") for e in GOOD]
    s = one2(carry_story(), els, "열 살 때 형과 둘이서 사과 궤짝을 창고까지 날랐다.")
    t = next(e for e in s["elements"] if e["kind"] == "time")
    assert t["status"] == "blocked" and t["flags"] == ["uncertain", "certainty_raised"]
    assert "- 때: 특정하지 않는다" in s["draft_prompt"]["scene_block"]
    assert s["checks"]["summary_consistency"]["certainty_raised"] == ["열 살"]
    assert "certainty_raised" in s["decision_reasons"]


def test_hedge_cut_off_by_a_short_quote_is_still_caught():
    els = [e if e[0] != "time" else ("time", "열 살", 2, "제가 열 살") for e in GOOD]
    t = next(e for e in one2(carry_story(), els, GOOD_SUMMARY)["elements"] if e["kind"] == "time")
    assert t["status"] == "blocked" and "certainty_raised" in t["flags"]


def test_time_only_in_the_summary_is_flagged():
    s = one2(carry_story(), [e for e in GOOD if e[0] != "time"], GOOD_SUMMARY)
    assert s["checks"]["summary_consistency"]["time_not_in_elements"] == ["열 살쯤"]
    assert "summary_time_not_in_elements" in s["decision_reasons"]


def test_prop_from_another_moment_is_pointed_out():
    """사다리(아버지가 사과를 따던 순간)와 고구마(일이 끝난 뒤)를 나르는 장면에 끼워 넣었다."""
    els = GOOD + [("object", "사다리", 2, "사다리에 올라가"), ("object", "삶은 고구마", 2, "삶은 고구마를 주셨어요")]
    s = one2(carry_story(), els, GOOD_SUMMARY)
    assert s["checks"]["same_moment"]["elements_from_other_sentences"] == ["e7", "e8"]
    assert "elements_from_other_sentences" in s["decision_reasons"]
    assert "사다리" in s["draft_prompt"]["scene_block"]                 # 빼지는 않는다 — 같은 순간일 수도 있다. 사람이 정한다


def test_prop_from_another_moment_in_the_same_sentence_is_not_caught():
    """한계 — 같은 문장 안에서 다른 순간의 것을 가져오면 코드가 모른다. 사람 검토 항목(moments_not_merged)이다."""
    d = carry_story()
    d["source"]["utterances"][1]["elder"] = d["source"]["utterances"][1]["elder"].replace(
        "창고까지 날랐어요. ", "창고까지 날랐고 전날에는 리어카를 고쳤어요. ")
    els = [e if e[0] != "action" else ("action", "사과 궤짝을 창고까지 날랐다", 2, "형이랑 둘이서 사과 궤짝을 창고까지 날랐고") for e in GOOD]
    els = [e if e[1] != "사과 궤짝" else ("object", "사과 궤짝", 2, "사과 궤짝을 창고까지 날랐고") for e in els]
    s = one2(d, els + [("object", "리어카", 2, "전날에는 리어카를 고쳤어요")], GOOD_SUMMARY)
    assert s["checks"]["same_moment"]["elements_from_other_sentences"] == []
    assert "moments_not_merged" in tool.REVIEW_ITEMS


def test_negated_recipient_is_not_drawn_as_receiving():
    els = [("action", "삶은 고구마를 주셨다", 2, "할머니께서 저한테 삶은 고구마를 주셨어요"),
           ("object", "삶은 고구마", 2, "삶은 고구마를 주셨어요"), ("person", "할머니", 2, "할머니께서 저한테"),
           ("person", "나", 2, "할머니께서 저한테 삶은 고구마를"), ("person", "사촌들", 2, "사촌들 몫은 안 남기셨어요")]
    s = one2(carry_story(), els, "일이 끝나면 할머니가 삶은 고구마를 주셨다.")
    assert s["elements"][-1]["status"] == "blocked" and "사촌들" not in s["draft_prompt"]["scene_block"]
    assert OPEN + f"할머니, {il.SELF_LABEL}" in s["draft_prompt"]["scene_block"]


def test_spot_claim_is_sent_to_review_and_shown_apart_from_the_setting():
    els = GOOD + [("place", "창고", 2, "사과 궤짝을 창고까지 날랐어요", "spot")]
    s = one2(carry_story(), els, GOOD_SUMMARY)
    assert "- 배경: 과수원" in s["draft_prompt"]["scene_block"]
    assert "- 행동이 벌어진 자리: 창고" in s["draft_prompt"]["scene_block"]
    assert s["checks"]["place_role"] == {"state": "spot_claimed", "spots": ["e7"]}
    assert "place_spot_not_checked" in s["decision_reasons"]


def test_place_without_role_is_treated_as_setting_only():
    s = one(seed(), APPLE)
    assert s["elements"][2]["role"] == "setting" and "- 배경: 장터" in s["generation_prompt"]["scene_block"]
    assert "- 행동이 벌어진 자리: 원문에서 확인되지 않았다" in s["generation_prompt"]["scene_block"]


@pytest.mark.parametrize("bad_el", [{"kind": "place", "text": "장터", "turn": 2, "quote": "장터까지 끌고 갔어요", "role": "here"},
                                    {"kind": "object", "text": "리어카", "turn": 2, "quote": "리어카에 싣고", "role": "spot"}])
def test_role_is_only_for_places(bad_el):
    c = cand(APPLE)
    c["elements"].append(bad_el)
    with pytest.raises(il.IllustError):
        il.run(seed(), call=lambda s, u: json.dumps({"candidates": [c]}, ensure_ascii=False))


def test_symbolic_scene_does_not_ask_for_people_from_the_summary():
    d = seed()
    d["photos"] = []
    s = one2(d, [("object", "놋숟가락", 7, "할머니가 쓰시던 놋숟가락이 아직 있어요")], "할머니가 쓰시던 놋숟가락이 아직 있다.", chapter_no=2)
    assert (s["visual_mode"], s["decision"]) == ("SYMBOLIC", "eligible")
    assert s["checks"]["summary_consistency"]["persons_not_in_elements"] == []


def test_select_prompt_is_v3_and_older_versions_are_kept():
    text = il.select_prompt()
    assert il.SELECT_FILE == "1_장면선정_v3.md"
    assert (il.PROMPTS / "1_장면선정_v1.md").is_file() and (il.PROMPTS / "1_장면선정_v2.md").is_file()
    for must in ("한 사람씩 따로", "동사 한 낱말로 적지 않습니다", "「쯤」", '"setting"', '"spot"', "상한이지 채울 개수가 아닙니다",
                 "central_action", "relation", "evidence", "캔 사람이지 나른 사람이 아닙니다", "scene_title 과 scene_summary"):
        assert must in text


def test_long_action_without_particle_is_not_called_short():
    s = one(long_story(), APPLE + [("action", "얼마 못 가서 세워 놓고 쉬었다", 2, "얼마 못 가서 세워 놓고 쉬었지요")])
    assert s["checks"]["action_detail"]["state"] == "has_object" and "action_too_short" not in s["decision_reasons"]


def test_approval_does_not_carry_over_to_a_changed_prompt():
    """지시문을 고치면 확인값이 바뀐다 — v1 때 받은 승인으로 v2 를 보낼 수 없다."""
    a = tool.confirm_token("ref", ["e01"], "m", "user", "system v1")
    assert a != tool.confirm_token("ref", ["e01"], "m", "user", "system v2")
    assert a != tool.confirm_token("ref", ["e02"], "m", "user", "system v1")
    assert a == tool.confirm_token("ref", ["e01"], "m", "user", "system v1")


# ---------------------------------------------------------------- 5차 — 그릴 행동 하나 · 인물의 참여 관계 · 사람 확인 전 차단

def el(key, kind, text, turn, quote, **extra) -> dict:
    return {"key": key, "kind": kind, "text": text, "turn": turn, "quote": quote, **extra}


def rel(action, role, *quotes, turn=2) -> dict:
    return {"action": action, "role": role, "evidence": [{"turn": turn, "quote": q} for q in quotes]}


def cand3(elements, summary="열 살쯤 형과 둘이서 사과 궤짝을 창고까지 날랐다.", central="a1", title="장면", chapter_no=1) -> dict:
    out = {"chapter_no": chapter_no, "scene_title": title, "scene_summary": summary, "importance": "main",
           "reason": "까닭", "elements": elements}
    if central is not None:
        out["central_action"] = central
    return out


CARRY = "형이랑 둘이서 사과 궤짝을 창고까지 날랐어요"
A1 = el("a1", "action", "사과 궤짝을 창고까지 날랐다", 2, CARRY)
ME = el("p1", "person", "나", 2, "제가 열 살쯤 되던 해였는데 형이랑 둘이서",
        relation=rel("a1", "actor", "제가 열 살쯤 되던 해였는데 형이랑 둘이서 사과 궤짝을 창고까지 날랐어요"))
BROTHER = el("p2", "person", "형", 2, "형이랑 둘이서", relation=rel("a1", "co_actor", CARRY))
CRATE = el("o1", "object", "사과 궤짝", 2, "사과 궤짝을 창고까지 날랐어요", relation=rel("a1", "acted_on", "사과 궤짝을 창고까지 날랐어요"))
AGE = el("t1", "time", "열 살쯤", 2, "제가 열 살쯤 되던 해였는데")
ORCHARD = el("s1", "place", "과수원", 2, "과수원이 우리 집 바로 뒤에 있었어요", role="setting")
V3 = [A1, ME, BROTHER, CRATE, AGE, ORCHARD]


def scene3(elements, data=None, confirm=None, **kw) -> dict:
    c = cand3(elements, **kw)
    data = data or carry_story()
    return (confirmed_run(data, [c], confirm) if confirm else run(data, [c]))["scenes"][0]


def test_v3_relations_are_recorded_in_three_separate_layers():
    s = scene3(V3)
    rows = {r["text"]: r for r in s["people_review"]}
    assert set(rows) == {"나", "형"}
    b = rows["형"]
    assert b["proposed"] == BROTHER["relation"]                                  # 모델이 낸 관계 그대로
    assert b["code"] == {"state": "structure_ok", "evidence_matched": 1, "evidence_total": 1}   # 코드가 본 것 — 칸과 인용
    assert b["human"] == "not_reviewed"                                          # 사람이 본 것 — 아직
    c = s["checks"]["people_and_action"]
    assert c["state"] == "not_checked" and c["code"]["structure_ok"] == 2 and c["human"]["not_reviewed"] == 2
    assert s["central_action"] == {"element": "e1", "text": "사과 궤짝을 창고까지 날랐다", "state": "declared",
                                   "turn": 2, "quote": CARRY}
    assert s["object_relations"][0]["code"]["state"] == "structure_ok"


def test_complete_relations_still_do_not_make_a_generation_prompt_before_human_review():
    """관계 칸과 인용을 다 채워도 뜻이 틀릴 수 있다 — 사람이 확인하기 전에는 생성용으로 확정하지 않는다."""
    s = scene3(V3)
    assert s["decision"] == "review" and s["generation_prompt"] is None and s["draft_prompt"] is not None
    assert "person_relation_not_human_confirmed" in s["decision_reasons"]
    assert "person_relation_missing" not in s["decision_reasons"]
    assert OPEN + "이야기하는 본인(열 살쯤의 어린아이 · 생김새를 정하지 않는다), 형" in s["draft_prompt"]["scene_block"]
    assert s["generation"]["candidate"] == "needs_review" and s["generation"]["user_selected"] is False


def test_human_confirmation_is_what_unlocks_the_people_line():
    d = carry_story()
    d["source"]["utterances"][1]["elder"] = d["source"]["utterances"][1]["elder"].replace("제가 열 살쯤 되던 해였는데 ", "제가 ")
    me = el("p1", "person", "나", 2, "제가 형이랑 둘이서", relation=rel("a1", "actor", "제가 형이랑 둘이서 사과 궤짝을 창고까지 날랐어요"))
    els = [A1, me, BROTHER, CRATE, ORCHARD]
    kw = dict(data=d, summary="형과 둘이서 사과 궤짝을 창고까지 날랐다.")
    assert scene3(els, **kw)["decision"] == "review"
    s = scene3(els, confirm="confirmed", **kw)
    assert s["decision"] == "eligible" and f"- 인물: {il.SELF_LABEL}, 형" in s["generation_prompt"]["scene_block"]
    assert s["checks"]["people_and_action"]["state"] == "human_confirmed"
    assert s["generation"]["user_selected"] is False and s["generation"]["image_status"] == "not_requested"   # 그래도 고른 것은 아니다


def test_human_rejection_removes_the_person_from_the_prompt():
    s = scene3(V3, confirm="rejected")
    block = (s["generation_prompt"] or s["draft_prompt"])["scene_block"]
    assert "- 인물: 사람을 특정하지 않는다" in block and any("사람이 참여자가 아니라고 확인해 뺐다" in n for n in s["risk_notes"])


def test_confirmation_without_a_reviewer_is_refused():
    reply = json.dumps({"candidates": [cand3(V3)]}, ensure_ascii=False)
    for doc in ({"reviewer": "", "relations": {}}, {"relations": {}}, {"reviewer": "가", "relations": {"x": "yes"}}):
        with pytest.raises(il.IllustError):
            il.run(carry_story(), call=lambda s, u: reply, confirmations=doc)


def test_maker_of_the_object_proposed_as_a_carrier_is_shown_for_review_not_generated():
    """실제 v2 응답의 꼴 — 아버지는 사과를 딴 사람인데 나른 사람으로 냈다(관계 칸 없음 · 인용은 원문과 같다)."""
    d = carry_story()
    d["source"]["utterances"][1]["elder"] = d["source"]["utterances"][1]["elder"].replace(
        "형이랑 둘이서 사과 궤짝을", "형이랑 둘이서 아버지가 따 놓은 사과 궤짝을")
    quote = "아버지가 따 놓은 사과 궤짝을 창고까지 날랐어요"
    legacy = [("action", "사과 궤짝을 창고까지 날랐다", 2, quote), ("person", "아버지", 2, quote),
              ("person", "형", 2, "형이랑 둘이서"), ("object", "사과 궤짝", 2, "사과 궤짝을 창고까지 날랐어요")]
    s = one2(d, legacy, "형과 둘이서 사과 궤짝을 창고까지 날랐다.")
    father = next(r for r in s["people_review"] if r["text"] == "아버지")
    assert s["elements"][1]["status"] == "quoted"                                # 인용은 글자까지 맞다
    assert father["proposed"] is None and father["code"]["state"] == "missing" and father["human"] == "not_reviewed"
    assert father["element_quote"] == {"turn": 2, "quote": quote}                 # 검토자가 볼 근거
    assert {"person_relation_missing", "person_relation_not_human_confirmed"} <= set(s["decision_reasons"])
    assert s["generation_prompt"] is None and OPEN in s["draft_prompt"]["scene_block"]
    assert s["checks"]["quote_match"]["state"] == "all" and s["checks"]["people_and_action"]["state"] == "not_checked"


def test_wrong_relation_with_matching_quotes_is_structure_ok_but_meaning_unchecked():
    """인용은 일치하지만 관계가 틀린 응답 — 아버지를 나르기의 co_actor 로, 사과를 딴 구절을 근거로 댔다."""
    father = el("p3", "person", "아버지", 2, "아버지는 사다리에 올라가", relation=rel("a1", "co_actor", "아버지는 사다리에 올라가 사과를 땄어요"))
    s = scene3(V3 + [father])
    row = next(r for r in s["people_review"] if r["text"] == "아버지")
    assert row["code"]["state"] == "structure_ok" and row["human"] == "not_reviewed"        # 코드는 틀린 줄 모른다
    assert s["checks"]["people_and_action"]["state"] == "not_checked" and s["generation_prompt"] is None


def test_participant_from_another_sentence_is_kept_with_both_quotes():
    """참여 근거가 행동과 다른 문장에 있다 — 문장 위치로 빼지 않고 두 근거를 함께 보여 준다."""
    d = carry_story()
    d["source"]["utterances"][1]["elder"] += " 궤짝이 무거워서 누나랑 둘이 메고도 자꾸 쉬었어요."
    sister = el("p4", "person", "누나", 2, "누나랑 둘이 메고도",
                relation=rel("a1", "co_actor", "누나랑 둘이 메고도 자꾸 쉬었어요", "사과 궤짝을 창고까지 날랐어요"))
    s = scene3([A1, ME, sister, CRATE, AGE, ORCHARD], data=d, summary="열 살쯤 누나와 둘이서 사과 궤짝을 창고까지 날랐다.")
    row = next(r for r in s["people_review"] if r["text"] == "누나")
    assert row["code"] == {"state": "structure_ok", "evidence_matched": 2, "evidence_total": 2}
    assert len(row["proposed"]["evidence"]) == 2 and "누나" in s["draft_prompt"]["scene_block"]
    assert "e3" in s["checks"]["same_moment"]["elements_from_other_sentences"]   # 사실로만 적는다
    assert "elements_from_other_sentences" not in s["decision_reasons"]          # 그것만으로 사유가 되지 않는다


def test_same_person_can_be_proposed_for_their_own_action():
    """아버지가 사과를 따는 별도 장면 — 그 행동의 근거가 있으면 참여자로 제안할 수 있다."""
    els = [el("a1", "action", "사다리에 올라가 사과를 땄다", 2, "아버지는 사다리에 올라가 사과를 땄어요"),
           el("p1", "person", "아버지", 2, "아버지는 사다리에 올라가", relation=rel("a1", "actor", "아버지는 사다리에 올라가 사과를 땄어요")),
           el("o1", "object", "사다리", 2, "사다리에 올라가", relation=rel("a1", "used", "사다리에 올라가 사과를 땄어요"))]
    kw = dict(summary="아버지는 사다리에 올라가 사과를 땄다.")
    s = scene3(els, **kw)
    assert s["people_review"][0]["code"]["state"] == "structure_ok" and s["decision"] == "review"
    assert scene3(els, confirm="confirmed", **kw)["decision"] == "eligible"


def test_person_tied_to_another_action_is_left_out_of_this_picture():
    els = V3 + [el("a2", "action", "사다리에 올라가 사과를 땄다", 2, "아버지는 사다리에 올라가 사과를 땄어요"),
                el("p3", "person", "아버지", 2, "아버지는 사다리에 올라가", relation=rel("a2", "actor", "아버지는 사다리에 올라가 사과를 땄어요"))]
    s = scene3(els)
    block = s["draft_prompt"]["scene_block"]
    assert "아버지" not in block and "사다리" not in block                          # 다른 행동과 그 사람은 넣지 않는다
    assert s["checks"]["central_action"] == {"state": "declared", "element": "e1", "other_actions": ["e7"]}
    assert next(r for r in s["people_review"] if r["text"] == "아버지")["code"]["state"] == "other_action"


def test_carry_and_rest_together_without_a_central_action():
    d = carry_story()
    d["source"]["utterances"][1]["elder"] += " 궤짝이 무거워서 얼마 못 가서 세워 놓고 쉬었지요."
    els = V3 + [el("a2", "action", "얼마 못 가서 세워 놓고 쉬었다", 2, "얼마 못 가서 세워 놓고 쉬었지요")]
    s = scene3(els, data=d, central=None)
    assert s["central_action"] is None and s["checks"]["central_action"]["state"] == "missing"
    assert "central_action_missing" in s["decision_reasons"]
    block = s["draft_prompt"]["scene_block"]                              # 검토자가 둘 다 보고 고른다
    assert "사과 궤짝을 창고까지 날랐다" in block and "세워 놓고 쉬었다" in block
    picked = scene3(els, data=d, central="a2")                            # 쉬는 순간을 고르면 나르기는 빠진다
    assert picked["central_action"]["text"] == "얼마 못 가서 세워 놓고 쉬었다"
    assert "창고까지 날랐다" not in picked["draft_prompt"]["scene_block"]


def test_central_action_pointing_nowhere_is_recorded():
    s = scene3(V3, central="zz")
    assert s["checks"]["central_action"]["state"] == "invalid" and "central_action_invalid" in s["decision_reasons"]


def test_missing_key_object_is_recorded():
    s = scene3([e for e in V3 if e["kind"] != "object"])
    assert "object_not_listed" in s["decision_reasons"] and "- 사물" not in s["draft_prompt"]["scene_block"]


def test_evidence_that_is_not_in_the_source_is_recorded():
    bro = el("p2", "person", "형", 2, "형이랑 둘이서", relation=rel("a1", "co_actor", "형이 앞장서서 궤짝을 들었어요"))
    s = scene3([A1, ME, bro, CRATE, AGE, ORCHARD])
    assert next(r for r in s["people_review"] if r["text"] == "형")["code"]["state"] == "evidence_not_found"
    assert "person_relation_evidence_not_found" in s["decision_reasons"]


def test_title_dropping_the_hedge_and_setting_turned_into_the_spot_are_caught():
    s = scene3(V3, title="열 살에 사과 궤짝 나르기", summary="열 살쯤 과수원 앞에서 형과 둘이서 사과 궤짝을 창고까지 날랐다.")
    c = s["checks"]["summary_consistency"]
    assert c["title_certainty_raised"] == ["열 살"] and c["certainty_raised"] == []
    assert c["setting_as_spot"] == [{"where": "summary", "text": "과수원 앞에서"}]
    assert {"certainty_raised", "summary_setting_as_spot"} <= set(s["decision_reasons"])


def test_setting_phrase_that_is_literally_in_the_source_is_not_caught():
    """한계 — 원문에 「과수원에서」 가 다른 행동의 자리로 나오면, 요약이 그 말을 나르기의 자리로 써도 코드는 모른다."""
    d = carry_story()
    d["source"]["utterances"][1]["elder"] += " 아버지는 과수원에서 하루 종일 일했어요."
    s = scene3(V3, data=d, summary="열 살쯤 과수원에서 형과 둘이서 사과 궤짝을 창고까지 날랐다.")
    assert s["checks"]["summary_consistency"]["setting_as_spot"] == []
    assert "time_place_object" in tool.REVIEW_ITEMS


@pytest.mark.parametrize("broken", [
    {"relation": {"action": "a1", "role": "carrier", "evidence": []}},
    {"relation": {"action": "a1", "role": "actor"}},
    {"relation": {"action": "a1", "role": "actor", "evidence": [{"quote": "형이랑"}]}},
    {"key": ""},
])
def test_bad_relation_shape_is_refused(broken):
    c = cand3([A1, {**BROTHER, **broken}, CRATE])
    with pytest.raises(il.IllustError):
        il.run(carry_story(), call=lambda s, u: json.dumps({"candidates": [c]}, ensure_ascii=False))


def test_relation_on_a_place_and_duplicate_keys_are_refused():
    for elements in ([A1, {**ORCHARD, "relation": rel("a1", "used", CARRY)}], [A1, {**CRATE, "key": "a1"}]):
        with pytest.raises(il.IllustError):
            il.run(carry_story(), call=lambda s, u: json.dumps({"candidates": [cand3(elements)]}, ensure_ascii=False))


def test_review_sheet_lists_each_relation_for_the_human(tmp_path, capsys):
    mock = tmp_path / "m.json"
    mock.write_text(json.dumps({"candidates": [cand3(V3)]}, ensure_ascii=False), encoding="utf-8")
    seed_file = tmp_path / "s.json"
    seed_file.write_text(json.dumps(carry_story(), ensure_ascii=False), encoding="utf-8")
    assert tool.main(["--input", str(seed_file), "--mock", str(mock), "--out", str(tmp_path / "o")]) == 0
    capsys.readouterr()
    sheet = json.loads((tmp_path / "o" / "human_review.json").read_text(encoding="utf-8"))
    rels = sheet["scenes"][0]["relations"]
    assert sheet["reviewer"] is None and [r["text"] for r in rels] == ["나", "형"]
    assert all(r["human"] == "not_reviewed" and r["relation_id"] and r["evidence"] for r in rels)
    conf = tmp_path / "c.json"
    conf.write_text(json.dumps({"reviewer": "시험용 확인(사람 아님)",
                                "relations": {r["relation_id"]: "confirmed" for r in rels}}, ensure_ascii=False), encoding="utf-8")
    assert tool.main(["--input", str(seed_file), "--mock", str(mock), "--confirmations", str(conf), "--out", str(tmp_path / "o2")]) == 0
    capsys.readouterr()
    res = json.loads((tmp_path / "o2" / "result.json").read_text(encoding="utf-8"))
    assert res["human_confirmations"] == {"reviewer": "시험용 확인(사람 아님)", "relations": 2, "applied": 2, "unused": 0,
                                          "scenes": 0, "scenes_applied": 0, "scenes_unused": 0}
    assert res["scenes"][0]["people_review"][0]["human"] == "confirmed"


# ---------------------------------------------------------------- 6차 — 오래된 확인 기록이 달라진 관계에 붙지 않는가

def _confirmation_for(elements, data=None, **kw) -> dict:
    """합성 자료의 한 후보를 사람이 확인한 것처럼 만든 기록 (시험용 — 사람 아님)."""
    first = run(data or carry_story(), [cand3(elements, **kw)])["scenes"][0]
    return {"reviewer": "시험용 확인(사람 아님)", "relations": {r["relation_id"]: "confirmed" for r in first["people_review"]}}


def _rerun(elements, conf, data=None, **kw) -> dict:
    reply = json.dumps({"candidates": [cand3(elements, **kw)]}, ensure_ascii=False)
    return il.run(data or carry_story(), call=lambda s, u: reply, confirmations=conf)


def _humans(result) -> dict:
    return {r["text"]: r["human"] for r in result["scenes"][0]["people_review"]}


def test_confirmation_applies_to_the_same_relation_again():
    conf = _confirmation_for(V3)
    r = _rerun(V3, conf)
    assert _humans(r) == {"나": "confirmed", "형": "confirmed"}
    assert r["human_confirmations"] == {"reviewer": "시험용 확인(사람 아님)", "relations": 2, "applied": 2, "unused": 0,
                                          "scenes": 0, "scenes_applied": 0, "scenes_unused": 0}


def test_confirmation_does_not_follow_a_changed_central_action():
    """같은 사람 · 같은 근거 인용이어도 그릴 행동이 바뀌면 다시 확인해야 한다."""
    conf = _confirmation_for(V3)
    other = el("a1", "action", "사과 궤짝을 창고에 쌓았다", 2, CARRY)
    r = _rerun([other] + V3[1:], conf)
    assert _humans(r) == {"나": "not_reviewed", "형": "not_reviewed"} and r["scenes"][0]["generation_prompt"] is None
    assert r["human_confirmations"]["applied"] == 0 and r["human_confirmations"]["unused"] == 2


def test_confirmation_does_not_follow_a_changed_central_action_quote():
    d = carry_story()
    d["source"]["utterances"][1]["elder"] += " 다음 날에도 사과 궤짝을 창고까지 날랐어요."
    conf = _confirmation_for(V3, data=d)
    other = el("a1", "action", "사과 궤짝을 창고까지 날랐다", 2, "다음 날에도 사과 궤짝을 창고까지 날랐어요")
    assert _humans(_rerun([other] + V3[1:], conf, data=d)) == {"나": "not_reviewed", "형": "not_reviewed"}


def test_confirmation_does_not_follow_changed_evidence():
    conf = _confirmation_for(V3)
    bro = el("p2", "person", "형", 2, "형이랑 둘이서", relation=rel("a1", "co_actor", "형이랑 둘이서"))
    assert _humans(_rerun([A1, ME, bro, CRATE, AGE, ORCHARD], conf)) == {"나": "confirmed", "형": "not_reviewed"}


def test_confirmation_does_not_follow_a_changed_role():
    """「함께 한 사람」 으로 확인한 것을 「받은 사람」 에 쓰면 안 된다."""
    conf = _confirmation_for(V3)
    bro = {**BROTHER, "relation": {**BROTHER["relation"], "role": "recipient"}}
    assert _humans(_rerun([A1, ME, bro, CRATE, AGE, ORCHARD], conf))["형"] == "not_reviewed"


def test_confirmation_does_not_follow_a_relation_that_appears_or_disappears():
    """관계 칸 없이(옛 응답) 확인한 것은 관계 칸이 생긴 응답에 붙지 않는다 — 그 반대도."""
    legacy = [{k: v for k, v in e.items() if k != "relation"} for e in V3]
    assert set(_humans(_rerun(V3, _confirmation_for(legacy))).values()) == {"not_reviewed"}
    assert set(_humans(_rerun(legacy, _confirmation_for(V3))).values()) == {"not_reviewed"}


def test_confirmation_does_not_follow_a_changed_source_text():
    """인용은 그대로 원문에 있어도 그 턴의 말씀이 달라졌으면(다른 원문 · 고친 원문) 다시 확인해야 한다."""
    conf = _confirmation_for(V3)
    d = carry_story()
    d["source"]["utterances"][1]["elder"] += " 그런데 그건 형이 아니라 사촌이었어요."
    assert set(_humans(_rerun(V3, conf, data=d)).values()) == {"not_reviewed"}


def test_confirmation_does_not_follow_another_chapter_or_person():
    conf = _confirmation_for(V3)
    d = carry_story()
    d["memoir"]["chapters"][0]["chapter_key"] = "e77"                      # 같은 번호의 다른 장(식별자가 다르다)
    assert set(_humans(_rerun(V3, conf, data=d)).values()) == {"not_reviewed"}
    cousin = {**BROTHER, "text": "둘이"}
    assert _humans(_rerun([A1, ME, cousin, CRATE, AGE, ORCHARD], conf))["둘이"] == "not_reviewed"


def test_review_sheet_shows_everything_for_one_candidate(tmp_path, capsys):
    """한 후보에서 함께 읽혀야 하는 것 — 중심 행동(인용 · 턴) · 인물별 제안 관계 · 근거 인용과 턴 · 코드 결과 · 사람의 상태."""
    mock, seed_file = tmp_path / "m.json", tmp_path / "s.json"
    mock.write_text(json.dumps({"candidates": [cand3(V3)]}, ensure_ascii=False), encoding="utf-8")
    seed_file.write_text(json.dumps(carry_story(), ensure_ascii=False), encoding="utf-8")
    assert tool.main(["--input", str(seed_file), "--mock", str(mock), "--out", str(tmp_path / "o")]) == 0
    capsys.readouterr()
    sc = json.loads((tmp_path / "o" / "human_review.json").read_text(encoding="utf-8"))["scenes"][0]
    assert sc["central_action"] == {"element": "e1", "text": "사과 궤짝을 창고까지 날랐다", "state": "declared",
                                    "turn": 2, "quote": CARRY}
    assert sc["scene_summary"] and sc["draft_scene_block"].startswith("[그릴 장면]")
    r = sc["relations"][1]
    assert set(r) >= {"relation_id", "text", "proposed", "evidence", "element_quote", "code", "human", "note"}
    assert r["proposed"] == BROTHER["relation"] and r["evidence"] == [{"turn": 2, "quote": CARRY}]
    assert (r["code"], r["human"]) == ("structure_ok", "not_reviewed")


def test_confirmation_does_not_follow_a_changed_relation_target():
    conf = _confirmation_for(V3)
    brother = {**BROTHER, "relation": {**BROTHER["relation"], "action": "a2"}}
    result = _rerun([A1, ME, brother, CRATE, AGE, ORCHARD], conf)
    row = next(r for r in result["scenes"][0]["people_review"] if r["text"] == "형")
    assert row["code"]["state"] == "other_action"
    assert row["human"] == "not_reviewed"
    assert result["human_confirmations"]["unused"] == 1


def test_confirmation_does_not_follow_a_changed_person_quote():
    conf = _confirmation_for(V3)
    brother = {**BROTHER, "quote": CARRY}
    result = _rerun([A1, ME, brother, CRATE, AGE, ORCHARD], conf)
    assert _humans(result) == {"나": "confirmed", "형": "not_reviewed"}
    assert result["scenes"][0]["generation_prompt"] is None


@pytest.mark.parametrize("change", ["session", "local_turn"])
def test_confirmation_does_not_follow_changed_source_identity(change):
    data = carry_story()
    conf = _confirmation_for(V3, data=data)
    mapping = next(m for m in data["source"]["turn_map"] if m["global_turn"] == 2)
    if change == "session":
        data["source"]["utterances"][1]["session_id"] = "another-session"
        mapping["session_id"] = "another-session"
    else:
        mapping["turn"] = 99
    result = _rerun(V3, conf, data=data)
    assert set(_humans(result).values()) == {"not_reviewed"}
    assert result["human_confirmations"]["applied"] == 0
    assert result["scenes"][0]["generation_prompt"] is None


# ---------------------------------------------------------------- 화자 표기 · 빠진 참여자 검토 · 보완 초안

@pytest.mark.parametrize("name", ["나", "저", "제가", "내가", "저는", "나는", "저도", "제", "내"])
def test_self_forms_are_written_as_the_narrator(name):
    """「제가」 로 적혀 와도 지시문에는 화자 표시로 쓴다 — 요소의 원래 이름과 인용은 그대로 둔다."""
    quote = "제가 형이랑 둘이서"
    s = one_confirmed(polite_story(), APPLE + [("person", name, 2, quote)])
    e = s["elements"][-1]
    assert (e["text"], e["quote"], e["is_self"], e["status"]) == (name, quote, True, "quoted")
    assert f"- 인물: {il.SELF_LABEL}" in s["generation_prompt"]["scene_block"]
    assert name + "," not in s["generation_prompt"]["scene_block"].split("- 인물:")[1].split("\n")[0]
    assert s["people_review"][0]["text"] == name                       # 검토 기록에도 원래 이름


@pytest.mark.parametrize("name,quote", [("저희", "저희 집은 장터에서 멀었어요"), ("저희 집", "저희 집은 장터에서 멀었어요"),
                                         ("우리", "저희 집은 장터에서 멀었어요")])
def test_group_words_are_not_turned_into_the_narrator(name, quote):
    s = one(polite_story(), APPLE + [("person", name, 2, quote)])
    e = s["elements"][-1]
    assert e["is_self"] is False
    assert il.SELF_LABEL not in s["draft_prompt"]["scene_block"]


def test_our_mother_is_not_the_narrator():
    d = polite_story()
    d["source"]["utterances"][1]["elder"] += " 우리 어머니가 옆에서 보고 계셨어요."
    s = one(d, APPLE + [("person", "우리 어머니", 2, "우리 어머니가 옆에서 보고 계셨어요")])
    assert s["elements"][-1]["is_self"] is False and "우리 어머니" in s["draft_prompt"]["scene_block"]
    assert il.SELF_LABEL not in s["draft_prompt"]["scene_block"]


def test_self_name_needs_a_self_word_in_the_quote():
    """이름이 「제가」 여도 인용에 「저희 집」 뿐이면 본인이 거기 있었다는 근거가 아니다."""
    s = one(polite_story(), APPLE + [("person", "제가", 2, "저희 집은 장터에서 멀었어요")])
    assert s["elements"][-1]["status"] == "paraphrased" and il.SELF_LABEL not in s["draft_prompt"]["scene_block"]


def _both(first, relations="confirmed", scenes="complete") -> dict:
    return {"reviewer": TEST_REVIEWER,
            "relations": {r["relation_id"]: relations for s in first["scenes"] for r in s["people_review"]} if relations else {},
            "scenes": {s["participants_review"]["scene_review_id"]: scenes for s in first["scenes"]} if scenes else {}}


NO_AGE = [e for e in V3 if e["kind"] != "time"]


def clean_story() -> dict:
    """불확실 표지가 없는 합성 원문 — 사람 확인만 남도록."""
    d = carry_story()
    d["source"]["utterances"][1]["elder"] = d["source"]["utterances"][1]["elder"].replace("제가 열 살쯤 되던 해였는데 ", "제가 ")
    return d


ME2 = el("p1", "person", "제가", 2, "제가 형이랑 둘이서", relation=rel("a1", "actor", "제가 형이랑 둘이서 사과 궤짝을 창고까지 날랐어요"))
CLEAN = [A1, ME2, BROTHER, CRATE, ORCHARD]
CLEAN_KW = dict(summary="형과 둘이서 사과 궤짝을 창고까지 날랐다.")


def test_confirming_every_proposed_person_does_not_say_nobody_is_missing():
    """제안된 인물의 관계를 모두 확인해도 「빠진 참여자가 없다」 는 따로 확인해야 한다."""
    cands = [cand3(CLEAN, **CLEAN_KW)]
    first = raw_run(clean_story(), cands)
    only_people = raw_run(clean_story(), cands, _both(first, scenes=None))
    s = only_people["scenes"][0]
    assert {r["human"] for r in s["people_review"]} == {"confirmed"}
    assert s["checks"]["people_and_action"]["state"] == "human_confirmed"       # 사람 하나하나는 확인됐다
    assert s["checks"]["participants_complete"]["state"] == "not_checked"       # 그래도 이것은 아니다
    assert s["participants_review"]["human"] == "not_reviewed"
    assert s["decision"] == "review" and s["generation_prompt"] is None
    assert s["decision_reasons"] == ["participants_completeness_not_human_confirmed"]
    assert il.PEOPLE_INCOMPLETE in s["draft_prompt"]["scene_block"]
    both = raw_run(clean_story(), cands, _both(first))["scenes"][0]
    assert both["decision"] == "eligible" and both["checks"]["participants_complete"]["state"] == "human_complete"
    assert both["generation"]["user_selected"] is False and both["generation"]["image_status"] == "not_requested"


def test_scene_marked_incomplete_stays_blocked():
    cands = [cand3(CLEAN, **CLEAN_KW)]
    first = raw_run(clean_story(), cands)
    s = raw_run(clean_story(), cands, _both(first, scenes="incomplete"))["scenes"][0]
    assert "participants_marked_incomplete" in s["decision_reasons"] and s["generation_prompt"] is None


def test_scene_without_any_proposed_person_also_needs_the_completeness_review():
    s = raw_run(seed(), [cand(APPLE)])["scenes"][0]
    assert s["people_review"] == [] and s["decision"] == "review"
    assert "participants_completeness_not_human_confirmed" in s["decision_reasons"]


def test_symbolic_scene_has_no_participants_to_review():
    d = seed()
    d["photos"] = []
    s = raw_run(d, [cand(SPOON, chapter_no=2)])["scenes"][0]
    assert (s["decision"], s["participants_review"]["human"]) == ("eligible", "not_required")
    assert s["checks"]["participants_complete"]["state"] == "not_applicable"


def test_reviewer_reads_the_source_context_next_to_the_people():
    s = raw_run(carry_story(), [cand3([A1, ME, CRATE, AGE, ORCHARD], summary="열 살쯤 사과 궤짝을 창고까지 날랐다.")])["scenes"][0]
    pr = s["participants_review"]
    assert pr["proposed_people"] == ["나"] and pr["human"] == "not_reviewed"
    assert pr["context"][0]["turn"] == 2 and "형이랑 둘이서 사과 궤짝을 창고까지 날랐어요" in pr["context"][0]["text"]
    assert pr["context"][0]["central_sentences"] == [1]                 # 그릴 행동의 인용이 든 문장
    # 코드가 알려 주는 범위 — 「형이랑 둘이서」 꼴
    assert pr["possible_omitted"] == [{"turn": 2, "name": "형", "quote": "제가 열 살쯤 되던 해였는데 형이랑 둘이서 사과 궤짝을 창고까지 날랐어요"}]
    assert "possible_participant_omitted" in s["decision_reasons"]
    assert "형" not in s["draft_prompt"]["scene_block"]                  # 알릴 뿐 채우지 않는다


def test_omission_that_is_not_in_the_with_pattern_is_not_hinted():
    """한계 — 「형도 같이 들었어요」 처럼 다른 꼴이면 코드는 알리지 못한다. 사람이 문맥을 읽어야 한다."""
    d = carry_story()
    d["source"]["utterances"][1]["elder"] = (
        "과수원이 우리 집 바로 뒤에 있었어요. 제가 사과 궤짝을 창고까지 날랐어요. 형도 한쪽을 들어 줬어요.")
    els = [el("a1", "action", "사과 궤짝을 창고까지 날랐다", 2, "제가 사과 궤짝을 창고까지 날랐어요"),
           el("p1", "person", "제가", 2, "제가 사과 궤짝을", relation=rel("a1", "actor", "제가 사과 궤짝을 창고까지 날랐어요")),
           el("o1", "object", "사과 궤짝", 2, "사과 궤짝을 창고까지 날랐어요", relation=rel("a1", "acted_on", "사과 궤짝을 창고까지 날랐어요"))]
    s = raw_run(d, [cand3(els, summary="사과 궤짝을 창고까지 날랐다.")])["scenes"][0]
    assert s["participants_review"]["possible_omitted"] == []
    assert "형도 한쪽을 들어 줬어요" in s["participants_review"]["context"][0]["text"]     # 그래도 문맥은 보인다
    assert "participants_completeness_not_human_confirmed" in s["decision_reasons"]


def test_adding_a_person_resets_the_no_one_missing_review():
    """함께 한 사람을 더하는 꼴 — 사람을 더한 뒤에는 앞 장면의 「누락 없음」 판단이 따라오지 않는다. 인물별 확인은 그 사람 것만 남는다."""
    alone = [A1, ME2, CRATE, ORCHARD]
    before = raw_run(clean_story(), [cand3(alone, summary="사과 궤짝을 창고까지 날랐다.")])
    conf = _both(before)                                                # 「제가」 confirmed · 장면 complete
    assert raw_run(clean_story(), [cand3(alone, summary="사과 궤짝을 창고까지 날랐다.")], conf)["scenes"][0]["decision"] == "eligible"
    after = raw_run(clean_story(), [cand3(CLEAN, **CLEAN_KW)], conf)
    s = after["scenes"][0]
    assert {r["text"]: r["human"] for r in s["people_review"]} == {"제가": "confirmed", "형": "not_reviewed"}
    assert s["participants_review"]["human"] == "not_reviewed" and s["generation_prompt"] is None
    assert after["human_confirmations"]["scenes_applied"] == 0 and after["human_confirmations"]["scenes_unused"] == 1


def test_removing_a_person_or_changing_the_action_also_resets_it():
    cands = [cand3(CLEAN, **CLEAN_KW)]
    conf = _both(raw_run(clean_story(), cands))
    without = raw_run(clean_story(), [cand3([A1, ME2, CRATE, ORCHARD], **CLEAN_KW)], conf)["scenes"][0]
    assert without["participants_review"]["human"] == "not_reviewed"
    other = el("a1", "action", "사과 궤짝을 창고에 쌓았다", 2, CARRY)
    assert raw_run(clean_story(), [cand3([other] + CLEAN[1:], **CLEAN_KW)], conf)["scenes"][0]["participants_review"]["human"] == "not_reviewed"
    d = clean_story()
    d["source"]["utterances"][1]["elder"] += " 누나도 같이 했어요."
    assert raw_run(d, cands, conf)["scenes"][0]["participants_review"]["human"] == "not_reviewed"   # 원문이 달라져도


def test_bad_scene_confirmation_is_refused():
    with pytest.raises(il.IllustError):
        raw_run(clean_story(), [cand3(CLEAN, **CLEAN_KW)], {"reviewer": "가", "relations": {}, "scenes": {"x": "ok"}})


def test_amended_draft_shows_what_was_added_and_who_wrote_it(tmp_path, capsys):
    """원본 후보는 그대로 두고, 사람을 더한 보완 초안과의 차이를 검토자가 읽을 수 있다."""
    original = {"candidates": [cand3([A1, ME2, CRATE, ORCHARD], summary="사과 궤짝을 창고까지 날랐다.")]}
    amended = {"amendment": {"author": "시험용 AI", "author_is_human": False, "reason": "함께 한 형이 빠졌다"},
               "candidates": [cand3(CLEAN, **CLEAN_KW)]}
    files = {}
    for name, doc in (("seed", clean_story()), ("orig", original), ("amend", amended)):
        files[name] = tmp_path / f"{name}.json"
        files[name].write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert tool.main(["--input", str(files["seed"]), "--mock", str(files["orig"]), "--out", str(tmp_path / "o1")]) == 0
    before = (tmp_path / "o1" / "candidates.json").read_text(encoding="utf-8")
    assert tool.main(["--input", str(files["seed"]), "--mock", str(files["amend"]),
                      "--compare-to", str(tmp_path / "o1" / "candidates.json"), "--out", str(tmp_path / "o2")]) == 0
    capsys.readouterr()
    assert (tmp_path / "o1" / "candidates.json").read_text(encoding="utf-8") == before        # 원본은 그대로
    ch = json.loads((tmp_path / "o2" / "changes.json").read_text(encoding="utf-8"))
    row = ch["changes"][0]
    assert ch["amendment"]["author"] == "시험용 AI" and ch["amendment"]["author_is_human"] is False
    assert [e["text"] for e in row["elements_added"]] == ["형"] and row["elements_removed"] == []
    assert row["elements_added"][0]["relation"]["evidence"] == BROTHER["relation"]["evidence"]
    assert row["fields_changed"]["scene_summary"]["to"] == CLEAN_KW["summary"]
    sheet = json.loads((tmp_path / "o2" / "human_review.json").read_text(encoding="utf-8"))
    assert sheet["amendment"]["human_review_of_amendment"] == "not_reviewed" and sheet["amendment"]["changes"] == ch["changes"]
    sc = sheet["scenes"][0]
    assert sc["participants_review"]["human"] == "not_reviewed" and {r["human"] for r in sc["relations"]} == {"not_reviewed"}
    res = json.loads((tmp_path / "o2" / "result.json").read_text(encoding="utf-8"))
    assert res["scenes"][0]["generation_prompt"] is None                 # 보완 초안도 사람이 확인하기 전에는 확정되지 않는다
    assert json.loads((tmp_path / "o2" / "run.json").read_text(encoding="utf-8"))["amendment"]["author"] == "시험용 AI"


def test_amendment_without_an_author_is_refused(tmp_path, capsys):
    seed_file, mock = tmp_path / "s.json", tmp_path / "m.json"
    seed_file.write_text(json.dumps(clean_story(), ensure_ascii=False), encoding="utf-8")
    mock.write_text(json.dumps({"candidates": [cand3(CLEAN, **CLEAN_KW)]}, ensure_ascii=False), encoding="utf-8")
    assert tool.main(["--input", str(seed_file), "--mock", str(mock), "--out", str(tmp_path / "o1")]) == 0
    assert tool.main(["--input", str(seed_file), "--mock", str(mock),
                      "--compare-to", str(tmp_path / "o1" / "candidates.json"), "--out", str(tmp_path / "o2")]) == 1
    capsys.readouterr()
    assert not (tmp_path / "o2" / "human_review.json").exists()


def test_diff_reports_removed_and_changed_elements():
    a = [cand3(CLEAN, **CLEAN_KW)]
    b = [cand3([A1, {**ME2, "text": "나"}, CRATE, ORCHARD], **CLEAN_KW)]
    row = il.diff_candidates(a, b)[0]
    assert [e["text"] for e in row["elements_removed"]] == ["형"]
    assert row["elements_changed"][0]["from"]["text"] == "제가" and row["elements_changed"][0]["to"]["text"] == "나"
    assert il.diff_candidates(a, a)[0]["elements_added"] == [] and il.diff_candidates(a, [])[0]["change"] == "candidate_removed"


def test_sheet_reflects_only_what_the_confirmation_record_covers(tmp_path, capsys):
    """확인 기록이 덮는 칸(검토자 · 관계 · 장면 · who_did_what · 보완 초안 채택)만 채우고 나머지는 not_reviewed 로 둔다."""
    files = {}
    original = {"candidates": [cand3([A1, ME2, CRATE, ORCHARD], summary="사과 궤짝을 창고까지 날랐다.")]}
    amended = {"amendment": {"author": "시험용 AI", "author_is_human": False}, "candidates": [cand3(CLEAN, **CLEAN_KW)]}
    for name, doc in (("seed", clean_story()), ("orig", original), ("amend", amended)):
        files[name] = tmp_path / f"{name}.json"
        files[name].write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert tool.main(["--input", str(files["seed"]), "--mock", str(files["orig"]), "--out", str(tmp_path / "o1")]) == 0
    conf = {**_both(raw_run(clean_story(), amended["candidates"])), "amendment_review": "adopted", "statement": "둘이 나르는 장면으로 한다"}
    (tmp_path / "c.json").write_text(json.dumps(conf, ensure_ascii=False), encoding="utf-8")
    args = ["--input", str(files["seed"]), "--mock", str(files["amend"]), "--compare-to", str(tmp_path / "o1" / "candidates.json")]
    assert tool.main(args + ["--confirmations", str(tmp_path / "c.json"), "--out", str(tmp_path / "o2")]) == 0
    assert tool.main(args + ["--out", str(tmp_path / "o3")]) == 0
    capsys.readouterr()
    sheet = json.loads((tmp_path / "o2" / "human_review.json").read_text(encoding="utf-8"))
    sc = sheet["scenes"][0]
    assert sheet["reviewer"] == TEST_REVIEWER and sheet["confirmation_record"]["statement"] == "둘이 나르는 장면으로 한다"
    assert "relations" not in sheet["confirmation_record"]
    assert sheet["amendment"]["author"] == "시험용 AI" and sheet["amendment"]["human_review_of_amendment"] == "adopted"
    assert sc["items"]["who_did_what"]["verdict"] == "ok"
    assert {v["verdict"] for k, v in sc["items"].items() if k != "who_did_what"} == {"not_reviewed"}
    assert json.loads((tmp_path / "o2" / "confirmations.json").read_text(encoding="utf-8")) == conf
    res = json.loads((tmp_path / "o2" / "result.json").read_text(encoding="utf-8"))["scenes"][0]
    assert res["generation"]["user_selected"] is False and res["generation"]["user_approved"] is False   # 장면 내용 확인이지 생성 선택이 아니다
    plain = json.loads((tmp_path / "o3" / "human_review.json").read_text(encoding="utf-8"))
    assert plain["reviewer"] is None and plain["amendment"]["human_review_of_amendment"] == "not_reviewed"
    assert plain["scenes"][0]["items"]["who_did_what"]["verdict"] == "not_reviewed"


# ---------------------------------------------------------------- 사람 확인 뒤에 남는 경고 — 좁게 푼다 · 원래 결과는 남긴다

def _full(first, texts=True) -> dict:
    """인물 관계 · 장면 검토 · (검토 때 본 제목과 요약)을 시험용으로 확인한 기록."""
    conf = _both(first)
    if texts:
        conf["scene_texts"] = {s["participants_review"]["scene_review_id"]: {"scene_title": s["scene_title"],
                                                                            "scene_summary": s["scene_summary"]}
                               for s in first["scenes"]}
    return conf


def _causes(s) -> dict:
    return {(x["text"], x["cause"]): x["resolved_by"] for x in s["verification_review"]["causes"]}


AGE_KW = dict(summary="열 살쯤 형과 둘이서 사과 궤짝을 창고까지 날랐다.")


def test_age_hedge_that_is_kept_does_not_make_the_person_or_action_uncertain():
    """「제가 열 살쯤 되던 해였는데 …」 — 「쯤」 은 나이의 것이다. 때 요소 · 요약이 지켰으면 사람 · 행동의 불확실로 보지 않는다."""
    cands = [cand3(V3, **AGE_KW)]
    first = raw_run(carry_story(), cands)
    s0 = first["scenes"][0]
    me = next(e for e in s0["elements"] if e["text"] == "나")
    assert me["flags"] == ["uncertain"] and me["hedge_scope"] == {"kind": "age_expression", "ages": ["열살"]}   # 표지는 그대로 있다
    assert _causes(s0)[("나", "uncertain")] == "rule_age_hedge_preserved"
    assert s0["verification"] == "partial"                                 # 자동 검사의 원래 결과를 verified 로 바꾸지 않는다
    assert s0["verification_review"]["effective"] == "no_open_cause" and "verification_partial" not in s0["decision_reasons"]
    s = raw_run(carry_story(), cands, _full(first))["scenes"][0]
    assert s["decision"] == "eligible" and "- 때: 열 살쯤" in s["generation_prompt"]["scene_block"]
    assert s["generation"]["user_selected"] is False and s["generation"]["image_status"] == "not_requested"


def test_age_hedge_dropped_in_title_or_summary_keeps_the_reason():
    for kw in (dict(summary="열 살 때 형과 둘이서 사과 궤짝을 창고까지 날랐다."),
               dict(title="열 살에 사과 궤짝 나르기", **AGE_KW)):
        cands = [cand3(V3, **kw)]
        first = raw_run(carry_story(), cands)
        s = raw_run(carry_story(), cands, _full(first))["scenes"][0]
        assert _causes(s)[("나", "uncertain")] is None and s["verification_review"]["effective"] == "open_causes"
        assert {"verification_partial", "certainty_raised"} <= set(s["decision_reasons"]) and s["generation_prompt"] is None


def test_age_hedge_without_a_time_element_keeps_the_reason():
    """추정을 지켰다고 볼 근거(때 요소)가 없으면 풀지 않는다."""
    cands = [cand3([e for e in V3 if e["kind"] != "time"], summary="형과 둘이서 사과 궤짝을 창고까지 날랐다.")]
    first = raw_run(carry_story(), cands)
    s = raw_run(carry_story(), cands, _full(first))["scenes"][0]
    assert _causes(s)[("나", "uncertain")] is None and "verification_partial" in s["decision_reasons"]


@pytest.mark.parametrize("sentence,quote,name,kind", [
    ("같이 나른 사람이 형이었나 그래요.", "같이 나른 사람이 형이었나 그래요", "형", "person"),
    ("제가 사과 궤짝을 창고까지 날랐던 것 같아요.", "사과 궤짝을 창고까지 날랐던 것 같아요", "사과 궤짝을 창고까지 날랐다", "action"),
    ("열 살쯤 형이랑 간 것 같아요.", "열 살쯤 형이랑 간 것 같아요", "형", "person"),
])
def test_uncertain_person_or_action_stays_for_review(sentence, quote, name, kind):
    """사람 · 행동 자체가 불확실한 말 — 나이의 「쯤」 과 섞여 있어도 좁은 규칙으로 풀지 않는다."""
    d = carry_story()
    d["source"]["utterances"][1]["elder"] += " " + sentence
    extra = el("x1", kind, name, 2, quote, **({"relation": rel("a1", "co_actor", quote)} if kind == "person" else {}))
    els = [e for e in V3 if e["text"] != name] + [extra]
    cands = [cand3(els, central="a1" if kind == "person" else "x1", **AGE_KW)]
    first = raw_run(d, cands)
    s = raw_run(d, cands, _full(first))["scenes"][0]
    e = next(x for x in s["elements"] if x["key"] == "x1")
    assert "uncertain" in e["flags"] and e["hedge_scope"]["kind"] == "other"
    assert _causes(s)[(name, "uncertain")] is None
    assert "verification_partial" in s["decision_reasons"] and s["generation_prompt"] is None


def test_age_hedge_helper():
    assert il._age_hedges("제가 여섯 살쯤 되던 해였는데") == ["여섯살"]
    assert il._age_hedges("내가 열 살쯤이었나") == ["열살", "열살"] and il._age_hedges("1972년 무렵에") == ["1972년"]
    for text in ("형이었나 그래요", "날랐던 것 같다", "여섯 살쯤 형이랑 간 것 같아요", "그때쯤이었어요", "갔나 봐요"):
        assert il._age_hedges(text) is None


def nearby_story() -> dict:
    """합성 — 함께 한 사람이 「못」 이 든 문장에 나온다 (실제 원문 한 항목의 짜임 — 내용은 지어낸 것)."""
    d = clean_story()
    d["source"]["utterances"][1]["elder"] += " 궤짝이 무거워서 누나랑 둘이 메고도 얼마 못 가서 길가에 내려놓고 쉬었어요."
    return d


SISTER = el("p3", "person", "누나", 2, "누나랑 둘이 메고도",
            relation=rel("a1", "co_actor", "사과 궤짝을 창고까지 날랐어요", "누나랑 둘이 메고도"))
WITH_SISTER = [A1, ME2, SISTER, CRATE, ORCHARD]
SISTER_KW = dict(summary="누나와 둘이서 사과 궤짝을 창고까지 날랐다.")


def test_confirmed_relation_covers_the_nearby_negation_and_nothing_more():
    """관계를 확인한 사람은 같은 문장의 「못 가서」 때문에 다시 미확인이 되지 않는다. 표지와 원래 결과는 남는다."""
    cands = [cand3(WITH_SISTER, **SISTER_KW)]
    first = raw_run(nearby_story(), cands)
    s0 = first["scenes"][0]
    assert next(e for e in s0["elements"] if e["text"] == "누나")["flags"] == ["negation_nearby"]
    assert _causes(s0)[("누나", "negation_nearby")] is None                 # 확인 전에는 열려 있다
    s = raw_run(nearby_story(), cands, _full(first))["scenes"][0]
    row = next(x for x in s["verification_review"]["causes"] if x["text"] == "누나")
    assert row["resolved_by"] == "human_relation_confirmed" and row["reviewer"] == TEST_REVIEWER
    assert row["relation_id"] == next(r for r in s["people_review"] if r["text"] == "누나")["relation_id"]
    assert "쉬지 않았다" in row["basis"]                                    # 다른 주장으로 넓히지 않는다는 것을 적는다
    assert next(e for e in s["elements"] if e["text"] == "누나")["flags"] == ["negation_nearby"]   # 표지는 지우지 않는다
    assert s["verification"] == "partial" and s["decision"] == "eligible"
    assert "쉬" not in s["generation_prompt"]["scene_block"] and "못" not in s["generation_prompt"]["scene_block"]


def test_relation_confirmation_does_not_follow_to_a_changed_relation():
    cands = [cand3(WITH_SISTER, **SISTER_KW)]
    conf = _full(raw_run(nearby_story(), cands))
    other = {**SISTER, "relation": rel("a1", "co_actor", "누나랑 둘이 메고도")}                    # 근거가 달라졌다
    s = raw_run(nearby_story(), [cand3([A1, ME2, other, CRATE, ORCHARD], **SISTER_KW)], conf)["scenes"][0]
    assert _causes(s)[("누나", "negation_nearby")] is None and s["generation_prompt"] is None


def test_confirmed_relation_does_not_unblock_a_directly_negated_action():
    """직접 부정된 일 — 「누나는 장터에는 안 갔어요」 — 은 관계 확인으로 풀리지 않는다."""
    d = nearby_story()
    d["source"]["utterances"][1]["elder"] += " 누나는 장터에는 안 갔어요."
    bad = el("p3", "person", "누나", 2, "누나는 장터에는 안 갔어요", relation=rel("a1", "co_actor", "누나는 장터에는 안 갔어요"))
    cands = [cand3([A1, ME2, bad, CRATE, ORCHARD], **SISTER_KW)]
    first = raw_run(d, cands)
    s = raw_run(d, cands, _full(first))["scenes"][0]
    assert next(e for e in s["elements"] if e["text"] == "누나")["status"] == "blocked"
    assert _causes(s)[("누나", "status_blocked")] is None
    assert "verification_partial" in s["decision_reasons"] and s["generation_prompt"] is None


def test_partial_scope_negation_on_the_action_is_not_covered_by_a_person_confirmation():
    """「못 가서 길가에 내려놓고 쉬었다」 를 행동으로 내면 — 사람을 확인했어도 그 행동의 부정 범위는 따로 남는다."""
    rest = el("a1", "action", "얼마 못 가서 길가에 내려놓고 쉬었다", 2, "누나랑 둘이 메고도 얼마 못 가서 길가에 내려놓고 쉬었어요")
    sis = {**SISTER, "relation": rel("a1", "co_actor", "누나랑 둘이 메고도 얼마 못 가서 길가에 내려놓고 쉬었어요")}
    cands = [cand3([rest, ME2, sis, CRATE, ORCHARD], summary="누나와 둘이 메고도 얼마 못 가서 길가에 내려놓고 쉬었다.")]
    first = raw_run(nearby_story(), cands)
    s = raw_run(nearby_story(), cands, _full(first))["scenes"][0]
    assert _causes(s)[("얼마 못 가서 길가에 내려놓고 쉬었다", "negation_partial_scope")] is None
    assert "negation_scope_unclear" in s["decision_reasons"] and s["generation_prompt"] is None


def mother_story() -> dict:
    d = clean_story()
    d["source"]["utterances"][1]["elder"] = d["source"]["utterances"][1]["elder"].replace(
        "형이랑 둘이서 사과 궤짝을", "형이랑 둘이서 아버지가 따 놓은 사과 궤짝을")
    return d


MOTHER_KW = dict(summary="형과 둘이서 아버지가 따 놓은 사과 궤짝을 창고까지 날랐다.")
CARRY2 = "형이랑 둘이서 아버지가 따 놓은 사과 궤짝을 창고까지 날랐어요"
MOTHER_ELS = [el("a1", "action", "사과 궤짝을 창고까지 날랐다", 2, CARRY2),
              el("p1", "person", "제가", 2, "제가 형이랑 둘이서", relation=rel("a1", "actor", "제가 " + CARRY2)),
              el("p2", "person", "형", 2, "형이랑 둘이서", relation=rel("a1", "co_actor", CARRY2)),
              el("o1", "object", "사과 궤짝", 2, "사과 궤짝을 창고까지 날랐어요", relation=rel("a1", "acted_on", "사과 궤짝을 창고까지 날랐어요")),
              ORCHARD]


def test_summary_only_person_is_resolved_only_through_the_reviewed_candidate():
    """요약의 「아버지가 따 놓은 궤짝」 — 실제 「어머니가 캐 오신 자루」 의 짜임. 사람의 장면 검토와 같은 글일 때만 푼다."""
    cands = [cand3(MOTHER_ELS, **MOTHER_KW)]
    first = raw_run(mother_story(), cands)
    assert first["scenes"][0]["checks"]["summary_consistency"]["persons_not_in_elements"] == ["아버지"]
    # ① 장면 검토 complete 만으로는 풀리지 않는다 (검토 때 본 제목 · 요약이 기록에 없다)
    s = raw_run(mother_story(), cands, _full(first, texts=False))["scenes"][0]
    res = s["checks"]["summary_consistency"]["persons_resolution"]
    assert res["unresolved"] == ["아버지"] and res["conditions"] == {"scene_review_complete": True, "same_title_and_summary_as_reviewed": False}
    assert "summary_person_not_in_elements" in s["decision_reasons"] and s["generation_prompt"] is None
    # ② 같은 제목 · 요약을 검토했다는 기록이 있으면 풀린다 — 원래 검사 결과 · 쓴 확인 · 이유가 남는다
    s = raw_run(mother_story(), cands, _full(first))["scenes"][0]
    sc = s["checks"]["summary_consistency"]
    assert sc["persons_not_in_elements"] == ["아버지"] and sc["state"] == "found"          # 원래 결과 그대로
    done = sc["persons_resolution"]["resolved"][0]
    assert (done["name"], done["resolved_by"], done["reviewer"]) == ("아버지", "human_scene_review", TEST_REVIEWER)
    assert done["scene_review_id"] == s["participants_review"]["scene_review_id"] and "그리지 않는 사람" in done["basis"]
    assert "summary_person_not_in_elements" not in s["decision_reasons"] and s["decision"] == "eligible"
    assert "아버지" not in s["generation_prompt"]["scene_block"]


def test_summary_resolution_is_lost_when_the_summary_or_people_change():
    cands = [cand3(MOTHER_ELS, **MOTHER_KW)]
    conf = _full(raw_run(mother_story(), cands))
    # 요약이 달라졌다 — 장면 식별값은 같아 complete 는 남지만, 요약의 경고는 다시 열린다
    changed = [cand3(MOTHER_ELS, summary="형과 아버지와 함께 사과 궤짝을 창고까지 날랐다.")]
    s = raw_run(mother_story(), changed, conf)["scenes"][0]
    assert s["participants_review"]["human"] == "complete"
    assert s["checks"]["summary_consistency"]["persons_resolution"]["unresolved"] == ["아버지"]
    assert "summary_person_not_in_elements" in s["decision_reasons"] and s["generation_prompt"] is None
    # 참여자가 달라졌다 — 장면 검토부터 다시다
    fewer = [cand3([e for e in MOTHER_ELS if e["text"] != "형"], **MOTHER_KW)]
    s = raw_run(mother_story(), fewer, conf)["scenes"][0]
    assert s["participants_review"]["human"] == "not_reviewed"
    assert "아버지" in s["checks"]["summary_consistency"]["persons_resolution"]["unresolved"]


def test_summary_person_that_would_be_drawn_is_not_resolved():
    """그 사람이 그림 지시문에 들어가는 요소(행동 이름)에 있으면 풀지 않는다."""
    els = [el("a1", "action", "아버지가 따 놓은 사과 궤짝을 창고까지 날랐다", 2, CARRY2)] + MOTHER_ELS[1:]
    cands = [cand3(els, **MOTHER_KW)]
    first = raw_run(mother_story(), cands)
    s = raw_run(mother_story(), cands, _full(first))["scenes"][0]
    assert s["checks"]["summary_consistency"]["persons_resolution"]["unresolved"] == ["아버지"]
    assert "summary_person_not_in_elements" in s["decision_reasons"]


def test_other_reasons_remain_after_these_warnings_are_resolved():
    """경고를 풀어도 전언 · 뒤의 정정은 남는다."""
    d = mother_story()
    d["source"]["utterances"][1]["elder"] += " 창고는 옆집 것이었대요."
    heard = el("s2", "place", "옆집", 2, "창고는 옆집 것이었대요", role="setting")
    cands = [cand3(MOTHER_ELS + [heard], **MOTHER_KW)]
    first = raw_run(d, cands)
    s = raw_run(d, cands, _full(first))["scenes"][0]
    assert s["checks"]["summary_consistency"]["persons_resolution"]["resolved"][0]["name"] == "아버지"
    assert _causes(s)[("옆집", "hearsay")] is None and {"verification_partial", "hearsay"} <= set(s["decision_reasons"])
    assert s["generation_prompt"] is None
    d2 = mother_story()
    d2["source"]["utterances"][2]["elder"] = "아니, 다시 생각하니 사과 궤짝이 아니라 배 상자였어요."
    first = raw_run(d2, [cand3(MOTHER_ELS, **MOTHER_KW)])
    s = raw_run(d2, [cand3(MOTHER_ELS, **MOTHER_KW)], _full(first))["scenes"][0]
    assert "possible_later_correction" in s["decision_reasons"] and s["generation_prompt"] is None


def test_bad_scene_texts_are_refused():
    with pytest.raises(il.IllustError):
        raw_run(clean_story(), [cand3(CLEAN, **CLEAN_KW)], {"reviewer": "가", "relations": {}, "scene_texts": {"x": "요약"}})


# ---------------------------------------------------------------- 화자의 나이 — 「나이를 정하지 않는다」 와 「때: 여섯 살쯤」 이 어긋나지 않게

def test_narrator_age_from_the_source_is_kept_in_the_people_line():
    """화자를 가리키는 인용 안에 나이가 있고 그 나이가 때 요소로도 있으면, 화자 표시에 그 추정 나이를 그대로 쓴다."""
    cands = [cand3(V3, **AGE_KW)]
    s = raw_run(carry_story(), cands, _full(raw_run(carry_story(), cands)))["scenes"][0]
    block = s["generation_prompt"]["scene_block"]
    assert "- 인물: 이야기하는 본인(열 살쯤의 어린아이 · 생김새를 정하지 않는다), 형" in block
    assert "나이 · 생김새를 정하지 않는다)" not in block.split("- 그 밖의 인물")[0]        # 어긋나던 말이 없다
    assert "- 그 밖의 인물(형): 나이 · 생김새 · 옷차림을 정하지 않는다" in block
    assert "- 때: 열 살쯤" in block and s["prompt_checks"] == []
    assert s["generation_prompt"]["self_age"] == {"text": "열 살쯤", "time_element": "e5", "person_element": "e2", "child": True}
    assert next(e for e in s["elements"] if e["text"] == "나")["quote"] == ME["quote"]     # 요소와 인용은 그대로다


def test_narrator_age_is_not_guessed_when_the_source_does_not_tie_it_to_the_narrator():
    """나이가 화자의 인용 안에 없으면(때 요소만 따로 있으면) 화자의 나이로 적지 않는다."""
    me = el("p1", "person", "제가", 2, "제가 형이랑 둘이서", relation=rel("a1", "actor", "제가 형이랑 둘이서 사과 궤짝을 창고까지 날랐어요"))
    d = clean_story()
    d["source"]["utterances"][1]["elder"] += " 그게 열 살쯤 일이에요."
    age = el("t1", "time", "열 살쯤", 2, "그게 열 살쯤 일이에요")
    cands = [cand3([A1, me, BROTHER, CRATE, age, ORCHARD], **AGE_KW)]
    s = raw_run(d, cands, _full(raw_run(d, cands)))["scenes"][0]
    block = (s["generation_prompt"] or s["draft_prompt"])["scene_block"]
    assert f"- 인물: {il.SELF_LABEL}, 형" in block and (s["generation_prompt"] or s["draft_prompt"])["self_age"] is None


def test_adult_age_is_not_called_a_child_and_no_other_people_line_without_others():
    d = clean_story()
    d["source"]["utterances"][1]["elder"] = d["source"]["utterances"][1]["elder"].replace("제가 형이랑", "제가 스무 살 때 형이랑")
    me = el("p1", "person", "제가", 2, "제가 스무 살 때 형이랑 둘이서",
            relation=rel("a1", "actor", "제가 스무 살 때 형이랑 둘이서 사과 궤짝을 창고까지 날랐어요"))
    age = el("t1", "time", "스무 살", 2, "제가 스무 살 때")
    cands = [cand3([A1, me, CRATE, age, ORCHARD], summary="스무 살 때 사과 궤짝을 창고까지 날랐다.")]
    s = raw_run(d, cands, _full(raw_run(d, cands)))["scenes"][0]
    block = (s["generation_prompt"] or s["draft_prompt"])["scene_block"]
    assert "이야기하는 본인(스무 살 때 · 생김새를 정하지 않는다)" in block and "어린아이" not in block
    assert "- 그 밖의 인물" not in block


def test_together_is_written_only_from_actor_and_co_actor_relations():
    cands = [cand3(V3, **AGE_KW)]
    s = raw_run(carry_story(), cands, _full(raw_run(carry_story(), cands)))["scenes"][0]
    assert "- 행동: 사과 궤짝을 창고까지 날랐다 (인물 칸의 사람들이 함께 한다)" in s["generation_prompt"]["scene_block"]
    # 받은 사람 · 그 자리에 있던 사람이 섞이면 「함께」 라고 적지 않는다
    watcher = {**BROTHER, "relation": {**BROTHER["relation"], "role": "bystander"}}
    cands = [cand3([A1, ME, watcher, CRATE, AGE, ORCHARD], **AGE_KW)]
    s = raw_run(carry_story(), cands, _full(raw_run(carry_story(), cands)))["scenes"][0]
    assert "함께 한다" not in (s["generation_prompt"] or s["draft_prompt"])["scene_block"]
    # 관계 칸이 없는 옛 응답 · 한 사람뿐인 장면에도 적지 않는다
    assert "함께 한다" not in one(seed(), APPLE + [("person", "형", 2, "형이랑 둘이서")])["draft_prompt"]["scene_block"]
    solo = [cand3([A1, ME, CRATE, AGE, ORCHARD], summary="열 살쯤 사과 궤짝을 창고까지 날랐다.")]
    assert "함께 한다" not in raw_run(carry_story(), solo)["scenes"][0]["draft_prompt"]["scene_block"]
