"""
낭독을 Gemini 로 바꾸면 어떤가 — Azure 와 같은 질문으로 잰다

    azure    지금. SSML · ko-KR-SunHiNeural · -8% · 끝 무음 150ms · mp3
    gemini   generateContent(response_modalities=AUDIO) · PCM 24kHz

**예산이 먼저다.** 낭독은 T2 최솟값 3초에서 질문 생성이 쓰고 남은 1.6초 안에
끝나야 한다 (tts.py DEFAULT_TIMEOUT). 넘기면 소리 없이 글자만 나간다. 그래서
지연은 평균이 아니라 **1.6초를 넘긴 비율**로 본다.

재는 것 넷.
  · 지연    응답을 다 받을 때까지. p50 · p90 · 1.6초 초과 비율
  · 크기    폰이 받아 가는 바이트. Gemini 는 PCM 이라 wav 로 센다
  · 무음    앞·끝 무음(ms). 끝이 길면 그동안 어르신 말씀의 앞머리가 녹음에
            못 들어간다 (tts._ssml 주석). Azure 는 SSML 로 150ms 에 맞춰 두었다
  · 충실도  만든 소리를 Azure 로 다시 받아 적어 원문과의 CER. 생성형 TTS 는
            낱말을 빼거나 바꾸고, 지시문까지 읽기도 한다. 화면의 글자와 귀의
            말이 다르면 안 된다

소리는 tools/recordings/tts/ 에 남긴다 (.gitignore). 숫자로 안 되는 것 —
억양, 한국어 발음, 어르신께 들리는 느낌 — 은 들어 보고 고른다.

    python tools/bench_tts.py
    python tools/bench_tts.py --models gemini-3.8-flash-tts --voices Kore,Aoede --rounds 2
"""

from __future__ import annotations

import argparse
import array
import asyncio
import io
import math
import os
import re
import statistics
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv                                    # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.session import stt, tts                                   # noqa: E402
from app.session.audio import pcm16_to_wav                         # noqa: E402

BUDGET = tts.DEFAULT_TIMEOUT
OUT = Path(__file__).resolve().parent / "recordings" / "tts"

# 인터뷰 에이전트가 실제로 내는 모양의 질문. 짧은 것·긴 것·숫자·이름·감정을 섞었다.
QUESTIONS = [
    "오늘은 어떤 이야기를 들려주시겠어요?",
    "지난 여름 바닷가에 가셨군요. 어떤 일이 있었는지 들려주세요.",
    "마음이 많이 아프셨겠어요. 바닷가에서 어떤 기억이 남았나요?",
    "새로운 만남이 있으셨군요. 그때 그 분을 만나고 어떤 기분이 드셨나요?",
    "1968년 여름에 서울 가는 완행열차를 타셨군요. 그때 누구와 함께 가셨어요?",
    "순애 씨는 어떤 분이셨어요?",
    "처음 서울에 도착했을 때 가장 먼저 눈에 들어온 것이 무엇이었나요?",
    "그 시절 하루 일과는 어땠는지 아침부터 차근차근 말씀해 주시겠어요?",
    "아버님께서 그런 말씀을 하셨을 때 어떤 마음이 드셨어요?",
    "고생이 참 많으셨네요. 그래도 그때 힘이 되어 준 사람이 있었나요?",
    "첫째 아드님이 태어난 날을 기억하세요?",
    "그 집에서는 몇 년 정도 사셨어요?",
    "사진 속 이 장소는 어디인가요?",
    "함께 웃고 계신 분들은 누구인지 여쭤봐도 될까요?",
    "그 일을 그만두셨을 때 아쉬움은 없으셨어요?",
    "지금 돌아보시면 그 결정이 어떻게 느껴지세요?",
    "오늘 들려주신 이야기 중에 꼭 남기고 싶은 장면이 있으세요?",
    "말씀 정말 고맙습니다. 오늘 이야기는 여기서 마무리할까요?",
]

# 말투를 어떻게 건네는가. 지시와 읽을 문장이 한 덩어리로 가므로, 모델이 지시까지
# 소리 내 읽는 일이 생긴다 — 그걸 잡으려고 갈래를 나눠 잰다.
#   long   지시문 + 따옴표 문장       (첫 시험: 지시문까지 다 읽었다)
#   colon  「말투: 문장」 한 줄        (Gemini 문서의 예시 꼴)
#   none   문장만                      (말투는 목소리 이름에 맡긴다)
STYLES = {
    "long": ("다음 한국어 문장을 어르신께 여쭙듯 차분하고 따뜻한 목소리로, "
             "조금 천천히 읽어 주세요. 따옴표 안의 문장만 읽고 다른 말은 덧붙이지 마세요."
             "\n\n\"{text}\""),
    "colon": "차분하고 따뜻하게, 조금 천천히 말해 주세요: {text}",
    "none": "{text}",
    # 지시는 영어, 읽을 문장은 한국어 — 언어가 갈리면 지시를 읽지 않을까.
    # system_instruction 은 이 모델들이 받지 않는다 (400 Developer instruction is not enabled).
    "en": "Say in a calm, warm, slightly slow voice, as if gently asking an elderly person: {text}",
}


