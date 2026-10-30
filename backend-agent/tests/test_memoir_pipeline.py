"""
자서전 5단계 파이프라인 v5 (단위 8P) — 모델도 DB 도 부르지 않는다.

    .venv\\Scripts\\python -m pytest tests/test_memoir_pipeline.py -v

호출 자리에 가짜를 끼운다(Fake). 단계마다 정해 둔 응답을 돌려주고, 받은 시스템
지시 · 자료 메시지를 남긴다. 기본 입력은 seed A 의 3회차(s-a · s-b · s-c, 말씀 6턴)다.

    턴 1 · 2 = s-a    턴 3 · 4 = s-b    턴 5 · 6 = s-c

v4 까지의 계약(사건 · 끈 · 장 입력 · 한 장 시험 계획)은 커밋 84c2f11 의 이 파일에 있다.
"""

from __future__ import annotations

import asyncio
import copy
import json
import random
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir, question                                  # noqa: E402
from app.session import memoir_pipeline as pipe                           # noqa: E402
from tools import memoir_blind as blind                                   # noqa: E402
from tools import memoir_pipeline as cli                                  # noqa: E402

SEED_A = json.loads((ROOT / "eval" / "memoir_seed_A.json").read_text(encoding="utf-8"))
SEED_B = json.loads((ROOT / "eval" / "memoir_seed_B.json").read_text(encoding="utf-8"))
SEED_C_PATH = ROOT / "eval" / "memoir_seed_C.json"
SLEEP = object()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(pipe.settings()):
        if k.startswith("MEMOIR_PIPE_"):
            monkeypatch.delenv(k, raising=False)


def source():
    return pipe.build_input(cli.records_from_seed(SEED_A, ["s-a", "s-b", "s-c"]))


def source_c():
    doc = cli._seed_doc(SEED_C_PATH)
    return pipe.build_input(cli.records_from_seed(doc, [s["alias"] for s in doc["sessions"]]))


def elder(data, turn):
    return next(u["elder"] for u in data["utterances"] if u["turn"] == turn)


def sent(text, facts, kind="supported"):
    return {"text": text, "kind": kind, "facts": list(facts)}


def fact(fid, turns, text="일", time="", source="self", certainty="stated", keep=False):
    return {"id": fid, "turns": list(turns), "text": text, "time": time, "source": source,
            "certainty": certainty, "keep": keep}


def analysis_ok():
    return {
        "status": "ready",
        "facts": [fact("f1", [1], "첫 월급", "1979년"), fact("f2", [2], "목도리를 사 드려 뿌듯했음"),
                  fact("f3", [5], "딸 입학", "1996년"), fact("f4", [6], "뭉클했음")],
        "units": [{"id": "m1", "name": "첫 월급", "facts": ["f1", "f2"], "time": "1979년", "weight": "main"},
                  {"id": "m2", "name": "딸 입학", "facts": ["f3", "f4"], "time": "1996년", "weight": "main"}],
        "threads": [],
        "people": [],
        "corrections": [],
        "themes": [{"theme": "배움", "supporting": [1], "counter": [], "strength": "clear"}],
        "direction": {"theme": "배움", "reason": "", "neutral": False},
        "exclusions": [],
        "not_in_facts": [{"turns": [3, 4], "reason": "시험용 — 쓰지 않음"}],
        "unclear": [],
        "missing_context": [],
    }


def para(facts, role="이어지는 기억", brief=(), time=""):
    return {"role": role, "facts": list(facts), "brief": list(brief), "time": time}


def chapter_plan(key, paragraphs, center="중심", units=("m1",), reorder=()):
    return {"chapter_key": key, "title": sent("편집 제목", [], "editorial"), "center": center,
            "experience": "핵심 경험", "units": list(units), "paragraphs": paragraphs, "reorder": list(reorder)}


def outline_ok():
    return {"status": "ready",
            "book": {"title": sent("책 제목", [], "editorial"), "center": "일과 가족", "flow": "",
                     "opening_facts": [], "closing_facts": ["f4"]},
            "chapters": [chapter_plan("ch-1", [para(["f1", "f2"])], "일", ["m1"]),
                         chapter_plan("ch-2", [para(["f3", "f4"])], "가족", ["m2"])],
            "omit": [],
            "missing_context": []}


def draft(key, facts):
    return {"chapter_key": key, "title": sent("장 제목", [], "editorial"),
            "paragraphs": [[sent("있었던 일이다.", facts), sent("이어서 적어 본다.", [], "editorial")]],
            "review_notes": []}


def edited_ok():
    return {"diagnosis": [{"issue": "장 사이가 끊긴다", "where": ["ch-1"], "action": "잇는다"}],
            "title": sent("책 제목", [], "editorial"),
            "chapters": [{"chapter_key": "ch-1", "center": "일", "title": sent("장 제목", [], "editorial"),
                          "paragraphs": [[sent("있었던 일이다.", ["f1", "f2"])]]},
                         {"chapter_key": "ch-2", "center": "가족", "title": sent("장 제목", [], "editorial"),
                          "paragraphs": [[sent("뒤의 일이다.", ["f3", "f4"])]]}],
            "omitted": [],
            "checks_resolution": [],
            "notes": []}


def quality(score=2, loc=("ch-1/p0",), **over):
    out = [{"item": q, "score": score, "locations": list(loc), "reason": "이유"} for q in pipe.QUALITY_ITEMS]
    for q, s in over.items():
        next(x for x in out if x["item"] == q)["score"] = s
    return out


def verify_ok(verdict="pass", **kw):
    out = {"review_status": "completed", "verdict": verdict, "issues": [], "quality": quality(),
           "reviewed_locations": ["artifact", "title", "ch-1/p0/s0", "ch-2/p0/s0"], "missing_context": []}
    out.update(kw)
    return out


def script(**over):
    s = {"analysis": analysis_ok(), "outline": outline_ok(), "ch-1": draft("ch-1", ["f1", "f2"]),
         "ch-2": draft("ch-2", ["f3", "f4"]), "edit": edited_ok(), "verify": verify_ok()}
    s.update({k.replace("_", "-"): v for k, v in over.items()})
    return s


class Fake:
    """단계 · 장마다 정해 둔 응답. dict 는 JSON 으로, str 은 원문 그대로, Reply 는 그대로."""

    def __init__(self, replies: dict):
        self.replies = replies
        self.specs: list[pipe.CallSpec] = []

    async def __call__(self, spec: pipe.CallSpec) -> pipe.Reply:
        self.specs.append(spec)
        v = self.replies[spec.chapter_key or spec.stage]
        if v is SLEEP:
            await asyncio.sleep(5)
        if isinstance(v, BaseException):
            raise v
        if isinstance(v, pipe.Reply):
            return v
        return pipe.Reply(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False), "STOP",
                          {"prompt": 10, "output": 5, "thoughts": 0, "total": 15})

    @property
    def order(self):
        return [s.chapter_key or s.stage for s in self.specs]

    def payload(self, stage, chapter_key=None):
        spec = next(s for s in self.specs if s.stage == stage and (chapter_key is None or s.chapter_key == chapter_key))
        return json.loads(spec.user.split("\n\n", 1)[1])


def go(fake, data=None, turn_map=None, recorder=None, focus=None):
    if data is None:
        data, turn_map = source()
    return asyncio.run(pipe.run(data, turn_map, call=fake, recorder=recorder, focus=focus,
                                meta={"run_ref": "test", "seed": "memoir_seed_A.json",
                                      "aliases": ["s-a", "s-b", "s-c"]}))


def all_turns(obj):
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("turns", "source_turns", "supporting", "counter", "link_turns"):
                found += v
            else:
                found += all_turns(v)
    elif isinstance(obj, list):
        for x in obj:
            found += all_turns(x)
    return found


def T_of(data):
    return {u["turn"] for u in data["utterances"]}


def seed_c_facts(data):
    """Seed C 턴마다 사실 하나 — 메모는 원문 그대로, 들은 이야기 표지 턴은 heard · 평가 표지 턴은 view
    (분석 계약을 지키는 최소 원장 — 시험용. 사실 수를 턴 수에 맞추라는 뜻이 아니다)."""
    marks = {m["turn"]: m for m in pipe.turn_marks(data)}
    src = pipe.source_texts(data)
    def kind(t):
        m = marks.get(t, {})
        return "heard" if m.get("heard") else "view" if m.get("view") else "self"
    return [fact(f"f{t}", [t], src[t], source=kind(t)) for t in sorted(T_of(data))]


# ---------------------------------------------------------------- 흐름


def test_t01_normal_run_calls_each_role_separately():
    fake = Fake(script())
    r = go(fake)
    assert fake.order == ["analysis", "outline", "ch-1", "ch-2", "edit", "verify"]
    assert r["calls"] == 2 + 4 and r["generation_state"] == "generated" and r["pipeline_complete"] is True
    assert (r["code_gate"], r["model_verdict"], r["human_review"]) == ("pass", "pass", "not_run")
    assert r["model_quality"]["meets_bar"] is True
    assert r["overall"] == "awaiting_human"                        # 사람 없이 approved 는 없다
    assert [c["chapter_key"] for c in r["chapters"]] == ["ch-1", "ch-2"]
    assert r["prompt_version"] == "v7"


def test_t02_each_call_has_its_own_role_prompt_and_common_rules():
    fake = Fake(script())
    go(fake)
    common = pipe.common_rules()
    roles = {s: pipe.role_text(s) for s in pipe.STAGES}
    for spec in fake.specs:
        assert spec.system.startswith(common)
        assert [s for s, t in roles.items() if t in spec.system] == [spec.stage]


def test_t03_source_text_goes_to_user_message_not_system():
    data, turn_map = source()
    fake = Fake(script())
    go(fake, data, turn_map)
    for u in data["utterances"]:
        for spec in fake.specs:
            assert u["elder"] not in spec.system
        assert u["elder"] in fake.specs[0].user


def test_t04_global_turns_are_never_renumbered_and_turns_come_from_facts():
    data, turn_map = source()
    want = copy.deepcopy(data["utterances"])
    fake = Fake(script())
    r = go(fake, data, turn_map)
    for spec in fake.specs:
        utts = json.loads(spec.user.split("\n\n", 1)[1])["source"]["utterances"]
        if spec.stage == "chapter":
            assert all(u in want for u in utts)
        else:
            assert utts == want
    assert data["utterances"] == want
    assert set(all_turns(r)) <= T_of(data)
    s = r["chapters"][0]["paragraphs"][0][0]
    assert s["facts"] == ["f1", "f2"] and s["turns"] == [1, 2]     # 코드가 사실 → 원문 턴을 펼친다


def test_t05_chapter_gets_only_its_plan_facts_and_their_turns():
    data, turn_map = source()
    fake = Fake(script())
    go(fake, data, turn_map)
    p1 = fake.payload("chapter", "ch-1")
    assert [u["turn"] for u in p1["source"]["utterances"]] == [1, 2]     # 앞뒤 문맥 턴을 붙이지 않는다
    assert [f["id"] for f in p1["facts"]] == ["f1", "f2"]
    assert elder(data, 5) not in json.dumps(p1, ensure_ascii=False)
    assert p1["other_chapters"] == [{"chapter_key": "ch-2", "title": "편집 제목", "center": "가족"}]
    assert "confirmed_facts" not in p1["source"]["shared_state"]


# ---------------------------------------------------------------- ① 분석


def test_t06_analysis_with_unknown_turn_stops_before_outline():
    a = analysis_ok()
    a["facts"][0]["turns"] = [1, 99]
    fake = Fake(script(analysis=a))
    r = go(fake)
    assert fake.order == ["analysis"]
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("analysis", "reference")


@pytest.mark.parametrize("mutate, kind, why", [
    (lambda a: a["units"][1]["facts"].append("f1"), "reference", "함께 있다"),
    (lambda a: a["units"][1].update(facts=["f3"]), "reference", "어느 기억 단위에도"),
    (lambda a: a.update(not_in_facts=[]), "reference", "[3, 4]"),
    (lambda a: a["facts"][0].update(source="told"), "format", "source"),
    (lambda a: a["facts"][0].update(certainty="maybe"), "format", "certainty"),
    (lambda a: a["facts"][0].pop("keep"), "format", "keep"),
    (lambda a: a.update(corrections=[{"fact": "f1", "turns": [1], "before": "1978년", "after": "1979년",
                                      "note": "x"}]), "reference", "정정 전 · 뒤"),
    (lambda a: a["facts"].append(fact("f1", [3])), "reference", "겹친다"),
])
def test_analysis_v5_contract(mutate, kind, why):
    data, _ = source()
    a = analysis_ok()
    mutate(a)
    with pytest.raises(pipe.PipelineError) as e:
        pipe.check_analysis(a, T_of(data))
    assert e.value.kind == kind and why in e.value.message


def test_heard_mark_needs_quote():
    """소리를 들은 것(「라디오를 들었어요」)은 전언 표시가 아니다 — 운영 10-29 분석 reference 실패."""
    def heard(text):
        return bool(pipe._HEARD_SRC.search(text))
    assert not heard("밤에 이불을 끼고 라디오를 들었어요.")
    assert not heard("아버지 없을 때에만 몰래 꺼내서 들었어요.")
    assert heard("산을 넘어 걸어서 왔다고 하더라고요.")
    assert heard("언니가 나를 업어 키웠다고 들었어요.")
    assert heard("엄마가 그날 울었대요.")


def test_heard_mark_mismatch_is_a_warning_not_a_failure():
    """표시는 힌트다 — 표시 턴에 heard 사실이 없어도 분석을 막지 않고 사람 확인 경고로 남긴다 (운영 10-30)."""
    data, _ = source_c()
    a = _seed_c_corrected(data)
    next(f for f in a["facts"] if f["id"] == "f10").update(source="self")    # 업어 키웠다고 하더라고요 → self
    errors, warnings = _diag(a, data)
    assert not any("남에게 들은 이야기 말투" in x for x in errors)
    assert any("턴 10 에 남에게 들은 이야기 말투" in x and "사람 확인" in x for x in warnings)
    pipe.check_analysis(a, T_of(data), pipe.turn_marks(data), pipe.source_texts(data), pipe.source_asked(data))


def test_analysis_v5_warnings_marks_units_and_years():
    data, _ = source_c()
    T = T_of(data)
    marks = {m["turn"]: m for m in pipe.turn_marks(data)}
    assert marks[10]["heard"] and marks[13]["heard"]                 # 업어 키웠다고 하더라고요 · 울었대요
    assert marks[2]["uncertain"] and marks[23]["uncertain"] and marks[28]["uncertain"]   # 했나 · 받았나 · 일 거예요
    assert 34 not in marks or not marks[34]["heard"]                 # 직접 겪은 별세
    assert 4 not in marks                                            # "보내 준 거예요" 는 흐림이 아니다
    facts = seed_c_facts(data)
    a = {**analysis_ok(), "facts": facts, "not_in_facts": [],
         "units": [{"id": f"m{t}", "name": "n", "facts": [f"f{t}"], "time": "", "weight": "minor"} for t in sorted(T)],
         "themes": [], "direction": {"theme": "", "reason": "", "neutral": True}}
    a["facts"][27]["time"] = "77년쯤, 2003년"                       # 두 방문을 한 사실로
    assert marks[25]["correction"] and not marks.get(32, {}).get("heard")   # 다시 생각해 보니 · "그래요"는 전언이 아니다
    _, w = pipe.check_analysis(a, T, pipe.turn_marks(data))
    assert any("턴 25 에 정정 말투가 있는데 정정 기록이 없다" in x for x in w)   # 추측하지 않고 검토 대상으로
    assert any("사실 하나" in x for x in w)                           # 사실마다 단위 하나 — 묶는 판단을 다시
    assert any("f28 의 시점이 여럿" in x for x in w)


def test_t14_insufficient_material_ends_after_one_call():
    a = {"status": "insufficient_material", "facts": [], "units": [], "threads": [], "people": [],
         "corrections": [], "themes": [], "direction": {"theme": "", "reason": "", "neutral": True},
         "exclusions": [], "not_in_facts": [], "unclear": [], "missing_context": []}
    fake = Fake(script(analysis=a))
    r = go(fake)
    assert fake.order == ["analysis"]
    assert r["generation_state"] == "insufficient_material" and r["failure"] is None


# ---------------------------------------------------------------- ② 목차 — 책 설계도


@pytest.mark.parametrize("chapters, kind", [
    ([], "format"),
    ([chapter_plan(f"ch-{i}", [para(["f1"])]) for i in range(1, pipe.MAX_CHAPTERS + 2)], "chapter_limit"),
    ([chapter_plan("ch-1", [para(["f9"])])], "reference"),
    ([chapter_plan("ch-1", [para([])])], "reference"),
    ([chapter_plan("ch-1", [])], "format"),
])
def test_t07_outline_checks_stop_before_chapters(chapters, kind):
    o = outline_ok()
    o["chapters"] = chapters
    fake = Fake(script(outline=o))
    r = go(fake)
    assert fake.order == ["analysis", "outline"]
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("outline", kind)


def test_outline_every_fact_is_used_or_omitted_with_reason():
    data, _ = source()
    T = T_of(data)
    o = outline_ok()
    o["chapters"] = [chapter_plan("ch-1", [para(["f1", "f2"])])]       # f3 · f4 가 사라졌다
    with pytest.raises(pipe.PipelineError, match=r"\['f3', 'f4'\]"):
        pipe.check_outline(o, analysis_ok(), T)
    o["omit"] = [{"facts": ["f3"], "reason": ""}]
    with pytest.raises(pipe.PipelineError, match="reason"):
        pipe.check_outline(o, analysis_ok(), T)
    o["omit"] = [{"facts": ["f3", "f4"], "reason": "이번 책의 중심과 다른 시기"}]
    o["book"]["closing_facts"] = ["f2"]
    assert pipe.check_outline(o, analysis_ok(), T)[0] == "ready"       # 모든 발언을 넣지 않아도 된다
    o["omit"].append({"facts": ["f1"], "reason": "x"})
    with pytest.raises(pipe.PipelineError, match="omit 에도"):
        pipe.check_outline(o, analysis_ok(), T)


def test_outline_warns_on_dropped_must_keep_reorder_and_listing_plan():
    data, _ = source()
    T = T_of(data)
    a = analysis_ok()
    a["facts"][3]["keep"] = True                                       # f4 — 직접 말한 감정
    o = outline_ok()
    o["chapters"][1]["paragraphs"] = [para(["f3"])]
    o["omit"] = [{"facts": ["f4"], "reason": "중복"}]
    o["book"]["closing_facts"] = ["f3"]
    _, w = pipe.check_outline(o, a, T)
    assert any("['f4'] 을 뺐다" in x for x in w)

    one = outline_ok()                                                 # 1996 문단 뒤에 1979 문단 — 이유 없음
    one["chapters"] = [chapter_plan("ch-1", [para(["f3", "f4"]), para(["f1", "f2"])], units=["m1", "m2"])]
    _, w = pipe.check_outline(one, analysis_ok(), T)
    assert any("ch-1/p1 가 앞 문단보다 이른" in x for x in w)
    one["chapters"][0]["reorder"] = [{"paragraph": 1, "reason": "딸을 보며 첫 월급을 떠올림", "facts": ["f4"]}]
    _, w = pipe.check_outline(one, analysis_ok(), T)
    assert not any("앞 문단보다 이른" in x for x in w)

    listing = outline_ok()
    listing["chapters"] = [chapter_plan("ch-1", [para([f]) for f in ("f1", "f2", "f3", "f4")], units=["m1", "m2"])]
    _, w = pipe.check_outline(listing, analysis_ok(), T)
    assert any("발언 나열 계획" in x for x in w)
    dup = outline_ok()
    dup["chapters"][1]["center"] = "일"
    _, w = pipe.check_outline(dup, analysis_ok(), T)
    assert any("center)이 겹친다" in x for x in w)


def test_focus_mode_is_one_chapter_five_calls_and_outline_knows_the_focus():
    data, _ = source()
    two = Fake(script())
    r = go(two, focus="첫 월급과 딸")
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("outline", "chapter_limit")
    assert two.payload("outline")["focus"] == {"theme": "첫 월급과 딸", "chapters": 1}

    o = outline_ok()
    o["chapters"] = [chapter_plan("ch-1", [para(["f1", "f2"]), para(["f3", "f4"])], units=["m1", "m2"])]
    e = edited_ok()
    e["chapters"] = [{"chapter_key": "ch-1", "center": "일과 딸", "title": sent("장", [], "editorial"),
                      "paragraphs": [[sent("있었던 일이다.", ["f1", "f2"])], [sent("뒤의 일이다.", ["f3", "f4"])]]}]
    fake = Fake(script(outline=o, ch_1=draft("ch-1", ["f1", "f2", "f3", "f4"]), edit=e,
                       verify=verify_ok(reviewed_locations=["artifact"])))
    r = go(fake, focus="첫 월급과 딸")
    assert fake.order == ["analysis", "outline", "ch-1", "edit", "verify"] and r["calls"] == 5
    assert fake.payload("edit")["focus"] == {"theme": "첫 월급과 딸", "chapters": 1}
    assert r["focus"] == "첫 월급과 딸" and r["pipeline_complete"] is True
    e2 = copy.deepcopy(e)
    e2["chapters"].append({**copy.deepcopy(e["chapters"][0]), "chapter_key": "ch-2"})
    with pytest.raises(pipe.PipelineError, match="정확히 1장"):
        pipe.check_final(e2, analysis_ok(), T_of(data), focus="x")


# ---------------------------------------------------------------- ③ 장 집필


