"""
자서전 5단계 독립 실행 파이프라인 — 단위 8P (서비스 경로와 따로 돈다)

    ① 분석      call  → 참조검사       사건 · 인물 · 주제 후보
    ② 목차      call  → 참조검사       장 1~5개 · 장마다 근거 턴
    ③ 장 집필   call × 장 수           장마다 그 장의 원문만
    ④ 편집      call  → 최종 근거검사  통합본
    ⑤ 검증      call                   문제 위치 · 근거 · 수정 방향

**역할마다 따로 부른다.** 다섯 역할을 한 지시에 넣어 한 번 부르지 않는다. 같은
모델이어도 된다. 성공하면 호출은 정확히 장 수 + 4 번이다.

**전역 턴은 merge 가 한 번 정한다.** 어느 단계도 다시 매기지 않는다. 모든 단계의
turns 는 그 번호이고, 코드가 매번 그 집합 안인지 본다. 분석 · 목차 · 편집 결과는
사실의 근거가 아니다 — 다음 단계에도 같은 원자료를 다시 준다.

**첫 실패에서 멈춘다.** 재시도는 없다. 장 하나가 실패하면 남은 장 · 편집 · 검증을
부르지 않고 partial 이다. 성공한 장은 실행 기록에만 남는다.

**고치지 않는다.** 모델이 낸 번호 · 키가 어긋나면 맞춰 주지 않고 실패다. 응답을
자르지 않는다 — 출력 상한에서 멈춘 응답은 JSON 이 맞아 보여도 truncated 다.

**모델 검증 pass 는 사람 검수가 아니다.** pipeline_complete 는 다섯 단계가 돌았다는
실행 사실이고, human_review 는 늘 not_run 이다.

저장하지 않는다. DB 를 부르지 않는다. 설정은 MEMOIR_PIPE_* 만 읽는다 — 서비스의
MEMOIR_* 와 섞지 않는다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import memoir
from .conf import env_float, env_int, env_str

PROMPTS = Path(__file__).resolve().parents[2] / "첨부프롬프트_md"
COMMON_DOC = PROMPTS / "자서전_v2.md"
ROLE_DIR = PROMPTS / "파이프라인"
# v1 — 첫 실측(fe94baf). v2 — 구성 · 제외(9231a70). v3 — 편집 메모 작업 종류 · 장 분할 원칙 ·
# 목차 메모 혼입 방지 · 원문에 없는 장면 금지(5ae6c1c · d3deb2b). v4 — 1인칭 회고 수필체(~다) ·
# 사건과 끈(thread) 분리 · 장 입력을 사건 묶음으로 · 코드 판정을 편집에 넘김 · code_gate/overall.
# 옛 판 파일은 실행 기록으로 남긴다. 계약은 판마다 달라 옛 판은 그 커밋에서만 돈다.
PROMPT_VERSION = "v4"
ROLE_FILES = {
    "analysis": "1_분석_v4.md",
    "outline": "2_목차_v4.md",
    "chapter": "3_장집필_v4.md",
    "edit": "4_편집_v4.md",
    "verify": "5_검증_v4.md",
}
STAGES = tuple(ROLE_FILES)

# 첫 실측용 값이다 (설계 Q2). 최적값도 서비스 설정도 아니다.
DEFAULT_LIMITS = {               # 초, 출력 토큰
    "analysis": (60.0, 5000),
    "outline": (60.0, 4000),
    "chapter": (90.0, 6000),     # 장마다
    "edit": (120.0, 8000),
    "verify": (90.0, 5000),
}
DEFAULT_TEMPERATURE = 0.3
DEFAULT_TOTAL_TIMEOUT = 600.0
MIN_CHAPTERS, MAX_CHAPTERS = 1, 5    # 독립 실험의 안전 상한. 넘으면 자르지 않고 실패
RETRIES = 0

# 상태 값
GENERATED, PARTIAL, FAILED = "generated", "partial", "failed"
INSUFFICIENT, NEEDS_CONTEXT = "insufficient_material", "needs_context"
KINDS = ("input", "call", "timeout", "truncated", "format", "reference",
         "context", "chapter_limit", "budget", "memo_leak")

# 편집 메모의 작업 종류 — before 는 장 초안의 위치, after 는 편집본의 위치다.
# 지운 문장은 편집본에 없는 것이 정상이라 before 로만 가리킨다 (v2 실측 실패의 원인).
#             before 개수   after 개수
EDIT_ACTIONS = {
    "rewrite": (1, None, 1, None),     # 고쳐 쓰기 · 나누기 (after 여럿)
    "delete":  (1, None, 0, 0),
    "merge":   (2, None, 1, 1),        # 문장 · 장 합치기
    "add":     (0, 0, 1, None),        # 새 사실 없는 연결 문장 등
}
# 독자에게 보일 문장에 섞이면 안 되는 안내문 말투 — 글 바깥에서 설명하는 문장
_META = re.compile(r"이\s?장(에서|은|는|에)|보여\s?(줍|드립)니다|보여\s?준다|이어집니다|마무리합니다"
                   r"|엮어\s?냅니다|다룹니다|다룬다|담았습니다")

# ---- 코드 판정 (v4) — 모델 판정과 따로 서는 규칙. severity: block 은 사용자 제공을 막고,
# fix 는 편집이 고칠 대상, info 는 사람 검수 참고.
# 인터뷰를 멈추거나 미루는 말 — 본문에 남으면 막는다 (같은 발언 속 사실은 써도 된다)
_STOP = re.compile(r"그만\s?할게요|그만\s?하자|오늘은\s?여기까지|다음에\s?(할게요|얘기)|나중에\s?할게요"
                   r"|넘어갈게요|말\s?안\s?할래요|얘기는\s?길어서|얘긴\s?(…|\.\.\.)")
# 질문에 대한 답의 흔적 — 문장 첫머리의 답 말
_ANSWER = re.compile(r"^\s*(아니요|아뇨|네[,.\s]|예[,.\s]|응[,.\s]|가끔요|글쎄요|그럼요|그렇죠|음\s?[…,.]|아[,.\s]\s*그거)")
# 직접 인용 — 원문 말투가 허용되는 부분. 문체 검사에서 뺀다
_QUOTE = re.compile(r"'[^']*'|\"[^\"]*\"|“[^”]*”|‘[^’]*’")

# 검증 issue 는 사실과 구성을 나눈다. code 는 자기 category 의 것만 쓴다.
FACT_CODES = ("unsupported_claim", "source_mismatch", "time_distortion",
              "identity_inference", "material_omission", "exclusion_violation",
              "editorial_misuse")
COMPOSITION_CODES = ("summary_listing", "over_split", "role_overlap", "weak_transition",
                     "theme_contradiction", "style_mismatch")
ISSUE_CODES = {"fact": FACT_CODES, "composition": COMPOSITION_CODES}
RESOLUTIONS = ("auto_fix", "ask_user", "provide_context", "accept_limit")
STRENGTHS = ("clear", "partial", "weak")
THREAD_KINDS = ("person", "object", "place", "theme")
CHECK_STATUSES = ("resolved", "kept")

_KEY = re.compile(r"^ch-\d{1,2}$")
_COMMON_HEAD = re.compile(r"^## 2\.[^\n]*\n(.*?)(?=^#{1,3} |\Z)", re.S | re.M)
_FENCE = re.compile(r"^(?:```|~~~)[^\n]*\n?", re.M)


class PipelineError(RuntimeError):
    """한 단계의 실패. kind 는 KINDS 중 하나 — 서로 다른 실패를 섞지 않는다."""

    def __init__(self, stage: str, kind: str, message: str, chapter_key: str | None = None):
        super().__init__(f"{stage}{'/' + chapter_key if chapter_key else ''} {kind} — {message}")
        self.stage, self.kind, self.message, self.chapter_key = stage, kind, message, chapter_key

    def as_dict(self) -> dict:
        return {"stage": self.stage, "chapter_key": self.chapter_key,
                "kind": self.kind, "message": self.message}


# ---------------------------------------------------------------- 설정


def settings() -> dict:
    """지금 적용되는 값. 실행 기록에 그대로 남긴다 — 비밀값은 없다."""
    s: dict[str, Any] = {
        "MEMOIR_PIPE_TEXT_MODEL": env_str("MEMOIR_PIPE_TEXT_MODEL", memoir.DEFAULT_TEXT_MODEL),
        "MEMOIR_PIPE_TEMPERATURE": env_float("MEMOIR_PIPE_TEMPERATURE", DEFAULT_TEMPERATURE),
        "MEMOIR_PIPE_TOTAL_TIMEOUT": env_float("MEMOIR_PIPE_TOTAL_TIMEOUT", DEFAULT_TOTAL_TIMEOUT),
    }
    for stage, (sec, tokens) in DEFAULT_LIMITS.items():
        up = stage.upper()
        s[f"MEMOIR_PIPE_{up}_TIMEOUT"] = env_float(f"MEMOIR_PIPE_{up}_TIMEOUT", sec)
        s[f"MEMOIR_PIPE_{up}_MAX_OUTPUT_TOKENS"] = env_int(f"MEMOIR_PIPE_{up}_MAX_OUTPUT_TOKENS", tokens)
    s["chapters"] = [MIN_CHAPTERS, MAX_CHAPTERS]
    s["retries"] = RETRIES
    s["prompt_version"] = PROMPT_VERSION
    return s


# ---------------------------------------------------------------- 지시문


def common_rules() -> str:
    """자서전_v2.md 의 「## 2. 공통 지침」 절 본문만. 다른 절은 장 구조와 부딪혀 싣지 않는다."""
    try:
        doc = COMMON_DOC.read_text(encoding="utf-8")
    except OSError as e:
        raise PipelineError("input", "input", f"공통 지침을 읽지 못했다: {COMMON_DOC.name} ({e})") from e
    m = _COMMON_HEAD.search(doc)
    body = _FENCE.sub("", m.group(1)).strip() if m else ""
    if not body:
        raise PipelineError("input", "input", f"{COMMON_DOC.name} 에 「## 2.」 절이 없거나 비었다")
    return body


def role_text(stage: str) -> str:
    path = ROLE_DIR / ROLE_FILES[stage]
    try:
        text = _FENCE.sub("", path.read_text(encoding="utf-8")).strip()
    except OSError as e:
        raise PipelineError(stage, "input", f"지시문을 읽지 못했다: {path.name} ({e})") from e
    if not text:
        raise PipelineError(stage, "input", f"{path.name} 이 비었다")
    return text


def prompt(stage: str) -> str:
    """시스템 지시 = 공통 지침 + 이 역할의 지시문 하나. 원문은 여기에 넣지 않는다."""
    return common_rules() + "\n\n" + role_text(stage)


def prompt_hashes() -> dict[str, str]:
    return {s: "sha256:" + hashlib.sha256(prompt(s).encode("utf-8")).hexdigest()[:16] for s in STAGES}


# ---------------------------------------------------------------- 입력


def input_ref(data: dict) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def build_input(records: list[dict]) -> tuple[dict, list[dict]]:
    """회차 기록 → (merge 출력, turn_map). 번호는 merge 가 정한 그대로 둔다."""
    try:
        return memoir.merge(records)
    except (memoir.MemoirError, KeyError, TypeError) as e:
        raise PipelineError("input", "input", f"합치지 못했다 ({type(e).__name__}: {e})") from e