# ---------------------------------------------------------------- 소리 재기


def _cer(ref: str, hyp: str) -> float:
    """글자 오류율. 공백과 문장부호는 떼고 센다 (bench_audio.py 와 같다)."""
    drop = " \t\n.,?!…·~-—\"'「」『』()"
    a = [c for c in ref if c not in drop]
    b = [c for c in hyp if c not in drop]
    if not a:
        return 0.0 if not b else 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / len(a)


def _silence_ms(pcm: bytes, rate: int, frame_ms: int = 10) -> tuple[float, float, float]:
    """(앞 무음, 끝 무음, 전체 길이) ms. 가장 큰 프레임의 3% 아래를 무음으로 본다."""
    s = array.array("h", pcm[: len(pcm) // 2 * 2])
    n = max(1, rate * frame_ms // 1000)
    rms = [math.sqrt(sum(x * x for x in s[i:i + n]) / max(1, len(s[i:i + n])))
           for i in range(0, len(s), n)]
    if not rms:
        return 0.0, 0.0, 0.0
    floor = max(rms) * 0.03
    loud = [i for i, r in enumerate(rms) if r > floor]
    total = len(s) / rate * 1000
    if not loud:
        return total, total, total
    return loud[0] * frame_ms, (len(rms) - 1 - loud[-1]) * frame_ms, total


# ---------------------------------------------------------------- 합성


async def azure(text: str, voice: str) -> tuple[bytes, str]:
    cred = tts._creds()
    if not cred:
        raise RuntimeError("AZURE_SPEECH_KEY/REGION 없음")
    data = await tts._post(*cred, text)
    if not data:
        raise RuntimeError("Azure 가 빈 응답")
    return data, "audio/mpeg"


_GENAI = None


def _genai():
    global _GENAI
    if _GENAI is None:
        from google import genai
        _GENAI = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _GENAI


async def gemini(text: str, model: str, voice: str, style: str) -> tuple[bytes, bytes, int]:
    """
    (그대로 보낼 바이트, PCM, rate). **이 모델들은 이미 wav 를 준다** (audio/wav,
    fmt · data · C2PA 출처 표시 덩어리). 날 PCM(audio/L16)이 오면 그때만 감싼다.
    """
    from google.genai import types
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))))
    res = await _genai().aio.models.generate_content(
        model=model, contents=STYLES[style].format(text=text), config=cfg)
    for part in res.candidates[0].content.parts:
        blob = getattr(part, "inline_data", None)
        if blob and blob.data:
            if blob.data[:4] == b"RIFF":
                with wave.open(io.BytesIO(blob.data)) as w:
                    return blob.data, w.readframes(w.getnframes()), w.getframerate()
            m = re.search(r"rate=(\d+)", blob.mime_type or "")
            rate = int(m.group(1)) if m else 24000
            return pcm16_to_wav(blob.data, rate), blob.data, rate
    raise RuntimeError("Gemini 응답에 오디오가 없다")


# ---------------------------------------------------------------- 한 갈래


