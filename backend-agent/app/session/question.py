"""
다음 질문 생성 — Gemini (Day 5)

`controller.QuestionFn` 자리에 그대로 들어간다. 시그니처만 맞으면 되고,
FSM 도 타이머도 이 파일의 존재를 모른다.

지켜야 하는 것 셋.

1. **예산은 T2 최솟값 3초다.** 생성이 그 안에 끝나야 처리 시간이 침묵 안에 숨는다.
   넘기면 어르신이 지연을 그대로 느낀다. 그래서 thinking 을 최소로 내리고
   타임아웃을 3초보다 짧게 잡는다 (`GEMINI_TIMEOUT`, 기본 2.5초).

2. **실패가 회차를 끝내면 안 된다.** controller._make_question 은 None 을 받으면
   CLOSED 로 간다. 그건 「AI 가 그만 물어도 되겠다고 판단했다」는 뜻이어야지,
   네트워크가 한 번 끊겼다는 뜻이면 안 된다. 그래서 오류·타임아웃은 여기서 삼키고
   고정 질문으로 물러선다. **None 은 오직 판단 결과일 때만 돌려준다.**

3. **회차를 끝내는 문은 이제 여기 하나뿐이다.** 턴 상한(`max_turn`)을 0(제한 없음)
   으로 열어 둔 뒤로, 대화가 끝나는 자리는 close 판단과 「중단」 버튼밖에 없다.
   그래서 close 에 하한을 뒀다 — `MIN_TURN`(기본 3) 전에는 모델이 close 를 골라도
   따르지 않고 다시 여쭙는다. 상한은 없애고 하한만 남겼다.

환경변수는 **함수 안에서** 읽는다. main.py 가 `load_dotenv()` 를 import 뒤에
호출하기 때문에, 모듈 수준에서 읽으면 .env 가 아직 로드되기 전이라 빈 값을 잡는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .controller import SessionController

log = logging.getLogger("question")

DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_TIMEOUT = 2.5           # T2 최솟값 3초보다 짧아야 의미가 있다

# 이 턴 전에는 close 를 따르지 않는다. 아래 gemini_question 참조.
DEFAULT_MIN_TURN = 3

_SYSTEM = """당신은 어르신의 인생 이야기를 듣는 인터뷰어입니다.
방금 하신 말씀에 이어, 그 기억을 더 선명하게 떠올리실 수 있는 질문을 하나만 하세요.

규칙:
- 한 문장, 존댓말, 40자 이내.
- 사실 확인이 아니라 감각과 마음을 묻습니다. (무엇이 보였는지, 어떤 소리가 났는지, 어떤 마음이었는지)
- 이미 하신 질문과 겹치지 않게 합니다.
- 어르신이 모르실 만한 어려운 말을 쓰지 않습니다.
- **대답이 질문과 어긋나거나, 못 알아들으신 것 같거나, 한두 마디로 짧아도 close 가 아닙니다.**
  그때는 같은 기억을 더 쉬운 말로 다시 여쭙습니다.
- close 는 이야기가 충분히 여물어 더 여쭐 것이 없을 때만 고릅니다. 몇 마디 나누지 않았다면 고르지 않습니다.

