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
from . import shared as shared_state
from . import photo_analyze, photostore, store, stt, tts
from .conf import env_float, env_int
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

# 빈 전사가 연속으로 몇 번까지면 다시 시도해 볼 것인가. 아래 _after_empty 참조.
#
# 재시도 한 번의 값은 전사 타임아웃 + T1 이다 — 어르신은 그만큼(약 9초) 화면도
# 소리도 없는 채로 기다린다. 같은 오디오를 다시 보내는 일이 그 값을 두 번
# 지불할 만큼 잘 듣지 않는다. 한 번까지만 해 보고 다음 발화에 맡긴다.
MAX_EMPTY_RETRY = 1

# ---------------------------------------------------------------- 안전 천장
#
# 아래 넷은 **설계가 아니라 사고 방지**다. 회차가 어디서 끝나는지는 여전히 AI 의
# close 판단과 「중단」 버튼이 정한다 (machine.py 의 max_turn 주석 참조). 여기 있는
# 것은 그 판단이 **오지 않을 때** 무한히 흐르지 않게 막는 선이다. 평소에는 한 번도
# 걸리지 않아야 하고, 걸리면 그건 기능이 아니라 **신호**다 — 아래 turn_cap 참조.
#
# 넷 다 .env 로 덮을 수 있다. 값은 함수 안에서 읽는다 (conf.py 참조).

# max_turn 을 주지 않은 회차(= 제한 없음)에 씌우는 천장.
TURN_CAP = 60

# 진행 중인 회차를 메모리에서 버리는 기준. 마지막 **활동**부터 잰다 —
# 폴링은 활동이 아니다. 폴링을 활동으로 세면 열어 둔 채 잊은 탭이 영원히 산다.
IDLE_SECONDS = 1800.0

# 닫힌 회차를 지우는 기준. 0 으로 두지 않는 이유 — 화면이 300ms 폴링으로 마지막
# 상태(CLOSED)를 받아 가야 한다. 닫는 순간 지우면 화면에는 회차가 끝난 것이 아니라
# **사라진 것**으로 보인다.
CLOSED_SECONDS = 300.0

# 한 프로세스가 동시에 들고 있을 회차 수. 스윕이 60초에 한 번 도니 그보다 빠른
# 폭주는 이 선이 막는다.
MAX_LIVE = 200

# 스윕 주기.
SWEEP_EVERY = 60.0

# 회차를 여는 말. **여기서는 LLM 을 부르지 않는다.**
#
# 예전에는 start() 가 씨앗 문장으로 첫 질문을 만들었다. 두 가지가 걸렸다.
#   · 어르신이 한 마디도 하시기 전에 주제가 정해졌다. 화면 입력창에 적혀 있던
#     글이 프롬프트에 「어르신:」 으로 들어가 어르신의 말씀 행세를 했다.
#   · 첫 질문에는 숨을 T2 가 없다. 생성 ~3초가 회차 시작 응답에 그대로 붙었다.
# 여는 말을 고정하면 둘 다 사라진다. 첫 **생성** 질문은 어르신의 첫 말씀을 듣고
# _make_question 이 만든다 — 그 자리에는 T2 가 있어 지연이 침묵 안에 숨는다.
OPENING = "오늘은 어떤 이야기를 들려주시겠어요?"

# 사진을 들고 여는 회차의 **뒷받침** 여는 말. 단서가 없을 때만 쓴다.
#
# 사진을 고르고 시작했는데 첫 마디가 「오늘은 어떤 이야기를」이면, 어르신에게는
# 사진이 닿지 않은 것으로 보인다. 실제로 그랬다 — 사진도 붙고 단서도 뽑혔는데
# 화면은 여는 말 그대로 멈춰 있었다.
#
# 다만 이 문장 자체는 사진을 보지 않은 말이다. 보통은 photo_opening 이 §2 가
# 만든 진짜 사진 질문으로 여는 말을 짓고, 여기로는 단서가 아직 없을 때만
# 내려온다 (아래 photo_opening · start 참조).
OPENING_PHOTO = "사진 잘 받았습니다. 이 사진은 어떤 사진인가요?"


