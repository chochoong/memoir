"""
자서전 수필체 · 문학체 (style=essay · literary · memoir_styled)

    python -m pytest tests/test_memoir_styled.py -q

모델을 부르지 않는다 — memoir_styled._call 을 갈아 끼운다.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.session import memoir, memoir_styled as ms, style as styles     # noqa: E402

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _rec(n: int, says: list[str], card: str | None = None, minutes: int = 0) -> dict:
    frags = [{"idx": 0, "question": "씨앗", "answer": "", "decision": None}]
    frags += [{"idx": i, "question": f"질문{i}", "answer": a, "decision": None} for i, a in enumerate(says, start=1)]
    return {"session_id": f"0000000{n}-0000-4000-8000-000000000000", "user_id": "u", "title": f"회차{n}",
            "created_at": T0 + timedelta(minutes=minutes), "fragments": frags, "closing_decision": None,
            "postcard": {"title": card} if card else None}


def _analysis(nums: list[int]) -> dict:
    st = [{"turn": n, "title_hint": f"힌트{n}", "people": ["어머니"], "time": ["열아홉"], "places": ["읍내"],
           "events": ["일"], "objects": ["못"], "emotions_then": [], "reflections_now": [], "quotes": [], "heard": [],
           "must_keep": [f"세부{n}"], "emotion_notes": [],
           "facts": [{"id": f"f{n}-1", "text": f"사실{n}", "source": "self", "certainty": "stated"}]} for n in nums]
    ch = {"id": "c1", "title_basis": {"core_change": "변화", "candidates": []}, "stories": nums, "fact_ids": [],
          "center_scene": "장면", "emotion": "감정", "direction": "방향", "fiction_notes": "주의", "avoid_overlap": "없음"}
    return {"book_title": "책", "stories": st, "chapters": [ch]}


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    ms._CACHE.clear()
    calls: list[tuple[str, str]] = []
    state = {"stop": {}}

    async def call(client, system, msg, fmt, model, mt, effort):
        a_sys, _ = ms.analysis_prompt()
        kind = "A" if system == a_sys else "W"
        calls.append((kind, msg))
        stop = next((v for k, v in state["stop"].items() if k in msg and kind == "W"), "end_turn")
        if kind == "A":
            nums = [int(x) for x in re.findall(r"^## 이야기 (\d+)$", msg, re.M)]
            body = _analysis(nums)
        else:
            cid = re.search(r"^# (c\d+)", msg, re.M).group(1)
            n = re.search(r"### 이야기 (\d+)", msg).group(1)
            body = {"essay_id": "e48", "title": "모델이 지은 제목",
                    "paragraphs": [f"사실{n}을 적었다. 두 번째 문장이다.", "첫 줄이다.\n둘째 줄이다."],
                    "facts": [{"id": f"f{n}-1", "where": f"사실{n}을 적었다"}], "quotes_kept": [],
                    "fiction": [{"text": "두 번째 문장이다", "type": "상징·비유", "basis": "없음", "risk": "낮음",
                                 "human_check": False}], "notes": cid}
        return json.dumps(body, ensure_ascii=False), {"stop": stop, "model": model, "input": 10, "output": 20}

    monkeypatch.setattr(ms, "_call", call)
    return calls, state


def test_handed_over_files():
    assert ms.prompt("essay")[1].startswith("4a9c43e3b163e70d")
    assert ms.prompt("literary")[1].startswith("fd70d60bb8ad4e14")
    assert ms.analysis_prompt()[1].startswith("6c2f1afea07e982e")
    assert ms.schema(ms.ANALYSIS["schema"])["required"] == ["book_title", "stories", "chapters"]


def test_story_numbers_run_through_the_book():
    a, b = _rec(1, ["하나", "  ", "둘"]), _rec(2, ["셋"], minutes=1)
    assert ms.stories_of([a, b]) == [{1: "하나", 2: "둘"}, {3: "셋"}]
    msg = ms.analysis_message({3: "셋"})
    assert msg.startswith("## 이야기 3\n\n셋\n\n위 이야기 1개를") and "장 하나(c1)" in msg


def test_sentences_and_fact_turns():
    assert ms.split_sentences('"가자." 그가 말했다. 정말? 그래') == ['"가자."', "그가 말했다.", "정말?", "그래"]
    ps = ms.paragraphs({"paragraphs": ["사실을 적었다. 그리고.", "가\n나"]}, [(ms.norm("사실을 적었다"), 7)])
    assert [[s["text"] for s in p["sentences"]] for p in ps] == [["사실을 적었다.", "그리고."], ["가"], ["나"]]
    assert ps[0]["sentences"][0]["turns"] == [7] and ps[0]["sentences"][1]["turns"] == []


@pytest.mark.parametrize("style", ["essay", "literary"])
def test_run_analyses_each_session_then_writes_each_chapter(fake, style):
    calls, _ = fake
    later, first = _rec(2, ["셋째 말씀"], minutes=5), _rec(1, ["첫 말씀", "둘째 말씀"], card="시집오던 날")
    ids = [later["session_id"], first["session_id"]]
    seen = []
    out = asyncio.run(ms.run([later, first], ids, style, lambda *a: seen.append(a)))
    assert out["status"] == "ready" and out["style"] == style and out["title"] == ms.STYLES[style]["book"]
    assert [c["title"] for c in out["chapters"]] == ["시집오던 날", "회차2"]          # 모델 제목은 쓰지 않는다
    assert [k for k, _ in calls] == ["A", "A", "W", "W"]
    w = {re.search(r"^# (c\d+)", m, re.M).group(1): m for k, m in calls if k == "W"}
    assert "첫 말씀" in w["c1"] and "셋째 말씀" in w["c2"] and "셋째 말씀" not in w["c1"]
    if style == "essay":
        assert "「시집오던 날」" in w["c1"]                                          # 확정 제목 = 엽서 제목
    else:
        assert "제목 미확정" in w["c1"]
    first_sent = out["chapters"][0]["paragraphs"][0]["sentences"][0]
    assert first_sent["turns"] == [1] and len(out["chapters"][0]["paragraphs"]) == 3
    assert out["adaptations"][0]["chapter"] == 1 and out["verification"] == {"state": "not_run"}
    assert out["run"]["session_ids"] == ids and seen[0] == ("analysis", 0, 2)

    # 책에 장이 늘어도 앞 장은 다시 분석 · 집필하지 않는다
    third = _rec(3, ["넷째 말씀"], minutes=9)
    out2 = asyncio.run(ms.run([later, first, third], ids + [third["session_id"]], style))
    assert [k for k, _ in calls[4:]] == ["A", "W"] and len(out2["chapters"]) == 3


def test_failures(fake):
    _, state = fake
    recs = [_rec(i, [f"말씀{i}"], minutes=i) for i in (1, 2)]
    state["stop"] = {"말씀2": "max_tokens"}
    with pytest.raises(memoir.Incomplete):
        asyncio.run(ms.run(recs, [r["session_id"] for r in recs], "essay"))
    ms._CACHE.clear()
    state["stop"] = {"말씀1": "refusal"}
    with pytest.raises(memoir.GenerationFailed):
        asyncio.run(ms.run(recs[:1], [recs[0]["session_id"]], "literary"))


def test_sensitive_memory_by_words():
    assert ms.sensitive({1: "그해 겨울에 아버지가 돌아가셨어요."})
    assert ms.sensitive({1: "봄에 시집왔어요.", 2: "6.25 때 피난을 갔지."})
    assert ms.sensitive({1: "어머니가 병원에 오래 계셨어."})
    assert not ms.sensitive({1: "열아홉에 읍내 철물점에서 배달 일을 했어요."})
    book = {"stories": _analysis([1])["stories"], "chapters": [{**_analysis([1])["chapters"][0], "title": "장"}]}
    assert "민감: true" in ms.style_message("essay", book, {1: "장례를 치렀어요."}, "c1")
    assert "민감: false" in ms.style_message("essay", book, {1: "누룽지가 고소했어요."}, "c1")
    assert "민감한 기억: 있음" in ms.style_message("literary", book, {1: "사고가 났어요."}, "c1")
    assert "민감한 기억: 없음" in ms.style_message("literary", book, {1: "누룽지가 고소했어요."}, "c1")


def test_analysis_must_cover_every_story():
    with pytest.raises(ValueError):
        ms.check_analysis(_analysis([1]), [1, 2])
    a = _analysis([1, 2])
    a["chapters"].append(dict(a["chapters"][0], id="c2"))
    part = ms.check_analysis(a, [1, 2])
    assert part["chapter"]["stories"] == [1, 2] and part["chapter"]["fact_ids"] == ["f1-1", "f2-1"]


def test_needs_anthropic_key(fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(memoir.GenerationFailed):
        asyncio.run(ms.run([_rec(1, ["a"])], ["x"], "essay"))


def test_open_for_memoir_only():
    for v in ("essay", "literary"):
        assert styles.pick(v, styles.MEMOIR) == v
        with pytest.raises(styles.UnsupportedStyle):
            styles.pick(v)                                       # 엽서


@pytest.mark.parametrize("style", ["essay", "literary"])
def test_generate_routes(monkeypatch, style):
    got = {}

    async def run(recs, ids, st, progress=None):
        got.update(style=st)
        return {"ok": True}

    monkeypatch.setattr(ms, "run", run)
    assert asyncio.run(memoir.generate([], ["a"], "u", style)) == {"ok": True}
    assert got == {"style": style}
