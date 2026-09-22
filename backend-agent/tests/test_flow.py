"""
상태 머신 · 타이머 검증

    python -m tests.test_flow
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows 콘솔은 기본이 cp949 라 한글 출력에서 UnicodeEncodeError 로 죽는다.
# 검증이 실패한 게 아니라 첫 print 에서 터지는 것이라 원인을 찾기 어렵다. 여기서 막는다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app.session import audio as audiolib                                # noqa: E402
from app.session.controller import MAX_EMPTY_RETRY, SessionController   # noqa: E402
from app.session.machine import Event, Machine, State, TransitionError   # noqa: E402
from app.session.timers import T2_PRESETS                                # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else '!! '}{name}{'  — ' + detail if detail else ''}")


# ---------------------------------------------------------------- 상태 머신

def test_machine():
    print("\n[1] 상태 전이")
    m = Machine()
    check("시작은 SPEAKING", m.state is State.SPEAKING)
    check("낭독 끝 → LISTENING", m.fire(Event.TTS_DONE) is State.LISTENING)
    check("발화 수신은 자기 전이", m.fire(Event.SPEECH_RECEIVED) is State.LISTENING)
    check("T1 만료 → PROCESSING", m.fire(Event.T1_EXPIRED) is State.PROCESSING)
    check("턴이 1 올라감", m.turn == 1)

    print("\n[2] PROCESSING 은 두 조건이 모두 참일 때만 나간다")
    check("질문만 준비 → 머문다", m.fire(Event.QUESTION_READY) is State.PROCESSING)
    check("T2 까지 만료 → SPEAKING", m.fire(Event.T2_EXPIRED) is State.SPEAKING)

    m2 = Machine()
    m2.fire(Event.TTS_DONE); m2.fire(Event.T1_EXPIRED)
    check("T2 먼저 만료 → 머문다", m2.fire(Event.T2_EXPIRED) is State.PROCESSING,
          "질문이 늦으면 지연이 그대로 드러난다")
    check("질문 도착 → SPEAKING", m2.fire(Event.QUESTION_READY) is State.SPEAKING)

    print("\n[3] 빈 전사는 턴을 소모하지 않는다")
    m3 = Machine()
    m3.fire(Event.TTS_DONE); m3.fire(Event.T1_EXPIRED)
    check("확정 시 턴 1", m3.turn == 1)
    check("빈 전사 → LISTENING 복귀", m3.fire(Event.EMPTY_TRANSCRIPT) is State.LISTENING)
    check("턴이 되돌아감", m3.turn == 0, "무음이 반복돼도 턴이 소진되지 않는다")

    print("\n[4] 턴 제한 — 준 회차만 걸린다")
    m4 = Machine(max_turn=2)
    for _ in range(2):
        m4.fire(Event.TTS_DONE); m4.fire(Event.T1_EXPIRED)
        m4.fire(Event.QUESTION_READY); m4.fire(Event.T2_EXPIRED)
    check("2턴 뒤 CLOSED", m4.state is State.CLOSED, f"turn={m4.turn}")

    # 기본값은 제한 없음이다. 대화를 끝내는 것은 턴 수가 아니라 AI 의 close 판단이다.
    m4b = Machine()
    for _ in range(8):
        m4b.fire(Event.TTS_DONE); m4b.fire(Event.T1_EXPIRED)
        m4b.fire(Event.QUESTION_READY); m4b.fire(Event.T2_EXPIRED)
    check("제한이 없으면 8턴 뒤에도 살아 있다",
          m4b.state is State.SPEAKING and m4b.turn == 8, f"turn={m4b.turn}")
    check("제한 없음은 turns_left -1", m4b.turns_left == -1,
          "0 은 「이번이 마지막」이라는 뜻이라 쓸 수 없다")

    print("\n[5] 정의되지 않은 전이는 예외로 터진다")
    m5 = Machine()
    try:
        m5.fire(Event.T1_EXPIRED)      # SPEAKING 에서는 불가
        check("SPEAKING 에서 T1 거부", False)
    except TransitionError:
        check("SPEAKING 에서 T1 거부", True, "조용히 무시하지 않는다")


# ---------------------------------------------------------------- 컨트롤러

async def _drive(pace="fast", say="덜컹덜컹 소리가 났지."):
    ctl = SessionController(user_id="t", title="시험", pace=pace)
    await ctl.start("1968년 여름, 순애랑 완행열차를 탔다.")
    await ctl.tts_done()
    await ctl.speech(say)
    return ctl


def test_controller():
    print("\n[6] 지연이 T2 안에 숨는가")

    async def run():
        t0 = time.perf_counter()
        ctl = await _drive(pace="fast")                 # T2 = 3.0초
        await asyncio.sleep(3.0 + 3.0 + 0.6)            # T1 + T2 + 여유
        elapsed = time.perf_counter() - t0
        return ctl, elapsed

    ctl, elapsed = asyncio.run(run())
    check("다음 질문이 나왔다", ctl.machine.state is State.SPEAKING,
          f"state={ctl.machine.state.value}")
    check("조각 2개 (엽서 + 답변 1)", len(ctl.fragments) == 2)

    spans = ctl.latencies[0] if ctl.latencies else {}
    if spans:
        check("질문 생성이 T2(3초) 안에 끝남",
              spans["question"] < T2_PRESETS["fast"] * 1000,
              f"질문 생성 {spans['question']:.0f}ms")
        check("어르신이 받는 총 틈 ≈ T1+T2",
              5.5 < elapsed < 7.5, f"{elapsed:.1f}초 (T1 3 + T2 3)")

    print("\n[7] 타이머 격발 오차 (허용 ±200ms)")
    rep = ctl.timers.drift_report()
    if rep:
        check(f"오차 최대 {rep['max_ms']:.0f}ms", rep["max_ms"] < 200,
              f"n={rep['n']} 평균 {rep['avg_ms']:.0f}ms")

    print("\n[8] 「다 말했어요」는 T2 를 건너뛴다")

    async def run_btn():
        t0 = time.perf_counter()
        ctl = SessionController(user_id="t", title="시험", pace="slow")   # T2 = 7초
        await ctl.start("엽서")
        await ctl.tts_done()
        await ctl.speech("응, 그랬지.")
        await ctl.done_button()
        await asyncio.sleep(0.5)
        return ctl, time.perf_counter() - t0

    ctl2, el2 = asyncio.run(run_btn())
    check("T2 7초를 기다리지 않음", el2 < 2.0, f"{el2:.1f}초")
    check("다음 질문이 준비됨", ctl2.machine.state is State.SPEAKING)

    print("\n[9] 빈 발화는 턴을 소모하지 않는다")

    async def run_empty():
        ctl = SessionController(user_id="t", title="시험", pace="fast")
        await ctl.start("엽서")
        await ctl.tts_done()
        await ctl.done_button()          # 아무 말 없이 확정
        await asyncio.sleep(0.3)
        return ctl

    ctl3 = asyncio.run(run_empty())
    check("턴 0 유지", ctl3.machine.turn == 0)
    check("LISTENING 으로 복귀", ctl3.machine.state is State.LISTENING)


def test_empty_loop():
    """
    빈 전사가 T1 을 다시 걸면 무한 루프가 된다.

    새 소리가 하나도 안 와도 3초 뒤 T1 이 또 터지고, 같은 버퍼를 또 전사하고,
    또 비고, 또 T1 을 건다. 텍스트로는 조용한 빈 반복이라 눈에 안 띄지만
    오디오가 붙으면 **3초마다 Azure 호출 한 번**이다. 실제로 429 폭주로 드러났다.

    이 시험이 없었던 이유는 단순하다 — 어떤 시험도 T1 을 두 주기 이상 기다리지
    않았다. 그래서 여기서는 t1_seconds 를 줄여 여러 주기를 돌린다.
    """
    print("\n[10] 빈 전사가 무한히 반복되지 않는다")

    async def run_silent():
        ctl = SessionController(user_id="t", title="시험", pace="fast")
        ctl.timers.t1_seconds = 0.3              # 3초씩 기다릴 이유가 없다
        await ctl.start("엽서")
        await ctl.tts_done()
        await ctl.done_button()                  # 아무 말 없이 확정
        await asyncio.sleep(2.0)                 # T1 이 여섯 번 돌 시간
        return ctl

    ctl = asyncio.run(run_silent())
    n = sum(1 for h in ctl.machine.history if h[1] is Event.EMPTY_TRANSCRIPT)
    check("말씀이 없으면 한 번으로 끝난다", n == 1,
          f"빈 전사 {n}회 — T1 을 다시 걸면 계속 늘어난다")

    async def run_broken_stt():
        async def always_empty(audio, mime, hint):
            return ""                            # 전사가 계속 실패하는 상황
        ctl = SessionController(user_id="t", title="시험", pace="fast",
                                stt_fn=always_empty)
        ctl.timers.t1_seconds = 0.3
        await ctl.start("엽서")
        await ctl.tts_done()
        await ctl.audio_chunk(bytes(64), "audio/wav")
        await asyncio.sleep(2.5)
        return ctl

    ctl2 = asyncio.run(run_broken_stt())
    n2 = sum(1 for h in ctl2.machine.history if h[1] is Event.EMPTY_TRANSCRIPT)
    # 상한을 숫자로 박지 않는다 — 어르신이 말없이 기다리는 시간이 이 값에 비례해서,
    # 값은 앞으로도 조정된다. 검사는 「상한을 지킨다」는 뜻만 붙잡는다.
    want = 1 + MAX_EMPTY_RETRY
    check(f"전사 실패는 {MAX_EMPTY_RETRY}번까지만 다시 시도", n2 == want,
          f"최초 1 + 재시도 {MAX_EMPTY_RETRY} = {want}, 실제 {n2}")
    check("실패해도 회차는 살아 있다", ctl2.machine.state is State.LISTENING,
          f"state={ctl2.machine.state.value}")
    check("턴을 소모하지 않는다", ctl2.machine.turn == 0)
    check("어르신의 말씀을 버리지 않는다", len(ctl2._audio) == 1,
          "버퍼가 남아 다음 발화와 함께 한 번 더 기회를 얻는다")


def test_pcm_wrap():
    """
    머리 없는 PCM 을 WAV 로 싸는 자리.

    조각들을 이어 붙인 뒤 머리 하나만 씌우는 것이 오디오 경로 전체의 전제다.
    머리의 길이 칸이 틀리면 Azure 는 오류가 아니라 **빈 전사**를 돌려주고,
    화면에는 「말씀이 없었다」로 보인다. 조용히 틀리는 자리라 시험을 둔다.
    """
    print("\n[11] 머리 없는 PCM 에 WAV 머리를 씌운다")

    pcm = bytes(3200)                            # 16kHz 16bit 모노로 0.1초
    w = wave.open(io.BytesIO(audiolib.pcm16_to_wav(pcm, 16000)))
    check("16kHz 모노 16비트로 읽힌다",
          (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2),
          f"{w.getframerate()}Hz {w.getnchannels()}ch {w.getsampwidth()*8}bit")
    check("표본 수가 맞는다", w.getnframes() == 1600, f"{w.getnframes()}개")
    check("표본을 건드리지 않는다", w.readframes(1600) == pcm)

    odd = audiolib.pcm16_to_wav(bytes(101), 16000)
    check("반 토막 난 표본은 버린다", wave.open(io.BytesIO(odd)).getnframes() == 50)

    check("mime 에서 표본율을 읽는다",
          audiolib.pcm_rate("audio/pcm;rate=8000") == 8000)
    check("이상한 표본율은 기본값으로 떨어진다",
          audiolib.pcm_rate("audio/pcm;rate=999") == 16000
          and audiolib.pcm_rate("audio/webm") == 16000)

    # 이미 컨테이너가 있는 것은 그대로 통과시킨다 — tools/replay.py --wav 경로
    check("wav 는 다시 싸지 않는다", audiolib.for_stt(b"RIFFxx", "audio/wav") == (b"RIFFxx", "audio/wav"))
    check("webm 도 그대로 지나간다",
          audiolib.for_stt(b"\x1aE\xdf\xa3", "audio/webm;codecs=opus")[1] == "audio/webm;codecs=opus")


def test_tts():
    """
    낭독 합성이 T2 안에 숨는가, 그리고 실패해도 회차가 사는가.

    **순서가 전부인 자리다.** 질문이 준비된 뒤에 합성을 시작하면 그 시간이
    그대로 어르신의 기다림이 된다. 준비되는 순간 걸어야 남은 T2 안에서 끝난다.
    조용히 어긋나도 숫자로만 드러나는 자리라 시험을 둔다.
    """
    print("\n[12] 낭독 합성은 침묵 안에서 끝난다")

    async def run_ok():
        async def slow_tts(text):
            await asyncio.sleep(0.4)             # T2(3초) 안에 넉넉히 드는 합성
            return b"ID3" + text.encode()[:8]

        ctl = SessionController(user_id="t", title="시험", pace="fast", tts_fn=slow_tts)
        await ctl.start("엽서")
        await ctl.tts_done()
        await ctl.speech("덜컹덜컹 소리가 났지.")
        await asyncio.sleep(T2_PRESETS["fast"] + ctl.timers.t1_seconds + 0.6)
        return ctl

    ctl = asyncio.run(run_ok())
    span = ctl.latencies[0]
    check("낭독 칸이 기록된다", span.get("tts", 0) > 0, f"tts={span.get('tts', 0):.0f}ms")
    check("낭독이 전달보다 작다 — 침묵 안에서 끝났다", span["tts"] < span["deliver"],
          f"낭독 {span['tts']:.0f}ms · 전달 {span['deliver']:.0f}ms")
    check("합계는 T2 그대로다", abs(span["total"] - T2_PRESETS["fast"] * 1000) < 200,
          f"{span['total']:.0f}ms — 합성이 T2 를 밀어냈다면 여기가 커진다")

    async def run_broken():
        async def broken_tts(text):
            raise RuntimeError("합성 서버가 죽었다")

        ctl = SessionController(user_id="t", title="시험", pace="fast", tts_fn=broken_tts)
        await ctl.start("엽서")
        await ctl.tts_done()
        await ctl.speech("덜컹덜컹 소리가 났지.")
        await asyncio.sleep(T2_PRESETS["fast"] + ctl.timers.t1_seconds + 0.6)
        return ctl, await ctl.question_audio(wait=0.2)

    ctl2, audio = asyncio.run(run_broken())
    check("합성이 터져도 회차는 산다", ctl2.machine.state is State.SPEAKING,
          f"state={ctl2.machine.state.value}")
    check("소리가 없으면 빈 바이트다", audio == b"", "화면은 글자만 띄우고 버튼으로 넘어간다")
    check("질문 글자는 그대로 있다", bool(ctl2.snapshot()["next_question"]))
    check("소리 없음을 스냅샷이 알린다", ctl2.snapshot()["question_audio"] is False)

    # 늦게 끝난 합성이 **다음 턴의** 기록을 건드리면 안 된다. 「다 말했어요」는
    # T2 를 건너뛰어 합성이 끝나기 전에 다음 턴이 시작되므로 여기서 드러난다.
    async def run_fast_turns():
        async def slow_tts(text):
            # 고정 질문(0.2초)보다 짧게 둔다. 그래야 늦은 쓰기가 **다음 턴의**
            # question_at 보다 앞선 시각으로 들어가 음수로 드러난다.
            await asyncio.sleep(0.1)
            return b"ID3"

        ctl = SessionController(user_id="t", title="시험", pace="fast", tts_fn=slow_tts)
        await ctl.start("엽서")
        for say in ("첫 마디입니다.", "둘째 마디입니다.", "셋째 마디입니다."):
            await ctl.tts_done()
            await ctl.speech(say)
            await ctl.done_button()
            for _ in range(40):                  # 질문이 준비될 때까지 (고정 0.2초)
                if ctl.machine.state is State.SPEAKING:
                    break
                await asyncio.sleep(0.02)
        await asyncio.sleep(0.7)
        return ctl

    ctl3 = asyncio.run(run_fast_turns())
    worst = min((t.get("tts", 0.0) for t in ctl3.latencies), default=0.0)
    check("늦은 합성이 다음 턴 기록을 덮지 않는다", worst >= 0,
          f"낭독 칸 최솟값 {worst:.0f}ms — 음수면 다음 턴 Marks 에 적힌 것이다")


async def _silent_tts(text: str) -> bytes:
    """합성은 여기서 재는 것이 아니다. 실제 Azure 를 부르지 않는다."""
    return b""


def test_done_button_race():
    """
    자동 확정이 도는 중에 「다 말했어요」가 도착한다.

    화면은 300ms 폴링으로 상태를 안다 (App.tsx POLL_MS). 무음 3초가 지나 서버가
    PROCESSING 으로 넘어간 것을 화면이 아직 모르는 창이 있고, 버튼은 그 창에서
    아직 눌린다 — 어르신 손가락이 거기 들어온다.

    예전에는 cancel_t1 이 자동 확정을 **태스크째로** 죽이고(timers._run 이 잠만
    자는 것이 아니라 콜백까지 await 한다) 버튼 자신은 PROCESSING 에 없는 전이라
    409 로 튕겼다. 둘 다 사라져 회차는 PROCESSING 에 영구히 멈추고, 전사 도중에
    잘렸으니 그 턴의 말씀도 저장되지 않았다.

    **텍스트 경로로는 못 잡는다.** speech(text) 는 _transcribe 가 await 없이
    버퍼를 돌려주어 창이 열리지 않는다. 오디오 + 느린 전사가 있어야 드러난다.
    """
    print("\n[11] 자동 확정 중에 도착한 「다 말했어요」")

    async def run_race():
        async def slow_stt(audio, mime, hint):
            await asyncio.sleep(0.6)          # 이 사이에 버튼이 온다
            return "그럼, 봉천동에서 살았지."

        ctl = SessionController(user_id="t", title="시험", pace="slow",   # T2 = 7초
                                stt_fn=slow_stt, tts_fn=_silent_tts)
        ctl.timers.t1_seconds = 0.3           # 3초를 기다릴 이유가 없다
        await ctl.start("엽서")
        await ctl.tts_done()
        await ctl.audio_chunk(bytes(64), "audio/wav")
        await asyncio.sleep(0.45)             # T1 격발 뒤 · 전사 도중
        mid = ctl.machine.state

        err = None
        t0 = time.perf_counter()
        try:
            await ctl.done_button()
        except TransitionError as e:
            err = str(e)
        for _ in range(150):                  # 전사 0.6 + 고정 질문 0.2
            if ctl.machine.state is State.SPEAKING:
                break
            await asyncio.sleep(0.02)
        return ctl, mid, err, time.perf_counter() - t0

    ctl, mid, err, el = asyncio.run(run_race())
    check("버튼이 전사 도중에 도착했다", mid is State.PROCESSING,
          f"state={mid.value} — 여기가 아니면 이 시험은 아무것도 재지 않는다")
    check("409 로 튕기지 않는다", err is None, err or "")
    check("PROCESSING 에 멈추지 않는다", ctl.machine.state is State.SPEAKING,
          f"state={ctl.machine.state.value}")
    # 0번 조각은 엽서다 (start). 턴 하나가 더 붙어 둘이 되어야 맞는다 —
    # 잘린 확정은 여기를 비워 두고, 그게 말씀이 사라진다는 뜻이다.
    check("말씀이 조각으로 남는다",
          len(ctl.fragments) == 2 and "봉천동" in ctl.fragments[-1]["answer"],
          f"조각 {len(ctl.fragments)}개 — 엽서 말고 턴이 없으면 말씀을 잃은 것이다")
    check("턴을 두 번 소모하지 않는다", ctl.machine.turn == 1, f"턴 {ctl.machine.turn}")
    check("남은 T2 7초를 기다리지 않는다", el < 2.0, f"{el:.1f}초")

    # 자동 확정이 이미 반환한 뒤(전사가 끝나고 질문 생성이 도는 중) 도착하는
    # 누름도 같은 자리다. 이쪽은 회차가 죽지는 않았지만 409 가 화면에 떴고,
    # _confirm 이 self.marks 를 새로 잡아 그 턴의 지연 숫자를 망가뜨렸다.
    async def run_late():
        async def slow_question(ctl):
            await asyncio.sleep(0.5)
            return "그 동네에서는 어떤 일을 하셨나요?"

        ctl = SessionController(user_id="t", title="시험", pace="slow",
                                question_fn=slow_question, tts_fn=_silent_tts)
        ctl.timers.t1_seconds = 0.3
        await ctl.start("엽서")
        await ctl.tts_done()
        await ctl.speech("그럼, 봉천동에서 살았지.")
        await asyncio.sleep(0.4)              # T1 격발 · 전사 끝 · 질문 생성 중
        mid = ctl.machine.state
        confirmed = ctl.marks.confirmed_at

        err = None
        try:
            await ctl.done_button()
        except TransitionError as e:
            err = str(e)
        for _ in range(150):
            if ctl.machine.state is State.SPEAKING:
                break
            await asyncio.sleep(0.02)
        return ctl, mid, err, confirmed

    ctl2, mid2, err2, confirmed2 = asyncio.run(run_late())
    check("늦은 누름도 PROCESSING 에서 받는다", mid2 is State.PROCESSING and err2 is None,
          err2 or f"state={mid2.value}")
    check("확정 시각이 덮이지 않는다", ctl2.marks.confirmed_at == confirmed2,
          "덮이면 그 턴의 지연 숫자가 전부 어긋난다")
    spans = ctl2.latencies[-1] if ctl2.latencies else {}
    check("지연 칸이 음수로 망가지지 않는다",
          bool(spans) and all(v >= 0 for v in spans.values()),
          f"{spans}")


def test_all_checks_passed():
    """
    pytest 로 돌릴 때의 안전판.

    위 check() 는 실패를 FAIL 에 적어 두기만 하고 **예외를 내지 않는다.** 다
    돌려 보고 한꺼번에 보려고 일부러 그렇게 만든 것인데, 그 대가로 pytest 에서는
    실패한 검사가 통과로 보인다 — `pytest tests` 가 「5 passed」라고 말해도
    안에서 몇 개가 깨졌는지 알 수 없다. (`python -m tests.test_flow` 쪽은
    main() 이 종료 코드로 알려 주므로 멀쩡했다.)

    마지막에 여기서 한 번 터뜨려 둘을 맞춘다. 정의 순서대로 도는 pytest 에서
    이 함수가 맨 뒤라 앞의 검사가 모두 끝난 뒤에 본다.
    """
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 상태 머신 · 타이머 검증")
    test_machine()
    test_controller()
    test_empty_loop()
    test_pcm_wrap()
    test_tts()
    test_done_button_race()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
