"""
세 문체(수필체 · 문학체 · 소설체)가 다섯 단계를 거치는지 — 모델을 부르지 않는다 (분석 · 목차 · 편집 · 검증과 문체 집필을 모두 흉내 낸다).

    python -m pytest -p no:cacheprovider -q tests/test_memoir_style_pipeline.py

여기서 통과하는 것은 **연결과 계약**이다 — 실제 모델이 문체를 지키며 편집하는지, 검증이 무엇을 잡는지는 실모델 실행으로만 알 수 있다.
"""

from __future__ import annotations

import asyncio
import functools
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_memoir_pipeline as base                        # noqa: E402 — 같은 폴더의 기존 테스트. 도우미만 빌려 쓴다

from app.session import memoir, memoir_novel, memoir_styled
from app.session import memoir_pipeline as pipe
from app.session import memoir_style_stage as stage3

sent = base.sent
STYLES = ("essay", "literary", "novel")
NOVEL = {"ch-1": "첫 월급을 받던 날이었다.\n“어머니, 이거 받으세요.”\n나는 목도리를 내밀었다.\n\n“아이고, 네가 무슨 돈이 있다고.”\n어머니는 한참 말이 없었다.",
         "ch-2": "딸이 입학하던 해였다.\n“엄마, 다녀올게.”\n교문 앞에서 나는 오래 서 있었다.\n“그래, 잘 다녀와.”\n가슴이 뭉클했다."}


def styled_out(cid, lines, marks):
    return {"essay_id": cid, "title": "제목 미확정", "paragraphs": lines,
            "facts": [{"id": f, "where": w} for f, w in marks],
            "fiction": [{"kind": "가상 대화", "where": "어머니, 이거", "why": "원문에 없는 말"}]}


STYLED = {"ch-1": styled_out("c1", ["첫 월급을 받던 날이 아직 선하다. 봉투는 얇았다.", "목도리 하나를 사 들고 집으로 갔다."],
                             [("f1", "첫 월급을 받던 날이 아직 선하다"), ("f2", "목도리 하나를 사 들고"), ("f9", "봉투는 얇았다")]),
          "ch-2": styled_out("c2", ["딸이 입학하던 해였다.\n교문 앞에 오래 서 있었다.", "가슴이 뭉클했다."],
                             [("f3", "딸이 입학하던 해였다"), ("f4", "가슴이 뭉클했다")])}


def edited(ch1, ch2):
    out = base.edited_ok()
    for ch, paras in zip(out["chapters"], (ch1, ch2)):
        ch["paragraphs"] = paras
    return out


KEPT = edited([[sent("첫 월급을 받던 날이었다.", ["f1"])], [sent("“어머니, 이거 받으세요.”", [], "editorial")],
               [sent("나는 목도리를 내밀었다.", ["f2"])], [sent("“아이고, 네가 무슨 돈이 있다고.”", [], "editorial")],
               [sent("어머니는 한참 말이 없었다.", [], "editorial")]],
              [[sent("딸이 입학하던 해였다.", ["f3"])], [sent("“엄마, 다녀올게.”", [], "editorial")],
               [sent("교문 앞에서 나는 오래 서 있었다.", [], "editorial")], [sent("“그래, 잘 다녀와.”", [], "editorial")],
               [sent("가슴이 뭉클했다.", ["f4"])]])
FLAT = edited([[sent("첫 월급으로 목도리를 샀다.", ["f1", "f2"])]], [[sent("딸이 입학해 뭉클했다.", ["f3", "f4"])]])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in list(pipe.settings()):
        if k.startswith("MEMOIR_PIPE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MEMOIR_FAIL_INJECT", raising=False)


class Stages(base.Fake):
    """분석 · 목차 · 편집 · 검증의 흉내 — 부른 차례를 order 에 적는다 (문체 집필의 흉내와 같은 목록)."""

    def __init__(self, replies, order):
        super().__init__(replies)
        self.log = order

    async def __call__(self, spec):
        self.log.append(spec.chapter_key and f"{spec.stage}:{spec.chapter_key}" or spec.stage)
        return await super().__call__(spec)


