"""
제미나이가 직접 들으면 어떤가 — 두 길을 같은 녹음으로 잰다

    A (지금)  오디오 → Azure 전사 → Gemini 질문            호출 2회
    B (제안)  오디오 → Gemini (전사 + 질문 한 번에)        호출 1회
    C (절충)  오디오 → Azure 전사 ┐
                      오디오 ────┴→ Gemini 질문          호출 2회

B 가 매력적인 이유는 왕복이 하나 줄어서만이 아니다. Azure 는 글자만 넘긴다 —
머뭇거림, 떨리는 목소리, 말끝을 흐리는 것은 글이 되는 순간 사라진다. 어르신의
이야기를 듣는 일에서 그게 정말 버려도 되는 것인지는 재봐야 안다.

B 가 져도 알아낼 것이 있다. **B 의 전사 품질은 「Gemini 가 오디오를 얼마나
알아듣는가」의 하한**이고, 그 값에 따라 나중에 감정·머뭇거림을 곁들여 쓰는 길이
열릴지 닫힐지가 갈린다.

재는 것 셋.
  · 지연 — 예산은 T2 최솟값 3초다. 여기 안 들어가면 어르신이 기다림을 느낀다
  · 전사 — Azure 의 결과와 얼마나 다른가 (CER). Azure 가 정답이라는 뜻은 아니고,
           지난 측정에서 실제 목소리에 가장 가까웠던 기준선이라는 뜻이다
  · 질문 — 숫자로 안 되는 것. 그대로 찍어서 눈으로 본다

C 는 B 가 왜 매력적이었는지를 가져오면서 대가는 치르지 않는 길이다. 글자는
Azure 가 정확히 넘기고, 목소리는 그대로 함께 간다. 호출 수는 A 와 같고, 오디오가
프롬프트에 얹히는 만큼만 느려진다. 그 「만큼」이 얼마인지가 이 시험의 값이다.
"""

from __future__ import annotations

import argparse
import array
import asyncio
import json
import math
import os
import statistics
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv                                    # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.session import stt                                        # noqa: E402
from app.session.audio import pcm16_to_wav                         # noqa: E402

SEED = "1968년 여름, 순애랑 서울 가는 완행열차를 탔다."
CHUNK_SEC = 1.0
SILENCE_RATIO = 0.08

# B 는 전사까지 돌려줘야 한다. 조각(fragment.answer)으로 DB 에 내려가는 값이라
# 질문만 받아서는 지금 구조를 대체할 수 없다.
_SYSTEM_B = """당신은 어르신의 인생 이야기를 듣는 인터뷰어입니다.
첨부된 음성은 어르신이 방금 하신 말씀입니다. 듣고 두 가지를 하세요.

1. 말씀을 그대로 받아적습니다. 고치거나 다듬지 않습니다.
2. 그 말씀에 이어, 그 기억을 더 선명하게 떠올리실 수 있는 질문을 하나만 합니다.

질문 규칙:
- 한 문장, 존댓말, 40자 이내.
- 사실 확인이 아니라 감각과 마음을 묻습니다.
- 이미 하신 질문과 겹치지 않게 합니다.
- 이야기가 충분히 마무리되었다면 close 를 고릅니다.

반드시 아래 JSON 으로만 답하세요.
{"transcript": "들으신 그대로", "action": "ask", "question": "질문 한 문장", "reason": "짧게"}
{"transcript": "들으신 그대로", "action": "close", "question": null, "reason": "짧게"}"""


def _voiced_wav(path: Path) -> bytes:
    """replay.py 와 같은 무음 제거. 서버에 실제로 닿는 것과 같은 소리를 만든다."""
    with wave.open(str(path)) as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise SystemExit(f"{path.name}: 16bit wav 만 받는다")
    s = array.array("h")
    s.frombytes(raw)
    per = int(sr * CHUNK_SEC) * ch
    blocks = [s[i:i + per] for i in range(0, len(s), per)]
    rms = [math.sqrt(sum(int(x) * int(x) for x in b) / len(b)) if len(b) else 0.0 for b in blocks]
    floor = (max(rms) or 1.0) * SILENCE_RATIO
    kept = array.array("h")
    for b, r in zip(blocks, rms):
        if r > floor:
            kept.extend(b)
    return pcm16_to_wav(kept.tobytes(), sr, ch)


