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
        "threads": [],
        "people": [],
        "themes": [{"theme": "배움", "supporting": [1], "counter": [], "strength": "clear", "note": ""}],
        "direction": {"theme": "배움", "reason": "", "neutral": False},
        "exclusions": [],
        "not_in_events": [{"turns": [3, 4], "reason": "시험용 — 사건으로 쓰지 않음"}],
        "unclear": [],
        "missing_context": [],
    }


def chapter_plan(key, events, focus, context=()):
    return {"chapter_key": key, "title": sent("편집 제목", [], "editorial"), "role": "역할",
            "purpose": "목적", "grouping_reason": "같은 시기", "threads": [],
            "events": events, "focus_turns": list(focus),
            "context_turns": list(context), "weight": "main", "transition_in": "", "transition_out": ""}


def outline_ok(context1=()):
    return {"status": "ready",
            "book": {"title": sent("책 제목", [], "editorial"), "direction": "",
                     "structure_reason": "시기가 달라 두 장", "theme_use": "배움으로 연다",
                     "opening_turns": [], "closing_turns": [6]},
            "chapters": [chapter_plan("ch-1", ["e1"], [1, 2], context1),
                         chapter_plan("ch-2", ["e2"], [5, 6])],
            "left_out": [],
            "missing_context": []}


def draft(key, turn):
    return {"chapter_key": key, "title": sent("장 제목", [], "editorial"),
            "paragraphs": [[sent("있었던 일이다.", [turn]), sent("이어서 적어 본다.", [], "editorial")]],
            "review_notes": []}


def edited_ok():
    return {"title": sent("책 제목", [], "editorial"),
            "chapters": [{"chapter_key": "ch-1", "from_chapters": ["ch-1"],
                          "title": sent("장 제목", [], "editorial"),
                          "paragraphs": [[sent("있었던 일이다.", [1])]]},
                         {"chapter_key": "ch-2", "from_chapters": ["ch-2"],
                          "title": sent("장 제목", [], "editorial"),
                          "paragraphs": [[sent("뒤의 일이다.", [5])]]}],
            "structure_notes": ["두 장의 역할이 달라 그대로 둠"],
            "checks_resolution": [],
            "review_notes": [],
            "edit_notes": [{"action": "rewrite", "before": ["ch-2/p0/s0"], "after": ["ch-2/p0/s0"],
                            "change": "다듬음", "reason": "반복"}]}


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
                   "structure_notes": ["시험"], "checks_resolution": [], "review_notes": [], "edit_notes": []}
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
    lambda e: e["edit_notes"].append({"action": "rewrite", "before": ["ch-9/p0/s0"],
                                      "after": ["ch-1/p0/s0"], "change": "", "reason": ""}),
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
         "threads": [], "not_in_events": [], "unclear": [], "missing_context": []}
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
    assert "있었던 일이다" not in summary                  # 본문 없음
    assert "human_review" in summary and r["run_ref"] == "test"


def test_t20_prompts_load_and_no_private_helpers():
    for s in pipe.STAGES:
        assert pipe.role_text(s)
    common = pipe.common_rules()
    assert common.startswith("당신은") and "## 5." not in common   # §2 만, 다음 절은 싣지 않는다
    src = (ROOT / "app" / "session" / "memoir_pipeline.py").read_text(encoding="utf-8")
    assert "_sections" not in src and "memoir._ints" not in src and "roledoc" not in src
    import re
    assert not re.search(r"(?<!5_)검증_v4\.md", src)     # 서비스 검증_v4.md 는 부르지 않는다


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
                                     "structure_reason": "한 장", "closing_turns": [7]},
         "chapters": [chapter_plan("ch-1", ["e1", "e2"], [1, 3], context=[4])],
         "left_out": [], "missing_context": []}
    with pytest.raises(pipe.PipelineError, match="빼 달라고"):
        pipe.check_outline(o, a, T)

    # 편집본이 뺄 턴을 근거로 달면 검증 전에 멈춘다
    o["chapters"][0]["context_turns"] = []
    e = {"title": sent("책", [], "editorial"),
         "chapters": [{"chapter_key": "ch-1", "from_chapters": ["ch-1"], "title": sent("장", [], "editorial"),
                       "paragraphs": [[sent("꽃집을 열었어요.", [3]), sent("돈을 빌렸어요.", [4])]]}],
         "structure_notes": ["한 장"], "checks_resolution": [], "review_notes": [], "edit_notes": []}
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
                      "paragraphs": [[sent("있었던 일이다.", [1, 5])]]}]
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
                           "paragraphs": [[sent("앞의 일이다.", [1]), sent("뒤의 일이다.", [5])]]}]
    merged["edit_notes"] = [{"action": "merge", "before": ["ch-1", "ch-2"], "after": ["ch-1"],
                             "change": "두 장을 합침", "reason": "장마다 두 문장뿐"}]
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


def test_t31_prompt_v4_in_use_and_earlier_versions_kept():
    assert pipe.PROMPT_VERSION == "v4" and all(f.endswith("_v4.md") for f in pipe.ROLE_FILES.values())
    for f in pipe.ROLE_FILES.values():
        for old in ("_v1", "_v2", "_v3"):                   # 실행 기록(fe94baf · 9231a70 · d3deb2b) 판을 지우지 않는다
            assert (pipe.ROLE_DIR / f.replace("_v4", old)).exists()
    assert pipe.settings()["prompt_version"] == "v4"


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
    assert "비교 지표" in s and "원문 그대로인 문장" in s and "composition" in s and "지시문 판: v4" in s
    assert r["prompt_version"] == "v4"


# ---------------------------------------------------------------- v3 — 편집 메모 · 분할 · 메모 혼입 · 장 목적


