"""
목차 유형별 대표 그림 — 합성 자료로 선정 로직만 시험한다 (memoir_illust_book · 로컬 실험)

    python -m pytest tests/test_memoir_illust_types.py -q

자료: eval/illust_types_C.json (가상의 책 — 목차 11개) · eval/illust_types_C_cases.json (손으로 쓴 모의 후보와 기대값).
모델도 이미지 API 도 부르지 않는다.

기대값(expect)은 코드를 돌리기 전에 「사람이 읽으면 무엇이 이 목차의 대표 그림인가」 로 적었다 (AI 작성 · 사람이 확인한 정답이 아니다).
코드 결과에 맞춰 고치지 않는다. limit 이 적힌 사례는 자동 판정이 따라가지 못하는 것이다 — 기대값을 그대로 두고 xfail(strict) 로 둔다.
코드가 언젠가 그 사례를 맞히면 이 시험이 알려 준다(그때 limit 을 지운다).
"""

from __future__ import annotations

import base64
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_illust_book as book     # noqa: E402
from tools import memoir_illust_book as tool           # noqa: E402

BOOK = json.loads((ROOT / "eval" / "illust_types_C.json").read_text(encoding="utf-8"))
CASES = json.loads((ROOT / "eval" / "illust_types_C_cases.json").read_text(encoding="utf-8"))["chapters"]
PHOTO_BASE = ROOT / "eval"
PIXELS = b"\xff\xd8\xff\xe0" + b"mock" * 30 + b"\xff\xd9"


def case(cid: str) -> tuple[str, dict]:
    key = cid.split("-")[0]
    return key, next(c for c in CASES[key]["cases"] if c["id"] == cid)


def run(key: str, c: dict) -> tuple[dict, list[str]]:
    ch, names = CASES[key], c["candidates"]
    doc = {"candidates": [ch["candidates"][n] for n in names]}
    if c["focus"]:
        doc["focus"] = ch["focus"][c["focus"]]
    return book.choose(copy.deepcopy(BOOK), key, json.dumps(doc, ensure_ascii=False)), names


def params():
    for key, ch in CASES.items():
        for c in ch["cases"]:
            marks = [pytest.mark.xfail(strict=True, reason="자동 판정의 한계 — " + c["limit"])] if c.get("limit") else []
            yield pytest.param(key, c, id=c["id"], marks=marks)


def item(sel: dict, text: str) -> dict:
    return next(v for v in sel["focus"]["items"] if v["text"] == text)


def row(sel: dict, names: list[str], name: str, source: str = "candidate") -> dict:
    return next(r for r in sel["comparison"] if r["source"] == source and names[r["candidate_index"]] == name)


# ---------------------------------------------------------------- 사례마다 — 기대한 대표 그림인가

@pytest.mark.parametrize("key,c", list(params()))
def test_representative_picture_is_what_a_reader_would_pick(key, c):
    sel, names = run(key, c)
    got = {"status": sel["status"], "pick": names[sel["candidate_index"]] if sel["status"] == "selected" else None,
           "source": sel.get("source"), "mode": sel.get("mode")}
    assert {k: got[k] for k in c["expect"]} == c["expect"], sel.get("choice_reason") or sel.get("detail")


# ---------------------------------------------------------------- 원문에 있는가 · 중심을 나타내는가 — 따로 적는다

def test_present_in_the_source_is_not_the_same_as_representing_the_chapter():
    """사다리 · 옆집 할머니는 인용이 맞고 본문에도 나온다. 그래도 이 목차(아버지와 이엉을 얹은 일)의 중심이 아니다."""
    sel, names = run(*case("c01-2"))
    for text in ("사다리", "옆집 할머니"):
        v = item(sel, text)
        assert v["source_check"]["quoted"] is True and v["source_check"]["in_body"] is True
        assert v["centrality"]["is_center"] is False
    assert item(sel, "사다리")["centrality"]["tier"] == "linked"                  # 중심(아버지 · 이엉)과 같은 문장에 나온다 — 딸린 것
    assert item(sel, "옆집 할머니")["centrality"]["tier"] == "supporting"           # 구경만 한 사람 — 곁가지
    ladder = row(sel, names, "C")
    assert ladder["source_check"] is True and ladder["represents"] is False         # 형식 · 원문 대조는 통과 · 대표하지 않는다
    assert ladder["reason"].startswith("탈락") and "중심" in ladder["reason"]


