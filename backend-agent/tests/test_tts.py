"""
낭독 갈래 검증 — 무음 깎기 · 흘려 읽기(Speech) · Gemini 가 막혔을 때 Azure

    python -m tests.test_tts

Gemini 와 Azure 는 부르지 않는다. tts_gemini.stream 과 tts._post 를 가짜로
바꿔 끼워, 「언제 무엇이 오는가」만 흉내 낸다.
"""

from __future__ import annotations

import array
import asyncio
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app.session import tts, tts_gemini                                 # noqa: E402
from app.session.controller import SessionController                    # noqa: E402

PASS, FAIL = [], []
RATE = 24000


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else '!! '}{name}{'  — ' + detail if detail else ''}")


def quiet(ms: int) -> bytes:
    return b"\x00\x00" * (RATE * ms // 1000)


def tone(ms: int, amp: int = 8000) -> bytes:
    n = RATE * ms // 1000
    return array.array("h", (int(amp * math.sin(2 * math.pi * 220 * i / RATE))
                             for i in range(n))).tobytes()


def chunks(pcm: bytes, ms: int = 40) -> list[bytes]:
    step = RATE * ms // 1000 * 2
    return [pcm[i:i + step] for i in range(0, len(pcm), step)]


def ms_of(pcm: bytes) -> float:
    return len(pcm) / 2 / RATE * 1000


def lead_ms(pcm: bytes) -> float:
    s = array.array("h", pcm)
    for i, v in enumerate(s):
        if abs(v) > tts.LOUD:
            return i / RATE * 1000
    return ms_of(pcm)


def tail_ms(pcm: bytes) -> float:
    s = array.array("h", pcm)
    for i in range(len(s) - 1, -1, -1):
        if abs(s[i]) > tts.LOUD:
            return (len(s) - 1 - i) / RATE * 1000
    return ms_of(pcm)


# ---------------------------------------------------------------- 무음 깎기

def test_trim():
    print("\n[1] 앞 무음은 걷고 끝 무음은 150ms 로 맞춘다")
    src = quiet(300) + tone(500) + quiet(120) + tone(300) + quiet(400)
    t = tts.Trim(RATE)
    out = b"".join(t.feed(c) for c in chunks(src)) + t.end()
    check("앞 무음이 40ms 안팎으로 줄었다", lead_ms(out) <= tts.LEAD_KEEP_MS + tts.FRAME_MS,
          f"{lead_ms(out):.0f}ms (원래 300ms)")
    check("끝 무음이 150ms 안팎이다",
          abs(tail_ms(out) - tts.TAIL_SILENCE_MS) <= tts.FRAME_MS + 5,
          f"{tail_ms(out):.0f}ms (원래 400ms)")
    check("말 사이 쉼은 그대로다", ms_of(out) >= 500 + 120 + 300,
          f"남은 길이 {ms_of(out):.0f}ms")

    t2 = tts.Trim(RATE)
    out2 = b"".join(t2.feed(c) for c in chunks(quiet(500))) + t2.end()
    check("무음뿐이면 아무것도 안 나간다", out2 == b"")

    # 조각 경계가 표본 중간에 걸려도 깨지지 않는다 (홀수 바이트)
    t3 = tts.Trim(RATE)
    raw = quiet(100) + tone(200) + quiet(300)
    out3 = b"".join(t3.feed(raw[i:i + 999]) for i in range(0, len(raw), 999)) + t3.end()
    check("홀수 바이트 조각도 짝수로 나간다", len(out3) % 2 == 0 and ms_of(out3) >= 200)


# ---------------------------------------------------------------- 가짜 끼우기

class Fake:
    """tts_gemini.stream · tts._post 를 바꿔 끼운다. 끝나면 되돌린다."""

    def __init__(self, gemini=None, azure=None, available=True):
        self.gemini, self.azure, self.available = gemini, azure, available
        self.calls = {"gemini": 0, "azure": 0}

    def __enter__(self):
        self.saved = (tts_gemini.stream, tts_gemini.available, tts._post, tts._creds)
        fake = self

        async def stream(text):
            fake.calls["gemini"] += 1
            async for x in fake.gemini(text):
                yield x

        async def post(key, region, text, fmt=None):
            fake.calls["azure"] += 1
            return await fake.azure(text)

        tts_gemini.stream = stream
        tts_gemini.available = lambda: fake.available
        tts._post = post
        tts._creds = lambda: ("k", "r")
        return self

    def __exit__(self, *a):
        tts_gemini.stream, tts_gemini.available, tts._post, tts._creds = self.saved
        tts_gemini._cool_until = 0.0


async def gemini_ok(text):
    await asyncio.sleep(0.05)
    for c in chunks(quiet(200) + tone(600) + quiet(300)):
        yield c, RATE
        await asyncio.sleep(0.005)


async def azure_ok(text):
    await asyncio.sleep(0.02)
    return quiet(100) + tone(400) + quiet(150)


class Quota(Exception):
    code = 429

    def __str__(self):
        return "429 RESOURCE_EXHAUSTED {'retryDelay': '120s'}"


async def gemini_429(text):
    raise Quota()
    yield  # noqa: unreachable — 비동기 생성기로 만든다


async def gemini_silent(text):
    await asyncio.sleep(5)
    yield quiet(40), RATE


async def gemini_breaks(text):
    for c in chunks(tone(400))[:5]:
        yield c, RATE
    raise RuntimeError("연결이 끊겼다")


async def collect(sp: tts.Speech) -> bytes:
    return b"".join([c async for c in sp.iter_chunks()])


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- 흘려 읽기

def test_speech_gemini():
    print("\n[2] Gemini 가 읽으면 조각이 오는 대로 나간다")

    async def go():
        with Fake(gemini=gemini_ok, azure=azure_ok) as f:
            t0 = time.perf_counter()
            sp = tts.Speech.start("질문")
            got_first = await sp.wait_first(2)
            first = (time.perf_counter() - t0) * 1000
            a, b = await asyncio.gather(collect(sp), collect(sp))
            return sp, f, got_first, first, a, b

    sp, f, got_first, first, a, b = run(go())
    check("첫 소리가 온다", got_first, f"{first:.0f}ms")
    check("읽은 쪽이 gemini", sp.source == "gemini")
    check("Azure 는 부르지 않았다", f.calls["azure"] == 0)
    check("받는 쪽이 둘이어도 둘 다 처음부터 끝까지", a == b == sp.pcm() and len(a) > 0)
    check("앞 무음이 깎였다", lead_ms(a) <= tts.LEAD_KEEP_MS + tts.FRAME_MS,
          f"{lead_ms(a):.0f}ms")
    check("끝 무음이 150ms 안팎", abs(tail_ms(a) - tts.TAIL_SILENCE_MS) <= tts.FRAME_MS + 5,
          f"{tail_ms(a):.0f}ms")
    check("조각이 여럿이다 — 한 덩어리로 모으지 않았다", len(sp.chunks) > 3,
          f"{len(sp.chunks)}개")


def test_speech_fallback():
    print("\n[3] Gemini 가 첫 소리 전에 막히면 Azure 가 대신 읽는다")

    async def quota():
        with Fake(gemini=gemini_429, azure=azure_ok) as f:
            sp = tts.Speech.start("질문")
            pcm = await collect(sp)
            cooled = tts_gemini._cool_until > time.monotonic()
            return sp, f, pcm, cooled

    sp, f, pcm, cooled = run(quota())
    check("429 → Azure 가 읽었다", sp.source == "azure" and len(pcm) > 0)
    check("429 면 한동안 Gemini 를 쉰다", cooled, "다음 질문은 곧장 Azure")

    async def slow(monkey_first=0.3):
        import os
        os.environ["GEMINI_TTS_FIRST_TIMEOUT"] = str(monkey_first)
        try:
            with Fake(gemini=gemini_silent, azure=azure_ok):
                t0 = time.perf_counter()
                sp = tts.Speech.start("질문")
                pcm = await collect(sp)
                return sp, pcm, (time.perf_counter() - t0) * 1000
        finally:
            os.environ.pop("GEMINI_TTS_FIRST_TIMEOUT", None)

    sp, pcm, ms = run(slow())
    check("첫 소리가 늦으면 Azure 로 넘어간다", sp.source == "azure" and len(pcm) > 0,
          f"{ms:.0f}ms 에 끝남 (첫 소리 예산 300ms)")

    async def breaks():
        with Fake(gemini=gemini_breaks, azure=azure_ok) as f:
            sp = tts.Speech.start("질문")
            pcm = await collect(sp)
            return sp, f, pcm

    sp, f, pcm = run(breaks())
    check("읽다 끊기면 받은 데까지만 — 다른 목소리로 다시 읽지 않는다",
          sp.source == "gemini" and f.calls["azure"] == 0 and len(pcm) > 0)

    async def cancelled():
        with Fake(gemini=gemini_silent, azure=azure_ok):
            sp = tts.Speech.start("질문")
            reader = asyncio.create_task(collect(sp))
            await asyncio.sleep(0.05)
            sp.cancel()
            return await asyncio.wait_for(reader, 1.0)

    try:
        pcm = run(cancelled())
        check("취소하면 받는 쪽도 풀린다", pcm == b"")
    except asyncio.TimeoutError:
        check("취소하면 받는 쪽도 풀린다", False, "화면 요청이 매달린다")


# ---------------------------------------------------------------- 컨트롤러

def test_controller_stream():
    print("\n[4] 흘려 읽는 회차 — 스냅샷과 파일 받기")

    async def go():
        with Fake(gemini=gemini_ok, azure=azure_ok):
            ctl = SessionController(user_id="t", title="시험", pace="fast",
                                    stream_fn=tts.Speech.start)
            await ctl.start("씨앗")
            snap = ctl.snapshot()
            sp = ctl.question_speech()
            wav = await ctl.question_audio(wait=2)
            await asyncio.sleep(0.05)
            spoken = ctl.marks.spoken_at
            ctl.release()
            return snap, sp, wav, spoken

    snap, sp, wav, spoken = run(go())
    check("스냅샷이 흘려 읽기를 알린다", snap["question_audio_stream"] is True)
    check("소리가 온다고 알린다", snap["question_audio"] is True)
    check("지금 낭독을 꺼낼 수 있다", sp is not None and sp.text == snap["next_question"])
    check("파일로 달라면 wav 로 준다 (소리 시험 버튼)", wav[:4] == b"RIFF" and len(wav) > 44)
    check("첫 소리 시각이 적힌다", spoken > 0)

    async def default():
        ctl = SessionController(user_id="t", title="시험", pace="fast")
        snap = ctl.snapshot()
        ctl.release()
        return ctl, snap

    ctl, snap = run(default())
    check("기본은 예전 길 — stream_fn 이 없다", ctl.stream_fn is None,
          "TTS_STREAM 을 안 켜면 Azure mp3 한 덩어리")
    check("기본 스냅샷은 흘려 읽기 아님", snap["question_audio_stream"] is False)


def test_provider_env():
    print("\n[5] 환경변수 — 켜는 쪽만 인정한다")
    import os
    saved = {k: os.environ.get(k) for k in ("TTS_PROVIDER", "TTS_STREAM")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        check("아무것도 없으면 azure", tts.provider() == "azure" and not tts.streaming())
        os.environ["TTS_STREAM"] = "1"
        check("TTS_STREAM 만으로는 안 켜진다 — Azure 는 흘릴 까닭이 없다", not tts.streaming())
        os.environ["TTS_PROVIDER"] = "Gemini"
        check("gemini + 1 → 흘려 읽기", tts.provider() == "gemini" and tts.streaming())
        os.environ["TTS_STREAM"] = "ture"
        check("오타는 꺼진 것으로", not tts.streaming())
        check("stream_factory 는 꺼지면 None", tts.stream_factory() is None)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_all_passed():
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 낭독 갈래 검증")
    test_trim()
    test_speech_gemini()
    test_speech_fallback()
    test_controller_stream()
    test_provider_env()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