def _v2_failure_case():
    """
    v2 실측(20261026T064453Z) 재현 — 장 초안 ch-3 은 4문장(여닫는 editorial 2), 편집이 그 둘을 지웠다.
    편집본 ch-3 은 2문장이라 초안의 ch-3/p0/s2 · s3 는 편집본에 없다.
    """
    o = outline_ok()
    o["chapters"].append(chapter_plan("ch-3", ["e2"], [6]))
    o["chapters"][1]["events"] = []                         # e2 는 ch-3 에
    o["chapters"][1]["focus_turns"] = [5]
    ch3 = {"chapter_key": "ch-3", "title": sent("장", [], "editorial"),
           "paragraphs": [[sent("이어지는 기억이에요.", [], "editorial"), sent("뒤의 일이다.", [5]),
                           sent("마음이 뭉클했어요.", [6]), sent("이야기를 닫아요.", [], "editorial")]],
           "review_notes": []}
    drafts = [draft("ch-1", 1), draft("ch-2", 5), ch3]
    e = edited_ok()
    e["chapters"].append({"chapter_key": "ch-3", "from_chapters": ["ch-3"], "title": sent("장", [], "editorial"),
                          "paragraphs": [[sent("뒤의 일이다.", [5]), sent("마음이 뭉클했어요.", [6])]]})
    e["edit_notes"] = [
        {"action": "delete", "before": ["ch-3/p0/s0"], "after": [], "change": "도입 삭제", "reason": "안내문"},
        {"action": "delete", "before": ["ch-3/p0/s3"], "after": [], "change": "마무리 삭제", "reason": "안내문"},
    ]
    return o, drafts, e


def test_t39_deleted_sentence_is_referenced_by_draft_location():
    data, _ = source()
    T = {u["turn"] for u in data["utterances"]}
    o, drafts, e = _v2_failure_case()
    pipe.check_final(e, o, T, frozenset(), drafts)            # 지운 문장은 편집본에 없는 것이 정상

    old = copy.deepcopy(e)                                    # v2 모양 — 지운 문장을 편집 뒤 위치로
    old["edit_notes"] = [{"location": "ch-3/p0/s2", "change": "마무리 삭제", "reason": ""}]
    with pytest.raises(pipe.PipelineError) as err:
        pipe.check_final(old, o, T, frozenset(), drafts)
    assert err.value.kind == "format"

    for bad, kind in ((["ch-3/p0/s9"], "reference"),          # 초안에도 없는 위치는 계속 실패
                      (["ch-4/p0/s0"], "reference")):
        x = copy.deepcopy(e)
        x["edit_notes"][1]["before"] = bad
        with pytest.raises(pipe.PipelineError) as err:
            pipe.check_final(x, o, T, frozenset(), drafts)
        assert err.value.kind == kind
    x = copy.deepcopy(e)
    x["edit_notes"][1]["after"] = ["ch-3/p0/s2"]             # delete 에 after 를 달면 형식 오류
    with pytest.raises(pipe.PipelineError, match="after"):
        pipe.check_final(x, o, T, frozenset(), drafts)

    # 사실 · 출처 검사는 그대로 — 편집본 문장의 근거가 범위 밖이면 여전히 실패
    x = copy.deepcopy(e)
    x["chapters"][2]["paragraphs"][0][0]["turns"] = [99]
    with pytest.raises(pipe.PipelineError, match="99"):
        pipe.check_final(x, o, T, frozenset(), drafts)


@pytest.mark.parametrize("note, ok", [
    ({"action": "merge", "before": ["ch-1/p0/s0", "ch-1/p0/s1"], "after": ["ch-1/p0/s0"]}, True),
    ({"action": "merge", "before": ["ch-1", "ch-2"], "after": ["ch-1"]}, True),       # 장 합치기
    ({"action": "merge", "before": ["ch-1/p0/s0"], "after": ["ch-1/p0/s0"]}, False),  # before 하나
    ({"action": "merge", "before": ["ch-1/p0/s0", "ch-1/p0/s1"], "after": []}, False),
    ({"action": "rewrite", "before": ["ch-1/p0/s0"], "after": ["ch-1/p0/s0"]}, True),
    ({"action": "rewrite", "before": ["ch-1/p0/s0"], "after": ["ch-1/p3/s0"]}, False),  # 편집본에 없는 위치
    ({"action": "rewrite", "before": ["ch-1/p0/s5"], "after": ["ch-1/p0/s0"]}, False),  # 초안에 없는 위치
    ({"action": "rewrite", "before": [], "after": ["ch-1/p0/s0"]}, False),
    ({"action": "add", "before": [], "after": ["ch-2/p0/s0"]}, True),
    ({"action": "add", "before": ["ch-2/p0/s0"], "after": ["ch-2/p0/s0"]}, False),
    ({"action": "move", "before": ["ch-1/p0/s0"], "after": ["ch-1/p0/s0"]}, False),
    ({"action": "rewrite", "before": ["title"], "after": ["title"]}, True),             # 책 제목
])
def test_t40_merge_rewrite_add_locations(note, ok):
    data, _ = source()
    T = {u["turn"] for u in data["utterances"]}
    drafts = [draft("ch-1", 1), draft("ch-2", 5)]
    e = edited_ok()
    if note["after"] == ["ch-1"] and note["before"] == ["ch-1", "ch-2"]:
        e["chapters"] = [{"chapter_key": "ch-1", "from_chapters": ["ch-1", "ch-2"], "title": sent("장", [], "editorial"),
                          "paragraphs": [[sent("앞의 일이다.", [1]), sent("뒤의 일이다.", [5])]]}]
    e["edit_notes"] = [{**note, "change": "", "reason": ""}]
    if ok:
        pipe.check_final(e, outline_ok(), T, frozenset(), drafts)
    else:
        with pytest.raises(pipe.PipelineError):
            pipe.check_final(e, outline_ok(), T, frozenset(), drafts)


def test_t41_chapter_split_is_flagged_not_hardcoded():
    data, _ = source()
    T = {u["turn"] for u in data["utterances"]}
    one = outline_ok()
    one["chapters"] = [chapter_plan("ch-1", ["e1", "e2"], [1, 2, 5, 6])]
    assert pipe.check_outline(one, analysis_ok(), T) == ("ready", [])   # 한 장 회상록 — 경고 없음

    split = outline_ok()                                      # 사건마다 한 장 — 막지 않고 경고
    status, warnings = pipe.check_outline(split, analysis_ok(), T)
    assert status == "ready" and any("사건 하나마다" in w for w in warnings)

    fake = Fake(script())                                     # 경고는 검증 역할의 plan.checks 로 간다
    go(fake)
    v = next(s for s in fake.specs if s.stage == "verify")
    checks = json.loads(v.user.split("\n\n", 1)[1])["plan"]["checks"]
    assert any("사건 하나마다" in c for c in checks)

    r = go(Fake(script()))                                    # 나눠도 실행은 된다 — 하드코딩으로 합치지 않는다
    assert r["pipeline_complete"] is True and r["metrics"]["chapters"] == 2


