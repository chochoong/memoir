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
   으로 열어 둔 뒤로, 대화가 끝나는 자리는 종료 판단과 「중단」 버튼밖에 없다.
   그래서 하한을 뒀다 — `MIN_TURN`(기본 3) 전에는 모델이 마무리를 골라도 따르지
   않고 다시 여쭙는다. 상한은 없애고 하한만 남겼다.

   **문 이름은 `topic_status: "closed"` 하나다.** 예전에 쓰던 `action: "close"` 는
   버렸다. 문서(§1)가 정한 이름과 코드가 쓰던 이름이 둘 다 살아 있으면 언젠가
   반드시 어긋나고, 어긋나는 쪽이 「회차가 안 끝난다」라 눈에도 잘 안 띈다.

4. **프롬프트는 `prompts/interview_v2.3.txt` 에서 읽는다** (prompt.py).
   여기에 한 벌 더 두지 않는다. 다만 그 파일에 아직 없는 세 필드(`facts_found` ·
   `information_status` · `completion_check_asked`)만 `_ADDENDUM` 으로 덧댄다 —
   아래 참조.

**빈 `question` 은 값이다.** 문서 §1 이 「질문하지 않는 종료 턴에는 question 을
빈 문자열로 둡니다」라고 정했다. 그래서 `topic_status` 를 **먼저** 보고 빈 question
검사는 그 뒤에 한다. 순서가 뒤집히면 어르신이 「그만하자」 하셔도 종료 턴이
고정 질문으로 덮여 회차가 안 끝난다.

환경변수는 **함수 안에서** 읽는다. main.py 가 `load_dotenv()` 를 import 뒤에
호출하기 때문에, 모듈 수준에서 읽으면 .env 가 아직 로드되기 전이라 빈 값을 잡는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import TYPE_CHECKING

from . import prompt as promptlib
from . import shared as shared_state

if TYPE_CHECKING:
    from .controller import SessionController

log = logging.getLogger("question")

DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_TIMEOUT = 2.5           # T2 최솟값 3초보다 짧아야 의미가 있다

# 이 턴 전에는 마무리를 따르지 않는다. 아래 gemini_question 참조.
#
# 3 에서 올렸다. 문서 프롬프트로 실제 회차를 돌려 보니 **3턴 만에 닫혔다** —
# 씨앗 한 줄("열아홉에 고향을 떠나 서울로 올라왔지. 큰형이 영등포역까지 마중을
# 나왔어")에 when·event·who·place 가 전부 들어 있어 턴 1 에 information_status 가
# 다 차 버리고, 그러면 §1 의 「필요한 정보가 모이면 세부 질문을 계속하지
# 않습니다」가 곧바로 발동한다. 어르신이 국밥 이야기를 막 꺼내신 참이었다.
#
# 아래 _ADDENDUM 의 [마무리 판단] 이 그 판단 자체를 고치고, 이 하한은 그것이
# 흔들릴 때의 바닥이다. 둘은 같은 것을 두 겹으로 막는다.
DEFAULT_MIN_TURN = 6

# 프롬프트에 실어 보낼 대화의 길이. 0 이면 전부.
#
# 자르는 이유가 둘이다. 하나는 지연 — 창이 없으면 턴 20 의 입력이 턴 1 의 스무
# 배가 되고, 그게 그대로 응답 시간이 된다 (실측 질문 생성 875~1110ms 의 흔들림이
# 여기다). 다른 하나는 품질 — 오래된 조각이 계속 실려 있으면 모델이 지금 하시는
# 말씀 대신 옛 이야기로 되돌아간다. 씨앗(0번)은 회차의 주제라 창 밖이어도 남긴다.
DEFAULT_WINDOW = 6

