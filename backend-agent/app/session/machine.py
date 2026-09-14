"""
4단계 대화 상태 머신 — FR-AD-303
=================================

**순수 파이썬이다. FastAPI 도 asyncio 도 import 하지 않는다.**
그래야 전이를 단위 테스트로 전부 돌려볼 수 있고, 나중에 실시간 계층을 바꿔도
이 파일은 살아남는다.

    SPEAKING ──낭독 끝──▶ LISTENING ──T1 만료──▶ PROCESSING ──┬─▶ SPEAKING
                              ▲                              │      (질문 준비 AND T2 만료)
                              └──── 빈 전사 (턴 미소모) ──────┘
                                                             └─▶ CLOSED

여기서 가장 중요한 규칙 하나 — PROCESSING 을 빠져나가려면
**질문 준비와 T2 만료가 둘 다** 참이어야 한다.

  · 질문이 먼저 준비되면 → T2 가 끝날 때까지 기다린다 (어르신에게 여유를 준다)
  · T2 가 먼저 끝나면    → 질문이 올 때까지 기다린다 (지연이 그대로 드러난다)

즉 처리 시간이 T2 안에 들어오면 어르신은 지연을 전혀 못 느낀다.
T2 최솟값이 3초(빠름 설정)이므로, 예산은 그 3초를 기준으로 잡는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    SPEAKING = "SPEAKING"      # 질문 낭독 중. 수음하지 않는다
    LISTENING = "LISTENING"    # 오디오/텍스트 수신 중. T1 작동
    PROCESSING = "PROCESSING"  # 전사 확정 · 조각 저장 · 다음 질문 생성 중. T2 작동
    CLOSED = "CLOSED"          # 마감


class Event(str, Enum):
    TTS_DONE = "tts_done"              # 낭독 끝(또는 탭으로 중단)
    SPEECH_RECEIVED = "speech"         # 유효 발화 수신 → T1 리셋
    T1_EXPIRED = "t1_expired"          # 무음 T1 경과 → 발화 확정
    DONE_BUTTON = "done_button"        # 「다 말했어요」 → 즉시 확정
    T2_EXPIRED = "t2_expired"          # 다음 말 대기 종료
    QUESTION_READY = "question_ready"  # 다음 질문 생성 완료
    EMPTY_TRANSCRIPT = "empty"         # 전사가 비었다 → 턴 미소모
    FINISH = "finish"                  # AI 판단(또는 턴 제한을 둔 회차에서 최대 턴 도달)
    ABORT = "abort"                    # 사용자 중단


class TransitionError(RuntimeError):
    """정의되지 않은 전이. 조용히 무시하지 않는다."""


@dataclass
class Machine:
    state: State = State.SPEAKING
    turn: int = 0
    # **0 은 「제한 없음」이다.** 어디서 끝날지는 AI 의 close 판단(question.py)과
    # 어르신의 「중단」 버튼이 정한다 — 턴 수가 정하지 않는다. 회차를 몇 턴으로
    # 묶고 싶으면 회차를 열 때 값을 준다 (tools/replay.py 가 그렇게 쓴다).
    max_turn: int = 0

    # PROCESSING 을 빠져나가기 위한 두 조건
    question_ready: bool = False
    t2_expired: bool = False

    history: list[tuple[State, Event, State]] = field(default_factory=list)

    # ------------------------------------------------------------ 조회

    @property
    def turns_left(self) -> int:
        """제한이 없으면 -1. 0 을 쓸 수 없다 — 그건 「이번이 마지막」이라는 뜻이다."""
        if self.max_turn <= 0:
            return -1
        return max(0, self.max_turn - self.turn)

    @property
    def can_advance(self) -> bool:
        """PROCESSING → SPEAKING 조건. 둘 다 참이어야 한다."""
        return self.question_ready and self.t2_expired

    def accepts(self, event: Event) -> bool:
        return event in _ALLOWED.get(self.state, ())

    # ------------------------------------------------------------ 전이

    def fire(self, event: Event) -> State:
        if event is Event.ABORT:
            return self._to(State.CLOSED, event)

        if not self.accepts(event):
            raise TransitionError(f"{self.state.value} 상태에서 {event.value} 는 정의되지 않았다")

        before = self.state

        if before is State.SPEAKING and event is Event.TTS_DONE:
            return self._to(State.LISTENING, event)

        if before is State.LISTENING:
            if event is Event.SPEECH_RECEIVED:
                return self._to(State.LISTENING, event)          # 자기 전이. T1 은 밖에서 리셋
            if event in (Event.T1_EXPIRED, Event.DONE_BUTTON):
                # 발화 확정 = 턴 소모. T2 는 여기서부터 센다 (말을 멈춘 시각이 아니다)
                self.turn += 1
                self.question_ready = False
                self.t2_expired = False
                return self._to(State.PROCESSING, event)

        if before is State.PROCESSING:
            if event is Event.EMPTY_TRANSCRIPT:
                self.turn -= 1                                    # 턴 미소모 (FR-AD-312)
                return self._to(State.LISTENING, event)
            if event is Event.FINISH:
                return self._to(State.CLOSED, event)
            if event is Event.QUESTION_READY:
                self.question_ready = True
            elif event is Event.T2_EXPIRED:
                self.t2_expired = True
            if self.can_advance:
                if self.max_turn and self.turn >= self.max_turn:
                    return self._to(State.CLOSED, event)          # 최대 턴 도달
                return self._to(State.SPEAKING, event)
            return self._to(State.PROCESSING, event)              # 아직 한쪽만 참

        raise TransitionError(f"처리되지 않은 전이: {before.value} + {event.value}")

    def _to(self, nxt: State, event: Event) -> State:
        self.history.append((self.state, event, nxt))
        self.state = nxt
        return nxt


_ALLOWED: dict[State, tuple[Event, ...]] = {
    State.SPEAKING: (Event.TTS_DONE, Event.ABORT),
    State.LISTENING: (Event.SPEECH_RECEIVED, Event.T1_EXPIRED, Event.DONE_BUTTON, Event.ABORT),
    State.PROCESSING: (Event.QUESTION_READY, Event.T2_EXPIRED, Event.EMPTY_TRANSCRIPT,
                       Event.FINISH, Event.ABORT),
    State.CLOSED: (),
}