class Writer:
    """문체 집필(Claude)의 흉내. replies[장 키] — 글 · dict(JSON) · 예외 · (글, 기록)."""

    def __init__(self, replies, order):
        self.replies, self.log, self.specs, self.closed = replies, order, [], False

    async def __call__(self, spec):
        self.log.append(f"write({spec.style}):{spec.chapter_key}")
        self.specs.append(spec)
        v = self.replies[spec.chapter_key]
        if v is base.SLEEP:
            await asyncio.sleep(5)
        if isinstance(v, BaseException):
            raise v
        if isinstance(v, tuple):
            return v
        return (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)), {"stop": "end_turn", "model": spec.model, "input": 10, "output": 20}

    async def close(self):
        self.closed = True


def run(style, stages=None, writer=None, **script):
    order: list[str] = []
    fake = Stages(base.script(**{"edit": KEPT, **script}), order)
    w = Writer({**(NOVEL if style == "novel" else STYLED), **(writer or {})}, order)
    data, turn_map = base.source()
    res = asyncio.run(pipe.run(data, turn_map, call=fake, style=style, style_call=w))
    return res, order, fake, w, data


# ---------------------------------------------------------------- 1. 문체마다 다섯 단계가 차례로 돈다

@pytest.mark.parametrize("style", STYLES)
def test_1_each_style_runs_analysis_outline_write_edit_verify(style):
    res, order, fake, w, data = run(style)
    assert order[:2] == ["analysis", "outline"] and order[-2:] == ["edit", "verify"]
    assert sorted(order[2:-2]) == [f"write({style}):ch-1", f"write({style}):ch-2"]          # 장은 함께 쓴다 — 차례는 정해져 있지 않다
    assert res["generation_state"] == pipe.GENERATED and res["pipeline_complete"] is True
    assert res["verification"]["state"] == "completed" and res["style"] == style
    assert res["calls"] == 6 and w.closed
    assert [s.stage for s in fake.specs] == ["analysis", "outline", "edit", "verify"]        # 공통 장 집필 지시문은 부르지 않았다


def test_1_novel_writer_gets_the_untouched_prompt_with_this_chapters_source_only():
    res, order, fake, w, data = run("novel")
    spec = next(s for s in w.specs if s.chapter_key == "ch-1")
    template, sha = memoir_novel.template()
    assert sha.startswith(memoir_novel.PROMPT_SHA256)
    src = "\n\n".join(base.elder(data, t).strip() for t in (1, 2))                             # 목차가 ch-1 에 놓은 사실 f1 · f2 의 원문
    assert spec.system is None and spec.schema is None and spec.user == template.replace(memoir_novel.SLOT, src)
    assert base.elder(data, 5).strip() not in spec.user                                        # 다른 장의 원문은 가지 않는다
    assert (spec.model, spec.max_tokens, spec.effort) == (memoir_novel.DEFAULT_MODEL, memoir_novel.DEFAULT_MAX_TOKENS, memoir_novel.DEFAULT_EFFORT)


@pytest.mark.parametrize("style", ["essay", "literary"])
def test_1_styled_writer_gets_the_untouched_prompt_and_the_common_ledger(style):
    res, order, fake, w, data = run(style)
    spec = next(s for s in w.specs if s.chapter_key == "ch-1")
    system, sha = memoir_styled.prompt(style)
    assert spec.system == system and sha.startswith(memoir_styled.STYLES[style]["sha"])
    assert spec.schema == memoir_styled.schema(memoir_styled.STYLES[style]["schema"])
    assert (spec.model, spec.max_tokens) == (memoir_styled.STYLES[style]["model"], memoir_styled.STYLES[style]["max_tokens"])
    assert "- f1 [self/stated] 첫 월급" in spec.user and "- f2 [self/stated] 목도리를 사 드려 뿌듯했음" in spec.user     # 공통 분석의 사실 원장
    assert "f3" not in spec.user and base.elder(data, 1).strip() in spec.user and base.elder(data, 5).strip() not in spec.user