def test_t42_outline_memo_must_not_leak_into_body():
    data, _ = source()
    T = {u["turn"] for u in data["utterances"]}
    D = [draft("ch-1", 1), draft("ch-2", 5)]
    o = outline_ok()
    o["chapters"][1]["transition_in"] = "어머니와의 기억에 이어 동생과 함께 나눈 발걸음을 따라갑니다."
    memo = "어머니와의 기억에 이어 동생과 함께 나눈 발걸음을 따라갑니다."
    # 장 초안에 메모가 그대로 들어가면 장 단계는 경고, 코드 판정은 block — 편집에 고칠 곳으로 간다
    d = draft("ch-2", 5)
    d["paragraphs"][0].insert(0, sent(memo, [], "editorial"))
    w = pipe.check_chapter(d, o["chapters"][1], [5, 6], {5, 6}, pipe.outline_memos(o))
    assert any("목차 메모" in x for x in w)
    rules = {(f["rule"], f["severity"]) for f in pipe.code_findings([draft("ch-1", 1), d], o)}
    assert ("memo_leak", "block") in rules and ("style_mix", "fix") in rules   # 합니다체도 함께

    # v4 — 편집본에 남아도 파이프라인을 멈추지 않고 code_gate 를 막는다 (검증은 그대로 돈다)
    e = edited_ok()
    e["chapters"][1]["paragraphs"][0].insert(0, sent(memo, [], "editorial"))
    pipe.check_final(e, o, T, frozenset(), D)
    fake = Fake(script(outline=o, edit=e,
                       verify=verify_ok(reviewed_locations=["artifact", "ch-2/p0/s0"])))
    r = go(fake)
    assert fake.order[-1] == "verify" and r["model_verdict"] == "pass"
    assert r["code_gate"] == "blocked" and r["overall"] == "blocked_by_code"

    # 안내문 말투만 있으면(메모 복사는 아님) fix
    e = edited_ok()
    e["chapters"][0]["paragraphs"][0].append(sent("이 장에서는 첫 월급 이야기를 보여 준다.", [], "editorial"))
    assert any(f["rule"] == "meta_text" and f["severity"] == "fix"
               for f in pipe.code_findings(e["chapters"], outline_ok()))

    # 원문을 옮긴 supported 문장은 메모 혼입으로 보지 않는다
    o2 = outline_ok()
    o2["chapters"][0]["purpose"] = data["utterances"][0]["elder"]
    e = edited_ok()
    e["chapters"][0]["paragraphs"][0][0] = sent(data["utterances"][0]["elder"], [1])
    pipe.check_final(e, o2, T, frozenset(), D)
    assert not any(f["rule"] == "memo_leak" for f in pipe.code_findings(e["chapters"], o2))


SEED_C_PATH = ROOT / "eval" / "memoir_seed_C.json"


def test_t44_seed_c_uses_pipeline_only_check_without_touching_team_tool():
    from tools import seed_sessions as seed
    doc = json.loads(SEED_C_PATH.read_text(encoding="utf-8"))
    assert seed.SET_IDS == ("A", "B")                         # 팀 도구는 그대로
    assert seed.check_seed(doc) == ["set_id 는 A · B 중 하나여야 한다 (지금 'C')"]
    assert cli.check_pipeline_seed(doc) == []
    assert cli.check_pipeline_seed(SEED_A) == [] and cli.check_pipeline_seed(SEED_B) == []

    for bad, why in ((dict(doc, synthetic=False), "synthetic"),
                     (dict(doc, set_id="D"), "set_id"),
                     (dict(doc, schema_version="x"), "schema_version")):
        assert any(why in m for m in cli.check_pipeline_seed(bad)), why
    renamed = copy.deepcopy(doc)
    renamed["sessions"][0]["title"] = "[A] 수선집 하루"
    assert any("[C] " in m for m in cli.check_pipeline_seed(renamed))
    broken = copy.deepcopy(doc)
    broken["sessions"][2]["turns"][1]["idx"] = 9                # 팀 검사의 나머지 규칙도 그대로 돈다
    assert any("idx" in m for m in cli.check_pipeline_seed(broken))


def test_t45_seed_c_merges_into_39_global_turns_without_loss():
    doc = cli._seed_doc(SEED_C_PATH)
    aliases = [s["alias"] for s in doc["sessions"]]
    assert [len(s["turns"]) for s in doc["sessions"]] == [8, 10, 6, 9, 6]
    data, turn_map = pipe.build_input(cli.records_from_seed(doc, aliases))
    T = pipe.check_input(data, turn_map)
    assert sorted(T) == list(range(1, 40))
    want = [t["answer"].strip() for s in sorted(doc["sessions"], key=lambda s: s["recorded_order"])
            for t in s["turns"]]
    assert [u["elder"] for u in data["utterances"]] == want   # 빠짐 · 바뀜 없음
    starts = {m["session_id"]: m["global_turn"] for m in reversed(turn_map)}
    assert starts == {"c1": 1, "c2": 9, "c3": 19, "c4": 25, "c5": 34}
    assert all(m["turn"] == m["global_turn"] - starts[m["session_id"]] + 1 for m in turn_map)
    # 회차를 넘는 정정은 merge 가 하지 않는다 — c3 의 1986 메모가 남고, 정정은 c4 원문(턴 25)에 있다
    assert any("1986" in f for f in data["shared_state"]["confirmed_facts"])
    assert "85년" in data["utterances"][24]["elder"]


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


def test_t46_seed_c_input_file_is_accepted_and_eval_doc_is_not_model_input(tmp_path):
    doc = cli._seed_doc(SEED_C_PATH)
    data, turn_map = pipe.build_input(cli.records_from_seed(doc, [s["alias"] for s in doc["sessions"]]))
    p = _memoir_input_file(tmp_path, data, turn_map, set_id="C", aliases=["c1", "c2", "c3", "c4", "c5"])
    got, _, meta = cli.load_input(p)
    assert got == data and meta["seed"] == "memoir_seed_C.json"
    # 평가 기준 문서는 지시문 폴더 밖에 있고, 어느 단계의 시스템 지시에도 들어가지 않는다
    for stage in pipe.STAGES:
        assert "seed-C-evaluation" not in pipe.prompt(stage)
    assert not list(pipe.ROLE_DIR.glob("*evaluation*"))


