"""
자서전 5단계 파이프라인 (단위 8P) — 모델도 DB 도 부르지 않는다.

    .venv\\Scripts\\python -m pytest tests/test_memoir_pipeline.py -v

호출 자리에 가짜를 끼운다(Fake). 단계마다 정해 둔 응답을 돌려주고, 받은 시스템
지시 · 자료 메시지를 남긴다. 입력은 seed A 의 3회차(s-a · s-b · s-c, 말씀 6턴)다.

    턴 1 · 2 = s-a    턴 3 · 4 = s-b    턴 5 · 6 = s-c
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir, question                                  # noqa: E402
from app.session import memoir_pipeline as pipe                           # noqa: E402
from tools import memoir_pipeline as cli                                  # noqa: E402

SEED_A = json.loads((ROOT / "eval" / "memoir_seed_A.json").read_text(encoding="utf-8"))
SLEEP = object()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(pipe.settings()):
        if k.startswith("MEMOIR_PIPE_"):
            monkeypatch.delenv(k, raising=False)


def source():
    data, turn_map = pipe.build_input(cli.records_from_seed(SEED_A, ["s-a", "s-b", "s-c"]))
    return data, turn_map


def elder(data, turn):
    return next(u["elder"] for u in data["utterances"] if u["turn"] == turn)


def sent(text, turns, kind="supported"):
    return {"text": text, "kind": kind, "turns": turns}


def analysis_ok():
    return {
        "status": "ready",
        "events": [
            {"event_key": "e1", "summary": "앞 사건", "turns": [1, 2], "people": [],
             "time": {"text": "", "certainty": "unknown"}, "said_feelings": []},
            {"event_key": "e2", "summary": "뒤 사건", "turns": [5, 6], "people": [],
             "time": {"text": "", "certainty": "unknown"}, "said_feelings": []},
        ],
        "people": [],
        "themes": [{"theme": "배움", "supporting": [1], "counter": [], "strength": "clear", "note": ""}],
        "direction": {"theme": "배움", "reason": "", "neutral": False},
        "exclusions": [],
        "not_in_events": [{"turns": [3, 4], "reason": "시험용 — 사건으로 쓰지 않음"}],
        "unclear": [],
        "missing_context": [],
    }


def chapter_plan(key, events, focus, context=()):
    return {"chapter_key": key, "title": sent("편집 제목", [], "editorial"), "purpose": "목적",
            "grouping_reason": "같은 시기", "events": events, "focus_turns": list(focus),
            "context_turns": list(context), "weight": "main", "transition_in": "", "transition_out": ""}


def outline_ok(context1=()):
    return {"status": "ready",
            "book": {"title": sent("책 제목", [], "editorial"), "direction": "",
                     "structure_reason": "시기가 달라 두 장"},
            "chapters": [chapter_plan("ch-1", ["e1"], [1, 2], context1),
                         chapter_plan("ch-2", ["e2"], [5, 6])],
            "left_out": [],
            "missing_context": []}


def draft(key, turn):
    return {"chapter_key": key, "title": sent("장 제목", [], "editorial"),
            "paragraphs": [[sent("있었던 일이에요.", [turn]), sent("이어서 말해 볼게요.", [], "editorial")]],
            "review_notes": []}


def edited_ok():
    return {"title": sent("책 제목", [], "editorial"),
            "chapters": [{"chapter_key": "ch-1", "from_chapters": ["ch-1"],
                          "title": sent("장 제목", [], "editorial"),
                          "paragraphs": [[sent("있었던 일이에요.", [1])]]},
                         {"chapter_key": "ch-2", "from_chapters": ["ch-2"],
                          "title": sent("장 제목", [], "editorial"),
                          "paragraphs": [[sent("뒤의 일이에요.", [5])]]}],
            "structure_notes": ["두 장의 역할이 달라 그대로 둠"],
            "review_notes": [],
            "edit_notes": [{"location": "ch-2/p0/s0", "change": "다듬음", "reason": "반복"}]}


def verify_ok(verdict="pass", **kw):
    out = {"review_status": "completed", "verdict": verdict, "issues": [],
           "reviewed_locations": ["artifact", "title", "ch-1/p0/s0", "ch-2/p0/s0"],
           "missing_context": []}
    out.update(kw)
    return out


def script(**over):
    s = {"analysis": analysis_ok(), "outline": outline_ok(), "ch-1": draft("ch-1", 1),
         "ch-2": draft("ch-2", 5), "edit": edited_ok(), "verify": verify_ok()}
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


def go(fake, data=None, turn_map=None, recorder=None):
    if data is None:
        data, turn_map = source()
    return asyncio.run(pipe.run(data, turn_map, call=fake, recorder=recorder,
                                meta={"run_ref": "test", "seed": "memoir_seed_A.json",
                                      "aliases": ["s-a", "s-b", "s-c"]}))


def all_turns(obj):
    """결과 어디에 있든 turns · focus_turns · source_turns 의 번호를 모은다."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("turns", "focus_turns", "context_turns", "source_turns", "supporting", "counter"):
                found += v
            else:
                found += all_turns(v)
    elif isinstance(obj, list):
        for x in obj:
            found += all_turns(x)
    return found