def check_input(data, turn_map) -> set[int]:
    """merge 출력 모양. 턴은 1부터 빈틈없이, turn_map 과 하나씩 맞아야 한다. 돌려주는 것은 T."""
    def bad(why: str):
        return PipelineError("input", "input", why)

    if not isinstance(data, dict) or not isinstance(turn_map, list):
        raise bad("입력이 객체 · turn_map 이 목록이 아니다")
    utts, sessions, shared = data.get("utterances"), data.get("sessions"), data.get("shared_state")
    if not isinstance(utts, list) or not utts:
        raise bad("utterances 가 비었거나 목록이 아니다")
    if not isinstance(sessions, list) or not isinstance(shared, dict):
        raise bad("sessions · shared_state 모양이 다르다")
    sids = {s.get("session_id") for s in sessions if isinstance(s, dict)}
    turns = []
    for u in utts:
        if (not isinstance(u, dict) or not _is_int(u.get("turn"))
                or not isinstance(u.get("elder"), str) or not isinstance(u.get("asked"), str)
                or u.get("session_id") not in sids):
            raise bad("utterances 항목 모양이 다르다")
        turns.append(u["turn"])
    if turns != list(range(1, len(turns) + 1)):
        raise bad("utterances.turn 이 1부터 차례가 아니다")
    mapped = [m.get("global_turn") for m in turn_map if isinstance(m, dict)]
    if mapped != turns:
        raise bad("turn_map 이 utterances 와 맞지 않는다")
    return set(turns)


def excluded_turns(analysis: dict) -> set[int]:
    """
    턴째로 막을 범위 — mode=whole 로 빼 달라고 한 턴과, 그 요청을 말한 턴.

    **모델이 원문에서 읽어 낸 것이다 — 서비스의 제외 기능이 아니다.** 단위 8d 전까지
    seed 의 제외 요청은 말씀 속 글로만 들어온다. 원문을 고치거나 지우지 않는다.

    mode=partial 인 턴은 여기 없다. 한 말씀에 남길 내용과 뺄 내용이 섞이면 턴을
    통째로 지우지 않고 남긴 채 scope 로 알린다(exclusion_notices) — 그 부분을 실제로
    빼는 것은 모델이고, 다시 나왔는지는 검증 역할과 사람이 본다.
    """
    out: set[int] = set()
    for x in analysis.get("exclusions") or []:
        if x.get("mode") == "whole":
            out |= set(x.get("turns") or [])
        out |= set(x.get("requested_in") or [])
    return out


def exclusion_notices(analysis: dict, turns: set[int] | None = None) -> list[dict]:
    """
    뒤 단계에 줄 제외 알림 — 무엇을 빼야 하는지의 중립 설명(scope)과 턴만.
    turns 를 주면 그 턴에 걸린 것만 (장 하나에 줄 때).
    """
    out = []
    for x in analysis.get("exclusions") or []:
        ts = set(x.get("turns") or []) | set(x.get("requested_in") or [])
        if turns is None or ts & turns:
            out.append({"mode": x.get("mode"), "turns": x.get("turns") or [],
                        "requested_in": x.get("requested_in") or [], "scope": x.get("scope", "")})
    return out


def stage_source(data: dict, analysis: dict) -> dict:
    """
    목차 · 편집에 줄 원자료. 제외가 없으면 merge 출력 그대로다.

    제외가 있으면:
        utterances   턴째로 막을 턴(whole · 요청 턴)을 뺀다 — 남은 턴의 번호 · 글은 그대로
        facts_found  whole · partial · 요청 턴의 메모를 뺀다 (메모는 뺄 내용을 그대로 담는다)
        confirmed_facts  싣지 않는다 — 회차 전체 요약이라 어느 턴의 것인지 가를 수 없다

    분석은 제외를 찾아야 하니 전부 받고, 검증은 재등장을 찾아야 하니 전부 받는다.
    """
    notes = analysis.get("exclusions") or []
    if not notes:
        return data
    gone = excluded_turns(analysis)
    memo_gone = gone | {t for x in notes for t in (x.get("turns") or [])}
    return {
        "shared_state": {"facts_found": [x for x in data["shared_state"].get("facts_found", [])
                                         if x.get("turn") not in memo_gone]},
        "sessions": data["sessions"],
        "utterances": [u for u in data["utterances"] if u["turn"] not in gone],
    }


def chapter_owned_turns(analysis: dict, chapter: dict) -> set[int]:
    """장이 근거로 쓰기로 한 턴 — focus_turns ∪ 그 장 사건의 turns (context 는 빼고)."""
    events = {e["event_key"]: e for e in analysis.get("events", [])}
    owned = set(chapter.get("focus_turns") or [])
    for k in chapter.get("events") or []:
        owned |= set(events[k]["turns"]) if k in events else set()
    return owned


def event_packets(analysis: dict, chapter: dict, given: list[int] | set[int]) -> list[dict]:
    """이 장의 사건을 목차가 놓은 순서대로, 사건마다 받은 턴. 사건 요약은 싣지 않는다(근거가 아니다)."""
    events = {e["event_key"]: e for e in analysis.get("events", [])}
    given = set(given)
    return [{"event_key": k, "turns": sorted(set(events[k]["turns"]) & given)}
            for k in chapter.get("events") or [] if k in events and set(events[k]["turns"]) & given]


def chapter_source(data: dict, analysis: dict, chapter: dict,
                   outline_out: dict | None = None) -> tuple[dict, list[int]]:
    """
    장 하나에 줄 원자료 (설계 Q4). 전체 원문을 장마다 주지 않는다.

        이 장의 focus_turns ∪ 이 장 사건의 turns ∪ 목차가 고른 context_turns
        ∪ 그 턴들의 같은 회차 앞뒤 1턴 — 단, **다른 장이 근거로 쓰기로 한 턴은 앞뒤 1턴으로
          끌어오지 않는다** (v3 실측: 4장 모두 경계에서 옆 장 턴을 받아 같은 내용을 두 번 썼다).
          일부러 쓰려면 목차가 context_turns 에 적는다
        − 턴째로 막을 제외 범위 (앞뒤 1턴으로도 끌려 들어오지 않게)
        partial 제외 턴은 남기고, 메시지에 제외 알림을 함께 준다

    항목은 merge 출력 그대로 고른다 — 번호도 글도 바꾸지 않는다. **순서는 인터뷰 순서가
    아니라 사건 묶음 순서**다(목차가 놓은 사건 순서 → 그 밖의 턴은 번호순).
    """
    events = {e["event_key"]: e for e in analysis.get("events", [])}
    core = set(chapter["focus_turns"]) | set(chapter.get("context_turns") or [])
    for k in chapter["events"]:
        core |= set(events[k]["turns"])
    others: set[int] = set()
    for ch in (outline_out or {}).get("chapters", []):
        if ch.get("chapter_key") != chapter.get("chapter_key"):
            others |= chapter_owned_turns(analysis, ch)
    session_of = {u["turn"]: u["session_id"] for u in data["utterances"]}
    gone = excluded_turns(analysis)
    given = set(core)
    for t in core:
        for n in (t - 1, t + 1):
            if n in session_of and session_of[n] == session_of[t] and n not in others:
                given.add(n)
    given -= gone
    keep = sorted(given)
    rank: dict[int, tuple[int, int]] = {}
    for i, pk in enumerate(event_packets(analysis, chapter, given)):
        for t in pk["turns"]:
            rank.setdefault(t, (i, t))
    big = len(chapter.get("events") or []) + 1
    picked = sorted((u for u in data["utterances"] if u["turn"] in given),
                    key=lambda u: rank.get(u["turn"], (big, u["turn"])))
    used_sessions = {u["session_id"] for u in picked}
    # partial 턴의 메모는 뺄 내용을 그대로 담을 수 있어 싣지 않는다 (원문 턴은 남긴다)
    partial = {t for x in analysis.get("exclusions") or [] if x.get("mode") == "partial"
               for t in (x.get("turns") or [])}
    src = {
        "shared_state": {"facts_found": [x for x in data["shared_state"].get("facts_found", [])
                                         if x.get("turn") in given and x.get("turn") not in partial]},
        "sessions": [s for s in data["sessions"] if s["session_id"] in used_sessions],
        "utterances": picked,
    }
    return src, keep


# ---------------------------------------------------------------- 작은 검사 함수


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _int_list(v) -> list[int] | None:
    """정수 목록이면 그대로, 아니면 None. True/False 는 정수로 치지 않는다."""
    if not isinstance(v, list) or not all(_is_int(t) for t in v):
        return None
    return v


def _str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


_YEAR = re.compile(r"(?<!\d)(?:19|20)?(\d{2})(?:년|(?=\D|$))")


def _years(text: str) -> set[str]:
    """시점 글에 나온 연도(끝 두 자리). "77년쯤, 2003년" → {"77", "03"}. 나이("열 살")는 세지 않는다."""
    return {m.group(1) for m in _YEAR.finditer(text or "") if re.search(r"\d{2,4}", m.group(0))
            and (len(m.group(0).rstrip("년")) in (2, 4))}


class _Check:
    """한 단계의 검사. 실패는 PipelineError, 경고는 모아 둔다."""

    def __init__(self, stage: str, chapter_key: str | None = None):
        self.stage, self.chapter_key = stage, chapter_key
        self.warnings: list[str] = []

    def fail(self, kind: str, why: str) -> PipelineError:
        return PipelineError(self.stage, kind, why, self.chapter_key)

    def obj(self, out, keys: tuple[str, ...]) -> dict:
        if not isinstance(out, dict):
            raise self.fail("format", "객체가 아니다")
        missing = [k for k in keys if k not in out]
        if missing:
            raise self.fail("format", f"키가 없다 {missing}")
        extra = sorted(set(out) - set(keys))
        if extra:
            self.warnings.append(f"계약에 없는 키 {extra}")
        return out

    def turns(self, v, allowed: set[int], where: str, *, nonempty: bool = False,
              outside: str = "입력에 없는 턴") -> list[int]:
        ts = _int_list(v)
        if ts is None:
            raise self.fail("format", f"{where}.turns 가 정수 목록이 아니다")
        if nonempty and not ts:
            raise self.fail("reference", f"{where}.turns 가 비었다")
        bad = [t for t in ts if t not in allowed]
        if bad:
            raise self.fail("reference", f"{where}.turns {bad} — {outside}")
        return ts

    def text(self, v, where: str, *, nonempty: bool = True) -> str:
        if not isinstance(v, str) or (nonempty and not v.strip()):
            raise self.fail("format", f"{where} 가 비었거나 문자열이 아니다")
        return v

    def sentence(self, s, allowed: set[int], where: str, outside: str = "입력에 없는 턴") -> dict:
        """문장 항목 · 제목. supported 는 근거 턴이 있어야 하고, editorial 은 비어도 된다."""
        if not isinstance(s, dict):
            raise self.fail("format", f"{where} 가 객체가 아니다")
        self.text(s.get("text"), f"{where}.text")
        kind = s.get("kind")
        if kind not in ("supported", "editorial"):
            raise self.fail("format", f"{where}.kind={kind!r}")
        self.turns(s.get("turns"), allowed, where, nonempty=(kind == "supported"), outside=outside)
        return s

    def notes(self, v, allowed: set[int], where: str, outside: str = "입력에 없는 턴") -> None:
        if not isinstance(v, list):
            raise self.fail("format", f"{where} 가 목록이 아니다")
        for i, n in enumerate(v):
            if not isinstance(n, dict):
                raise self.fail("format", f"{where}[{i}] 가 객체가 아니다")
            self.text(n.get("issue"), f"{where}[{i}].issue")
            self.turns(n.get("turns"), allowed, f"{where}[{i}]", outside=outside)

    def paragraphs(self, v, allowed: set[int], where: str, outside: str = "입력에 없는 턴") -> list:
        if not isinstance(v, list) or not v:
            raise self.fail("format", f"{where}.paragraphs 가 비었거나 목록이 아니다")
        for p, para in enumerate(v):
            if not isinstance(para, list) or not para:
                raise self.fail("format", f"{where}/p{p} 가 비었거나 목록이 아니다")
            for s, sent in enumerate(para):
                self.sentence(sent, allowed, f"{where}/p{p}/s{s}", outside)
        return v


