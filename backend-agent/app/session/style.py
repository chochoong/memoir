"""
문체 — 엽서와 자서전이 같이 받는 `style` 값 (4-C1 §2)

    spoken    구어체    기본. 값을 안 보내면 이것이다
    novel     소설체    4-P1 이 오기 전에는 지원 목록에 없다
    cyworld   싸이월드체 4-P1 이 오기 전에는 지원 목록에 없다

**지원하지 않는 값은 거절한다.** 다른 문체로 바꿔 쓰지 않는다 — 소설체를 골랐는데
구어체로 만들어 주면 화면이 고른 것과 다른 글을 보여 준다 (지시서 S1 「임의 fallback」).
라우트가 400 `{"detail", "code": "unsupported_style"}` 로 바꾼다.

**지금은 모델에 문체를 보내지 않는다.** 지원하는 것이 spoken 하나이고, 실행본
(엽서_v3 · 자서전_v4) 는 style 이 없으면 spoken 으로 쓴다. 나머지 둘은 4-P1 의 지시가
온 뒤에 SUPPORTED 에 더한다.
"""

from __future__ import annotations

DEFAULT = "spoken"
SUPPORTED = (DEFAULT,)
CODE = "unsupported_style"
SAYS = "지원하지 않는 문체예요."


class UnsupportedStyle(ValueError):
    """모르는 값 · 아직 지원하지 않는 값. 400."""


def pick(v) -> str:
    """
    요청 본문의 style. **키가 없을 때(None)만** 기본값이다 — 빈 문자열 · 숫자 ·
    대소문자만 다른 값도 거절한다. 화면이 보낸 값을 서버가 짐작해 고치지 않는다.
    """
    if v is None:
        return DEFAULT
    if v not in SUPPORTED:
        raise UnsupportedStyle(f"style={v!r}")
    return v