def photo_opening(clues: dict | None) -> str:
    """
    §2 가 만든 사진 질문으로 여는 말을 짓는다. 쓸 수 없으면 OPENING_PHOTO 다.

    **여기서도 LLM 을 부르지 않는다** — 위 OPENING 과 같은 이유다. 부를 필요가
    없다: 단서는 사진을 **올릴 때** 이미 계산돼 있다 (photo.analyze_later). 예전에
    분석을 회차 시작에 붙였을 때는 1.6~3.9초가 여는 말 앞에 그대로 얹혔고, 그
    시간이 숨을 T2 침묵이 없어서 고정 문장 말고는 낼 것이 없었다. 계산하는 자리를
    옮기자 그 값이 공짜가 됐다.

    **§2 의 말을 다듬지 않는다.** §1 의 「photo_analyses의 questions가 들어오면
    의미를 바꾸지 않고 자연스러운 존댓말로 바꿔 묻습니다」를 코드가 대신할 수는
    없다. 대신 **쓸 만한지만 본다.** 실제 사진 셋을 두 번씩 돌려 나온 질문 12개는
    모두 존댓말 의문문이었고 20~42자였다 —
    「가운데에 꽃목걸이를 하고 계신 분은 어떤 좋은 일로 축하를 받으신 건가요?」

    그래도 거르는 까닭은 §2 가 시각 분석가이지 인터뷰어가 아니어서다. 여쭐
    「내용」을 적어 버리면(「찍은 장소가 어디인지」) 어르신께 그대로 읽어 드릴 수
    없는 말이 된다. 물음표로 끝나지 않거나 길면 고정 문장으로 돌아간다 — 어색한
    첫 마디보다 사진을 안 본 첫 마디가 낫다.

    앞에 「사진 잘 받았습니다」를 붙인다. 사진이 닿았다는 신호가 첫 마디에 있어야
    하고, §1 의 「공감 한 문장 + 질문 한 문장, 합쳐 60자」와도 같은 모양이 된다.
    다만 아래 상한(질문 100자)은 아직 60자보다 넓다.
    """
    qs = (clues or {}).get("questions")
    q = qs[0].strip() if isinstance(qs, list) and qs and isinstance(qs[0], str) else ""
    if not q.endswith(("?", "？")) or len(q) > 100:
        return OPENING_PHOTO
    return f"사진 잘 받았습니다. {q}"


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
    # 회차를 연 사진. 배경에서 한 번만 분석해 state["photo_analyses"] 로 간다.
    photo_id: str | None = None
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
    # §1 의 closing_hint — 마칠 때 화면에 띄울 한 줄. 진행 턴에는 None 이다.
    closing_hint: str | None = None
    # 네 에이전트가 함께 보는 기록 (문서 §0). **모델은 읽고 코드가 쓴다** —
    # 쓰는 자리는 shared.py 하나뿐이고, 여기는 담아 두기만 한다.
    state: dict = field(default_factory=shared_state.initial)
    # 마지막 활동 시각 (monotonic). 스윕이 보는 값이다 — 아래 touch 참조.
    last_active: float = field(default_factory=time.monotonic)

    _buffer: str = ""
    _audio: list[bytes] = field(default_factory=list)
    _audio_mime: str = "audio/webm"
    _empty_streak: int = 0
    _pending: asyncio.Task | None = None
    _clues: asyncio.Task | None = None
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
            # 폰 화면의 콘솔에서 상태가 차오르는 것을 보려고 싣는다. 사실이
            # 한 턴도 안 쌓이면 인터뷰 에이전트가 제 몫을 못 하고 있는 것인데,
            # 로그를 열지 않고 알아채려면 여기 있어야 한다.
            "shared_state": shared_state.for_interview(self),
            # 마칠 때 화면에 띄울 한 줄. 화면이 제 말로 「마쳤습니다」를 쓰는 대신
            # 모델이 방금 어떤 이야기를 들었는지 실린 문구를 쓴다. None 이면
            # 화면이 쓰던 문구로 돈다 — 소리처럼, 없어도 회차는 산다.
            "closing_hint": self.closing_hint,
            "timer_drift": self.timers.drift_report(),
        }

    def turn_cap(self) -> int:
        """
        이번 회차를 끊을 턴 수. 0 이면 상한이 없다.

        요청이 max_turn 을 주면 그것이 끝이다 (tools/replay.py 가 그렇게 쓴다).
        주지 않았으면 안전 천장을 씌운다 — 「제한 없음」은 **AI 가 정한다**는
        뜻이지 **영원히**라는 뜻이 아니다.
        """
        if self.machine.max_turn:
            return self.machine.max_turn
        return env_int("TURN_CAP", TURN_CAP)

    def idle_seconds(self) -> float:
        """활동이 없던 시간. 스윕과 로그가 같은 값을 보게 한 자리다."""
        return time.monotonic() - self.last_active

    # ------------------------------------------------------------ 외부 이벤트

    def touch(self) -> None:
        """
        활동이 있었다고 적는다. **상태를 바꾸는 경로에서만 부른다.**

        조회(GET /api/sessions/{id})에서 부르지 않는 것이 이 함수의 핵심이다.
        화면이 300ms 마다 때리므로, 폴링을 활동으로 세면 브라우저 탭이 열려 있는
        동안 회차는 절대 만료되지 않는다 — 어르신이 자리를 떠나 잊은 탭도 그렇다.
        그러면 스윕이 있으나 없으나 같아진다.
        """
        self.last_active = time.monotonic()

    async def start(self, seed: str) -> None:
        """씨앗(0번 조각)으로 회차를 연다. 여는 말 낭독 상태에서 시작한다."""
        self.touch()
        self.fragments.append({"idx": 0, "question": None, "answer": seed})
        await store.save_session(self)
        await store.save_turn(self, self.fragments[0])

        # 여는 말을 정한다. 질문 **생성**은 어르신의 첫 말씀을 들은 뒤
        # _make_question 에서 처음 일어난다 — 위 OPENING 참조.
        #
        # 사진이 있으면 단서를 먼저 본다. 읽기 한 번이면 되는 까닭은 분석이
        # 사진을 올릴 때 이미 끝나 있어서다 (photo.analyze_later).
        rec = await self._photo_record() if self.photo_id else None
        clues = (rec or {}).get("clues")
        if clues:
            self._apply_clues(clues)
            await store.save_photo_clues(self, clues)
            self._next_question = photo_opening(clues)
        else:
            self._next_question = OPENING_PHOTO if self.photo_id else OPENING

        # 합성은 붙잡지 않고 띄워 둔다 — 화면이 받으러 올 때 기다리면 된다
        # (question_audio 가 최대 2초 기다린다).
        self._speak(self._next_question)

        # 단서가 없으면 여기서 한 번 더 해 본다. 붙잡지 않는다.
        if rec is not None and not clues:
            self._clues = asyncio.create_task(self._analyze_photo(rec))

    async def _photo_record(self) -> dict | None:
        """
        회차를 연 사진의 표지. 없거나 남의 것이면 None — **회차는 그대로 간다.**

        화면이 보낸 photo_id 가 틀릴 수 있다. 그때 회차를 깨지 않는 까닭은 아래
        _analyze_photo 와 같다. 읽기가 실패해도 마찬가지다 — DB 가 한 번 비틀거렸다고
        어르신의 회차가 열리지 않으면 안 된다.
        """
        pid = (self.photo_id or "")[:8]
        try:
            rec = await store.load_photo(self.photo_id or "")
        except Exception as e:                               # noqa: BLE001
            log.error("사진 %s 를 읽을 수 없다 — 사진 단서 없이 간다 (%s: %s)",
                      pid, type(e).__name__, str(e)[:120])
            return None
        if rec is None or rec["user_id"] != self.user_id:
            log.error("사진 %s 를 읽을 수 없다 — 사진 단서 없이 간다", pid)
            return None
        return rec

    def _apply_clues(self, clues: dict) -> None:
        """
        단서를 state 에 얹는다. **얹는 것이 곧 §1 에 붙이는 일이다** — §1 에
        「photo_analyses의 questions가 들어오면 의미를 바꾸지 않고 …」 규칙이 이미
        있고, shared.for_interview 가 ctl.state 를 그대로 실어 보낸다.
        """
        self.state["photo_analyses"] = [clues]

    async def _analyze_photo(self, rec: dict) -> None:
        """
        올릴 때 못 끝낸 분석을 여기서 한 번 더 한다 (§2). **회차당 한 번이다.**

        **보통은 여기 오지 않는다.** 분석은 사진을 올리는 자리에서 돈다
        (photo.analyze_later). 이 길로 오는 것은 그때 Gemini 가 실패했거나, 004
        이전에 올라와 단서가 없는 사진이거나, 분석이 끝나기 전에 서버가 다시 뜬
        경우다. 그래도 한 번은 더 해 봐야 그 회차에 사진 질문이 산다.

        **붙잡지 않고 배경으로 돈다.** 여는 말은 이미 정해져 나갔고, 첫 질문이
        필요해지는 때는 낭독과 어르신의 첫 말씀이 끝난 뒤다. 분석 예산 10초는 그
        안에 넉넉히 들어간다 — 어르신은 이것 때문에 기다리지 않는다.

        **실패해도 회차는 그대로 간다.** 사진 단서는 있으면 좋은 것이지 회차의
        조건이 아니다. stt·tts 와 같은 정책이다. 다만 조용히 지나가지는 않는다 —
        어르신이 사진을 고르셨는데 사진 질문이 안 나오면 그 까닭이 로그에 있어야
        한다.
        """
        pid = str(rec.get("photo_id") or self.photo_id or "")[:8]
        try:
            data = await photostore.current().get(rec["storage_key"])
            clues = await photo_analyze.analyze_photo(data, rec["mime"])
        except asyncio.CancelledError:
            raise
        except Exception as e:                               # noqa: BLE001
            log.error("사진 분석 실패 %s (%s: %s)", pid, type(e).__name__, str(e)[:120])
            return

        if not clues:
            log.error("사진 %s 에서 단서를 얻지 못했다 — 사진 질문 없이 간다", pid)
            return

        self._apply_clues(clues)
        await store.save_photo_clues(self, clues)
        # 사진에도 적어 둔다. 다음 회차는 이 사진을 다시 분석하지 않는다.
        await store.save_photo_analysis(
            str(rec.get("photo_id") or self.photo_id), clues)
        log.info("사진 단서 %s — 사물 %d개 · 여쭐 것 %d개", pid,
                 len(clues.get("objects") or []), len(clues.get("questions") or []))

    async def tts_done(self) -> dict:
        """낭독이 끝났다(또는 탭으로 중단). 수음을 연다."""
        self.touch()
        self.machine.fire(Event.TTS_DONE)
        self._buffer = ""
        self.timers.reset_t1()
        return self.snapshot()

    async def speech(self, text: str) -> dict:
        """
        유효 발화 수신. 1주차는 텍스트, 2주차에 오디오 청크로 바뀐다.
        올 때마다 T1 을 리셋한다.
        """
        self.touch()
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
        self.touch()
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
        """
        「다 말했어요」 — T1·T2 를 건너뛴다. 지연이 그대로 드러나는 유일한 경로.

        **타이머보다 전이를 먼저 본다.** 다른 경로는 전부 이 순서다 — speech·
        audio_chunk 는 machine.fire 가 앞에 있어서 PROCESSING 중에 와도 거기서
        먼저 튕기고 reset_t1 까지 가지 않는다. 이 함수만 순서가 뒤집혀 있었다.

        뒤집힌 순서가 회차를 죽였다. 무음 3초가 지나 자동 확정이 이미 도는 중에
        버튼이 오면 cancel_t1 이 **자동 확정을 태스크째로 죽인다** — 타이머
        태스크가 잠만 자는 것이 아니라 콜백까지 await 하기 때문이다
        (timers._run). 그 콜백은 전사 도중에 잘려 조각 저장도 질문 생성도 못 하고,
        이어지는 fire(DONE_BUTTON) 는 PROCESSING 에 그 전이가 없어 409 로 튕긴다.
        남은 T2 가 격발해도 _maybe_advance 가 SPEAKING 이 아니라 되돌아가므로,
        회차는 PROCESSING 에 영구히 멈추고 그 턴의 말씀이 사라진다.

        타이머 쪽은 고치지 않았다. 「일하는 중에 취소」는 abort 가 의지하는
        성질이다 — cancel_all 이 진행 중인 확정을 죽여 주는 것이 중단의 정의다.
        abort 에는 기능이고 이 버튼에는 버그라서, 구분은 타이머가 아니라 여기 있다.
        """
        self.touch()

        if self.machine.state is State.PROCESSING:
            # 화면은 LISTENING 으로 알고 버튼을 열어 두었다. 300ms 폴링이 물어온
            # 스냅샷이라 서버가 넘어간 것을 아직 모르는 창이 있다 (App.tsx).
            #
            # 튕기지 않고 받는다. 누름의 뜻이 이미 이뤄지고 있기 때문이다 —
            # T1 은 지났으니 건너뛸 것이 없고 남은 것은 T2 뿐이라, **예약된
            # 격발을 버리고 지금 터뜨린다.** 3초 전에 누른 것과 뒤에 누른 것이
            # 어르신께 같아진다. 경계가 만져지면 그건 버튼이 고장난 것으로 보인다.
            #
            # 질문이 아직 안 왔으면 t2_expired 만 서고 PROCESSING 에 머문다.
            # 그 뒤 질문이 도착하는 순간 넘어간다 — 건너뛴 것은 기다림이지
            # 질문이 아니다.
            self.timers.cancel_t2()
            await self._t2_fired()
            return self.snapshot()

        self.timers.cancel_t1()
        await self._confirm(Event.DONE_BUTTON, skip_t2=True)
        return self.snapshot()

    async def abort(self) -> dict:
        """사용자 중단."""
        self.touch()
        return await self._close("abort")

    async def expire(self) -> None:
        """
        스윕이 버리는 회차. 중단과 같은 정리를 하지만 **이유가 다르다.**

        이유를 남기는 것이 이 함수의 값이다. 남기지 않으면 그 회차는 DB 에서
        영원히 「진행 중」으로 남고, 나중에 목록을 볼 때 아직 하는 중인 회차와
        어르신이 떠나 버린 회차를 구분할 수 없다. expired 가 자주 쌓이면 그것도
        신호다 — 어르신들이 어느 지점에서 이탈하는지가 거기 적힌다.
        """
        log.info("회차 %s 를 버린다 — %.0f분 활동이 없었다",
                 self.session_id[:8], self.idle_seconds() / 60)
        await self._close("expired")

    def release(self) -> None:
        """
        타이머와 대기 태스크만 끊는다. **DB 는 건드리지 않는다.**

        이미 닫힌 회차를 메모리에서 지울 때 쓴다. 그 회차의 closed_reason 은 이미
        제 이유(finish · abort · max_turn)로 적혀 있어서, 여기서 또 쓰면 그것을
        expired 로 덮어쓰게 된다 — **왜 끝났는지를 잃는다.**
        """
        self.timers.cancel_all()
        for task in (self._pending, self._speaking, self._clues):
            if task and not task.done():
                task.cancel()

    async def _close(self, reason: str) -> dict:
        """ABORT 전이로 닫는다. 어느 상태에서 불러도 받는다 (machine.fire 참조)."""
        self.release()
        self.machine.fire(Event.ABORT)
        await store.update_session(self, closed_reason=reason)
        return self.snapshot()

    async def _finish(self, reason: str) -> None:
        """
        FINISH 전이로 닫는다. 중단과 구분되는 **정상 종료** 경로다.

        touch() 를 하는 이유 — 닫는 것도 활동이다. 빼면 닫힌 회차의 유예 시간
        (CLOSED_SECONDS)이 마지막 발화 시각부터 세어지고, 말씀이 길었던 회차는
        화면이 마지막 상태를 받아 가기 전에 메모리에서 지워질 수 있다.
        """
        self.timers.cancel_all()
        self.machine.fire(Event.FINISH)
        self.touch()
        await store.update_session(self, closed_reason=reason)

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
        self.machine.fire(event)                       # LISTENING → PROCESSING (턴 +1)

        # **전이가 선 뒤에 잡는다.** 앞에 두면 튕길 요청이 이번 턴의 계측을
        # 먼저 덮어쓴다 — 돌고 있던 _confirm 이 transcribed_at 을 새 Marks 에
        # 적어 지연 숫자가 망가진다. fire 는 동기라 시각은 사실상 같다.
        self.marks = Marks(confirmed_at=time.perf_counter())

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

        cap = self.turn_cap()
        if cap and self.machine.turn >= cap:
            # FR-IV-006 — 최대 턴에 도달하면 판단·질문 생성을 **호출하지 않고** 종료한다.
            # 어차피 내보내지 않을 질문에 LLM 비용과 지연을 쓸 이유가 없다.
            #
            # **이유를 둘로 나눠 적는다.** max_turn 은 회차를 열 때 요청이 정한
            # 끝이고, turn_cap 은 아무도 끝을 정하지 않았을 때 씌운 안전 천장이다.
            # 후자가 기록에 남았다면 「60턴짜리 회차였다」가 아니라 **AI 가 60턴
            # 동안 마무리를 고르지 않았다**는 뜻이라 프롬프트를 봐야 한다. 한 이름
            # 으로 적으면 그 둘을 나중에 셀 수 없다.
            if self.machine.max_turn:
                await self._finish("max_turn")
            else:
                log.warning("턴 천장 %d 에 닿아 회차를 닫는다 — AI 가 마무리를 "
                            "고르지 않았다. 프롬프트를 봐야 한다", cap)
                await self._finish("turn_cap")
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
            버퍼에 뭔가 있다      전사가 실패한 것일 수 있다. MAX_EMPTY_RETRY 만큼
                                 다시 해 본다.

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
        씨앗과 직전 답변. 인명·지명을 전사기에 흘려 넣는다.

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
            # **왜 마쳤는지를 적는다.** §1 이 사유 세 가지를 정했고 (shared.END_REASONS)
            # question.py 가 아는 값만 걸러 올려 준다. 없으면 "finish" 로 떨어진다 —
            # 예전과 같은 값이라 사유가 빠진 회차도 목록에서 그대로 읽힌다.
            reason = (self.last_decision or {}).get("end_reason") or "finish"
            await self._finish(reason)
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
        # 앞의 넷은 더해서 total 이 되고, 합성은 전달 안에 든 값이다 (Marks.spans_ms
        # 참조). 대괄호로 묶어 더하는 칸이 아님을 드러낸다.
        log.info("턴 %d 지연 %.0fms  (전사 %.0f · 저장 %.0f · 질문 %.0f · 전달 %.0f [합성 %.0f])",
                 self.machine.turn, spans["total"], spans["stt"], spans["save"],
                 spans["question"], spans["deliver"], spans["tts"])
        await store.update_turn_marks(self, self.fragments[-1]["idx"], spans)
        await store.update_session(self)