# ---------------------------------------------------------------- 단계별 검사


def check_analysis(out, T: set[int]) -> tuple[str, list[str]]:
    c = _Check("analysis")
    out = c.obj(out, ("status", "events", "threads", "people", "themes", "direction", "exclusions",
                      "not_in_events", "unclear", "missing_context"))
    status = out["status"]
    if status not in ("ready", INSUFFICIENT, NEEDS_CONTEXT):
        raise c.fail("format", f"status={status!r}")
    for k in ("events", "threads", "people", "themes", "exclusions", "not_in_events", "unclear"):
        if not isinstance(out[k], list):
            raise c.fail("format", f"{k} 가 목록이 아니다")
    if not _str_list(out["missing_context"]):
        raise c.fail("format", "missing_context 가 문자열 목록이 아니다")
    if status != "ready":
        return status, c.warnings
    if not out["events"]:
        raise c.fail("format", "ready 인데 events 가 비었다")

    # 제외 범위 — whole 은 턴째로 막고, partial 은 턴을 남긴 채 scope 로 알린다
    gone: set[int] = set()
    for i, x in enumerate(out["exclusions"]):
        at = f"exclusions[{i}]"
        if not isinstance(x, dict) or not isinstance(x.get("scope", ""), str):
            raise c.fail("format", f"{at} 모양이 다르다")
        mode = x.get("mode")
        if mode not in ("whole", "partial"):
            raise c.fail("format", f"{at}.mode={mode!r} — whole · partial")
        ts = c.turns(x.get("turns"), T, f"{at}.turns", nonempty=(mode == "partial"))
        if mode == "partial" and not x["scope"].strip():
            raise c.fail("format", f"{at} 는 partial 인데 scope 가 비었다 — 무엇을 빼는지 알 수 없다")
        if mode == "whole":
            gone |= set(ts)
        gone |= set(c.turns(x.get("requested_in"), T, f"{at}.requested_in", nonempty=True))
    partial = {t for x in out["exclusions"] if x["mode"] == "partial" for t in x["turns"]}
    if partial & gone:
        raise c.fail("reference", f"턴 {sorted(partial & gone)} 이 partial 과 whole · 요청 턴에 함께 있다")
    left: set[int] = set()
    for i, x in enumerate(out["not_in_events"]):
        if not isinstance(x, dict):
            raise c.fail("format", f"not_in_events[{i}] 가 객체가 아니다")
        left |= set(c.turns(x.get("turns"), T, f"not_in_events[{i}]"))
        c.text(x.get("reason"), f"not_in_events[{i}].reason")

    keys: list[str] = []
    covered: set[int] = set()
    for i, e in enumerate(out["events"]):
        at = f"events[{i}]"
        if not isinstance(e, dict):
            raise c.fail("format", f"{at} 가 객체가 아니다")
        key = c.text(e.get("event_key"), f"{at}.event_key")
        if key in keys:
            raise c.fail("reference", f"event_key {key!r} 가 겹친다")
        keys.append(key)
        c.text(e.get("summary"), f"{at}.summary")
        ts = c.turns(e.get("turns"), T, at, nonempty=True,
                     outside="입력에 없는 턴")
        bad = sorted(set(ts) & gone)
        if bad:
            raise c.fail("reference", f"{at}.turns {bad} — 빼 달라고 한 턴을 사건 근거로 씀")
        covered |= set(ts)
        years = _years((e.get("time") or {}).get("text", ""))
        if len(years) > 1:
            c.warnings.append(f"사건 {key} 의 시점이 여럿 {sorted(years)} — 별개 사건을 합쳤는지 본다")
        if not _str_list(e.get("people", [])):
            raise c.fail("format", f"{at}.people 가 문자열 목록이 아니다")
        tm = e.get("time")
        if (not isinstance(tm, dict) or not isinstance(tm.get("text"), str)
                or tm.get("certainty") not in ("stated", "approx", "unknown")):
            raise c.fail("format", f"{at}.time 모양이 다르다")
        for j, f in enumerate(e.get("said_feelings") or []):
            if not isinstance(f, dict):
                raise c.fail("format", f"{at}.said_feelings[{j}] 가 객체가 아니다")
            c.text(f.get("text"), f"{at}.said_feelings[{j}].text")
            c.turns(f.get("turns"), T, f"{at}.said_feelings[{j}]", nonempty=True)
    for i, p in enumerate(out["people"]):
        if not isinstance(p, dict):
            raise c.fail("format", f"people[{i}] 가 객체가 아니다")
        c.text(p.get("name"), f"people[{i}].name")
        c.turns(p.get("turns"), T, f"people[{i}]")
    for i, t in enumerate(out["themes"]):
        if not isinstance(t, dict):
            raise c.fail("format", f"themes[{i}] 가 객체가 아니다")
        c.text(t.get("theme"), f"themes[{i}].theme")
        c.turns(t.get("supporting"), T, f"themes[{i}].supporting", nonempty=True)
        c.turns(t.get("counter"), T, f"themes[{i}].counter")
        if t.get("strength") not in STRENGTHS:
            raise c.fail("format", f"themes[{i}].strength={t.get('strength')!r}")
    d = out["direction"]
    if not isinstance(d, dict) or not isinstance(d.get("theme"), str) or not isinstance(d.get("neutral"), bool):
        raise c.fail("format", "direction 모양이 다르다")
    # 주제 판단의 앞뒤가 맞는지 — 실패로 막지 않고 기록한다 (검증 역할이 본다)
    clear = [t["theme"] for t in out["themes"] if t["strength"] == "clear"]
    if d["neutral"] and d["theme"].strip():
        c.warnings.append("direction.neutral=true 인데 theme 을 정했다")
    if not d["neutral"] and not clear:
        c.warnings.append("clear 인 주제가 없는데 direction.neutral=false")
    c.notes(out["unclear"], T, "unclear")

    # 끈(thread) — 여러 사건을 잇는 사람 · 물건 · 장소 · 주제. 사건을 합치지 않고 여기서 잇는다
    thread_keys: list[str] = []
    for i, th in enumerate(out["threads"]):
        at = f"threads[{i}]"
        if not isinstance(th, dict):
            raise c.fail("format", f"{at} 가 객체가 아니다")
        tk = c.text(th.get("thread_key"), f"{at}.thread_key")
        if tk in thread_keys:
            raise c.fail("reference", f"thread_key {tk!r} 가 겹친다")
        thread_keys.append(tk)
        c.text(th.get("name"), f"{at}.name")
        if th.get("kind") not in THREAD_KINDS:
            raise c.fail("format", f"{at}.kind={th.get('kind')!r}")
        evs = th.get("events")
        if not _str_list(evs):
            raise c.fail("format", f"{at}.events 가 문자열 목록이 아니다")
        unknown = [e for e in evs if e not in keys]
        if unknown:
            raise c.fail("reference", f"{at}.events {unknown} — 분석에 없는 사건")
        c.turns(th.get("turns"), T - gone, at, nonempty=True, outside="입력에 없거나 빼 달라고 한 턴")

    # 빠짐없이 — 모든 발언 턴은 사건 · not_in_events · 제외 중 한 곳에 있어야 한다.
    # partial 턴은 남길 내용이 있으니 사건이나 not_in_events 에 따로 놓여야 한다
    missing = sorted(T - covered - left - gone)
    if missing:
        raise c.fail("reference", f"턴 {missing} 이 사건 · not_in_events · exclusions 어디에도 없다")
    return status, c.warnings


def check_outline(out, analysis: dict, T: set[int]) -> tuple[str, list[str]]:
    c = _Check("outline")
    out = c.obj(out, ("status", "book", "chapters", "left_out", "missing_context"))
    status = out["status"]
    if status not in ("ready", NEEDS_CONTEXT):
        raise c.fail("format", f"status={status!r}")
    if not _str_list(out["missing_context"]):
        raise c.fail("format", "missing_context 가 문자열 목록이 아니다")
    if status != "ready":
        return status, c.warnings

    book = out["book"]
    if not isinstance(book, dict):
        raise c.fail("format", "book 이 객체가 아니다")
    c.sentence(book.get("title"), T, "book.title")
    c.text(book.get("structure_reason"), "book.structure_reason")
    gone = excluded_turns(analysis)
    # 책을 어디서 열고 닫는가 — 마지막 중요 발언이 시간순 마지막 장 끝에 묻히지 않게
    c.turns(book.get("opening_turns", []), T - gone, "book.opening", outside="입력에 없거나 빼 달라고 한 턴")
    c.turns(book.get("closing_turns"), T - gone, "book.closing", nonempty=True,
            outside="입력에 없거나 빼 달라고 한 턴")
    if not isinstance(book.get("theme_use", ""), str):
        raise c.fail("format", "book.theme_use 가 문자열이 아니다")
    thread_keys = {th["thread_key"] for th in analysis.get("threads", [])}
    direction = analysis.get("direction") or {}
    if not direction.get("neutral", True) and not book.get("theme_use", "").strip():
        c.warnings.append("분석은 뚜렷한 주제를 냈는데 목차가 그 주제를 어떻게 쓰는지(theme_use) 비었다")
    chapters = out["chapters"]
    if not isinstance(chapters, list) or not chapters:
        raise c.fail("format", "chapters 가 비었다 — 0장")
    if len(chapters) > MAX_CHAPTERS:
        raise c.fail("chapter_limit", f"{len(chapters)}장 — 상한 {MAX_CHAPTERS}장 (자르지 않는다)")

    event_keys = {e["event_key"] for e in analysis["events"]}
    placed: set[str] = set()
    keys: list[str] = []
    for i, ch in enumerate(chapters):
        at = f"chapters[{i}]"
        if not isinstance(ch, dict):
            raise c.fail("format", f"{at} 가 객체가 아니다")
        key = ch.get("chapter_key")
        if not isinstance(key, str) or not _KEY.match(key):
            raise c.fail("format", f"{at}.chapter_key={key!r} — ch-<숫자> 여야 한다")
        if key in keys:
            raise c.fail("reference", f"chapter_key {key} 가 겹친다")
        keys.append(key)
        c.sentence(ch.get("title"), T, f"{key}.title")
        c.text(ch.get("role"), f"{key}.role")
        c.text(ch.get("purpose"), f"{key}.purpose")
        c.text(ch.get("grouping_reason"), f"{key}.grouping_reason")
        ths = ch.get("threads", [])
        if not _str_list(ths):
            raise c.fail("format", f"{key}.threads 가 문자열 목록이 아니다")
        unknown = [t for t in ths if t not in thread_keys]
        if unknown:
            raise c.fail("reference", f"{key}.threads {unknown} — 분석에 없는 끈")
        evs = ch.get("events")
        if not _str_list(evs):
            raise c.fail("format", f"{key}.events 가 문자열 목록이 아니다")
        unknown = [e for e in evs if e not in event_keys]
        if unknown:
            raise c.fail("reference", f"{key}.events {unknown} — 분석에 없는 사건")
        placed |= set(evs)
        used = c.turns(ch.get("focus_turns"), T, f"{key}.focus", nonempty=True)
        used = used + c.turns(ch.get("context_turns", []), T, f"{key}.context")
        bad = sorted(set(used) & gone)
        if bad:
            raise c.fail("reference", f"{key} 이 빼 달라고 한 턴 {bad} 을 쓴다")
        if ch.get("weight") not in ("main", "minor"):
            raise c.fail("format", f"{key}.weight={ch.get('weight')!r}")
        for k in ("transition_in", "transition_out"):
            if not isinstance(ch.get(k, ""), str):
                raise c.fail("format", f"{key}.{k} 가 문자열이 아니다")

    # 모든 사건은 어느 장에 놓이거나, 뺀 이유와 함께 left_out 에 있어야 한다
    if not isinstance(out["left_out"], list):
        raise c.fail("format", "left_out 이 목록이 아니다")
    dropped: set[str] = set()
    for i, x in enumerate(out["left_out"]):
        if not isinstance(x, dict) or x.get("event_key") not in event_keys:
            raise c.fail("reference", f"left_out[{i}] — 분석에 없는 사건")
        c.text(x.get("reason"), f"left_out[{i}].reason")
        dropped.add(x["event_key"])
    if placed & dropped:
        raise c.fail("reference", f"사건 {sorted(placed & dropped)} 이 장에도 left_out 에도 있다")
    lost = sorted(event_keys - placed - dropped)
    if lost:
        raise c.fail("reference", f"사건 {lost} 이 어느 장에도 · left_out 에도 없다")
    if len(chapters) > 1 and len(chapters) == len(event_keys) and all(
            len(ch["events"]) == 1 for ch in chapters):
        c.warnings.append("사건 하나마다 장 하나 — 분할 이유를 확인한다")
    for ch in chapters:                          # 끈 없이 사건을 많이 모은 장 — "나머지 모음" 일 수 있다
        if len(ch["events"]) >= 4 and not ch.get("threads"):
            c.warnings.append(f"{ch['chapter_key']} 가 끈 없이 사건 {len(ch['events'])}개를 모았다 — 모음 장인지 본다")
    if thread_keys and not any(ch.get("threads") for ch in chapters):
        c.warnings.append("분석의 끈(threads)을 어느 장도 쓰지 않았다")
    return status, c.warnings


