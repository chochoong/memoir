"""
공유 상태(shared_state) — 문서 §0 이 「서비스 코드가 관리합니다」라고 한 그 코드

네 에이전트가 함께 보는 기록이다. 모델은 **읽기만** 하고, 쓰는 것은 여기다.
지금 붙은 것은 §1 인터뷰 에이전트 한 곳뿐이라 그쪽이 읽는 항목만 담는다.

**문서의 기본 구조를 통째로 넣지 않는다.** §0 에 스무 개 남짓이 적혀 있지만
같은 §0 이 「각 에이전트는 자신의 역할에 필요한 항목만 사용합니다」라고도 정했다.
입력 토큰이 곧 지연인 구간이라 (질문 생성 예산이 T2 안이다) 안 읽는 필드를 매 턴
실어 보내면 그만큼 어르신이 기다린다.

    담는다   current_topic · topic_status · conversation_mode
             last_sense_used · asked_questions          반복 금지 규칙의 근거
             confirmed_facts · to_confirm · blocking_to_confirm
             information_status · completion_check_asked
             ready_for_chronology

    뺀다     conversation_history   question._transcript() 과 같은 일이다. 둘 중 하나만
             photo_analyses 등      사진 기능이 붙기 전까지 늘 빈 배열이다
             chronology 등          §3 · §4 에이전트의 몫

**두 항목은 모델이 아니라 코드가 채운다.** 지금 있는 데이터로 공짜다.

    asked_questions   ctl.fragments 에서 뽑는다. 따로 쌓지 않는다 —
                      두 벌을 두면 어긋나고, 어긋나면 같은 질문이 또 나간다.
    current_topic     비어 있으면 엽서(0번 조각)로 채운다. 엽서가 회차의 주제다.

나머지(confirmed_facts · information_status …)는 인터뷰 에이전트가 자기 응답에
함께 담아 오고, 그것을 여기서 머지한다 — 5단계에서 붙는다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .controller import SessionController

log = logging.getLogger("shared")

# 문서 §0 「상태값」 참조. emotion 만 not_mentioned 를 더 쓴다 —
# 어르신이 감정을 말씀하지 않은 것은 정보가 빠진 것과 다르다.
INFO_KEYS = ("event", "when", "who", "place", "emotion")

NO_SENSE = "없음"
SENSES = ("시각", "청각", "후각", "미각", "촉각")
TOPIC_STATUS = ("active", "awaiting_choice", "closed")
MODES = ("normal", "sensitive")

# §1 「종료할 때, 종료하는 이유를 한줄로 설명하고 종료한다」의 사유 세 가지.
# 그대로 session.closed_reason 에 내려가 abort · expired · turn_cap 과 한 칸을
# 나눠 쓴다 — 「AI 가 판단해 마쳤다」를 셋으로 가르는 것이 이 값의 몫이다.
#
# **허용값 목록이 001_init.sql 주석에도 있지만 그쪽은 못 고친다.** 적용된
# 마이그레이션의 본문이 바뀌면 checksum 이 어긋나 기동이 막힌다 (migrate.py).
# 그래서 어휘의 주인은 여기다.
END_REASONS = ("user_request", "info_complete", "sensitive")

# 정보 상태의 **되돌아가지 않는 순서**. 머지할 때 낮은 쪽으로 못 내려간다.
#
#   0  아직 안 물어봤다
#   1  물어봤고 답이 정해졌다 — 문서 §1 이 「다시 묻지 않습니다」라고 한 것들
#   2  확인됐다
#
# 이게 없으면 모델이 한 턴 흔들릴 때마다 3턴에 확인된 장소가 missing 으로
# 되돌아가고, 종료 조건이 턴마다 참·거짓을 오간다. 대화가 안 끝나는 쪽으로.
_RANK = {
    "missing": 0, "not_mentioned": 0,
    "unknown_by_user": 1, "declined": 1, "not_applicable": 1,
    "confirmed": 2,
}

# 프롬프트에 실어 보낼 사실의 개수. 기록은 다 남기고 보내는 것만 줄인다 —
# 회차가 길어지면 이것도 입력 토큰이고, §3 연대기는 ctl.state 에서 전부 가져간다.
FACTS_SENT = 20


def initial() -> dict:
    """
    회차 하나의 시작 상태. 키 순서는 문서 §0 과 같게 둔다 —
    문서가 바뀌었을 때 눈으로 맞춰 보게 된다.
    """
    return {
        "current_topic": "",
        "topic_status": "active",
        "conversation_mode": "normal",
        "confirmed_facts": [],
        "to_confirm": [],
        "blocking_to_confirm": [],
        "last_sense_used": NO_SENSE,
        "completion_check_asked": False,
        "information_status": {
            "event": "missing",
            "when": "missing",
            "who": "missing",
            "place": "missing",
            "emotion": "not_mentioned",
        },
        "ready_for_chronology": False,
    }


def asked_questions(ctl: "SessionController") -> list[str]:
    """
    지금까지 여쭌 질문. 0번 조각은 엽서라 question 이 None 이다.

    이것이 문서의 「이미 물었거나 답변이 끝난 내용을 다시 묻지 않습니다」를
    실제로 돌게 하는 값이다. 모델에게 기억을 시키는 대신 사실을 준다.
    """
    return [f["question"] for f in ctl.fragments if f.get("question")]


def postcard(ctl: "SessionController") -> str:
    """엽서 = 0번 조각의 answer. 회차를 연 씨앗 문장이다."""
    if not ctl.fragments:
        return ""
    return (ctl.fragments[0].get("answer") or "").strip()


def for_interview(ctl: "SessionController") -> dict:
    """
    인터뷰 에이전트에게 보낼 한 벌. 매 턴 새로 만든다.

    **ctl.state 를 그대로 주지 않는다.** 코드가 채우는 두 항목을 여기서 얹어야
    하고, 그것을 ctl.state 에 쌓아 두면 fragments 와 두 벌이 되기 때문이다.
    """
    out = dict(ctl.state)
    out["asked_questions"] = asked_questions(ctl)
    if not out.get("current_topic"):
        out["current_topic"] = postcard(ctl)
    facts = out.get("confirmed_facts") or []
    if len(facts) > FACTS_SENT:
        out["confirmed_facts"] = facts[-FACTS_SENT:]
    return out


def _facts(value) -> list[str]:
    """모델이 배열 대신 문자열 하나를 줄 때가 있다. 양쪽 다 받는다."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [s.strip() for s in value if isinstance(s, str) and s.strip()]


