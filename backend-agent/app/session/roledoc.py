"""
작성 담당 문서(엽서_v2.md · 자서전_v2.md)에서 실행할 절만 골라 시스템 지시로 잇는다.

쓰는 절은 김대원 님과 정했다 (P2-SV-01). 문서에 다른 절이 더 붙어 와도 이 절들만 싣는다
— 설계 설명이나 다른 역할 절을 모델이 지시로 읽지 않게.

    §2 공통 지침 · §5 작성 공통 · 역할 절     절 본문
    §7-4 분량 규칙 · §8-2 작성 출력           [제목] + 절 본문 (기본값 · 상태 우선순위)

본문의 울타리 줄(``` · ~~~)은 뺀다. 지침 블록(~~~)이 있는 절은 그 블록만 쓴다.
절이 하나라도 없거나 비었으면 ValueError 다. 반쪽 지시로 쓰지 않는다.
"""

from __future__ import annotations

import re

_HEAD = re.compile(r"^#{2,3} (\d+(?:-\d+)?)\.[^\n]*$", re.M)
_BLOCK = re.compile(r"^~~~[^\n]*\n(.*?)^~~~[ \t]*$", re.S | re.M)
_FENCE_LINE = re.compile(r"^(?:~~~|```)[^\n]*\n?", re.M)

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
    for n in (*COMMON, role, *RULES):
        head, body = sec[n]
        blocks = [b.strip() for b in _BLOCK.findall(body) if b.strip()]
        text = "\n\n".join(blocks) if blocks and n not in RULES else _FENCE_LINE.sub("", body).strip()
        if not text:
            raise ValueError(f"§{n} 이 비었다")
        parts.append(f"[{head}]\n{text}" if n in RULES else text)
    return "\n\n".join(parts)
