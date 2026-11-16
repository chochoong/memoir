"""
자서전 각색 실험 — 모델을 부르지 않는다. 실행 폴더는 tmp_path 에 손으로 만든다(eval/runs 는 git 제외).

    .venv\\Scripts\\python -m pytest tests/test_memoir_adapt.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_pipeline as pipe                           # noqa: E402
from tools import memoir_adapt as adapt                                   # noqa: E402
from tools import memoir_pipeline as cli                                  # noqa: E402

UTTERANCES = [
    {"turn": 1, "session_id": "c1", "asked": "언니는 어떤 분이었어요?", "elder": "언니가 나를 업어 키웠다고 들었어요."},
    {"turn": 2, "session_id": "c1", "asked": "재봉틀은요?", "elder": "86년에, 아니 85년 봄에 가게를 열었어요. 언니가 '너는 손이 야무지다' 그랬어요."},
    {"turn": 3, "session_id": "c2", "asked": "남편분은요?", "elder": "그 얘기는 그만할게요."},
]
FACTS = [
    {"id": "f1", "turns": [1], "text": "큰언니가 업어 키웠다고 들음", "time": "", "source": "heard", "certainty": "stated"},
    {"id": "f2", "turns": [2], "text": "1985년 봄 가게를 엶", "time": "1985년 봄", "source": "self", "certainty": "stated"},
    {"id": "f3", "turns": [2], "text": "언니가 손이 야무지다고 말함", "time": "", "source": "self", "certainty": "stated"},
]
CHAPTERS = [{"chapter_key": "ch-1", "center": "", "title": {"text": "언니와 재봉틀", "kind": "editorial", "facts": []},
             "paragraphs": [[
                 {"text": "큰언니가 나를 업어 키웠다고 들었다.", "kind": "supported", "facts": ["f1"], "turns": [1]},
                 {"text": "1985년 봄 나는 가게를 열었다.", "kind": "supported", "facts": ["f2"], "turns": [2]},
                 {"text": "언니는 내 손이 야무지다고 했다.", "kind": "supported", "facts": ["f3"], "turns": [2]},
             ]]}]


def make_run(tmp_path: Path, **result) -> Path:
    folder = tmp_path / "run"
    folder.mkdir()
    (folder / "00_input.json").write_text(json.dumps(
        {"input_ref": "abc", "input": {"utterances": UTTERANCES}}, ensure_ascii=False), encoding="utf-8")
    (folder / "01_analysis.json").write_text(json.dumps(
        {"facts": FACTS, "people": [{"name": "큰언니", "relation": "언니"}],
         "corrections": [{"fact": "f2", "turns": [2], "before": "1986년", "after": "1985년 봄"}],
         "exclusions": [{"mode": "whole", "turns": [3], "scope": "남편 이야기"}]}, ensure_ascii=False), encoding="utf-8")
    doc = {"run_ref": "R", "pipeline_complete": True, "chapters": CHAPTERS, "overall": "needs_revision",
           "human_review": "not_run"} | result
    (folder / "result.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return folder


def good_doc() -> dict:
    return {"chapters": [{"chapter_key": "ch-1", "title": "언니와 재봉틀", "paragraphs": [[
        {"text": "큰언니가 나를 업어 키웠다고 들었다.", "kind": "kept", "from": ["ch-1/p1/s1"], "facts": ["f1"], "turns": [1]},
        {"text": "1985년 봄 나는 가게를 열었다.", "kind": "kept", "from": ["ch-1/p1/s2"], "facts": ["f2"], "turns": [2]},
        {"text": "창으로 봄볕이 들었다.", "kind": "scene", "from": [], "facts": ["f2"], "turns": []},
        {"text": "\"너는 손이 야무지다.\" 언니가 말했다.", "kind": "dialogue", "from": ["ch-1/p1/s3"], "facts": ["f3"], "turns": [2]},
    ]]}], "notes": []}


def test_input_carries_manuscript_ledger_and_turns_but_not_excluded_turn_or_common_rules(tmp_path):
    system, user, index = adapt.build(adapt.load_run(make_run(tmp_path)))
    payload = json.loads(user)
    assert [s["id"] for s in payload["chapters"][0]["paragraphs"][0]] == ["ch-1/p1/s1", "ch-1/p1/s2", "ch-1/p1/s3"]
    assert {f["id"] for f in payload["facts"]} == {"f1", "f2", "f3"}
    assert [t["turn"] for t in payload["turns"]] == [1, 2]                  # 통째 제외 턴 3 은 주지 않는다
    assert payload["corrections"] == [{"fact": "f2", "after": "1985년 봄"}]  # 정정 전 값은 보내지 않는다
    assert "[역할 — 각색 담당]" in system and pipe.common_rules() not in system


def test_rejects_unfinished_run_and_non_pipeline_folder(tmp_path):
    try:
        adapt.load_run(make_run(tmp_path, pipeline_complete=False))
        raise AssertionError("받으면 안 된다")
    except adapt.InputRejected:
        pass
    assert adapt.main(["--run-dir", str(tmp_path), "--dry-run"]) == 2


def test_rejects_ledger_from_another_run(tmp_path):
    folder = make_run(tmp_path)
    doc = json.loads((folder / "01_analysis.json").read_text(encoding="utf-8"))
    doc["facts"][0]["turns"] = [3]                       # 같은 id f1 이 다른 턴을 가리킨다
    (folder / "01_analysis.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    try:
        adapt.build(adapt.load_run(folder))
        raise AssertionError("받으면 안 된다")
    except adapt.InputRejected as e:
        assert "ch-1/p1/s1:f1" in str(e)


def test_findings_pass_good_adaptation_and_flag_fiction_share(tmp_path):
    index = adapt.build(adapt.load_run(make_run(tmp_path)))[2]
    found = adapt.adapt_findings(good_doc(), index)
    assert [f for f in found if f["severity"] == "fix"] == []
    assert any(f["rule"] == "fiction_share" for f in found)                 # 4문장 중 2문장 — 3분의 1 넘음


def test_findings_catch_lost_fact_dropped_sentence_excluded_turn_and_pre_correction(tmp_path):
    index = adapt.build(adapt.load_run(make_run(tmp_path)))[2]
    doc = good_doc()
    para = doc["chapters"][0]["paragraphs"][0]
    para[1]["text"] = "1986년 봄 나는 가게를 열었다."                       # 정정 전 값
    del para[3]                                                            # 사실 f3 · 문장 s3 이 사라짐
    para.append({"text": "남편은 말이 없었다.", "kind": "scene", "from": [], "facts": [], "turns": [3]})
    rules = {f["rule"] for f in adapt.adapt_findings(doc, index) if f["severity"] == "fix"}
    assert {"pre_correction", "fact_lost", "sentence_dropped", "excluded_turn", "unanchored"} <= rules


def test_v2_takes_turn_anchored_scene_and_flags_restated_and_too_little(tmp_path):
    run = adapt.load_run(make_run(tmp_path))
    doc = good_doc()
    para = doc["chapters"][0]["paragraphs"][0]
    para[2] = {"text": "가게 문턱에 놓인 다리미에서 김이 올랐다.", "kind": "scene", "from": [], "facts": [], "turns": [2]}
    v1 = {f["rule"] for f in adapt.adapt_findings(doc, adapt.build(run, "v1")[2])}
    v2 = {f["rule"] for f in adapt.adapt_findings(doc, adapt.build(run, "v2")[2])}
    assert "unanchored" in v1 and "unanchored" not in v2                    # 원문 턴만으로 근거 — v2 에서만
    assert "6_각색_v2" not in adapt.build(run, "v1")[0] and "[분량 — 문단마다 한 곳]" in adapt.build(run, "v2")[0]

    para[2] = {"text": "1985년 봄에 나는 가게를 열었다.", "kind": "scene", "from": [], "facts": ["f2"], "turns": []}
    assert any(f["rule"] == "restated" for f in adapt.adapt_findings(doc, adapt.build(run)[2]))

    doc["chapters"][0]["paragraphs"][0] = [x for x in para if x["kind"] != "scene"] + [
        {"text": t, "kind": "kept", "from": [], "facts": [], "turns": []} for t in ("가.", "나.", "다.")]
    assert any(f["rule"] == "fiction_low" for f in adapt.adapt_findings(doc, adapt.build(run, "v2")[2]))
    assert not any(f["rule"] == "fiction_low" for f in adapt.adapt_findings(doc, adapt.build(run, "v1")[2]))


def test_paragraph_span_keeps_only_those_paragraphs_with_their_anchors(tmp_path):
    folder = make_run(tmp_path)
    doc = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    para = doc["chapters"][0]["paragraphs"][0]
    doc["chapters"][0]["paragraphs"] = [para[:1], para[1:]]
    (folder / "result.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    run = adapt.select_paragraphs(adapt.load_run(folder), "2")
    payload = json.loads(adapt.build(run)[1])
    assert [s["id"] for s in payload["chapters"][0]["paragraphs"][0]] == ["ch-1/p1/s1", "ch-1/p1/s2"]
    assert {f["id"] for f in payload["facts"]} == {"f2", "f3"} and [t["turn"] for t in payload["turns"]] == [2]
    for bad in ("3", "2-1", "x"):
        try:
            adapt.select_paragraphs(adapt.load_run(folder), bad)
            raise AssertionError(bad)
        except adapt.InputRejected:
            pass


def test_run_calls_once_and_writes_marked_manuscript_and_review_sheet(tmp_path, monkeypatch, capsys):
    folder = make_run(tmp_path)
    calls = []

    async def fake(spec):
        calls.append(spec)
        return pipe.Reply(text="```json\n" + json.dumps(good_doc(), ensure_ascii=False) + "\n```", finish="STOP",
                          usage={"prompt": 1, "output": 2, "thoughts": None, "total": 3})

    monkeypatch.setattr(cli, "call_any", fake)
    out_dir = tmp_path / "out"
    assert adapt.main(["--run-dir", str(folder), "--run", "--model", "gemini-4-argon", "--out-dir", str(out_dir)]) == 0
    assert len(calls) == 1 and calls[0].stage == "adapt" and calls[0].temperature == adapt.TEMPERATURE
    [run_dir] = list(out_dir.iterdir())
    md = (run_dir / "각색본.md").read_text(encoding="utf-8")
    assert "*창으로 봄볕이 들었다.*" in md and "⟨\"너는 손이 야무지다.\" 언니가 말했다.⟩" in md
    sheet = (run_dir / "각색_검수표.md").read_text(encoding="utf-8")
    assert "턴 2: 86년에, 아니 85년 봄에" in sheet and "fiction_share" in sheet
    assert json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["ok"] is True
    assert "코드 검사" in capsys.readouterr().out