def check_chapter(out, chapter: dict, given: list[int], core: set[int],
                  memos: list[str] | None = None) -> list[str]:
    key = chapter["chapter_key"]
    c = _Check("chapter", key)
    out = c.obj(out, ("chapter_key", "title", "paragraphs", "review_notes"))
    if out["chapter_key"] != key:
        raise c.fail("reference", f"chapter_key={out['chapter_key']!r} — 부른 장은 {key}")
    allowed = set(given)
    outside = "이 장에 주지 않은 원문"
    c.sentence(out["title"], allowed, f"{key}/title", outside)
    c.paragraphs(out["paragraphs"], allowed, key, outside)
    c.notes(out["review_notes"], allowed, f"{key}/review_notes", outside)
    only_context = sorted({t for para in out["paragraphs"] for s in para
                           if s["kind"] == "supported" for t in s["turns"]} - core)
    if only_context:
        c.warnings.append(f"문맥으로만 준 턴을 근거로 씀 {only_context}")
    # 장 초안에서는 경고만 — 편집이 지울 수 있다. 편집본에 남으면 final_check 에서 실패
    leaks = memo_leaks([out], memos or [])
    if leaks:
        c.warnings.append(f"목차 메모를 그대로 옮긴 문장 {leaks}")
    meta = meta_sentences([out])
    if meta:
        c.warnings.append(f"안내문 말투 문장 {meta}")
    return c.warnings


# ---------------------------------------------------------------- 글 지표 (비교용, 판정 아님)

_NORM = re.compile(r"[\s\W_]+")


def _norm(s: str) -> str:
    return _NORM.sub("", s)


def text_metrics(chapters: list[dict], data: dict) -> dict:
    """
    결과 글의 모양을 숫자로. **품질 판정이 아니라 실행끼리 견주는 기준**이다.

        verbatim_ratio  문장 중 원문 한 턴 안에 글자 그대로 들어 있는 것의 비율
                        (공백 · 문장부호는 빼고 견준다). 높을수록 원문을 옮겨 적은 것
    """
    utts = [_norm(u["elder"]) for u in data["utterances"]]
    sents = [x for ch in chapters for p in ch.get("paragraphs", []) for x in p]
    verbatim = sum(1 for x in sents if _norm(x["text"]) and any(_norm(x["text"]) in u for u in utts))
    return {
        "chapters": len(chapters),
        "paragraphs": sum(len(ch.get("paragraphs", [])) for ch in chapters),
        "sentences": len(sents),
        "editorial_sentences": sum(1 for x in sents if x["kind"] == "editorial"),
        "multi_turn_sentences": sum(1 for x in sents if len(set(x["turns"])) > 1),
        "verbatim_sentences": verbatim,
        "verbatim_ratio": round(verbatim / len(sents), 2) if sents else None,
    }


def locations(edited: dict) -> set[str]:
    """편집본에 실제로 있는 위치. 검증의 location · edit_notes 의 after 는 이 안이어야 한다."""
    locs = {"artifact", "title"}
    for ch in edited.get("chapters", []):
        k = ch["chapter_key"]
        locs |= {k, f"{k}/title"}
        for p, para in enumerate(ch["paragraphs"]):
            locs |= {f"{k}/p{p}/s{s}" for s in range(len(para))}
    locs |= {f"review_notes:{i}" for i in range(len(edited.get("review_notes", [])))}
    return locs


def draft_locations(drafts: list[dict]) -> set[str]:
    """장 초안에 있던 위치 (목차의 장 키 기준). edit_notes 의 before 는 이 안이어야 한다."""
    locs = {"title"}                               # 책 제목은 목차에서 온다
    for d in drafts:
        k = d["chapter_key"]
        locs |= {k, f"{k}/title"}
        for p, para in enumerate(d["paragraphs"]):
            locs |= {f"{k}/p{p}/s{s}" for s in range(len(para))}
    return locs


def outline_memos(outline_out: dict) -> list[str]:
    """목차의 내부 메모(목적 · 묶은 이유 · 전환 · 방향) — 본문에 그대로 들어가면 안 되는 글."""
    texts = [outline_out.get("book", {}).get(k, "") for k in ("direction", "structure_reason")]
    for ch in outline_out.get("chapters", []):
        texts += [ch.get(k, "") for k in ("purpose", "grouping_reason", "transition_in", "transition_out")]
    return [m for m in (_norm(t) for t in texts if isinstance(t, str)) if len(m) >= 8]


def memo_leaks(chapters: list[dict], memos: list[str]) -> list[str]:
    """
    목차 메모를 그대로 옮긴 editorial 문장의 위치. 글자(공백 · 부호 뺀)가 메모와 같거나
    메모 안에 통째로 들어 있으면 옮긴 것으로 본다. supported 문장은 원문을 옮기는 게
    정상이라 보지 않는다 — 그 뜻은 검증 역할이 본다.
    """
    out = []
    for ch in chapters:
        for p, para in enumerate(ch.get("paragraphs", [])):
            for s, x in enumerate(para):
                t = _norm(x.get("text", ""))
                if x.get("kind") == "editorial" and len(t) >= 8 and any(t in m or m in t for m in memos):
                    out.append(f"{ch['chapter_key']}/p{p}/s{s}")
    return out


def _narration(text: str) -> str:
    """직접 인용을 뺀 서술 부분. 인용은 원문 말투를 그대로 둘 수 있다."""
    return _QUOTE.sub("", text or "").strip()


def _essay_ending(text: str) -> bool:
    """1인칭 회고 수필체 종결(~다 · ~했다)인가. 합니다체(~니다)와 해요체(~요)는 아니다."""
    t = _narration(text).rstrip(" .!?…\"'”’)")
    if not t:
        return True                               # 통째로 인용인 문장
    return t.endswith("다") and not t.endswith("니다")


def code_findings(chapters: list[dict], outline_out: dict) -> list[dict]:
    """
    코드로 판별되는 문제 (설계 v4 · redesign-v4-analysis 3절 A). 모델 판정과 따로 선다.

        block  stop_phrase   인터뷰를 멈추거나 미루는 말이 본문에 남음 ("오늘은 그만할게요")
               memo_leak     목차 메모를 그대로 옮긴 editorial 문장
        fix    style_mix     인용 밖 서술이 ~다 로 끝나지 않음 (해요체 · 합니다체 · 끊긴 문장)
               answer_trace  질문에 대한 답 말로 시작 ("아니요," · "가끔요.")
               meta_text     글 바깥에서 설명하는 안내문 ("이 장에서는 …")
               repeat_turn   같은 원문 턴을 두 장 이상이 근거로 씀 — 의도한 회상인지 편집이 판단
        info   verbatim_run  원문 한 턴을 그대로 옮긴 문장이 셋 이상 잇달음 (사람 검수 참고)

    출처 · 참조 오류와 제외 턴은 여기 없다 — check_final 이 실패로 멈춘다.
    """
    memos = outline_memos(outline_out)
    out: list[dict] = []

    def add(rule, severity, location, detail, **extra):
        out.append({"id": f"{rule}:{location}", "rule": rule, "severity": severity,
                    "location": location, "detail": detail, **extra})

    for ch in chapters:
        k = ch["chapter_key"]
        title = (ch.get("title") or {}).get("text", "")
        if _STOP.search(title):
            add("stop_phrase", "block", f"{k}/title", "인터뷰 진행을 멈추는 말")
        for p, para in enumerate(ch.get("paragraphs", [])):
            for s, x in enumerate(para):
                loc, text = f"{k}/p{p}/s{s}", x.get("text", "")
                if _STOP.search(text):
                    add("stop_phrase", "block", loc, "인터뷰 진행을 멈추는 말")
                t = _norm(text)
                if x.get("kind") == "editorial" and len(t) >= 8 and any(t in m or m in t for m in memos):
                    add("memo_leak", "block", loc, "목차 메모를 그대로 옮김")
                if not _essay_ending(text):
                    add("style_mix", "fix", loc, "인용 밖 서술이 ~다 로 끝나지 않는다")
                if _ANSWER.search(_narration(text) or text):
                    add("answer_trace", "fix", loc, "질문에 대한 답 말로 시작한다")
                if _META.search(_narration(text)):
                    add("meta_text", "fix", loc, "글 바깥에서 설명하는 안내문")
    cited: dict[int, set[str]] = {}
    where: dict[int, list[str]] = {}
    for ch in chapters:
        for p, para in enumerate(ch.get("paragraphs", [])):
            for s, x in enumerate(para):
                if x.get("kind") == "supported":
                    for t in x.get("turns", []):
                        cited.setdefault(t, set()).add(ch["chapter_key"])
                        where.setdefault(t, []).append(f"{ch['chapter_key']}/p{p}/s{s}")
    for t in sorted(cited):
        if len(cited[t]) > 1:
            add("repeat_turn", "fix", where[t][0], f"턴 {t} 을 {sorted(cited[t])} 가 함께 근거로 씀",
                turn=t, locations=where[t])
    return out


def verbatim_runs(chapters: list[dict], data: dict, n: int = 3) -> list[dict]:
    """원문 한 턴을 그대로 옮긴 문장이 n 개 이상 잇달은 곳 — info (사람 검수 참고)."""
    utts = {u["turn"]: _norm(u["elder"]) for u in data["utterances"]}
    out = []
    for ch in chapters:
        for p, para in enumerate(ch.get("paragraphs", [])):
            run_start, run = 0, 0
            for s, x in enumerate(para + [None]):
                hit = (x is not None and len(x.get("turns", [])) == 1 and _norm(x["text"])
                       and _norm(x["text"]) in utts.get(x["turns"][0], ""))
                if hit:
                    run_start = s if run == 0 else run_start
                    run += 1
                else:
                    if run >= n:
                        loc = f"{ch['chapter_key']}/p{p}/s{run_start}"
                        out.append({"id": f"verbatim_run:{loc}", "rule": "verbatim_run", "severity": "info",
                                    "location": loc, "detail": f"원문 한 턴 그대로인 문장 {run}개 잇달음"})
                    run = 0
    return out


