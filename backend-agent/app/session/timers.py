"""
T1 / T2 타이머 — FR-AD-308 · FR-AD-310

  T1  마지막 유효 발화 수신 시각 → 3.0초    발화 확정
  T2  조각이 확정된 시각        → 3/5/7초   다음 질문 발행

두 가지를 반드시 지킨다.

1. **격발 오차를 항상 잰다.** 예약 시각과 실제 격발 시각의 차이를 기록한다.
   이벤트 루프가 밀리기 시작하는 순간을 부하 테스트 없이도 알아챌 수 있다.
   기능보다 먼저 넣어야 하는 계측이다 (허용 오차 ±200ms).

2. **T1 은 발화가 올 때마다 리셋한다.** T2 는 리셋하지 않는다 —
   T2 가 도는 동안 발화가 오면 그건 타이머 리셋이 아니라 상태 전이다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

log = logging.getLogger("timers")

T1_SECONDS = 3.0
T2_PRESETS = {"fast": 3.0, "normal": 5.0, "slow": 7.0}
DRIFT_WARN_MS = 200.0


@dataclass
class Fire:
    name: str
    scheduled_at: float
    fired_at: float

    @property
    def drift_ms(self) -> float:
        return (self.fired_at - self.scheduled_at) * 1000


@dataclass
class TimerSet:
    """한 회차의 타이머. 회차마다 하나씩 만든다."""
    on_t1: Callable[[], Awaitable[None]]
    on_t2: Callable[[], Awaitable[None]]
    t1_seconds: float = T1_SECONDS
    t2_seconds: float = T2_PRESETS["normal"]

    fires: list[Fire] = field(default_factory=list)
    _t1: asyncio.Task | None = None
    _t2: asyncio.Task | None = None

    # ------------------------------------------------------------ T1

    def reset_t1(self) -> None:
        """유효 발화를 받을 때마다 호출. 이전 예약을 버리고 다시 건다."""
        self.cancel_t1()
        self._t1 = asyncio.create_task(self._run("T1", self.t1_seconds, self.on_t1))

    def cancel_t1(self) -> None:
        if self._t1 and not self._t1.done():
            self._t1.cancel()
        self._t1 = None

    # ------------------------------------------------------------ T2

    def start_t2(self) -> None:
        """조각이 확정 저장된 뒤에 호출한다. 말을 멈춘 시각이 아니다."""
        self.cancel_t2()
        self._t2 = asyncio.create_task(self._run("T2", self.t2_seconds, self.on_t2))

    def cancel_t2(self) -> None:
        if self._t2 and not self._t2.done():
            self._t2.cancel()
        self._t2 = None

    def cancel_all(self) -> None:
        self.cancel_t1()
        self.cancel_t2()

    # ------------------------------------------------------------ 내부

    async def _run(self, name: str, seconds: float,
                   cb: Callable[[], Awaitable[None]]) -> None:
        scheduled = time.perf_counter() + seconds
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        fired = time.perf_counter()
        f = Fire(name=name, scheduled_at=scheduled, fired_at=fired)
        self.fires.append(f)
        if abs(f.drift_ms) > DRIFT_WARN_MS:
            log.warning("%s 격발 오차 %.0fms — 이벤트 루프가 밀리고 있다", name, f.drift_ms)
        else:
            log.info("%s 격발 (오차 %.0fms)", name, f.drift_ms)
        await cb()

    def drift_report(self) -> dict[str, float]:
        if not self.fires:
            return {}
        d = [abs(f.drift_ms) for f in self.fires]
        return {"n": len(d), "max_ms": max(d), "avg_ms": sum(d) / len(d)}
