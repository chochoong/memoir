"""
질문 판단 · 공유 상태 · 프롬프트 로더 검증

    python -m tests.test_question

test_flow.py 가 상태 머신과 타이머를 본다면 여기는 **그 위에 얹힌 판단**을 본다.
모델을 부르지 않는다 — 부르는 자리(_client)를 가짜로 바꾸고, 모델이 이렇게
답해 왔을 때 코드가 어떻게 움직이는지만 본다. 회차를 끝내는 문이 여기 하나뿐이라
(question.py 머리말 3번) 잘못 닫히거나 안 닫히는 것이 제일 비싼 고장이다.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app.session import prompt as promptlib                              # noqa: E402
from app.session import question as Q                                    # noqa: E402
from app.session import shared                                           # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else '!! '}{name}{'  — ' + detail if detail else ''}")


# ------------------------------------------------------------------ 가짜 회차

class _Machine:
    def __init__(self, turn):
        self.turn = turn


class _Ctl:
    """gemini_question 이 실제로 만지는 것만 갖춘 최소한의 회차."""

    def __init__(self, turn=1, fragments=None):
        self.machine = _Machine(turn)
        self.fragments = fragments if fragments is not None else []
        self.state = shared.initial()
        self.last_decision = None


class _FakeClient:
    """모델 자리. 준 대로 돌려준다."""

    def __init__(self, payload):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.aio = self
        self.models = self
        self._text = text
        self.seen = {}

    async def generate_content(self, *, model, contents, config):
        self.seen = {"model": model, "contents": contents, "config": config}
        return type("R", (), {"text": self._text})()


def _ask(ctl, payload):
    """모델이 payload 로 답해 왔을 때의 결과. (반환값, 가짜 클라이언트)"""
    fake = _FakeClient(payload)
    orig = Q._client
    Q._client = lambda: fake
    try:
        return asyncio.run(Q.gemini_question(ctl)), fake
    finally:
        Q._client = orig


def _answer(**kw):
    """모델의 정상 응답 한 벌. 바꿀 것만 준다."""
    out = {
        "empathy": "그러셨군요.",
        "question": "그때 어떤 소리가 들렸나요?",
        "question_type": "회상확장",
        "sense_used": "청각",
        "facts_found": [],
        "information_status": {},
        "conversation_mode": "normal",
        "topic_status": "active",
        "completion_check_asked": False,
        "ready_for_chronology": False,
    }
    out.update(kw)
    return out


# ------------------------------------------------------------ 한 문장으로 줄이기

def test_trim():
    """
    모델이 두 문장을 적어 와도 어르신 귀에 가는 것은 한 문장씩이다.

    원인은 출력 필드 순서였고 그것을 고쳤지만 (question.py _ADDENDUM 참조)
    여기는 바닥으로 남겼다. 바닥이 정말 받치는지 본다.
    """
    print("\n[1] 공감·질문을 한 문장으로 줄인다")

    q = Q._one_question("눈이 참 많이 왔군요. 온통 하얗던 그때 풍경은 어땠나요?")
    check("질문은 뒤에서 가져온다", q == "온통 하얗던 그때 풍경은 어땠나요?", q)

    q2 = Q._one_question("그때 어떤 소리가 들렸나요?")
    check("한 문장이면 그대로 둔다", q2 == "그때 어떤 소리가 들렸나요?", q2)

    q3 = Q._one_question("")
    check("빈 질문은 빈 채로 나간다", q3 == "", repr(q3))

    q4 = Q._one_question("그러셨군요. 조금 더 들려주세요.")
    check("물음표가 없으면 마지막 문장", q4 == "조금 더 들려주세요.", q4)

    e = Q._one_sentence("눈이 참 많이 왔었군요. 눈이 참 많이 왔군요.")
    check("공감은 앞에서 가져온다", e == "눈이 참 많이 왔었군요.", e)

    e2 = Q._one_sentence("네… 뜨끈한 국밥이 좋으셨겠어요. 그 시절이 생각나네요.")
    check("추임새만 남기지 않는다", e2.startswith("네…") and "국밥" in e2, e2)


# ---------------------------------------------------------------- 대화 창 자르기

def test_window():
    """
    창이 없으면 턴 20 의 입력이 턴 1 의 스무 배가 되고 그게 그대로 지연이 된다.
    엽서는 회차의 주제라 창 밖으로 밀려나도 남는다.
    """
    print("\n[2] 대화는 최근 몇 턴만 싣는다")

    frs = [{"idx": 0, "question": None, "answer": "엽서 한 줄"}]
    for i in range(1, 11):
        frs.append({"idx": i, "question": f"질문{i}", "answer": f"대답{i}"})
    ctl = _Ctl(turn=10, fragments=frs)

    os.environ["PROMPT_WINDOW"] = "3"
    try:
        t = Q._transcript(ctl)
    finally:
        os.environ.pop("PROMPT_WINDOW", None)

    check("엽서는 남는다", "엽서 한 줄" in t)
    check("창 안의 턴은 실린다", "대답10" in t and "대답8" in t)
    check("창 밖의 턴은 빠진다", "대답7" not in t, t[:60])
    check("자른 것을 말없이 넘기지 않는다", "7턴은 줄였습니다" in t,
          "모델이 「앞에 더 있었다」를 알아야 없는 맥락을 안 지어낸다")

    os.environ["PROMPT_WINDOW"] = "0"
    try:
        full = Q._transcript(ctl)
    finally:
        os.environ.pop("PROMPT_WINDOW", None)
    check("0 이면 자르지 않는다", "대답1" in full and "줄였습니다" not in full)


# ------------------------------------------------------------------- 공유 상태

def test_merge():
    """
    한 번 확인된 것이 되돌아가면 종료 조건이 턴마다 참·거짓을 오간다.
    대화가 안 끝나는 쪽으로.
    """
    print("\n[3] 공유 상태는 얹기만 한다")

    st = shared.initial()
    shared.merge(st, _answer(information_status={"place": "confirmed"}))
    shared.merge(st, _answer(information_status={"place": "missing"}))
    check("확인된 것은 되돌아가지 않는다", st["information_status"]["place"] == "confirmed",
          st["information_status"]["place"])

    shared.merge(st, _answer(information_status={"when": "unknown_by_user"}))
    shared.merge(st, _answer(information_status={"when": "confirmed"}))
    check("모르신다던 것은 확인으로 올라갈 수 있다",
          st["information_status"]["when"] == "confirmed")

    st2 = shared.initial()
    shared.merge(st2, _answer(facts_found=["순애는 첫사랑", "서울로 감"]))
    shared.merge(st2, _answer(facts_found=["순애는 첫사랑", "계란을 나눠 먹음"]))
    check("같은 사실을 두 번 적지 않는다", len(st2["confirmed_facts"]) == 3,
          str(st2["confirmed_facts"]))
    check("말씀하신 차례를 지킨다", st2["confirmed_facts"][0] == "순애는 첫사랑",
          "§3 연대기가 이 순서를 본다")

    st3 = shared.initial()
    shared.merge(st3, _answer(facts_found="문자열 하나로 올 때도 있다"))
    check("배열이 아닌 것도 받는다", st3["confirmed_facts"] == ["문자열 하나로 올 때도 있다"],
          str(st3["confirmed_facts"]))

    st4 = shared.initial()
    shared.merge(st4, _answer(sense_used="후각"))
    shared.merge(st4, _answer(sense_used="없음", question_type="사실확인"))
    check("회상이 아닌 턴은 감각을 지우지 않는다", st4["last_sense_used"] == "후각",
          "지우면 바로 앞 회상의 감각을 잊어 같은 감각이 또 나간다")

    st5 = shared.initial()
    shared.merge(st5, _answer(completion_check_asked=True))
    shared.merge(st5, _answer(completion_check_asked=False))
    check("한 번 여쭌 것은 되돌리지 않는다", st5["completion_check_asked"] is True,
          "되돌리면 그 질문이 매 턴 반복된다")


def test_for_interview():
    print("\n[4] 모델에게 보낼 한 벌은 코드가 채운다")

    frs = [{"idx": 0, "question": None, "answer": "1968년 여름, 완행열차를 탔다."},
           {"idx": 1, "question": "그때 어떤 소리가 들렸나요?", "answer": "덜컹덜컹했지."}]
    ctl = _Ctl(turn=1, fragments=frs)
    out = shared.for_interview(ctl)

    check("엽서가 주제가 된다", out["current_topic"] == "1968년 여름, 완행열차를 탔다.",
          out["current_topic"])
    check("여쭌 질문을 fragments 에서 뽑는다",
          out["asked_questions"] == ["그때 어떤 소리가 들렸나요?"],
          "따로 쌓으면 두 벌이 되고, 어긋나면 같은 질문이 또 나간다")
    check("원본을 건드리지 않는다", ctl.state["current_topic"] == "",
          "ctl.state 에 쌓아 두면 fragments 와 두 벌이 된다")

    ctl.state["confirmed_facts"] = [f"사실{i}" for i in range(shared.FACTS_SENT + 5)]
    out2 = shared.for_interview(ctl)
    check("보내는 사실 수를 줄인다", len(out2["confirmed_facts"]) == shared.FACTS_SENT,
          str(len(out2["confirmed_facts"])))
    check("기록은 다 남긴다", len(ctl.state["confirmed_facts"]) == shared.FACTS_SENT + 5)


# --------------------------------------------------------------- 회차를 닫는 문

def test_close():
    """
    **회차를 끝내는 문은 여기 하나뿐이다.** 잘못 닫히면 어르신 말씀이 끊기고,
    안 닫히면 영영 안 끝난다. 둘 다 화면에는 「그냥 계속되는 것」으로 보인다.
    """
    print("\n[5] 마무리 판단")

    frs = [{"idx": 0, "question": None, "answer": "엽서"}]
    for i in range(1, 9):
        frs.append({"idx": i, "question": f"질문{i}", "answer": f"대답{i}"})

    # 종료 턴의 question 은 빈 문자열이다 (문서 §1). 빈 question 검사를 먼저 하면
    # 이 턴이 고정 질문으로 덮여 회차가 영영 안 끝난다 — 순서가 전부다.
    ctl = _Ctl(turn=8, fragments=frs)
    out, _ = _ask(ctl, _answer(topic_status="closed", question="", empathy="말씀 고맙습니다."))
    check("빈 question 인 종료 턴이 회차를 닫는다", out is None,
          "고정 질문이 나왔다면 빈 question 검사가 앞선 것이다")
    check("상태에도 closed 가 남는다", ctl.state["topic_status"] == "closed")

    # 하한 — 어르신이 한 번 되물으신 것만으로 닫히던 자리
    ctl2 = _Ctl(turn=2, fragments=frs[:3])
    out2, _ = _ask(ctl2, _answer(topic_status="closed", question=""))
    check("하한 전의 마무리는 따르지 않는다", isinstance(out2, str) and out2,
          repr(out2))
    check("되돌린 결과를 상태에 적는다", ctl2.state["topic_status"] == "active",
          "closed 를 적으면 다음 턴에 모델이 그걸 읽고 또 닫는다 — 하한이 한 턴만 버틴다")
    check("되돌린 것을 기록에 남긴다", (ctl2.last_decision or {}).get("overruled") == "closed",
          str(ctl2.last_decision))

    # 힘든 기억에서 그만하시겠다는 뜻은 하한보다 위다 (문서 §0 우선순위 1번)
    ctl3 = _Ctl(turn=1, fragments=frs[:2])
    out3, _ = _ask(ctl3, _answer(topic_status="closed", question="",
                                 conversation_mode="sensitive"))
    check("sensitive 는 하한을 넘어선다", out3 is None,
          "하한은 모델의 성급함을 막는 장치지 어르신의 뜻을 막는 장치가 아니다")

    # 정상 턴
    ctl4 = _Ctl(turn=3, fragments=frs[:4])
    out4, _ = _ask(ctl4, _answer(empathy="그러셨군요.", question="그때 어떤 소리가 들렸나요?"))
    check("공감과 질문을 한 줄로 합쳐 내보낸다",
          out4 == "그러셨군요. 그때 어떤 소리가 들렸나요?", repr(out4))

    # 닫는 턴이 아닌데 질문이 비면 고정 질문으로 물러선다
    ctl5 = _Ctl(turn=3, fragments=frs[:4])
    out5, _ = _ask(ctl5, _answer(question="", empathy=""))
    check("질문 없는 진행 턴은 고정 질문으로 받친다", isinstance(out5, str) and out5,
          repr(out5))


def test_broken_answer():
    """
    **실패한 턴에는 상태를 건드리지 않는다.** 아무것도 모르는 것이 잘못 아는 것보다 낫다.
    그리고 무슨 일이 있어도 None 을 돌려주지 않는다 — None 은 회차를 닫는 신호다.
    """
    print("\n[6] 망가진 응답")

    frs = [{"idx": 0, "question": None, "answer": "엽서"},
           {"idx": 1, "question": "질문1", "answer": "대답1"}]

    for label, payload in (("JSON 이 아니다", "그냥 문장입니다"),
                           ("객체가 아니다", "[1, 2, 3]"),
                           ("잘린 JSON", '{"question": "그때 어떤')):
        ctl = _Ctl(turn=3, fragments=frs)
        out, _ = _ask(ctl, payload)
        check(f"{label} → 고정 질문으로 돈다", isinstance(out, str) and out, repr(out))
        check(f"{label} → 상태를 건드리지 않는다",
              ctl.state == shared.initial(), "잘못 아는 것보다 모르는 것이 낫다")


# ------------------------------------------------------------------- 프롬프트

def test_prompt():
    """
    공유 상태가 system 안에 들어가면 매 턴 앞이 바뀌어 프롬프트 캐시가 죽는다.
    """
    print("\n[7] 프롬프트 문서 로더")

    p = promptlib.load()
    check("§0 과 §1 을 둘 다 읽는다", len(p.system) > 1000, f"{len(p.system)}자")
    check("상태는 system 에서 떼어 냈다", "{shared_state}" not in p.system,
          "system 이 고정이어야 캐시가 듣는다")
    check("상태 틀에 자리가 있다", "{shared_state}" in p.state_block, p.state_block[:40])

    body = p.render_state(shared.initial())
    check("상태를 끼워 넣는다", '"topic_status"' in body and "{shared_state}" not in body)
    check("한글을 \\uXXXX 로 부풀리지 않는다", "\\u" not in body,
          "부풀면 입력 토큰이 서너 배가 되고 그게 그대로 지연이 된다")

    # 실제로 보내는 모습 — 상태가 앞, 대화가 뒤
    ctl = _Ctl(turn=1, fragments=[{"idx": 0, "question": None, "answer": "엽서 한 줄"}])
    _, fake = _ask(ctl, _answer())
    sent = fake.seen["contents"]
    check("상태를 대화 앞에 얹어 보낸다",
          sent.index("[현재 공유 상태]") < sent.index("[지금까지의 대화]"), sent[:40])

    sysmsg = fake.seen["config"].system_instruction
    check("덧댄 규칙이 system 에 실린다", "facts_found" in sysmsg,
          "문서에 없는 필드는 여기서 덧댄다")
    check("출력 순서는 문서를 따른다 — 공감이 먼저",
          sysmsg.rindex('"empathy"') < sysmsg.rindex('"question_type"'),
          "질문이 앞서면 모델이 질문 칸 안에서 먼저 공감한다")
    check("문서가 정한 길이를 덮어쓰지 않는다", "40자" not in sysmsg,
          "문서 §1 은 60자다 — 두 벌이 살아 있으면 둘 다 안 지켜진다")


def test_all_checks_passed():
    """check() 는 예외를 내지 않는다 — pytest 에서 실패가 보이도록 여기서 터뜨린다."""
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 질문 판단 · 공유 상태 검증")
    test_trim()
    test_window()
    test_merge()
    test_for_interview()
    test_close()
    test_broken_answer()
    test_prompt()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