def context_findings(draft: dict, core: set[int]) -> list[dict]:
    """
    문맥으로만 준 턴(context_only_turns)을 근거로 단 문장 — fix. 계획에 없는 사건이 앞뒤 문맥을
    타고 본문에 들어오는 것을 편집 · 사람에게 알린다. 이 장 근거 턴과 함께 단 문장은 보지 않는다
    (문맥을 설명에 쓴 것은 허용 — 문맥 턴만으로 선 문장이 문제다).
    """
    out = []
    k = draft["chapter_key"]
    for p, para in enumerate(draft.get("paragraphs", [])):
        for s, x in enumerate(para):
            ts = set(x.get("turns", []))
            if x.get("kind") == "supported" and ts and not ts & core:
                loc = f"{k}/p{p}/s{s}"
                out.append({"id": f"context_only:{loc}", "rule": "context_only", "severity": "fix",
                            "location": loc, "detail": f"문맥으로만 준 턴 {sorted(ts)} 만으로 선 문장 — 계획에 없는 내용인지 본다",
                            "turns": sorted(ts)})
    return out


def check_resolutions(out: dict, checks: list[dict]) -> tuple[dict, list[str]]:
    """
    편집의 checks_resolution — 넘긴 경고(block · fix)마다 resolved / kept + 이유.
    빠진 항목은 처리하지 않은 것으로 센다(실패로 멈추지 않는다 — 최종 본문을 코드가 다시 본다).
    """
    warnings: list[str] = []
    got: dict[str, dict] = {}
    rows = out.get("checks_resolution")
    if not isinstance(rows, list):
        warnings.append("checks_resolution 이 없거나 목록이 아니다")
        rows = []
    for i, r in enumerate(rows):
        if (not isinstance(r, dict) or r.get("status") not in CHECK_STATUSES
                or not isinstance(r.get("check_id"), str) or not isinstance(r.get("reason", ""), str)):
            warnings.append(f"checks_resolution[{i}] 모양이 다르다")
            continue
        if r["status"] == "kept" and not r.get("reason", "").strip():
            warnings.append(f"checks_resolution[{i}] 는 kept 인데 이유가 없다")
            continue
        got[r["check_id"]] = r
    needed = [c["id"] for c in checks if c["severity"] in ("block", "fix")]
    missing = [i for i in needed if i not in got]
    if missing:
        warnings.append(f"처리 결과가 없는 경고 {len(missing)}개 — {missing[:5]}")
    return got, warnings


def code_gate(final: list[dict], resolutions: dict[str, dict], draft_checks: list[dict] | None = None) -> dict:
    """
    편집본 기준 코드 판정.

        blocked    block 이 하나라도 남음 — 모델이 pass 여도 사용자에게 내놓지 않는다
        attention  fix 가 남음. 단 repeat_turn 은 편집이 그 턴의 경고를 kept + 이유(의도한 회상)로
                   처리했으면 남은 것으로 치지 않는다 — 같은 턴을 두 장이 쓴 것만으로 막지 않는다
        pass       block · fix 없음 (info 는 사람 검수 참고로만)
    """
    kept_turns = {c.get("turn") for c in draft_checks or [] if c["rule"] == "repeat_turn"
                  and resolutions.get(c["id"], {}).get("status") == "kept"}

    def accepted(f):
        return f["rule"] == "repeat_turn" and f.get("turn") in kept_turns
    blocks = [f for f in final if f["severity"] == "block"]
    fixes = [f for f in final if f["severity"] == "fix" and not accepted(f)]
    state = "blocked" if blocks else "attention" if fixes else "pass"
    return {"state": state, "findings": final, "accepted_repeats": sorted(t for t in kept_turns if t is not None),
            "counts": {s: sum(1 for f in final if f["severity"] == s) for s in ("block", "fix", "info")}}


def overall_state(generation_state: str, gate: dict | None, verification: dict, human: str) -> str:
    """
    최종 상태. **approved 는 사람만 만든다** — 코드 · 모델 판정으로는 awaiting_human 까지다.

        not_generated    생성이 끝나지 않음 (failed · partial · needs_context · insufficient)
        blocked_by_code  code_gate=blocked
        needs_revision   code_gate=attention · 모델이 revise/ask_user · 검증이 끝나지 않음
        awaiting_human   코드 pass · 모델 pass — 사람 검수 대기
        approved         human_review=passed
    """
    if generation_state != GENERATED:
        return "not_generated"
    if (gate or {}).get("state") == "blocked":
        return "blocked_by_code"
    if human == "passed":
        return "approved"
    if (gate or {}).get("state") != "pass" or verification.get("state") != "completed" \
            or verification.get("verdict") != "pass":
        return "needs_revision"
    return "awaiting_human"


def meta_sentences(chapters: list[dict]) -> list[str]:
    """안내문 말투("이 장에서는", "…보여줍니다", "…이어집니다")가 섞인 문장의 위치."""
    return [f"{ch['chapter_key']}/p{p}/s{s}"
            for ch in chapters for p, para in enumerate(ch.get("paragraphs", []))
            for s, x in enumerate(para) if _META.search(x.get("text", ""))]


def check_edit_notes(notes, before_locs: set[str], after_locs: set[str], c: "_Check") -> None:
    """
    편집 메모 하나하나 — 작업 종류(action)와 before(장 초안 위치) · after(편집본 위치).

        delete   before 1+ · after 0      지운 문장은 편집본에 없는 것이 정상
        merge    before 2+ · after 1      여러 문장 · 장을 하나로
        rewrite  before 1+ · after 1+     고쳐 쓰기 · 나누기
        add      before 0  · after 1+     새로 넣은 연결 문장

    위치가 틀리면 지금처럼 실패다 — 느슨하게 받지 않는다.
    """
    if not isinstance(notes, list):
        raise c.fail("format", "edit_notes 가 목록이 아니다")
    for i, n in enumerate(notes):
        at = f"edit_notes[{i}]"
        if not isinstance(n, dict):
            raise c.fail("format", f"{at} 가 객체가 아니다")
        action = n.get("action")
        if action not in EDIT_ACTIONS:
            raise c.fail("format", f"{at}.action={action!r} — {', '.join(EDIT_ACTIONS)}")
        before, after = n.get("before"), n.get("after")
        if not _str_list(before) or not _str_list(after):
            raise c.fail("format", f"{at}.before · after 가 문자열 목록이 아니다")
        b_min, b_max, a_min, a_max = EDIT_ACTIONS[action]
        if len(before) < b_min or (b_max is not None and len(before) > b_max):
            raise c.fail("format", f"{at} {action} 의 before {len(before)}개 — 개수가 맞지 않는다")
        if len(after) < a_min or (a_max is not None and len(after) > a_max):
            raise c.fail("format", f"{at} {action} 의 after {len(after)}개 — 개수가 맞지 않는다")
        bad = [x for x in before if x not in before_locs]
        if bad:
            raise c.fail("reference", f"{at}.before {bad} — 장 초안에 없는 위치")
        bad = [x for x in after if x not in after_locs]
        if bad:
            raise c.fail("reference", f"{at}.after {bad} — 편집본에 없는 위치")
        for k in ("change", "reason"):
            if not isinstance(n.get(k), str):
                raise c.fail("format", f"{at}.{k} 가 문자열이 아니다")


def check_final(out, outline_out: dict, T: set[int], gone: set[int] = frozenset(),
                drafts: list[dict] | None = None) -> list[str]:
    """
    편집본의 최종 근거검사. 장이 빠지거나 생기면 검증까지 가지 않는다.

    편집은 **장을 합칠 수 있다** — 지나친 분할을 고치라고 했다. 대신 나누거나 순서를
    바꾸거나 목차에 없는 장을 만들 수는 없다: from_chapters 를 차례로 이으면 목차의
    장 순서와 정확히 같아야 한다. 편집본의 장 키는 ch-1 부터 다시 매긴다.

    목차 메모(목적 · 전환 등)를 그대로 옮긴 editorial 문장이 남아 있으면 memo_leak 이다.
    """
    c = _Check("final_check")
    out = c.obj(out, ("title", "chapters", "structure_notes", "review_notes", "edit_notes",
                      "checks_resolution"))
    c.sentence(out["title"], T, "title")
    want = [ch["chapter_key"] for ch in outline_out["chapters"]]
    if not isinstance(out["chapters"], list) or not out["chapters"]:
        raise c.fail("format", "chapters 가 비었거나 목록이 아니다")
    keys, joined = [], []
    for i, ch in enumerate(out["chapters"]):
        if not isinstance(ch, dict):
            raise c.fail("format", f"chapters[{i}] 가 객체가 아니다")
        keys.append(ch.get("chapter_key"))
        src = ch.get("from_chapters")
        if not _str_list(src) or not src:
            raise c.fail("format", f"chapters[{i}].from_chapters 가 비었거나 문자열 목록이 아니다")
        joined += src
    if keys != [f"ch-{n}" for n in range(1, len(keys) + 1)]:
        raise c.fail("reference", f"편집본 장 키 {keys} — ch-1 부터 차례여야 한다")
    if joined != want:
        raise c.fail("reference", f"from_chapters {joined} — 목차의 장 {want} 을 순서대로 한 번씩 담아야 한다")
    allowed = T - set(gone)
    outside = "입력에 없거나 빼 달라고 한 턴"
    for ch in out["chapters"]:
        k = ch["chapter_key"]
        if "title" not in ch or "paragraphs" not in ch:
            raise c.fail("format", f"{k} 에 title · paragraphs 가 없다")
        c.sentence(ch["title"], allowed, f"{k}/title", outside)
        c.paragraphs(ch["paragraphs"], allowed, k, outside)
    if not _str_list(out["structure_notes"]) or not any(s.strip() for s in out["structure_notes"]):
        raise c.fail("format", "structure_notes 가 비었다 — 구성을 본 기록이 없다")
    c.notes(out["review_notes"], allowed, "review_notes", outside)
    before_locs = draft_locations(drafts) if drafts is not None else (
        {"title"} | {k for k in want} | {f"{k}/title" for k in want})
    check_edit_notes(out["edit_notes"], before_locs, locations(out) - {"artifact"}, c)

    # 목차 메모 혼입 · 안내문 · 문체는 v4 부터 code_findings 가 맡는다 (memo_leak 은 block → code_gate)
    return c.warnings