async def run(name: str, synth, questions: list[str], rounds: int, gap: float,
              check: bool) -> dict:
    """synth(text) -> (wav 또는 mp3 바이트, mime, pcm, rate|None)."""
    folder = OUT / re.sub(r"[^\w.-]+", "_", name)
    folder.mkdir(parents=True, exist_ok=True)

    # 예열 — 첫 호출의 연결·모델 깨우기는 재지 않는다 (tts.warmup 과 같은 이유).
    try:
        await synth("안녕하세요")
    except Exception as e:                                   # noqa: BLE001
        print(f"  [{name}] 예열 실패: {type(e).__name__}: {str(e)[:160]}")

    lat, size, lead, tail, dur, cers, fails = [], [], [], [], [], [], 0
    for r in range(rounds):
        for i, q in enumerate(questions):
            t0 = time.perf_counter()
            try:
                data, mime, pcm, rate = await synth(q)
            except Exception as e:                           # noqa: BLE001
                fails += 1
                print(f"  [{name}] {i:02d} 실패: {type(e).__name__}: {str(e)[:160]}")
                await asyncio.sleep(gap)
                continue
            ms = (time.perf_counter() - t0) * 1000
            lat.append(ms)
            size.append(len(data))
            if pcm is not None:
                a, b, d = _silence_ms(pcm, rate)
                lead.append(a), tail.append(b), dur.append(d)
            ext = "mp3" if mime == "audio/mpeg" else "wav"
            if r == 0:
                (folder / f"{i:02d}.{ext}").write_bytes(data)
                if check:
                    heard = await stt.azure_transcribe(data, mime)
                    c = _cer(q, heard)
                    cers.append(c)
                    if c > 0.15:
                        print(f"  [{name}] {i:02d} CER {c:.0%}\n      원문 {q}\n      들림 {heard}")
            await asyncio.sleep(gap)

    def pct(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else float("nan")

    return dict(
        name=name, n=len(lat), fails=fails,
        p50=pct(lat, .5), p90=pct(lat, .9), mx=max(lat, default=float("nan")),
        over=sum(x > BUDGET * 1000 for x in lat) / len(lat) if lat else float("nan"),
        kb=statistics.mean(size) / 1024 if size else float("nan"),
        lead=statistics.mean(lead) if lead else None,
        tail=statistics.mean(tail) if tail else None,
        tail_max=max(tail) if tail else None,
        sec=statistics.mean(dur) / 1000 if dur else None,
        cer=statistics.mean(cers) if cers else None,
        bad=sum(c > 0.15 for c in cers),
    )


def table(rows: list[dict]) -> None:
    def f(v, fmt):
        return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else format(v, fmt)
    print(f"\n예산 {BUDGET:.1f}s · 지연은 응답을 다 받을 때까지\n")
    head = (f"{'갈래':<44}{'n':>4}{'실패':>5}{'p50':>8}{'p90':>8}{'최대':>8}"
            f"{'초과':>7}{'KB':>7}{'길이s':>7}{'앞ms':>7}{'끝ms':>7}{'끝최대':>8}{'CER':>7}{'틀림':>5}")
    print(head)
    print("-" * len(head.encode("cp949", "replace")))
    for r in rows:
        print(f"{r['name']:<44}{r['n']:>4}{r['fails']:>5}{f(r['p50'], '.0f'):>8}"
              f"{f(r['p90'], '.0f'):>8}{f(r['mx'], '.0f'):>8}{f(r['over'], '.0%'):>7}"
              f"{f(r['kb'], '.0f'):>7}{f(r['sec'], '.1f'):>7}{f(r['lead'], '.0f'):>7}"
              f"{f(r['tail'], '.0f'):>7}{f(r['tail_max'], '.0f'):>8}"
              f"{f(r['cer'], '.1%'):>7}{r['bad']:>5}")
    print("\nAzure 의 앞·끝 무음은 mp3 라 재지 않는다 — SSML 로 끝 150ms 에 맞춰 두었다.")
    print(f"소리: {OUT}")


async def main_async(a) -> int:
    questions = QUESTIONS[: a.limit] if a.limit else QUESTIONS
    rows = []

    if not a.no_azure:
        voice = os.environ.get("AZURE_TTS_VOICE") or tts.DEFAULT_VOICE

        async def s_az(text):
            data, mime = await azure(text, voice)
            return data, mime, None, None
        print(f"azure · {voice}")
        rows.append(await run(f"azure/{voice}", s_az, questions, a.rounds, a.gap, a.check))

    for model in [m for m in a.models.split(",") if m]:
        for voice in [v for v in a.voices.split(",") if v]:
            for style in [x for x in a.styles.split(",") if x]:
                async def s_gm(text, model=model, voice=voice, style=style):
                    data, pcm, rate = await gemini(text, model, voice, style)
                    return data, "audio/wav", pcm, rate
                name = f"{model}/{voice}/{style}"
                print(name)
                rows.append(await run(name, s_gm, questions, a.rounds, a.gap, a.check))

    table(rows)
    await tts.aclose()
    await stt.aclose()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gemini-3.8-flash-tts,gemini-3.8-flash-lite-tts")
    ap.add_argument("--voices", default="Kore")
    ap.add_argument("--styles", default="colon,none", help=",".join(STYLES))
    ap.add_argument("--rounds", type=int, default=2,
                    help="질문 목록을 몇 번 돌릴지. 소리와 CER 은 첫 판만 본다")
    ap.add_argument("--gap", type=float, default=1.0,
                    help="호출 사이 쉬는 초. 무료 티어 분당 한도에 걸리지 않게")
    ap.add_argument("--limit", type=int, default=0, help="질문 앞에서 몇 개만")
    ap.add_argument("--no-azure", action="store_true")
    ap.add_argument("--no-check", dest="check", action="store_false",
                    help="Azure 로 되받아 적는 충실도 검사를 끈다")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