반드시 아래 JSON 으로만 답하세요.
{"action": "ask", "question": "질문 한 문장", "reason": "왜 이걸 묻는지 짧게"}
{"action": "close", "question": null, "reason": "왜 마무리해도 되는지 짧게"}"""


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


_CLIENT = None


def _transcript(ctl: "SessionController") -> str:
    """
    지금까지의 조각을 프롬프트에 넣을 형태로. 0번은 엽서라 질문이 없다.

    빈 answer 는 넣지 않는다. 엽서를 비워 두고 회차를 열면 (프론트 기본값이
    비어 있다) 0번 조각의 answer 가 빈 문자열인데, 그대로 넣으면 프롬프트 맨
    위에 내용 없는 「어르신:」 한 줄이 얹힌다. 1번부터는 빈 전사가 턴을 소모하지
    않으므로 (controller._confirm) answer 가 비는 일이 없다.
    """
    out = []
    for f in ctl.fragments:
        if f["question"]:
            out.append(f"질문: {f['question']}")
        if f["answer"]:
            out.append(f"어르신: {f['answer']}")
    return "\n".join(out)


async def gemini_question(ctl: "SessionController") -> str | None:
    """
    다음 질문. 판단 결과로 마무리해야 할 때만 None 을 돌려준다.

    키가 없으면 고정 질문으로 돈다 — 키 없이도 흐름 전체가 돌아가야
    프론트 작업이 백엔드 키 발급을 기다리지 않는다.
    """
    client = _client()
    if client is None:
        from .controller import fixed_questions
        log.info("GEMINI_API_KEY 없음 — 고정 질문으로 돈다")
        return await fixed_questions(ctl)

    model = os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    try:
        timeout = float(os.environ.get("GEMINI_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        timeout = DEFAULT_TIMEOUT

    from google.genai import types

    cfg = types.GenerateContentConfig(
        system_instruction=_SYSTEM,
        response_mime_type="application/json",
        temperature=1.0,
        max_output_tokens=200,
        # 지연이 곧 품질인 구간이다. 생각을 오래 할수록 어르신이 기다린다.
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
        # 도구를 쓰지 않는다. 켜 두면 호출마다 AFC 로그가 한 줄씩 쌓여
        # 정작 봐야 할 지연 숫자가 묻힌다.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    try:
        res = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model, contents=_transcript(ctl), config=cfg),
            timeout=timeout)
        data = json.loads((res.text or "").strip())
    except asyncio.TimeoutError:
        log.warning("질문 생성 %.1fs 초과 — 고정 질문으로 물러선다 (회차는 계속)", timeout)
        return await _fallback(ctl)
    except Exception as e:                                   # noqa: BLE001
        log.error("질문 생성 실패(%s: %s) — 고정 질문으로 물러선다", type(e).__name__, e)
        return await _fallback(ctl)

    action = (data.get("action") or "").lower()
    reason = data.get("reason") or ""
    # 지금은 로그로만 보이지만 store 가 turn.decision(JSONB) 으로 내린다.
    # 「왜 이 질문을 했나 · 왜 마무리했나」를 나중에 되짚을 수 있어야 한다 (FR-IV-006).
    ctl.last_decision = {"action": action, "reason": reason}

    if action == "close":
        # **바닥을 하나 깐다.** 턴 상한을 없앤 뒤로 close 는 회차를 끝내는 유일한
        # 문이 됐는데, 실제로 돌려보니 어르신이 질문과 어긋난 말씀을 한 번 하신
        # 것만으로 모델이 마무리를 골랐다 (「어떻게 지금 돼가고 있어?」 → 턴 1 종료).
        # 어르신이 못 알아들으셨거나 되물으시는 건 흔한 일이고, 그때 할 일은
        # 회차를 닫는 게 아니라 다시 여쭙는 것이다. 그래서 min 턴 전의 close 는
        # 따르지 않고 질문으로 되돌린다 — 상한은 없애고 하한만 남긴 셈이다.
        if ctl.machine.turn < _min_turn():
            log.info("AI 가 마무리를 골랐지만 아직 %d턴이다 — 다시 여쭙는다 (%s)",
                     ctl.machine.turn, reason)
            ctl.last_decision = {"action": "ask", "reason": reason,
                                 "overruled": "close"}
            return await _fallback(ctl)
        # FR-IV-006 — 판단으로 마무리. DB 가 붙으면 turn.decision 에 들어갈 값이다.
        log.info("AI 판단: 마무리 — %s", reason)
        return None

    q = (data.get("question") or "").strip()
    if not q:
        log.warning("action=ask 인데 question 이 비었다 — 고정 질문으로 물러선다")
        return await _fallback(ctl)

    log.info("질문 준비 — %s (%s)", q, reason)
    return q


def _min_turn() -> int:
    try:
        return max(0, int(os.environ.get("MIN_TURN") or DEFAULT_MIN_TURN))
    except ValueError:
        return DEFAULT_MIN_TURN


async def _fallback(ctl: "SessionController") -> str:
    """
    실패했을 때. **절대 None 을 돌려주지 않는다** — None 은 CLOSED 로 가는 신호라
    네트워크 오류로 어르신의 회차가 끊기게 된다.
    """
    from .controller import fixed_questions
    return await fixed_questions(ctl) or "그때 이야기를 조금 더 들려주시겠어요?"


async def warmup() -> None:
    """
    기동 시 한 번. 클라이언트 생성과 TLS 연결을 미리 끝내 둔다.

    안 하면 **첫 어르신이 그 비용을 다 낸다.** 실측으로 첫 호출 2864ms, 이후 ~950ms 였다.
    차이의 대부분은 질문 생성이 아니라 genai.Client() 생성과 첫 연결이고, 둘 다
    gemini_question 의 wait_for 바깥에서 일어나 **타임아웃으로 막히지도 않는다.**

    실패해도 조용히 넘어간다. 예열은 최적화일 뿐이라 여기서 기동을 막을 이유가 없다.
    """
    client = _client()
    if client is None:
        return
    try:
        from google.genai import types
        await asyncio.wait_for(
            client.aio.models.generate_content(
                model=os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL,
                contents="ping",
                config=types.GenerateContentConfig(
                    max_output_tokens=1,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                )),
            timeout=10)
        log.info("Gemini 예열 완료")
    except Exception as e:                                   # noqa: BLE001
        log.warning("Gemini 예열 실패(%s) — 첫 질문이 느릴 수 있다", type(e).__name__)