# ---------------------------------------------------------------- 흐름


def test_t01_normal_run_calls_each_role_separately():
    fake = Fake(script())
    r = go(fake)
    assert fake.order == ["analysis", "outline", "ch-1", "ch-2", "edit", "verify"]
    assert r["calls"] == 2 + 4
    assert r["generation_state"] == "generated"
    assert r["pipeline_complete"] is True
    assert r["verification"]["state"] == "completed" and r["verification"]["verdict"] == "pass"
    assert r["human_review"] == "not_run"
    assert "is_final" not in r
    assert [c["chapter_key"] for c in r["chapters"]] == ["ch-1", "ch-2"]


def test_t02_each_call_has_its_own_role_prompt_and_common_rules():
    fake = Fake(script())
    go(fake)
    systems = [s.system for s in fake.specs]
    assert len(set(systems[:2] + systems[3:])) == 5          # ch-1 · ch-2 는 같은 장 지시
    common = pipe.common_rules()
    roles = {s: pipe.role_text(s) for s in pipe.STAGES}
    for spec in fake.specs:
        assert spec.system.startswith(common)
        inside = [s for s, t in roles.items() if t in spec.system]
        assert inside == [spec.stage]                         # 한 역할의 지시문만


def test_t03_source_text_goes_to_user_message_not_system():
    data, turn_map = source()
    fake = Fake(script())
    go(fake, data, turn_map)
    for u in data["utterances"]:
        for spec in fake.specs:
            assert u["elder"] not in spec.system
        assert u["elder"] in fake.specs[0].user


def test_t04_global_turns_are_never_renumbered():
    data, turn_map = source()
    want = copy.deepcopy(data["utterances"])
    fake = Fake(script())
    r = go(fake, data, turn_map)
    T = {u["turn"] for u in want}
    for spec in fake.specs:
        payload = json.loads(spec.user.split("\n\n", 1)[1])
        utts = payload["source"]["utterances"]
        if spec.stage == "chapter":
            assert all(u in want for u in utts)               # 고른 것이지 바꾼 것이 아니다
        else:
            assert utts == want
    assert data["utterances"] == want
    assert set(all_turns(r)) <= T


def test_t05_chapter_gets_only_its_own_source_and_context():
    data, turn_map = source()
    fake = Fake(script(outline=outline_ok(context1=[3])))
    go(fake, data, turn_map)
    ch1 = next(s for s in fake.specs if s.chapter_key == "ch-1")
    ch2 = next(s for s in fake.specs if s.chapter_key == "ch-2")
    payload = json.loads(ch1.user.split("\n\n", 1)[1])
    # focus 1 · 2, context 3, 같은 회차(s-b) 앞뒤 1턴 4
    assert payload["given_turns"] == [1, 2, 3, 4]
    assert [u["turn"] for u in payload["source"]["utterances"]] == [1, 2, 3, 4]
    for t in (1, 2, 3, 4):
        assert elder(data, t) in ch1.user
    for t in (5, 6):
        assert elder(data, t) not in ch1.user                 # 다른 장 원문은 없다
    for t in (1, 2):
        assert elder(data, t) not in ch2.user
    assert "confirmed_facts" not in payload["source"]["shared_state"]
    assert len(payload["outline"]["chapters"]) == 2           # 전체 목차는 준다


# ---------------------------------------------------------------- 단계 검사


def test_t06_analysis_with_unknown_turn_stops_before_outline():
    a = analysis_ok()
    a["events"][0]["turns"] = [1, 99]
    fake = Fake(script(analysis=a))
    r = go(fake)
    assert fake.order == ["analysis"]
    assert r["generation_state"] == "failed"
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("analysis", "reference")


@pytest.mark.parametrize("chapters, kind", [
    ([], "format"),
    ([chapter_plan(f"ch-{i}", ["e1"], [1]) for i in range(1, 7)], "chapter_limit"),
    ([chapter_plan("ch-1", ["e9"], [1])], "reference"),
    ([chapter_plan("ch-1", ["e1"], [])], "reference"),
])
def test_t07_outline_checks_stop_before_chapters(chapters, kind):
    o = outline_ok()
    o["chapters"] = chapters
    fake = Fake(script(outline=o))
    r = go(fake)
    assert fake.order == ["analysis", "outline"]
    assert r["generation_state"] == "failed"
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("outline", kind)


def test_t07b_five_chapters_is_allowed():
    o = outline_ok()
    o["chapters"] = [chapter_plan(f"ch-{i}", ["e1"], [1]) for i in range(1, 6)]
    o["left_out"] = [{"event_key": "e2", "reason": "시험용"}]
    rep = script(outline=o, edit=None)
    for i in range(1, 6):
        rep[f"ch-{i}"] = draft(f"ch-{i}", 1)
    rep["edit"] = {"title": sent("책", [], "editorial"),
                   "chapters": [{"chapter_key": f"ch-{i}", "from_chapters": [f"ch-{i}"],
                                 "title": sent("장", [], "editorial"),
                                 "paragraphs": [[sent("일이에요.", [1])]]} for i in range(1, 6)],
                   "structure_notes": ["시험"], "review_notes": [], "edit_notes": []}
    rep["verify"] = verify_ok(reviewed_locations=["artifact"])
    fake = Fake(rep)
    r = go(fake)
    assert r["calls"] == 5 + 4 and r["pipeline_complete"] is True


