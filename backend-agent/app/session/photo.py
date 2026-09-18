"""
사진 분석 — Gemini VLM

`docs/인터뷰 에이전트_프롬프트.md` §2(사진 분석 에이전트)를 그대로 불러 쓴다.
shared_state 연결은 이 파일의 범위 밖이다 — photo_analyses 에 얹는 일은 다른
곳(최충 님 담당)이 한다. 여기는 사진 한 장을 받아 §2 가 정한 JSON 하나를
돌려주는 것까지만 한다.

최충 님 확인 전 가정 (아래 여섯 가지는 문서·기존 코드에 명시가 없어 임시로 정함)
- **위치**: `app/session/photo.py` — question.py·prompt.py 와 같은 계층에 둠.
- **async**: `question.py` 의 호출 관례를 따라 `async def` 로 만듦.
- **실패 시 None**: question.py 는 "None 은 회차 종료 신호"라 실패해도 절대
  None 을 안 돌려주지만, 사진 분석에는 그런 부작용이 없다고 보고 실패 시
  그대로 None 을 돌려주기로 함. 호출자가 재시도·보류를 판단.
- **mime_type 인자**: 업로드가 어떤 형식으로 넘어올지 아직 안 정해져서
  `bytes + mime_type` 을 입력 인터페이스로 가정함 (기본값 "image/jpeg").
- **타임아웃 10초**: question.py 의 2.5초는 "T2 3초 예산"에 묶인 값인데,
  사진 분석은 그 예산 밖이라고 보고 임시로 10초를 넣음 — 실측 후 조정 필요.
- **프롬프트 읽는 위치**: prompt.py 의 비공개 파싱 함수를 가져다 쓰지 않고
  이 파일이 문서를 직접 읽는다 (아래 `_load_prompt` 참조) — prompt.py 는
  §0+§1(인터뷰용)로 고정돼 있어 그대로 재사용할 수 없었음.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("photo")

# app/session/photo.py → backend-agent/
DOC = Path(__file__).resolve().parents[2] / "docs" / "인터뷰 에이전트_프롬프트.md"

DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_TIMEOUT = 10.0          # 임시값 — 위 "최충 님 확인 전 가정" 참조

COMMON = "0"
PHOTO = "2"
_STATE_MARK = "[현재 공유 상태]"

_HEADING = re.compile(r"^##\s*(\d+)\.")
_FENCE = re.compile(r"^```(.*)$")
_LANG = re.compile(r"^[A-Za-z0-9_+-]{0,12}$")

# §2 출력(JSON)이 정한 여섯 키. 응답 검증에만 쓰고 값은 건드리지 않는다.
_REQUIRED_KEYS = ("scene", "objects", "people", "text_in_photo", "uncertain", "questions")


class PromptError(RuntimeError):
    """문서를 못 읽거나 모양이 다르다."""


@lru_cache(maxsize=1)
def _load_prompt() -> str:
    """
    §0 앞부분(공유 상태 틀 제외) + §2 를 읽어 하나의 system prompt 로 합친다.

    prompt.py 의 `_blocks` 등 비공개 함수는 가져다 쓰지 않는다 — 이 모듈은
    §1(인터뷰용)이 아니라 §2 만 있으면 되고, 실패했을 때 할 일도 다르다
    (거기는 기동을 막지만 여기는 None 으로 물러나면 된다). 그래서 같은 모양의
    파싱을 이 파일 안에 따로 둔다. §2 텍스트 자체는 어디에도 복사해 두지
    않고, 호출될 때마다(캐시 전이라면) 문서를 직접 읽는다.
    """
    try:
        text = DOC.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise PromptError(f"프롬프트 문서를 찾을 수 없다: {DOC}") from e
    except UnicodeDecodeError as e:
        raise PromptError(f"프롬프트 문서가 UTF-8 이 아니다: {DOC}") from e

    blocks: dict[str, str] = {}
    section: str | None = None
    buf: list[str] | None = None
    for line in text.splitlines():
        head = _HEADING.match(line)
        if head and buf is None:            # 블록 안의 ## 은 본문이다
            section = head.group(1)
            continue

        fence = _FENCE.match(line)
        if not fence:
            if buf is not None:
                buf.append(line)
            continue

        if buf is not None:                 # 닫는 울타리
            if section is not None and section not in blocks:
                blocks[section] = "\n".join(buf).strip()
            buf = None
            continue

        if section is None or section in blocks:
            continue                        # 한 절에서 첫 블록만 쓴다

        tail = fence.group(1).strip()
        buf = [] if _LANG.match(tail) else [tail]

    missing = [n for n in (COMMON, PHOTO) if not blocks.get(n)]
    if missing:
        raise PromptError(
            f"{DOC.name} 에 §{' · §'.join(missing)} 의 ``` 블록이 없다 "
            f"(찾은 절: {sorted(blocks) or '없음'})")

    common = blocks[COMMON]
    at = common.rfind(_STATE_MARK)
    head = common[:at].rstrip() if at >= 0 else common
    return f"{head}\n\n{blocks[PHOTO]}"


_CLIENT = None


def _client():
    """키가 없으면 None. 클라이언트는 한 번만 만들어 재사용한다."""
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        return None
    global _CLIENT
    if _CLIENT is None:
        from google import genai
        _CLIENT = genai.Client(api_key=key)
    return _CLIENT


async def analyze_photo(image: bytes, mime_type: str = "image/jpeg") -> dict | None:
    """
    사진 한 장을 §2 규칙대로 분석한다.

    실패(키 없음·타임아웃·예외·JSON 아님·dict 아님)하면 로그만 남기고 None 을
    돌려준다 — 위 "최충 님 확인 전 가정" 참조.
    """
    client = _client()
    if client is None:
        log.warning("GEMINI_API_KEY 없음 — 사진 분석을 건너뛴다")
        return None

    try:
        system = _load_prompt()
    except PromptError as e:
        log.error("프롬프트 로드 실패(%s) — 사진 분석을 건너뛴다", e)
        return None

    model = os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL

    from google.genai import types

    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        temperature=0.2,
        # 도구를 쓰지 않는다. 켜 두면 호출마다 AFC 로그가 한 줄씩 쌓인다 (question.py 참조).
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    parts = [types.Part.from_bytes(data=image, mime_type=mime_type)]

    try:
        res = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=parts)],
                config=cfg),
            timeout=DEFAULT_TIMEOUT)
        data = json.loads((res.text or "").strip())
    except asyncio.TimeoutError:
        log.warning("사진 분석 %.1fs 초과 — 건너뛴다", DEFAULT_TIMEOUT)
        return None
    except Exception as e:                                       # noqa: BLE001
        log.error("사진 분석 실패(%s: %s) — 건너뛴다", type(e).__name__, e)
        return None

    if not isinstance(data, dict):
        log.error("응답이 객체가 아니다(%s) — 건너뛴다", type(data).__name__)
        return None

    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        log.warning("응답에 %s 키가 없다 — 그대로 반환한다", missing)

    return data
