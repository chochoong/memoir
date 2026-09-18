"""
사진 분석 검증 — §2 호출이 실패해도 조용히 None 으로 물러나는지 본다

    python -m tests.test_photo

test_question.py 와 같은 방식이다. 모델을 부르지 않는다 — `_client` 자리를
가짜로 바꾸고, 모델이 이렇게 답해 왔을 때(또는 아예 못 왔을 때) 코드가 어떻게
움직이는지만 본다.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app.session import photo as P                                        # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else '!! '}{name}{'  — ' + detail if detail else ''}")


_FULL_ANSWER = """{
  "scene": "마당, 초가집 앞",
  "objects": ["장독대", "빨랫줄"],
  "people": "성인 여성 1명, 아이 2명",
  "text_in_photo": [],
  "uncertain": ["오른쪽 인물의 옷차림"],
  "questions": ["이 마당은 어느 댁이었나요?"]
}"""


class _FakeClient:
    """모델 자리. 준 대로(또는 지연·예외를) 돌려준다."""

    def __init__(self, text=None, *, delay=0.0, raise_exc=None):
        self.aio = self
        self.models = self
        self._text = text
        self._delay = delay
        self._raise = raise_exc
        self.called = False

    async def generate_content(self, *, model, contents, config):
        self.called = True
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raise is not None:
            raise self._raise
        return type("R", (), {"text": self._text})()


def _run(fake, *, timeout=None):
    """가짜 클라이언트를 끼워 넣고 analyze_photo 를 한 번 돌린다."""
    orig_client = P._client
    orig_timeout = P.DEFAULT_TIMEOUT
    P._client = lambda: fake
    if timeout is not None:
        P.DEFAULT_TIMEOUT = timeout
    try:
        return asyncio.run(P.analyze_photo(b"fake-bytes", "image/jpeg"))
    finally:
        P._client = orig_client
        P.DEFAULT_TIMEOUT = orig_timeout


# --------------------------------------------------------------------- 성공

def test_success():
    print("\n[1] 정상 응답")
    fake = _FakeClient(_FULL_ANSWER)
    data = _run(fake)
    check("호출됐다", fake.called)
    check("dict 를 돌려준다", isinstance(data, dict), type(data).__name__)
    check("6개 키가 다 있다",
          data is not None and all(k in data for k in P._REQUIRED_KEYS))
    check("scene 값이 그대로 온다", data is not None and data.get("scene") == "마당, 초가집 앞")


def test_missing_keys():
    print("\n[2] 필수 키가 빠진 응답")
    fake = _FakeClient('{"scene": "마당"}')
    data = _run(fake)
    check("실패로 취급하지 않는다 — 값은 그대로 반환", data == {"scene": "마당"}, str(data))


# -------------------------------------------------------------------- 타임아웃

def test_timeout():
    print("\n[3] 타임아웃")
    fake = _FakeClient(_FULL_ANSWER, delay=0.2)
    data = _run(fake, timeout=0.05)
    check("None 을 돌려준다", data is None)
    check("호출은 갔다 — 응답만 늦었다", fake.called)


# ------------------------------------------------------------------ 잘못된 JSON

def test_bad_json():
    print("\n[4] 잘못된 JSON")
    fake = _FakeClient("이것은 JSON 이 아니다")
    data = _run(fake)
    check("JSON 이 아니다 → None", data is None)

    fake2 = _FakeClient('{"scene": "마당"')  # 잘린 JSON
    data2 = _run(fake2)
    check("잘린 JSON → None", data2 is None)

    fake3 = _FakeClient("[1, 2, 3]")  # 객체가 아니다
    data3 = _run(fake3)
    check("객체가 아니다 → None", data3 is None)


# ---------------------------------------------------------------------- 키 없음

def test_no_key():
    print("\n[5] GEMINI_API_KEY 없음")
    orig_client = P._client
    P._client = lambda: None
    try:
        data = asyncio.run(P.analyze_photo(b"fake-bytes"))
    finally:
        P._client = orig_client
    check("모델을 부르지 않고 None 을 돌려준다", data is None)


# -------------------------------------------------------------------- 프롬프트

def test_prompt():
    print("\n[6] 프롬프트 문서 로더")
    system = P._load_prompt()
    check("§0 과 §2 를 읽는다", len(system) > 200, f"{len(system)}자")
    check("상태 틀은 끼우지 않는다", "{shared_state}" not in system)
    check("§2 의 관찰 규칙이 실린다", "사진에서 실제로 보이는 것만 적습니다" in system)
    check("인터뷰 에이전트(§1) 규칙은 안 섞인다", "감각 질문 규칙" not in system)


def test_all_checks_passed():
    """check() 는 예외를 내지 않는다 — pytest 에서 실패가 보이도록 여기서 터뜨린다."""
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("사진 분석 — §2 호출 검증")
    test_success()
    test_missing_keys()
    test_timeout()
    test_bad_json()
    test_no_key()
    test_prompt()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