def _cer(ref: str, hyp: str) -> float:
    """글자 오류율. 공백과 문장부호는 떼고 센다 — 뜻이 달라지는 자리가 아니다."""
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


_CLIENT = None


def _client():
    """
    **한 번만 만들어 재사용한다.** 호출마다 새로 만들면 TLS 악수가 매번 지연에
    섞여 들어간다. 앱(question.py)은 재사용하므로, 여기서 새로 만들면 앱보다
    느린 숫자를 재고 잘못된 결론을 낸다. 처음 이렇게 재서 A 의 p90 이 3002ms 로
    나왔고, 예산 초과로 읽을 뻔했다.
    """
    global _CLIENT
    if _CLIENT is None:
        key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if not key:
            raise SystemExit("GEMINI_API_KEY 가 없다")
        from google import genai
        _CLIENT = genai.Client(api_key=key)
    return _CLIENT


async def _path_a(audio: bytes, history: str) -> tuple[float, str, str, str]:
    """오디오 → Azure → Gemini. 지금 앱이 하는 그대로."""
    from app.session import question as q

    t0 = time.perf_counter()
    text = await stt.azure_transcribe(audio, "audio/wav", None)
    t_stt = time.perf_counter()

    client = _client()
    from google.genai import types
    cfg = types.GenerateContentConfig(
        system_instruction=q._SYSTEM,
        response_mime_type="application/json",
        temperature=1.0, max_output_tokens=200,
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    res = await client.aio.models.generate_content(
        model=os.environ.get("GEMINI_MODEL") or q.DEFAULT_MODEL,
        contents=f"{history}\n어르신: {text}".strip(), config=cfg)
    t1 = time.perf_counter()
    d = json.loads((res.text or "{}").strip())
    return ((t1 - t0) * 1000, text, d.get("question") or "(마무리)",
            f"전사 {(t_stt - t0) * 1000:.0f} + 질문 {(t1 - t_stt) * 1000:.0f}")


async def _path_b(audio: bytes, history: str, model: str) -> tuple[float, str, str, str]:
    """오디오 → Gemini 한 번. 전사와 질문을 함께 받는다."""
    client = _client()
    from google.genai import types
    cfg = types.GenerateContentConfig(
        system_instruction=_SYSTEM_B,
        response_mime_type="application/json",
        temperature=1.0, max_output_tokens=400,
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    parts = [types.Part.from_bytes(data=audio, mime_type="audio/wav")]
    if history:
        parts.insert(0, types.Part.from_text(text=f"지금까지의 대화:\n{history}"))
    t0 = time.perf_counter()
    res = await client.aio.models.generate_content(
        model=model, contents=[types.Content(role="user", parts=parts)], config=cfg)
    t1 = time.perf_counter()
    d = json.loads((res.text or "{}").strip())
    return ((t1 - t0) * 1000, (d.get("transcript") or "").strip(),
            d.get("question") or "(마무리)", "한 번")


_SYSTEM_C = """당신은 어르신의 인생 이야기를 듣는 인터뷰어입니다.
첨부된 음성은 어르신이 방금 하신 말씀이고, 글로 옮긴 것도 함께 드립니다.
**사람 이름·땅 이름 같은 말은 글 쪽이 정확합니다.** 음성은 목소리와 머뭇거림,
말끝의 여운을 읽는 데 쓰세요.

방금 하신 말씀에 이어, 그 기억을 더 선명하게 떠올리실 수 있는 질문을 하나만 하세요.

규칙:
- 한 문장, 존댓말, 40자 이내.
- 사실 확인이 아니라 감각과 마음을 묻습니다.
- 이미 하신 질문과 겹치지 않게 합니다.
- 이야기가 충분히 마무리되었다면 close 를 고릅니다.

반드시 아래 JSON 으로만 답하세요.
{"action": "ask", "question": "질문 한 문장", "reason": "짧게"}
{"action": "close", "question": null, "reason": "짧게"}"""


async def _path_c(audio: bytes, history: str, model: str) -> tuple[float, str, str, str]:
    """오디오 → Azure 전사, 그리고 오디오와 전사를 함께 Gemini 로."""
    client = _client()
    from google.genai import types

    t0 = time.perf_counter()
    text = await stt.azure_transcribe(audio, "audio/wav", None)
    t_stt = time.perf_counter()

    cfg = types.GenerateContentConfig(
        system_instruction=_SYSTEM_C,
        response_mime_type="application/json",
        temperature=1.0, max_output_tokens=200,
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    parts = [
        types.Part.from_text(text=f"""{history}
어르신(글로 옮긴 것): {text}""".strip()),
        types.Part.from_bytes(data=audio, mime_type="audio/wav"),
    ]
    res = await client.aio.models.generate_content(
        model=model, contents=[types.Content(role="user", parts=parts)], config=cfg)
    t1 = time.perf_counter()
    d = json.loads((res.text or "{}").strip())
    return ((t1 - t0) * 1000, text, d.get("question") or "(마무리)",
            f"전사 {(t_stt - t0) * 1000:.0f} + 질문 {(t1 - t_stt) * 1000:.0f}")


def _stat(xs: list[float]) -> str:
    xs = sorted(xs)
    p90 = xs[min(len(xs) - 1, int(len(xs) * 0.9))]
    return f"중앙 {statistics.median(xs):6.0f} · p90 {p90:6.0f} · 최소 {xs[0]:6.0f} · 최대 {xs[-1]:6.0f}"


async def run(a) -> int:
    files = sorted(Path(a.dir).glob(a.glob))
    if not files:
        print(f"{a.dir}/{a.glob} 에 녹음이 없다")
        return 1

    clips = [(p, _voiced_wav(p)) for p in files]
    print(f"녹음 {len(clips)}개 · 각 {a.rounds}회 · B 모델 {a.model}\n")

    await stt.warmup()
    # 두 길 모두 한 번씩 버린다. 첫 호출에는 TLS 악수가 섞여 있다.
    try:
        await _path_a(clips[0][1], "")
        await _path_b(clips[0][1], "", a.model)
        await _path_c(clips[0][1], "", a.model)
    except Exception as e:                                        # noqa: BLE001
        print(f"B 예열 실패 — {type(e).__name__}: {e}")
        print("이 모델이 오디오를 받지 않는 것일 수 있다. --model 로 바꿔 본다.")
        return 1

    lat: dict[str, list[float]] = {"A": [], "B": [], "C": []}
    cers: list[float] = []
    for p, audio in clips:
        sec = (len(audio) - 44) / 32000
        print(f"── {p.name}  소리 {sec:.1f}초")
        ref = ""
        for r in range(a.rounds):
            hist = f"질문: {SEED}"
            ms_a, txt_a, q_a, split = await _path_a(audio, hist)
            lat["A"].append(ms_a)
            if not ref:
                ref = txt_a
            try:
                ms_b, txt_b, q_b, _ = await _path_b(audio, hist, a.model)
            except Exception as e:                                # noqa: BLE001
                print(f"   B 실패 — {type(e).__name__}: {e}")
                await asyncio.sleep(a.gap)
                continue
            lat["B"].append(ms_b)
            cer = _cer(ref, txt_b)
            cers.append(cer)

            ms_c, _, q_c, split_c = await _path_c(audio, hist, a.model)
            lat["C"].append(ms_c)

            if r == 0:
                print(f"   A {ms_a:6.0f}ms ({split})")
                print(f"     전사  {txt_a}")
                print(f"     질문  {q_a}")
                print(f"   B {ms_b:6.0f}ms (한 번)")
                print(f"     전사  {txt_b}   [Azure 와의 차이 {cer * 100:.1f}%]")
                print(f"     질문  {q_b}")
                print(f"   C {ms_c:6.0f}ms ({split_c})  전사는 A 와 같다")
                print(f"     질문  {q_c}")
            else:
                print(f"   A {ms_a:6.0f}  B {ms_b:6.0f}  C {ms_c:6.0f}   B차이 {cer * 100:4.1f}%")
            await asyncio.sleep(a.gap)
        print()

    print("지연 (ms)")
    for k in ("A", "B", "C"):
        if lat[k]:
            print(f"  {k}  {_stat(lat[k])}   n={len(lat[k])}")
    if cers:
        print(f"\n전사  B 와 Azure 의 차이 중앙 {statistics.median(cers) * 100:.1f}% "
              f"· 최대 {max(cers) * 100:.1f}%")
    print("\n  예산은 T2 최솟값 3000ms. p90 이 그 안에 들어와야 침묵에 숨는다.")
    await stt.aclose()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="tools/recordings")
    ap.add_argument("--glob", default="turn*.wav")
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--gap", type=float, default=2.0,
                    help="호출 사이 간격. Azure 가 429 를 낸다 (README 참조)")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