def test_1_edit_and_verify_keep_their_prompts_and_get_the_style_note_only_for_styles():
    res, order, fake, w, data = run("novel")
    by = {s.stage: s for s in fake.specs}
    assert by["edit"].system == pipe.prompt("edit") + stage3.edit_note("novel")
    assert by["verify"].system == pipe.prompt("verify") + stage3.verify_note("novel")
    assert by["analysis"].system == pipe.prompt("analysis") and by["outline"].system == pipe.prompt("outline")
    drafts = fake.payload("edit")["drafts"]
    assert [p[0]["text"] for p in drafts[0]["paragraphs"]] == [ln for ln in NOVEL["ch-1"].splitlines() if ln.strip()]
    payload = fake.payload("verify")
    assert payload["source"] == data and payload["facts"] == base.analysis_ok()["facts"]      # 원문 · 사실 원장과 대조한다
    assert payload["candidate"]["chapters"][0]["paragraphs"][1][0]["text"] == "“어머니, 이거 받으세요.”"
    # 구어체 — 지시문이 글자까지 그대로다
    plain = base.Fake(base.script())
    base.go(plain)
    assert {s.stage: s.system for s in plain.specs} == {k: pipe.prompt(k) for k in pipe.STAGES}


# ---------------------------------------------------------------- 근거를 지어 달지 않는다

def test_novel_draft_has_no_fact_marks_and_one_line_is_one_paragraph():
    res, order, fake, w, data = run("novel")
    d = fake.payload("edit")["drafts"][0]
    assert all(len(p) == 1 and p[0]["kind"] == "editorial" and p[0]["facts"] == [] and p[0]["turns"] == [] for p in d["paragraphs"])
    checks = fake.payload("edit")["checks"]
    assert not [c for c in checks if c["rule"] in ("must_keep_missing", "core_missing", "style_mix")]


def test_styled_draft_marks_only_what_the_writer_marked_and_drops_unknown_ids():
    res, order, fake, w, data = run("essay")
    d = fake.payload("edit")["drafts"][0]
    got = [(s["text"], s["kind"], s["facts"], s["turns"]) for p in d["paragraphs"] for s in p]
    assert got == [("첫 월급을 받던 날이 아직 선하다.", "supported", ["f1"], [1]), ("봉투는 얇았다.", "editorial", [], []),
                   ("목도리 하나를 사 들고 집으로 갔다.", "supported", ["f2"], [2])]              # f9 는 이 장에 준 사실이 아니다 — 버린다
    assert res["metrics"]["style"]["drafts"] == {"marked": 4, "unmarked": 2} and res["metrics"]["style"]["adaptations"] == 2


def test_bundle_carries_only_what_the_common_analysis_has():
    a, o = base.analysis_ok(), base.outline_ok()
    a["people"] = [{"name": "어머니", "relation": "모"}]
    a["facts"][1].update(source="heard", keep=True)
    book = stage3.bundle_book(a, o, {"ch-1": {1: "첫 월급을 받았지 “이거 받으세요” 했어", 2: "어머니가 좋아하셨대"}, "ch-2": {5: "딸", 6: "뭉클"}})
    s1, s2 = book["stories"][0], book["stories"][1]
    assert s1["facts"] == [{"id": "f1", "source": "self", "certainty": "stated", "text": "첫 월급"}] and s1["title_hint"] == "첫 월급"
    assert s1["quotes"] == ["“이거 받으세요”"] and s1["time"] == ["1979년"]
    assert s2["heard"] == ["목도리를 사 드려 뿌듯했음"] and s2["must_keep"] == ["목도리를 사 드려 뿌듯했음"] and s2["people"] == ["어머니(모)"]
    for s in book["stories"]:
        assert s["emotion_notes"] == [] and s["reflections_now"] == [] and s["places"] == []      # 공통 분석에 없는 칸 — 지어내지 않는다
    assert [c["id"] for c in book["chapters"]] == ["c1", "c2"] and book["chapters"][0]["stories"] == [1, 2]
    assert book["chapters"][0]["direction"] == "일" and book["chapters"][0]["emotion"] == stage3._NOT_GIVEN