def test_t08_chapter_timeout_stops_everything_after_it(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMOIR_PIPE_CHAPTER_TIMEOUT", "0.05")
    fake = Fake(script(ch_2=SLEEP))
    r = go(fake, recorder=pipe.Recorder(tmp_path))
    assert fake.order == ["analysis", "outline", "ch-1", "ch-2"]
    assert r["generation_state"] == "partial" and r["pipeline_complete"] is False
    assert (r["failure"]["stage"], r["failure"]["chapter_key"], r["failure"]["kind"]) == ("chapter", "ch-2", "timeout")
    assert r["chapters"] == [] and r["verification"]["state"] == "not_run"
    assert (tmp_path / "03_ch-1.json").exists() and not (tmp_path / "04_edited.json").exists()


def test_t09_truncated_or_broken_chapter_is_partial():
    cut = pipe.Reply(json.dumps(draft("ch-1", ["f1"]), ensure_ascii=False), "FinishReason.MAX_TOKENS")
    r = go(Fake(script(ch_1=cut)))
    assert (r["generation_state"], r["failure"]["kind"]) == ("partial", "truncated")
    r = go(Fake(script(ch_1='{"chapter_key": "ch-1", "title": ')))
    assert (r["generation_state"], r["failure"]["kind"]) == ("partial", "format")


def test_t10_supported_needs_facts_editorial_has_none_and_plan_bounds_facts():
    r = go(Fake(script(ch_1=draft("ch-1", []))))
    assert (r["generation_state"], r["failure"]["kind"]) == ("partial", "reference")
    d = draft("ch-1", ["f1"])
    d["paragraphs"][0][1]["facts"] = ["f2"]                            # editorial 에 사실
    r = go(Fake(script(ch_1=d)))
    assert r["failure"]["kind"] == "reference" and "editorial" in r["failure"]["message"]
    r = go(Fake(script(ch_1=draft("ch-1", ["f3"]))))                   # 다른 장 계획의 사실
    assert (r["failure"]["chapter_key"], r["failure"]["kind"]) == ("ch-1", "reference")
    assert "문단 계획에 없는" in r["failure"]["message"]
    d = draft("ch-1", ["f1"])
    d["paragraphs"][0][0]["turns"] = [1]                               # turns 는 모델이 아니라 코드가 쓴다
    d["paragraphs"][0][0].pop("facts")
    r = go(Fake(script(ch_1=d)))
    assert r["failure"]["kind"] == "format"


# ---------------------------------------------------------------- ④ 편집 — 구성 편집


@pytest.mark.parametrize("mutate, kind", [
    (lambda e: e["chapters"][0]["paragraphs"][0].append(sent("새 사실이다.", ["f42"])), "reference"),
    (lambda e: e["chapters"].reverse(), "reference"),                  # 장 키가 ch-1 부터가 아니다
    (lambda e: e.update(diagnosis=[]), "format"),
    (lambda e: e.update(omitted=[{"facts": ["f1"], "reason": ""}]), "format"),
    (lambda e: e.pop("notes"), "format"),
])
def test_t11_final_check_stops_before_verify(mutate, kind):
    e = edited_ok()
    mutate(e)
    fake = Fake(script(edit=e))
    r = go(fake)
    assert fake.order[-1] == "edit"
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("final_check", kind)


def test_edit_may_merge_split_and_reorder_and_code_measures_it(tmp_path):
    """편집이 구성을 바꾸면 결과물끼리 견줘 코드가 잰다 — 모델의 메모는 없어도 된다."""
    merged = edited_ok()
    merged["chapters"] = [{"chapter_key": "ch-1", "center": "일과 딸", "title": sent("장", [], "editorial"),
                           "paragraphs": [[sent("뒤의 일이다.", ["f3", "f4"]),
                                           sent("그보다 앞선 1979년의 일이다.", ["f1", "f2"])]]}]
    merged["notes"] = []
    fake = Fake(script(edit=merged, verify=verify_ok(reviewed_locations=["artifact"])))
    r = go(fake, recorder=pipe.Recorder(tmp_path))
    t = r["edit_trace"]
    assert (t["draft_chapters"], t["final_chapters"]) == (2, 1)
    assert t["chapter_merges"] == [] or t["structure_changed"]         # 한 문장씩이라 합침 기준(2문장)에 못 미쳐도
    assert t["moved"] == 1 and t["structure_changed"] is True          # 순서가 바뀐 것은 잡는다
    assert t["dropped"] == 2                                           # 초안의 잇는 문장 둘을 덜어 냈다
    trace = json.loads((tmp_path / "04_edit_trace.json").read_text(encoding="utf-8"))
    assert trace["unexplained_dropped_facts"] == []
    assert {x["kind"] for x in trace["sentences"]} <= {"kept", "revised", "rewritten", "new"}


def test_edit_trace_detects_unchanged_merge_split_and_dropped_facts():
    d1 = {"chapter_key": "ch-1", "title": sent("가", [], "editorial"), "paragraphs": [
        [sent("앞의 첫째 일이다.", ["f1"]), sent("앞의 둘째 일이다.", ["f2"])]]}
    d2 = {"chapter_key": "ch-2", "title": sent("나", [], "editorial"), "paragraphs": [
        [sent("뒤의 첫째 일이다.", ["f3"]), sent("뒤의 둘째 일이다.", ["f4"])]]}
    same = pipe.edit_trace([d1, d2], copy.deepcopy([d1, d2]))
    assert same["summary"]["unchanged_ratio"] == 1.0 and same["summary"]["structure_changed"] is False

    one = {"chapter_key": "ch-1", "title": sent("하나", [], "editorial"),
           "paragraphs": d1["paragraphs"] + d2["paragraphs"]}
    t = pipe.edit_trace([d1, d2], [one])["summary"]
    assert t["chapter_merges"] == ["ch-1"] and t["structure_changed"] is True
    t = pipe.edit_trace([one], [d1, d2])["summary"]
    assert t["chapter_splits"] == ["ch-1"]

    woven = {"chapter_key": "ch-1", "title": sent("하나", [], "editorial"),
             "paragraphs": [[sent("앞의 두 일과 뒤의 첫 일을 함께 떠올린다.", ["f1", "f2", "f3"])]]}
    tr = pipe.edit_trace([d1, d2], [woven], omitted={})
    assert tr["summary"]["rewritten"] == 1 and tr["summary"]["paragraph_merges"] == 0
    assert tr["dropped_facts"] == ["f4"] and tr["unexplained_dropped_facts"] == ["f4"]
    tr = pipe.edit_trace([d1, d2], [woven], omitted={"f4": "앞 문장과 같은 뜻"})
    assert tr["unexplained_dropped_facts"] == []


def test_edit_receives_facts_must_keep_checks_and_listing_signals():
    data, _ = source_c()
    T = sorted(T_of(data))
    a = {**analysis_ok(), "facts": seed_c_facts(data), "not_in_facts": [],
         "units": [{"id": "m1", "name": "전부", "facts": [f"f{t}" for t in T], "time": "", "weight": "main"}],
         "themes": [], "direction": {"theme": "", "reason": "", "neutral": True}}
    a["facts"][12].update(source="heard", keep=True)                   # 턴 13
    plan = [para([f"f{t}" for t in T])]
    o = {**outline_ok(), "chapters": [chapter_plan("ch-1", plan)], "book": {**outline_ok()["book"], "closing_facts": ["f39"]}}
    listing = {"chapter_key": "ch-1", "title": sent("장", [], "editorial"),
               "paragraphs": [[sent("그때의 일을 적는다.", [f"f{t}"]) for t in T]], "review_notes": []}
    e = {**edited_ok(), "chapters": [{"chapter_key": "ch-1", "center": "", "title": sent("장", [], "editorial"),
                                      "paragraphs": listing["paragraphs"]}]}
    fake = Fake({"analysis": a, "outline": o, "ch-1": listing, "edit": e,
                 "verify": verify_ok(reviewed_locations=["artifact"])})
    r = asyncio.run(pipe.run(data, [{"global_turn": t} for t in T], call=fake))
    p = fake.payload("edit")
    assert p["signals"][0]["listing"] is True and p["signals"][0]["one_to_one"] == 1.0
    assert "f13" in p["must_keep"] and len(p["facts"]) == 39
    assert any(c["rule"] == "hearsay_lost" and c["fact"] == "f13" for c in p["checks"])
    v = fake.payload("verify")
    assert v["plan"]["signals"][0]["listing"] is True and "edit_trace" in v["plan"]
    q = r["model_quality"]                                             # 검증이 2점을 줘도 나열이면 1점까지
    assert q["scores"]["Q2"] == q["scores"]["Q3"] == q["scores"]["Q5"] == 1 and q["meets_bar"] is False
    assert r["overall"] == "needs_revision"


# ---------------------------------------------------------------- 코드 판정


def _chapter(rows, key="ch-1"):
    return {"chapter_key": key, "title": sent("장", [], "editorial"),
            "paragraphs": [[sent(text, fs) for text, fs in rows]]}


def _expanded(chs, a):
    pipe.expand_turns(chs, pipe.ledger(a))
    return chs


def test_essay_ending_and_style_findings():
    ok = ["그해 봄에 가게를 열었다.", "나는 그 소리가 싫었다.", "편지에는 '밥은 먹고 다녀라'라고만 쓰여 있었다.",
          "'그건 내가 했다 싶어요.'"]
    bad = ["가게를 열었어요.", "가게를 열었습니다.", "그 소리가 싫었는데.", "가끔요."]
    assert all(pipe._essay_ending(x) for x in ok)
    assert not any(pipe._essay_ending(x) for x in bad)
    f = pipe.code_findings([_chapter([("가끔요. 그랬어요.", ["f1"]), ("그 얘긴 오늘은 그만할게요.", ["f2"]),
                                      ("이 장에서는 일을 다룬다.", ["f1"])])], outline_ok())
    rules = {(x["rule"], x["severity"]) for x in f}
    assert {("answer_trace", "fix"), ("style_mix", "fix"), ("stop_phrase", "block"), ("meta_text", "fix")} <= rules


def test_voice_findings_keep_hearsay_and_uncertainty():
    data, _ = source_c()
    a = {"facts": [fact("f10", [10], "업어 키웠다고 들음", source="heard"),
                   fact("f23", [23], "첫 손님에게 천 원쯤 받음", certainty="uncertain"),
                   fact("f11", [11], "열 살쯤 양말 꿰매기를 배움", "열 살쯤", certainty="approx")]}
    book = pipe.ledger(a)
    rows = [("언니가 나를 업어 키웠다.", ["f10"]),                         # 들은 이야기를 기억처럼
            ("언니가 나를 업어 키웠다고 들었다.", ["f10"]),
            ("첫 손님에게 천 원을 받았다.", ["f23"]),                     # 흐린 기억을 확정
            ("첫 손님에게 천 원쯤 받았던 것 같다.", ["f23"]),
            ("열 살쯤 양말 꿰매는 법을 배웠다.", ["f11"])]
    f = pipe.voice_findings([_chapter(rows)], book)
    assert [(x["rule"], x["location"]) for x in f] == [("hearsay_lost", "ch-1/p0/s0"), ("certainty_lost", "ch-1/p0/s2")]


def test_time_reversal_needs_a_time_mark():
    a = analysis_ok()
    ch = {"chapter_key": "ch-1", "title": sent("장", [], "editorial"),
          "paragraphs": [[sent("딸이 학교에 들어갔다.", ["f3"])], [sent("첫 월급을 받았다.", ["f1"])]]}
    f = pipe.time_findings([ch], pipe.ledger(a))
    assert [(x["rule"], x["location"]) for x in f] == [("time_reversal", "ch-1/p1")]
    ch["paragraphs"][1][0]["text"] = "그보다 훨씬 전, 첫 월급을 받았다."
    assert pipe.time_findings([ch], pipe.ledger(a)) == []


def test_must_keep_missing_unless_omitted_with_reason():
    a = analysis_ok()
    a["facts"][3]["keep"] = True
    a["corrections"] = [{"fact": "f3", "turns": [5, 6], "note": "x"}]
    a["facts"][2]["turns"] = [5, 6]
    a["facts"][3]["turns"] = [6]
    ch = [_chapter([("있었던 일이다.", ["f1", "f2"])])]
    f = pipe.keep_findings(ch, pipe.must_keep(a), {})
    assert {(x["rule"], x["fact"]) for x in f} == {("must_keep_missing", "f3"), ("must_keep_missing", "f4")}
    f = pipe.keep_findings(ch, pipe.must_keep(a), {"f3": "", "f4": "다른 장과 같은 뜻"})          # 목차의 생략
    assert {(x["rule"], x["severity"], x["fact"]) for x in f} == {("must_keep_missing", "fix", "f3"),
                                                                  ("must_keep_excluded", "review", "f4")}
    f = pipe.keep_findings(ch, pipe.must_keep(a), {}, {"f4": "다른 장과 같은 뜻"})                 # 편집의 생략
    assert {(x["rule"], x["severity"], x["fact"]) for x in f} == {("must_keep_missing", "fix", "f3"),
                                                                  ("must_keep_omitted", "fix", "f4")}


def test_fact_token_regression_cases():
    """v4 회귀 — 문맥 턴 14 의 나이 · 지명을 턴 15 로 표시, v4 전체의 '오십오 년'(원문은 이십오)."""
    data, _ = source_c()
    a = {"facts": [fact(f"f{t}", [t]) for t in sorted(T_of(data))]}
    rows = [("열일곱 살에 서울 동대문 근처 봉제 공장에 들어갔다.", ["f15"]),
            ("열일곱 살에 서울 동대문 근처 봉제 공장에 들어갔다.", ["f14", "f15"]),
            ("수선집을 오십오 년쯤 했다.", ["f1"]),
            ("그만둔 게 2010년이니 이십오 년쯤 했다.", ["f2"]),
            ("1985년 봄에 가게를 열었다.", ["f25"])]                         # 원문 '85년' — 끝 두 자리로 맞춘다
    f = pipe.fact_findings(_expanded([_chapter(rows)], a), data)
    by = {}
    for x in f:
        by.setdefault(x["location"], set()).add(x["token"])
    assert by == {"ch-1/p0/s0": {"열일곱 살", "서울", "동대문"}, "ch-1/p0/s2": {"오십오 년"}}


@pytest.mark.parametrize("rule, key", list(pipe.KEPT_ACCEPTED.items()))
def test_kept_with_reason_accepts_only_listed_rules_for_the_same_target(rule, key):
    f = {"id": f"{rule}:ch-1/p0/s0:x", "rule": rule, "severity": "fix", "location": "ch-1/p0/s0", key: "x"}
    kept = {f["id"]: {"check_id": f["id"], "status": "kept", "reason": "같은 뜻"}}
    assert pipe.code_gate([f], kept, [f])["state"] == "pass"
    other = dict(f, id="o", **{key: "y"})
    assert pipe.code_gate([other], kept, [f])["state"] == "attention"   # 다른 대상은 남는다


def test_kept_does_not_clear_style_or_missing_facts_or_blocks():
    for rule, sev, gate in (("style_mix", "fix", "attention"), ("must_keep_missing", "fix", "attention"),
                            ("hearsay_lost", "fix", "attention"), ("certainty_lost", "fix", "attention"),
                            ("time_reversal", "fix", "attention"), ("stop_phrase", "block", "blocked")):
        f = {"id": "c", "rule": rule, "severity": sev, "location": "artifact", "fact": "f1"}
        kept = {"c": {"check_id": "c", "status": "kept", "reason": "그대로 두는 게 낫다"}}
        g = pipe.code_gate([f], kept, [f])
        assert g["state"] == gate, rule
        assert pipe.overall_state("generated", g, {"state": "completed", "verdict": "pass"}, "not_run",
                                  {"meets_bar": True}) in ("needs_revision", "blocked_by_code")


def test_run_with_all_kept_but_problems_left_stays_needs_revision():
    d1 = draft("ch-1", ["f1", "f2"])
    d1["paragraphs"][0].append(sent("가끔요. 그랬어요.", ["f1"]))
    e = edited_ok()
    e["chapters"][0]["paragraphs"][0].append(sent("가끔요. 그랬어요.", ["f1"]))
    fake = Fake(script(ch_1=d1, edit=e, verify=verify_ok(reviewed_locations=["artifact"])))

    async def call(spec):
        r = await fake(spec)
        if spec.stage == "edit":
            checks = json.loads(spec.user.split("\n\n", 1)[1])["checks"]
            out = json.loads(r.text)
            out["checks_resolution"] = [{"check_id": c["id"], "status": "kept", "reason": "원문 말투"} for c in checks]
            return pipe.Reply(json.dumps(out, ensure_ascii=False), "STOP")
        return r
    r = go(call)
    assert r["model_verdict"] == "pass" and r["code_gate"] == "attention" and r["overall"] == "needs_revision"


# ---------------------------------------------------------------- ⑤ 검증 — 사실 + 구성 채점


def test_t12_verify_revise_is_recorded_not_rewritten():
    issue = {"location": "ch-1/p0/s0", "category": "fact", "severity": "blocker", "code": "source_mismatch",
             "resolution": "auto_fix", "explanation": "들은 이야기를 기억처럼", "source_turns": [1],
             "fix_instruction": "y"}
    fake = Fake(script(verify=verify_ok("revise", issues=[issue])))
    r = go(fake)
    assert len(fake.specs) == 6 and r["model_verdict"] == "revise" and r["overall"] == "needs_revision"


@pytest.mark.parametrize("bad", [
    verify_ok(reviewed_locations=["artifact", "ch-7/p0/s0"]),
    verify_ok(verdict=None),
    verify_ok(quality=quality()[:5]),                                  # Q6 이 빠짐
    verify_ok(quality=quality(score=3)),
    {k: v for k, v in verify_ok().items() if k != "quality"},
    verify_ok("pass", issues=[{"location": "ch-1/p0/s0", "category": "fact", "severity": "blocker",
                               "code": "unsupported_claim", "resolution": "auto_fix", "explanation": "",
                               "source_turns": [], "fix_instruction": ""}]),
])
def test_t13_verify_shape_error_marks_verification_failed(bad):
    r = go(Fake(script(verify=bad)))
    assert r["generation_state"] == "generated" and r["pipeline_complete"] is False
    assert r["verification"]["state"] == "failed" and r["failure"]["stage"] == "verify"
    assert r["overall"] == "needs_revision"


def test_quality_location_outside_candidate_is_no_evidence():
    r = go(Fake(script(verify=verify_ok(quality=quality(loc=("ch-9/p0",))))))
    assert r["verification"]["state"] == "completed"                   # 실패로 막지 않는다
    assert r["model_quality"]["scores"] == {q: 0 for q in pipe.QUALITY_ITEMS} and r["overall"] == "needs_revision"


def test_quality_without_locations_is_zero_and_style_caps_voice():
    q = quality()
    q[0]["locations"] = []
    adj = pipe.adjust_quality(q, [], [])
    assert adj["scores"]["Q1"] == 0 and adj["meets_bar"] is False
    assert adj["adjusted"][0]["why"] == "근거 위치 없음"
    adj = pipe.adjust_quality(quality(), [], [{"rule": "style_mix"}])
    assert adj["scores"]["Q6"] == 1 and adj["meets_bar"] is False
    assert pipe.adjust_quality(quality(Q4=1), [], [])["meets_bar"] is True      # 2점 넷 · 0점 없음
    assert pipe.adjust_quality(quality(Q4=1, Q5=1), [], [])["meets_bar"] is False
    assert pipe.adjust_quality(quality(Q1=0), [], [])["meets_bar"] is False


def test_model_pass_is_not_publishable_quality():
    """사실 pass · 코드 pass 여도 구성 채점이 기준에 못 미치면 needs_revision. approved 는 사람만."""
    r = go(Fake(script(verify=verify_ok(quality=quality(score=1)))))
    assert (r["code_gate"], r["model_verdict"]) == ("pass", "pass")
    assert r["model_quality"]["meets_bar"] is False and r["overall"] == "needs_revision"
    g = {"state": "pass"}
    v = {"state": "completed", "verdict": "pass"}
    assert pipe.overall_state("generated", g, v, "not_run", {"meets_bar": True}) == "awaiting_human"
    assert pipe.overall_state("generated", g, v, "passed", {"meets_bar": True}) == "approved"
    assert pipe.overall_state("partial", g, v, "not_run", {"meets_bar": True}) == "not_generated"


def test_verify_gets_ledger_plan_signals_and_trace():
    fake = Fake(script())
    go(fake)
    p = fake.payload("verify")
    assert [f["id"] for f in p["facts"]] == ["f1", "f2", "f3", "f4"]
    assert [c["center"] for c in p["plan"]["chapters"]] == ["일", "가족"]
    assert {"signals", "edit_trace", "code_findings", "checks"} <= set(p["plan"])
    assert p["candidate"]["chapters"][0]["paragraphs"][0][0]["turns"] == [1, 2]


def test_listing_signals_match_the_v4_measurement():
    data, _ = source_c()
    a = {"facts": [fact(f"f{t}", [t]) for t in sorted(T_of(data))]}
    rows = [("그 일이 있었다.", [f"f{t}"]) for t in range(1, 9)]
    s = pipe.listing_signals(_expanded([_chapter(rows)], a), data)[0]
    assert (s["one_to_one"], s["order_kept"], s["links"], s["listing"]) == (1.0, 1.0, 0, True)
    woven = [("앞뒤 회차의 일을 함께 적는다.", ["f4", "f26", "f35"]), ("그 무렵의 일이다.", ["f3"]),
             ("지금도 그 일을 떠올린다.", ["f38", "f39"]), ("새 사실이 없는 잇는 문장이다.", []),
             ("처음 일을 배운 때를 적는다.", ["f11", "f12"])]
    ch = {"chapter_key": "ch-1", "title": sent("장", [], "editorial"),
          "paragraphs": [[sent(t, fs, "editorial" if not fs else "supported") for t, fs in woven]]}
    s = pipe.listing_signals(_expanded([ch], a), data)[0]
    assert s["listing"] is False and s["links"] >= 3 and s["multi_session_paragraphs"] == 1


# ---------------------------------------------------------------- 실패 · 설정 · 입력 · 기록


def test_t15_no_retry():
    fake = Fake(script(outline=RuntimeError("일시 오류")))
    r = go(fake)
    assert fake.order == ["analysis", "outline"] and r["failure"]["kind"] == "call" and pipe.RETRIES == 0


def test_t16_missing_key_fails_without_network(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(question, "_CLIENT", None)
    data, turn_map = source()
    r = asyncio.run(pipe.run(data, turn_map, call=pipe.call_model))
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("analysis", "call")
    assert "GEMINI_API_KEY" in r["failure"]["message"]


def test_t17_pipeline_and_service_settings_are_separate(monkeypatch):
    monkeypatch.delenv("MEMOIR_TEXT_MODEL", raising=False)
    monkeypatch.setenv("MEMOIR_PIPE_TEXT_MODEL", "pipe-model")
    monkeypatch.setenv("MEMOIR_PIPE_EDIT_TIMEOUT", "7")
    assert memoir.settings()["MEMOIR_TEXT_MODEL"] == memoir.DEFAULT_TEXT_MODEL
    monkeypatch.setenv("MEMOIR_TEXT_MODEL", "service-model")
    s = pipe.settings()
    assert s["MEMOIR_PIPE_TEXT_MODEL"] == "pipe-model" and s["MEMOIR_PIPE_EDIT_TIMEOUT"] == 7.0
    assert not any(k.startswith("MEMOIR_TEXT") for k in s)


def test_t17b_default_limits_v5():
    s = pipe.settings()
    want = {"ANALYSIS": (90, 8000), "OUTLINE": (60, 6000), "CHAPTER": (90, 6000),
            "EDIT": (150, 10000), "VERIFY": (90, 6000)}
    for st, (sec, tok) in want.items():
        assert (s[f"MEMOIR_PIPE_{st}_TIMEOUT"], s[f"MEMOIR_PIPE_{st}_MAX_OUTPUT_TOKENS"]) == (sec, tok)
    assert s["MEMOIR_PIPE_TOTAL_TIMEOUT"] == 600 and s["retries"] == 0 and s["chapters"] == [1, 10]


def _memoir_input_file(tmp_path, data, turn_map, **over):
    doc = {"set_id": "A", "aliases": ["s-a", "s-b", "s-c"], "session_ids": [], "input": data, "turn_map": turn_map}
    doc.update(over)
    p = tmp_path / "in.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def test_t18_rejects_bad_schema_or_disallowed_input(tmp_path):
    data, turn_map = source()
    got, _, meta = cli.load_input(_memoir_input_file(tmp_path, data, turn_map))
    assert got == data and meta["set_id"] == "A"
    with pytest.raises(cli.InputRejected):
        cli.records_from_seed(SEED_A, ["s-a", "s-b"])
    with pytest.raises(cli.InputRejected):
        cli.records_from_seed(SEED_A, ["s-a", "s-b", "s-z"])
    real = copy.deepcopy(data)
    real["utterances"][0]["elder"] = "seed 에 없는 실제 말씀"
    with pytest.raises(cli.InputRejected, match="합성 자료만"):
        cli.load_input(_memoir_input_file(tmp_path, real, turn_map))
    renum = copy.deepcopy(data)
    renum["utterances"][0]["turn"] = 7
    with pytest.raises(cli.InputRejected):
        cli.load_input(_memoir_input_file(tmp_path, renum, turn_map))
    fake = Fake(script())
    r = go(fake, renum, turn_map)
    assert fake.specs == [] and (r["failure"]["stage"], r["failure"]["kind"]) == ("input", "input")


def test_t18b_session_range_follows_server_constant_style(monkeypatch):
    monkeypatch.delattr(memoir, "max_sessions", raising=False)
    monkeypatch.setattr(memoir, "MAX_SESSIONS", 4, raising=False)
    assert cli.session_range() == (memoir.MIN_SESSIONS, 4)
    with pytest.raises(cli.InputRejected, match="3~4"):
        cli.records_from_seed(SEED_A, ["s-a", "s-b", "s-c", "s-d", "s-e"])


def test_t18c_session_range_follows_server_function_style(monkeypatch):
    monkeypatch.delattr(memoir, "MAX_SESSIONS", raising=False)
    monkeypatch.setenv("MEMOIR_MAX_SESSIONS", "4")
    monkeypatch.setattr(memoir, "max_sessions",
                        lambda: int(__import__("os").environ["MEMOIR_MAX_SESSIONS"]), raising=False)
    assert cli.session_range() == (memoir.MIN_SESSIONS, 4)


def test_t18d_session_range_without_any_limit_refuses(monkeypatch):
    monkeypatch.delattr(memoir, "MAX_SESSIONS", raising=False)
    monkeypatch.delattr(memoir, "max_sessions", raising=False)
    with pytest.raises(cli.InputRejected, match="찾지 못했다"):
        cli.records_from_seed(SEED_A, ["s-a", "s-b", "s-c"])


def test_t18e_tools_use_only_names_both_servers_have():
    shared = {"merge", "MemoirError", "DEFAULT_TEXT_MODEL", "MIN_SESSIONS", "settings"}
    for path in (ROOT / "tools" / "memoir_pipeline.py", ROOT / "tools" / "memoir_blind.py",
                 ROOT / "app" / "session" / "memoir_pipeline.py"):
        used = set(re.findall(r"(?<![\w.])memoir\.(\w+)", path.read_text(encoding="utf-8")))
        assert used <= shared, f"{path.name}: {sorted(used - shared)}"


def test_t19_run_folder_has_stage_files_without_secrets_or_text(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-value-123")
    data, turn_map = source()
    r = go(Fake(script()), data, turn_map, pipe.Recorder(tmp_path))
    names = {p.name for p in tmp_path.iterdir()}
    for n in ("00_input.json", "01_analysis.json", "02_outline.json", "03_ch-1.json", "03_ch-2.json",
              "03_checks.json", "04_edited.json", "04_edit_trace.json", "04_code_gate.json", "05_verify.json",
              "result.json", "run.json", "r1_summary.md"):
        assert n in names
    for p in tmp_path.iterdir():
        assert "test-secret-value-123" not in p.read_text(encoding="utf-8")
    summary = (tmp_path / "r1_summary.md").read_text(encoding="utf-8")
    for u in data["utterances"]:
        assert u["elder"] not in summary
    assert "있었던 일이다" not in summary and "편집 추적" in summary and "구성 채점" in summary
    assert "Q7 사실 충실" in summary and r["run_ref"] == "test"


def test_t20_prompts_load_v7_and_earlier_versions_kept():
    assert pipe.PROMPT_VERSION == "v7" and all(f.endswith("_v7.md") for f in pipe.ROLE_FILES.values())
    for f in pipe.ROLE_FILES.values():
        for old in ("_v1", "_v2", "_v3", "_v4", "_v5"):                # 실행 기록의 옛 판을 지우지 않는다
            assert (pipe.ROLE_DIR / f.replace("_v7", old)).exists()
    common = pipe.common_rules()
    assert common.startswith("당신은") and "## 5." not in common
    src = (ROOT / "app" / "session" / "memoir_pipeline.py").read_text(encoding="utf-8")
    assert "_sections" not in src and "memoir._ints" not in src and "roledoc" not in src
    assert not re.search(r"(?<!5_)검증_v4\.md", src)


def test_prompts_v5_carry_the_book_contract_without_seed_c_text():
    a, o, c, e, v = (pipe.role_text(s) for s in pipe.STAGES)
    assert "사실 원장" in a and "기억 단위" in a and "사실마다 문장을 하나씩 쓰라는 뜻이 아닙니다" in a
    assert "모든 발언을 본문에 넣지 않아도 됩니다" in o and "reorder" in o and "experience" in o
    assert "한 턴을 한 문장으로 차례로 옮기지 마세요" in c and "정해져 있지 않습니다" in c
    assert "들은 이야기로 씁니다" in c and "흐린 채로" in c and "인생 교훈" in c
    assert "제안일 뿐이고 바꿀 수 있습니다" in e and "diagnosis" in e and "장 합치기 · 나누기" in e
    assert "근거 위치가 없는 점수는 0점" in v and "출판 품질 승인이 아닙니다" in v
    doc = cli._seed_doc(SEED_C_PATH)
    frags = {x for s in doc["sessions"] for t in s["turns"]
             for x in re.split(r"[.,?!…'\"]\s*", t["answer"]) if len(x.strip()) >= 8}
    for stage in pipe.STAGES:
        text = pipe.role_text(stage)
        assert not [x for x in frags if x.strip() in text], stage
        assert "seed-C-evaluation" not in pipe.prompt(stage)


def test_t21_total_time_budget_stops_before_next_call(monkeypatch):
    monkeypatch.setenv("MEMOIR_PIPE_TOTAL_TIMEOUT", "0")
    fake = Fake(script())
    r = go(fake)
    assert fake.specs == [] and (r["failure"]["stage"], r["failure"]["kind"]) == ("analysis", "budget")


def test_t38_test_guard_blocks_external_calls():
    """tests/conftest.py — 실제 키가 .env 에 있어도 시험은 외부를 부르지 않는다."""
    import os
    import socket
    from tests import conftest
    assert conftest.ALLOW_NETWORK is False
    for k in conftest.KEY_NAMES:
        assert os.environ.get(k) == ""
    assert question._client() is None
    import google.genai as genai
    before = len(conftest.BLOCKED)
    with pytest.raises(conftest.ExternalCallBlocked):
        genai.Client(api_key="x")
    s = socket.socket()
    try:
        with pytest.raises(conftest.ExternalCallBlocked):
            s.connect(("203.0.113.1", 443))
    finally:
        s.close()
    assert len(conftest.BLOCKED) == before + 2
    del conftest.BLOCKED[before:]


def test_cli_focus_dry_run_and_rejects_long_focus(capsys):
    args = ["--seed", str(SEED_C_PATH), "--aliases", "c1,c2,c3,c4,c5", "--dry-run"]
    assert cli.main(args + ["--focus", "큰 소재"]) == 0
    out = capsys.readouterr().out
    assert "예상 호출 5회" in out and "지시문 v7" in out and "모델을 부르지 않았다" in out
    assert cli.main(args + ["--focus", "가" * (cli.FOCUS_MAX_CHARS + 1)]) == 2
    assert cli.main(args) == 0 and "예상 호출 5~14회" in capsys.readouterr().out


# ---------------------------------------------------------------- 제외 (seed B)


def source_b():
    """턴 1 · 2 = s-r1 · 3 · 4 · 5 = s-r2 (5 가 제외 요청) · 6 · 7 = s-r3 (6 이 정정)."""
    return pipe.build_input(cli.records_from_seed(SEED_B, ["s-r1", "s-r2", "s-r3"]))


def analysis_b(partial=False):
    a = analysis_ok()
    a["facts"] = [fact("f1", [1, 6], "딸 입학", "1996년"), fact("f2", [2, 7], "노란 가방 · 딸은 울지 않음 · 뭉클"),
                  fact("f3", [3, 4] if partial else [3], "꽃집 첫 손님")]
    a["units"] = [{"id": "m1", "name": "딸 입학", "facts": ["f1", "f2"], "time": "1996년", "weight": "main"},
                  {"id": "m2", "name": "꽃집", "facts": ["f3"], "time": "", "weight": "main"}]
    a["corrections"] = [{"fact": "f1", "turns": [1, 6], "before": "1998년", "after": "1996년",
                         "note": "입학 연도를 고쳐 말함"}]
    a["exclusions"] = [{"mode": "partial" if partial else "whole", "turns": [4], "requested_in": [5],
                        "scope": "빌린 사람과 금액"}]
    a["not_in_facts"] = []
    return a


def test_t24_exclusions_are_kept_out_of_facts_and_chapter_input():
    data, _ = source_b()
    T = T_of(data)
    a = analysis_b()
    assert pipe.check_analysis(a, T)[0] == "ready" and pipe.excluded_turns(a) == {4, 5}
    assert pipe.must_keep(a) == {"f1"}                                 # 정정된 사실
    bad = copy.deepcopy(a)
    bad["facts"][2]["turns"] = [3, 4]
    with pytest.raises(pipe.PipelineError, match="빼 달라고"):
        pipe.check_analysis(bad, T)
    src, given = pipe.chapter_source(data, a, chapter_plan("ch-1", [para(["f3"])]))
    assert given == [3] and all(u["turn"] not in (4, 5) for u in src["utterances"])


def test_t34_partial_exclusion_keeps_turn_but_drops_memo_and_warns_stages():
    data, _ = source_b()
    a = analysis_b(partial=True)
    assert pipe.check_analysis(a, T_of(data))[0] == "ready" and pipe.excluded_turns(a) == {5}
    ch = chapter_plan("ch-1", [para(["f3"])])
    src, given = pipe.chapter_source(data, a, ch)
    assert given == [3, 4] and all(x["turn"] != 4 for x in src["shared_state"]["facts_found"])
    o = {**outline_ok(), "chapters": [ch]}
    payload = json.loads(pipe.chapter_message(src, a, o, ch).split("\n\n", 1)[1])
    assert payload["exclusions"] == [{"mode": "partial", "turns": [4], "requested_in": [5], "scope": "빌린 사람과 금액"}]


def test_t35_outline_and_edit_sources_drop_excluded_turns_and_memos():
    data, _ = source_b()
    for a, gone in ((analysis_b(), {4, 5}), (analysis_b(partial=True), {5})):
        for msg in (pipe.outline_message(data, a), pipe.edit_message(data, a, outline_ok(), [], [], [])):
            payload = json.loads(msg.split("\n\n", 1)[1])
            assert {u["turn"] for u in payload["source"]["utterances"]} == {1, 2, 3, 4, 6, 7} - gone
            assert "빼 주세요" not in msg
            assert "빌림" not in json.dumps(payload["source"], ensure_ascii=False)
            assert ("삼백만" in json.dumps(payload["source"], ensure_ascii=False)) == (4 not in gone)
    a0, _ = source()
    assert pipe.stage_source(a0, analysis_ok()) is a0


def test_t36_verify_keeps_full_source_with_exclusion_notice():
    data, _ = source_b()
    a = analysis_b()
    msg = pipe.verify_message(data, a, edited_ok(), T_of(data), {}, pipe.exclusion_notices(a))
    payload = json.loads(msg.split("\n\n", 1)[1])
    assert [u["turn"] for u in payload["source"]["utterances"]] == [1, 2, 3, 4, 5, 6, 7]
    assert payload["exclusions"][0]["mode"] == "whole"


@pytest.mark.parametrize("bad, kind", [
    ({"mode": "partial", "turns": [4], "requested_in": [5], "scope": ""}, "format"),
    ({"mode": "partial", "turns": [], "requested_in": [5], "scope": "x"}, "reference"),
    ({"turns": [4], "requested_in": [5], "scope": "x"}, "format"),
    ({"mode": "partial", "turns": [5], "requested_in": [5], "scope": "x"}, "reference"),
])
def test_t37_exclusion_shape(bad, kind):
    data, _ = source_b()
    a = analysis_b(partial=True)
    a["exclusions"] = [bad]
    with pytest.raises(pipe.PipelineError) as e:
        pipe.check_analysis(a, T_of(data))
    assert e.value.kind == kind


# ---------------------------------------------------------------- Seed C


def test_t44_seed_c_uses_pipeline_only_check_without_touching_team_tool():
    from tools import seed_sessions as seed
    doc = json.loads(SEED_C_PATH.read_text(encoding="utf-8"))
    assert seed.SET_IDS == ("A", "B")
    assert cli.check_pipeline_seed(doc) == [] and cli.check_pipeline_seed(SEED_A) == []
    for bad, why in ((dict(doc, synthetic=False), "synthetic"), (dict(doc, set_id="D"), "set_id")):
        assert any(why in m for m in cli.check_pipeline_seed(bad)), why


def test_t45_seed_c_merges_into_39_global_turns_without_loss():
    doc = cli._seed_doc(SEED_C_PATH)
    data, turn_map = source_c()
    assert sorted(pipe.check_input(data, turn_map)) == list(range(1, 40))
    want = [t["answer"].strip() for s in sorted(doc["sessions"], key=lambda s: s["recorded_order"]) for t in s["turns"]]
    assert [u["elder"] for u in data["utterances"]] == want
    assert pipe.input_ref(data) == "b9f8e2daea65"                      # 입력 식별값 그대로
    assert any("1986" in f for f in data["shared_state"]["confirmed_facts"]) and "85년" in data["utterances"][24]["elder"]


def test_t46_seed_c_input_file_is_accepted_and_eval_doc_is_not_model_input(tmp_path):
    data, turn_map = source_c()
    p = _memoir_input_file(tmp_path, data, turn_map, set_id="C", aliases=["c1", "c2", "c3", "c4", "c5"])
    got, _, meta = cli.load_input(p)
    assert got == data and meta["seed"] == "memoir_seed_C.json"
    assert not list(pipe.ROLE_DIR.glob("*evaluation*"))


# ---------------------------------------------------------------- 블라인드 평가 자료


def _result(run_ref, chapters, version, ref):
    return {"run_ref": run_ref, "input_ref": ref, "prompt_version": version,
            "title": sent("책", [], "editorial"), "chapters": chapters}


def test_blind_material_hides_version_and_keeps_fact_sheet_apart(tmp_path):
    data, _ = source_c()
    ref = pipe.input_ref(data)
    a = {"facts": [fact(f"f{t}", [t]) for t in sorted(T_of(data))]}
    v4 = _expanded([_chapter([("가게 일을 적는다.", ["f3"])])], a)
    v5 = _expanded([_chapter([("발틀과 언니를 함께 적는다.", ["f4", "f26"])])], a)
    p4, p5 = tmp_path / "r4.json", tmp_path / "r5.json"
    p4.write_text(json.dumps(_result("20261026T083021Z-C5-b9f8-trial", v4, "v4", ref), ensure_ascii=False), encoding="utf-8")
    trial = {"run_ref": "x-trial", "input_ref": ref, "prompt_version": "v4", "draft": v4[0]}
    p4.write_text(json.dumps(trial, ensure_ascii=False), encoding="utf-8")       # v4 한 장 시험 모양도 받는다
    p5.write_text(json.dumps(_result("r-focus", v5, "v5", ref), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "blind"
    key = blind.make([p4, p5], data, out, random.Random(1))
    assert set(key) == {"가", "나"} and {k["prompt_version"] for k in key.values()} == {"v4", "v5"}
    for f in (out / "평가용").iterdir():
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"v[45]|trial|focus|turn|턴|f\d", text), f.name   # 버전 · 실행 · 근거 표시 없음
    sheet = (out / "검수자용" / f"사실대조표_{[k for k, v in key.items() if v['prompt_version'] == 'v5'][0]}.md").read_text(encoding="utf-8")
    assert "[26]" in sheet and elder(data, 26) in sheet
    firsts = {blind.make([p4, p5], data, tmp_path / f"b{i}", random.Random(i))["가"]["path"] for i in range(8)}
    assert len(firsts) == 2                                            # 제시 순서가 무작위로 바뀐다
    other = tmp_path / "other.json"
    other.write_text(json.dumps(_result("o", v5, "v5", "000000000000"), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="같은 자료"):
        blind.make([p4, other], data, tmp_path / "x", random.Random(0))

# ---------------------------------------------------------------- 실행 전 확인 — v4 에서 옮겨 온 조건 · 구조 이동 · 비교 조건


def test_t33_seed_b_turn4_mixes_kept_and_excluded_content():
    """전제 확인 — seed B 의 제외는 말씀 속 요청(턴 5)이고, 턴 4 한 문장에 남길 것과 뺄 것이 섞였다."""
    data, _ = source_b()
    t = {u["turn"]: u["elder"] for u in data["utterances"]}
    assert "꽃집" in t[4] and "빌렸" in t[4]
    assert "빼 주세요" in t[5] and "남겨 주세요" in t[5]
    assert "꽃집" in t[3] and "빌" not in t[3]
    # merge 는 제외를 모른다 — 메모에도 그대로 남아 있다
    assert any("빌림" in f for x in data["shared_state"]["facts_found"] if x["turn"] == 4 for f in x["facts"])
    assert any("빌림" in f for f in data["shared_state"]["confirmed_facts"])


def test_t47_seed_c_timeline_people_and_correction_are_consistent():
    """
    Seed C 원문끼리의 연대기 · 인물 관계. 출생 연도는 원문에 없고, 원문이 정하는 범위 안에서 맞물린다.
    전역 턴 번호로 짚는다 (c1 1~8 · c2 9~18 · c3 19~24 · c4 25~33 · c5 34~39).
    """
    import re
    doc = cli._seed_doc(SEED_C_PATH)
    t = {}
    g = 0
    for s in sorted(doc["sessions"], key=lambda s: s["recorded_order"]):
        for x in s["turns"]:
            g += 1
            t[g] = x["answer"]
    assert len(t) == 39
    all_text = " ".join(t.values())
    assert not re.search(r"(19|20)\d\d년생|태어난 해|\d+살 때 태어", all_text)   # 출생 연도를 정하지 않는다

    # 딸 — 83년에 네 살(19), 85년에 여섯 살(25) → 같은 해에 태어났다
    assert "딸이 네 살" in t[19] and "83년" in t[19]
    assert "여섯 살" in t[25] and "85년" in t[25]
    assert 1983 - 4 == 1985 - 6
    # 아들 — 돌 지나고 77년쯤(28). 상경 열일곱(14) + 한 육 년(18) 뒤 결혼 → 출생 1953년 이전이어야 성립
    assert "아들 돌" in t[28] and "77년" in t[28]
    assert "열일곱" in t[14] and "육 년" in t[18]
    assert (1977 - 1) - 6 - 17 <= 1953
    # 수선집 — 85년 봄(25) ~ 2010년(2 · 35), "한 이십오 년"(2)
    assert "이십오 년" in t[2] and "2010" in t[2] and "2010" in t[35]
    assert 2010 - 1985 == 25
    # 정정은 시험 항목으로 남는다 — 21 은 86년, 25 가 85년 봄으로 고친다
    assert "86년" in t[21] and "86년" in t[25] and "85년 봄" in t[25]
    # 큰언니 — 2003 병문안(29) → 그다음 해 2004 별세(34). 34 는 주어 · 기준을 발언 안에 갖는다
    assert "2003" in t[29] and "병원" in t[29]
    assert "큰언니" in t[34] and "병원" in t[34] and "그다음 해" in t[34] and "2004" in t[34]
    # 33 은 남편(2015), 34 는 큰언니(2004) — 바로 붙어 있어도 다른 사람
    assert "남편" in t[33] and "2015" in t[33] and "남편" not in t[34]
    # 큰언니와 공장 "재단하는 언니들"은 다른 사람
    assert "재단하는 언니들" in t[17] and "큰언니" not in t[17]


def test_t07b_five_chapters_is_allowed_six_is_not():
    data, _ = source()
    T = T_of(data)
    o = outline_ok()
    o["chapters"] = [chapter_plan(f"ch-{i}", [para([f"f{min(i, 4)}"])], center=f"중심{i}") for i in range(1, 6)]
    assert pipe.check_outline(o, analysis_ok(), T)[0] == "ready"
    e = edited_ok()
    e["chapters"] = [{"chapter_key": f"ch-{i}", "center": "", "title": sent("장", [], "editorial"),
                      "paragraphs": [[sent("일이다.", ["f1"])]]} for i in range(1, pipe.MAX_CHAPTERS + 1)]
    pipe.check_final(e, analysis_ok(), T)
    e["chapters"].append({**e["chapters"][0], "chapter_key": f"ch-{pipe.MAX_CHAPTERS + 1}"})
    with pytest.raises(pipe.PipelineError) as err:
        pipe.check_final(e, analysis_ok(), T)
    assert err.value.kind == "chapter_limit"


def test_t23_theme_strength_and_direction_consistency():
    a = analysis_ok()
    a["themes"][0].pop("strength")
    r = go(Fake(script(analysis=a)))
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("analysis", "format")
    data, _ = source()
    a = analysis_ok()
    a["themes"][0]["strength"] = "weak"
    a["direction"] = {"theme": "가족", "reason": "", "neutral": True}
    status, w = pipe.check_analysis(a, T_of(data))
    assert status == "ready" and any("neutral=true" in x for x in w)


def _issue(**kw):
    x = {"location": "ch-1/p0/s0", "category": "composition", "severity": "warning", "code": "summary_listing",
         "resolution": "accept_limit", "explanation": "", "source_turns": [], "fix_instruction": ""}
    x.update(kw)
    return x


def test_t28_verify_separates_fact_and_composition_codes():
    r = go(Fake(script(verify=verify_ok("pass", issues=[_issue()]))))
    assert r["pipeline_complete"] is True and r["verification"]["issues"][0]["category"] == "composition"
    for bad in (_issue(code="unsupported_claim"), _issue(category="fact", code="over_split"),
                _issue(category="style"), _issue(resolution="rewrite")):
        r = go(Fake(script(verify=verify_ok("revise", issues=[bad]))))
        assert r["verification"]["state"] == "failed", bad


def test_t42_outline_memo_and_stop_phrase_in_body_block_the_run():
    o = outline_ok()
    o["chapters"][0]["center"] = "가게에서 보낸 긴 세월의 무게"
    e = edited_ok()
    e["chapters"][0]["paragraphs"][0].append(sent("가게에서 보낸 긴 세월의 무게.", [], "editorial"))
    r = go(Fake(script(outline=o, edit=e, verify=verify_ok(reviewed_locations=["artifact"]))))
    assert r["code_gate"] == "blocked" and r["overall"] == "blocked_by_code"
    assert any(f["rule"] == "memo_leak" for f in r["code_findings"])
    e = edited_ok()
    e["chapters"][1]["paragraphs"][0].append(sent("그 얘긴 오늘은 그만할게요.", ["f4"]))
    r = go(Fake(script(edit=e, verify=verify_ok(reviewed_locations=["artifact"]))))
    assert r["model_verdict"] == "pass" and r["overall"] == "blocked_by_code"


def test_t43_invented_scene_in_plan_memo_is_not_caught_by_code():
    """한계 기록 — 문단 계획 role 의 "입학식 날"(원문은 "입학해서")은 사실 id 가 맞으면 코드가 못 잡는다.
    본문으로 옮겨지면 검증 · 사람이 원문과 대조한다. 규칙은 지시문에 있다."""
    data, _ = source()
    o = outline_ok()
    o["chapters"][1]["paragraphs"][0]["role"] = "딸의 초등학교 입학식 날 학교에 데려다준 장면"
    assert pipe.check_outline(o, analysis_ok(), T_of(data))[0] == "ready"
    assert "장면" in pipe.role_text("outline") and "원문에 없는 사건" in pipe.role_text("outline")
    for stage in ("analysis", "chapter", "verify"):
        assert "더 구체적인" in pipe.role_text(stage)


def test_structure_moves_keep_fact_ids_and_source_turns(tmp_path):
    """편집이 문단을 다른 장으로 옮기고 장을 합쳐도 문장의 사실 id 와 원문 턴이 그대로 따라간다.
    모델이 turns 를 직접 써 넣어도 코드가 사실 원장에서 다시 펼친다."""
    moved = edited_ok()
    moved["chapters"] = [{"chapter_key": "ch-1", "center": "딸과 첫 월급", "title": sent("장", [], "editorial"),
                          "paragraphs": [[{**sent("딸의 일이다.", ["f3", "f4"]), "turns": [99]}],
                                         [sent("그보다 전, 첫 월급의 일이다.", ["f1", "f2"])]]}]
    fake = Fake(script(edit=moved, verify=verify_ok(reviewed_locations=["artifact"])))
    r = go(fake, recorder=pipe.Recorder(tmp_path))
    book = pipe.ledger(analysis_ok())
    for p in r["chapters"][0]["paragraphs"]:
        for x in p:
            assert x["turns"] == pipe.fact_turns(x["facts"], book)            # [99] 는 남지 않는다
    assert [x["turns"] for p in r["chapters"][0]["paragraphs"] for x in p] == [[5, 6], [1, 2]]
    trace = json.loads((tmp_path / "04_edit_trace.json").read_text(encoding="utf-8"))
    drafts = {"ch-1/p0/s0": ["f1", "f2"], "ch-2/p0/s0": ["f3", "f4"]}
    finals = {f"ch-1/p{i}/s0": x["facts"] for i, p in enumerate(r["chapters"][0]["paragraphs"]) for x in p}
    for row in trace["sentences"]:
        assert set(finals[row["at"]]) & set(drafts[row["from"]])               # 짝은 같은 사실을 가진 초안 문장
    assert {row["from"] for row in trace["sentences"]} == {"ch-1/p0/s0", "ch-2/p0/s0"}
    assert trace["summary"]["moved"] == 1 and trace["summary"]["final_chapters"] == 1


def test_unresolved_hearsay_or_certainty_never_reaches_awaiting_human():
    data, _ = source_c()
    T = sorted(T_of(data))
    a = {**analysis_ok(), "facts": seed_c_facts(data), "not_in_facts": [],
         "units": [{"id": "m1", "name": "전부", "facts": [f"f{t}" for t in T], "time": "", "weight": "main"}],
         "themes": [], "direction": {"theme": "", "reason": "", "neutral": True}}
    assert a["facts"][9]["source"] == "heard"                             # f10 — 업어 키웠다고 들음
    o = {**outline_ok(), "chapters": [chapter_plan("ch-1", [para([f"f{t}" for t in T])])],
         "book": {**outline_ok()["book"], "closing_facts": ["f39"]}}
    body = [sent("언니가 나를 업어 키웠다.", ["f10"])] + [sent("그 일이 있었다.", [f"f{t}"]) for t in T if t != 10]
    d = {"chapter_key": "ch-1", "title": sent("장", [], "editorial"), "paragraphs": [body], "review_notes": []}
    e = {**edited_ok(), "chapters": [{"chapter_key": "ch-1", "center": "", "title": sent("장", [], "editorial"),
                                      "paragraphs": [body]}]}
    base = Fake({"analysis": a, "outline": o, "ch-1": d, "edit": e, "verify": verify_ok(reviewed_locations=["artifact"])})

    async def kept_all(spec):
        r = await base(spec)
        if spec.stage == "edit":
            checks = json.loads(spec.user.split("\n\n", 1)[1])["checks"]
            out = json.loads(r.text)
            out["checks_resolution"] = [{"check_id": c["id"], "status": "kept", "reason": "그대로가 자연스럽다"}
                                        for c in checks]
            return pipe.Reply(json.dumps(out, ensure_ascii=False), "STOP")
        return r
    r = asyncio.run(pipe.run(data, [{"global_turn": t} for t in T], call=kept_all))
    assert any(f["rule"] == "hearsay_lost" for f in r["code_findings"])
    assert r["code_gate"] == "attention" and r["overall"] == "needs_revision"     # kept 로 넘어가지 않는다


def test_blind_comparison_records_different_input_scope(tmp_path):
    data, _ = source_c()
    ref = pipe.input_ref(data)
    a = {"facts": [fact(f"f{t}", [t]) for t in sorted(T_of(data))]}
    v4dir, v5dir = tmp_path / "v4", tmp_path / "v5"
    v4dir.mkdir()
    v5dir.mkdir()
    v4 = _expanded([_chapter([("가게 일을 적는다.", ["f3"])])], a)[0]
    (v4dir / "result.json").write_text(json.dumps({"mode": "chapter_trial", "run_ref": "a", "input_ref": ref,
                                                   "prompt_version": "v4", "draft": v4}, ensure_ascii=False),
                                       encoding="utf-8")
    (v4dir / "00_input.json").write_text(json.dumps({"given_turns": [2, 3, 4, 11]}), encoding="utf-8")
    v5 = _expanded([_chapter([("발틀과 언니를 함께 적는다.", ["f4", "f26"])])], a)
    (v5dir / "result.json").write_text(json.dumps({**_result("b-focus", v5, "v5", ref), "focus": "소재"},
                                                  ensure_ascii=False), encoding="utf-8")
    steps = [{"stage": s, "given_turns": [4, 26, 27] if s == "chapter" else None} for s in pipe.STAGES]
    (v5dir / "run.json").write_text(json.dumps({"steps": steps}), encoding="utf-8")
    key = blind.make([v4dir / "result.json", v5dir / "result.json"], data, tmp_path / "out", random.Random(0))
    scopes = {k["prompt_version"]: k["scope"] for k in key.values()}
    assert scopes["v4"]["chapter_given_turns"] == [2, 3, 4, 11] and scopes["v4"]["model_stages"] == ["chapter"]
    assert "사람이 짠" in scopes["v4"]["how"] and "모델이 분석" in scopes["v5"]["how"]
    assert scopes["v5"]["chapter_given_turns"] == [4, 26, 27] and scopes["v5"]["cited_turns"] == [4, 26]
    note = (tmp_path / "out" / "검수자용" / "비교조건.md").read_text(encoding="utf-8")
    assert "입력 범위가 다르다" in note and "사람이 짠" in note
    assert not (tmp_path / "out" / "평가용" / "비교조건.md").exists()


# ---------------------------------------------------------------- 분석 안정화 — 정정 · 기억 단위 · keep · 전언 · 주제 (v5 실패 회귀)

FAILED_V5 = ROOT / "tests" / "data" / "v5_focus_analysis_20261026T093440Z.json"


def _diag(a, data):
    return pipe.analysis_diagnostics(a, T_of(data), pipe.turn_marks(data), pipe.source_texts(data), pipe.source_asked(data))


def test_failed_v5_analysis_reports_every_problem_and_stops_before_outline():
    """v5 집중 시험(20261026T093440Z) 분석 출력 그대로 — 문제를 한 번에 모두 모으고, 목차로 넘기지 않는다."""
    data, turn_map = source_c()
    a = json.loads(FAILED_V5.read_text(encoding="utf-8"))
    with pytest.raises(pipe.PipelineError) as e:
        pipe.check_analysis(a, T_of(data), pipe.turn_marks(data), pipe.source_texts(data), pipe.source_asked(data))
    d = " / ".join(e.value.details)
    assert e.value.kind == "reference"
    assert "사실 f30 이 기억 단위 ['m2', 'm4'] 에 함께" in d and "사실 f31 이 기억 단위 ['m2', 'm4'] 에 함께" in d
    assert "사실 ['f51'] 이 어느 기억 단위에도 없다" in d
    assert "사실 f34 의 turns" in d                                    # 정정 기록이 정정 전 사실을 가리킴
    assert "다른 사실 f40 에도 시점" in d                              # 정정 전 f34 와 유효 f40 이 나뉨
    w = " / ".join(e.value.warnings)
    assert "턴 13 에 남에게 들은 이야기 말투" in w                     # 전언 표시 불일치는 경고 (운영 10-30)
    assert "keep 이 사실 58개 중 42개" in w                           # 단순화 뒤 — keep 과다는 경고
    assert "m2(대전 수선집 운영과 삶) 가 1983~2010년" in w           # 여러 시기를 한 단위로
    assert "['그리움']" in w and "['치열']" in w                       # 원문에 없는 감정 · 서사 말
    fake = Fake({"analysis": a})
    r = asyncio.run(pipe.run(data, turn_map, call=fake))
    assert fake.order == ["analysis"] and r["generation_state"] == "failed"
    assert len(r["failure"]["details"]) == len(e.value.details) >= 6


def _seed_c_corrected(data):
    """Seed C 개업 정정을 하나의 유효 사실로 — f25 [21, 25] 1985년 봄, 정정 이력 before 1986년."""
    facts = [f for f in seed_c_facts(data) if f["id"] not in ("f21", "f25")]
    facts += [fact("f21", [21], "은행동 골목에 두 평짜리 가게를 얻음"),
              fact("f25", [21, 25], "가게를 연 때", "1985년 봄", keep=True)]
    a = {**analysis_ok(), "facts": facts, "not_in_facts": [],
         "units": [{"id": f"m{i}", "name": "n", "facts": [f["id"]], "time": "", "weight": "minor"}
                   for i, f in enumerate(facts, 1)],
         "corrections": [{"fact": "f25", "turns": [21, 25], "before": "1986년", "after": "1985년 봄",
                          "note": "개업 연도를 다시 말함"}],
         "themes": [], "direction": {"theme": "", "reason": "", "neutral": True}}
    return a


def test_correction_is_one_valid_fact_and_the_old_value_is_history_only():
    data, _ = source_c()
    a = _seed_c_corrected(data)
    errors, warnings = _diag(a, data)
    assert errors == [] and not any("정정 말투" in w for w in warnings)
    assert "f25" in pipe.must_keep(a)
    nxt = json.loads(pipe.outline_message(data, a).split("\n\n", 1)[1])["analysis"]
    assert nxt["corrections"] == [{"fact": "f25", "turns": [21, 25], "after": "1985년 봄"}]   # before 는 넘기지 않는다

    split = copy.deepcopy(a)                                           # v5 실패 모양 — 정정 전 값을 별개 사실로
    split["facts"].append(fact("f40", [21], "가게를 연 것이 86년", "86년이었을 것", certainty="uncertain", keep=True))
    split["units"].append({"id": "m99", "name": "n", "facts": ["f40"], "time": "", "weight": "minor"})
    errors, _ = _diag(split, data)
    assert any("정정 전 값(1986년)을 별개 사실 f40" in x for x in errors)

    stale = copy.deepcopy(a)
    next(f for f in stale["facts"] if f["id"] == "f25")["time"] = "1986년"
    errors, _ = _diag(stale, data)
    assert any("정정 전 값(1986년)이 남아" in x for x in errors) and any("정정 뒤 값(1985년 봄)이 없다" in x for x in errors)

    for bad, why in (({"before": ""}, "before · after"), ({"after": "1986년"}, "before · after"),
                     ({"turns": [21, 24]}, "정정 전 · 뒤 턴")):
        x = copy.deepcopy(a)
        x["corrections"][0].update(bad)
        errors, _ = _diag(x, data)
        assert any(why in e for e in errors), bad                      # 불명확한 정정은 추측하지 않고 실패


def test_stale_correction_value_in_body_blocks():
    data, _ = source_c()
    a = _seed_c_corrected(data)
    ch = _chapter([("1986년 봄에 은행동에 가게를 열었다.", ["f21", "f25"])])
    f = pipe.correction_findings([ch], a)
    assert [(x["rule"], x["severity"], x["fact"]) for x in f] == [("stale_correction", "block", "f25")]
    ch = _chapter([("1985년 봄에 은행동에 가게를 열었다.", ["f21", "f25"])])
    assert pipe.correction_findings([ch], a) == []
    assert pipe.correction_findings([], a, sent("86년의 가게", [], "editorial"))[0]["location"] == "title"


@pytest.mark.parametrize("share, kind", [(0.6, "warning"), (0.4, "warning"), (0.1, None)])   # 단순화 뒤 경고만
def test_keep_is_for_core_facts_only(share, kind):
    data, _ = source_c()
    a = _seed_c_corrected(data)
    n = len(a["facts"])
    for f in a["facts"]:
        f["keep"] = False
    for f in a["facts"][:int(n * share)]:
        f["keep"] = True
    errors, warnings = _diag(a, data)
    hit = [x for x in errors if x.startswith("keep")], [x for x in warnings if x.startswith("keep")]
    assert (bool(hit[0]), bool(hit[1])) == {"error": (True, False), "warning": (False, True), None: (False, False)}[kind]


def test_turn13_heard_and_remembered_must_be_split_at_fact_level():
    data, _ = source_c()
    a = _seed_c_corrected(data)
    f13 = next(f for f in a["facts"] if f["id"] == "f13")
    f13.update(source="self", text="시집가던 날 버스 정류장에서 많이 울었음")
    _, warnings = _diag(a, data)
    assert any("턴 13 에 남에게 들은 이야기 말투" in x for x in warnings)    # 막지 않고 사람 확인 (운영 10-30)
    f13.update(source="heard", text="시집가던 날 많이 울었다고 들음")   # 들은 부분(heard) + 기억 부분(self)으로 나눔
    a["facts"].append(fact("f40", [13], "버스 정류장이 기억남"))
    a["units"].append({"id": "m99", "name": "n", "facts": ["f40"], "time": "", "weight": "minor"})
    errors, warnings = _diag(a, data)
    assert not any("턴 13 에 남에게 들은" in x for x in errors + warnings)
    f37 = next(f for f in a["facts"] if f["id"] == "f37")                  # 딸이 한 말을 전한 것 — 직접 겪은 일
    f37.update(source="self", text="딸이 이야기를 책으로 남기자고 함")
    assert not any("턴 37 에서 화자가 직접 받은 말" in x for x in _diag(a, data)[0])   # 직접 받은 말 — 전언 아님


def test_unit_spanning_unrelated_periods_and_loaded_theme_words_are_flagged():
    data, _ = source_c()
    a = _seed_c_corrected(data)
    times = {"f19": "1983년쯤", "f2": "2010년", "f22": "", "f23": "", "f24": "", "f3": ""}
    for f in a["facts"]:
        if f["id"] in times:
            f["time"] = times[f["id"]]
    a["units"] = [u for u in a["units"] if u["facts"][0] not in times]
    a["units"].append({"id": "m99", "name": "가게를 한 세월 전체", "facts": list(times), "time": "", "weight": "main"})
    a["themes"] = [{"theme": "재봉틀에 담긴 그리움", "supporting": [38], "counter": [], "strength": "clear"},
                   {"theme": "언니가 준 재봉틀과 함께한 세월", "supporting": [4, 26, 38], "counter": [7], "strength": "clear"}]
    errors, warnings = _diag(a, data)
    assert errors == []
    assert any("m99(가게를 한 세월 전체) 가 1983~2010년" in w for w in warnings)
    assert any("['그리움']" in w for w in warnings) and not any("함께한 세월" in w for w in warnings)


def test_analysis_only_mode_is_one_call_and_writes_the_memory_map(tmp_path):
    data, turn_map = source_c()
    bad = json.loads(FAILED_V5.read_text(encoding="utf-8"))
    fake = Fake({"analysis": bad})
    r = asyncio.run(pipe.run_analysis_only(data, turn_map, call=fake, recorder=pipe.Recorder(tmp_path)))
    assert fake.order == ["analysis"] and r["calls"] == 1 and r["analysis_ok"] is False
    assert len(r["diagnostics"]) >= 7 and r["memory_map"]["keep"] == 42 and r["human_review"] == "not_run"
    text = (tmp_path / "01_memory_map.md").read_text(encoding="utf-8")
    assert "f30 (중복)" in text and "계약 위반" in text and "keep 이 사실 58개 중 42개" in text
    good = _seed_c_corrected(data)
    r = asyncio.run(pipe.run_analysis_only(data, turn_map, call=Fake({"analysis": good}),
                                           recorder=pipe.Recorder(tmp_path / "ok")))
    assert r["analysis_ok"] is True and r["generation_state"] == "analyzed" and r["diagnostics"] == []
    assert r["memory_map"]["corrections"][0]["before"] == "1986년"         # 정정 이력은 분석 기록에 남는다
    run_doc = json.loads((tmp_path / "ok" / "run.json").read_text(encoding="utf-8"))
    assert run_doc["mode"] == "analysis_only" and [s["stage"] for s in run_doc["steps"]] == ["analysis"]


def test_cli_analysis_only_dry_run(capsys):
    args = ["--seed", str(SEED_C_PATH), "--aliases", "c1,c2,c3,c4,c5", "--dry-run"]
    assert cli.main(args + ["--analysis-only"]) == 0
    out = capsys.readouterr().out
    assert "분석만 · 예상 호출 1회" in out and "모델을 부르지 않았다" in out
    assert cli.main(args + ["--analysis-only", "--focus", "소재"]) == 2


def test_analysis_prompt_carries_the_stabilised_rules():
    a = pipe.role_text("analysis")
    assert "정정된 유효 사실은 하나" in a and '"before"' in a and "따로 만들지 마세요" in a and "unclear에 적으세요" in a
    assert "주 기억 단위" in a and "threads로 잇습니다" in a and "개수는 정해져 있지 않습니다" in a
    assert "핵심 사실에만" in a and "대부분의 사실은 false" in a
    assert "한 발언에 섞이면 사실을 나눕니다" in a
    assert "편집적 해석" in a and "희생" in a


# ---------------------------------------------------------------- 정정 정규화 · 전언/직접 들은 말/평가 · 감정 보존

LITE_V5 = ROOT / "tests" / "data" / "v5_analysis_20261027T002005Z.json"


def test_explicit_correction_is_normalized_into_one_valid_fact():
    """Flash-Lite 분석만(20261027T002005Z) 출력 — 정정 이력은 분명하고 사실만 둘로 나뉜 모양을 코드가 정리한다."""
    data, _ = source_c()
    a = json.loads(LITE_V5.read_text(encoding="utf-8"))
    with pytest.raises(pipe.PipelineError) as e:                       # 정정 말고 다른 위반이 남아 실패한다
        pipe.check_analysis(a, T_of(data), pipe.turn_marks(data), pipe.source_texts(data), pipe.source_asked(data))
    assert not any("corrections" in d for d in e.value.details)        # 정정 위반은 사라졌다
    f = {x["id"]: x for x in a["facts"]}
    assert f["f25"]["turns"] == [21, 25] and f["f25"]["time"] == "1985년 봄"   # 유효 사실 하나, 두 발언 출처
    assert f["f21"]["text"] == "은행동 골목 두 평 가게를 얻음" and f["f21"]["time"] == ""   # 정정 대상 아닌 사실은 남김
    assert f["f21"]["certainty"] == "stated"                           # 흐림은 지운 연도에 걸린 것이었다
    assert a["corrections"] == [{"fact": "f25", "turns": [21, 25], "before": "86년", "after": "1985년 봄",
                                 "note": a["corrections"][0]["note"]}]  # 1986 은 이력으로만
    assert a["normalized"][0] == {"correction": 0, "applied": True, "changed": True, "valid_fact": "f25",
                                  "was": "f21", "turns_added": [21], "stripped": "f21", "removed": None}
    assert not any(re.search(r"86\s?년", x["text"] + x["time"]) for x in a["facts"])
    nxt = pipe._analysis_for_next(a)
    assert "86" not in json.dumps(nxt["corrections"]) and "normalized" not in nxt


def test_correction_normalization_is_general_not_seed_specific():
    data, _ = source_b()                                               # seed B — 1998 → 1996 정정
    a = analysis_b()
    a["facts"] = [fact("f1", [1], "1998년에 딸이 초등학교에 입학함", "1998년"), fact("f2", [2, 7], "노란 가방 · 딸은 울지 않음 · 뭉클했음"),
                  fact("f3", [3], "꽃집 첫 손님"), fact("f6", [6], "입학 연도는 1996년", "1996년")]
    a["units"] = [{"id": "m1", "name": "딸 입학", "facts": ["f1", "f2", "f6"], "time": "", "weight": "main"},
                  {"id": "m2", "name": "꽃집", "facts": ["f3"], "time": "", "weight": "main"}]
    a["corrections"] = [{"fact": "f1", "turns": [1, 6], "before": "1998년", "after": "1996년", "note": "입학 연도"}]
    pipe.check_analysis(a, T_of(data), pipe.turn_marks(data), pipe.source_texts(data), pipe.source_asked(data))
    f = {x["id"]: x for x in a["facts"]}
    assert f["f6"]["turns"] == [1, 6] and a["corrections"][0]["fact"] == "f6"
    assert f["f1"]["text"] == "딸이 초등학교에 입학함" and f["f1"]["time"] == ""
    src = (ROOT / "app" / "session" / "memoir_pipeline.py").read_text(encoding="utf-8")
    assert not re.search(r"1985|1986|은행동|f2[15]\b", src)             # Seed C 값을 코드에 두지 않는다


@pytest.mark.parametrize("change, why", [
    (lambda a: a["facts"].append(fact("f40", [25], "다시 1985년 봄이라 함", "1985년 봄")), "정뒤 둘"),
    (lambda a: a["corrections"][0].update(before="", after=""), "이력 없음"),
    (lambda a: a["corrections"][0].update(before="작은 가게", after="큰 가게"), "연도 없는 정정"),
])
def test_unclear_corrections_are_not_guessed(change, why):
    data, _ = source_c()
    a = json.loads(LITE_V5.read_text(encoding="utf-8"))
    change(a)
    if why == "정뒤 둘":
        a["units"][1]["facts"].append("f40")
    with pytest.raises(pipe.PipelineError) as e:
        pipe.check_analysis(a, T_of(data), pipe.turn_marks(data), pipe.source_texts(data), pipe.source_asked(data))
    assert a["normalized"][0]["applied"] is False, why                 # 고치지 않고
    assert any("corrections" in d for d in e.value.details), why       # 실패로 멈춘다


def test_stripped_fact_with_nothing_left_is_removed():
    data, _ = source_c()
    a = _seed_c_corrected(data)
    a["corrections"][0]["fact"] = "f21"
    f25 = next(f for f in a["facts"] if f["id"] == "f25")
    f25["turns"] = [25]
    a["facts"].append(fact("f40", [21], "86년쯤", "86년쯤", certainty="uncertain"))
    a["units"].append({"id": "m99", "name": "n", "facts": ["f40"], "time": "", "weight": "minor"})
    log = pipe.normalize_corrections(a)
    assert log[0]["removed"] == "f40" and all(f["id"] != "f40" for f in a["facts"])
    assert all("f40" not in u["facts"] for u in a["units"]) and f25["turns"] == [21, 25]


def test_turn_marks_separate_heard_reported_view_and_emotions():
    data, _ = source_c()
    m = {x["turn"]: x for x in pipe.turn_marks(data)}
    assert m[13]["heard"] and not m[13]["reported"]                    # 울었대요 — 남에게 들은 지난 일
    assert m[16]["reported"] and not m[16]["heard"]                    # 엄마가 편지로 고맙다고 했어요 — 직접 받은 말
    assert m[32]["view"] and not m[32]["heard"]                        # 닮았다고 제가 그래요 — 화자의 평가
    assert m[38]["emotions"] == ["싫음"] and set(m[31]["emotions"]) == {"좋음 · 기쁨", "아쉬움 · 서운함"}


def test_turn16_32_38_keep_their_meaning():
    data, _ = source_c()
    a = _seed_c_corrected(data)
    f = {x["id"]: x for x in a["facts"]}
    f["f16"].update(text="첫 월급을 집에 부치고 엄마에게 편지를 받음")      # 고마움 · 좋았음 · 힘들었음을 뺌
    f["f32"].update(source="self", text="아들은 말이 없어 큰언니를 닮음")  # 평가를 사실로
    f["f38"].update(text="언니가 준 재봉틀 소리에 언니 생각이 남")         # 지난날 싫었던 소리를 뺌
    errors, warnings = _diag(a, data)
    assert any("턴 16 원문의 감정 말" in x for x in warnings) and not any("턴 16 에 남에게" in x for x in errors)
    assert any("턴 32 은 화자의 평가" in x for x in errors)                         # 출처 오분류 — 실패로 보호
    assert any("턴 38 원문의 감정 말 ['싫음']" in x for x in warnings)             # 메모 뉘앙스 — 경고(원문이 뒤에 간다)
    assert any("턴 16 에서 화자가 직접 받은 말" in x for x in warnings)
    f["f16"].update(text="힘들었지만 첫 월급을 집에 부칠 때 좋았고 엄마가 편지로 고맙다고 함")
    f["f32"].update(source="view", text="말이 없는 아들이 큰언니를 닮았다고 내가 말함")
    f["f38"].update(text="재봉틀을 아직 못 버림 · 지금은 그 소리에 언니 생각이 남")
    a["facts"].append(fact("f40", [38], "공장 다닐 때는 그 소리가 싫었음"))
    a["units"].append({"id": "m99", "name": "n", "facts": ["f40"], "time": "", "weight": "minor"})
    errors, warnings = _diag(a, data)
    assert not any(re.search(r"턴 (16|32|38) ", x) for x in errors + warnings)


def test_opinion_written_as_fact_is_flagged_in_body():
    book = pipe.ledger({"facts": [fact("f32", [32], "아들이 큰언니를 닮았다고 내가 말함", source="view")]})
    f = pipe.voice_findings([_chapter([("아들은 큰언니를 닮았다.", ["f32"])])], book)
    assert [x["rule"] for x in f] == ["opinion_as_fact"]
    assert pipe.voice_findings([_chapter([("아들이 큰언니를 닮았다고 나는 말하곤 한다.", ["f32"])])], book) == []
    assert "opinion_as_fact" not in pipe.KEPT_ACCEPTED


def test_unit_of_unrelated_people_and_times_is_flagged():
    data, _ = source_c()
    a = _seed_c_corrected(data)
    f = {x["id"]: x for x in a["facts"]}
    f["f33"]["time"], f["f30"]["time"] = "2015년", "2008년"
    a["units"] = [u for u in a["units"] if u["facts"][0] not in ("f33", "f30")]
    a["units"].append({"id": "m99", "name": "자녀 결혼과 남편과의 이별", "facts": ["f30", "f33"], "time": "", "weight": "minor"})
    _, warnings = _diag(a, data)
    assert any("m99(자녀 결혼과 남편과의 이별) 의 사실들이 시기로도 끈으로도" in w for w in warnings)
    f["f30"].update(time="", text="빌린 드레스가 커서 가게에서 허리를 줄임")   # 시점이 있는 사실이 하나뿐이면 묶음을 판단하지 않는다
    _, warnings = _diag(a, data)
    assert not any("m99(" in w and "끈으로도" in w for w in warnings)


def test_analysis_prompt_separates_fact_unit_thread_and_paragraph_plan():
    a = pipe.role_text("analysis")
    assert "네 가지를 섞지 마세요" in a and "문단 계획" in a and "목차 단계가 합니다" in a
    assert "사실 수는 턴 수와 같아도, 많아도, 적어도 됩니다" in a
    assert '"view"' in a and "직접 받은 말" in a and "다른 사람의 다른 일을 한 묶음으로 만들지 마세요" in a
    assert "화자가 말한 감정은 메모에서 빼지 마세요" in a
    assert "화자의 생각임이 드러나게" in pipe.role_text("chapter") and "opinion_as_fact" in pipe.role_text("edit")


# ---------------------------------------------------------------- source 계약 · 사실 보존 · 로그 (01:02Z flash-lite 회귀)

LITE_V5B = ROOT / "tests" / "data" / "v5_analysis_20261027T010241Z.json"


def test_reported_is_a_marker_not_a_source_and_is_not_auto_converted(tmp_path):
    data, turn_map = source_c()
    a = json.loads(LITE_V5B.read_text(encoding="utf-8"))
    with pytest.raises(pipe.PipelineError) as e:
        pipe.check_analysis(a, T_of(data), pipe.turn_marks(data), pipe.source_texts(data), pipe.source_asked(data))
    assert e.value.kind == "format" and "f56.source='reported'" in e.value.message
    assert next(f for f in a["facts"] if f["id"] == "f56")["source"] == "reported"   # 바꿔 통과시키지 않는다
    r = asyncio.run(pipe.run_analysis_only(data, turn_map, call=Fake({"analysis": json.loads(LITE_V5B.read_text(encoding="utf-8"))}),
                                           recorder=pipe.Recorder(tmp_path)))
    assert r["analysis_ok"] is False and r["semantic_checks"] == "not_run"
    text = (tmp_path / "01_memory_map.md").read_text(encoding="utf-8")
    assert "뜻 검사 미실행" in text and "검사 미실행 (경고 0건이 아니다)" in text


def test_lite_v5b_meaning_losses_are_all_caught():
    """01:02Z 출력을 source 만 self 로 고친 사본(시험용) — 사실 원장에서 빠진 뜻을 모두 찾는다. 38 은 보존돼 통과."""
    data, _ = source_c()
    a = json.loads(LITE_V5B.read_text(encoding="utf-8"))
    next(f for f in a["facts"] if f["id"] == "f56")["source"] = "self"
    errors, warnings = _diag(a, data)
    assert any("턴 13 에 남에게 들은 이야기 말투" in x for x in warnings)   # 출처 오분류는 사람 확인 경고 (운영 10-30)
    d = " / ".join(warnings)                                            # 메모 뉘앙스는 경고로 모두 남긴다
    for want in ("턴 2 원문의 수 · 기간 표현 ['이십오 년']",           # 운영 기간의 대략 표현
                 "턴 8 원문의 감정 말 ['뿌듯함 · 자부심']",           # 대학 보낸 자부심
                 "턴 16 원문의 감정 말 ['좋음 · 기쁨', '힘듦']",      # 힘들었지만 좋았다
                 "턴 29 원문의 부정 표현",                          # 바다 쪽은 쳐다보지도 않았다
                 "턴 35 에서 화자가 직접 받은 말",                   # 남들은 고물이라고 팔라고
                 "턴 37 원문의 망설임"):                             # 대단한 게 있나 싶은데
        assert want in d, want
    assert "턴 38" not in d                                           # 싫었던 소리 · 언니 생각 · 못 버림 모두 보존
    pipe.check_analysis(a, T_of(data), pipe.turn_marks(data), pipe.source_texts(data), pipe.source_asked(data))   # 막지 않는다 · normalized 를 단다
    assert a["normalized"][0]["changed"] is False and a["normalized"][0]["applied"] is False
    assert not any("정정 정규화" in w for w in warnings)               # 바꾼 것이 없으면 정규화로 적지 않는다
    assert any("m6(자녀들의 결혼과 가족의 소식)" in w for w in warnings)   # 무관한 묶음은 경고로 유지


def test_turn_marks_for_negation_doubt_numbers_and_pride():
    data, _ = source_c()
    m = {x["turn"]: x for x in pipe.turn_marks(data)}
    assert m[10]["negation"] and m[29]["negation"] and m[27]["negation"]      # 기억은 안 나요 · 쳐다보지도 않았어요 · 별말 없었어요
    assert 39 not in m                                                       # "없어요." 는 질문에 대한 답 — 사실의 부정 아님
    assert m[37]["doubt"] and m[2]["numbers"] == ["이십오 년", "2010"]
    assert m[28]["numbers"] == []                                            # 두 번(횟수)은 수 보존 대상이 아니다
    assert "뿌듯함 · 자부심" in m[8]["emotions"]                              # 내가 했다 싶어요


@pytest.mark.parametrize("num, n", [("이십오", 25), ("육", 6), ("십", 10), ("열일곱", 17), ("네", 4), ("스무", 20), ("곰", None)])
def test_korean_numbers_match_digits(num, n):
    assert pipe._korean_number(num) == n


def test_approximate_duration_can_be_written_in_digits():
    assert pipe._num_supported("육|년", "약6년", {"6"}) and pipe._num_supported("이십오|년", "25년쯤", {"25"})
    assert not pipe._num_supported("이십오|년", "오래함", set())


def test_analysis_prompt_states_three_sources_and_meaning_preservation():
    a = pipe.role_text("analysis")
    assert '"self" · "heard" · "view" 세 값뿐' in a and "turn_marks의 이름(reported 등)을 source에 쓰지 마세요" in a
    assert "참고 표시" in a and "원문의 뜻을 메모에서 잃지 마세요" in a
    for k in ("수 · 기간 · 나이", "부정 표현", "남이 화자에게 한 말", "망설임", "자부심"):
        assert k in a, k


# ---------------------------------------------------------------- 분석 계약 단순화 · 시험용 분석 스냅샷 · 후속 단계 시험

FIXTURE_C = ROOT / "eval" / "analysis_fixture_C_v5_reviewed.json"


def test_simplified_contract_keeps_protected_items_as_errors():
    data, _ = source_c()
    base = _seed_c_corrected(data)
    cases = {
        "view 오분류": lambda a: next(f for f in a["facts"] if f["id"] == "f32").update(source="self"),
        "근거 턴 불일치": lambda a: next(f for f in a["facts"] if f["id"] == "f3").update(turns=[29]),
        "없는 턴": lambda a: next(f for f in a["facts"] if f["id"] == "f3").update(turns=[99]),
    }
    for why, change in cases.items():
        a = copy.deepcopy(base)
        change(a)
        with pytest.raises(pipe.PipelineError):
            pipe.check_analysis(a, T_of(data), pipe.turn_marks(data), pipe.source_texts(data), pipe.source_asked(data))
    a = copy.deepcopy(base)                                            # 메모 뉘앙스만 빠지면 경고
    next(f for f in a["facts"] if f["id"] == "f29").update(text="2003년에 언니가 아파 병원에 감")
    errors, warnings = _diag(a, data)
    assert errors == [] and any("턴 29 원문의 부정 표현" in w for w in warnings)


def test_body_fact_checks_are_not_relaxed():
    """분석 메모 검사만 경고로 내렸다 — 본문의 들은 말 · 흐림 · 평가 · 숫자 검사는 그대로 fix/block."""
    book = pipe.ledger({"facts": [fact("f10", [10], "업어 키웠다고 들음", source="heard"),
                                  fact("f23", [23], "천 원 받았던 것 같음", certainty="uncertain")]})
    rules = {x["rule"] for x in pipe.voice_findings([_chapter([("언니가 나를 업어 키웠다.", ["f10"]),
                                                               ("천 원을 받았다.", ["f23"])])], book)}
    assert rules == {"hearsay_lost", "certainty_lost"}
    assert "hearsay_lost" not in pipe.KEPT_ACCEPTED and "certainty_lost" not in pipe.KEPT_ACCEPTED


def test_reviewed_fixture_is_valid_marked_and_reproducible():
    import importlib.util
    data, turn_map = source_c()
    fx = json.loads(FIXTURE_C.read_text(encoding="utf-8"))
    assert fx["analysis_source"] == "reviewed_fixture" and fx["synthetic"] is True and "원본이 아니다" in fx["note"]
    assert fx["input_ref"] == "b9f8e2daea65" and fx["based_on"]["run_ref"] == "20261027T010241Z-C5-b9f8-analysis"
    a = pipe.load_analysis_fixture(fx, data, pipe.check_input(data, turn_map))
    f = {x["id"]: x for x in a["facts"]}
    assert f["f34"]["turns"] == [21, 25] and f["f34"]["time"] == "1985년 봄"              # 개업 정정
    assert not any(re.search(r"86\s?년", x["text"] + x["time"]) for x in a["facts"])     # 1986 은 이력에만
    assert a["corrections"][0]["before"] == "1986년"
    assert f["f21"]["source"] == "heard" and f["f61"]["turns"] == [13] and f["f61"]["source"] == "self"   # 턴 13
    for fid in ("f62", "f63", "f64", "f65", "f66"):                    # 덧붙인 사실은 모두 그 턴 원문의 말
        assert fid in f and set(f[fid]["turns"]) <= T_of(data)
    for e in fx["edits"]:
        assert e["reason"] and e["turns"] and "after" in e and "before" in e   # 고친 것을 모두 기록
    spec = importlib.util.spec_from_file_location("bf", ROOT / "eval" / "build_analysis_fixture_C_v5.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.build() == fx                                            # 만드는 스크립트로 같은 결과가 나온다
    base = (ROOT / fx["based_on"]["file"]).read_bytes()
    import hashlib
    assert hashlib.sha256(base).hexdigest()[:16] == fx["based_on"]["sha256"]       # 바탕은 모델 원본 그대로


@pytest.mark.parametrize("change, why", [
    (lambda fx: fx.update(input_ref="000000000000"), "input_ref"),
    (lambda fx: fx.update(analysis_source="model"), "analysis_source"),
    (lambda fx: fx.update(edits=[]), "edits"),
    (lambda fx: fx.pop("based_on"), "based_on"),
    (lambda fx: next(f for f in fx["analysis"]["facts"] if f["id"] == "f21").update(turns=[99]), "계약 위반"),
])
def test_fixture_is_refused_when_unmarked_or_invalid(change, why):
    data, turn_map = source_c()
    fx = json.loads(FIXTURE_C.read_text(encoding="utf-8"))
    change(fx)
    with pytest.raises(pipe.PipelineError, match=why):
        pipe.load_analysis_fixture(fx, data, pipe.check_input(data, turn_map))
    raw = json.loads(LITE_V5B.read_text(encoding="utf-8"))           # 모델 원본을 그대로 스냅샷으로 쓸 수 없다
    with pytest.raises(pipe.PipelineError, match="analysis_snapshot"):
        pipe.load_analysis_fixture(raw, data, pipe.check_input(data, turn_map))


def test_follow_on_run_starts_at_outline_and_marks_the_source(tmp_path):
    data, turn_map = source_c()
    fx = json.loads(FIXTURE_C.read_text(encoding="utf-8"))
    ids = [f["id"] for f in fx["analysis"]["facts"]]
    use = ["f17", "f22", "f23", "f40", "f41", "f6", "f44", "f52", "f54", "f57", "f58", "f59", "f60"]
    o = {**outline_ok(), "book": {**outline_ok()["book"], "closing_facts": ["f60"]},
         "chapters": [chapter_plan("ch-1", [para(use)], "큰언니와 재봉틀", ["m1", "m3", "m7"])],
         "omit": [{"facts": [i for i in ids if i not in use], "reason": "이번 장의 중심 밖"}]}
    body = [sent("열 살쯤 큰언니에게 바느질을 배웠다.", ["f17"])]
    d = {"chapter_key": "ch-1", "title": sent("언니의 발틀", [], "editorial"), "paragraphs": [body], "review_notes": []}
    e = {**edited_ok(), "chapters": [{"chapter_key": "ch-1", "center": "", "title": sent("언니의 발틀", [], "editorial"),
                                      "paragraphs": [body]}],
         "omitted": [{"facts": [i for i in ids if i != "f17"], "reason": "시험"}]}
    fake = Fake({"outline": o, "ch-1": d, "edit": e, "verify": verify_ok(reviewed_locations=["artifact"])})
    r = asyncio.run(pipe.run(data, turn_map, call=fake, recorder=pipe.Recorder(tmp_path), focus="큰언니와 재봉틀",
                             analysis_fixture=fx))
    assert fake.order == ["outline", "ch-1", "edit", "verify"] and r["calls"] == 4    # 분석을 부르지 않는다
    assert r["analysis_source"] == "reviewed_fixture" and r["pipeline_complete"] is True
    assert (tmp_path / "01_analysis_fixture.json").exists() and not (tmp_path / "01_analysis.json").exists()
    run_doc = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert run_doc["analysis_source"] == "reviewed_fixture" and [s["stage"] for s in run_doc["steps"]][0] == "outline"
    assert "reviewed_fixture" in (tmp_path / "r1_summary.md").read_text(encoding="utf-8")
    out = fake.payload("outline")["analysis"]
    assert "before" not in json.dumps(out["corrections"]) and len(out["facts"]) == len(ids)
    r = asyncio.run(pipe.run(data, turn_map, call=Fake(script())))      # 스냅샷 없이 돌리면 출처는 model
    assert r["analysis_source"] == "model"


def test_cli_from_analysis_dry_run_and_refusals(capsys, tmp_path):
    args = ["--seed", str(SEED_C_PATH), "--aliases", "c1,c2,c3,c4,c5", "--dry-run"]
    assert cli.main(args + ["--from-analysis", str(FIXTURE_C), "--focus", "큰언니와 재봉틀"]) == 0
    out = capsys.readouterr().out
    assert "analysis_source=reviewed_fixture" in out and "분석 호출 없음" in out and "예상 호출 4회" in out
    assert cli.main(args + ["--from-analysis", str(FIXTURE_C), "--analysis-only"]) == 2
    bad = tmp_path / "raw.json"
    bad.write_text(LITE_V5B.read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(args + ["--from-analysis", str(bad)]) == 2


# ---------------------------------------------------------------- 출처 대응 — 질문(asked)은 근거가 아니다


def _turn24_data(elder):
    data, _ = source_c()
    data = copy.deepcopy(data)
    u = next(x for x in data["utterances"] if x["turn"] == 24)
    u.update(asked="첫 천 원을 지갑에 넣고 다니셨어요?", elder=elder)
    return data


@pytest.mark.parametrize("elder, why", [
    ("네.", "짧은 답뿐"),                       # 질문에 '네'만 — 질문 내용을 사실로 세울 수 없다
    ("그럼요, 한참이요.", "질문에만 있는 내용"),  # 질문 글을 메모로 옮김 — 화자 발언과 맞지 않는다
])
def test_content_only_in_the_question_is_not_a_fact(elder, why):
    data = _turn24_data(elder)
    a = _seed_c_corrected(source_c()[0])
    next(f for f in a["facts"] if f["id"] == "f24").update(text="첫 천 원을 지갑에 넣고 다님")
    errors, _ = pipe.analysis_diagnostics(a, T_of(data), pipe.turn_marks(data), pipe.source_texts(data),
                                          pipe.source_asked(data))
    assert any("f24" in e and why in e for e in errors), errors


def test_question_may_supply_the_referent_but_the_answer_must_carry_the_fact():
    """턴 18 — 질문 '서울에서는 얼마나 계셨어요?' · 답 '한 육 년?' → '서울에서 약 6년 살았음' 은 답의 수가 근거라 통과."""
    data, _ = source_c()
    a = _seed_c_corrected(data)
    next(f for f in a["facts"] if f["id"] == "f18").update(text="서울에서 약 6년 살았음", certainty="approx")
    errors, _ = _diag(a, data)
    assert not any("f18" in e for e in errors)
    next(f for f in a["facts"] if f["id"] == "f18").update(text="서울에서 오래 지냈음")   # 답의 수도 글도 없음
    errors, _ = _diag(a, data)
    assert any("f18" in e and "발언과 맞지 않는다" in e for e in errors)


def test_character_overlap_does_not_prove_meaning():
    """한계 기록 — 글자가 닮아도 뜻이 뒤집힐 수 있다('안 왔어요' → '왔음'). 대응 검사는 통과하고, 부정 누락 경고 ·
    검증 단계 · 사람 대조가 뜻을 본다. 대응 검사를 뜻 검증으로 쓰지 않는다."""
    data, _ = source_c()
    a = _seed_c_corrected(data)
    next(f for f in a["facts"] if f["id"] == "f23").update(text="첫날은 손님이 많이 왔고 사흘째에 할머니 한 분이 바지 단 줄여 달라고 옴")
    errors, warnings = _diag(a, data)
    assert not any("f23" in e for e in errors)
    assert any("턴 23 원문의 부정 표현" in w for w in warnings)
    assert "뜻의 대조는 검증 단계와 사람이 한다" in (ROOT / "app" / "session" / "memoir_pipeline.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 후속 4단계 실패(01:44Z) 원인별 회귀 · 사람 검토 목차 · 집필 시험

FOLLOWON = ROOT / "tests" / "data" / "v5_followon_20261027T014432Z.json"
OUTLINE_C = ROOT / "eval" / "outline_fixture_C_v5_reviewed.json"


def _fixture_analysis():
    data, turn_map = source_c()
    fx = json.loads(FIXTURE_C.read_text(encoding="utf-8"))
    return data, turn_map, fx, pipe.load_analysis_fixture(fx, data, pipe.check_input(data, turn_map))


def test_failed_followon_outline_is_flagged_for_mixing_and_bulk_omission():
    """01:44Z 목차 그대로 — 셋째 문단에 딸(m6) · 남편(m9)이 섞이고, 장의 단위 m1 · m3 를 거의 다 뺐다."""
    data, turn_map, _, a = _fixture_analysis()
    o = json.loads(FOLLOWON.read_text(encoding="utf-8"))["outline"]
    _, w = pipe.check_outline(o, a, pipe.check_input(data, turn_map), "큰언니와 재봉틀")
    assert any("ch-1/p2 에 다른 기억 단위와 끈으로 이어지지 않는 단위 ['m6', 'm9']" in x for x in w)
    assert any("m1 의 사실 9개 중 8개를 뺐다" in x for x in w) and any("m3 의 사실 15개 중 13개를 뺐다" in x for x in w)


def test_edit_that_claims_changes_but_changed_nothing_is_flagged():
    f = json.loads(FOLLOWON.read_text(encoding="utf-8"))
    found = pipe.edit_claim_findings(f["edited"], f["edit_trace"])
    assert [(x["rule"], x["severity"]) for x in found] == [("edit_claim_mismatch", "fix")]
    assert "edit_claim_mismatch" not in pipe.KEPT_ACCEPTED
    quiet = {**f["edited"], "diagnosis": [{"issue": "고칠 곳 없음", "where": [], "action": ""}]}
    assert pipe.edit_claim_findings(quiet, f["edit_trace"]) == []          # 조치를 적지 않았으면 문제 아님
    changed = {**f["edit_trace"], "summary": {**f["edit_trace"]["summary"], "structure_changed": True}}
    assert pipe.edit_claim_findings(f["edited"], changed) == []          # 실제로 바뀌었으면 문제 아님


def test_undecided_wording_counts_as_hedge():
    """01:44Z f60 '아직 모르겠고 … 싶다' 에 certainty_lost 가 난 오탐."""
    book = pipe.ledger({"facts": [fact("f60", [39], "줄지는 아직 모름", certainty="uncertain")]})
    assert pipe.voice_findings([_chapter([("애들한테 그 재봉틀을 줄지는 아직 모르겠고 걔들이 쓸 일이 있겠나 싶다.", ["f60"])])],
                               book) == []


def test_result_json_records_sources(tmp_path):
    data, turn_map, fx, _ = _fixture_analysis()
    o = json.loads(OUTLINE_C.read_text(encoding="utf-8"))
    plan = [f for p in o["outline"]["chapters"][0]["paragraphs"] for f in p["facts"]]
    d = {"chapter_key": "ch-1", "title": sent("언니의 발틀", [], "editorial"),
         "paragraphs": [[sent("언니가 준 재봉틀을 아직 못 버렸다.", ["f57"])]], "review_notes": []}
    e = {**edited_ok(), "chapters": [{"chapter_key": "ch-1", "center": "", "title": sent("언니의 발틀", [], "editorial"),
                                      "paragraphs": d["paragraphs"]}],
         "diagnosis": [{"issue": "없음", "where": [], "action": ""}]}
    fake = Fake({"ch-1": d, "edit": e, "verify": verify_ok(reviewed_locations=["artifact"])})
    r = asyncio.run(pipe.run(data, turn_map, call=fake, recorder=pipe.Recorder(tmp_path), analysis_fixture=fx,
                             outline_fixture=o))
    saved = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert saved["analysis_source"] == "reviewed_fixture" and saved["outline_source"] == "reviewed_fixture"
    assert fake.order == ["ch-1", "edit", "verify"] and r["calls"] == 3       # 분석 · 목차를 부르지 않는다
    assert r["focus"] == "큰언니와 재봉틀" and len(plan) > 0
    assert (tmp_path / "02_outline_fixture.json").exists() and not (tmp_path / "02_outline.json").exists()
    run_doc = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert run_doc["outline_source"] == "reviewed_fixture" and [s["stage"] for s in run_doc["steps"]] == ["chapter", "edit", "verify"]
    assert "사람이 검토한 시험용 목차" in (tmp_path / "r1_summary.md").read_text(encoding="utf-8")
    asyncio.run(pipe.run(data, turn_map, call=Fake(script()), recorder=pipe.Recorder(tmp_path / "m")))
    assert json.loads((tmp_path / "m" / "result.json").read_text(encoding="utf-8"))["analysis_source"] == "model"


def test_reviewed_outline_covers_the_required_memories_and_is_reproducible():
    import importlib.util
    data, turn_map, fx, a = _fixture_analysis()
    o = json.loads(OUTLINE_C.read_text(encoding="utf-8"))
    assert o["outline_source"] == "reviewed_fixture" and o["synthetic"] is True and "자동 목차 생성 결과가 아니다" in o["note"]
    outline, focus = pipe.load_outline_fixture(o, a, fx, pipe.check_input(data, turn_map))
    assert focus == "큰언니와 재봉틀" and len(o["memories"]) == 7
    used = {f for p in outline["chapters"][0]["paragraphs"] for f in p["facts"] + p["brief"]}
    for m in o["memories"]:
        assert set(m["facts"]) <= used, m["name"]
    book = pipe.ledger(a)
    for f in used:                                                         # 다른 인물의 무관한 일은 없다
        assert f in book and not set(book[f]["turns"]) & {5, 7, 8, 30, 31, 32, 33, 37}, f
    memos = [p["role"] for p in outline["chapters"][0]["paragraphs"]]
    assert not any(m.strip().endswith("다.") for m in memos)               # 완성된 본문 문장 없음
    spec = importlib.util.spec_from_file_location("bo", ROOT / "eval" / "build_outline_fixture_C_v5.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert _without_core_warnings(mod.build()) == _without_core_warnings(o)


CORE_WARN = "핵심 경위(core)가 지정되지 않았다"


def _without_core_warnings(o):
    """v7 의 core 미지정 경고는 시험용 목차를 만든 뒤에 생겼다 — 저장된 목차 스냅샷의 check 기록은 그대로 둔다."""
    o = json.loads(json.dumps(o))
    o["check"]["warnings"] = [w for w in o["check"]["warnings"] if CORE_WARN not in w]
    return o


@pytest.mark.parametrize("change, why", [
    (lambda o: o["analysis_fixture"].update(sha256="0" * 16), "sha256"),
    (lambda o: o.update(outline_source="model"), "outline_source"),
    (lambda o: o["outline"]["chapters"][0]["paragraphs"][0].update(role="언니가 준 재봉틀을 나는 아직 버리지 못했다."), "완성된 본문"),
    (lambda o: o["memories"].append({"name": "없는 기억", "facts": ["f99"]}), "원장에 없거나"),
    (lambda o: (o["outline"]["chapters"][0]["paragraphs"][6]["facts"].append("f51"),
                o["outline"]["omit"].__setitem__(slice(None), [x if "f51" not in x["facts"] else
                                                                {**x, "facts": [f for f in x["facts"] if f != "f51"]}
                                                                for x in o["outline"]["omit"] if x["facts"] != ["f51"]])),
     "섞였다"),
])
def test_reviewed_outline_is_refused_when_unmarked_or_unsafe(change, why):
    data, turn_map, fx, a = _fixture_analysis()
    o = json.loads(OUTLINE_C.read_text(encoding="utf-8"))
    change(o)
    with pytest.raises(pipe.PipelineError, match=why):
        pipe.load_outline_fixture(o, a, fx, pipe.check_input(data, turn_map))


def test_cli_from_outline_dry_run_and_refusals(capsys):
    args = ["--seed", str(SEED_C_PATH), "--aliases", "c1,c2,c3,c4,c5", "--dry-run"]
    assert cli.main(args + ["--from-analysis", str(FIXTURE_C), "--from-outline", str(OUTLINE_C)]) == 0
    out = capsys.readouterr().out
    assert "outline_source=reviewed_fixture" in out and "목차 호출 없음" in out and "예상 호출 3회" in out
    assert "focus「큰언니와 재봉틀」" in out
    assert cli.main(args + ["--from-outline", str(OUTLINE_C)]) == 2                     # 분석 스냅샷 없이 못 쓴다
    assert cli.main(args + ["--from-analysis", str(FIXTURE_C), "--from-outline", str(OUTLINE_C),
                            "--focus", "다른 소재"]) == 2


# ---------------------------------------------------------------- 집필 시험(02:06Z) 회귀 — 핵심 사실 누락 · 검증 위치 · 장 집필 비교

WRITING = ROOT / "tests" / "data" / "v5_writing_20261027T020620Z.json"
OUTLINE_C2 = ROOT / "eval" / "outline_fixture_C_v5_reviewed_r2.json"
# 02:06Z 에서 빠진 기억 — 바느질을 배운 일 · 공장의 미싱 소리 · 재봉틀 도착과 편지 · 병문안 · 집으로 가져온 재봉틀
LOST = {"f17", "f23", "f40", "f41", "f44", "f54"}


def _r2():
    data, turn_map, fx, a = _fixture_analysis()
    o = json.loads(OUTLINE_C2.read_text(encoding="utf-8"))
    outline, _ = pipe.load_outline_fixture(o, a, fx, pipe.check_input(data, turn_map))
    omit = {f: x["reason"] for x in outline["omit"] for f in x["facts"]}
    return data, a, outline, omit, json.loads(WRITING.read_text(encoding="utf-8"))


def test_draft_missing_core_memories_are_caught():
    data, a, outline, omit, w = _r2()
    found = pipe.all_findings([w["draft"]], outline, data, a, omit)
    core = [f for f in found if f["rule"] == "core_missing"]
    assert {f["fact"] for f in core} == LOST | {"f59"} and all(f["severity"] == "fix" for f in core)
    assert {f["plan"] for f in core if f["fact"] in ("f40", "f41")} == {"ch-1/p3"}
    cov = pipe.plan_coverage([w["draft"]], outline)
    assert (cov["planned"], cov["planned_used"], cov["core"], cov["core_used"]) == (30, 12, 18, 11)


def test_supporting_facts_may_be_left_out():
    """f18 · f19 · f61 · f16 · f26 · f33 · f64 · f62 · f53 · f65 · f55 는 보조 — 빠져도 판정하지 않는다."""
    data, a, outline, omit, w = _r2()
    core = set(pipe.plan_core(outline))
    flagged = {f.get("fact") for f in pipe.all_findings([w["draft"]], outline, data, a, omit)
               if f["rule"] in ("core_missing", "must_keep_missing")}
    assert flagged <= core and not flagged & {"f18", "f19", "f61", "f16", "f26", "f33", "f64", "f62", "f53", "f65", "f55"}


def test_core_still_missing_after_edit_means_needs_revision():
    data, a, outline, omit, w = _r2()
    eo = {f: x["reason"] for x in w["edited"]["omitted"] for f in x["facts"]}
    final = pipe.all_findings(w["edited"]["chapters"], outline, data, a, {**omit, **eo}, final=True, edit_omitted=eo)
    assert {f["fact"] for f in final if f["rule"] == "core_missing"} == LOST          # f59 는 편집이 살렸다
    gate = pipe.code_gate(final, {}, [])
    assert gate["state"] == "attention"
    verification = {"state": "completed", "verdict": "pass"}
    assert pipe.overall_state(pipe.GENERATED, gate, verification, "not_run", {"meets_bar": True}) == "needs_revision"
    kept = {f"core_missing:artifact:{f}": {"status": "kept", "reason": "그냥"} for f in LOST}
    assert pipe.code_gate(final, kept, final)["state"] == "attention"                 # kept 로 넘기지 못한다


def test_core_omitted_with_reason_by_edit_stays_fix_not_outline_omit():
    data, a, outline, omit, w = _r2()
    eo = {"f44": "병문안 대목은 화자가 다음 장에서 다루기를 원했다(사람 확인)"}
    final = pipe.all_findings(w["edited"]["chapters"], outline, data, a, omit, final=True, edit_omitted=eo)
    by = {f["fact"]: f for f in final if f["rule"].startswith("core_")}
    assert by["f44"]["rule"] == "core_omitted" and by["f44"]["severity"] == "fix"        # v7 — 이유가 있어도 미해결
    assert by["f17"]["rule"] == "core_missing"
    # 편집의 생략 목록이 아닌 곳의 이유로는 정당한 생략이 되지 않는다
    final = pipe.all_findings(w["edited"]["chapters"], outline, data, a, {**omit, "f44": "목차 이유"}, final=True)
    assert next(f for f in final if f.get("fact") == "f44")["rule"] == "core_missing"


def test_edit_receives_missing_core_with_source_and_certainty():
    data, a, outline, omit, w = _r2()
    checks = pipe.all_findings([w["draft"]], outline, data, a, omit)
    msg = pipe.edit_message(data, a, outline, [w["draft"]], checks, [], "큰언니와 재봉틀")
    payload = json.loads(msg.split("\n\n", 1)[1])
    rows = {x["fact"]: x for x in payload["missing_core"]}
    assert set(rows) == LOST | {"f59"}
    assert rows["f17"]["certainty"] == "approx" and rows["f17"]["turns"] == [11]
    assert rows["f40"]["role"].startswith("가게를 연 뒤") and rows["f41"]["check_id"] == "core_missing:artifact:f41"
    assert "missing_core 는 장 초안이 빠뜨린" in msg and "들은 이야기 · 흐린 기억 · 감정을 그대로" in msg
    plain = pipe.edit_message(data, a, outline, [w["draft"]], [], [], "큰언니와 재봉틀")
    assert "missing_core" not in plain


def test_outline_without_core_keeps_old_behaviour():
    data, a, _, _, w = _r2()
    o1 = json.loads(OUTLINE_C.read_text(encoding="utf-8"))["outline"]
    assert pipe.plan_core(o1) == {}
    assert not [f for f in pipe.all_findings([w["draft"]], o1, data, a, {}) if f["rule"].startswith("core_")]
    assert "core 는" not in pipe.chapter_message({}, a, o1, o1["chapters"][0])


@pytest.mark.parametrize("change, why", [
    (lambda o: o["outline"]["chapters"][0]["paragraphs"][1]["core"].append("f16"), "핵심 사실은 그 문단 facts 안에서만"),
    (lambda o: o["outline"]["chapters"][0]["paragraphs"][1]["core"].append("f99"), "f99"),
    (lambda o: o["outline"]["chapters"][0]["paragraphs"][4].update(core=[]), r"핵심 사실\(core\)이 없다"),
])
def test_core_marks_are_checked(change, why):
    data, turn_map, fx, a = _fixture_analysis()
    o = json.loads(OUTLINE_C2.read_text(encoding="utf-8"))
    change(o)
    with pytest.raises(pipe.PipelineError, match=why):
        pipe.load_outline_fixture(o, a, fx, pipe.check_input(data, turn_map))


def test_r2_outline_only_adds_core_marks():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bo2", ROOT / "eval" / "build_outline_fixture_C_v5.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r1 = json.loads(OUTLINE_C.read_text(encoding="utf-8"))
    r2 = json.loads(OUTLINE_C2.read_text(encoding="utf-8"))
    assert _without_core_warnings(mod.build()) == _without_core_warnings(r1)
    assert _without_core_warnings(mod.build(core=True)) == _without_core_warnings(r2)
    strip = [{k: v for k, v in p.items() if k != "core"} for p in r2["outline"]["chapters"][0]["paragraphs"]]
    assert strip == r1["outline"]["chapters"][0]["paragraphs"]
    assert r2["analysis_fixture"] == r1["analysis_fixture"] and r2["memories"] == r1["memories"]


def test_verify_location_aliases_are_normalized_only_when_real():
    _, _, _, _, w = _r2()
    T = set(range(1, 40))
    locs = pipe.locations(w["edited"])
    v = json.loads(json.dumps(w["verify"]))
    warnings = pipe.check_verify(v, T, locs)                       # 02:06Z 에는 reference 실패였다
    assert any("같은 뜻의 계약 표기로 바꿨다" in x for x in warnings)
    assert "ch-1/p5" in v["reviewed_locations"] and not any("paragraphs" in x for x in v["reviewed_locations"])
    assert next(q for q in v["quality"] if q["item"] == "Q4")["locations"] == []   # ch-1/omitted 는 근거가 아니다
    bad = json.loads(json.dumps(w["verify"]))
    bad["reviewed_locations"].append("ch-1/paragraphs/9")         # 편집본에 없는 문단 — 바꾸지 않고 막는다
    with pytest.raises(pipe.PipelineError, match="paragraphs/9"):
        pipe.check_verify(bad, T, locs)
    assert pipe.normalize_location("ch-1/paragraphs/0/sentences/1", locs) == "ch-1/p0/s1"
    assert pipe.normalize_location("ch-1/paragraphs/0/1", locs) == "ch-1/p0/s1"
    assert pipe.normalize_location("ch-1/paragraphs/0/9", locs) == "ch-1/paragraphs/0/9"
    assert pipe.normalize_location("ch-2/paragraphs/0", locs) == "ch-2/paragraphs/0"
    assert pipe.normalize_location("ch-1/omitted", locs) == "ch-1/omitted"


def test_chapter_only_run_calls_once_with_override_model(tmp_path):
    data, turn_map, fx, _ = _fixture_analysis()
    o = json.loads(OUTLINE_C2.read_text(encoding="utf-8"))
    w = json.loads(WRITING.read_text(encoding="utf-8"))
    fake = Fake({"ch-1": w["draft"]})
    r = asyncio.run(pipe.run(data, turn_map, call=fake, recorder=pipe.Recorder(tmp_path), analysis_fixture=fx,
                             outline_fixture=o, chapter_only=True, model="gemini-3.1-pro-preview"))
    assert fake.order == ["ch-1"] and r["calls"] == 1
    spec = fake.specs[0]
    assert spec.model == "gemini-3.1-pro-preview" and spec.max_output_tokens == pipe.CHAPTER_ONLY_LIMITS[1]
    assert "core 는 그 문단이 꼭 담아야 할 핵심 사실" in spec.user
    assert r["generation_state"] == pipe.DRAFT_ONLY and r["overall"] == "draft_only" and r["human_review"] == "not_run"
    assert r["code_gate"] == "attention"
    assert r["metrics"]["plan_coverage"]["draft"]["core_missing"] == sorted(LOST | {"f59"}, key=lambda f: int(f[1:]))
    assert len(r["chapters"]) == 1 and r["edit_trace"] is None
    assert not (tmp_path / "04_edited.json").exists() and not (tmp_path / "05_verify.json").exists()
    run_doc = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert run_doc["settings"]["MEMOIR_PIPE_TEXT_MODEL"] == "gemini-3.1-pro-preview" and run_doc["settings"]["chapter_only"]
    assert "장 집필 비교(chapter_only)" in (tmp_path / "r1_summary.md").read_text(encoding="utf-8")
    assert pipe.settings()["MEMOIR_PIPE_TEXT_MODEL"] == "gemini-3.5-flash-lite"      # 기본 모델은 그대로


def test_chapter_only_needs_both_snapshots(tmp_path):
    data, turn_map, fx, _ = _fixture_analysis()
    fake = Fake({})
    r = asyncio.run(pipe.run(data, turn_map, call=fake, recorder=pipe.Recorder(tmp_path), analysis_fixture=fx,
                             chapter_only=True))
    assert fake.order == [] and r["generation_state"] == pipe.FAILED and "목차 스냅샷" in r["failure"]["message"]


def test_cli_chapter_only_dry_run_and_refusals(capsys):
    args = ["--seed", str(SEED_C_PATH), "--aliases", "c1,c2,c3,c4,c5", "--dry-run"]
    fx = ["--from-analysis", str(FIXTURE_C), "--from-outline", str(OUTLINE_C2)]
    assert cli.main(args + fx + ["--chapter-only", "--model", "gemini-3.1-pro-preview"]) == 0
    out = capsys.readouterr().out
    assert "예상 호출 1회" in out and "기본 gemini-3.5-flash-lite 그대로" in out and "핵심 사실 18" in out
    assert "예상 비용 gemini-3.1-pro-preview" in out and "출력 상한 32,768" in out
    assert cli.main(args + fx + ["--model", "gemini-3.1-pro-preview"]) == 2           # 비교 시험 밖에서는 안 된다
    assert cli.main(args + ["--from-analysis", str(FIXTURE_C), "--chapter-only"]) == 2


# ---------------------------------------------------------------- 편집 단독 시험 — Pro 초안(02:36Z)을 그대로 받아 편집만

PRO_DRAFT = ROOT / "tests" / "data" / "v5_chapter_pro_20261027T023603Z"
NOTES_C = ROOT / "eval" / "review_notes_C_v5_pro_draft.json"


def _draft_fx():
    return cli.read_draft_run(PRO_DRAFT, NOTES_C)


def _load_drafts(fx=None, outline_fx=None):
    data, turn_map, afx, a = _fixture_analysis()
    o = outline_fx or json.loads(OUTLINE_C2.read_text(encoding="utf-8"))
    outline, _ = pipe.load_outline_fixture(o, a, afx, pipe.check_input(data, turn_map))
    return pipe.load_draft_fixture(fx or _draft_fx()[0], o, outline, a, data)


def _pro_edit(paragraphs=None, omitted=()):
    d = json.loads((PRO_DRAFT / "03_ch-1.json").read_text(encoding="utf-8"))
    return {"diagnosis": [{"issue": "문단 사이가 끊긴다", "where": ["ch-1"], "action": "잇는다"}],
            "title": d["title"],
            "chapters": [{"chapter_key": "ch-1", "center": "큰언니와 재봉틀", "title": d["title"],
                          "paragraphs": paragraphs if paragraphs is not None else d["paragraphs"]}],
            "omitted": list(omitted), "checks_resolution": [], "notes": []}


def test_pro_draft_snapshot_is_loaded_as_is():
    drafts, src = _load_drafts()
    assert src["run_ref"] == "20261027T023603Z-C5-b9f8-focus-fixture-outline-chapter-31propreview"
    assert src["model"] == "gemini-3.1-pro-preview" and src["temperature"] == 1.0
    assert src["sha256"] == ["2cabbb3a7850def6"]
    assert drafts == [json.loads((PRO_DRAFT / "03_ch-1.json").read_text(encoding="utf-8"))]


@pytest.mark.parametrize("change, why", [
    (lambda fx: fx["run"].update(generation_state="generated"), "draft_only"),
    (lambda fx: fx["run"].update(input_ref="0" * 12), "input_ref"),
    (lambda fx: fx["run"].update(outline_source="model"), "reviewed_fixture"),
    (lambda fx: fx["run"]["steps"][0].update(ok=False), "성공한 기록"),
    (lambda fx: fx["drafts"][0]["paragraphs"][0][0].update(facts=["f12"]), "장 집필 계약 위반"),
])
def test_draft_snapshot_is_refused_when_unsafe(change, why):
    fx = json.loads(json.dumps(_draft_fx()[0]))
    change(fx)
    with pytest.raises(pipe.PipelineError, match=why):
        _load_drafts(fx)


def test_draft_snapshot_must_come_from_the_same_outline():
    with pytest.raises(pipe.PipelineError, match="목차 스냅샷과 다르다"):
        _load_drafts(outline_fx=json.loads(OUTLINE_C.read_text(encoding="utf-8")))


@pytest.mark.parametrize("change, why", [
    (lambda d: d["notes"][0].update(fix="손이 빨랐다. 동네 옷도 고쳐 줬다."), "고칠 문장은 넣지 않는다"),
    (lambda d: d["notes"][0].update(location="ch-1/p9"), "초안에 없는 위치"),
    (lambda d: d["notes"][0].update(issue="가" * 200), "자를 넘는다"),
    (lambda d: d["notes"][0].update(turns=[99]), "원문 턴이 아니다"),
    (lambda d: d.update(based_on="다른 실행"), "based_on"),
])
def test_review_notes_carry_problems_only(change, why):
    drafts, src = _load_drafts()
    doc = json.loads(NOTES_C.read_text(encoding="utf-8"))
    assert len(pipe.check_review_notes(doc, drafts, src["run_ref"], set(range(1, 40)))) == 9
    change(doc)
    with pytest.raises(pipe.PipelineError, match=why):
        pipe.check_review_notes(doc, drafts, src["run_ref"], set(range(1, 40)))


def _edit_only(tmp_path, edit, notes=True):
    data, turn_map, afx, _ = _fixture_analysis()
    o = json.loads(OUTLINE_C2.read_text(encoding="utf-8"))
    fx, doc = _draft_fx()
    fake = Fake({"edit": edit})
    r = asyncio.run(pipe.run(data, turn_map, call=fake, recorder=pipe.Recorder(tmp_path), analysis_fixture=afx,
                             outline_fixture=o, model="gemini-3.1-pro-preview", draft_fixture=fx,
                             review_notes=doc if notes else None))
    return r, fake


def test_edit_only_calls_edit_once_with_the_pro_draft(tmp_path):
    r, fake = _edit_only(tmp_path, _pro_edit())
    assert fake.order == ["edit"] and r["calls"] == 1
    spec = fake.specs[0]
    assert spec.model == "gemini-3.1-pro-preview" and spec.max_output_tokens == pipe.EDIT_ONLY_LIMITS[1]
    payload = fake.payload("edit")
    assert len(payload["review_notes"]) == 9 and "missing_core" not in payload          # Pro 초안은 핵심을 다 썼다
    assert payload["drafts"][0]["paragraphs"][1][2]["text"].startswith("말이 별로 없었던 큰언니는")
    assert payload["drafts"][0]["paragraphs"][1][2]["turns"] == [12]                      # 코드가 펼친 턴
    # 조치를 적고 아무것도 바꾸지 않은 편집 — edit_claim_mismatch 로 needs_revision (편집 자기평가를 믿지 않는다)
    assert r["generation_state"] == pipe.EDIT_ONLY and r["overall"] == "needs_revision" and r["human_review"] == "not_run"
    assert [f["rule"] for f in r["code_findings"] if f["severity"] == "fix"] == ["edit_claim_mismatch"]
    assert r["draft_source"]["sha256"] == ["2cabbb3a7850def6"] and r["edit_trace"]["kept"] == 24
    assert r["verification"]["state"] == "not_run"
    for name in ("03_draft_fixture.json", "03_review_notes.json", "03_checks.json", "04_edited.json",
                 "04_edit_trace.json", "04_code_gate.json"):
        assert (tmp_path / name).exists(), name
    assert not (tmp_path / "03_ch-1.json").exists() and not (tmp_path / "05_verify.json").exists()
    run_doc = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert run_doc["settings"]["edit_only"] and run_doc["draft_source"]["run_ref"].endswith("31propreview")
    assert [s["stage"] for s in run_doc["steps"]] == ["edit"]
    assert "편집 단독 시험(edit_only)" in (tmp_path / "r1_summary.md").read_text(encoding="utf-8")
    assert pipe.settings()["MEMOIR_PIPE_TEXT_MODEL"] == "gemini-3.5-flash-lite"
    quiet = {**_pro_edit(), "diagnosis": [{"issue": "고칠 곳 없음", "where": [], "action": ""}]}
    r2, _ = _edit_only(tmp_path / "q", quiet)
    assert r2["code_gate"] == "pass" and r2["overall"] == "edit_only"                   # 검증 전 — awaiting_human 아님


def test_edit_only_that_drops_a_core_memory_needs_revision(tmp_path):
    d = json.loads((PRO_DRAFT / "03_ch-1.json").read_text(encoding="utf-8"))
    paras = json.loads(json.dumps(d["paragraphs"]))
    del paras[1][1]                                                       # f17 바느질을 배운 일
    r, _ = _edit_only(tmp_path, _pro_edit(paras), notes=False)
    assert r["code_gate"] == "attention" and r["overall"] == "needs_revision"
    assert [f["fact"] for f in r["code_findings"] if f["rule"] == "core_missing"] == ["f17"]
    r2, _ = _edit_only(tmp_path / "b", _pro_edit(paras, [{"facts": ["f17"], "reason": "다음 장에서 다룬다"}]), notes=False)
    assert [f["rule"] for f in r2["code_findings"] if f.get("fact") == "f17"] == ["core_omitted"]


def test_edit_only_refusals(tmp_path):
    data, turn_map, afx, _ = _fixture_analysis()
    o = json.loads(OUTLINE_C2.read_text(encoding="utf-8"))
    fx, doc = _draft_fx()
    both = asyncio.run(pipe.run(data, turn_map, call=Fake({}), recorder=pipe.Recorder(tmp_path / "a"),
                                analysis_fixture=afx, outline_fixture=o, chapter_only=True, draft_fixture=fx))
    assert both["generation_state"] == pipe.FAILED and "함께 하지 않는다" in both["failure"]["message"]
    notes = asyncio.run(pipe.run(data, turn_map, call=Fake({}), recorder=pipe.Recorder(tmp_path / "b"),
                                 analysis_fixture=afx, outline_fixture=o, chapter_only=True, review_notes=doc))
    assert notes["generation_state"] == pipe.FAILED and "편집 단독 시험에서만" in notes["failure"]["message"]


def test_cli_edit_only_dry_run_and_refusals(capsys):
    args = ["--seed", str(SEED_C_PATH), "--aliases", "c1,c2,c3,c4,c5", "--dry-run"]
    fx = ["--from-analysis", str(FIXTURE_C), "--from-outline", str(OUTLINE_C2)]
    run = ["--from-draft", str(PRO_DRAFT), "--review-notes", str(NOTES_C), "--model", "gemini-3.1-pro-preview"]
    assert cli.main(args + fx + run) == 0
    out = capsys.readouterr().out
    assert "예상 호출 1회 (편집만)" in out and "검토 지적 9개" in out and "sha256 2cabbb3a7850def6" in out
    assert "예상 비용 gemini-3.1-pro-preview" in out and "출력 상한 32,768" in out and "시간 상한 300초" in out
    assert cli.main(args + run) == 2                                                    # 스냅샷 없이
    assert cli.main(args + fx + run + ["--chapter-only"]) == 2
    assert cli.main(args + fx + ["--review-notes", str(NOTES_C)]) == 2


# ---------------------------------------------------------------- 편집 계약 v6 — 문단 산문 + 근거 표현(claims)
#
# 기준선은 02:49Z Pro 편집(tests/data/v5_edit_pro_20261027T024949Z) — v5 계약으로 나온 그대로다. v6 검사는
# 그 원고에서 실제로 놓쳤던 문제(부정 누락 · 구어 · 1977년 되돌아감 · 안내문 · 진단과 결과 불일치)를 잡아야 하고,
# 같은 원고를 그 문제만 고쳐(적게 바꿔도) 정직하게 적으면 통과해야 한다.

PRO_EDIT = ROOT / "tests" / "data" / "v5_edit_pro_20261027T024949Z"


def _pro_edit_v5():
    return json.loads((PRO_EDIT / "04_edited.json").read_text(encoding="utf-8"))


# 기준선 진단 5개를 v6 의 change · result 로 옮긴 것 — 진단 0 만 결과와 맞지 않는다(문단을 다시 썼다고 했지만 다듬음뿐)
PRO_DIAGNOSIS_V6 = [("rewrite", ["ch-1"], ["ch-1"]), ("move", ["ch-1/p6"], ["ch-1/p0"]),
                    ("fact_fix", ["ch-1/p5"], ["ch-1/p4"]), ("link", ["ch-1/p1"], ["ch-1/p0"]),
                    ("fact_fix", ["ch-1/p1", "ch-1/p3"], ["ch-1/p1", "ch-1/p3"])]


def _as_v6(e=None, diagnosis=PRO_DIAGNOSIS_V6):
    """v5 편집본 → v6 출력 모양(문장마다 span 하나). 본문은 한 글자도 바꾸지 않는다."""
    e = copy.deepcopy(e or _pro_edit_v5())
    chs = []
    for ch in e["chapters"]:
        paras = [{"text": " ".join(x["text"] for x in para),
                  "claims": [{"span": x["text"], "kind": "claim" if x["facts"] else "link", "facts": list(x["facts"])}
                             for x in para]} for para in ch["paragraphs"]]
        chs.append({"chapter_key": ch["chapter_key"], "center": ch.get("center", ""), "title": ch["title"],
                    "composition": [{"paragraph": p, "role": "", "from": [f"ch-1/p{p}"], "after_previous": "",
                                     "reorder": None} for p in range(len(paras))],
                    "paragraphs": paras})
    diag = [{**d, "change": c, "where": w, "result": r} for d, (c, w, r) in zip(e["diagnosis"], diagnosis)]
    return {"diagnosis": diag, "title": e["title"], "chapters": chs, "omitted": e["omitted"],
            "checks_resolution": e["checks_resolution"], "notes": e["notes"]}


def _v6_check(out):
    data, turn_map, _, a = _fixture_analysis()
    return pipe.check_final_v6(out, a, pipe.check_input(data, turn_map), "큰언니와 재봉틀")


def _rules(findings, severity=None):
    return sorted({(f["rule"], f["location"]) for f in findings if severity in (None, f["severity"])})


def test_split_sentences_keeps_quotes_whole():
    t = "편지에는 '기름 자주 쳐라. 알았제.' 그 말 하나였다. 나는 웃었다!  그랬다"
    assert [t[s:e] for s, e in pipe.split_sentences(t)] == [
        "편지에는 '기름 자주 쳐라. 알았제.' 그 말 하나였다.", "나는 웃었다!", "그랬다"]
    q = "언니는 '기름 자주 쳐라.' 그리고 끝이었다."
    assert len(pipe.split_sentences(q)) == 1


def test_v6_baseline_converts_to_the_same_sentences():
    edited, omitted, warnings, findings = _v6_check(_as_v6())
    v5 = _pro_edit_v5()
    assert [[x["text"] for x in p] for p in edited["chapters"][0]["paragraphs"]] == \
           [[x["text"] for x in p] for p in v5["chapters"][0]["paragraphs"]]
    assert [[x["facts"] for x in p] for p in edited["chapters"][0]["paragraphs"]] == \
           [[x["facts"] for x in p] for p in v5["chapters"][0]["paragraphs"]]
    assert edited["contract"] == "v6" and len(edited["chapters"][0]["prose"]) == 6
    assert findings == [] and "f51" in omitted


@pytest.mark.parametrize("change, rule, severity", [
    (lambda p: p["claims"][0].update(span="원문에 없는 표현"), "span_missing", "block"),
    (lambda p: p["claims"].reverse(), "span_misplaced", "block"),
    (lambda p: p["claims"].__setitem__(slice(0, 2), [{"span": p["claims"][0]["span"] + " " + p["claims"][1]["span"],
                                                       "kind": "claim", "facts": ["f57", "f58"]}]),
     "span_crosses_sentence", "block"),
    (lambda p: p["claims"].pop(1), "uncovered_text", "fix"),
    (lambda p: p["claims"][0].update(span="언니가"), "uncovered_text", "fix"),          # 「준 재봉틀을 아직 못 버렸다」 근거 없음
])
def test_v6_span_must_point_at_the_text(change, rule, severity):
    out = _as_v6()
    change(out["chapters"][0]["paragraphs"][0])
    _, _, _, findings = _v6_check(out)
    assert any(f["rule"] == rule and f["severity"] == severity for f in findings), _rules(findings)


@pytest.mark.parametrize("change, why", [
    (lambda o: o["chapters"][0]["paragraphs"][0]["claims"][3].update(facts=["f57"]), "link 인데 facts"),
    (lambda o: o["chapters"][0]["paragraphs"][0]["claims"][0].update(facts=[]), "비었다"),
    (lambda o: o["chapters"][0]["paragraphs"][0]["claims"][0].update(facts=["f99"]), "없는 사실"),
    (lambda o: o["diagnosis"][0].update(change="improve"), "change="),
    (lambda o: o["chapters"][0]["paragraphs"].__setitem__(0, [{"text": "옛 모양", "kind": "editorial", "facts": []}]),
     "객체가 아니다"),
    (lambda o: o["chapters"][0].pop("composition"), "composition"),
    (lambda o: o["chapters"][0]["composition"][4].update(reorder={"facts": [], "reason": "왜"}), "reorder.facts"),
])
def test_v6_contract_shape_errors_stop(change, why):
    out = _as_v6()
    change(out)
    with pytest.raises(pipe.PipelineError, match=why):
        _v6_check(out)


def _baseline_v6_findings():
    data, turn_map, _, a = _fixture_analysis()
    edited, _, _, spans = _v6_check(_as_v6())
    pipe.expand_turns(edited["chapters"], pipe.ledger(a), edited["title"])
    return data, a, edited, spans + pipe.v6_findings(edited["chapters"], data, a)


def test_v6_checks_catch_what_the_pro_edit_got_past():
    """02:49Z Pro 편집본 그대로 — v5 code_gate 는 pass(info 4)였다."""
    data, a, edited, found = _baseline_v6_findings()
    fix = _rules(found, "fix")
    assert ("negation_lost", "ch-1/p1/s0") in fix                       # 턴 10 「저는 기억은 안 나요」
    assert ("time_reversal_undeclared", "ch-1/p4") in fix               # 1985~ 가게 뒤 1977년, 이유 없음
    review = _rules(found, "review")
    for want in [("spoken_carryover", "ch-1/p0/s2"), ("spoken_carryover", "ch-1/p3/s2"),     # 말이다 · 그거 하나
                 ("spoken_carryover", "ch-1/p5/s0"), ("meta_suspect", "ch-1/p0/s3")]:        # ~겠어서 · 안내문
        assert want in review, want
    neg = next(f for f in found if f["rule"] == "negation_lost")
    assert neg["fact"] == "f16"
    assert not any(f["rule"] == "negation_lost" and f["fact"] != "f16" for f in found)   # 다른 부정은 지켰다


def test_v6_checks_on_the_pro_draft_find_its_cause_and_repeat_but_not_negation():
    data, _, _, a = _fixture_analysis()
    d = [json.loads((PRO_DRAFT / "03_ch-1.json").read_text(encoding="utf-8"))]
    pipe.expand_turns(d, pipe.ledger(a))
    found = pipe.v6_findings(d, data, a)
    assert ("causal_suspect", "ch-1/p1/s2") in _rules(found, "review")      # 손이 빨라서 … 고쳐 주곤
    assert ("repeat_phrase", "ch-1/p6/s1") in _rules(found, "review")       # 2010년에 … 2010년에
    assert not [f for f in found if f["rule"] == "negation_lost"]           # 초안은 「기억하지는 못하지만」


def _one(text, facts, a):
    ch = _expanded([_chapter([(text, facts)])], a)
    return ch


def test_negation_kept_when_rephrased_with_a_negative():
    data, _, _, a = _fixture_analysis()
    book = pipe.ledger(a)
    lost = _one("엄마가 밭일 나가면 큰언니가 나를 업어 키웠다고 들었다.", ["f16"], a)
    kept = _one("엄마가 밭일을 나가면 큰언니가 나를 업어 키웠다고 들었지만, 나는 기억이 나지 않는다.", ["f16"], a)
    assert [f["rule"] for f in pipe.negation_findings(lost, book, data)] == ["negation_lost"]
    assert pipe.negation_findings(kept, book, data) == []


@pytest.mark.parametrize("text, facts, rule", [
    ("말이 별로 없었기 때문에 큰언니는 손이 빨랐다.", ["f18"], "causal_unsupported"),
    ("말이 별로 없었던 큰언니는 손이 빨라서 동네 사람들의 옷을 다 고쳐 주곤 했다.", ["f18", "f19"], "causal_suspect"),
    ("무릎이 아파서 더는 오래 앉아 있을 수 없어 2010년에 수선집을 그만두었다.", ["f2", "f3"], None),   # 턴 2 「아파서」
    ("가게 문을 닫으면서 그 발틀 재봉틀을 집으로 가져왔다.", ["f54", "f65"], None),                   # ~면서 는 동시
])
def test_causal_findings(text, facts, rule):
    data, _, _, a = _fixture_analysis()
    got = [f["rule"] for f in pipe.causal_findings(_one(text, facts, a), data)]
    assert got == ([rule] if rule else [])


def test_link_may_not_carry_feeling_motive_or_cause_and_weak_claims_go_to_review():
    out = _as_v6()
    p0 = out["chapters"][0]["paragraphs"][0]
    p0["text"] = p0["text"].replace("이 재봉틀에 얽힌 기억을 따라가다 보면 어린 시절로 거슬러 올라가게 된다.",
                                    "그 소리가 그리워서 나는 다시 재봉틀 앞에 앉는다.")
    p0["claims"][3]["span"] = "그 소리가 그리워서 나는 다시 재봉틀 앞에 앉는다."
    p1 = out["chapters"][0]["paragraphs"][1]
    p1["text"] = p1["text"].replace("열 살쯤 큰언니에게 양말 꿰매는 걸 배웠다.", "열 살쯤 나는 처음으로 우주를 꿈꾸었다.")
    p1["claims"][1]["span"] = "열 살쯤 나는 처음으로 우주를 꿈꾸었다."
    data, turn_map, _, a = _fixture_analysis()
    edited, _, _, spans = _v6_check(out)
    pipe.expand_turns(edited["chapters"], pipe.ledger(a))
    found = pipe.span_findings(edited["chapters"], data, pipe.ledger(a))
    assert ("link_content", "ch-1/p0/s3") in _rules(found, "fix")
    assert ("claim_weak", "ch-1/p1/s1") in _rules(found, "review")
    assert not [f for f in found if f["rule"] == "claim_weak" and f["location"] != "ch-1/p1/s1"]   # 기준선 문장은 걸리지 않는다


def _baseline_trace():
    data, a, edited, _ = _baseline_v6_findings()
    d = [json.loads((PRO_DRAFT / "03_ch-1.json").read_text(encoding="utf-8"))]
    pipe.expand_turns(d, pipe.ledger(a))
    return edited, pipe.edit_trace(d, edited["chapters"])


def test_claimed_rewrite_that_only_polished_is_a_mismatch_but_honest_small_claims_pass():
    edited, trace = _baseline_trace()
    found = pipe.claim_findings(edited, trace)
    assert [f["token"] for f in found] == ["d0"]                     # 「문단을 다시 구성」 — 다시 쓴 문장 1개뿐
    assert "다시 썼다는 문장 27개 중" in found[0]["detail"]


@pytest.mark.parametrize("change, where, result, ok", [
    ("merge", ["ch-1/p3", "ch-1/p4"], ["ch-1/p3"], True),            # 초안 p3 + p4 → 편집 p3
    ("merge", ["ch-1/p1"], ["ch-1/p1"], False),
    ("split", ["ch-1/p1"], ["ch-1/p1"], False),
    ("cut", ["ch-1/p6"], [], False),                                  # 덜어 낸 문장 · 사실이 없다
    ("move", ["ch-1/p1"], ["ch-1/p1"], False),
    ("link", ["ch-1/p5"], ["ch-1/p4"], False),                       # p4 의 새 문장은 사실 문장(1977)이다
    ("fact_fix", ["ch-1/p2"], ["ch-1/p2"], False),                   # 공장 문단은 초안 그대로
    ("rewrite", ["ch-1/p1"], ["ch-1/p9"], False),                    # 없는 위치
])
def test_each_change_is_checked_against_the_trace(change, where, result, ok):
    edited, trace = _baseline_trace()
    edited["diagnosis"] = [{"issue": "x", "where": where, "change": change, "action": "", "result": result}]
    assert (pipe.claim_findings(edited, trace) == []) is ok


def test_declared_reorder_goes_to_review_and_composition_is_compared_with_the_trace():
    out = _as_v6()
    out["chapters"][0]["composition"][4]["reorder"] = {"facts": ["f42", "f43"],
                                                      "reason": "2003년 병문안 때 바다를 보지 않은 일 앞에 처음 본 바다를 둔다"}
    data, turn_map, _, a = _fixture_analysis()
    edited, _, _, spans = _v6_check(out)
    pipe.expand_turns(edited["chapters"], pipe.ledger(a))
    found = pipe.reorder_findings(edited["chapters"], pipe.ledger(a))
    assert _rules(found) == [("time_reversal_declared", "ch-1/p4")] and found[0]["severity"] == "review"
    _, trace = _baseline_trace()
    mism = pipe.composition_findings(edited, trace)                  # from 을 초안 같은 번호로만 적었다
    assert ("composition_mismatch", "ch-1/p3") in _rules(mism, "review")     # 실제는 초안 p3 + p4
    out["chapters"][0]["composition"].pop()
    _, _, _, f2 = _v6_check(out)
    assert ("composition_missing", "ch-1") in _rules(f2, "fix")


def test_composition_memo_copied_into_a_link_is_blocked():
    out = _as_v6()
    out["chapters"][0]["composition"][0]["after_previous"] = "이 재봉틀에 얽힌 기억을 따라가다 보면 어린 시절로 거슬러 올라가게 된다"
    edited, _, _, _ = _v6_check(out)
    assert _rules(pipe.composition_leaks(edited)) == [("memo_leak", "ch-1/p0/s3")]


def _small_honest_fix():
    """기준선을 문제 셋만 고친 v6 원고 — 부정 표현 되살림 · 1977년 재배치 이유 · 진단을 사실대로."""
    out = _as_v6(diagnosis=[("fact_fix", ["ch-1/p1"], ["ch-1/p1"])] * 5)
    out["diagnosis"] = out["diagnosis"][:1]
    p1 = out["chapters"][0]["paragraphs"][1]
    old = "엄마가 밭일 나가면 큰언니가 나를 업어 키웠다고 들었다."
    new = "엄마가 밭일을 나가면 큰언니가 나를 업어 키웠다고 들었지만, 나는 기억이 나지 않는다."
    p1["text"] = p1["text"].replace(old, new)
    p1["claims"][0]["span"] = new
    out["chapters"][0]["composition"][4]["reorder"] = {"facts": ["f42", "f43"], "reason": "병문안 때의 바다 앞에 처음 본 바다를 둔다"}
    for e, src in zip(out["chapters"][0]["composition"], (["ch-1/p0", "ch-1/p6"], ["ch-1/p1"], ["ch-1/p2"],
                                                          ["ch-1/p3", "ch-1/p4"], ["ch-1/p5"], ["ch-1/p6"])):
        e["from"] = src
    return out


def _edit_only_v6(tmp_path, edit, notes=True):
    data, turn_map, afx, _ = _fixture_analysis()
    o = json.loads(OUTLINE_C2.read_text(encoding="utf-8"))
    fx, doc = _draft_fx()
    fake = Fake({"edit": edit})
    r = asyncio.run(pipe.run(data, turn_map, call=fake, recorder=pipe.Recorder(tmp_path), analysis_fixture=afx,
                             outline_fixture=o, model="gemini-3.1-pro-preview", draft_fixture=fx,
                             review_notes=doc if notes else None, edit_contract="v6"))
    return r, fake


def test_v6_edit_only_run_on_the_pro_baseline_needs_revision(tmp_path):
    r, fake = _edit_only_v6(tmp_path, _as_v6())
    assert fake.order == ["edit"] and r["calls"] == 1 and r["edit_contract"] == "v6"
    spec = fake.specs[0]
    assert "claims" in spec.system and "4_편집_v6" not in spec.system and spec.system != pipe.prompt("edit")
    assert spec.system == pipe.edit_prompt("v6") and spec.max_output_tokens == pipe.EDIT_ONLY_LIMITS[1]
    payload = fake.payload("edit")
    d0 = payload["drafts"][0]["paragraphs"]
    assert len(d0) == 7 and set(d0[0]) == {"location", "text", "facts"}                   # 문장 객체를 주지 않는다
    assert d0[1]["text"].startswith("내가 기억하지는 못하지만,") and d0[1]["facts"][0] == "f16"
    assert "facts" not in payload["book_plan"]["chapters"][0]["paragraphs"][0]            # 문단별 facts 배열은 뺀다
    assert payload["book_plan"]["chapters"][0]["paragraphs"][1]["core"] == ["f17", "f20", "f21"]
    assert len(payload["core_facts"]) == 18 and not set(payload["core_facts"]) & set(payload["must_keep"])
    assert all(c["severity"] in ("block", "fix") for c in payload["checks"])
    note = next(n for n in payload["review_notes"] if n["location"] == "ch-1/p1/s2")
    assert note["quote"].startswith("말이 별로 없었던 큰언니는 손이 빨라서")
    assert r["overall"] == "needs_revision" and r["code_gate"] == "attention"
    fixes = _rules(r["code_findings"], "fix")
    for want in [("negation_lost", "ch-1/p1/s0"), ("time_reversal_undeclared", "ch-1/p4"),
                 ("edit_claim_mismatch", "artifact")]:
        assert want in fixes, want
    assert any(f["severity"] == "review" for f in r["code_findings"])
    gate = json.loads((tmp_path / "04_code_gate.json").read_text(encoding="utf-8"))
    assert gate["counts"]["review"] >= 5
    for name in ("04_edited.json", "04_edited_sentences.json", "04_edit_trace.json", "04_code_gate.json"):
        assert (tmp_path / name).exists(), name
    assert "편집 계약 v6" in (tmp_path / "r1_summary.md").read_text(encoding="utf-8")
    assert "review 는 사람 확인" in (tmp_path / "r1_summary.md").read_text(encoding="utf-8")
    run_doc = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert run_doc["settings"]["edit_contract"] == "v6" and run_doc["prompts"]["edit_v6"].startswith("sha256:")
    assert pipe.settings()["MEMOIR_PIPE_TEXT_MODEL"] == "gemini-3.5-flash-lite"


def test_v6_small_honest_fix_passes_the_gate_even_with_little_change(tmp_path):
    r, _ = _edit_only_v6(tmp_path, _small_honest_fix())
    assert [f for f in r["code_findings"] if f["severity"] in ("block", "fix")] == []
    assert r["code_gate"] == "pass" and r["overall"] == "edit_only" and r["human_review"] == "not_run"
    assert r["edit_trace"]["unchanged_ratio"] < 0.5
    assert any(f["rule"] == "spoken_carryover" for f in r["code_findings"])   # 구어는 사람 확인으로 남는다


def test_v6_span_problem_blocks_but_keeps_the_manuscript(tmp_path):
    out = _as_v6()
    out["chapters"][0]["paragraphs"][2]["claims"][0]["span"] = "서울로 올라갔다"
    r, _ = _edit_only_v6(tmp_path, out)
    assert r["code_gate"] == "blocked" and r["overall"] == "blocked_by_code"
    assert ("span_missing", "ch-1/p2") in _rules(r["code_findings"], "block")
    assert r["chapters"] and (tmp_path / "04_edited_sentences.json").exists()


def test_v6_is_only_for_edit_only_and_v5_edit_is_unchanged(tmp_path):
    data, turn_map, afx, _ = _fixture_analysis()
    o = json.loads(OUTLINE_C2.read_text(encoding="utf-8"))
    bad = asyncio.run(pipe.run(data, turn_map, call=Fake({}), recorder=pipe.Recorder(tmp_path / "a"),
                               analysis_fixture=afx, outline_fixture=o, chapter_only=True, edit_contract="v6"))
    assert bad["generation_state"] == pipe.FAILED and "편집 단독 시험에서만" in bad["failure"]["message"]
    other = asyncio.run(pipe.run(data, turn_map, call=Fake({}), recorder=pipe.Recorder(tmp_path / "b"),
                                 analysis_fixture=afx, outline_fixture=o, chapter_only=True, edit_contract="v7"))
    assert "편집 계약 'v7'" in other["failure"]["message"]
    r, fake = _edit_only(tmp_path / "c", _pro_edit())                    # 기본 v5 — 지시문 · 자료 그대로
    assert fake.specs[0].system == pipe.prompt("edit") and r["edit_contract"] == "v5"
    assert "drafts" in fake.payload("edit") and "text" in fake.payload("edit")["drafts"][0]["paragraphs"][0][0]
    V6_RULES = {"negation_lost", "causal_unsupported", "causal_suspect", "spoken_carryover", "meta_suspect",
                "repeat_phrase", "time_reversal_undeclared", "time_reversal_declared", "link_content", "claim_weak",
                "span_missing", "span_misplaced", "span_crosses_sentence", "uncovered_text", "composition_missing",
                "composition_mismatch"}
    assert not [f for f in r["code_findings"] if f["rule"] in V6_RULES]      # 문장 객체 계약 실행에는 v6 검사를 더하지 않는다
    assert pipe.ROLE_FILES["edit"] == "4_편집_v7.md" and pipe.PROMPT_VERSION == "v7"


def test_v1_to_v5_prompts_untouched_and_v6_prompt_exists():
    d = ROOT / "첨부프롬프트_md" / "파이프라인"
    for n in range(1, 6):
        assert (d / f"4_편집_v{n}.md").exists()
    v6 = (d / pipe.EDIT_V6_FILE).read_text(encoding="utf-8")
    for want in ('"claims"', '"composition"', '"change"', '"result"', '"reorder"', "사실 메모이지 문장이 아닙니다"):
        assert want in v6, want


def test_cli_v6_dry_run_and_refusal(capsys):
    args = ["--seed", str(SEED_C_PATH), "--aliases", "c1,c2,c3,c4,c5", "--dry-run"]
    fx = ["--from-analysis", str(FIXTURE_C), "--from-outline", str(OUTLINE_C2)]
    run = ["--from-draft", str(PRO_DRAFT), "--review-notes", str(NOTES_C), "--model", "gemini-3.1-pro-preview"]
    assert cli.main(args + fx + run + ["--edit-contract", "v6"]) == 0
    out = capsys.readouterr().out
    assert "예상 호출 1회 (편집만) · 편집 계약 v6" in out and "편집(v6) — 입력 약" in out and "출력 상한 32,768" in out
    assert cli.main(args + fx + ["--edit-contract", "v6"]) == 2


def test_blind_edit_comparison_uses_v6_prose_and_edit_criteria(tmp_path):
    data, _ = source_c()
    base = tmp_path / "base"
    base.mkdir()
    for name in ("result.json", "run.json", "03_review_notes.json"):
        (base / name).write_bytes((PRO_EDIT / name).read_bytes())
    r6, _ = _edit_only_v6(tmp_path / "v6", _small_honest_fix())
    key = blind.make([base / "result.json", tmp_path / "v6" / "result.json"], data, tmp_path / "out",
                     random.Random(0), blind.EDIT_CRITERIA)
    assert {k["edit_contract"] for k in key.values()} == {None, "v6"}
    lab6 = next(k for k, v in key.items() if v["edit_contract"] == "v6")
    text6 = (tmp_path / "out" / "평가용" / f"글_{lab6}.md").read_text(encoding="utf-8")
    assert "나는 기억이 나지 않는다." in text6 and not re.search(r"v[56]|f\d|claim|span", text6)
    sheet = (tmp_path / "out" / "평가용" / "평가지.md").read_text(encoding="utf-8")
    assert "도입과 마무리" in sheet and "책 수록" in sheet
    scope = {v["edit_contract"]: v["scope"]["how"] for v in key.values()}
    assert "편집 계약 v6" in scope["v6"] and "검토 지적 9개" in scope["v6"] and "편집 계약 v5" in scope[None]
    facts = (tmp_path / "out" / "검수자용" / f"사실대조표_{lab6}.md").read_text(encoding="utf-8")
    assert "「엄마가 밭일을 나가면" in facts and "뜻이 맞는 것이 아니다" in facts


# ---------------------------------------------------------------- v7 — 독립 일화 · 필수 경위 보존 (2026-10-29 합의 명세)
#
# 모델을 부르지 않는다. 저장된 Pro 초안 · v5 편집 · v6 편집 기록과, 대화에 첨부된 원문 20개 시험(5 · 10 · 20개 입력
# 결과)의 사례를 짧은 합성 원장으로 옮긴 것만 쓴다 — 그 결과들의 실행 기록은 없어 단계별 원인은 시험하지 않는다.


def test_v7_prompts_are_what_the_run_actually_sends_and_v5_files_stay():
    fake = Fake(script())
    go(fake)
    by = {s.stage: s.system for s in fake.specs}
    want = {"analysis": "흐린 대상이 나이라는 이유만으로 값을 바꾸지 마세요",
            "outline": "주된 구간은 한 곳이며, 필요하면 이어지는 여러 문단으로 전개합니다",
            "chapter": "\"나는 생각한다\", \"것 같다\"는 필수 문형이 아닙니다",
            "edit": "예시 문구를 문장 끝에 덧붙이지 마세요",
            "verify": "theme_contradiction"}
    for stage, text in want.items():
        assert by[stage] == pipe.prompt(stage) and text in by[stage], stage
    reflect = {"analysis": "당시의 감정 · 판단과 지금 돌아보며 하는 해석도 같은 방식으로 나눕니다",      # 당시의 경험과 지금의 회고
               "outline": "의미 있는 회고를 일화마다 끝에 되풀이해 두지 말고",
               "chapter": "그때의 나와 지금 돌아보는 나",
               "edit": "원문에 없는 성장 · 화해 · 용서 · 감사를 결말로 더하지 마세요",
               "verify": "회고가 없다는 이유로 감점하지 마세요"}
    for stage, text in reflect.items():
        assert text in by[stage], stage
    v5 = (pipe.ROLE_DIR / "2_목차_v5.md").read_text(encoding="utf-8")
    assert "**모든 발언을 본문에 넣지 않습니다.**" in v5 and "주된 구간" not in v5          # 옛 판은 그대로
    for stage in pipe.STAGES:                                                      # 출력 계약(키)은 v5 그대로
        old = (pipe.ROLE_DIR / pipe.ROLE_FILES[stage].replace("_v7", "_v5")).read_text(encoding="utf-8")
        new = pipe.role_text(stage)
        tail = lambda s: re.findall(r'"(\w+)":', s.split("[출력")[-1])
        assert set(tail(new)) - set(tail(old)) <= {"core"}, stage                  # core 는 기존 선택 키


def test_edit_trace_shape_is_unchanged_and_merge_is_only_a_candidate():
    data, _ = source()
    a = analysis_ok()
    drafts = _expanded([_chapter([("첫 월급을 받았다.", ["f1"]), ("목도리를 사 드렸다.", ["f2"])])], a)
    final = _expanded([_chapter([("첫 월급으로 목도리를 사 드렸다.", ["f1", "f2"])])], a)
    trace = pipe.edit_trace(drafts, final)
    s = trace["summary"]
    assert isinstance(s["dropped"], int) and s["dropped"] == 1 and len(trace["dropped"]) == 1
    assert all(isinstance(x, str) for x in trace["dropped"]) and trace["dropped_facts"] == []
    gone = trace["dropped"][0]
    gone_fact = trace["draft_facts_at"][gone][0]
    cands = pipe.omission_candidates(drafts, final, trace, a, data, {}, {}, set())
    assert [(c["fact"], c["kind"]) for c in cands] == [(gone_fact, "fact_changed")]     # 같은 id 가 남아도 후보
    assert "덜어 낸 문장" in cands[0]["signals"][0] and cands[0]["draft"][0]["loc"] == gone
    assert cands[0]["final"][0]["text"] == "첫 월급으로 목도리를 사 드렸다." and cands[0]["evidence"][0]["turn"] == int(gone_fact[1:])
    outline = outline_ok()
    found = pipe.all_findings(final, {**outline, "chapters": outline["chapters"][:1]}, data, a, {}, final=True)
    assert not [f for f in found if f["severity"] in ("block", "fix")]                  # 통합만으로 오류를 내지 않는다


def _one_chapter_outline(paras, units=("m1", "m2"), omit=()):
    o = outline_ok()
    o["chapters"] = [chapter_plan("ch-1", paras, "일과 가족", list(units))]
    o["omit"] = list(omit)
    o["book"]["closing_facts"] = [paras[-1]["facts"][0]]
    return o


def test_referenced_id_does_not_resolve_a_protected_omission():
    data, _ = source()
    a = analysis_ok()
    a["facts"][1]["keep"] = True                                                   # f2 는 must_keep
    o = _one_chapter_outline([{**para(["f1", "f2"]), "core": ["f1"]}, para(["f3", "f4"])])
    final = _expanded([_chapter([("첫 월급을 받던 해였다.", ["f3"]), ("딸이 입학했다.", ["f4"])])], a)
    eo = {"f1": "중복 — f3 에 남음", "f2": "중복 — f3 문장에 합침"}
    found = pipe.all_findings(final, o, data, a, {}, final=True, edit_omitted=eo)
    by = {(f["rule"], f.get("fact")): f["severity"] for f in found}
    assert by[("core_omitted", "f1")] == "fix" and by[("must_keep_omitted", "f2")] == "fix"
    assert pipe.code_gate(found, {}, [])["state"] == "attention"
    prot = pipe.protected_omissions(found, a, data, final)
    row = next(x for x in prot if x["rule"] == "core_omitted")
    assert row["facts"][0]["fact"] == "f1" and row["facts"][0]["evidence"][0]["turn"] == 1
    assert row["referenced"] == [{"fact": "f3", "final": [{"loc": "ch-1/p0/s0", "text": "첫 월급을 받던 해였다."}]}]


# 원문 20개 시험의 사례 — 텔레비전 · 펜팔(어머니와 먼 독립 일화)과 고무신 두 일화를 짧은 원장으로 옮긴 것
def _twenty_case():
    a = analysis_ok()
    a["facts"] = [fact("f1", [1], "어머니가 캐 온 꼬막 자루를 나름", "여섯 살쯤", certainty="approx"),
                  fact("f2", [2], "이장님 댁에 동네 첫 텔레비전", "열 살 때"),
                  fact("f3", [3], "순천 여고생과 펜팔 · 순천역에서 한 번 만남", "열여덟 살"),
                  fact("f4", [4], "종태가 고무신을 빼앗겨 맨발로 울며 옴", "중학교 2학년"),
                  fact("f5", [5], "동생 학교를 뒤져 고무신을 찾아냄"),
                  fact("f6", [6], "못을 달궈 고무신 안쪽에 종태 이름을 새김")]
    a["units"] = [{"id": "m1", "name": "꼬막 자루", "facts": ["f1"], "time": "", "weight": "main"},
                  {"id": "m2", "name": "동네 첫 텔레비전", "facts": ["f2"], "time": "", "weight": "minor"},
                  {"id": "m3", "name": "펜팔", "facts": ["f3"], "time": "", "weight": "minor"},
                  {"id": "m4", "name": "빼앗긴 고무신", "facts": ["f4", "f5", "f6"], "time": "", "weight": "main"}]
    return a


def test_twenty_case_tv_and_penpal_dropped_whole_are_fixed_even_when_minor_or_brief_only():
    data, _ = source()
    a = _twenty_case()
    o = _one_chapter_outline([{**para(["f1"]), "core": ["f1"]}, {**para(["f4", "f5", "f6"], brief=["f3"]), "core": ["f6"]},
                              {**para(["f2"]), "core": ["f2"]}], units=("m1", "m2", "m3", "m4"))
    final = _expanded([_chapter([("여섯 살쯤 어머니가 캐 온 꼬막 자루를 날랐다.", ["f1"]),
                                 ("종태가 고무신을 빼앗겼다.", ["f4"]), ("나는 동생 학교를 뒤져 찾아냈다.", ["f5"]),
                                 ("못을 달궈 이름을 새겨 주었다.", ["f6"])])], a)
    found = pipe.episode_findings(final, o, a, {"f2": "어머니 이야기와 멀다"}, {})
    assert {(f["rule"], f["unit"], f["severity"]) for f in found} == {
        ("episode_omitted", "m2", "fix"),                                          # minor 이고 이유가 있어도
        ("episode_missing", "m3", "fix")}                                          # brief 로만 계획한 펜팔도 채택이다


def test_twenty_case_gomusin_background_loss_is_a_candidate_not_an_episode_error():
    data, _ = source()
    a = _twenty_case()
    o = _one_chapter_outline([{**para(["f4", "f5", "f6"]), "core": ["f6"]}], units=("m4",),
                             omit=[{"facts": ["f1", "f2", "f3"], "reason": "다른 장 몫"}])
    drafts = _expanded([_chapter([("종태가 고무신을 빼앗겨 맨발로 울며 왔다.", ["f4"]),
                                  ("다음 날 동생 학교를 뒤져 고무신을 찾아냈다.", ["f5"]),
                                  ("그날 저녁 못을 달궈 고무신 안쪽에 이름을 새겨 주었다.", ["f6"])])], a)
    final = _expanded([_chapter([("중학교 2학년 때 못을 달궈 고무신 안쪽에 종태 이름을 새겨 주었다.", ["f6"])])], a)
    trace = pipe.edit_trace(drafts, final)
    found = pipe.all_findings(final, o, data, a, {f: "다른 장 몫" for f in ("f1", "f2", "f3")}, final=True)
    assert not [f for f in found if f["rule"].startswith("episode_m") or f["rule"] == "episode_omitted"]
    cands = pipe.omission_candidates(drafts, final, trace, a, data, {}, {}, {"f6"})
    assert [(c["fact"], c["kind"]) for c in cands] == [("f4", "fact_dropped"), ("f5", "fact_dropped")]
    assert cands[0]["draft"][0]["text"].startswith("종태가 고무신을 빼앗겨")              # 검증이 원문과 대조할 재료


def test_outline_exclusion_edit_omission_and_focus_scope_are_kept_apart():
    data, _ = source()
    a = analysis_ok()
    a["facts"][3]["keep"] = True                                                   # f4 must_keep, 목차가 뺐다
    o = _one_chapter_outline([{**para(["f1", "f2"]), "core": ["f1"]}], units=("m1",),
                             omit=[{"facts": ["f3", "f4"], "reason": "한 장 시험 범위 밖 — 딸의 장 몫"}])
    outline_omit = {"f3": "한 장 시험 범위 밖", "f4": "한 장 시험 범위 밖"}
    final = _expanded([_chapter([("첫 월급으로 목도리를 사 드렸다.", ["f1", "f2"])])], a)
    found = pipe.all_findings(final, o, data, a, outline_omit, final=True, edit_omitted=dict(outline_omit))
    rules = {(f["rule"], f.get("fact") or f.get("unit"), f["severity"]) for f in found
             if f["rule"].startswith(("episode_", "must_keep_"))}
    assert rules == {("episode_excluded", "m2", "review"), ("must_keep_excluded", "f4", "review")}
    assert pipe.code_gate(found, {}, [])["state"] == "pass"                        # 범위 밖은 편집 누락이 아니다
    gone = pipe.all_findings(_expanded([_chapter([("딴 얘기다.", ["f3"])])], a), _one_chapter_outline(
        [{**para(["f1", "f2"]), "core": ["f1"]}, {**para(["f3", "f4"]), "core": ["f3"]}]), data, a, {}, final=True,
        edit_omitted={"f1": "줄임", "f2": "줄임"})
    assert ("episode_omitted", "m1") in {(f["rule"], f.get("unit")) for f in gone}


def test_core_unset_warning_reaches_verify_through_plan_checks():
    fake = Fake(script())
    r = go(fake)
    checks = fake.payload("verify")["plan"]["checks"]
    core_warn = [c for c in checks if CORE_WARN in c]
    assert len(core_warn) == 2 and all(c.startswith("outline: ch-") for c in core_warn)  # 장마다 일화 하나씩
    assert r["code_gate"] == "pass" and r["overall"] == "awaiting_human"           # 형식 오류 · 게이트 실패가 아니다
    with_core = outline_ok()
    for ch in with_core["chapters"]:
        ch["paragraphs"][0]["core"] = ch["paragraphs"][0]["facts"][:1]
    status, w = pipe.check_outline(with_core, analysis_ok(), set(range(1, 7)))
    assert status == "ready" and not [x for x in w if CORE_WARN in x]
    brief_only = outline_ok()
    brief_only["chapters"][1]["paragraphs"] = [{**para(["f3"], brief=["f4"]), "core": ["f3"]}]
    brief_only["chapters"][0]["paragraphs"][0]["core"] = ["f1"]
    _, w = pipe.check_outline(brief_only, analysis_ok(), set(range(1, 7)))
    assert not [x for x in w if CORE_WARN in x]                                    # 기준은 facts 의 주된 서술


def test_verify_receives_omission_review_and_protected_omissions():
    edit = edited_ok()
    edit["chapters"][1]["paragraphs"] = [[sent("뒤의 일이다.", ["f3"])]]          # f4 를 말없이 뺐다
    fake = Fake(script(edit=edit))
    r = go(fake)
    plan = fake.payload("verify")["plan"]
    assert [(c["fact"], c["kind"]) for c in plan["omission_review"]] == [("f4", "fact_dropped")]
    assert plan["omission_review"][0]["evidence"][0]["turn"] == 6
    assert "omission_review" in fake.specs[-1].user.split("\n\n", 1)[0]           # 검증 입력 설명
    assert r["code_gate"] == "pass"                                                # 보조 사실 생략은 후보일 뿐
    keep = analysis_ok()
    keep["facts"][3]["keep"] = True
    fake = Fake(script(analysis=keep, edit=edit))
    r = go(fake)
    prot = fake.payload("verify")["plan"]["protected_omissions"]
    assert [(x["rule"], x["facts"][0]["fact"]) for x in prot] == [("must_keep_missing", "f4")]
    assert r["overall"] == "needs_revision"                                        # 미해결 보호 누락은 상태에 남는다


def test_title_composition_warning_fits_the_verify_contract(tmp_path):
    v = verify_ok(issues=[{"location": "title", "category": "composition", "severity": "warning",
                           "code": "theme_contradiction", "resolution": "auto_fix",
                           "explanation": "제목의 교복 이야기가 본문에 없다", "source_turns": [1], "fix_instruction": ""}])
    locs = pipe.locations(edited_ok())
    assert isinstance(pipe.check_verify(json.loads(json.dumps(v)), set(range(1, 7)), locs), list)   # 형식 거부 없음
    r = go(Fake(script(verify=v)))
    assert r["model_verdict"] == "pass" and r["verification"]["issues"][0]["code"] == "theme_contradiction"


def _saved_edit(path, sentences=False):
    return json.loads((ROOT / "tests" / "data" / path / ("04_edited_sentences.json" if sentences else "04_edited.json"))
                      .read_text(encoding="utf-8"))["chapters"]


def test_saved_pro_edits_give_the_expected_candidates_and_no_episode_loss():
    """02:49Z v5 · 04:32Z v6 Pro 편집을 Pro 초안과 견준다 — 실제로 있었던 손실이 후보로 나오는지."""
    data, _, _, a = _fixture_analysis()
    o = json.loads(OUTLINE_C2.read_text(encoding="utf-8"))["outline"]
    omit = {f: x["reason"] for x in o["omit"] for f in x["facts"]}
    book = pipe.ledger(a)
    d = [json.loads((PRO_DRAFT / "03_ch-1.json").read_text(encoding="utf-8"))]
    pipe.expand_turns(d, book)
    protected = set(pipe.plan_core(o)) | pipe.must_keep(a)
    for name, sentences, want in [("v5_edit_pro_20261027T024949Z", False, {("f16", "fact_changed")}),
                                  ("v6_edit_pro_20261027T043228Z", True,
                                   {(f, "fact_dropped") for f in ("f16", "f26", "f33", "f62", "f65")})]:
        fin = _saved_edit(name, sentences)
        pipe.expand_turns(fin, book)
        trace = pipe.edit_trace(d, fin)
        cands = pipe.omission_candidates(d, fin, trace, a, data, {}, omit, protected)
        got = {(c["fact"], c["kind"]) for c in cands}
        assert want <= got, name
        if name.startswith("v5"):
            f16 = next(c for c in cands if c["fact"] == "f16")
            assert any("부정" in s for s in f16["signals"])                         # 턴 10 「저는 기억은 안 나요」
        ep = pipe.episode_findings(fin, o, a, {}, omit)
        assert all(f["rule"] == "episode_excluded" and f["severity"] == "review" for f in ep)   # 채택한 일화는 다 남았다
        # 목차 r2 가 통째로 뺀 일화 — 편집이 되살린 m5(부산 · 바다)는 빠지고 나머지는 검토 대상으로
        assert {f["unit"] for f in ep} == {"m6", "m8", "m9", "m11"}