def check_verify(out, T: set[int], locs: set[str]) -> list[str]:
    c = _Check("verify")
    out = c.obj(out, ("review_status", "verdict", "issues", "reviewed_locations", "missing_context"))
    rs, verdict = out["review_status"], out["verdict"]
    if rs not in ("completed", "needs_context", "not_applicable"):
        raise c.fail("format", f"review_status={rs!r}")
    if rs == "completed" and verdict not in ("pass", "revise", "ask_user"):
        raise c.fail("format", f"completed 인데 verdict={verdict!r}")
    if rs != "completed" and verdict is not None:
        raise c.fail("format", f"{rs} 인데 verdict={verdict!r}")
    if not isinstance(out["issues"], list):
        raise c.fail("format", "issues 가 목록이 아니다")
    for i, x in enumerate(out["issues"]):
        at = f"issues[{i}]"
        if not isinstance(x, dict):
            raise c.fail("format", f"{at} 가 객체가 아니다")
        if x.get("location") not in locs:
            raise c.fail("reference", f"{at}.location={x.get('location')!r} — 편집본에 없는 위치")
        if x.get("severity") not in ("blocker", "warning"):
            raise c.fail("format", f"{at}.severity={x.get('severity')!r}")
        cat = x.get("category")
        if cat not in ISSUE_CODES:
            raise c.fail("format", f"{at}.category={cat!r} — fact · composition")
        if x.get("code") not in ISSUE_CODES[cat]:
            raise c.fail("format", f"{at}.code={x.get('code')!r} 는 {cat} 분류가 아니다")
        if x.get("resolution") not in RESOLUTIONS:
            raise c.fail("format", f"{at}.resolution={x.get('resolution')!r}")
        if x["severity"] == "blocker" and verdict == "pass":
            raise c.fail("format", f"{at} 가 blocker 인데 verdict=pass")
        for k in ("explanation", "fix_instruction"):
            if not isinstance(x.get(k), str):
                raise c.fail("format", f"{at}.{k} 가 문자열이 아니다")
        c.turns(x.get("source_turns"), T, f"{at}.source")
    rl = out["reviewed_locations"]
    if not _str_list(rl) or len(set(rl)) != len(rl):
        raise c.fail("format", "reviewed_locations 가 중복 없는 문자열 목록이 아니다")
    unknown = [x for x in rl if x not in locs]
    if unknown:
        raise c.fail("reference", f"reviewed_locations {unknown[:5]} — 편집본에 없는 위치")
    if rs == "completed" and "artifact" not in rl:
        raise c.fail("format", "completed 인데 reviewed_locations 에 artifact 가 없다")
    if not _str_list(out["missing_context"]):
        raise c.fail("format", "missing_context 가 문자열 목록이 아니다")
    return c.warnings


# ---------------------------------------------------------------- 호출


@dataclass
class CallSpec:
    stage: str
    chapter_key: str | None
    system: str
    user: str
    model: str
    temperature: float
    max_output_tokens: int


@dataclass
class Reply:
    text: str
    finish: str | None = None
    usage: dict | None = None


Call = Callable[[CallSpec], Awaitable[Reply]]