# 문서에 아직 없는 부분. **B안** — 인터뷰 에이전트가 질문만이 아니라 「이번 턴에
# 무엇이 확인됐는지」까지 함께 답하게 한다.
#
# 문서 §1 은 `information_status` 를 **읽으라고만** 하고, 그것을 missing 에서
# confirmed 로 바꾸는 주체가 문서 어디에도 없다. 채우는 사람이 없으면 §1 의
# 종료 조건(「기본 정보가 모이면」)이 영원히 참이 되지 않아 대화가 안 끝난다.
# 추출 에이전트를 따로 두면 턴마다 호출이 하나 더 붙으므로 (지연·비용 2배),
# 어차피 속으로 판단하고 있는 것을 출력에 적게 하는 쪽을 골랐다.
#
# **덧대기만 한다. 프롬프트가 이미 정한 것은 다시 적지 않는다.** 여기서 한 번
# 어겼다가 값을 치렀다 — 「합쳐 40자」라고 적었는데 §1 은 다른 수였고, 모델은 둘
# 사이의 어느 수를 내놓았다. 어느 쪽도 지키지 않은 셈이다. 길이·문장 수처럼 §1 에
# 이미 있는 규칙(지금은 합쳐 60자)은 그쪽 것으로 두고, 없는 것만 더한다.
#
# **출력의 필드 순서도 문서를 따른다.** 여기서 question 을 empathy 앞에 놓았더니
# 모델이 질문 칸 안에서 먼저 공감을 하고 (JSON 은 적는 순서대로 생각한다) 그
# 공감이 empathy 와 겹쳤다 — 같은 대본으로 6턴씩 두 번 돌려 2턴·3턴이 되풀이였다.
# 문서 순서(공감 → 질문)로 되돌리자 같은 대본에서 0턴·0턴이 됐다. 아래
# _one_question 이 잘라 내던 것의 출처가 여기였다.
#
# **문서에 합쳐지면 이 상수는 지운다.** 두 벌로 오래 두면 갈라진다.
_ADDENDUM = """
[공감 문장]
- empathy에는 문장을 하나만 적습니다. 마침표는 한 번만 씁니다.
- 어르신의 말씀을 그대로 되풀이하지 않습니다. 짧게 받아 주기만 합니다.

[이번 턴에 확인된 것]
- facts_found에는 이번 턴에 어르신이 새로 말씀하신 사실만 적습니다.
- 어르신이 말씀하신 표현을 그대로 짧게 적습니다. 다듬거나 추측하지 않습니다.
- 각 항목은 15자를 넘기지 않습니다. 느낌이나 감상이 아니라 사실만 적습니다.
- 새로 확인된 것이 없으면 빈 배열로 둡니다.
- 앞서 확인된 사실을 어르신이 아니라고 하시면 facts_retracted에 그 사실을 그대로 적습니다.
- information_status에는 지금까지 확인된 정보의 상태를 다시 적습니다.
- 한 번 confirmed가 된 항목은 어르신이 아니라고 하시기 전에는 되돌리지 않습니다.
- 더 남기고 싶은 이야기가 있는지 여쭈는 턴에는 completion_check_asked를 true로 적습니다.

[마무리 판단]
- 어르신이 직접 그만하자고 하시기 전에는, 감각에 관한 기억이 세 가지 이상 나오기 전까지
  topic_status를 closed로 적지 않습니다.
- 정보가 모였더라도 어르신이 방금 새로운 이야기를 꺼내셨다면 그 이야기를 먼저 여쭙습니다.
- 확인된 사실의 개수는 마무리의 근거가 아닙니다. 이야기가 여물었는지로 판단합니다.

출력(JSON)은 반드시 아래 순서와 형식으로만 적습니다.
{
  "empathy": "공감 한 문장",
  "question": "질문 한 문장 또는 빈 문자열",
  "question_type": "회상확장|사실확인|주제전환|안전확인|없음",
  "sense_used": "시각|청각|후각|미각|촉각|없음",
  "facts_found": ["어르신이 새로 말씀하신 사실"],
  "facts_retracted": ["어르신이 아니라고 하신 사실"],
  "information_status": {"event": "", "when": "", "who": "", "place": "", "emotion": ""},
  "conversation_mode": "normal|sensitive",
  "topic_status": "active|awaiting_choice|closed",
  "completion_check_asked": true 또는 false,
  "ready_for_chronology": true 또는 false,
  "closing_hint": "대화 종료 시 화면에 띄울 안내 문구 (종료가 아니면 null)",
  "end_reason": "user_request|info_complete|sensitive (종료가 아니면 null)"
}"""


# 공감도 질문도 **한 문장씩만** 내보낸다. 여기는 이제 바닥이다.
#
# 되풀이가 쏟아지던 때가 있었다 — 8턴 중 6턴이 같은 말을 고쳐 썼다. 「눈이 참
# 많이 왔었군요. 눈이 참 많이 왔군요. 온통 하얗던 그때 풍경은 어땠나요?」
# 프롬프트로 두 번 조였고 두 번 다 남아서, 세 번째로 조이는 대신 여기서 잘랐다.
# 그 뒤에 원인이 프롬프트가 아니라 **출력 필드 순서**였다는 것이 드러났고
# (위 _ADDENDUM 참조) 순서를 문서대로 되돌리자 같은 대본에서 한 번도 안 나왔다.
#
# 그래도 남겨 둔다. 자르는 값이 싸고, 모델이 무엇을 적어 오든 어르신 귀에 가는
# 것은 두 문장이어야 한다. 원인을 고쳤다고 바닥까지 걷어낼 이유는 없다.
#
# **되풀이가 앉던 자리는 question 쪽이다.** 위 예에서 empathy 는 규칙대로 한
# 문장이었고 (「눈이 참 많이 왔었군요.」), 두 번째 공감은 question 안에 들어
# 있었다. 그래서 자르는 방향이 서로 반대다 — 공감은 **앞에서**, 질문은
# **뒤에서** 가져온다. 질문은 마지막 물음표가 붙은 문장이 본체다.
#
# 공감의 첫 문장이 너무 짧으면 다음 문장까지 가져온다. 「네… 뜨끈한 국밥이
# 좋으셨겠어요.」처럼 추임새로 여는 턴이 있어서, 첫 마디만 자르면 공감이
# 통째로 사라진다.
_SENTENCE = re.compile(r"[^.!?…]+[.!?…]*")
_EMPATHY_MIN = 6