def test_t43_unsupported_purpose_is_not_caught_by_code():
    """
    한계 기록 — 목차 purpose 의 "입학식 날"(원문은 "입학해서")은 턴 번호가 맞으면 코드가 못 잡는다.
    뜻의 근거는 검증 역할 · 사람 검수가 본다. 대신 purpose 는 검증의 plan 으로 넘어간다.
    """
    data, _ = source()
    T = {u["turn"] for u in data["utterances"]}
    o = outline_ok()
    o["chapters"][1]["purpose"] = "1996년 딸의 초등학교 입학식 날 학교에 데려다준 기억"
    assert pipe.check_outline(o, analysis_ok(), T)[0] == "ready"
    fake = Fake(script(outline=o))
    go(fake)
    v = next(s for s in fake.specs if s.stage == "verify")
    plan = json.loads(v.user.split("\n\n", 1)[1])["plan"]
    assert "입학식" in plan["chapters"][1]["purpose"]
    assert "입학식" in pipe.role_text("outline")               # 목차 지시문에 예와 함께 규칙이 있다
    for stage in ("analysis", "chapter", "verify"):           # 다른 단계에는 같은 규칙을 일반 문장으로
        assert "더 구체적인" in pipe.role_text(stage)


# ---------------------------------------------------------------- v4 — 수필체 · 사건과 끈 · 장 입력 · 코드 판정


def test_v4_essay_ending_and_style_findings():
    ok = ["그해 봄에 가게를 열었다.", "나는 그 소리가 싫었다.", "편지에는 '기름 자주 쳐라'라고만 쓰여 있었다.",
          "어머니는 '밥은 먹었니?' 하고 물었다.", "'그건 내가 했다 싶어요.'"]
    bad = ["가게를 열었어요.", "가게를 열었습니다.", "공장 다닐 때는 그 소리가 싫었는데.", "가끔요."]
    assert all(pipe._essay_ending(x) for x in ok), [x for x in ok if not pipe._essay_ending(x)]
    assert not any(pipe._essay_ending(x) for x in bad)
    ch = {"chapter_key": "ch-1", "title": sent("제목", [], "editorial"),
          "paragraphs": [[sent(x, [1]) for x in ok + bad]]}
    f = pipe.code_findings([ch], outline_ok())
    style = sorted(int(x["location"].split("/s")[1]) for x in f if x["rule"] == "style_mix")
    assert style == [5, 6, 7, 8]                              # 인용 안의 해요체는 문체 혼합이 아니다
    assert {x["severity"] for x in f if x["rule"] == "style_mix"} == {"fix"}


def test_v4_stop_phrase_blocks_but_answer_trace_is_fix():
    ch = {"chapter_key": "ch-1", "title": sent("제목", [], "editorial"), "paragraphs": [[
        sent("남편은 2015년에 세상을 떠났다. 그 얘긴… 오늘은 그만할게요.", [1]),
        sent("그 얘기는 길어서 나중에 할게요.", [1]),
        sent("아니요, 남편은 시내버스를 몰았다.", [1]),
        sent("가끔요. 손주 바지 단 정도.", [1]),
        sent("남편은 2015년에 세상을 떠났다.", [1])]]}
    f = {(x["location"], x["rule"], x["severity"]) for x in pipe.code_findings([ch], outline_ok())}
    assert ("ch-1/p0/s0", "stop_phrase", "block") in f and ("ch-1/p0/s1", "stop_phrase", "block") in f
    assert ("ch-1/p0/s2", "answer_trace", "fix") in f and ("ch-1/p0/s3", "answer_trace", "fix") in f
    assert not any(loc == "ch-1/p0/s4" for loc, *_ in f)     # 같은 발언 속 사실만 쓰면 문제없다


def test_v4_repeat_turn_is_fix_and_intended_recall_is_accepted():
    chs = [{"chapter_key": "ch-1", "title": sent("가", [], "editorial"), "paragraphs": [[sent("그 일이 있었다.", [1])]]},
           {"chapter_key": "ch-2", "title": sent("나", [], "editorial"), "paragraphs": [[sent("그 일을 다시 떠올렸다.", [1])]]}]
    draft_checks = pipe.code_findings(chs, outline_ok())
    rep = [c for c in draft_checks if c["rule"] == "repeat_turn"]
    assert len(rep) == 1 and rep[0]["severity"] == "fix" and rep[0]["turn"] == 1
    assert pipe.code_gate(draft_checks, {}, draft_checks)["state"] == "attention"   # 처리 안 함 → 남음
    kept = {rep[0]["id"]: {"check_id": rep[0]["id"], "status": "kept", "reason": "일부러 다시 떠올리는 회상"}}
    assert pipe.code_gate(draft_checks, kept, draft_checks)["state"] == "pass"       # 의도한 회상은 막지 않는다
    style = pipe.code_findings([{"chapter_key": "ch-1", "title": sent("가", [], "editorial"),
                                 "paragraphs": [[sent("있었어요.", [1])]]}], outline_ok())
    sk = {style[0]["id"]: {"check_id": style[0]["id"], "status": "kept", "reason": "그냥"}}
    assert pipe.code_gate(style, sk, style)["state"] == "attention"                  # 문체는 kept 로 넘어가지 않는다


@pytest.mark.parametrize("gate, verdict, vstate, overall", [
    ("blocked", "pass", "completed", "blocked_by_code"),       # 모델 pass 여도 막힌다
    ("attention", "pass", "completed", "needs_revision"),
    ("pass", "revise", "completed", "needs_revision"),
    ("pass", None, "failed", "needs_revision"),
    ("pass", "pass", "completed", "awaiting_human"),           # 코드 · 모델 통과 — 그래도 사람 검수 대기
])
def test_v4_overall_state_never_approves_without_human(gate, verdict, vstate, overall):
    v = {"state": vstate, "verdict": verdict}
    assert pipe.overall_state("generated", {"state": gate}, v, "not_run") == overall
    assert pipe.overall_state("partial", {"state": "pass"}, v, "not_run") == "not_generated"
    if gate != "blocked":
        assert pipe.overall_state("generated", {"state": gate}, v, "passed") == "approved"