def test_blocked_candidate_still_records_whether_it_would_represent():
    """형식 검사에서 막힌 후보도 「통과했다면 중심을 담았는가」 를 따로 적는다 — 두 판단을 섞지 않는다."""
    sel, names = run(*case("c01-3"))
    blocked = row(sel, names, "A_no_father")
    assert blocked["source_check"] is False and "possible_participant_omitted" in blocked["blocking"]
    assert blocked["represent"]["represents"] is True and blocked["represent"]["evaluated_on"] == "quoted_elements"
    assert sel["source"] == "derived_symbolic" and sel["prompt"]["composition"]["center"] == ["이엉"]


def test_the_model_label_is_kept_as_a_proposal_only():
    sel, _ = run(*case("c07-5"))
    cup = item(sel, "찻잔")
    assert cup["model_proposed"] == "core" and cup["model_agrees"] is False and cup["centrality"]["is_center"] is False
    assert "트럭" in sel["focus"]["center_known"]                                     # 목차 근거로 본 중심 — 후보에 없어도 적는다
    assert "트럭" in sel["detail"]


def test_a_short_chapter_does_not_lose_its_landscape():
    """두 문장짜리 글 — 보리밭은 한 번만 나오지만 본문 문장의 절반이고 제목이다."""
    sel, _ = run(*case("c03-2"))
    v = item(sel, "보리밭")
    assert v["tier"] == "core" and set(v["why"]) == {"title", "body_share"} and v["body_share"] == 0.5


def test_destination_in_the_title_does_not_outrank_the_moving_itself():
    """모델이 가는 곳(서울)을 중심이라 적으면 서울은 신호 둘(제목 · 모델)을 얻는다 — 그래도 제목 점수는 본문이 다룬 장소에만 준다."""
    sel, names = run(*case("c07-4"))
    seoul = row(sel, names, "C")
    assert item(sel, "서울")["tier"] == "core" and seoul["represent"]["title_hits"] == 0
    assert names[sel["candidate_index"]] == "A"


# ---------------------------------------------------------------- 한 권 — 사진 유지 · 한 장씩 삽입 · 다시 돌리기

def first_case_reply(key: str) -> str:
    ch = CASES[key]
    c = ch["cases"][0]
    doc = {"candidates": [ch["candidates"][n] for n in c["candidates"]]}
    if c["focus"]:
        doc["focus"] = ch["focus"][c["focus"]]
    return json.dumps(doc, ensure_ascii=False)


def test_whole_book_keeps_photos_inserts_once_and_reruns_with_no_calls(tmp_path):
    selects, images = [], []

    def select_for(t):
        def call(system, user):
            selects.append(t["ident"])
            return first_case_reply(t["ident"])
        return call

    def image_call(prompt, *, model, size, aspect, key):
        images.append(prompt)
        return {"id": "mock", "status": "completed",
                "output_image": {"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(PIXELS).decode()}}

    def go():
        items, calls = tool.process(copy.deepcopy(BOOK), tmp_path, select_for=select_for, image_call=image_call, mock=True,
                                    image_model="mock", base_dir=PHOTO_BASE)
        summary = tool.write_outputs(copy.deepcopy(BOOK), tmp_path, items, True, PHOTO_BASE)
        return {it["ident"]: it for it in items}, calls, summary, json.loads((tmp_path / "book_illustrated.json").read_text(encoding="utf-8"))

    items, calls, summary, doc = go()
    no_photo = [f"c{i:02d}" for i in range(1, 9)]
    assert sorted(selects) == no_photo                                                 # 사진 있는 항목 · 사진 정보 없는 항목은 부르지 않는다
    assert items["c09"]["status"] == "kept_photo" and items["c10"]["status"] == "kept_photo"
    assert (items["c11"]["status"], items["c11"]["failure"]) == ("photo_unknown", ["photo_info_missing"])
    per = {c["chapter_key"]: c["blocks"] for c in doc["chapters"]}
    count = {k: (sum(b["type"] == "illustration" for b in v), sum(b["type"] == "photo" for b in v)) for k, v in per.items()}
    assert count["c09"] == (0, 1) and count["c10"] == (0, 1) and count["c11"] == (0, 0)
    for k in no_photo:                                                                  # 고른 항목은 한 장, 실패한 항목은 0장
        want = 1 if items[k]["status"] == "inserted" else 0
        assert count[k] == (want, 0), (k, items[k]["status"])
        assert items[k]["status"] in ("inserted", "failed") and items[k]["user_selected"] is False
    assert len(images) == sum(1 for k in no_photo if items[k]["status"] == "inserted") == calls["image"]
    assert summary["status"] == "incomplete"                                            # 실패 · 사진 정보 없음이 있으면 complete 가 아니다
    again, calls2, _, doc2 = go()
    assert calls2 == {"select": 0, "image": 0} and doc2 == doc                          # 다시 돌려도 더 부르지 않고 두 번 넣지 않는다
