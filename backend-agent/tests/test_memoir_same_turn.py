"""
한 말씀 안에서 고쳐 말한 것 · 일부를 빼 달라고 한 것 — 분석 검사가 받는지, 받은 뒤에 지켜지는지 (모델을 부르지 않는다).

    python -m pytest -p no:cacheprovider -q tests/test_memoir_same_turn.py

실모델 시험(2026-11-15)에서 공통 분석이 이 두 꼴에서 멈췄다(502):
    「83년이라고 말하려다가 생각해 보니 84년이 맞아요」      → corrections 의 turns 가 한 턴
    「그 모임 이름은 그냥 안 적으면 좋겠어요」 (같은 말씀 안)  → exclusions 의 partial 턴 = 요청 턴
"""

from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_memoir_pipeline as base                        # noqa: E402
import test_memoir_style_pipeline as styled                # noqa: E402

from app.session import memoir_pipeline as pipe            # noqa: E402
from app.session import memoir_style_stage as stage3       # noqa: E402

fact, sent = base.fact, base.sent


def analysis(**over):
    a = base.analysis_ok()
    a.update(over)
    return a


def check(a):
    data, _ = base.source()
    return pipe.check_analysis(a, base.T_of(data))


def correction(turns, before="1978년", after="1979년", fid="f1"):
    return {"fact": fid, "turns": turns, "before": before, "after": after, "note": "고쳐 말함"}


# ---------------------------------------------------------------- 문제 A — 정정

def test_a_correction_inside_one_turn_is_accepted():
    a = analysis(corrections=[correction([1])])               # f1 — 턴 1 · 시점 1979년 (정정 뒤 값)
    status, warnings = check(a)
    assert status == "ready"
    assert a["facts"][0]["time"] == "1979년" and "1978" not in str(a["facts"])     # 유효 사실은 정정 뒤 값 하나


def test_a_correction_across_turns_still_works():
    a = analysis()
    a["facts"][0]["turns"] = [1, 3]
    a["not_in_facts"] = [{"turns": [4], "reason": "시험용"}]
    a["corrections"] = [correction([1, 3])]
    assert check(a)[0] == "ready"


@pytest.mark.parametrize("mutate, why", [
    (lambda a: a["facts"][0].update(time="1978년"), "정정 전 값"),                       # 유효 사실에 정정 전 값이 남았다
    (lambda a: a["facts"][0].update(time=""), "정정 뒤 값"),                             # 유효 사실에 정정 뒤 값이 없다
    (lambda a: a["facts"].append(fact("f9", [1], "첫 출근", "1978년")), "별개 사실"),     # 정정 전 값을 다른 사실로 남겼다
    (lambda a: a["corrections"][0].update(turns=[2]), "정정 전 · 뒤"),                   # 정정 턴이 그 사실의 턴이 아니다
    (lambda a: a["corrections"][0].update(after="1978년"), "before · after"),            # 무엇으로 고쳤는지 없다
])
def test_a_one_turn_correction_is_still_checked(mutate, why):
    a = analysis(corrections=[correction([1])])
    mutate(a)
    if any(f["id"] == "f9" for f in a["facts"]):
        a["units"][0]["facts"].append("f9")
    with pytest.raises(pipe.PipelineError) as e:
        check(a)
    assert e.value.kind == "reference" and why in str(e.value.details or e.value.message)


def test_a_before_value_in_the_manuscript_is_blocked():
    a = analysis(corrections=[correction([1])])
    check(a)
    ch = [{"chapter_key": "ch-1", "title": sent("제목", [], "editorial"),
           "paragraphs": [[sent("1978년에 첫 월급을 받았다.", ["f1"])], [sent("1979년의 일이다.", ["f1"])]]}]
    found = pipe.correction_findings(ch, a)
    assert [(f["rule"], f["severity"], f["location"]) for f in found] == [("stale_correction", "block", "ch-1/p0/s0")]
    assert pipe._analysis_for_next(a)["corrections"] == [{"fact": "f1", "turns": [1], "after": "1979년", "note": "고쳐 말함"}] \
        or "before" not in str(pipe._analysis_for_next(a).get("corrections"))                 # 뒤 단계는 정정 전 값을 받지 않는다


# ---------------------------------------------------------------- 문제 B — 일부 제외 요청

def excl(mode, turns, asked, scope="모임 이름"):
    return {"mode": mode, "turns": turns, "requested_in": asked, "scope": scope}


def with_exclusion(x, facts_on_3=True):
    a = analysis(exclusions=[x])
    if facts_on_3:                                            # 턴 3 의 남길 기억
        a["facts"].append(fact("f5", [3], "봉사 모임을 기억함"))
        a["units"][0]["facts"].append("f5")
        a["not_in_facts"] = [{"turns": [4], "reason": "시험용"}]
    return a