def test_v4_run_result_has_four_states_and_stop_phrase_blocks():
    r = go(Fake(script()))
    assert (r["code_gate"], r["model_verdict"], r["human_review"], r["overall"]) == \
           ("pass", "pass", "not_run", "awaiting_human")

    e = edited_ok()
    e["chapters"][1]["paragraphs"][0].append(sent("그 얘긴… 오늘은 그만할게요.", [5]))
    fake = Fake(script(edit=e, verify=verify_ok(reviewed_locations=["artifact"])))
    r = go(fake)
    assert r["pipeline_complete"] is True and r["model_verdict"] == "pass"
    assert r["code_gate"] == "blocked" and r["overall"] == "blocked_by_code"
    assert any(f["rule"] == "stop_phrase" for f in r["code_findings"])


def test_v4_edit_receives_draft_checks_and_resolutions_are_recorded(tmp_path):
    d1 = draft("ch-1", 1)
    d1["paragraphs"][0].append(sent("가끔요. 그랬어요.", [1]))      # answer_trace · style_mix
    e = edited_ok()
    fake = Fake(script(ch_1=d1, edit=e))
    r = go(fake, recorder=pipe.Recorder(tmp_path))
    edit_spec = next(s for s in fake.specs if s.stage == "edit")
    checks = json.loads(edit_spec.user.split("\n\n", 1)[1])["checks"]
    assert {c["rule"] for c in checks} >= {"answer_trace", "style_mix"}
    assert all(c["location"].startswith("ch-1/") for c in checks)
    gate = json.loads((tmp_path / "04_code_gate.json").read_text(encoding="utf-8"))
    assert gate["draft_checks"] == len(checks) and gate["state"] == "pass"   # 편집본에는 남지 않음
    steps = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["steps"]
    assert any("처리 결과가 없는 경고" in w for w in steps[-2]["warnings"])     # 편집이 처리 결과를 안 적음
    assert (tmp_path / "03_checks.json").exists()

    e2 = copy.deepcopy(e)
    e2["checks_resolution"] = [{"check_id": c["id"], "status": "resolved", "reason": ""} for c in checks]
    got, warn = pipe.check_resolutions(e2, checks)
    assert len(got) == len(checks) and warn == []
    e2["checks_resolution"][0] = {"check_id": checks[0]["id"], "status": "kept", "reason": ""}
    assert any("이유가 없다" in w for w in pipe.check_resolutions(e2, checks)[1])


def test_v4_chapter_input_excludes_other_chapters_turns_and_uses_packet_order():
    # v3 실측 재현 — Seed C c4 의 26 · 27(편지)과 28(부산)이 같은 회차에서 붙어 있다.
    # ch-x 는 26 · 27, ch-y 는 28 을 근거로 쓴다. 앞뒤 1턴 규칙만으로는 서로의 턴을 끌어온다
    data, _ = _seed_c_input()
    ev = lambda k, ts: {"event_key": k, "summary": "", "turns": ts, "people": [],
                        "time": {"text": "", "certainty": "unknown"}, "said_feelings": []}
    a = {"events": [ev("e-letter", [26, 27]), ev("e-busan", [28])], "exclusions": [], "threads": []}
    x = chapter_plan("ch-1", ["e-letter"], [26, 27])
    y = chapter_plan("ch-2", ["e-busan"], [28])
    o = {"book": outline_ok()["book"], "chapters": [x, y]}
    _, old_x = pipe.chapter_source(data, a, x)                # 목차를 안 주면 옛 방식 — 이웃이 그대로
    _, old_y = pipe.chapter_source(data, a, y)
    assert 28 in old_x and 27 in old_y                        # v3 의 중복 원인
    _, gx = pipe.chapter_source(data, a, x, o)
    _, gy = pipe.chapter_source(data, a, y, o)
    assert 28 not in gx and 27 not in gy                      # 다른 장의 턴은 이웃으로 오지 않는다
    assert 25 in gx and 29 in gy                              # 다른 장이 쓰지 않는 이웃은 그대로 문맥
    x["context_turns"] = [28]                                 # 일부러 쓰려면 목차가 적는다
    _, gx = pipe.chapter_source(data, a, x, o)
    assert 28 in gx

    # 사건 묶음 순서 — 목차가 e2 를 e1 앞에 두면 원문도 그 순서로
    data, _ = source()
    a2, o2 = analysis_ok(), outline_ok()
    one = chapter_plan("ch-1", ["e2", "e1"], [1, 2, 5, 6])
    o2["chapters"] = [one]
    src, given = pipe.chapter_source(data, a2, one, o2)
    assert [u["turn"] for u in src["utterances"]][:4] == [5, 6, 1, 2]
    assert all(u in data["utterances"] for u in src["utterances"])   # 번호 · 글 그대로
    assert pipe.event_packets(a2, one, given) == [{"event_key": "e2", "turns": [5, 6]},
                                                  {"event_key": "e1", "turns": [1, 2]}]
    msg = json.loads(pipe.chapter_message(src, given, o2, one, [], None,
                                          pipe.event_packets(a2, one, given), []).split("\n\n", 1)[1])
    assert msg["event_packets"][0]["event_key"] == "e2" and "threads" in msg


def test_v4_analysis_threads_and_multi_time_warning():
    data, _ = source()
    T = {u["turn"] for u in data["utterances"]}
    a = analysis_ok()
    a["threads"] = [{"thread_key": "t1", "name": "가게", "kind": "place", "events": ["e1", "e2"], "turns": [1, 5]}]
    assert pipe.check_analysis(a, T)[0] == "ready"
    for bad, kind in ((dict(a["threads"][0], events=["e9"]), "reference"),
                      (dict(a["threads"][0], kind="symbol"), "format"),
                      (dict(a["threads"][0], turns=[]), "reference")):
        x = copy.deepcopy(a)
        x["threads"] = [bad]
        with pytest.raises(pipe.PipelineError) as e:
            pipe.check_analysis(x, T)
        assert e.value.kind == kind
    x = copy.deepcopy(a)
    x.pop("threads")
    with pytest.raises(pipe.PipelineError):
        pipe.check_analysis(x, T)
    x = copy.deepcopy(a)
    x["events"][0]["time"] = {"text": "77년쯤, 2003년", "certainty": "approx"}   # v3 실측 e9
    _, w = pipe.check_analysis(x, T)
    assert any("시점이 여럿" in s for s in w)


