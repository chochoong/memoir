"""
회차의 낭독 목소리 고르기 — StartReq · LinkReq 의 voice (default · young)

    python -m pytest tests/test_voice.py -q

네트워크 없이 돈다 — Gemini · Azure 를 부르지 않고, 누구에게 어떤 목소리 이름이 갔는지만 본다.
"""

from __future__ import annotations

import asyncio
import sys
import typing
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.session import link, tts, tts_gemini                            # noqa: E402
from app.session.controller import SessionController                     # noqa: E402


def test_request_names_match_tts_voices():
    from app import main
    assert set(typing.get_args(main.VoiceKey)) == set(tts.VOICES)
    assert main.StartReq(title="t").voice == "default"
    assert main.LinkReq(elder_id="e_1").voice == "default"
    with pytest.raises(Exception):
        main.StartReq(title="t", voice="child")


def test_gemini_voice_mapping():
    assert tts.gemini_voice("young") == "Leda"
    assert tts.gemini_voice("default") is None          # .env 의 GEMINI_TTS_VOICE (기본 Kore)
    assert tts.gemini_voice(None) is None
    assert tts.gemini_voice("모르는 이름") is None


def test_gemini_config_uses_voice(monkeypatch):
    monkeypatch.delenv("GEMINI_TTS_VOICE", raising=False)
    name = lambda cfg: cfg.speech_config.voice_config.prebuilt_voice_config.voice_name
    assert name(tts_gemini._config()) == "Kore"
    assert name(tts_gemini._config("Leda")) == "Leda"


def _run_one_question(**kw):
    seen = []

    async def tts_fn(text, **k):
        seen.append(k)
        return b""

    async def go():
        ctl = SessionController(user_id="t", title="시험", tts_fn=tts_fn, stream_fn=None, **kw)
        await ctl.start("씨앗")
        await asyncio.sleep(0.05)
        return ctl

    return asyncio.run(go()), seen


def test_session_reads_with_its_voice():
    ctl, seen = _run_one_question(voice="young")
    assert seen and seen[0] == {"voice": "young"}
    assert ctl.snapshot()["voice"] == "young"


def test_default_voice_passes_nothing():
    """기본 목소리면 voice 를 넘기지 않는다 — 글자 하나만 받는 tts_fn 도 그대로 돈다."""
    ctl, seen = _run_one_question()
    assert seen and seen[0] == {}
    assert ctl.snapshot()["voice"] == "default"


def test_stream_sends_voice_to_gemini(monkeypatch):
    got = []

    async def fake_stream(text, voice=None):
        got.append(voice)
        yield b"\x00\x40" * 24000, 24000                 # 1초, 무음 깎기에 걸리지 않을 크기

    monkeypatch.setattr(tts_gemini, "available", lambda: True)
    monkeypatch.setattr(tts_gemini, "stream", fake_stream)

    async def go():
        sp = tts.Speech.start("안녕하세요", "young")
        await sp._task
        return sp

    sp = asyncio.run(go())
    assert got == ["Leda"] and sp.source == "gemini"


def test_link_keeps_voice(monkeypatch):
    saved = {}

    async def create_link(rec):
        saved.update(rec)
    monkeypatch.setattr(link.store, "create_link", create_link)
    prep = {"elder_id": "e_1", "title": "t", "seed": "", "theme": None, "topic": "", "photo_id": None}
    rec, _ = asyncio.run(link.issue("u_1", {**prep, "voice": "young"}))
    assert saved["voice"] == "young" and link.summary(rec)["voice"] == "young"
    rec, _ = asyncio.run(link.issue("u_1", prep))
    assert saved["voice"] == "default"