def merge(state: dict, data: dict, *, status: str | None = None) -> dict:
    """
    인터뷰 에이전트의 응답을 공유 상태에 **얹는다.** 덮어쓰지 않는다.

    B안의 본체다. 모델이 질문과 함께 「이번 턴에 무엇이 확인됐는지」를 답해 오면
    그것을 여기서 누적한다. 문서 §1 의 종료 조건(「기본 정보가 모이면」)이 실제로
    참이 되는 자리이고, 이게 없으면 information_status 가 영원히 missing 이라
    대화가 안 끝난다.

    `status` 를 따로 받는 이유 — 모델이 closed 를 골랐어도 MIN_TURN 하한에 걸려
    되돌린 턴이 있다. 그때 상태에까지 closed 를 적으면 다음 턴에 모델이 그것을
    읽고 또 마무리를 고른다. **되돌린 결과를 적어야 한다** (question.py 참조).

    실패한 턴(타임아웃·파싱 오류)에는 **부르지 않는다.** 아무것도 모르는 것이
    잘못 아는 것보다 낫다.
    """
    st = (status or str(data.get("topic_status") or "")).strip().lower()
    if st in TOPIC_STATUS:
        state["topic_status"] = st

    mode = str(data.get("conversation_mode") or "").strip().lower()
    if mode in MODES:
        if mode != state.get("conversation_mode"):
            log.info("대화 결이 바뀐다 — %s → %s", state.get("conversation_mode"), mode)
        state["conversation_mode"] = mode

    # **한 번 확인된 것은 되돌아가지 않는다.** 위 _RANK 참조.
    info = data.get("information_status")
    if isinstance(info, dict):
        cur = state.setdefault("information_status", {})
        for k in INFO_KEYS:
            new = str(info.get(k) or "").strip()
            if new not in _RANK:
                continue
            if _RANK[new] >= _RANK.get(str(cur.get(k) or "missing"), 0):
                cur[k] = new

    # 새 사실만 덧붙인다. 순서는 말씀하신 차례 그대로 — §3 연대기가 이 순서를 본다.
    facts = state.setdefault("confirmed_facts", [])
    seen = set(facts)
    for f in _facts(data.get("facts_found")):
        if f not in seen:
            seen.add(f)
            facts.append(f)

    # **회상 질문에 쓴 감각만 기억한다.** 문서 §1 이 금지한 것은 「직전 *회상*
    # 질문에서 쓴 감각」의 반복이다. 이름·시간을 묻는 턴은 sense_used 가 "없음"
    # 으로 오는데, 그것까지 적으면 바로 앞 회상 질문의 감각을 잊어버려 다음
    # 턴에 같은 감각이 또 나간다.
    sense = str(data.get("sense_used") or "").strip()
    if sense in SENSES:
        state["last_sense_used"] = sense

    # 문서 §1 「더 남기고 싶은 이야기가 있는지 한 번만 여쭙습니다」. 한 번 참이
    # 되면 되돌리지 않는다 — 되돌리면 그 질문이 매 턴 반복된다.
    if data.get("completion_check_asked"):
        state["completion_check_asked"] = True

    if data.get("ready_for_chronology"):
        state["ready_for_chronology"] = True

    topic = str(data.get("current_topic") or "").strip()
    if topic:
        state["current_topic"] = topic

    return state


def summary(state: dict) -> str:
    """로그 한 줄로 줄인 모습. 상태가 도는지 눈으로 보는 자리다."""
    info = state.get("information_status") or {}
    got = [k for k in INFO_KEYS if info.get(k) == "confirmed"]
    return (f"{state.get('topic_status')}/{state.get('conversation_mode')}"
            f" · 사실 {len(state.get('confirmed_facts') or [])}"
            f" · 확인 {'+'.join(got) or '없음'}"
            f" · 감각 {state.get('last_sense_used')}")