# ---------------------------------------------------------------- 레지스트리
#
# **제거가 있어야 한다.** 예전에는 put·get 만 있었다. 어르신이 브라우저를 닫고 떠난
# 회차가 프로세스가 죽을 때까지 남는데, 회차 하나는 fragments(전사 전부)와 확정 전
# 발화 오디오를 들고 있다 — PCM 이 초당 32KB 라 10초 발화가 320KB 다 (audio.py 참조).
# 하루 돌리면 메모리가 계단식으로 올라가고, 밖에서는 「이유 없이 며칠에 한 번 죽는
# 서버」로 보인다. 타이머도 함께 남아 아무도 없는 회차에서 T1 이 계속 돈다.
#
# 여기 있는 것은 **한 프로세스 안의** 정리다. 인스턴스를 늘리면 _need(session_id) 가
# 애초에 깨진다 (회차가 어느 프로세스에 있는지 알 수 없다) — 그때는 상태를 밖으로
# (Redis 등) 내보내야 하고, 이 파일이 아니라 설계가 바뀐다.

_sessions: dict[str, SessionController] = {}


def put(ctl: SessionController) -> SessionController:
    _sessions[ctl.session_id] = ctl
    return ctl


def get(session_id: str) -> SessionController | None:
    return _sessions.get(session_id)