def _one_sentence(text: str) -> str:
    parts = [m.group().strip() for m in _SENTENCE.finditer(text)]
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return text
    out = ""
    for p in parts:
        out = f"{out} {p}".strip()
        if len(out.rstrip(".!?… ")) >= _EMPATHY_MIN:
            break
    return out


def _one_question(text: str) -> str:
    """질문은 **뒤에서** 가져온다. 앞에 붙은 것은 공감의 되풀이다."""
    parts = [m.group().strip() for m in _SENTENCE.finditer(text)]
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return text
    for p in reversed(parts):
        if p.endswith(("?", "？")):
            return p
    return parts[-1]


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


# 어르신 말씀의 **끝 물음표를 떼고 모델에게 준다.** 기록은 건드리지 않는다 —
# turn.answer 에는 들으신 그대로 남는다. 여기는 모델에게 보낼 사본이다.
#
# Azure 는 억양을 보고 부호를 단다. 그게 한국어에서는 뜻을 흐리는 게 아니라
# **뒤집는다.**
#
#     칠순 잔치 아니야.   아니라는 말씀
#     칠순 잔치 아니야?   맞지 않냐는 물음 — 칠순잔치라는 뜻이 된다
#
# 실제 회차에서 어르신이 글자까지 같은 말씀을 두 번 하셨는데 한 번은 `?` 로,
# 한 번은 `.` 으로 왔다. 모델은 그 부호를 따라 정반대로 움직였고, 아니라는
# 말씀을 두 번 더 하시게 만들었다.
#
# **못 믿을 뿐 아니라 없어도 된다.** 의문사(뭐·언제·어디)나 의문 어미(-까·-나)가
# 있으면 부호 없이도 되물음인 줄 안다. 부호만이 단서인 것은 `아니야?` `맞아?`
# 처럼 평서형으로 끝나는 판정의문문뿐인데, 측정한 오류가 전부 거기 몰려 있었다.
# 평서문으로 넣은 「…사진 찍은 거야」도 확신도 0.93 으로 `?` 가 붙어 돌아왔다.
#
# 같은 대본 4회씩 — 칠순잔치로 단정한 턴 12회 → 5회, 어르신이 아니라고 하신 뒤
# 빠져나오는 자리 4번째 → 2번째.
#
# **API 로 끌 수는 없다.** Fast Transcription 은 배치 전사의 punctuationMode 를
# 조용히 무시하고(같은 결과, 오류도 없다), 부호 없는 형태(lexical)를 주지 않는다.
# combinedPhrases 에 있는 것은 text 하나뿐이라 뗄 자리는 여기밖에 없다.
#
# **끝에 붙은 것만 뗀다.** 한 문장이 아닐 때 가운데 물음표는 어르신이 남의 말을
# 옮기시는 자리라 (「그래서 내가 뭐냐고 물었지?」) 그대로 둔다.
_TRAILING_Q = re.compile(r"[?？]+\s*$")


def _heard(answer: str) -> str:
    return _TRAILING_Q.sub("", answer.rstrip()) or answer


