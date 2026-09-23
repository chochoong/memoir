"""
프롬프트 로더 — prompts/interview_v2.2.txt

**프롬프트를 .py 안에 복붙하지 않는다.** 그 파일이 살아 있는 스펙이고 팀에서
고친다. 여기에 한 벌 더 두면 두 벌이 갈라지고, 갈라진 것을 아무도 못 알아챈다.
파일을 읽어 쓰면 규칙이 바뀌었을 때 고칠 자리가 한 곳이다.

파일은 이렇게 생겼다. 「공통 지시어 + 해당 에이전트」를 합쳐 쓴다.

    ## 0. 공통 지시어        ``` … ```
    ## 1. 인터뷰 에이전트    ``` … ```

**§2~§4 는 여기 없다.** 사진 분석·연대기·카드 프롬프트는 아직
`docs/인터뷰 에이전트_프롬프트.md` 에 있고, photo_analyze.py 가 거기서 §0 + §2 를
직접 읽는다. 그래서 §0 이 지금 두 벌이다 — 한쪽만 고치면 인터뷰와 사진 분석이
서로 다른 공통 규칙으로 돈다. §0 을 고칠 때는 양쪽을 같이 본다.

**공유 상태는 system 에서 떼어 낸다.**

§0 의 끝에 `[현재 공유 상태]` / `{shared_state}` 두 줄이 붙어 있다. 그대로 이어
붙이면 **매 턴 바뀌는 값이 system_instruction 안에 들어간다.** system 은 회차
내내 같아야 프롬프트 캐시가 듣는다 — 바뀌는 자리가 앞에 있으면 뒤가 전부 다시
계산된다. 그래서 여기서 둘로 가른다.

    system       §0(상태 블록 제외) + §1      회차 내내 고정
    state_block  [현재 공유 상태] / {…}       턴마다 contents 에 얹는다

지켜야 하는 것 둘.

1. **encoding="utf-8" 을 반드시 적는다.** 이 PC 의 기본 인코딩은 CP949 라
   안 적으면 문서가 통째로 깨지거나 UnicodeDecodeError 로 죽는다.

2. **못 읽으면 그 자리에서 죽는다.** 조용히 빈 프롬프트로 도는 것이 제일 나쁘다 —
   어르신께 이상한 질문이 나가는데 화면에도 로그에도 아무 표시가 없다. 기동이
   실패하는 편이 낫다. 그래서 main.py 가 뜰 때 한 번 불러 확인한다.

읽기는 **기동 시 한 번**이다. 매 턴 파일을 열면 디스크 I/O 가 T2 예산에 들어간다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("prompt")

# app/session/prompt.py → backend-agent/
DOC = Path(__file__).resolve().parents[2] / "prompts" / "interview_v2.2.txt"

COMMON = "0"            # 공통 지시어
INTERVIEW = "1"         # 인터뷰 에이전트

_STATE_MARK = "[현재 공유 상태]"

_HEADING = re.compile(r"^##\s*(\d+)\.")
_FENCE = re.compile(r"^```(.*)$")

# 여는 울타리 뒤에 붙는 것이 언어 표시인지 본문인지 가른다. 울타리와 본문이
# 같은 줄에 붙어 있으면 (```당신은…) 그 한 줄이 통째로 날아간다.
_LANG = re.compile(r"^[A-Za-z0-9_+-]{0,12}$")


class PromptError(RuntimeError):
    """문서를 못 읽거나 모양이 다르다. 기동을 멈춰야 하는 종류의 오류다."""


@dataclass(frozen=True)
class Prompt:
    """한 에이전트가 쓸 프롬프트 한 벌."""

    system: str
    state_block: str

    def render_state(self, state: dict | None) -> str:
        """
        공유 상태를 문서가 정한 자리에 끼워 넣는다. contents 앞에 얹을 몫이다.

        `ensure_ascii=False` 여야 한다. 아니면 한글이 전부 \\uXXXX 로 부풀어
        입력 토큰이 서너 배가 되고, 그게 그대로 응답 지연이 된다.
        """
        body = json.dumps(state or {}, ensure_ascii=False, indent=2)
        return self.state_block.replace("{shared_state}", body)


def _blocks(text: str) -> dict[str, str]:
    """`## N.` 아래 첫 ``` 블록을 N 별로 모은다."""
    out: dict[str, str] = {}
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
            if section is not None and section not in out:
                out[section] = "\n".join(buf).strip()
            buf = None
            continue

        if section is None or section in out:
            continue                        # 한 절에서 첫 블록만 쓴다

        tail = fence.group(1).strip()
        # 언어 표시면 버리고, 본문이면 첫 줄로 살린다
        buf = [] if _LANG.match(tail) else [tail]

    return out


def _split_state(common: str) -> tuple[str, str]:
    """§0 을 「고정되는 앞부분」과 「턴마다 바뀌는 상태 블록」으로 가른다."""
    at = common.rfind(_STATE_MARK)
    if at < 0:
        raise PromptError(
            f"{DOC.name} §0 에 {_STATE_MARK} 가 없다 — 공유 상태를 끼울 자리가 없다")
    head, block = common[:at].rstrip(), common[at:].strip()
    if "{shared_state}" not in block:
        raise PromptError(f"{DOC.name} §0 의 {_STATE_MARK} 뒤에 {{shared_state}} 가 없다")
    return head, block


@lru_cache(maxsize=1)
def load() -> Prompt:
    """
    인터뷰 에이전트 프롬프트. 기동 시 한 번 읽고 그 뒤로는 캐시를 돌려준다.

    문서가 없거나 모양이 다르면 PromptError 로 죽는다 — 위 2번 참조.
    """
    try:
        text = DOC.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise PromptError(f"프롬프트 문서를 찾을 수 없다: {DOC}") from e
    except UnicodeDecodeError as e:
        raise PromptError(f"프롬프트 문서가 UTF-8 이 아니다: {DOC}") from e

    blocks = _blocks(text)
    missing = [n for n in (COMMON, INTERVIEW) if not blocks.get(n)]
    if missing:
        raise PromptError(
            f"{DOC.name} 에 §{' · §'.join(missing)} 의 ``` 블록이 없다 "
            f"(찾은 절: {sorted(blocks) or '없음'})")

    head, block = _split_state(blocks[COMMON])
    system = f"{head}\n\n{blocks[INTERVIEW]}"

    log.info("프롬프트 로드 — %s (지시 %d자 · 상태틀 %d자)",
             DOC.name, len(system), len(block))
    return Prompt(system=system, state_block=block)


def reload() -> Prompt:
    """문서를 고친 뒤 다시 읽는다. 개발 중에만 쓴다."""
    load.cache_clear()
    return load()