def all_sessions() -> list[SessionController]:
    return list(_sessions.values())


def live_sessions() -> list[SessionController]:
    """아직 닫히지 않은 회차. 동시 회차 상한이 보는 값이다."""
    return [c for c in _sessions.values() if c.machine.state is not State.CLOSED]


def user_live(user_id: str) -> int:
    """
    한 사용자가 지금 들고 있는 회차 수.

    **이 값으로 막는 것은 보안이 아니다.** user_id 는 X-User-Id 를 그대로 믿는
    값이라 바꿔 넣으면 통과한다 (limits.py 참조). 로그인이 붙으면 실효를 가진다.
    """
    return sum(1 for c in live_sessions() if c.user_id == user_id)


def max_live() -> int:
    return env_int("MAX_LIVE_SESSIONS", MAX_LIVE)


async def drop(session_id: str) -> bool:
    """
    회차 하나를 메모리에서 지운다. 아직 안 닫혀 있으면 이유를 남기고 닫는다.

    스윕과 같은 일을 하지만 시간을 보지 않는다 — 시험과 수동 정리용이다.
    """
    ctl = _sessions.pop(session_id, None)
    if ctl is None:
        return False
    if ctl.machine.state is State.CLOSED:
        ctl.release()
    else:
        await ctl.expire()
    return True


