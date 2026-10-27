"""
자유 산문형 집필 진단 실험 (단위 8P) — 모델을 부르지 않는다.

    .venv\\Scripts\\python -m pytest tests/test_memoir_free_essay.py -v
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_pipeline as pipe                           # noqa: E402
from tools import memoir_free_essay as free                               # noqa: E402
from tools import memoir_pipeline as cli                                  # noqa: E402

SEED_C = ROOT / "eval" / "memoir_seed_C.json"
ARGS = ["--seed", str(SEED_C), "--aliases", "c1,c2,c3,c4,c5"]


def _data():
    doc = cli._seed_doc(SEED_C)
    return pipe.build_input(cli.records_from_seed(doc, [s["alias"] for s in doc["sessions"]]))[0]


def test_input_is_raw_turns_only_without_ledger_draft_or_expected_essay():
    data = _data()
    system, user, sel = free.build(data)
    by = {u["turn"]: u for u in data["utterances"]}
    assert [u["turn"] for u in sel] == list(free.TURNS) and 33 not in free.TURNS
    for t in free.TURNS:                                             # 원문 글자 그대로
        assert f"어르신: {by[t]['elder']}" in user and f"질문: {by[t]['asked']}" in user
    assert "남편은 2015년에 돌아가셨어요" not in user                   # 멈춘 대목은 주지 않는다
    a = json.loads((ROOT / "eval" / "analysis_fixture_C_v5_reviewed.json").read_text(encoding="utf-8"))["analysis"]
    memos = [f["text"] for f in a["facts"]]
    draft = json.loads((ROOT / "tests" / "data" / "v5_chapter_pro_20261027T023603Z" / "03_ch-1.json").read_text(encoding="utf-8"))
    sentences = [x["text"] for p in draft["paragraphs"] for x in p]
    for text in memos + sentences + ["언니가 남긴 소리", "언니의 발틀"]:
        assert text not in system + user, text
    assert "업어 키웠다고 들음" not in user and "f16" not in system + user and "{" not in system + user
    assert "85년 봄" in system and "86년은 어디에도 쓰지" in system and "JSON" in system


def test_dry_run_does_not_call(capsys, monkeypatch):
    called = []
    monkeypatch.setattr(free, "call_once", lambda *a: called.append(a))
    assert free.main(ARGS + ["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert not called and "전달 턴 21개" in out and "gemini-3.1-pro-preview · 온도 1.0 · 호출 1회 · 재시도 0" in out
    assert "출력 상한 32,768" in out and "시간 상한 300초" in out and "예상 비용" in out


def test_run_calls_once_as_plain_text_and_records(tmp_path, monkeypatch):
    calls = []

    async def fake(system, user):
        calls.append((system, user))
        return {"text": "언니의 재봉틀\n\n언니가 준 재봉틀을 아직 버리지 못했다.", "finish": "STOP",
                "usage": {"prompt": 10, "candidates": 5, "thoughts": 3, "total": 18}}
    monkeypatch.setattr(free, "call_once", fake)
    assert free.main(ARGS + ["--run", "--out-dir", str(tmp_path)]) == 0
    assert len(calls) == 1
    folder = next(tmp_path.iterdir())
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert run["calls"] == 1 and run["settings"]["retries"] == 0 and run["settings"]["response_mime_type"] is None
    assert (folder / "평가용_수필.md").read_text(encoding="utf-8").startswith("언니의 재봉틀")
    sheet = (folder / "검수자용_대조표.md").read_text(encoding="utf-8")
    assert "| 10 | 2 |" in sheet and "기억은 안 나요" in sheet
    assert pipe.settings()["MEMOIR_PIPE_TEXT_MODEL"] == "gemini-3.5-flash-lite"


def test_failed_call_is_recorded_not_retried(tmp_path, monkeypatch):
    n = []

    async def boom(system, user):
        n.append(1)
        raise TimeoutError("300초")
    monkeypatch.setattr(free, "call_once", boom)
    assert free.main(ARGS + ["--run", "--out-dir", str(tmp_path)]) == 1
    run = json.loads((next(tmp_path.iterdir()) / "run.json").read_text(encoding="utf-8"))
    assert n == [1] and run["ok"] is False and "TimeoutError" in run["error"]


def test_real_call_config_has_no_json_mode(monkeypatch):
    seen = {}

    class Models:
        async def generate_content(self, model, contents, config):
            seen.update(model=model, config=config)

            class R:
                text, candidates, usage_metadata = "글", [], None
            return R()

    class Client:
        class aio:
            models = Models()
    monkeypatch.setattr("app.session.question._client", lambda: Client())
    out = asyncio.run(free.call_once("지시", "원문"))
    assert out["text"] == "글" and seen["model"] == "gemini-3.1-pro-preview"
    assert seen["config"].response_mime_type is None and seen["config"].temperature == 1.0
    assert seen["config"].max_output_tokens == 32768