# ---------------------------------------------------------------- 2. 편집 뒤에도 문체가 남는가 — 코드가 재는 만큼만

def test_2_kept_edit_keeps_dialogue_and_has_no_warning():
    res, *_ = run("novel", edit=KEPT)
    st = res["metrics"]["style"]
    assert st["warnings"] == [] and st["ratio"]["sentences_unchanged"] == 1.0 and st["draft"]["dialogue"] == st["final"]["dialogue"] == 4
    assert [p[0]["text"] for p in res["chapters"][0]["paragraphs"]] == [ln for ln in NOVEL["ch-1"].splitlines() if ln.strip()]


def test_2_flattened_edit_is_reported_not_hidden():
    res, *_ = run("novel", edit=FLAT)
    st = res["metrics"]["style"]
    assert res["generation_state"] == pipe.GENERATED                                          # 생성은 됐다 — 문체가 지워졌다는 신호를 함께 낸다
    assert st["ratio"]["chars"] < stage3.CHARS_KEPT_MIN and st["final"]["dialogue"] == 0
    assert len(st["warnings"]) == 3 and any("대화" in x for x in st["warnings"])
    out = memoir.pipeline_result(res, ["a"], "novel")
    assert out["verification"]["style"]["warnings"] == st["warnings"]                          # 응답까지 간다


# ---------------------------------------------------------------- 3. 검증 결과

def issue(**kw):
    return {"location": "ch-1/p1/s0", "category": "fact", "severity": "blocker", "code": "unsupported_claim",
            "resolution": "auto_fix", "explanation": "원문에 없는 말", "source_turns": [1], "fix_instruction": "지운다", **kw}


def test_3_clean_manuscript_is_passed():
    res, *_ = run("literary")
    out = memoir.pipeline_result(res, ["a"], "literary")
    v = out["verification"]
    assert (v["state"], v["outcome"], v["verdict"], v["issues"]) == ("completed", "passed", "pass", []) and out["to_confirm"] == []


def test_3_unsupported_fact_becomes_an_issue_not_a_user_question():
    res, *_ = run("novel", verify=base.verify_ok("revise", issues=[issue()]))
    out = memoir.pipeline_result(res, ["a"], "novel")
    v = out["verification"]
    assert v["outcome"] == "issues_found" and v["counts"] == {"issues": 1, "blockers": 1, "needs_user": 0, "composition": 0}
    assert v["issues"][0]["sentence"] == "“어머니, 이거 받으세요.”" and v["issues"][0]["chapter"] == 1 and v["issues"][0]["source_turns"] == [1]
    assert "fix_instruction" not in v["issues"][0] and out["to_confirm"] == []


def test_3_unclear_transcript_goes_to_to_confirm():
    ask = issue(code="source_mismatch", resolution="ask_user", explanation="「면도 무소」 의 뜻을 확정할 수 없다", source_turns=[2])
    res, *_ = run("essay", verify=base.verify_ok("ask_user", issues=[issue(), ask]))
    out = memoir.pipeline_result(res, ["a"], "essay")
    assert out["verification"]["outcome"] == "needs_confirmation" and out["verification"]["counts"]["needs_user"] == 1
    assert out["to_confirm"] == [{"issue": "「면도 무소」 의 뜻을 확정할 수 없다", "turns": [2]}]       # 확인이 필요한 것만 — issues 전부가 아니다