async def sweep() -> int:
    """
    오래된 회차를 정리한다. 지운 개수를 돌려준다.

    기준이 둘인 이유 —

        닫힌 회차    짧게 둔다. 화면이 마지막 상태(CLOSED)를 받아 갈 시간만
                     주면 되고, 그 뒤로는 DB 에 다 남아 있다.
        진행 중 회차  길게 둔다. 어르신이 한참 생각하시는 중일 수 있다.
                     잘못 지우면 말씀하시던 회차가 404 가 된다 — 되돌릴 수 없다.

    **정리에 실패해도 메모리에서는 뺀다.** expire() 가 DB 쓰기를 하는데, 그게
    실패했다고 회차를 메모리에 남겨 두면 다음 스윕에서 또 실패하고, 고쳐지지 않는
    한 영원히 안 지워진다 — 막으려던 누수가 그대로 돌아온다. DB 기록을 잃는 것과
    프로세스가 죽는 것 중에 앞을 고른다 (store.py 의 쓰기 원칙과 같다).
    """
    idle = env_float("SESSION_IDLE_SECONDS", IDLE_SECONDS)
    grace = env_float("SESSION_CLOSED_SECONDS", CLOSED_SECONDS)
    gone = 0

    for ctl in list(_sessions.values()):
        closed = ctl.machine.state is State.CLOSED
        limit = grace if closed else idle
        if limit <= 0 or ctl.idle_seconds() < limit:
            continue
        _sessions.pop(ctl.session_id, None)
        gone += 1
        if closed:
            ctl.release()
            continue
        try:
            await ctl.expire()
        except Exception as e:                              # noqa: BLE001
            log.error("회차 %s 정리 실패 (%s: %s) — 메모리에서는 뺀다",
                      ctl.session_id[:8], type(e).__name__, str(e)[:120])
            ctl.release()

    if gone:
        log.info("스윕 — 회차 %d개 정리, %d개 남음 (진행 중 %d)",
                 gone, len(_sessions), len(live_sessions()))
    return gone


async def sweep_forever() -> None:
    """
    main.py 의 lifespan 이 띄운다.

    **한 번 실패해도 멈추지 않는다.** 멈추면 그 뒤로 아무것도 정리되지 않는데
    로그에는 예외 한 줄만 남는다 — 누수는 조용히 돌아오고, 원인은 며칠 전 그
    한 줄이 된다. 그래서 예외를 삼키고 다음 주기를 돈다.
    """
    every = env_float("SWEEP_EVERY_SECONDS", SWEEP_EVERY)
    log.info("세션 스윕 시작 — %.0f초마다", every)
    while True:
        try:
            await asyncio.sleep(every)
            await sweep()
        except asyncio.CancelledError:
            raise
        except Exception as e:                              # noqa: BLE001
            log.error("스윕 실패 (%s: %s)", type(e).__name__, str(e)[:120])
