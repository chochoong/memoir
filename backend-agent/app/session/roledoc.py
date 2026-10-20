"""
작성 담당 문서(엽서.md · 자서전.md v2.0)에서 실행할 절만 골라 시스템 지시로 잇는다.

문서 한 벌에 설계 설명(§0 · §1 표 · 팝업 문구)과 실행 지침이 함께 있다. 통째로
넣으면 모델이 다른 역할과 화면 이야기까지 지시로 읽는다. 쓰는 절은 김대원 님과
정했다 (P2-SV-01).

    §2 공통 지침 · §5 작성 공통 · 역할 절     ~~~ 지침 블록만
    §7-4 분량 설정 · §8-2 작성 출력           블록과 규칙 문단을 함께 (기본값 · 글자 수
                                              세는 법 · 상태 우선순위가 문단에 있다)

절이 하나라도 없거나 지침 블록이 비었으면 ValueError 다. 반쪽 지시로 쓰지 않는다.
"""

from __future__ import annotations

import re

_HEAD = re.compile(r"^#{2,3} (\d+(?:-\d+)?)\.[^\n]*$", re.M)
_BLOCK = re.compile(r"^~~~[^\n]*\n(.*?)^~~~[ \t]*$", re.S | re.M)
_FENCE_LINE = re.compile(r"^~~~[^\n]*\n?", re.M)

COMMON = ("2", "5")
RULES = ("7-4", "8-2")


def _sections(doc: str) -> dict[str, tuple[str, str]]:
    """절 번호 → (제목 줄, 본문). 본문은 다음 제목(## · ###) 앞까지다."""
    marks = list(_HEAD.finditer(doc))
    out: dict[str, tuple[str, str]] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(doc)
        out[m.group(1)] = (m.group(0).lstrip("#").strip(), doc[m.end():end])
    return out


def assemble(doc: str, role: str) -> str:
    """role 은 역할 절 번호다 — 엽서 "5-1", 자서전 "5-2"."""
    sec = _sections(doc)
    missing = [n for n in (*COMMON, role, *RULES) if n not in sec]
    if missing:
        raise ValueError(f"절이 없다: {', '.join('§' + n for n in missing)}")

    parts: list[str] = []
    for n in (*COMMON, role):
        blocks = [b.strip() for b in _BLOCK.findall(sec[n][1]) if b.strip()]
        if not blocks:
            raise ValueError(f"§{n} 에 지침 블록(~~~)이 없다")
        parts += blocks
    for n in RULES:
        head, body = sec[n]
        parts.append(f"[{head}]\n{_FENCE_LINE.sub('', body).strip()}")
    return "\n\n".join(parts)
