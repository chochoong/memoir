"""
목차 주제 삽화 (chapter_theme_v2 · memoir_illust_theme) — 합성 자료로만

    python -m pytest tests/test_memoir_illust_theme.py -q

모델 응답 자리에는 AI 가 쓴 모의 계획(eval/illust_theme_mock_D.json · 이 파일 안의 계획)을 넣는다. 실제 모델의 이해력이나
그림 품질을 시험하는 것이 아니라, 코드가 계획을 받아 (낱말 검사로 막지 않고) 그림 지시문을 조립하는 것을 시험한다.

**v2 에서 뜻이 바뀐 v1 시험 (2026-11-18)** — v1 은 코드가 낱말로 소재를 빼고 생성을 막았고, v2 는 뜻을 모델에 맡기고 코드는
모양 · 존재만 본다(제품 결정). 아래 v1 시험은 그 차단을 확인하던 것이라 v2 의 동작을 확인하도록 바꿨다.
    부정된 주제는 그리지 않는다(theme_negated)        → 부정어가 든 본문 · 계획도 코드가 막지 않는다 (판단은 지시문 v7 · 모델)
    본문에 없는 관계는 뺀다(relation:아버지)           → 관계 낱말로 소재를 빼지 않는다 (그림 양식 v2 · 지시문 v7 이 금지)
    제목에만 · 본문에 없는 낱말은 뺀다                → 빼지 않는다. 어디에 나오는지는 anchor_reference 로 참고만 남는다
    한 문단 소재 · 반복 횟수 · 「카페인」 부정 수        → 반복 · 부정 셈이 없어졌다. 낱말 경계는 참고 셈에만 남는다
    중심 소재가 없으면 실패(no_central_subject)        → 그 실패 이름이 없어졌다. 실패는 모양 오류 · 빈 계획 · 지시문 조립 불가뿐이다
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
OLD_GATES = {"theme_negated", "no_central_subject", "theme_adds_relation", "negated_in_chapter", "anchor_not_in_chapter",
             "title_only_not_supported", "listed_not_in_story", "anchor_not_in_body"}


def pick(key: str, data=None, ident=None) -> dict:
    no = int(key.split("_")[0])
    return th.choose_theme(copy.deepcopy(data or SEED_D), ident or no, json.dumps(MOCK["D"][key], ensure_ascii=False))


def one_chapter(title: str, paragraphs: list[list[str]]) -> dict:
    """합성 — 장 하나짜리 책 (원문 없음)."""
    return {"schema_version": il.INPUT_SCHEMA, "synthetic": True, "source": None, "photos": [], "photo_placement": {"complete": True},
            "memoir": {"memoir_id": None, "style": "essay", "title": "합성",
                       "chapters": [{"no": 1, "title": title, "status": "ready",
                                     "paragraphs": [{"sentences": [{"text": s, "turns": []} for s in p]} for p in paragraphs]}]}}


def plan(theme: str, subjects: list[tuple], supports: list[tuple] = (), short: str | None = None, composition=None) -> str:
    return json.dumps({"chapter_no": 1, "theme": theme, "theme_short": short or theme[:20], "mood": "따뜻한", "period": None,
                       "supports": [{"point": p, "paragraphs": list(ps)} for p, ps in supports],
                       "subjects": [{"text": t, "kind": k, "role": r, "anchor": a} for t, k, r, a in subjects],
                       "composition": composition, "not_in_story": []}, ensure_ascii=False)


def no_gate_trace(sel: dict) -> bool:
    """앞선 판의 낱말 차단이 이름만 바꿔 남아 있지 않은가 — 결과 어디에도 그 사유 · 빠진 소재가 없다."""
    text = json.dumps(sel, ensure_ascii=False)
    return not any(g in text for g in OLD_GATES) and sel["scene"]["not_used"] == []


# ---------------------------------------------------------------- 판 · 지시문

def test_theme_v2_is_the_default_and_the_scene_policy_stays_separate():
    assert book.DEFAULT_POLICY == "theme" and book.POLICY_IDS == {"theme": "chapter_theme_v2", "scene": "scene_v5"}
    assert book.CHECKS_VERSIONS == {"theme": "theme_checks_v2", "scene": "scene_checks_v5"}
    assert book.select_system("theme") == th.select_prompt() != book.select_system("scene")
    files = book.policy_files("theme")
    assert files["select_prompt"] == "1_목차주제_v7.md" and files["checks_version"] == "theme_checks_v2"
    assert files["style"] == "2_그림양식_v2.md" and book.policy_files("scene")["select_prompt"] == book.SELECT_FILE
    assert (il.PROMPTS / "1_목차주제_v6.md").is_file()                         # v1 의 지시문은 기록으로 남는다
    with pytest.raises(il.IllustError):
        book.check_policy("story")


def test_prompt_v7_tells_the_model_to_read_context_not_words():
    p = th.select_prompt()
    for must in ("특정 사건의 한순간을 정확히 복원할 필요가 없다", "일반화된 삽화면 충분하다", "부정", "가정", "희망",
                 "본문과 반대되는 경험", "옷차림 · 빛 · 색감", "똑같이 되살렸다고 하지 않는다"):
        assert must in p, must


def test_message_carries_the_title_whole_chapter_and_its_source_only():
    msg = json.loads(th.theme_message(SEED_D, 3).split("\n", 1)[1])
    assert msg["chapter"]["title"] == "역 앞 분식집" and [p["p"] for p in msg["chapter"]["paragraphs"]] == [0, 1, 2]
    assert "퇴근하는 사람들" in msg["chapter"]["paragraphs"][2]["text"]           # 첫 일화만이 아니라 끝까지
    assert [u["turn"] for u in msg["utterances"]] == [3]                           # 그 장의 원문만 (참고 자료)


# ---------------------------------------------------------------- 부정어 차단 제거 (직접 · 간접)

def test_hugging_the_world_does_not_block():
    """「세계를 안고 있었다」 — 「안고」 를 부정으로 읽어 막던 경로가 없다. 그 낱말을 소재 · 주제가 써도 그대로 간다."""
    data = one_chapter("방학의 작은 도서관", [["방학이면 동네 도서관 서가 앞에서 오후 내내 책을 골랐다."],
                                              ["그림책을 펼치면 나는 그 속 세계를 안고 있었다."]])
    sel = th.choose_theme(data, 1, plan("도서관에서 책 속의 세계에 빠져 지낸 날들",
                                        [("책이 빼곡한 도서관 서가", "place", "main", "서가"),
                                         ("펼친 책 위로 번지는 작은 세계", "object", "main", "세계")],
                                        short="책 속의 세계와 도서관"))
    assert sel["status"] == "selected" and no_gate_trace(sel)
    assert sel["prompt"]["composition"]["main"] == ["책이 빼곡한 도서관 서가", "펼친 책 위로 번지는 작은 세계"]


@pytest.mark.parametrize("sentence", ["나는 그 책을 안 읽은 척했다.", "끝까지 다 읽지 못한 책도 많았다.",
                                      "도서관에는 놀 친구가 없었지만 상관없었다.", "읽지 않은 책이 서가에 가득했다."])
def test_sentences_with_an_mot_eopda_do_not_drop_a_normal_plan(sentence):
    data = one_chapter("책과 보낸 오후", [["방과 후면 도서관에 들러 책을 읽었다.", sentence], ["해가 질 때까지 서가 옆에 앉아 있었다."]])
    sel = th.choose_theme(data, 1, plan("방과 후 도서관에서 책을 읽던 시간",
                                        [("책이 꽂힌 서가", "place", "main", "서가"), ("펼친 책", "object", "main", "책")]))
    assert sel["status"] == "selected" and no_gate_trace(sel)
    assert sel["prompt"]["composition"]["main"] == ["책이 꽂힌 서가", "펼친 책"]


def test_removing_the_negation_gate_is_not_routed_into_another_failure():
    """v1 이 막던 계획들 — 부정 문장에만 나오는 소재 · 본문에 없는 낱말 · 관계 낱말 — 이 다른 실패 이름으로도 막히지 않는다."""
    for key in ("2_bad", "4", "5", "6"):
        sel = pick(key)
        assert sel["status"] == "selected", (key, sel.get("reasons"))
        assert no_gate_trace(sel), key
        assert all(s["text"] in sel["prompt"]["text"] for s in sel["theme"]["main"])


def test_the_model_is_responsible_for_meaning_and_the_result_says_so():
    """「카페에서 일한 적이 없다」 장에 모델이 카페 주제를 내면 코드는 그대로 쓴다 — 그 판단은 지시문 v7 이 모델에 맡긴 것이다.
    결과는 코드가 뜻을 검증하지 않았다고 적는다."""
    sel = pick("2_bad")
    v = sel["verdict"]
    assert v["meaning_verified_by_code"] is False and v["policy"] == "chapter_theme_v2" and v["checks_version"] == "theme_checks_v2"
    assert any("뜻" in x for x in v["not_checked"]) and any("부정 · 가정 · 희망" in x for x in v["not_checked"])
    assert sel["human"] == "not_reviewed" and "verified" not in json.dumps(sel["auto_checks"])
    assert "검증하지 않았다" in sel["choice_reason"]


def test_reference_info_never_blocks():
    sel = pick("6")                                               # 모델이 적은 낱말이 본문 · 제목 어디에도 없다
    ref = next(c for c in sel["auto_checks"] if c["check"] == "anchor_reference")
    assert ref["blocking"] is False and all(d["mentions"] == 0 for d in ref["detail"])
    assert sel["status"] == "selected"


# ---------------------------------------------------------------- 실제로 처리할 수 없는 경우만 실패

def test_format_and_empty_plan_fail_with_their_own_reasons():
    cases = [("not json", "model_output"), (json.dumps("문자열"), "model_output"),
             (json.dumps({"theme": "", "subjects": [{"text": "책", "kind": "object", "role": "main"}]}), "empty_plan"),
             (json.dumps({"theme": "주제", "subjects": []}), "empty_plan"),
             (json.dumps({"theme": "주제", "subjects": [{"text": "  "}, {"kind": "object"}]}), "empty_plan")]
    for reply, why in cases:
        sel = th.choose_theme(SEED_D, 3, reply)
        assert sel["status"] == "failed" and sel["reasons"] == [why], (reply, sel.get("reasons"))
        assert sel["verdict"]["accept"] is False


def test_a_plan_wrapped_in_a_list_is_unwrapped():
    sel = th.choose_theme(SEED_D, 3, json.dumps([MOCK["D"]["3"]], ensure_ascii=False))
    assert sel["status"] == "selected"


def test_without_main_the_first_subject_is_the_center():
    data = one_chapter("낡은 자전거", [["할아버지가 물려주신 낡은 자전거를 타고 장터에 다녔다."]])
    sel = th.choose_theme(data, 1, plan("낡은 자전거로 장터에 다니던 일",
                                        [("낡은 자전거", "object", "sub", "자전거"), ("장터 가는 길", "place", "sub", "장터")]))
    assert sel["status"] == "selected" and sel["prompt"]["composition"]["main"] == ["낡은 자전거"]
    assert sel["theme"]["main_from"] == "model_order"


# ---------------------------------------------------------------- 지시문 · 자리 · 모양

def test_metaphorical_title_follows_the_plan_main():
    sel = pick("1")
    assert sel["status"] == "selected" and sel["policy"] == "chapter_theme_v2" and sel["mode"] == "THEME"
    assert sel["prompt"]["composition"]["main"] == ["안방 구석의 재봉틀"] and "재봉틀과 겨울밤" in sel["prompt"]["text"]


def test_prompt_is_korean_style_v2_and_keeps_plan_and_expression_apart():
    sel = pick("3")
    p = sel["prompt"]
    blocks = th.style_blocks()
    assert all(blocks[k] in p["text"] for k in blocks) and p["style_id"] == "watercolor-recall-v2" and p["language"] == "ko"
    assert "[이 장의 주제]" in p["text"] and "[그릴 것]" in p["text"] and len(p["text"]) <= il.PROMPT_MAX
    assert "특정 한 순간을 사실 그대로 재현한 그림이 아니다" in p["text"]
    assert [x["anchor"] for x in p["composition"]["from_plan"]] == ["떡볶이", "분식집", "창"]


def test_not_in_story_is_never_written_into_the_prompt():
    good = pick("2_good")
    assert good["status"] == "selected" and "카페" not in good["prompt"]["text"]


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


def test_same_text_split_into_different_paragraphs_gives_the_same_picture():
    sewing = ["열 살쯤 되던 해부터 겨울이 오면 안방 구석의 재봉틀이 바빠졌다.", "구멍 난 소매와 해진 무릎을 하나씩 기웠다.",
              "다 고친 옷을 개어 쌓아 두면 백열등 불빛이 노랗게 내려앉았다.", "그 소리가 들리면 겨울이 깊어진 줄 알았다."]
    p = plan("겨울밤마다 재봉틀로 해진 옷을 기우던 날들",
             [("안방 구석의 재봉틀", "object", "main", "재봉틀"), ("개어 쌓은 옷", "object", "sub", "옷")], short="재봉틀과 겨울밤")
    results = [th.choose_theme(one_chapter("바늘 끝에 걸린 겨울", paras), 1, p)["prompt"]["scene_block"]
               for paras in ([sewing], [[s] for s in sewing], [sewing[:2], sewing[2:]])]
    assert results[0] == results[1] == results[2]


def test_synthetic_book_b_chapters_with_two_short_paragraphs():
    for no in (1, 2, 3):
        sel = th.choose_theme(copy.deepcopy(SEED_B), f"c0{no}", json.dumps(MOCK["B"][str(no)], ensure_ascii=False))
        assert sel["status"] == "selected", (no, sel.get("reasons"))


def test_reference_word_boundary_is_the_same_for_every_word():
    """참고 셈의 낱말 경계 — 앞은 낱말 경계, 뒤는 조사 · 어미만. 판정에는 쓰지 않는다."""
    assert [len(th._hits(w, s)) for w, s in [("서가", "회의실 비서가 서류를 정리했다"), ("산", "산책을 했다"), ("배낭", "배낭여행을 갔다"),
                                              ("카페", "카페인이 있다"), ("서가", "서가에 꽂았다"), ("산", "산이 이어졌다"),
                                              ("배낭", "배낭을 멨다"), ("카페", "카페와는 달랐다"), ("알바", "알바하면서")]] \
        == [0, 0, 0, 0, 1, 1, 1, 1, 1]


# ---------------------------------------------------------------- 로컬 실행기

def test_runner_uses_the_theme_v2_policy_by_default(tmp_path, monkeypatch):
    from tools import memoir_illust_book as tool
    monkeypatch.setattr(tool, "RUNS", tmp_path / "runs")
    seed_path, mock_path = tmp_path / "seed.json", tmp_path / "mock.json"
    seed_path.write_text(json.dumps(SEED_D, ensure_ascii=False), encoding="utf-8")
    by = {k: v for k, v in MOCK["D"].items() if "_" not in k} | {"2": MOCK["D"]["2_good"]}
    mock_path.write_text(json.dumps({"by_chapter": by}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "runs" / "o"
    code = tool.main(["--input", str(seed_path), "--out", str(out), "--mock-select", str(mock_path), "--mock-images"])
    items = {r["ident"]: r for r in json.loads((out / "items.json").read_text(encoding="utf-8"))["items"]}
    assert code == 0 and [k for k, r in items.items() if r["status"] == "inserted"] == [1, 2, 3, 4, 5, 6]
    assert all(r["mode"] == "THEME" for r in items.values())
    req = json.loads((out / "items" / "1" / "select_request.json").read_text(encoding="utf-8"))
    assert req["policy_id"] == "chapter_theme_v2" and req["prompt_file"] == "1_목차주제_v7.md"
    # 다시 돌리면 부르지 않고 그대로 쓴다
    again = tool.process(json.loads(seed_path.read_text(encoding="utf-8")), out, select_for=None, image_call=None, mock=True,
                         image_model="mock")
    assert again[1] == {"select": 0, "image": 0} and [it["status"] for it in again[0]] == ["inserted"] * 6
    # 같은 폴더를 장면 방식으로 돌리면 주제 방식의 앞선 결과를 그 방식의 결과로 쓰지 않는다 (지시문이 다르다)
    other = tool.process(json.loads(seed_path.read_text(encoding="utf-8")), out, select_for=None, image_call=None, mock=True,
                         image_model="mock", policy="scene")
    assert other[1] == {"select": 0, "image": 0}
    assert all(it["status"] == "needs_reprocess" and "select_prompt_changed" in it["failure"] for it in other[0])