def test_3_completed_is_not_the_same_as_no_problem():
    res, *_ = run("novel")
    v = memoir.pipeline_result(res, ["a"], "novel")["verification"]
    assert v["state"] == "completed" and v["outcome"] == "passed" and v["code"]["state"] == v["code_gate"] != "blocked"
    blocked = {**res, "code_gate": "blocked", "code_findings": [
        {"rule": "stale_correction", "severity": "block", "location": "ch-1/p0/s0", "detail": "정정 전 값이 다시 나왔다"},
        {"rule": "fact_token", "severity": "fix", "location": "ch-1/p1/s0", "detail": "x"}]}
    v = memoir.pipeline_result(blocked, ["a"], "novel")["verification"]
    assert v["state"] == "completed" and v["verdict"] == "pass" and v["outcome"] == "issues_found"      # 검증은 통과시켰지만 코드가 막았다
    assert v["code"] == {"state": "blocked", "counts": {"block": 1, "fix": 1, "info": 0, "review": 0},
                         "blocks": [{"rule": "stale_correction", "location": "ch-1/p0/s0", "detail": "정정 전 값이 다시 나왔다"}]}
    noisy = {**res, "code_gate": "attention", "code_findings": [{"rule": "fact_token", "severity": "fix", "location": "ch-1/p1/s0", "detail": "x"}]}
    assert memoir.pipeline_result(noisy, ["a"], "novel")["verification"]["outcome"] == "passed"       # 참고 신호는 outcome 을 바꾸지 않는다


@pytest.mark.parametrize("bad", [RuntimeError("boom"), "JSON 이 아닌 글", base.verify_ok(review_status="needs_context", verdict=None, quality=[])])
def test_3_failed_or_unfinished_verification_is_never_completed(bad):
    res, order, *_ = run("novel", verify=bad)
    assert order[-1] == "verify" and res["generation_state"] == pipe.GENERATED and res["pipeline_complete"] is False
    v = memoir.pipeline_result(res, ["a"], "novel")["verification"]
    assert v["state"] != "completed" and v["outcome"] in ("failed", "incomplete") and v["outcome"] != "passed"


# ---------------------------------------------------------------- 4. 진입 — 세 문체는 예전 전용 경로로 가지 않는다

@pytest.mark.parametrize("style", STYLES)
def test_4_service_path_runs_five_stages_and_returns_verification(monkeypatch, style):
    order: list[str] = []
    fake = Stages(base.script(edit=KEPT, verify=base.verify_ok("revise", issues=[issue()])), order)
    w = Writer(NOVEL if style == "novel" else STYLED, order)
    monkeypatch.setattr(pipe, "run", functools.partial(pipe.run, call=fake, style_call=w))

    async def never(*a, **k):
        raise AssertionError("예전의 문체 전용 경로를 불렀다")
    monkeypatch.setattr(memoir_novel, "run", never)
    monkeypatch.setattr(memoir_styled, "run", never)
    recs = base.cli.records_from_seed(base.SEED_A, ["s-a", "s-b", "s-c"])
    seen = []
    out = asyncio.run(memoir.generate(recs, ["s-a", "s-b", "s-c"], "anyone", style, lambda *a: seen.append(a[0])))
    assert order[:2] == ["analysis", "outline"] and order[-2:] == ["edit", "verify"] and len(order) == 6
    assert out["status"] == memoir.READY and out["style"] == style and len(out["chapters"]) == 2
    assert out["verification"]["state"] == "completed" and out["verification"]["outcome"] == "issues_found"
    assert out["chapters"][0]["paragraphs"][1]["sentences"][0] == {"text": "“어머니, 이거 받으세요.”", "turns": []}
    assert out["chapters"][0]["paragraphs"][0]["sentences"][0]["turns"] == [1]                 # 편집이 단 사실의 원문 턴
    assert [x for x in seen if x in ("outline", "chapter", "edit", "verify")][:1] == ["outline"] and "verify" in seen


def test_4_spoken_does_not_take_the_style_argument(monkeypatch):
    got = {}

    async def fake_run(data, turn_map, **kw):
        got.update(kw)
        return {"generation_state": pipe.INSUFFICIENT, "calls": 1}
    monkeypatch.setattr(pipe, "run", fake_run)
    monkeypatch.setenv("MEMOIR_ENGINE", "pipeline")
    monkeypatch.setenv("MEMOIR_PIPELINE_USERS", "*")
    recs = base.cli.records_from_seed(base.SEED_A, ["s-a", "s-b", "s-c"])
    asyncio.run(memoir.generate(recs, ["s-a"], "u", "spoken"))
    assert "style" not in got and got["variant"] == "v7"
    asyncio.run(memoir.generate(recs, ["s-a"], "u", "novel"))
    assert got["style"] == "novel"


