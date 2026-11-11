"""
낭독 — Gemini TTS (실험)

tts.py 가 `TTS_PROVIDER=gemini` 일 때만 부른다. 기본은 여전히 Azure 다.

**왜 실험인가 — 숫자 셋** (tools/bench_tts.py, 2026-10-08)

    다 받을 때까지        2.0~2.9초   예산 1.6초를 매번 넘긴다
    스트리밍 첫 조각      0.9~1.1초   예산 안. 조각이 재생보다 빨리 온다
    하루 한도 (Tier 1)    모델당 100번 = 하루 7~10회차

그래서 서비스에 쓰려면 **스트리밍(tts.Speech)이어야 하고, 한도가 올라야 한다.**
한 번에 받는 synth() 는 폰에서 목소리를 들어 보는 시험용이다.

**말투 지시를 붙이지 않는다.** 이 모델들은 system_instruction 을 400 으로
거절하고, 문장 앞에 붙인 지시(한국어든 영어든)는 그대로 소리 내 읽는다
(bench_tts.py 의 STYLES). 말투는 목소리 이름에 맡긴다.

**429 를 맞으면 한동안 부르지 않는다.** 한도는 프로젝트 단위라 한 번 막히면
다음 질문도 막힌다. 매 질문 Gemini 를 두드리고 실패를 기다렸다가 Azure 로
넘어가면 그 왕복만큼 매번 늦는다. 막힌 동안은 곧장 Azure 로 간다 — 목소리가
질문마다 오락가락하지 않는 덕도 있다.
"""

from __future__ import annotations

import io
import logging
import re
import time
import wave
from typing import AsyncIterator

from .conf import env_str

log = logging.getLogger("tts")

DEFAULT_MODEL = "gemini-3.8-flash-lite-tts"   # 첫 조각이 flash 보다 0.15초 빠르다
DEFAULT_VOICE = "Kore"
PCM_RATE = 24000                               # 이 모델들이 내는 값. 조각 mime 에 따라온다

# 막혔을 때 쉬는 시간. 응답의 retryDelay 를 따르되 이 범위로 묶는다 —
# 하루 한도는 「18시간 뒤」를 주는데, 그동안 한도가 올라갈 수도 있다.
COOL_MIN, COOL_MAX = 60.0, 3600.0

_CLIENT = None
_cool_until = 0.0


def _client():
    key = env_str("GEMINI_API_KEY")
    if not key:
        return None
    global _CLIENT
    if _CLIENT is None:
        from google import genai
        _CLIENT = genai.Client(api_key=key)
    return _CLIENT


def available() -> bool:
    """키가 있고, 한도에 막혀 쉬는 중이 아니다."""
    return _client() is not None and time.monotonic() >= _cool_until


def _config():
    from google.genai import types
    return types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=env_str("GEMINI_TTS_VOICE", DEFAULT_VOICE)))))


def _model() -> str:
    return env_str("GEMINI_TTS_MODEL", DEFAULT_MODEL)


def note_failure(e: BaseException) -> None:
    """429 면 쉬기 시작한다. 다른 실패는 다음 질문에서 다시 해 본다."""
    if getattr(e, "code", None) != 429:
        return
    global _cool_until
    m = re.search(r"retryDelay['\"]?:\s*['\"](\d+)", str(e))
    wait = min(COOL_MAX, max(COOL_MIN, float(m.group(1)) if m else COOL_MIN))
    _cool_until = time.monotonic() + wait
    log.warning("Gemini TTS 한도 초과 — %.0f분 동안 Azure 로 읽는다", wait / 60)


def _rate(mime: str | None) -> int:
    m = re.search(r"rate=(\d+)", mime or "")
    return int(m.group(1)) if m else PCM_RATE


async def synth(text: str) -> tuple[bytes, int]:
    """
    한 번에 받는다. (PCM, rate). **이 모델들은 wav 로 준다** (fmt · data ·
    C2PA 출처 덩어리) — 머리를 벗겨 PCM 만 돌려준다. 날 PCM 이면 그대로.
    """
    client = _client()
    if client is None:
        raise RuntimeError("GEMINI_API_KEY 가 없다")
    res = await client.aio.models.generate_content(
        model=_model(), contents=text, config=_config())
    for part in res.candidates[0].content.parts:
        blob = getattr(part, "inline_data", None)
        if blob and blob.data:
            if blob.data[:4] == b"RIFF":
                with wave.open(io.BytesIO(blob.data)) as w:
                    return w.readframes(w.getnframes()), w.getframerate()
            return blob.data, _rate(blob.mime_type)
    raise RuntimeError("Gemini 응답에 오디오가 없다")


async def stream(text: str) -> AsyncIterator[tuple[bytes, int]]:
    """
    조각마다 (PCM, rate). 조각은 audio/l16 날 PCM 이고 40ms 남짓이다.

    실측에서 첫 조각 시각과 「끊김 없이 틀 수 있는 가장 이른 시각」이 같았다 —
    조각이 재생보다 빨리 온다. 그래서 받는 대로 흘려보내도 된다.
    """
    client = _client()
    if client is None:
        raise RuntimeError("GEMINI_API_KEY 가 없다")
    async for ch in await client.aio.models.generate_content_stream(
            model=_model(), contents=text, config=_config()):
        cand = ch.candidates[0] if ch.candidates else None
        for part in (cand.content.parts or []) if cand and cand.content else []:
            blob = getattr(part, "inline_data", None)
            if blob and blob.data:
                yield blob.data, _rate(blob.mime_type)
