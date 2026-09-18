"""
환경변수 읽기 — 값이 틀렸을 때 **조용히 0 이 되지 않게** 하는 자리

환경변수는 반드시 **함수 안에서** 읽는다. main.py 가 load_dotenv() 를 import 뒤에
부르기 때문에, 모듈 수준에서 읽으면 .env 가 아직 로드되기 전이라 빈 값을 잡는다
(store.py · question.py 의 같은 주석 참조).

`int(os.environ.get(X) or default)` 를 그냥 쓰면 두 가지로 아프다. 오타 하나가
ValueError 로 기동을 막거나, 더 나쁘게는 상한 값이 0 (= 「제한 없음」) 이 된 것을
아무도 모른다. 상한은 걸리지 않을 때 아무 소리도 내지 않으므로, 꺼져 있는 것과
잘 돌고 있는 것이 로그에서 똑같이 보인다. 여기서 잡아 말하고 기본값으로 돈다.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("conf")


def env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        log.warning("%s=%r 를 숫자로 읽을 수 없다 — 기본값 %s 로 돈다", name, raw, default)
        return default


def env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        log.warning("%s=%r 를 숫자로 읽을 수 없다 — 기본값 %s 로 돈다", name, raw, default)
        return default


def env_flag(name: str) -> bool:
    """켜는 쪽만 명시적으로 인정한다. 오타는 꺼진 것으로 읽는다 — 안전한 쪽이다."""
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def env_str(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default