# ---------------------------------------------------------------- 5. 단계를 건너뛰지 않는다

def test_5_analysis_failure_stops_before_writing():
    res, order, fake, w, _ = run("novel", analysis="JSON 이 아닌 글")
    assert order == ["analysis"] and res["generation_state"] == pipe.FAILED and res["verification"]["state"] == "not_run"
    with pytest.raises(memoir.GenerationFailed):
        memoir.pipeline_result(res, ["a"], "novel")


def test_5_outline_failure_does_not_write():
    res, order, fake, w, _ = run("essay", outline="JSON 이 아닌 글")
    assert order == ["analysis", "outline"] and w.specs == [] and res["generation_state"] == pipe.FAILED


@pytest.mark.parametrize("bad,kind", [(RuntimeError("boom"), "call"), (("잘린 글", {"stop": "max_tokens"}), "truncated"),
                                      (("", {"stop": "end_turn"}), "format"), (("거절", {"stop": "refusal"}), "format")])
def test_5_writing_failure_stops_before_edit_and_verify(bad, kind):
    res, order, fake, w, _ = run("novel", writer={"ch-2": bad})
    assert "edit" not in order and "verify" not in order
    assert res["generation_state"] == pipe.PARTIAL and res["failure"]["kind"] == kind and res["chapters"] == []
    assert res["verification"]["state"] == "not_run" and res["pipeline_complete"] is False
    with pytest.raises(memoir.Incomplete):
        memoir.pipeline_result(res, ["a"], "novel")


def test_5_styled_output_that_is_not_json_or_has_no_text_is_a_failure():
    for bad in ("JSON 이 아닌 글", {"essay_id": "c1", "paragraphs": [], "facts": []}):
        res, order, *_ = run("literary", writer={"ch-1": bad})
        assert res["generation_state"] == pipe.PARTIAL and res["failure"]["kind"] == "format" and "edit" not in order


def test_5_writer_timeout_is_a_failure(monkeypatch):
    monkeypatch.setenv("MEMOIR_NOVEL_TIMEOUT", "0.05")
    res, order, *_ = run("novel", writer={"ch-1": base.SLEEP})
    assert res["generation_state"] == pipe.PARTIAL and res["failure"]["kind"] == "timeout" and "edit" not in order


def test_5_edit_failure_stops_before_verify():
    res, order, *_ = run("novel", edit="JSON 이 아닌 글")
    assert order[-1] == "edit" and res["generation_state"] == pipe.FAILED and res["verification"]["state"] == "not_run"
    bad = json.loads(json.dumps(KEPT))
    bad["chapters"][0]["paragraphs"][0][0]["facts"] = ["f99"]                                   # 원장에 없는 사실 id — 최종 근거검사에서 멈춘다
    res, order, *_ = run("novel", edit=bad)
    assert order[-1] == "edit" and res["generation_state"] == pipe.FAILED and res["failure"]["kind"] == "reference"


def test_5_without_a_writer_key_nothing_is_called():
    order: list[str] = []
    fake = Stages(base.script(), order)
    data, turn_map = base.source()
    res = asyncio.run(pipe.run(data, turn_map, call=fake, style="novel"))
    assert order == [] and res["calls"] == 0 and res["generation_state"] == pipe.FAILED and res["failure"]["stage"] == "input"


def test_5_style_is_refused_outside_the_plain_five_stages():
    data, turn_map = base.source()
    w = Writer(NOVEL, [])
    for kw in ({"style": "cyworld"}, {"style": "novel", "variant": "integrated"}):
        res = asyncio.run(pipe.run(data, turn_map, call=base.Fake(base.script()), style_call=w, **kw))
        assert res["generation_state"] == pipe.FAILED and res["failure"]["stage"] == "input" and res["calls"] == 0
