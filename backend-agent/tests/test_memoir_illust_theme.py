"""
목차 주제 삽화 (chapter_theme_v1 · memoir_illust_theme) — 합성 자료로만

    python -m pytest tests/test_memoir_illust_theme.py -q

모델 응답 자리에는 AI 가 쓴 모의 계획(eval/illust_theme_mock_D.json)을 넣는다 — 실제 모델의 판단을 시험하는 것이 아니라,
코드가 계획을 본문에 비춰 보고(중심 소재 · 부정 · 없는 관계) 그림 지시문을 조립하는 것을 시험한다.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_illust as il, memoir_illust_book as book, memoir_illust_theme as th   # noqa: E402

SEED_D = json.loads((ROOT / "eval" / "illust_theme_seed_D.json").read_text(encoding="utf-8"))
SEED_B = json.loads((ROOT / "eval" / "illust_book_seed_B.json").read_text(encoding="utf-8"))
MOCK = json.loads((ROOT / "eval" / "illust_theme_mock_D.json").read_text(encoding="utf-8"))


def pick(key: str, data=None, ident=None) -> dict:
    no = int(key.split("_")[0])
    return th.choose_theme(copy.deepcopy(data or SEED_D), ident or no, json.dumps(MOCK["D"][key], ensure_ascii=False))


def test_theme_is_the_default_and_the_scene_policy_stays_separate():
    assert book.DEFAULT_POLICY == "theme" and book.POLICY_IDS == {"theme": "chapter_theme_v1", "scene": "scene_v5"}
    assert book.select_system("theme") == th.select_prompt() != book.select_system("scene")
    assert book.policy_files("theme")["select_prompt"] == "1_목차주제_v6.md"
    assert book.policy_files("scene")["select_prompt"] == book.SELECT_FILE
    assert book.policy_files("theme")["style"] == "2_그림양식_v2.md" and book.policy_files("scene")["style"] == il.STYLE_FILE
    with pytest.raises(il.IllustError):
        book.check_policy("story")


def test_message_carries_the_whole_chapter_and_its_source_only():
    msg = json.loads(th.theme_message(SEED_D, 3).split("\n", 1)[1])
    assert msg["chapter"]["title"] == "역 앞 분식집" and [p["p"] for p in msg["chapter"]["paragraphs"]] == [0, 1, 2]
    assert "퇴근하는 사람들" in msg["chapter"]["paragraphs"][2]["text"]           # 첫 일화만이 아니라 끝까지
    assert [u["turn"] for u in msg["utterances"]] == [3]                           # 그 장의 원문만


def test_metaphorical_title_follows_the_body():
    sel = pick("1")
    assert sel["status"] == "selected" and sel["policy"] == "chapter_theme_v1" and sel["mode"] == "THEME"
    main = sel["prompt"]["composition"]["main"]
    assert main == ["안방 구석의 재봉틀"]                       # 제목의 「바늘 · 겨울」 이 아니라 본문 전체에 걸친 재봉틀
    assert "재봉틀과 겨울밤" in sel["prompt"]["text"]


def test_age_marker_and_negation_inside_a_sentence_do_not_block():
    # 1장: 「열 살쯤」 · 「꿰지 못해」 / 3장: 「떡볶이를 못 드시는 손님」 · 「고춧가루 없는」
    assert pick("1")["status"] == "selected"
    sel = pick("3")
    assert sel["status"] == "selected"
    st = next(s for s in sel["theme"]["subjects"] if s["anchor"] == "떡볶이")["anchor_stats"]
    assert st["negated"] >= 1 and st["affirmed"] >= 2 and st["paragraphs"] == [0, 1, 2]


def test_a_theme_the_body_negates_is_not_drawn():
    bad = pick("2_bad")
    assert bad["status"] == "failed" and "theme_negated" in bad["reasons"]
    dropped = {d["text"]: d["dropped"] for d in bad["theme"]["dropped"]}
    assert dropped["커피가 놓인 카페 카운터"] == ["negated_in_chapter"]
    good = pick("2_good")                                        # 같은 장 — 본문이 말하는 서점 일은 그린다
    assert good["status"] == "selected" and good["prompt"]["composition"]["main"] == ["책이 꽂힌 동네 서점"]
    assert "카페" not in good["prompt"]["text"]                   # 「본문에 없다」 고 적은 것을 지시문에 넣지 않는다


def test_relation_not_in_the_chapter_is_dropped_without_blocking():
    sel = pick("4")
    assert sel["status"] == "selected"
    assert [d["dropped"] for d in sel["theme"]["dropped"]] == [["relation:아버지"]]
    assert "아버지" not in sel["prompt"]["text"]
    assert sel["prompt"]["composition"]["layout_from"] == "default"          # 관계를 만든 구도도 뺐다
    assert {"composition_dropped": ["relation:아버지"]} in sel["theme"]["notes"]


def test_title_only_or_missing_anchor_is_not_a_fact():
    sel = pick("5")
    assert sel["status"] == "selected" and [d["text"] for d in sel["theme"]["dropped"]] == ["봄꽃이 핀 들판"]
    assert sel["theme"]["dropped"][0]["dropped"] == ["anchor_not_in_body"]
    none = pick("6")
    assert none["status"] == "failed" and none["reasons"] == ["no_central_subject"]
    assert "지어내서 채우지 않는다" in none["detail"]


def test_one_paragraph_episode_is_not_central_but_can_support():
    sel = pick("1")
    rows = {s["text"]: s for s in sel["theme"]["subjects"]}
    assert rows["노란 백열등 불빛"]["central"] is False and "한 문단에만" in rows["노란 백열등 불빛"]["central_basis"]
    assert "노란 백열등 불빛" in sel["prompt"]["composition"]["sub"]           # 곁들이는 소재로는 쓴다
    assert "바느질하는 손" in sel["prompt"]["composition"]["expression"]      # 꾸밈(anchor 없음)도 허용


def test_prompt_is_korean_style_v2_and_keeps_facts_apart_from_expression():
    sel = pick("3")
    p = sel["prompt"]
    blocks = th.style_blocks()
    assert all(blocks[k] in p["text"] for k in blocks) and p["style_id"] == "watercolor-recall-v2" and p["language"] == "ko"
    assert "[이 장의 주제]" in p["text"] and "[그릴 것]" in p["text"] and len(p["text"]) <= il.PROMPT_MAX
    assert "특정 한 순간을 사실 그대로 재현한 그림이 아니다" in p["text"]
    assert [f["anchor"] for f in p["composition"]["facts"]] == ["떡볶이", "분식집", "창"]


def test_result_records_the_policy_and_what_was_and_was_not_checked():
    sel = pick("2_good")
    assert sel["verdict"]["policy"] == "chapter_theme_v1" and sel["human"] == "not_reviewed" and sel["automatic"] is True
    assert sel["verdict"]["checked"] == th.THEME_CHECKED and sel["verdict"]["not_checked"] == th.THEME_NOT_CHECKED
    assert "verified" not in json.dumps(sel["auto_checks"])                  # 원문 대조를 했다고 적지 않는다
    assert [c["check"] for c in sel["auto_checks"]] == ["central_subject", "not_negated", "no_new_relation_or_number",
                                                        "supports_spread"]


def test_placement_is_the_chapter_start_and_locates_back():
    data = copy.deepcopy(SEED_D)
    sel = pick("3", data)
    pl = sel["placement"]
    assert pl["basis"] == "chapter_theme_start" and pl["paragraph_index"] == 0
    ins = book.insert_position(data, {"key": None, "no": 3, "title": "역 앞 분식집"}, pl)
    assert ins["status"] == "inserted" and ins["after_paragraph"] == 0 and ins["locate"] == "exact"


def test_same_shape_as_the_scene_result_for_the_runner_and_service():
    sel = pick("3")
    for k in ("status", "mode", "source", "scene", "prompt", "placement", "auto_checks", "tolerated_reasons"):
        assert k in sel
    assert set(sel["scene"]) >= {"scene_title", "scene_summary", "source_turns", "evidence", "not_used"}
    assert sel["scene"]["source_turns"] == [3]


def test_malformed_plan_fails_without_inventing():
    for reply in ["not json", json.dumps({"theme": ""}), json.dumps({"theme": "주제", "subjects": []})]:
        sel = th.choose_theme(SEED_D, 3, reply)
        assert sel["status"] == "failed" and sel["reasons"] == ["model_output"]


def test_synthetic_book_b_chapters_with_two_short_paragraphs():
    for no in (1, 2, 3):
        sel = th.choose_theme(copy.deepcopy(SEED_B), f"c0{no}", json.dumps(MOCK["B"][str(no)], ensure_ascii=False))
        assert sel["status"] == "selected", (no, sel.get("reasons"))


def test_runner_uses_the_theme_policy_by_default(tmp_path, monkeypatch):
    from tools import memoir_illust_book as tool
    monkeypatch.setattr(tool, "RUNS", tmp_path / "runs")
    seed_path, mock_path = tmp_path / "seed.json", tmp_path / "mock.json"
    seed_path.write_text(json.dumps(SEED_D, ensure_ascii=False), encoding="utf-8")
    by = {k: v for k, v in MOCK["D"].items() if "_" not in k} | {"2": MOCK["D"]["2_good"]}
    mock_path.write_text(json.dumps({"by_chapter": by}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "runs" / "o"
    code = tool.main(["--input", str(seed_path), "--out", str(out), "--mock-select", str(mock_path), "--mock-images"])
    items = {r["ident"]: r for r in json.loads((out / "items.json").read_text(encoding="utf-8"))["items"]}
    assert code == 1                                              # 6장이 실패라 complete 가 아니다
    assert [k for k, r in items.items() if r["status"] == "inserted"] == [1, 2, 3, 4, 5]
    assert items[6]["status"] == "failed" and items[6]["failure"] == ["no_central_subject"]
    assert all(r["mode"] == "THEME" for k, r in items.items() if k != 6)
    req = json.loads((out / "items" / "1" / "select_request.json").read_text(encoding="utf-8"))
    assert req["policy_id"] == "chapter_theme_v1" and req["prompt_file"] == "1_목차주제_v6.md"
    # 다시 돌리면 부르지 않고 그대로 쓴다
    again = tool.process(json.loads(seed_path.read_text(encoding="utf-8")), out, select_for=None, image_call=None, mock=True,
                         image_model="mock")
    assert again[1] == {"select": 0, "image": 0}
    assert [it["status"] for it in again[0]][:5] == ["inserted"] * 5
    # 같은 폴더를 장면 방식으로 돌리면 앞선 주제 방식의 결과를 그 방식의 결과로 쓰지 않는다 (지시문이 다르다)
    other = tool.process(json.loads(seed_path.read_text(encoding="utf-8")), out, select_for=None, image_call=None, mock=True,
                         image_model="mock", policy="scene")
    assert other[1] == {"select": 0, "image": 0}
    assert all(it["status"] == "needs_reprocess" and "select_prompt_changed" in it["failure"] for it in other[0][:5])