def test_v4_outline_role_threads_closing_and_catch_all():
    data, _ = source()
    T = {u["turn"] for u in data["utterances"]}
    a = analysis_ok()
    a["threads"] = [{"thread_key": "t1", "name": "가게", "kind": "place", "events": ["e1", "e2"], "turns": [1, 5]}]
    o = outline_ok()
    o["chapters"][0]["threads"] = ["t1"]
    assert pipe.check_outline(o, a, T)[0] == "ready"
    for mutate, kind in ((lambda x: x["chapters"][0].pop("role"), "format"),
                         (lambda x: x["chapters"][0].__setitem__("threads", ["t9"]), "reference"),
                         (lambda x: x["book"].__setitem__("closing_turns", []), "reference"),
                         (lambda x: x["book"].__setitem__("closing_turns", [99]), "reference")):
        y = copy.deepcopy(o)
        mutate(y)
        with pytest.raises(pipe.PipelineError) as e:
            pipe.check_outline(y, a, T)
        assert e.value.kind == kind
    y = copy.deepcopy(o)
    y["book"]["theme_use"] = ""
    y["chapters"][0]["threads"] = []
    _, w = pipe.check_outline(y, a, T)
    assert any("theme_use" in s for s in w) and any("끈(threads)을 어느 장도" in s for s in w)
    # 끈 없이 사건 넷 이상을 모은 장
    many = analysis_ok()
    many["events"] = [{"event_key": f"e{i}", "summary": "s", "turns": [i], "people": [],
                       "time": {"text": "", "certainty": "unknown"}, "said_feelings": []} for i in range(1, 7)]
    many["not_in_events"] = []
    z = outline_ok()
    z["chapters"] = [chapter_plan("ch-1", ["e1", "e2"], [1, 2]),
                     chapter_plan("ch-2", ["e3", "e4", "e5", "e6"], [3, 4, 5, 6])]
    _, w = pipe.check_outline(z, many, T)
    assert any("모음 장" in s for s in w)


def _trial_spec():
    return json.loads((ROOT / "eval" / "trial_C_sewing.json").read_text(encoding="utf-8"))


def _seed_c_input():
    doc = cli._seed_doc(SEED_C_PATH)
    return pipe.build_input(cli.records_from_seed(doc, [s["alias"] for s in doc["sessions"]]))


def test_v4_trial_plan_is_plan_only_and_rejects_expected_essay():
    data, turn_map = _seed_c_input()
    T = pipe.check_input(data, turn_map)
    a, o = pipe.trial_plan(_trial_spec(), T)
    assert len(o["chapters"]) == 1 and all(e["summary"] == "" for e in a["events"])
    for bad in ({"expected_essay": "…"}, {"정답": "…"},
                {"chapter": dict(_trial_spec()["chapter"], purpose="가" * 200)}):
        spec = {**_trial_spec(), **bad}
        with pytest.raises(pipe.PipelineError, match="시험 계획"):
            pipe.trial_plan(spec, T)
    spec = _trial_spec()
    spec["events"][0]["turns"] = [99]
    with pytest.raises(pipe.PipelineError, match="입력에 없다"):
        pipe.trial_plan(spec, T)


def test_v4_chapter_trial_makes_one_call_and_records_findings(tmp_path):
    data, turn_map = _seed_c_input()
    essay = {"chapter_key": "ch-1", "title": sent("언니의 발틀", [], "editorial"),
             "paragraphs": [[sent("가게를 열고 한 달쯤 지나 부산에서 화물이 하나 왔다.", [26]),
                             sent("큰언니가 쓰던 검은색 발틀 재봉틀이었다.", [4, 26])],
                            [sent("가끔요. 손주 바지 단 정도.", [36])]],
             "review_notes": []}
    fake = Fake({"ch-1": essay})
    r = asyncio.run(pipe.run_chapter_trial(data, turn_map, _trial_spec(), call=fake,
                                           recorder=pipe.Recorder(tmp_path), meta={"run_ref": "trial"}))
    assert fake.order == ["ch-1"] and r["calls"] == 1 and r["generation_state"] == "generated"
    assert r["human_review"] == "not_run" and r["mode"] == "chapter_trial"
    assert r["metrics"]["multi_turn_sentences"] == 1
    assert {f["rule"] for f in r["code_findings"]} >= {"answer_trace", "style_mix"}
    assert r["metrics"]["paragraph_sessions"][0]["sessions"] == ["c1", "c4"]
    for n in ("00_trial_plan.json", "00_input.json", "03_ch-1.json", "result.json", "run.json"):
        assert (tmp_path / n).exists()
    spec = fake.specs[0]
    payload = json.loads(spec.user.split("\n\n", 1)[1])
    assert [p["event_key"] for p in payload["event_packets"]][:3] == ["e-learn", "e-factory", "e-arrival"]
    assert pipe.role_text("chapter") in spec.system