def test_b_request_and_content_in_one_turn_keeps_the_turn():
    a = with_exclusion(excl("partial", [3], [3]))
    assert check(a)[0] == "ready"                              # 502 가 아니다
    data, _ = base.source()
    assert pipe.excluded_turns(a) == set()                     # 요청 턴이라고 통째로 지우지 않는다
    src = pipe.stage_source(data, a)
    assert 3 in [u["turn"] for u in src["utterances"]]         # 편집 · 목차는 그 말씀을 받는다
    assert all(x.get("turn") != 3 for x in src["shared_state"]["facts_found"])     # 그 턴의 메모(뺄 내용을 담을 수 있다)는 주지 않는다
    note = pipe.exclusion_notices(a)[0]
    assert note["scope"] == "모임 이름" and note["note"] == pipe.SAME_TURN_NOTE and "지어 넣지 않는다" in note["note"]


def test_b_request_in_another_turn_removes_only_the_request_turn():
    a = with_exclusion(excl("partial", [3], [4]))
    a["not_in_facts"] = []
    assert check(a)[0] == "ready"
    assert pipe.excluded_turns(a) == {4}
    assert "note" not in pipe.exclusion_notices(a)[0]          # 예전 모양 그대로


def test_b_whole_turn_request_removes_the_turn_and_its_facts_are_refused():
    a = with_exclusion(excl("whole", [3], [4]), facts_on_3=False)
    a["not_in_facts"] = []
    assert check(a)[0] == "ready" and pipe.excluded_turns(a) == {3, 4}
    bad = with_exclusion(excl("whole", [3], [3]))              # 통째로 뺀 턴을 근거로 쓴 사실 — 여전히 멈춘다
    with pytest.raises(pipe.PipelineError):
        check(bad)


def test_b_same_turn_cannot_be_both_whole_and_partial():
    a = analysis(exclusions=[excl("partial", [3], [3]), excl("whole", [3], [4])])
    with pytest.raises(pipe.PipelineError) as e:
        check(a)
    assert e.value.kind == "reference" and "partial 과 whole" in e.value.message


def test_b_every_later_stage_gets_the_notice_and_the_style_writer_does_not_get_the_raw_turn():
    a = with_exclusion(excl("partial", [3], [3]))
    o = base.outline_ok()
    o["chapters"][0]["paragraphs"][0]["facts"].append("f5")
    order: list[str] = []
    fake = styled.Stages(base.script(analysis=a, outline=o, edit=styled.KEPT), order)
    w = styled.Writer(styled.NOVEL, order)
    data, turn_map = base.source()
    raw = base.elder(data, 3).strip()
    memo = raw[:len(raw) // 2]                                 # 분석이 남긴 사실 메모 — 그 말씀의 앞 절반 (전체 검사는 메모가 원문에 닿는지도 본다)
    a["facts"][-1]["text"] = memo
    res = asyncio.run(pipe.run(data, turn_map, call=fake, style="novel", style_call=w))
    assert res["generation_state"] == pipe.GENERATED, res["failure"]
    spec = next(s for s in w.specs if s.chapter_key == "ch-1")
    assert raw not in spec.user and memo in spec.user          # 원문 대신 분석이 남긴 사실 메모
    assert base.elder(data, 1).strip() in spec.user                             # 다른 말씀은 원문 그대로
    for stage in ("edit", "verify"):                           # 목차는 분석(exclusions 포함)을 그대로 받는다
        notices = fake.payload(stage)["exclusions"]
        assert notices[0]["scope"] == "모임 이름" and notices[0]["note"] == pipe.SAME_TURN_NOTE, stage
    assert raw in [u["elder"].strip() for u in fake.payload("verify")["source"]["utterances"]]     # 검증은 다시 나왔는지 보려고 원문을 받는다


def test_b_partial_turn_without_kept_facts_is_not_a_missing_turn():
    a = with_exclusion(excl("partial", [3], [3]), facts_on_3=False)           # 실모델이 낸 꼴 — 그 말씀에서 남긴 사실이 없다
    a["not_in_facts"] = [{"turns": [4], "reason": "시험용"}]
    assert check(a)[0] == "ready"
    a["exclusions"] = []
    with pytest.raises(pipe.PipelineError) as e:               # 제외에도 없으면 예전처럼 「어디에도 없는 턴」 이다
        check(a)
    assert "[3]" in str(e.value.details)


def test_b_style_source_drops_a_partial_turn_that_has_no_kept_fact():
    a = with_exclusion(excl("partial", [3], [3]), facts_on_3=False)
    src = {"utterances": [{"turn": 1, "elder": "첫 월급을 받았어요"}, {"turn": 3, "elder": "그 모임 이름은 쓰지 말아 주세요"}]}
    assert stage3.stories(src, a) == {1: "첫 월급을 받았어요"}
    assert stage3.stories(src) == {1: "첫 월급을 받았어요", 3: "그 모임 이름은 쓰지 말아 주세요"}     # 제외가 없으면 원문 그대로


def test_plain_cases_are_unchanged():
    a = analysis()
    before = copy.deepcopy(a)
    assert check(a)[0] == "ready"
    a.pop("normalized", None)
    assert a == before and pipe.excluded_turns(a) == set() and pipe.exclusion_notices(a) == []