async def call_model(spec: CallSpec) -> Reply:
    """한 번 부른다. 다시 부르지 않는다. 시간 제한은 run 이 건다."""
    from .question import _client

    client = _client()
    if client is None:
        raise PipelineError(spec.stage, "call", "GEMINI_API_KEY 가 없다", spec.chapter_key)

    from google.genai import types

    cfg = types.GenerateContentConfig(
        system_instruction=spec.system,
        response_mime_type="application/json",
        temperature=spec.temperature,
        max_output_tokens=spec.max_output_tokens,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    res = await client.aio.models.generate_content(model=spec.model, contents=spec.user, config=cfg)
    finish = None
    cands = getattr(res, "candidates", None) or []
    if cands and getattr(cands[0], "finish_reason", None) is not None:
        finish = str(cands[0].finish_reason)
    um = getattr(res, "usage_metadata", None)
    usage = None
    if um is not None:
        usage = {"prompt": getattr(um, "prompt_token_count", None),
                 "output": getattr(um, "candidates_token_count", None),
                 "thoughts": getattr(um, "thoughts_token_count", None),
                 "total": getattr(um, "total_token_count", None)}
    return Reply(text=res.text or "", finish=finish, usage=usage)


def _user(head: str, payload: dict) -> str:
    """자료 메시지. 모양 설명만 짧게 — 규칙은 지시문에 있다."""
    return "[자료]\n" + head + "\n\n" + json.dumps(payload, ensure_ascii=False, indent=1)


_SOURCE_HEAD = (
    "source 는 고른 회차의 말씀을 합친 원자료다. utterances.turn 은 이 요청의 전역 원문 번호이고 "
    "모든 turns 는 이 번호만 쓴다. elder 는 사용자 발언, asked 는 AI 질문이다. "
    "sessions.recorded_order 는 기록 순서이며 사건 순서가 아니다. "
    "shared_state.facts_found 는 대화 중 정리한 메모이고 원문이 아니다."
)


def analysis_message(data: dict) -> str:
    return _user(_SOURCE_HEAD, {"source": data})


_EXCLUSION_HEAD = (
    "\nexclusions 는 사용자가 빼 달라고 한 범위다. mode=whole 인 턴과 요청 턴(requested_in)은 "
    "source 에서 이미 뺐다. mode=partial 인 턴은 남길 내용이 있어 source 에 남아 있다 — 그 턴에서 "
    "scope 에 해당하는 내용은 본문 · 제목 · 메모 어디에도 쓰지 않는다."
)


def outline_message(data: dict, analysis: dict) -> str:
    head = _SOURCE_HEAD + "\nanalysis 는 앞 단계의 분석이다. 편집 참고일 뿐 사실 근거가 아니다."
    if analysis.get("exclusions"):
        head += _EXCLUSION_HEAD
    return _user(head, {"analysis": analysis, "source": stage_source(data, analysis)})


def chapter_threads(analysis: dict, chapter: dict, given: list[int] | set[int]) -> list[dict]:
    """이 장이 쓰는 끈 — 이름 · 종류와 이 장에 준 턴만 (끈 전체의 턴 목록은 다른 장 원문을 가리킨다)."""
    want = set(chapter.get("threads") or [])
    given = set(given)
    return [{"thread_key": th["thread_key"], "name": th["name"], "kind": th["kind"],
             "turns": sorted(set(th["turns"]) & given)}
            for th in analysis.get("threads", []) if th["thread_key"] in want]


def chapter_message(src: dict, given: list[int], outline_out: dict, chapter: dict,
                    people: list, exclusions: list | None = None,
                    packets: list | None = None, threads: list | None = None,
                    core: set[int] | None = None) -> str:
    head = (_SOURCE_HEAD + "\n이 source 는 이번 장에 필요한 원문만 남긴 것이다(given_turns). "
            "다른 장의 원문은 일부러 뺐다. source.utterances 는 인터뷰 순서가 아니라 이 장의 사건 "
            "묶음 순서로 놓았다(번호와 글은 그대로). event_packets 는 사건마다 받은 턴, threads 는 "
            "이 장이 잇는 사람 · 물건 · 장소 · 주제다. core_turns 는 이 장 본문의 근거 턴이고, "
            "context_only_turns 는 앞뒤 사정을 이해하라고 붙인 문맥일 뿐 이 장에서 다룰 사건이 아니다. "
            "outline 은 책 전체 목차, chapter 는 이번에 쓸 장, people 은 앞 단계가 정리한 인물이다.")
    core = set(core) if core is not None else set(given)
    payload = {"outline": {"book": outline_out["book"], "chapters": outline_out["chapters"]},
               "chapter": chapter, "people": people, "given_turns": given,
               "core_turns": sorted(set(given) & core),
               "context_only_turns": sorted(set(given) - core),
               "event_packets": packets or [], "threads": threads or []}
    if exclusions:
        head += _EXCLUSION_HEAD
        payload["exclusions"] = exclusions
    payload["source"] = src
    return _user(head, payload)


def edit_message(data: dict, outline_out: dict, chapters: list[dict],
                 analysis: dict | None = None, checks: list | None = None) -> str:
    head = (_SOURCE_HEAD + "\noutline 은 목차, chapters 는 장마다 따로 쓴 초안이다. "
            "초안은 사실 근거가 아니다 — source 와 다시 대조한다. checks 는 코드가 초안에서 찾은 "
            "고칠 곳이다(location 은 초안 위치). 하나하나 checks_resolution 에 처리 결과를 적는다.")
    payload = {"outline": {"book": outline_out["book"], "chapters": outline_out["chapters"]},
               "chapters": chapters, "checks": checks or []}
    analysis = analysis or {}
    if analysis.get("exclusions"):
        head += _EXCLUSION_HEAD
        payload["exclusions"] = exclusion_notices(analysis)
    payload["source"] = stage_source(data, analysis)
    return _user(head, payload)


def verify_plan(analysis: dict, outline_out: dict, steps: list[dict] | None = None) -> dict:
    """
    구성 검사(장 역할 중복 · 주제 모순 · 분할)에 쓸 계획만. 사건 요약 · 근거 턴은 싣지 않는다.
    앞 단계의 코드 경고(예: "사건 하나마다 장 하나")를 checks 로 함께 준다 — 판정은 검증이 한다.
    """
    checks = [f"{s['stage']}{'/' + s['chapter_key'] if s.get('chapter_key') else ''}: {w}"
              for s in steps or [] for w in s.get("warnings") or []]
    return {
        "checks": checks,
        "direction": analysis.get("direction"),
        "themes": [{"theme": t["theme"], "strength": t["strength"]} for t in analysis.get("themes", [])],
        "book": {"structure_reason": outline_out["book"].get("structure_reason", "")},
        "chapters": [{"chapter_key": ch["chapter_key"], "purpose": ch["purpose"],
                      "grouping_reason": ch.get("grouping_reason", "")}
                     for ch in outline_out["chapters"]],
    }


def verify_message(data: dict, edited: dict, T: set[int], plan: dict | None = None,
                   exclusions: list | None = None) -> str:
    """검증은 재등장을 찾아야 하니 원자료 전부를 받는다 — 빼 달라고 한 턴도 source 에 있다."""
    head = (_SOURCE_HEAD + "\ncandidate 는 검증할 편집본이다. plan 은 목차의 장별 목적과 분석의 "
            "주제 판단이며 구성 검사에만 쓴다(사실 근거가 아니다). 편집에서 장을 합쳤다면 "
            "candidate 의 from_chapters 가 목차의 장 키를 가리킨다. review_scope.turns 는 이번 "
            "검토 범위 전체이고 complete=true 는 그 원문이 빠짐없이 source 에 있다는 뜻이다.")
    payload = {"artifact_type": "memoir_chapters", "candidate": edited, "plan": plan or {}}
    if exclusions:
        head += ("\nexclusions 는 사용자가 빼 달라고 한 범위다. source 에는 대조를 위해 그 턴도 "
                 "남겨 두었다. scope 에 해당하는 내용이 candidate 에 나오면 exclusion_violation 이다.")
        payload["exclusions"] = exclusions
    payload.update({"review_scope": {"turns": sorted(T), "complete": True}, "source": data})
    return _user(head, payload)


# ---------------------------------------------------------------- 기록


class Recorder:
    """run 폴더에 단계 파일을 남긴다. folder 가 None 이면 메모리에만 (시험용)."""

    def __init__(self, folder: Path | None = None):
        self.folder = folder
        self.files: dict[str, str] = {}
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)

    def text(self, name: str, body: str) -> str:
        self.files[name] = body
        if self.folder is not None:
            (self.folder / name).write_text(body, encoding="utf-8", newline="\n")
        return name

    def json(self, name: str, obj) -> str:
        return self.text(name, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


@dataclass
class _Run:
    data: dict
    T: set[int]
    call: Call
    rec: Recorder
    cfg: dict
    started: float = field(default_factory=time.monotonic)
    steps: list[dict] = field(default_factory=list)
    calls: int = 0
    max_calls: int = 2       # 목차가 나오면 장 수 + 4 로 늘린다

    async def ask(self, stage: str, user: str, file_stem: str,
                  chapter_key: str | None = None) -> tuple[Any, dict]:
        """한 단계 한 번. 시간 · 호출 수 상한을 먼저 보고, 응답을 그대로 남긴 뒤 JSON 으로 읽는다."""
        up = stage.upper()
        limit = self.cfg[f"MEMOIR_PIPE_{up}_TIMEOUT"]
        tokens = self.cfg[f"MEMOIR_PIPE_{up}_MAX_OUTPUT_TOKENS"]
        left = self.cfg["MEMOIR_PIPE_TOTAL_TIMEOUT"] - (time.monotonic() - self.started)
        step = {"stage": stage, "chapter_key": chapter_key, "ok": False, "ms": 0,
                "timeout": limit, "max_output_tokens": tokens, "in_chars": len(user),
                "out_chars": 0, "finish": None, "usage": None,
                "file": None, "raw_file": None, "warnings": [], "error": None}
        self.steps.append(step)
        if left <= 0:
            raise PipelineError(stage, "budget", "전체 시간 상한을 넘었다", chapter_key)
        if self.calls >= self.max_calls:
            raise PipelineError(stage, "budget", f"호출 수 상한 {self.max_calls}", chapter_key)

        spec = CallSpec(stage, chapter_key, prompt(stage), user,
                        self.cfg["MEMOIR_PIPE_TEXT_MODEL"], self.cfg["MEMOIR_PIPE_TEMPERATURE"], tokens)
        wait = min(limit, left)
        self.calls += 1
        t0 = time.monotonic()
        try:
            reply = await asyncio.wait_for(self.call(spec), timeout=wait)
        except asyncio.TimeoutError as e:
            kind = "timeout" if wait == limit else "budget"
            raise PipelineError(stage, kind, f"{wait:.0f}초 안에 오지 않았다", chapter_key) from e
        except PipelineError:
            raise
        except Exception as e:                               # noqa: BLE001
            raise PipelineError(stage, "call", f"{type(e).__name__}: {str(e)[:200]}", chapter_key) from e
        finally:
            step["ms"] = int((time.monotonic() - t0) * 1000)

        step.update(out_chars=len(reply.text), finish=reply.finish, usage=reply.usage)
        step["raw_file"] = self.rec.text(f"{file_stem}.raw.txt", reply.text)
        if reply.finish and "MAX_TOKENS" in reply.finish:
            raise PipelineError(stage, "truncated",
                                f"출력 토큰 상한 {tokens} 에서 멈췄다 ({len(reply.text)}자)", chapter_key)
        text = reply.text.strip()
        if not text:
            raise PipelineError(stage, "format", "빈 응답", chapter_key)
        try:
            out = json.loads(text)
        except ValueError as e:
            raise PipelineError(stage, "format", f"JSON 이 아니다 ({len(text)}자)", chapter_key) from e
        step["file"] = self.rec.json(f"{file_stem}.json", out)
        return out, step


def _result(state: str, *, failure: PipelineError | None = None, edited: dict | None = None,
            verification: dict | None = None, complete: bool = False, calls: int = 0,
            metrics: dict | None = None, gate: dict | None = None) -> dict:
    edited = edited if state == GENERATED else None
    verification = verification or {"state": "not_run", "verdict": None, "issues": [],
                                    "reviewed_locations": [], "missing_context": []}
    human = "not_run"                            # 코드는 늘 not_run 으로 쓴다 — 사람이 R1 에 적는다
    gate = gate or {"state": "not_run", "findings": [], "counts": {}}
    return {
        "generation_state": state,
        "pipeline_complete": complete,
        "code_gate": gate["state"],
        "model_verdict": verification.get("verdict"),
        "human_review": human,
        "overall": overall_state(state, gate if gate["state"] != "not_run" else None, verification, human),
        "failure": failure.as_dict() if failure else None,
        "title": edited["title"] if edited else None,
        "chapters": edited["chapters"] if edited else [],
        "structure_notes": edited.get("structure_notes", []) if edited else [],
        "review_notes": edited["review_notes"] if edited else [],
        "verification": verification,
        "code_findings": gate.get("findings", []),
        "metrics": metrics or {},
        "calls": calls,
        "prompt_version": PROMPT_VERSION,
    }


async def run(data: dict, turn_map: list[dict], *, call: Call = call_model,
              recorder: Recorder | None = None, meta: dict | None = None) -> dict:
    """
    다섯 단계를 차례로. 돌려주는 것은 result (result.json 과 같은 것).

    meta 는 실행 기록에 그대로 덧붙이는 식별(run_ref · seed · alias)이다.
    """
    rec = recorder or Recorder()
    cfg = settings()
    meta = dict(meta or {})
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    st: _Run | None = None
    result = _result(FAILED)     # 아래에서 반드시 덮어쓴다. 예상 못 한 오류에도 기록은 남긴다

    try:
        try:
            T = check_input(data, turn_map)
        except PipelineError as e:
            rec.json("00_input.json", {"input_ref": None, "rejected": e.message})
            raise
        ref = input_ref(data)
        meta["input_ref"] = ref
        rec.json("00_input.json", {"input_ref": ref, "input": data, "turn_map": turn_map})
        st = _Run(data, T, call, rec, cfg)

        # ① 분석
        analysis, step = await st.ask("analysis", analysis_message(data), "01_analysis")
        status, step["warnings"] = check_analysis(analysis, T)
        step["ok"] = True
        if status == INSUFFICIENT:
            result = _result(INSUFFICIENT, calls=st.calls)
            return result
        if status == NEEDS_CONTEXT:
            raise PipelineError("analysis", "context", "; ".join(analysis["missing_context"])[:300])

        # ② 목차
        outline_out, step = await st.ask("outline", outline_message(data, analysis), "02_outline")
        status, step["warnings"] = check_outline(outline_out, analysis, T)
        step["ok"] = True
        if status == NEEDS_CONTEXT:
            raise PipelineError("outline", "context", "; ".join(outline_out["missing_context"])[:300])
        chapters_plan = outline_out["chapters"]
        st.max_calls = len(chapters_plan) + 4

        # ③ 장별 집필 — 순서대로, 첫 실패에서 멈춘다
        drafts: list[dict] = []
        cores: list[set[int]] = []
        for ch in chapters_plan:
            key = ch["chapter_key"]
            src, given = chapter_source(data, analysis, ch, outline_out)
            core = chapter_owned_turns(analysis, ch) | set(ch.get("context_turns") or [])
            try:
                draft, step = await st.ask("chapter", chapter_message(
                    src, given, outline_out, ch, analysis["people"],
                    exclusion_notices(analysis, set(given)),
                    event_packets(analysis, ch, given), chapter_threads(analysis, ch, given), core),
                    f"03_{key}", key)
                step["warnings"] = check_chapter(draft, ch, given, core, outline_memos(outline_out))
                step["given_turns"] = given
                step["metrics"] = text_metrics([draft], data)
                step["ok"] = True
            except PipelineError as e:
                st.steps[-1]["error"] = e.as_dict()
                result = _result(PARTIAL, failure=e, calls=st.calls)
                return result
            drafts.append(draft)
            cores.append(core)

        # 코드 판정 ① — 장 초안에서. 편집이 고칠 곳으로 넘긴다
        draft_checks = code_findings(drafts, outline_out) + [
            f for d, c in zip(drafts, cores) for f in context_findings(d, c)]
        rec.json("03_checks.json", draft_checks)

        # ④ 전체 편집 → 최종 근거검사 → 코드 판정 ②
        edited, step = await st.ask("edit", edit_message(data, outline_out, drafts, analysis, draft_checks),
                                    "04_edited")
        step["ok"] = True
        try:
            step["warnings"] = check_final(edited, outline_out, T, excluded_turns(analysis), drafts)
        except PipelineError as e:
            step["ok"] = False
            raise
        resolutions, res_warnings = check_resolutions(edited, draft_checks)
        step["warnings"] += res_warnings
        final_findings = code_findings(edited["chapters"], outline_out) + verbatim_runs(edited["chapters"], data)
        gate = code_gate(final_findings, resolutions, draft_checks)
        gate["draft_checks"] = len(draft_checks)
        gate["resolutions"] = {s: sum(1 for r in resolutions.values() if r["status"] == s) for s in CHECK_STATUSES}
        rec.json("04_code_gate.json", gate)
        actions: dict[str, int] = {}
        for n in edited["edit_notes"]:
            actions[n["action"]] = actions.get(n["action"], 0) + 1
        metrics = {"events": len(analysis["events"]), "outline_chapters": len(chapters_plan),
                   **text_metrics(edited["chapters"], data),
                   "edit_notes": len(edited["edit_notes"]), "edit_actions": actions,
                   "merged_chapters": sum(1 for ch in edited["chapters"] if len(ch["from_chapters"]) > 1),
                   "draft_verbatim_ratio": text_metrics(drafts, data)["verbatim_ratio"]}
        step["metrics"] = metrics

        # ⑤ 검증 — 실패해도 편집본은 생성된 것이다. 완성 실행은 아니다
        locs = locations(edited)
        plan = verify_plan(analysis, outline_out, st.steps)
        plan["code_findings"] = [{k: f[k] for k in ("rule", "severity", "location")} for f in final_findings]
        try:
            verdict_out, step = await st.ask(
                "verify", verify_message(data, edited, T, plan, exclusion_notices(analysis)), "05_verify")
            step["warnings"] = check_verify(verdict_out, T, locs)
            step["ok"] = True
        except PipelineError as e:
            st.steps[-1]["error"] = e.as_dict()
            result = _result(GENERATED, failure=e, edited=edited, calls=st.calls, metrics=metrics, gate=gate,
                             verification={"state": "failed", "verdict": None, "issues": [],
                                           "reviewed_locations": [], "missing_context": []})
            return result
        verification = {"state": verdict_out["review_status"], "verdict": verdict_out["verdict"],
                        "issues": verdict_out["issues"],
                        "reviewed_locations": verdict_out["reviewed_locations"],
                        "missing_context": verdict_out["missing_context"]}
        result = _result(GENERATED, edited=edited, verification=verification, calls=st.calls,
                         complete=verdict_out["review_status"] == "completed", metrics=metrics, gate=gate)
        return result

    except PipelineError as e:
        if st is not None and st.steps and st.steps[-1]["error"] is None and not st.steps[-1]["ok"]:
            st.steps[-1]["error"] = e.as_dict()
        state = NEEDS_CONTEXT if e.kind == "context" else FAILED
        result = _result(state, failure=e, calls=st.calls if st else 0)
        return result

    finally:
        result.update({k: meta[k] for k in ("run_ref", "input_ref") if k in meta})
        rec.json("result.json", result)
        run_doc = {**meta, "started_at": started_at,
                   "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "settings": cfg, "prompts": _safe_hashes(),
                   "steps": st.steps if st else [],
                   "generation_state": result["generation_state"],
                   "pipeline_complete": result["pipeline_complete"],
                   "code_gate": result.get("code_gate"), "overall": result.get("overall"),
                   "failure": result["failure"], "calls": result["calls"]}
        rec.json("run.json", run_doc)
        rec.text("r1_summary.md", r1_summary(run_doc, result))


def _safe_hashes() -> dict:
    try:
        return prompt_hashes()
    except PipelineError as e:
        return {"error": e.message}


# ---------------------------------------------------------------- 한 장 시험 (v4)

# 시험 계획에 들어오면 안 되는 것 — 예상 정답 글. 모델에게 정답을 보여 주면 시험이 아니다
_TRIAL_FORBIDDEN_KEYS = re.compile(r"expected|answer|sample|essay|reference_text|정답|예시글|모범")
TRIAL_MAX_TEXT = 160


def trial_plan(spec, T: set[int]) -> tuple[dict, dict]:
    """
    한 장 시험 계획 → (분석 모양, 목차 모양). 계획은 **턴 배치 · 사건 묶음 · 끈 · 장 역할** 뿐이다.

    예상 정답 수필은 받지 않는다 — 그런 키가 있거나 글이 길면(TRIAL_MAX_TEXT 자 초과) 거부한다.
    사건 요약은 비운 채 넘긴다(장 집필은 원문만 근거로 쓴다).
    """
    def bad(why):
        return PipelineError("input", "input", f"시험 계획: {why}")

    if not isinstance(spec, dict):
        raise bad("객체가 아니다")

    def walk(v, path="spec"):
        if isinstance(v, dict):
            for k, x in v.items():
                if _TRIAL_FORBIDDEN_KEYS.search(str(k)):
                    raise bad(f"{path}.{k} — 예상 정답 글은 계획에 넣지 않는다")
                walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
        elif isinstance(v, str) and len(v) > TRIAL_MAX_TEXT:
            raise bad(f"{path} 가 {len(v)}자 — 계획 메모는 짧게, 본문 같은 글은 넣지 않는다")
    walk(spec)

    for k in ("chapter", "events", "threads", "people"):
        if k not in spec:
            raise bad(f"{k} 가 없다")
    events = []
    for i, e in enumerate(spec["events"]):
        ts = _int_list((e or {}).get("turns"))
        if not isinstance(e, dict) or not isinstance(e.get("event_key"), str) or not ts:
            raise bad(f"events[{i}] 모양이 다르다")
        if set(ts) - T:
            raise bad(f"events[{i}] 의 턴 {sorted(set(ts) - T)} 이 입력에 없다")
        events.append({"event_key": e["event_key"], "summary": "", "turns": ts, "people": [],
                       "time": {"text": "", "certainty": "unknown"}, "said_feelings": []})
    keys = {e["event_key"] for e in events}
    for i, th in enumerate(spec["threads"]):
        if (not isinstance(th, dict) or th.get("kind") not in THREAD_KINDS
                or not isinstance(th.get("thread_key"), str) or not _str_list(th.get("events"))
                or set(th["events"]) - keys or not _int_list(th.get("turns")) or set(th["turns"]) - T):
            raise bad(f"threads[{i}] 모양이 다르다")
    analysis = {"events": events, "threads": spec["threads"], "people": spec["people"], "exclusions": [],
                "direction": spec.get("direction") or {"theme": "", "reason": "", "neutral": True}}
    ch = spec["chapter"]
    outline_out = {"status": "ready",
                   "book": {"title": {"text": "한 장 시험", "kind": "editorial", "turns": []},
                            "direction": "", "structure_reason": "한 장 시험",
                            "opening_turns": [], "closing_turns": (ch.get("focus_turns") or [])[-1:],
                            "theme_use": spec.get("theme_use", "")},
                   "chapters": [ch], "left_out": [], "missing_context": []}
    check_outline(outline_out, analysis, T)
    return analysis, outline_out


async def run_chapter_trial(data: dict, turn_map: list[dict], spec: dict, *, call: Call = call_model,
                            recorder: Recorder | None = None, meta: dict | None = None) -> dict:
    """
    장 하나만 쓰는 작은 시험 — 모델 호출 **1회**(장 집필 v4). 분석 · 목차는 계획 파일이 대신하고,
    편집 · 검증은 부르지 않는다. 결과는 코드 판정 · 지표와 함께 남기고 사람이 읽고 판단한다.
    """
    rec = recorder or Recorder()
    cfg = settings()
    meta = dict(meta or {})
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    st: _Run | None = None
    result: dict = {"mode": "chapter_trial", "generation_state": FAILED, "human_review": "not_run",
                    "failure": None, "draft": None, "code_findings": [], "metrics": {}, "calls": 0,
                    "prompt_version": PROMPT_VERSION}
    try:
        T = check_input(data, turn_map)
        meta["input_ref"] = input_ref(data)
        analysis, outline_out = trial_plan(spec, T)
        rec.json("00_trial_plan.json", spec)
        ch = outline_out["chapters"][0]
        src, given = chapter_source(data, analysis, ch, outline_out)
        core_turns = chapter_owned_turns(analysis, ch) | set(ch.get("context_turns") or [])
        rec.json("00_input.json", {"input_ref": meta["input_ref"], "given_turns": given,
                                   "core_turns": sorted(set(given) & core_turns),
                                   "context_only_turns": sorted(set(given) - core_turns),
                                   "event_packets": event_packets(analysis, ch, given)})
        st = _Run(data, T, call, rec, cfg)
        st.max_calls = 1
        core = chapter_owned_turns(analysis, ch) | set(ch.get("context_turns") or [])
        draft, step = await st.ask("chapter", chapter_message(
            src, given, outline_out, ch, analysis["people"], None,
            event_packets(analysis, ch, given), chapter_threads(analysis, ch, given), core),
            f"03_{ch['chapter_key']}", ch["chapter_key"])
        step["warnings"] = check_chapter(draft, ch, given, core, outline_memos(outline_out))
        step["given_turns"] = given
        step["ok"] = True
        findings = (code_findings([draft], outline_out) + context_findings(draft, core)
                    + verbatim_runs([draft], data))
        sessions = {u["turn"]: u["session_id"] for u in data["utterances"]}
        paras = [{"paragraph": p, "sessions": sorted({sessions[t] for x in para for t in x["turns"]})}
                 for p, para in enumerate(draft["paragraphs"])]
        result.update(generation_state=GENERATED, draft=draft, code_findings=findings, calls=st.calls,
                      metrics={**text_metrics([draft], data), "given_turns": len(given),
                               "cited_turns": len({t for para in draft["paragraphs"] for x in para
                                                   for t in x["turns"]}),
                               "paragraph_sessions": paras})
        return result
    except PipelineError as e:
        if st is not None and st.steps and st.steps[-1]["error"] is None:
            st.steps[-1]["error"] = e.as_dict()
        result.update(failure=e.as_dict(), calls=st.calls if st else 0)
        return result
    finally:
        result.update({k: meta[k] for k in ("run_ref", "input_ref") if k in meta})
        rec.json("result.json", result)
        rec.json("run.json", {**meta, "mode": "chapter_trial", "started_at": started_at,
                              "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "settings": cfg, "prompts": _safe_hashes(),
                              "steps": st.steps if st else [], "calls": result["calls"],
                              "generation_state": result["generation_state"], "failure": result["failure"]})


# ---------------------------------------------------------------- R1 요약


def r1_summary(run_doc: dict, result: dict) -> str:
    """
    팀 공유용 요약. **본문 · 원문 · 검증 설명문 · 비밀값을 넣지 않는다** — 숫자 · 상태 ·
    위치 · 코드만. 사람 검수 칸은 비워 둔다.
    """
    cfg = run_doc.get("settings", {})
    v = result["verification"]
    f = result["failure"]
    lines = [
        f"# R1 — 자서전 파이프라인 실행 {run_doc.get('run_ref', '(이름 없음)')}",
        "",
        "## 실행 식별",
        f"- input_ref: `{run_doc.get('input_ref')}` · seed: `{run_doc.get('seed')}` · "
        f"alias: {', '.join(run_doc.get('aliases') or [])}",
        f"- 시각: {run_doc.get('started_at')} ~ {run_doc.get('finished_at')}",
        "",
        "## 설정",
        f"- 모델 `{cfg.get('MEMOIR_PIPE_TEXT_MODEL')}` · 온도 {cfg.get('MEMOIR_PIPE_TEMPERATURE')} · "
        f"전체 상한 {cfg.get('MEMOIR_PIPE_TOTAL_TIMEOUT')}초 · 재시도 {cfg.get('retries')} · "
        f"장 {cfg.get('chapters')}",
        "- 단계 상한: " + " · ".join(
            f"{s} {cfg.get(f'MEMOIR_PIPE_{s.upper()}_TIMEOUT')}초/"
            f"{cfg.get(f'MEMOIR_PIPE_{s.upper()}_MAX_OUTPUT_TOKENS')}" for s in STAGES),
        f"- 지시문 판: {result.get('prompt_version')}",
        "",
        "## 상태",
        f"- generation_state: **{result['generation_state']}** · pipeline_complete: "
        f"**{str(result['pipeline_complete']).lower()}** · 호출 {result['calls']}회",
        f"- verification: {v['state']} · verdict: {v['verdict']}",
        f"- code_gate: **{result.get('code_gate')}** · model_verdict: {result.get('model_verdict')} · "
        f"human_review: {result['human_review']} → **overall: {result.get('overall')}**",
        "- approved 는 사람 검수로만 된다 — 모델 pass · 코드 pass 는 품질 승인이 아니다",
    ]
    if f:
        lines.append(f"- 실패: 단계 `{f['stage']}` · 장 `{f['chapter_key']}` · 종류 `{f['kind']}`")
    lines += ["", "## 단계", "",
              "| 단계 | 장 | 성공 | ms | 입력 글자 | 출력 글자 | 토큰(입력/출력/생각) | finish | 경고 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for s in run_doc.get("steps", []):
        u = s.get("usage") or {}
        lines.append(
            f"| {s['stage']} | {s.get('chapter_key') or ''} | {'O' if s['ok'] else 'X'} | {s['ms']} | "
            f"{s['in_chars']} | {s['out_chars']} | {u.get('prompt')}/{u.get('output')}/{u.get('thoughts')} | "
            f"{s.get('finish') or ''} | {len(s.get('warnings') or [])} |")
    if result["chapters"]:
        lines += ["", "## 결과 모양", ""]
        for ch in result["chapters"]:
            sents = [x for p in ch["paragraphs"] for x in p]
            sup = sum(1 for x in sents if x["kind"] == "supported")
            lines.append(f"- {ch['chapter_key']}: 문단 {len(ch['paragraphs'])} · 문장 {len(sents)} "
                         f"(supported {sup} · editorial {len(sents) - sup})")
        lines.append(f"- review_notes {len(result['review_notes'])}건 · structure_notes "
                     f"{len(result.get('structure_notes') or [])}건")
    m = result.get("metrics") or {}
    if m:
        lines += ["", "## 비교 지표 (판정 아님)", "",
                  f"- 사건 {m.get('events')} · 목차 장 {m.get('outline_chapters')} → 편집본 장 "
                  f"{m.get('chapters')} (합친 장 {m.get('merged_chapters')})",
                  f"- 문장 {m.get('sentences')} · editorial {m.get('editorial_sentences')} · 여러 턴을 묶은 문장 "
                  f"{m.get('multi_turn_sentences')}",
                  f"- 원문 그대로인 문장 {m.get('verbatim_sentences')} (편집본 {m.get('verbatim_ratio')} · "
                  f"장 초안 {m.get('draft_verbatim_ratio')}) · edit_notes {m.get('edit_notes')} "
                  f"{m.get('edit_actions') or ''}"]
    cf = result.get("code_findings") or []
    if cf:
        by_rule: dict[str, int] = {}
        for f in cf:
            key = f"{f['rule']}({f['severity']})"
            by_rule[key] = by_rule.get(key, 0) + 1
        lines += ["", f"## 코드 판정 (편집본) — {by_rule}", "", "| 위치 | 규칙 | severity |", "|---|---|---|"]
        lines += [f"| {f['location']} | {f['rule']} | {f['severity']} |" for f in cf]
    if v["issues"]:
        by = {}
        for x in v["issues"]:
            by[x.get("category")] = by.get(x.get("category"), 0) + 1
        lines += ["", f"## 검증 issues (설명문 제외) — {by}", "",
                  "| 위치 | 분류 | severity | code | resolution |", "|---|---|---|---|---|"]
        lines += [f"| {x['location']} | {x.get('category')} | {x['severity']} | {x['code']} | "
                  f"{x['resolution']} |" for x in v["issues"]]
    lines += ["", "## 사람 검수 (직접 적는다 — 위 지표보다 먼저 본다)", "",
              "- human_review: not_run / passed / failed",
              "- 1 중심 주제가 실제 발언으로 뒷받침되는가:",
              "- 2 장 구성이 필요한 만큼만 나뉘었는가:",
              "- 3 회차 요약을 단순 나열하지 않았는가:",
              "- 4 전체 흐름이 자연스러운가:",
              "- 5 원문 사실과 직접 표현된 감정이 보존됐는가:",
              "- 6 제외된 정보가 재등장하지 않는가:",
              "- 문제 위치와 이유:",
              "- 검수자 · 시각:", ""]
    return "\n".join(lines)