def test_v4_chapter_trial_without_key_does_not_reach_network(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(question, "_CLIENT", None)
    data, turn_map = _seed_c_input()
    r = asyncio.run(pipe.run_chapter_trial(data, turn_map, _trial_spec(), recorder=pipe.Recorder(tmp_path)))
    assert r["generation_state"] == "failed" and r["failure"]["kind"] == "call"


def test_v4_prompts_are_essay_style_and_do_not_carry_seed_c_text():
    import re
    prompts = {s: pipe.role_text(s) for s in pipe.STAGES}
    for s in ("chapter", "edit"):
        assert "~다" in prompts[s] and "수필" in prompts[s]
        assert "해요체로 쓰고" not in prompts[s] and "해요체·" not in prompts[s]
    seed = json.loads(SEED_C_PATH.read_text(encoding="utf-8"))
    frags = set()
    for sess in seed["sessions"]:
        for t in sess["turns"]:
            a = re.sub(r"\s+", " ", t["answer"])
            frags |= {a[i:i + 8] for i in range(max(0, len(a) - 7))}
    for s, txt in prompts.items():
        hits = [f for f in frags if f.strip() and len(f.strip()) >= 8 and f in txt]
        assert not hits, (s, hits[:3])                        # 시험 자료 원문을 지시문 예시로 쓰지 않는다
    trial = (ROOT / "eval" / "trial_C_sewing.json").read_text(encoding="utf-8")
    assert not any(f in trial for f in frags if len(f.strip()) >= 8)   # 시험 계획에도 원문 · 정답 글 없음


# ---------------------------------------------------------------- v4 실행 전 확인 — kept · 문맥 턴


@pytest.mark.parametrize("text, turns, rule, gate", [
    ("가게를 열었어요.", [1], "style_mix", "attention"),
    ("아니요, 가게를 열었다.", [1], "answer_trace", "attention"),
    ("이 장에서는 가게 이야기를 다룬다.", [], "meta_text", "attention"),
    ("그 얘긴 오늘은 그만할게요.", [1], "stop_phrase", "blocked"),
])
def test_kept_with_reason_does_not_clear_real_problems(text, turns, rule, gate):
    """kept + 이유는 기록일 뿐 — 문제가 편집본에 남으면 repeat_turn 말고는 남은 문제로 센다."""
    ch = {"chapter_key": "ch-1", "title": sent("제목", [], "editorial"),
          "paragraphs": [[sent(text, turns, "supported" if turns else "editorial")]]}
    checks = pipe.code_findings([ch], outline_ok())
    mine = [c for c in checks if c["rule"] == rule]
    assert mine, checks
    kept = {c["id"]: {"check_id": c["id"], "status": "kept", "reason": "그대로 두는 게 낫다고 봄"} for c in checks}
    g = pipe.code_gate(checks, kept, checks)
    assert g["state"] == gate
    v = {"state": "completed", "verdict": "pass"}
    assert pipe.overall_state("generated", g, v, "not_run") in ("needs_revision", "blocked_by_code")


def test_kept_repeat_only_accepts_that_turn():
    chs = [{"chapter_key": "ch-1", "title": sent("가", [], "editorial"),
            "paragraphs": [[sent("첫 일이 있었다.", [1]), sent("둘째 일이 있었다.", [5])]]},
           {"chapter_key": "ch-2", "title": sent("나", [], "editorial"),
            "paragraphs": [[sent("첫 일을 다시 떠올렸다.", [1]), sent("둘째 일도 떠올렸다.", [5])]]}]
    checks = pipe.code_findings(chs, outline_ok())
    rep = {c["turn"]: c for c in checks if c["rule"] == "repeat_turn"}
    assert set(rep) == {1, 5}
    kept1 = {rep[1]["id"]: {"check_id": rep[1]["id"], "status": "kept", "reason": "의도한 회상"}}
    assert pipe.code_gate(checks, kept1, checks)["state"] == "attention"     # 턴 5 의 중복은 남는다
    kept_both = {**kept1, rep[5]["id"]: {"check_id": rep[5]["id"], "status": "kept", "reason": "의도한 회상"}}
    assert pipe.code_gate(checks, kept_both, checks)["state"] == "pass"


def test_run_with_all_kept_but_problems_left_stays_needs_revision():
    d1 = draft("ch-1", 1)
    d1["paragraphs"][0].append(sent("가끔요. 그랬어요.", [1]))
    e = edited_ok()
    e["chapters"][0]["paragraphs"][0].append(sent("가끔요. 그랬어요.", [1]))    # 고치지 않고 그대로
    fake = Fake(script(ch_1=d1, edit=e, verify=verify_ok(reviewed_locations=["artifact"])))

    async def call(spec):                                       # 편집이 모든 경고를 kept + 이유로 적었다고 치자
        r = await fake(spec)
        if spec.stage == "edit":
            checks = json.loads(spec.user.split("\n\n", 1)[1])["checks"]
            out = json.loads(r.text)
            out["checks_resolution"] = [{"check_id": c["id"], "status": "kept", "reason": "원문 말투를 살림"}
                                        for c in checks]
            return pipe.Reply(json.dumps(out, ensure_ascii=False), "STOP")
        return r
    r = go(call)
    assert r["model_verdict"] == "pass" and r["code_gate"] == "attention"
    assert r["overall"] == "needs_revision"                     # kept 로 통과되지 않는다


def test_context_only_turns_are_marked_and_flagged():
    data, turn_map = _seed_c_input()
    T = pipe.check_input(data, turn_map)
    a, o = pipe.trial_plan(_trial_spec(), T)
    ch = o["chapters"][0]
    src, given = pipe.chapter_source(data, a, ch, o)
    core = pipe.chapter_owned_turns(a, ch) | set(ch["context_turns"])
    msg = json.loads(pipe.chapter_message(src, given, o, ch, a["people"], None,
                                          pipe.event_packets(a, ch, given), [], core).split("\n\n", 1)[1])
    assert set(msg["core_turns"]) == set(_trial_spec()["chapter"]["focus_turns"])
    assert set(msg["context_only_turns"]) == {1, 5, 10, 13, 16, 25, 28, 30, 37}
    assert not set(msg["core_turns"]) & set(msg["context_only_turns"])
    assert "context_only_turns" in pipe.role_text("chapter")

    d = {"chapter_key": "ch-1", "title": sent("t", [], "editorial"), "paragraphs": [[
        sent("딸이 결혼할 때 드레스 허리를 줄였다.", [30]),          # 계획에 없는 사건(문맥 턴만)
        sent("가게 일과는 그 재봉틀 앞에서 이어졌다.", [3, 4]),       # 핵심 근거
        sent("가게를 연 해를 바로잡았다.", [25, 26])]]}              # 문맥 + 핵심 함께 — 허용
    f = pipe.context_findings(d, core)
    assert [x["location"] for x in f] == ["ch-1/p0/s0"] and f[0]["severity"] == "fix"


# ---------------------------------------------------------------- v4 보완 — 근거 턴 · 사건 순서 · 집필 지시문

# v4 한 장 시험(20261026T081430Z-C5-b9f8-trial)의 모델 출력 — p1 이 문맥 전용 턴 14 의 사실을 턴 15 만 달고 썼다
_V4_TRIAL_SENTENCES = [
    ("열 살쯤 큰언니에게 양말 꿰매는 걸 배웠다.", [11, 12]),
    ("열일곱 살에 서울 동대문 근처 봉제 공장에 들어갔다.", [15]),
    ("기숙사 한 방에 여섯 명이 썼는데, 미싱 소리가 하도 시끄러워 밤에 누우면 귀에서 웅웅 소리가 났다.", [15]),
    ("가게를 열고 한 달쯤 지나서 부산에서 화물로 검은색 발틀 재봉틀이 왔다.", [4, 26, 27]),
    ("아침 아홉 시에 문을 열면 저녁 여덟 시까지 거의 재봉틀 앞에 앉아 지냈다.", [3]),
    ("무릎이 아파서 더는 앉아 있을 수 없어 2010년에 수선집 문을 닫았다.", [2, 35]),
    ("큰언니는 2004년 봄에 돌아가셨고, 장례식에는 남동생과 함께 갔다.", [34]),
    ("발이 예전 같지 않아 오래는 못 돌리지만, 가끔 손주 바지 단을 줄일 때 그 재봉틀을 쓴다.", [36, 38]),
    ("애들한테 그 재봉틀을 줄지는 아직 모르겠다.", [39]),
]


def _one_chapter(rows):
    return {"chapter_key": "ch-1", "title": sent("언니의 발틀", [], "editorial"),
            "paragraphs": [[sent(text, turns) for text, turns in rows]]}


def test_fact_check_regression_turn14_cited_as_15():
    """14 · 15 출처 회귀 사례 — 나이 · 지명이 근거 턴 15 에 없고 14 에 있다."""
    data, _ = _seed_c_input()
    f = pipe.fact_findings([_one_chapter(_V4_TRIAL_SENTENCES)], data)
    assert {x["location"] for x in f} == {"ch-1/p0/s1"}              # 다른 여덟 문장은 걸리지 않는다
    assert {x["token"] for x in f} == {"열일곱 살", "서울", "동대문"}
    assert all(14 in x["found_in"] and x["severity"] == "fix" for x in f)
    fixed = [(t, [14, 15] if i == 1 else ts) for i, (t, ts) in enumerate(_V4_TRIAL_SENTENCES)]
    assert pipe.fact_findings([_one_chapter(fixed)], data) == []     # 근거를 바로잡으면 경고 없음


def test_fact_check_allows_natural_rewording_and_flags_editorial_facts():
    data, _ = _seed_c_input()
    rows = [("1985년 봄에 가게를 열었다고 바로잡았다.", [25]),        # 원문 '85년' — 연도는 끝 두 자리로 맞춘다
            ("열일곱에 서울로 올라가 동대문 근처 공장에 들어갔다.", [14]),
            ("큰언니는 말수가 적었지만 손이 빨랐다.", [12])]
    assert pipe.fact_findings([_one_chapter(rows)], data) == []
    ed = _one_chapter([("그리고 2010년이 왔다.", [])])
    ed["paragraphs"][0][0]["kind"] = "editorial"
    f = pipe.fact_findings([ed], data)
    assert [x["token"] for x in f] == ["2010"] and set(f[0]["found_in"]) >= {2, 35}
    made_up = pipe.fact_findings([_one_chapter([("스무 살에 공장에 들어갔다.", [15])])], data)
    assert made_up and made_up[0]["found_in"] == [] and "어디에도 없다" in made_up[0]["detail"]


def test_fact_token_kept_with_reason_is_a_warning_not_a_block():
    data, _ = _seed_c_input()
    ch = _one_chapter([_V4_TRIAL_SENTENCES[1]])
    checks = pipe.fact_findings([ch], data)
    assert checks and pipe.code_gate(checks, {}, checks)["state"] == "attention"
    kept = {c["id"]: {"check_id": c["id"], "status": "kept", "reason": "같은 뜻을 바꿔 씀"} for c in checks}
    g = pipe.code_gate(checks, kept, checks)
    assert g["state"] == "pass" and set(g["accepted_facts"]) == {"열일곱 살", "서울", "동대문"}
    style = pipe.code_findings([_one_chapter([("공장에 들어갔어요.", [14])])], outline_ok())
    both = checks + style                                              # 문체 문제는 kept 로도 남는다
    kept_all = {c["id"]: {"check_id": c["id"], "status": "kept", "reason": "그대로"} for c in both}
    assert pipe.code_gate(both, kept_all, both)["state"] == "attention"


def test_chapter_trial_records_fact_findings(tmp_path):
    data, turn_map = _seed_c_input()
    fake = Fake({"ch-1": {**_one_chapter([_V4_TRIAL_SENTENCES[1]]), "review_notes": []}})
    r = asyncio.run(pipe.run_chapter_trial(data, turn_map, _trial_spec(), call=fake,
                                           recorder=pipe.Recorder(tmp_path)))
    assert r["calls"] == 1 and "fact_token" in {f["rule"] for f in r["code_findings"]}


def test_run_passes_fact_findings_to_edit():
    d1 = draft("ch-1", 1)
    d1["paragraphs"][0].append(sent("2099년에 그 일이 있었다.", [1]))
    fake = Fake(script(ch_1=d1))
    go(fake)
    edit = next(s for s in fake.specs if s.stage == "edit")
    checks = json.loads(edit.user.split("\n\n", 1)[1])["checks"]
    assert any(c["rule"] == "fact_token" and c["token"] == "2099" for c in checks)


def test_trial_plan_turn14_is_core_and_events_follow_the_sister_and_machine():
    data, turn_map = _seed_c_input()
    T = pipe.check_input(data, turn_map)
    spec = _trial_spec()
    a, o = pipe.trial_plan(spec, T)
    ch = o["chapters"][0]
    assert ch["events"] == ["e-learn", "e-factory", "e-arrival", "e-shop-days", "e-sister-death", "e-close", "e-now"]
    owned = pipe.chapter_owned_turns(a, ch)
    assert {14, 15, 29, 34} <= owned and 14 in ch["focus_turns"]
    _, given = pipe.chapter_source(data, a, ch, o)
    assert len(given) == 24 and set(given) - owned == {1, 5, 10, 13, 16, 25, 28, 30, 37}
    packets = pipe.event_packets(a, ch, given)
    assert [p["event_key"] for p in packets][3:6] == ["e-shop-days", "e-sister-death", "e-close"]
    text = json.dumps(spec, ensure_ascii=False)
    assert not any(len(s) > pipe.TRIAL_MAX_TEXT for s in (spec["theme_use"], ch["purpose"], ch["role"]))
    assert "paragraphs" not in text                                   # 계획에 본문 글 없음


def test_chapter_prompt_v4_asks_for_connected_paragraphs_without_counts():
    c, e = pipe.role_text("chapter"), pipe.role_text("edit")
    assert "문단의 단위가 아닙니다" in c and "한 문단으로 세우지 마세요" in c
    assert "문단 수와 문장 수는 정해져 있지 않습니다" in c
    assert "인생 교훈" in c and "지나친 감성 표현" in c
    assert "숫자·연도·나이·지명" in c and "그 턴을 반드시 turns에 넣으세요" in c
    assert "fact_token" in e and "보조 검사" in e

