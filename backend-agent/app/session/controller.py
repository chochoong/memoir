"""
세션 컨트롤러 — 상태 머신 + 타이머 + 저장을 묶는 곳

핵심 설계 하나. T1 이 만료되면 **T2 와 질문 생성을 동시에 건다.**

    T1 만료 (발화 확정)
       ├──▶ T2 카운트다운 시작 ────────────┐
       └──▶ 조각 저장 → 질문 생성 (비동기) ┘
                                          둘 다 끝나야 다음 질문이 나간다

순차로 짜면 T2 가 끝난 뒤에 질문 생성을 시작해서 8 + 1.5 = 9.5초가 된다.
병렬로 걸면 처리 시간이 T2 안에 숨어 어르신은 지연을 못 느낀다.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from . import audio as audiolib
from . import store, stt, tts
from .machine import Event, Machine, State, TransitionError
from .timers import T2_PRESETS, TimerSet

log = logging.getLogger("session")

# 질문 생성기. Day 5 에 Gemini 로 교체한다.
QuestionFn = Callable[["SessionController"], Awaitable[str | None]]

# 전사기. (오디오, mime, 힌트) -> 글. 실패해도 예외가 아니라 빈 문자열이다.
SttFn = Callable[[bytes, str, str | None], Awaitable[str]]

# 낭독기. 질문 -> mp3. 실패해도 예외가 아니라 빈 바이트다.
TtsFn = Callable[[str], Awaitable[bytes]]

# 한 발화가 이보다 커지면 받지 않는다. opus 로 두 시간쯤 된다.
MAX_AUDIO_BYTES = 25 * 1024 * 1024

# 빈 전사가 연속으로 몇 번까지면 다시 시도해 볼 것인가. 아래 _confirm 참조.
MAX_EMPTY_RETRY = 2

# 회차를 여는 말. **여기서는 LLM 을 부르지 않는다.**
#
# 예전에는 start() 가 엽서를 씨앗으로 첫 질문을 만들었다. 두 가지가 걸렸다.
#   · 어르신이 한 마디도 하시기 전에 주제가 정해졌다. 화면 입력창에 적혀 있던
#     글이 프롬프트에 「어르신:」 으로 들어가 어르신의 말씀 행세를 했다.
#   · 첫 질문에는 숨을 T2 가 없다. 생성 ~3초가 회차 시작 응답에 그대로 붙었다.
# 여는 말을 고정하면 둘 다 사라진다. 첫 **생성** 질문은 어르신의 첫 말씀을 듣고
# _make_question 이 만든다 — 그 자리에는 T2 가 있어 지연이 침묵 안에 숨는다.
OPENING = "오늘은 어떤 이야기를 들려주시겠어요?"


async def fixed_questions(ctl: "SessionController") -> str | None:
    """Day 1~4 용 고정 문구. LLM 없이 흐름만 돌린다."""
    await asyncio.sleep(0.2)                     # 호출 지연 흉내
    seq = [
        "그때 어떤 소리가 들렸는지 기억나세요?",
        "그 자리에 누가 함께 계셨어요?",
        "그 이야기를 하시니 지금 어떤 마음이 드세요?",
    ]
    i = ctl.machine.turn - 1
    return seq[i] if 0 <= i < len(seq) else None


@dataclass
class Marks:
    """구간별 지연 (FR-AD-314). 넘겼을 때 어디 때문인지 알기 위한 것."""
    confirmed_at: float = 0.0
    transcribed_at: float = 0.0
    saved_at: float = 0.0
    question_at: float = 0.0
    spoken_at: float = 0.0
    delivered_at: float = 0.0

    def spans_ms(self) -> dict[str, float]:
        if not self.confirmed_at:
            return {}
        return {
            # 전사는 텍스트 경로에서 0 이다. 오디오가 붙으면 여기가 가장 큰 칸이 된다.
            "stt": (self.transcribed_at - self.confirmed_at) * 1000,
            "save": (self.saved_at - self.transcribed_at) * 1000,
            "question": (self.question_at - self.saved_at) * 1000,
            # 합성은 질문 뒤에 이어 붙지만 **T2 안에서 일어난다.** 아래 deliver 가
            # 그만큼 줄어들 뿐 total 은 T2 그대로다. 이 칸이 deliver 보다 커지면
            # 그때 비로소 어르신이 기다리게 된다 — 그걸 보려고 따로 잰다.
            "tts": (self.spoken_at - self.question_at) * 1000 if self.spoken_at else 0.0,
            "deliver": (self.delivered_at - self.question_at) * 1000,
            "total": (self.delivered_at - self.confirmed_at) * 1000,
        }


@dataclass
class SessionController:
    user_id: str
    title: str
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pace: str = "normal"                          # fast(3) / normal(5) / slow(7)
    max_turn: int = 0                             # 0 = 제한 없음 (machine.py 참조)
    question_fn: QuestionFn = fixed_questions
    stt_fn: SttFn = stt.azure_transcribe
    tts_fn: TtsFn = tts.synthesize

    machine: Machine = field(init=False)
    timers: TimerSet = field(init=False)
    fragments: list[dict] = field(default_factory=list)
    marks: Marks = field(default_factory=Marks)
    latencies: list[dict] = field(default_factory=list)
    # question.py 가 채운다. FR-IV-006 의 근거로 turn.decision 에 내려간다.
    last_decision: dict | None = None

    _buffer: str = ""
    _audio: list[bytes] = field(default_factory=list)
    _audio_mime: str = "audio/webm"
    _empty_streak: int = 0
    _pending: asyncio.Task | None = None
    _next_question: str | None = None
    _question_audio: bytes = b""
    _speaking: asyncio.Task | None = None

    def __post_init__(self) -> None:
        self.machine = Machine(max_turn=self.max_turn)
        self.timers = TimerSet(
            on_t1=self._t1_fired, on_t2=self._t2_fired,
            t2_seconds=T2_PRESETS.get(self.pace, 5.0))

    # ------------------------------------------------------------ 조회

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "state": self.machine.state.value,
            "turn": self.machine.turn,
            "max_turn": self.machine.max_turn,
            "turns_left": self.machine.turns_left,
            "question_ready": self.machine.question_ready,
            "t2_expired": self.machine.t2_expired,
            "fragments": self.fragments,
            "next_question": self._next_question,
            "audio_bytes": sum(len(c) for c in self._audio),
            # 화면이 「받아 갈 소리가 있나」를 물을 자리. 없으면 글자만 띄우고
            # 「낭독 끝」 버튼으로 넘어간다 (NFR-AC — 소리가 안 나도 회차는 산다).
            # 「소리가 있다」 또는 「아직 만드는 중이다」. 끝난 태스크는 세지
            # 않는다 — 합성이 실패로 끝나도 있다고 말하게 되고, 화면은 오지
            # 않을 소리를 기다린다.
            "question_audio": bool(self._question_audio) or bool(
                self._speaking and not self._speaking.done()),
            "timer_drift": self.timers.drift_report(),
        }

    # ------------------------------------------------------------ 외부 이벤트

    async def start(self, postcard: str) -> None:
        """엽서(0번 조각)로 회차를 연다. 여는 말 낭독 상태에서 시작한다."""
        self.fragments.append({"idx": 0, "question": None, "answer": postcard})
        await store.save_session(self)
        await store.save_turn(self, self.fragments[0])
        # 고정 여는 말이다 — 위 OPENING 참조. 질문 생성은 어르신의 첫 말씀을
        # 들은 뒤 _make_question 에서 처음 일어난다.
        self._next_question = OPENING
        # 합성은 붙잡지 않고 띄워 둔다 — 화면이 받으러 올 때 기다리면 된다
        # (question_audio 가 최대 2초 기다린다).
        self._speak(self._next_question)

    async def tts_done(self) -> dict:
        """낭독이 끝났다(또는 탭으로 중단). 수음을 연다."""
        self.machine.fire(Event.TTS_DONE)
        self._buffer = ""
        self.timers.reset_t1()
        return self.snapshot()

    async def speech(self, text: str) -> dict:
        """
        유효 발화 수신. 1주차는 텍스트, 2주차에 오디오 청크로 바뀐다.
        올 때마다 T1 을 리셋한다.
        """
        self.machine.fire(Event.SPEECH_RECEIVED)
        self._buffer = (self._buffer + " " + text).strip()
        self._empty_streak = 0
        self.timers.reset_t1()
        return self.snapshot()

    async def audio_chunk(self, data: bytes, mime: str = "") -> dict:
        """
        오디오 청크 수신 → T1 리셋. speech(text) 와 정확히 같은 자리다.

        **소리가 있는 청크만 올려보내는 것은 프론트의 몫이다.** 무음까지 올라오면
        T1 이 영원히 리셋되어 발화가 확정되지 않는다.

        서버에서 VAD 를 돌리지 않는 이유는 T1 이 이미 「무음 3초」의 정의이기
        때문이다. 아무것도 보내지 않는 것이 곧 무음 신호다. 판정을 두 군데 두면
        둘이 어긋날 때 원인을 찾을 수 없다.
        """
        self.machine.fire(Event.SPEECH_RECEIVED)
        self._empty_streak = 0
        if sum(len(c) for c in self._audio) + len(data) > MAX_AUDIO_BYTES:
            log.error("발화 오디오가 %dMB 를 넘었다 — 이 청크는 버린다",
                      MAX_AUDIO_BYTES // (1024 * 1024))
        else:
            self._audio.append(data)
            if mime:
                self._audio_mime = mime
        self.timers.reset_t1()
        return self.snapshot()

    async def done_button(self) -> dict:
        """「다 말했어요」 — T1·T2 를 건너뛴다. 지연이 그대로 드러나는 유일한 경로."""
        self.timers.cancel_t1()
        await self._confirm(Event.DONE_BUTTON, skip_t2=True)
        return self.snapshot()

    async def abort(self) -> dict:
        self.timers.cancel_all()
        for task in (self._pending, self._speaking):
            if task and not task.done():
                task.cancel()
        self.machine.fire(Event.ABORT)
        await store.update_session(self, closed_reason="abort")
        return self.snapshot()

    # ------------------------------------------------------------ 타이머 콜백

    async def _t1_fired(self) -> None:
        await self._confirm(Event.T1_EXPIRED, skip_t2=False)

    async def _t2_fired(self) -> None:
        try:
            self.machine.fire(Event.T2_EXPIRED)
        except TransitionError:
            return
        await self._maybe_advance()

    # ------------------------------------------------------------ 내부

    async def _confirm(self, event: Event, *, skip_t2: bool) -> None:
        """
        발화 확정. 여기서 T2 · 전사 · 질문 생성이 맞물린다.

        **T2 를 전사보다 먼저 건다.** 순서를 바꾸면 전사 시간(Azure 실측 p90
        921ms)이 T2 밖으로 새어 나와 어르신이 느끼는 틈이 그만큼 길어진다.
        T2 는 「말씀을 마치신 뒤의 사이」지 「서버가 일을 끝낸 뒤의 사이」가 아니다.

            확정 ─┬─ T2 카운트다운 ───────────────────┐
                  └─ 전사(921ms) → 질문 생성(875ms) ──┘  둘 다 끝나야 다음 질문

        전사가 비면 T2 를 취소하고 되돌린다. 플래그는 손대지 않는다 — machine 이
        다음 확정 때 t2_expired 를 다시 False 로 놓는다.
        """
        self.marks = Marks(confirmed_at=time.perf_counter())

        self.machine.fire(event)                       # LISTENING → PROCESSING (턴 +1)

        if skip_t2:
            self.machine.t2_expired = True             # 버튼은 T2 를 건너뛴다
        else:
            self.timers.start_t2()

        text = await self._transcribe()
        self.marks.transcribed_at = time.perf_counter()

        if not text:                                   # FR-AD-312 턴 미소모
            self.timers.cancel_t2()
            self.machine.fire(Event.EMPTY_TRANSCRIPT)
            self._after_empty()
            return

        self.fragments.append({
            "idx": len(self.fragments),
            "question": self._next_question,
            "answer": text,
        })
        self._buffer = ""
        self._audio.clear()
        # 지연 숫자를 기다리지 않고 바로 내린다. 어르신의 말을 잃지 않는 게 먼저다.
        await store.save_turn(self, self.fragments[-1])
        self.marks.saved_at = time.perf_counter()

        if self.machine.max_turn and self.machine.turn >= self.machine.max_turn:
            # FR-IV-006 — 최대 턴에 도달하면 판단·질문 생성을 **호출하지 않고** 종료한다.
            # 어차피 내보내지 않을 질문에 LLM 비용과 지연을 쓸 이유가 없다.
            # max_turn 이 0 이면 이 문은 통째로 지나간다 — 회차를 끝내는 것은
            # AI 의 close 판단과 「중단」 버튼뿐이다.
            self.timers.cancel_all()
            self.machine.fire(Event.FINISH)
            await store.update_session(self, closed_reason="max_turn")
            return

        self._pending = asyncio.create_task(self._make_question())

    def _after_empty(self) -> None:
        """
        빈 전사 뒤에 T1 을 **다시 걸지 말지** 정한다.

        여기서 무조건 reset_t1() 을 하면 무한 루프가 된다. 새 소리가 하나도 안
        와도 3초 뒤 T1 이 또 터지고, 같은 버퍼를 또 전사하고, 또 비고, 또 T1 을
        건다. 텍스트 경로에서는 조용히 도는 빈 반복이라 눈에 안 띄었지만, 오디오가
        붙으면 **3초마다 Azure 호출 한 번**이 된다. 실제로 429 폭주로 드러났다.

        그래서 둘로 나눈다.

            버퍼가 비었다        말씀이 없었던 것이다. 다시 시도할 대상이 없다.
                                 T1 을 걸지 않고 기다린다 — 다음 발화가 걸어 준다.
            버퍼에 뭔가 있다      전사가 실패한 것일 수 있다. 두 번까지 다시 해 본다.

        **버퍼는 비우지 않는다.** 전사에 실패한 것이라면 그 안에 어르신의 말씀이
        들어 있다. 다음 발화가 뒤에 붙어 함께 전사되면서 한 번 더 기회를 얻는다.
        크기는 MAX_AUDIO_BYTES 가 묶는다.
        """
        self._empty_streak += 1
        has_buffer = bool(self._audio) or bool(self._buffer.strip())
        if has_buffer and self._empty_streak <= MAX_EMPTY_RETRY:
            log.info("빈 전사 %d회 — 턴을 소모하지 않고 다시 기다린다", self._empty_streak)
            self.timers.reset_t1()
            return
        if has_buffer:
            log.error("빈 전사 %d회 연속 — 재시도를 멈춘다. 다음 발화를 기다린다",
                      self._empty_streak)
        else:
            log.info("빈 전사 — 말씀이 없었다. 다음 발화를 기다린다")

    async def _transcribe(self) -> str:
        """
        오디오가 있으면 전사하고, 없으면 텍스트 버퍼를 쓴다.

        텍스트 경로를 남겨 둔 것은 시험 도구 때문이다. 오디오가 붙은 뒤에도
        FSM 과 타이머를 네트워크도 키도 없이 돌려볼 수 있어야 한다.
        tests/test_flow.py 가 이 경로로 돈다.
        """
        if not self._audio:
            return self._buffer.strip()
        # 머리 없는 PCM 이면 여기서 WAV 머리를 씌운다. audio.py 의 설명 참조 —
        # 무음을 들어낸 조각들은 PCM 으로만 온전히 이어 붙는다.
        audio, mime = audiolib.for_stt(b"".join(self._audio), self._audio_mime)
        text = (await self.stt_fn(audio, mime, self._hint())).strip()
        if not text:
            # 빈 전사는 「말씀이 없었다」일 수도, 「받아오지 못했다」일 수도 있다.
            # 어르신에게는 똑같이 보이지만 로그에서는 구분되어야 한다.
            log.error("전사가 비었다 — 오디오 %d바이트를 글로 옮기지 못했다", len(audio))
        return text

    def _hint(self) -> str:
        """
        엽서와 직전 답변. 인명·지명을 전사기에 흘려 넣는다.

        「순애」「서울」 같은 말은 우리가 이미 알고 있는데 STT 만 모른다.
        whisper 측정에서 이 힌트 하나로 글자 오류율이 4.2% -> 0.8% 로 내려갔다.
        """
        return " ".join(f["answer"] for f in self.fragments[-2:] if f.get("answer"))

    async def _make_question(self) -> None:
        try:
            q = await self.question_fn(self)
        except Exception as e:                          # noqa: BLE001
            log.error("질문 생성 실패: %s", e)          # FR-AD-315 실패 복구 지점
            q = None
        self._next_question = q
        self.marks.question_at = time.perf_counter()

        if q is None:
            self.machine.fire(Event.FINISH)
            self.timers.cancel_all()
            await store.update_session(self, closed_reason="finish")
            return
        # **합성을 먼저 건다.** 여기서 걸면 남은 T2 안에서 끝나고, 어르신 귀에는
        # 침묵이 끝나는 순간 곧바로 목소리가 나온다. QUESTION_READY 를 먼저
        # 올리고 나중에 합성하면 그 시간이 그대로 기다림이 된다 — 순서가 전부다.
        self._speak(q)
        try:
            self.machine.fire(Event.QUESTION_READY)
        except TransitionError:
            return
        await self._maybe_advance()

    def _speak(self, q: str) -> None:
        """낭독 합성을 띄운다. 붙잡지 않는다 — T2 가 이미 흐르고 있다."""
        self._question_audio = b""
        if self._speaking and not self._speaking.done():
            self._speaking.cancel()

        # **지금 턴의 Marks 를 붙잡아 둔다.** self.marks 를 태스크 안에서 읽으면
        # 늦게 끝난 합성이 **다음 턴의** 기록에 시각을 적는다. 전달이 빠른 경로
        # (「다 말했어요」는 T2 를 건너뛴다)에서 실제로 낭독 칸이 음수로 나왔다 —
        # 이번 턴 question_at 보다 앞선 시각이 적혔다는 뜻이다.
        marks = self.marks

        async def run() -> None:
            try:
                self._question_audio = await self.tts_fn(q)
            except asyncio.CancelledError:
                raise
            except Exception as e:                      # noqa: BLE001
                log.error("낭독 합성 실패: %s", e)      # 글자는 그대로 나간다
                self._question_audio = b""
            marks.spoken_at = time.perf_counter()

        self._speaking = asyncio.create_task(run())

    async def question_audio(self, wait: float = 2.0) -> bytes:
        """
        지금 질문의 mp3. 아직 합성 중이면 기다린다.

        여기서 기다리는 것은 어르신을 기다리게 하는 것과 다르다. 화면은 이미
        질문 글자를 띄운 채고, 소리는 그 위에 얹히는 것이다. 못 받으면 빈
        바이트가 가고 화면은 「낭독 끝」 버튼으로 넘어간다.
        """
        if self._speaking and not self._speaking.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._speaking), timeout=wait)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                log.warning("낭독 소리를 %.1f초 안에 못 만들었다 — 글자만 나간다", wait)
        return self._question_audio

    async def _maybe_advance(self) -> None:
        """질문 준비 + T2 만료가 모두 참일 때만 다음 턴으로."""
        if self.machine.state is not State.SPEAKING:
            return
        self.marks.delivered_at = time.perf_counter()
        spans = self.marks.spans_ms()
        self.latencies.append(spans)
        log.info("턴 %d 지연 %.0fms  (저장 %.0f · 질문 %.0f · 전달 %.0f)",
                 self.machine.turn, spans["total"],
                 spans["save"], spans["question"], spans["deliver"])
        await store.update_turn_marks(self, self.fragments[-1]["idx"], spans)
        await store.update_session(self)


# ---------------------------------------------------------------- 레지스트리

_sessions: dict[str, SessionController] = {}


def put(ctl: SessionController) -> SessionController:
    _sessions[ctl.session_id] = ctl
    return ctl


def get(session_id: str) -> SessionController | None:
    return _sessions.get(session_id)


def all_sessions() -> list[SessionController]:
    return list(_sessions.values())
