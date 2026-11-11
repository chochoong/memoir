"""
자서전 소설체 (style=novel · memoir_novel)

    python -m pytest tests/test_memoir_novel.py -q

모델을 부르지 않는다 — memoir_novel._call 을 갈아 끼운다.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.session import memoir, memoir_novel as mn, style as styles     # noqa: E402

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _rec(n: int, says: list[str], card: str | None = None, minutes: int = 0) -> dict:
    frags = [{"idx": 0, "question": "씨앗", "answer": "", "decision": None}]
    frags += [{"idx": i, "question": f"질문{i}", "answer": a, "decision": None} for i, a in enumerate(says, start=1)]
    return {"session_id": f"0000000{n}-0000-4000-8000-000000000000", "user_id": "u", "title": f"회차{n}",
            "created_at": T0 + timedelta(minutes=minutes), "fragments": frags, "closing_decision": None,
            "postcard": {"title": card} if card else None}


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mn._CACHE.clear()
    calls: list[str] = []
    state = {"stop": {}}

    async def call(client, msg, s):
        calls.append(msg)
        no = len(calls)
        stop = next((v for k, v in state["stop"].items() if f"\n{k}\n" in msg), "end_turn")
        return f"첫 장면이다. {no}\n\n\"대사야.\"\n\"대답이야.\"", {"stop": stop, "model": s["MEMOIR_NOVEL_MODEL"],
                                                              "input": 100, "output": 200}

    monkeypatch.setattr(mn, "_call", call)
    return calls, state


def test_prompt_is_the_handed_over_file():
    text, sha = mn.template()
    assert sha.startswith(mn.PROMPT_SHA256) and text.count(mn.SLOT) == 1
    msg = mn.user_message("할머니 말씀")
    assert mn.SLOT not in msg and "[현재 장 원문 시작]\n할머니 말씀\n[현재 장 원문 끝]" in msg


def test_source_is_elder_words_only():
    src = mn.source_text(_rec(1, ["열아홉에 시집왔지.", "  ", "그해 겨울이 추웠어."]))
    assert src == "열아홉에 시집왔지.\n\n그해 겨울이 추웠어." and "질문" not in src


def test_paragraphs_keep_every_line():
    ps = mn.paragraphs("장면.\n\n\"가자.\"\n\"응.\"\n")
    assert [p["sentences"][0]["text"] for p in ps] == ["장면.", "\"가자.\"", "\"응.\""]
    assert all(p["sentences"][0]["turns"] == [] for p in ps)


def test_run_one_chapter_per_session_in_recorded_order(fake):
    calls, _ = fake
    later, first = _rec(2, ["두번째"], minutes=5), _rec(1, ["첫번째"], card="시집오던 날")
    ids = [later["session_id"], first["session_id"]]
    seen = []
    out = asyncio.run(mn.run([later, first], ids, "novel", lambda *a: seen.append(a)))
    assert out["status"] == "ready" and out["style"] == "novel" and out["title"] == mn.BOOK_TITLE
    assert [c["title"] for c in out["chapters"]] == ["시집오던 날", "회차2"]
    assert "첫번째" in calls[0] and "두번째" in calls[1]
    assert out["run"]["session_ids"] == ids and out["run"]["prompt_sha256"] == mn.PROMPT_SHA256
    assert out["verification"] == {"state": "not_run"} and len(out["sources"]) == 6
    assert seen[0] == ("chapter", 1, 2)

    # 같은 회차를 다시 쓰면 모델을 다시 부르지 않는다 (책에 장이 늘 때)
    third = _rec(3, ["세번째"], minutes=9)
    out2 = asyncio.run(mn.run([later, first, third], ids + [third["session_id"]], "novel"))
    assert len(calls) == 3 and len(out2["chapters"]) == 3


def test_truncated_chapter_is_not_used(fake):
    _, state = fake
    state["stop"] = {"말씀2": "max_tokens"}
    recs = [_rec(i, [f"말씀{i}"], minutes=i) for i in (1, 2, 3)]
    with pytest.raises(memoir.Incomplete):
        asyncio.run(mn.run(recs, [r["session_id"] for r in recs], "novel"))
    mn._CACHE.clear()
    state["stop"] = {"말씀1": "refusal"}
    with pytest.raises(memoir.GenerationFailed):
        asyncio.run(mn.run(recs[:1], [recs[0]["session_id"]], "novel"))


def test_needs_anthropic_key(fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(memoir.GenerationFailed):
        asyncio.run(mn.run([_rec(1, ["a"])], ["x"], "novel"))


def test_novel_is_open_for_memoir_only():
    assert styles.pick("novel", styles.MEMOIR) == "novel"
    with pytest.raises(styles.UnsupportedStyle):
        styles.pick("novel")                                     # 엽서
    with pytest.raises(styles.UnsupportedStyle):
        styles.pick("cyworld", styles.MEMOIR)


def test_generate_routes_novel(monkeypatch):
    got = {}

    async def run(recs, ids, style, progress=None):
        got.update(ids=ids, style=style)
        return {"ok": True}

    monkeypatch.setattr(mn, "run", run)
    assert asyncio.run(memoir.generate([], ["a"], "u", "novel")) == {"ok": True}
    assert got == {"ids": ["a"], "style": "novel"}