def test_t08_chapter_timeout_stops_everything_after_it(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMOIR_PIPE_CHAPTER_TIMEOUT", "0.05")
    o = outline_ok()
    o["chapters"].append(chapter_plan("ch-3", ["e2"], [6]))
    fake = Fake(script(outline=o, ch_2=SLEEP, ch_3=draft("ch-3", 6)))
    r = go(fake, recorder=pipe.Recorder(tmp_path))
    assert fake.order == ["analysis", "outline", "ch-1", "ch-2"]   # ch-3 · 편집 · 검증 없음
    assert r["generation_state"] == "partial"
    assert r["pipeline_complete"] is False
    assert (r["failure"]["stage"], r["failure"]["chapter_key"], r["failure"]["kind"]) == \
           ("chapter", "ch-2", "timeout")
    assert r["chapters"] == [] and r["title"] is None
    assert r["verification"]["state"] == "not_run"
    assert (tmp_path / "03_ch-1.json").exists()                     # 성공한 장은 진단용으로 남는다
    assert not (tmp_path / "04_edited.json").exists()
    steps = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["steps"]
    assert steps[-1]["error"]["kind"] == "timeout"


def test_t09_truncated_or_broken_chapter_is_partial():
    cut = pipe.Reply(json.dumps(draft("ch-1", 1), ensure_ascii=False), "FinishReason.MAX_TOKENS")
    r = go(Fake(script(ch_1=cut)))
    assert (r["generation_state"], r["failure"]["kind"]) == ("partial", "truncated")
    r = go(Fake(script(ch_1='{"chapter_key": "ch-1", "title": ')))
    assert (r["generation_state"], r["failure"]["kind"]) == ("partial", "format")


def test_t10_supported_needs_turns_editorial_does_not():
    d = draft("ch-1", 1)
    d["paragraphs"][0][0]["turns"] = []
    r = go(Fake(script(ch_1=d)))
    assert (r["generation_state"], r["failure"]["kind"]) == ("partial", "reference")

    r = go(Fake(script()))                                  # draft 에 editorial 빈 turns 가 있다
    assert r["pipeline_complete"] is True

    d = draft("ch-1", 5)                                    # ch-1 에 주지 않은 턴
    r = go(Fake(script(ch_1=d)))
    assert (r["failure"]["chapter_key"], r["failure"]["kind"]) == ("ch-1", "reference")
    assert "주지 않은" in r["failure"]["message"]


@pytest.mark.parametrize("mutate", [
    lambda e: e["chapters"].pop(),
    lambda e: e["chapters"].reverse(),
    lambda e: e["edit_notes"].append({"location": "ch-9/p0/s0", "change": "", "reason": ""}),
    lambda e: e["chapters"][0]["paragraphs"][0].append(sent("새 사실", [42])),
])
def test_t11_final_check_stops_before_verify(mutate):
    e = edited_ok()
    mutate(e)
    fake = Fake(script(edit=e))
    r = go(fake)
    assert fake.order[-1] == "edit"
    assert r["generation_state"] == "failed"
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("final_check", "reference")


def test_t12_verify_revise_is_recorded_not_rewritten():
    issue = {"location": "ch-1/p0/s0", "category": "fact", "severity": "blocker",
             "code": "unsupported_claim", "resolution": "auto_fix", "explanation": "x",
             "source_turns": [1], "fix_instruction": "y"}
    fake = Fake(script(verify=verify_ok("revise", issues=[issue])))
    r = go(fake)
    assert len(fake.specs) == 6                              # 다시 쓰지 않는다
    assert r["generation_state"] == "generated"
    assert r["pipeline_complete"] is True
    assert r["verification"]["verdict"] == "revise"
    assert r["human_review"] == "not_run"


@pytest.mark.parametrize("bad", [
    verify_ok(reviewed_locations=["artifact", "ch-7/p0/s0"]),
    verify_ok("revise", issues=[{"location": "nowhere", "category": "fact", "severity": "blocker",
                                 "code": "unsupported_claim", "resolution": "auto_fix",
                                 "explanation": "", "source_turns": [], "fix_instruction": ""}]),
    verify_ok(verdict=None),
    {"review_status": "completed"},
])
def test_t13_verify_shape_error_marks_verification_failed(bad):
    r = go(Fake(script(verify=bad)))
    assert r["generation_state"] == "generated"
    assert r["pipeline_complete"] is False
    assert r["verification"]["state"] == "failed"
    assert r["failure"]["stage"] == "verify"


def test_t14_insufficient_material_ends_after_one_call():
    a = {"status": "insufficient_material", "events": [], "people": [], "themes": [],
         "direction": {"theme": "", "reason": "", "neutral": True}, "exclusions": [],
         "not_in_events": [], "unclear": [], "missing_context": []}
    fake = Fake(script(analysis=a))
    r = go(fake)
    assert fake.order == ["analysis"]
    assert r["generation_state"] == "insufficient_material"
    assert r["failure"] is None and r["pipeline_complete"] is False


def test_t15_no_retry():
    fake = Fake(script(outline=RuntimeError("일시 오류")))
    r = go(fake)
    assert fake.order == ["analysis", "outline"]             # outline 은 한 번만
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("outline", "call")
    assert pipe.RETRIES == 0


def test_t16_missing_key_fails_without_network(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(question, "_CLIENT", None)
    data, turn_map = source()
    r = asyncio.run(pipe.run(data, turn_map, call=pipe.call_model))
    assert r["generation_state"] == "failed"
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("analysis", "call")
    assert "GEMINI_API_KEY" in r["failure"]["message"]


def test_t17_pipeline_and_service_settings_are_separate(monkeypatch):
    monkeypatch.delenv("MEMOIR_TEXT_MODEL", raising=False)
    monkeypatch.setenv("MEMOIR_PIPE_TEXT_MODEL", "pipe-model")
    monkeypatch.setenv("MEMOIR_PIPE_EDIT_TIMEOUT", "7")
    assert memoir.settings()["MEMOIR_TEXT_MODEL"] == memoir.DEFAULT_TEXT_MODEL
    assert memoir.settings()["MEMOIR_TEXT_TIMEOUT"] == memoir.DEFAULT_TEXT_TIMEOUT
    monkeypatch.setenv("MEMOIR_TEXT_MODEL", "service-model")
    monkeypatch.setenv("MEMOIR_TEXT_TIMEOUT", "3")
    s = pipe.settings()
    assert s["MEMOIR_PIPE_TEXT_MODEL"] == "pipe-model"
    assert s["MEMOIR_PIPE_EDIT_TIMEOUT"] == 7.0
    assert s["MEMOIR_PIPE_ANALYSIS_TIMEOUT"] == 60.0
    assert not any(k.startswith("MEMOIR_TEXT") for k in s)


def test_t17b_default_limits_match_design():
    s = pipe.settings()
    want = {"ANALYSIS": (60, 5000), "OUTLINE": (60, 4000), "CHAPTER": (90, 6000),
            "EDIT": (120, 8000), "VERIFY": (90, 5000)}
    for st, (sec, tok) in want.items():
        assert s[f"MEMOIR_PIPE_{st}_TIMEOUT"] == sec
        assert s[f"MEMOIR_PIPE_{st}_MAX_OUTPUT_TOKENS"] == tok
    assert s["MEMOIR_PIPE_TOTAL_TIMEOUT"] == 600 and s["retries"] == 0
    assert s["chapters"] == [1, 5]


# ---------------------------------------------------------------- 입력 · 기록


def _memoir_input_file(tmp_path, data, turn_map, **over):
    doc = {"set_id": "A", "aliases": ["s-a", "s-b", "s-c"], "session_ids": [],
           "input": data, "turn_map": turn_map}
    doc.update(over)
    p = tmp_path / "in.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def test_t18_rejects_bad_schema_or_disallowed_input(tmp_path):
    data, turn_map = source()
    got, tm, meta = cli.load_input(_memoir_input_file(tmp_path, data, turn_map))
    assert got == data and meta["set_id"] == "A"             # 합성 seed 에서 만든 입력은 받는다

    with pytest.raises(cli.InputRejected):
        cli.records_from_seed(SEED_A, ["s-a", "s-b"])         # 3~5개가 아니다
    with pytest.raises(cli.InputRejected):
        cli.records_from_seed(SEED_A, ["s-a", "s-b", "s-z"])  # seed 에 없는 alias
    bad_seed = dict(SEED_A, schema_version="other")
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(bad_seed, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(cli.InputRejected):
        cli._seed_doc(p)

    real = copy.deepcopy(data)
    real["utterances"][0]["elder"] = "seed 에 없는 실제 말씀"
    with pytest.raises(cli.InputRejected, match="합성 자료만"):
        cli.load_input(_memoir_input_file(tmp_path, real, turn_map))
    with pytest.raises(cli.InputRejected):
        cli.load_input(_memoir_input_file(tmp_path, data, turn_map, set_id="C"))
    renum = copy.deepcopy(data)
    renum["utterances"][0]["turn"] = 7
    with pytest.raises(cli.InputRejected):
        cli.load_input(_memoir_input_file(tmp_path, renum, turn_map))
    p = tmp_path / "x.json"
    p.write_text('{"input": {}}', encoding="utf-8")
    with pytest.raises(cli.InputRejected):
        cli.load_input(p)

    fake = Fake(script())
    r = go(fake, renum, turn_map)                            # run 도 깨진 입력이면 부르지 않는다
    assert fake.specs == []
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("input", "input")


def test_t18b_session_range_follows_server_constant_style(monkeypatch):
    """develop — MIN_SESSIONS, MAX_SESSIONS 상수."""
    monkeypatch.delattr(memoir, "max_sessions", raising=False)
    monkeypatch.setattr(memoir, "MAX_SESSIONS", 4, raising=False)
    assert cli.session_range() == (memoir.MIN_SESSIONS, 4)
    cli.records_from_seed(SEED_A, ["s-a", "s-b", "s-c", "s-d"])
    with pytest.raises(cli.InputRejected, match="3~4"):
        cli.records_from_seed(SEED_A, ["s-a", "s-b", "s-c", "s-d", "s-e"])


def test_t18c_session_range_follows_server_function_style(monkeypatch):
    """feature/theme-interview — MAX_SESSIONS 가 없고 max_sessions() (MEMOIR_MAX_SESSIONS)."""
    monkeypatch.delattr(memoir, "MAX_SESSIONS", raising=False)
    monkeypatch.setenv("MEMOIR_MAX_SESSIONS", "4")
    monkeypatch.setattr(memoir, "max_sessions",
                        lambda: int(__import__("os").environ["MEMOIR_MAX_SESSIONS"]), raising=False)
    assert cli.session_range() == (memoir.MIN_SESSIONS, 4)
    with pytest.raises(cli.InputRejected, match="3~4"):
        cli.records_from_seed(SEED_A, ["s-a", "s-b", "s-c", "s-d", "s-e"])
    monkeypatch.setenv("MEMOIR_MAX_SESSIONS", "5")
    assert len(cli.records_from_seed(SEED_A, ["s-a", "s-b", "s-c", "s-d", "s-e"])) == 5


def test_t18d_session_range_without_any_limit_refuses(monkeypatch):
    monkeypatch.delattr(memoir, "MAX_SESSIONS", raising=False)
    monkeypatch.delattr(memoir, "max_sessions", raising=False)
    with pytest.raises(cli.InputRejected, match="찾지 못했다"):
        cli.records_from_seed(SEED_A, ["s-a", "s-b", "s-c"])


def test_t18e_tools_use_only_names_both_servers_have():
    """통합 회귀 방지 — 실행기 · 파이프라인이 memoir 에서 쓰는 이름은 두 판에 모두 있는 것뿐이다."""
    import re
    shared = {"merge", "MemoirError", "DEFAULT_TEXT_MODEL", "MIN_SESSIONS", "settings"}
    for path in (ROOT / "tools" / "memoir_pipeline.py", ROOT / "app" / "session" / "memoir_pipeline.py"):
        used = set(re.findall(r"(?<![\w.])memoir\.(\w+)", path.read_text(encoding="utf-8")))
        assert used <= shared, f"{path.name}: {sorted(used - shared)}"


def test_t19_run_folder_has_stage_files_without_secrets_or_text(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-value-123")
    data, turn_map = source()
    r = go(Fake(script()), data, turn_map, pipe.Recorder(tmp_path))
    names = {p.name for p in tmp_path.iterdir()}
    for n in ("00_input.json", "01_analysis.json", "01_analysis.raw.txt", "02_outline.json",
              "03_ch-1.json", "03_ch-2.json", "04_edited.json", "05_verify.json",
              "result.json", "run.json", "r1_summary.md"):
        assert n in names
    for p in tmp_path.iterdir():
        assert "test-secret-value-123" not in p.read_text(encoding="utf-8")
    run_doc = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert [s["stage"] for s in run_doc["steps"]] == ["analysis", "outline", "chapter", "chapter",
                                                      "edit", "verify"]
    assert all(s["ok"] and s["ms"] >= 0 and s["usage"] for s in run_doc["steps"])
    assert run_doc["settings"]["retries"] == 0 and run_doc["prompts"]["verify"].startswith("sha256:")
    summary = (tmp_path / "r1_summary.md").read_text(encoding="utf-8")
    for u in data["utterances"]:
        assert u["elder"] not in summary                     # 원문 없음
    assert "있었던 일이에요" not in summary                  # 본문 없음
    assert "human_review" in summary and r["run_ref"] == "test"


def test_t20_prompts_load_and_no_private_helpers():
    for s in pipe.STAGES:
        assert pipe.role_text(s)
    common = pipe.common_rules()
    assert common.startswith("당신은") and "## 5." not in common   # §2 만, 다음 절은 싣지 않는다
    src = (ROOT / "app" / "session" / "memoir_pipeline.py").read_text(encoding="utf-8")
    assert "_sections" not in src and "memoir._ints" not in src and "roledoc" not in src
    assert "검증_v4" not in src                              # 검증은 새 판으로 부른다


def test_t21_total_time_budget_stops_before_next_call(monkeypatch):
    monkeypatch.setenv("MEMOIR_PIPE_TOTAL_TIMEOUT", "0")
    fake = Fake(script())
    r = go(fake)
    assert fake.specs == []
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("analysis", "budget")


# ---------------------------------------------------------------- v2 — 구성 · 빠짐 · 제외 · 지표


SEED_B = json.loads((ROOT / "eval" / "memoir_seed_B.json").read_text(encoding="utf-8"))


def source_b():
    """턴 1 · 2 = s-r1 · 3 · 4 · 5 = s-r2 (5 가 제외 요청) · 6 · 7 = s-r3 (6 이 정정)."""
    return pipe.build_input(cli.records_from_seed(SEED_B, ["s-r1", "s-r2", "s-r3"]))


def analysis_b():
    a = analysis_ok()
    a["events"] = [
        {"event_key": "e1", "summary": "딸 입학", "turns": [1, 2, 6, 7], "people": ["딸"],
         "time": {"text": "1996년", "certainty": "stated"}, "said_feelings": []},
        {"event_key": "e2", "summary": "꽃집 첫 손님", "turns": [3], "people": [],
         "time": {"text": "", "certainty": "unknown"}, "said_feelings": []},
    ]
    a["exclusions"] = [{"mode": "whole", "turns": [4], "requested_in": [5], "scope": "빌린 이야기와 금액"}]
    a["not_in_events"] = []
    return a


def analysis_b_partial():
    """턴 4 는 꽃집 준비(남김)와 빌린 사람 · 금액(뺌)이 한 문장에 있다 — 턴째로 버리지 않는다."""
    a = analysis_b()
    a["events"][1]["turns"] = [3, 4]
    a["exclusions"] = [{"mode": "partial", "turns": [4], "requested_in": [5], "scope": "빌린 사람과 금액"}]
    return a


def test_t22_analysis_must_cover_every_turn():
    a = analysis_ok()
    a["not_in_events"] = []                                   # 턴 3 · 4 가 어디에도 없다
    fake = Fake(script(analysis=a))
    r = go(fake)
    assert fake.order == ["analysis"]
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("analysis", "reference")
    assert "[3, 4]" in r["failure"]["message"]


def test_t23_theme_strength_and_direction_consistency():
    a = analysis_ok()
    a["themes"][0].pop("strength")
    r = go(Fake(script(analysis=a)))
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("analysis", "format")

    data, _ = source()
    a = analysis_ok()
    a["themes"][0]["strength"] = "weak"
    a["direction"] = {"theme": "가족", "reason": "", "neutral": True}   # 모순 — 경고로 남긴다
    status, warnings = pipe.check_analysis(a, {u["turn"] for u in data["utterances"]})
    assert status == "ready"
    assert any("neutral=true" in w for w in warnings)


def test_t24_exclusions_are_kept_out_of_events_chapters_and_body():
    data, turn_map = source_b()
    T = {u["turn"] for u in data["utterances"]}
    a = analysis_b()
    assert pipe.check_analysis(a, T)[0] == "ready"
    assert pipe.excluded_turns(a) == {4, 5}

    bad = copy.deepcopy(a)
    bad["events"][1]["turns"] = [3, 4]                       # 뺄 턴을 사건 근거로
    with pytest.raises(pipe.PipelineError, match="빼 달라고"):
        pipe.check_analysis(bad, T)

    # 장 입력 — 같은 회차 앞뒤 1턴 규칙으로도 4 · 5 가 끌려 들어오지 않는다
    ch = chapter_plan("ch-1", ["e2"], [3])
    src, given = pipe.chapter_source(data, a, ch)
    assert given == [3]
    assert all(u["turn"] not in (4, 5) for u in src["utterances"])

    # 목차가 뺄 턴을 쓰면 장 집필 전에 멈춘다
    o = {"status": "ready", "book": {"title": sent("책", [], "editorial"), "direction": "",
                                     "structure_reason": "한 장"},
         "chapters": [chapter_plan("ch-1", ["e1", "e2"], [1, 3], context=[4])],
         "left_out": [], "missing_context": []}
    with pytest.raises(pipe.PipelineError, match="빼 달라고"):
        pipe.check_outline(o, a, T)

    # 편집본이 뺄 턴을 근거로 달면 검증 전에 멈춘다
    o["chapters"][0]["context_turns"] = []
    e = {"title": sent("책", [], "editorial"),
         "chapters": [{"chapter_key": "ch-1", "from_chapters": ["ch-1"], "title": sent("장", [], "editorial"),
                       "paragraphs": [[sent("꽃집을 열었어요.", [3]), sent("돈을 빌렸어요.", [4])]]}],
         "structure_notes": ["한 장"], "review_notes": [], "edit_notes": []}
    with pytest.raises(pipe.PipelineError, match="빼 달라고"):
        pipe.check_final(e, o, T, pipe.excluded_turns(a))


def test_t25_outline_must_place_or_explain_every_event():
    o = outline_ok()
    o["chapters"] = [chapter_plan("ch-1", ["e1"], [1, 2])]   # e2 가 사라졌다
    r = go(Fake(script(outline=o)))
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("outline", "reference")
    assert "e2" in r["failure"]["message"]

    o["left_out"] = [{"event_key": "e2", "reason": "시험"}]
    data, _ = source()
    status, _ = pipe.check_outline(o, analysis_ok(), {u["turn"] for u in data["utterances"]})
    assert status == "ready"

    o = outline_ok()
    o["chapters"][0].pop("grouping_reason")
    r = go(Fake(script(outline=o)))
    assert (r["failure"]["stage"], r["failure"]["kind"]) == ("outline", "format")


def test_t26_one_chapter_memoir_is_allowed_and_split_is_flagged():
    o = outline_ok()
    o["chapters"] = [chapter_plan("ch-1", ["e1", "e2"], [1, 2, 5, 6])]
    o["book"]["structure_reason"] = "자료가 적어 한 장"
    e = edited_ok()
    e["chapters"] = [{"chapter_key": "ch-1", "from_chapters": ["ch-1"], "title": sent("장", [], "editorial"),
                      "paragraphs": [[sent("있었던 일이에요.", [1, 5])]]}]
    e["edit_notes"] = []
    fake = Fake(script(outline=o, ch_1=draft("ch-1", 1), edit=e,
                       verify=verify_ok(reviewed_locations=["artifact", "ch-1/p0/s0"])))
    r = go(fake)
    assert r["calls"] == 1 + 4 and r["pipeline_complete"] is True

    data, _ = source()
    _, warnings = pipe.check_outline(outline_ok(), analysis_ok(), {u["turn"] for u in data["utterances"]})
    assert any("사건 하나마다 장 하나" in w for w in warnings)


def test_t27_edit_may_merge_chapters_but_not_split_or_reorder():
    data, _ = source()
    T = {u["turn"] for u in data["utterances"]}
    merged = edited_ok()
    merged["chapters"] = [{"chapter_key": "ch-1", "from_chapters": ["ch-1", "ch-2"],
                           "title": sent("장", [], "editorial"),
                           "paragraphs": [[sent("앞의 일이에요.", [1]), sent("뒤의 일이에요.", [5])]]}]
    merged["edit_notes"] = [{"location": "ch-1", "change": "두 장을 합침", "reason": "장마다 두 문장뿐"}]
    pipe.check_final(merged, outline_ok(), T)                 # 합치기는 된다

    fake = Fake(script(edit=merged, verify=verify_ok(reviewed_locations=["artifact", "ch-1/p0/s1"])))
    r = go(fake)
    assert r["metrics"]["merged_chapters"] == 1 and r["metrics"]["outline_chapters"] == 2
    assert r["metrics"]["chapters"] == 1

    for bad in (["ch-2", "ch-1"], ["ch-1"], ["ch-1", "ch-2", "ch-3"]):
        e = copy.deepcopy(merged)
        e["chapters"][0]["from_chapters"] = bad
        with pytest.raises(pipe.PipelineError, match="from_chapters"):
            pipe.check_final(e, outline_ok(), T)
    e = copy.deepcopy(merged)
    e["chapters"][0]["chapter_key"] = "ch-2"
    with pytest.raises(pipe.PipelineError, match="ch-1 부터"):
        pipe.check_final(e, outline_ok(), T)
    e = copy.deepcopy(merged)
    e["structure_notes"] = []
    with pytest.raises(pipe.PipelineError, match="structure_notes"):
        pipe.check_final(e, outline_ok(), T)


def _issue(**kw):
    x = {"location": "ch-1/p0/s0", "category": "composition", "severity": "warning",
         "code": "summary_listing", "resolution": "accept_limit", "explanation": "",
         "source_turns": [], "fix_instruction": ""}
    x.update(kw)
    return x


def test_t28_verify_separates_fact_and_composition():
    r = go(Fake(script(verify=verify_ok("pass", issues=[_issue()]))))
    assert r["pipeline_complete"] is True                     # 구성 warning · accept_limit 은 pass 와 함께 간다
    assert r["verification"]["issues"][0]["category"] == "composition"

    for bad in (_issue(code="unsupported_claim"),              # 사실 code 를 구성으로
                _issue(category="fact", code="over_split"),   # 구성 code 를 사실로
                _issue(category="style"),
                _issue(resolution="rewrite")):
        r = go(Fake(script(verify=verify_ok("revise", issues=[bad]))))
        assert r["verification"]["state"] == "failed", bad

    r = go(Fake(script(verify=verify_ok("pass", issues=[_issue(severity="blocker")]))))
    assert r["verification"]["state"] == "failed"             # blocker 인데 pass


def test_t29_verify_gets_plan_without_event_detail():
    fake = Fake(script())
    go(fake)
    v = next(s for s in fake.specs if s.stage == "verify")
    payload = json.loads(v.user.split("\n\n", 1)[1])
    plan = payload["plan"]
    assert [c["chapter_key"] for c in plan["chapters"]] == ["ch-1", "ch-2"]
    assert plan["themes"] == [{"theme": "배움", "strength": "clear"}]
    assert "events" not in json.dumps(plan) and "turns" not in json.dumps(plan)


def test_t30_text_metrics_show_verbatim_copy():
    data, _ = source()
    copied = [{"chapter_key": "ch-1", "paragraphs": [[sent(u["elder"], [u["turn"]]) for u in data["utterances"]]]}]
    m = pipe.text_metrics(copied, data)
    assert m["verbatim_ratio"] == 1.0 and m["editorial_sentences"] == 0
    woven = [{"chapter_key": "ch-1", "paragraphs": [[
        sent("이 이야기는 일과 가족에 관한 기억이에요.", [], "editorial"),
        sent("광주 인쇄소 첫 월급으로 어머니께 빨간 목도리를 사 드렸어요.", [1, 2])]]}]
    m = pipe.text_metrics(woven, data)
    assert m["verbatim_ratio"] == 0.0 and m["multi_turn_sentences"] == 1 and m["editorial_sentences"] == 1


def test_t31_prompt_v2_in_use_and_v1_kept_as_baseline():
    assert pipe.PROMPT_VERSION == "v2" and all(f.endswith("_v2.md") for f in pipe.ROLE_FILES.values())
    for f in pipe.ROLE_FILES.values():
        assert (pipe.ROLE_DIR / f.replace("_v2", "_v1")).exists()  # 기준선(fe94baf) 판을 지우지 않는다
    assert pipe.settings()["prompt_version"] == "v2"


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


def test_t34_partial_exclusion_keeps_turn_but_drops_memo_and_warns_stages():
    data, turn_map = source_b()
    T = {u["turn"] for u in data["utterances"]}
    a = analysis_b_partial()
    assert pipe.check_analysis(a, T)[0] == "ready"            # partial 턴은 사건 근거로 써도 된다
    assert pipe.excluded_turns(a) == {5}                      # 턴째로 막는 것은 요청 턴뿐

    ch = chapter_plan("ch-1", ["e2"], [3, 4])
    src, given = pipe.chapter_source(data, a, ch)
    assert given == [3, 4]                                    # 턴 4 는 남는다 — 번호 그대로
    assert [u["turn"] for u in src["utterances"]] == [3, 4]
    assert all(x["turn"] != 4 for x in src["shared_state"]["facts_found"])   # 메모는 뺀다
    notes = pipe.exclusion_notices(a, set(given))
    assert notes == [{"mode": "partial", "turns": [4], "requested_in": [5], "scope": "빌린 사람과 금액"}]
    msg = pipe.chapter_message(src, given, outline_ok(), ch, [], notes)
    assert '"exclusions"' in msg and "삼백만" not in json.dumps(notes, ensure_ascii=False)


def test_t35_outline_and_edit_sources_drop_excluded_turns_and_memos():
    data, _ = source_b()
    for a, gone_turns in ((analysis_b(), {4, 5}), (analysis_b_partial(), {5})):
        src = pipe.stage_source(data, a)
        assert {u["turn"] for u in src["utterances"]} == {1, 2, 3, 4, 6, 7} - gone_turns
        assert "confirmed_facts" not in src["shared_state"]
        assert all(x["turn"] not in (4, 5) for x in src["shared_state"]["facts_found"])
        assert all(u in data["utterances"] for u in src["utterances"])   # 고른 것이지 고친 것이 아니다
        for msg in (pipe.outline_message(data, a),
                    pipe.edit_message(data, outline_ok(), [], a)):
            payload = json.loads(msg.split("\n\n", 1)[1])
            sent_turns = {u["turn"] for u in payload["source"]["utterances"]}
            assert sent_turns == {1, 2, 3, 4, 6, 7} - gone_turns
            assert "빼 주세요" not in msg                    # 요청 턴은 넘어가지 않는다
            assert "빌림" not in json.dumps(payload["source"], ensure_ascii=False)   # 메모로도 새지 않는다
            # whole 이면 턴 4 원문도 안 간다. partial 이면 턴 4 원문은 가고(남길 내용) 알림이 붙는다
            assert ("삼백만" in json.dumps(payload["source"], ensure_ascii=False)) == (4 not in gone_turns)
    # 제외가 없으면 원자료 그대로
    a0, _ = source()
    assert pipe.stage_source(a0, analysis_ok()) is a0


def test_t36_verify_keeps_full_source_with_exclusion_notice():
    data, _ = source_b()
    a = analysis_b()
    msg = pipe.verify_message(data, edited_ok(), {u["turn"] for u in data["utterances"]},
                              {}, pipe.exclusion_notices(a))
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
    a = analysis_b_partial()
    a["exclusions"] = [bad]
    with pytest.raises(pipe.PipelineError) as e:
        pipe.check_analysis(a, {u["turn"] for u in data["utterances"]})
    assert e.value.kind == kind


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
            s.connect(("203.0.113.1", 443))                  # 문서용 주소 — 실제로 나가지 않는다
    finally:
        s.close()
    assert len(conftest.BLOCKED) == before + 2
    del conftest.BLOCKED[before:]                            # 일부러 낸 시도는 세지 않는다


def test_t32_r1_summary_has_metrics_and_categories(tmp_path):
    r = go(Fake(script(verify=verify_ok("pass", issues=[_issue()]))), recorder=pipe.Recorder(tmp_path))
    s = (tmp_path / "r1_summary.md").read_text(encoding="utf-8")
    assert "비교 지표" in s and "원문 그대로인 문장" in s and "composition" in s and "지시문 판: v2" in s
    assert r["prompt_version"] == "v2"