def _transcript(ctl: "SessionController") -> str:
    """
    지금까지의 조각을 프롬프트에 넣을 형태로. 0번은 씨앗이라 질문이 없다.

    빈 answer 는 넣지 않는다. 씨앗을 비워 두고 회차를 열면 (프론트 기본값이
    비어 있다) 0번 조각의 answer 가 빈 문자열인데, 그대로 넣으면 프롬프트 맨
    위에 내용 없는 「어르신:」 한 줄이 얹힌다. 1번부터는 빈 전사가 턴을 소모하지
    않으므로 (controller._confirm) answer 가 비는 일이 없다.

    **최근 WINDOW 턴만 넣는다** (위 DEFAULT_WINDOW 참조). 씨앗은 회차의 주제라
    창 밖으로 밀려나도 맨 앞에 남긴다. 잘린 자리는 말없이 넘기지 않고 한 줄로
    알린다 — 모델이 「앞에 더 있었다」를 알아야 없는 맥락을 지어내지 않는다.
    """
    frs = ctl.fragments
    window = _window()
    head, rest = frs[:1], frs[1:]
    cut = len(rest) - window if window and len(rest) > window else 0

    out = []
    for f in head:
        if f["answer"]:
            out.append(f"어르신: {_heard(f['answer'])}")
    if cut:
        out.append(f"(앞의 {cut}턴은 줄였습니다)")
    for f in rest[cut:]:
        if f["question"]:
            out.append(f"질문: {f['question']}")
        if f["answer"]:
            out.append(f"어르신: {_heard(f['answer'])}")
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
        # 문서(§0 + §1)를 그대로 쓴다. 매 턴 바뀌는 공유 상태는 여기 넣지 않는다 —
        # system 이 고정이어야 프롬프트 캐시가 듣는다 (prompt.py 참조).
        system_instruction=promptlib.load().system + _ADDENDUM,
        response_mime_type="application/json",
        # 1.0 에서 내렸다. 규칙이 열 줄에서 마흔 줄로 늘어난 프롬프트에서 높은
        # 온도는 「다양한 질문」이 아니라 「규칙 이탈」로 나온다. 다양성은 온도가
        # 아니라 asked_questions · last_sense_used 가 만들게 한다 — 그쪽은 통제된다.
        temperature=0.7,
        # 400 에서 올렸다. 필드가 10개에서 12개로 늘었다 (공감·질문은 §1 이
        # 합쳐 60자로 묶는다). 모자라면 **뒤쪽 필드부터** 잘려 나가는데 지금
        # 뒤쪽이 end_reason·closing_hint 라 회차를 닫는 자리가 먼저 사라진다.
        # 잘린 JSON 은 파싱에서 통째로 실패하고, 그러면 고정 질문으로 물러선다.
        max_output_tokens=700,
        # 지연이 곧 품질인 구간이다. 생각을 오래 할수록 어르신이 기다린다.
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
        # 도구를 쓰지 않는다. 켜 두면 호출마다 AFC 로그가 한 줄씩 쌓여
        # 정작 봐야 할 지연 숫자가 묻힌다.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    # 공유 상태를 문서가 정한 자리에 얹고 그 아래 대화를 붙인다.
    contents = (f"{promptlib.load().render_state(shared_state.for_interview(ctl))}\n\n"
                f"[지금까지의 대화]\n{_transcript(ctl)}")

    try:
        res = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model, contents=contents, config=cfg),
            timeout=timeout)
        data = json.loads((res.text or "").strip())
    except asyncio.TimeoutError:
        log.warning("질문 생성 %.1fs 초과 — 고정 질문으로 물러선다 (회차는 계속)", timeout)
        return await _fallback(ctl)
    except Exception as e:                                   # noqa: BLE001
        log.error("질문 생성 실패(%s: %s) — 고정 질문으로 물러선다", type(e).__name__, e)
        return await _fallback(ctl)

    if not isinstance(data, dict):
        log.error("응답이 객체가 아니다(%s) — 고정 질문으로 물러선다", type(data).__name__)
        return await _fallback(ctl)

    status = str(data.get("topic_status") or "active").strip().lower()
    mode = str(data.get("conversation_mode") or "normal").strip().lower()

    # §1 이 새로 정한 두 필드. **아는 사유만 받는다** — 모델이 제 말로 지어낸
    # 사유를 그대로 session.closed_reason 에 적으면 나중에 회차 목록을 사유로
    # 셀 수 없다. 모르는 값은 버리고 아래에서 "finish" 로 떨어뜨린다.
    reason = str(data.get("end_reason") or "").strip().lower()
    if reason and reason not in shared_state.END_REASONS:
        log.warning("모르는 종료 사유(%r) — 버린다", reason)
        reason = ""
    hint = str(data.get("closing_hint") or "").strip()
    raw_q = str(data.get("question") or "").strip()
    q = _one_question(raw_q)
    if q != raw_q:
        log.info("질문을 한 문장으로 줄였다 — %r → %r", raw_q, q)
    raw_empathy = str(data.get("empathy") or "").strip()
    empathy = _one_sentence(raw_empathy)
    if empathy != raw_empathy:
        log.info("공감을 한 문장으로 줄였다 — %r → %r", raw_empathy, empathy)

    # **바닥을 하나 깐다.** 턴 상한을 없앤 뒤로 여기가 회차를 끝내는 유일한 문이
    # 됐는데, 실제로 돌려보니 어르신이 질문과 어긋난 말씀을 한 번 하신 것만으로
    # 모델이 마무리를 골랐다 (「어떻게 지금 돼가고 있어?」 → 턴 1 종료). 어르신이
    # 못 알아들으셨거나 되물으시는 건 흔한 일이고, 그때 할 일은 회차를 닫는 게
    # 아니라 다시 여쭙는 것이다.
    #
    # **단 sensitive 는 하한을 넘어선다.** 힘든 기억에서 그만하시겠다는 뜻인데
    # 턴이 모자라다고 또 여쭙는 것은 문서 §0 의 우선순위 1번(「힘든 기억에 대한
    # 중단 규칙」)을 정면으로 어기는 일이다. 하한은 모델의 성급함을 막는 장치지
    # 어르신의 뜻을 막는 장치가 아니다.
    overruled = (status == "closed" and mode != "sensitive"
                 and ctl.machine.turn < _min_turn())
    effective = "active" if overruled else status

    # **닫는 턴에만 값이 있다.** 진행 턴에 모델이 적어 와도 버린다 — 남겨 두면
    # 아직 말씀하시는 중인 화면에 마무리 안내가 뜬다. 되돌린 턴(overruled)도
    # 진행 턴이라 여기서 같이 지워진다.
    if effective != "closed":
        reason, hint = "", ""
    ctl.closing_hint = hint or None

    # **되돌린 결과를 상태에 적는다.** 여기에 closed 를 적어 두면 다음 턴에
    # 모델이 그것을 읽고 또 마무리를 고른다 — 하한이 한 턴만 버티고 무너진다.
    shared_state.merge(ctl.state, data, status=effective)

    # 지금은 로그로만 보이지만 store 가 turn.decision(JSONB) 으로 내린다.
    # 「왜 이 질문을 했나 · 왜 마무리했나」를 나중에 되짚을 수 있어야 한다 (FR-IV-006).
    ctl.last_decision = {
        "topic_status": effective,
        "conversation_mode": mode,
        "question_type": data.get("question_type"),
        "sense_used": data.get("sense_used"),
        "facts_found": data.get("facts_found") or [],
        "facts_retracted": data.get("facts_retracted") or [],
        "information_status": data.get("information_status") or {},
        "ready_for_chronology": bool(data.get("ready_for_chronology")),
        "end_reason": reason or None,
        "closing_hint": hint or None,
    }
    if overruled:
        ctl.last_decision["overruled"] = "closed"

    # **종료를 먼저 본다.** 문서 §1 은 종료 턴의 question 을 빈 문자열로 두라고
    # 정했다. 아래 「q 가 비었나」 검사를 먼저 하면 그 종료 턴이 고정 질문으로
    # 덮여 회차가 영영 안 끝난다 — 순서가 전부다.
    if overruled:
        log.info("마무리를 골랐지만 아직 %d턴이다 — 다시 여쭙는다 · %s",
                 ctl.machine.turn, shared_state.summary(ctl.state))
        return await _fallback(ctl)

    if effective == "closed":
        # FR-IV-006 — 판단으로 마무리. turn.decision 에 들어갈 값이다.
        # 사유는 controller._make_question 이 여기서 받아 closed_reason 에 적는다.
        log.info("마무리 — %s/%s · %s", mode, reason or "사유없음",
                 shared_state.summary(ctl.state))
        return None

    if not q:
        log.warning("종료가 아닌데 question 이 비었다 — 고정 질문으로 물러선다")
        return await _fallback(ctl)

    # 문서 §1 — 「공감 한 문장을 먼저 쓰고 질문 한 문장을 이어서 쓴다」.
    # 합쳐서 내보내는 것은 어르신 귀에 한 번의 말이기 때문이다. 화면도 낭독도
    # 이 한 줄을 쓴다.
    said = f"{empathy} {q}".strip() if empathy else q
    log.info("질문 준비 — %s [%s/%s·%d자] · %s",
             said, data.get("question_type"), data.get("sense_used"), len(said),
             shared_state.summary(ctl.state))
    return said


def _min_turn() -> int:
    try:
        return max(0, int(os.environ.get("MIN_TURN") or DEFAULT_MIN_TURN))
    except ValueError:
        return DEFAULT_MIN_TURN


def _window() -> int:
    """0 이면 자르지 않는다."""
    try:
        return max(0, int(os.environ.get("PROMPT_WINDOW") or DEFAULT_WINDOW))
    except ValueError:
        return DEFAULT_WINDOW


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
