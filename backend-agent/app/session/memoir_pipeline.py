"""
자서전 5단계 독립 실행 파이프라인 — 단위 8P (서비스 경로와 따로 돈다)

    ① 분석      call  → 참조검사       사실 원장 · 기억 단위 · 끈 · 정정
    ② 목차      call  → 참조검사       책 설계도 — 장마다 중심 · 핵심 경험 · 문단 계획 · 생략
    ③ 장 집필   call × 장 수           장마다 그 장 문단 계획의 사실과 원문만
    ④ 편집      call  → 최종 근거검사  구성 편집 — 장 · 문단을 합치고 나누고 옮긴다
    ⑤ 검증      call                   사실 대조 + 구성 채점(근거 위치 필수)

**역할마다 따로 부른다.** 다섯 역할을 한 지시에 넣어 한 번 부르지 않는다. 같은
모델이어도 된다. 성공하면 호출은 정확히 장 수 + 4 번이다.

**전역 턴은 merge 가 한 번 정한다.** 어느 단계도 다시 매기지 않는다. v5 부터 본문
문장은 사실 원장의 사실(facts)을 근거로 달고, 코드가 그 사실의 원문 턴(turns)을 펼쳐
붙인다 — 문장마다 원문 턴까지 거슬러 갈 수 있다. 분석 · 목차 · 편집 결과는 사실의
근거가 아니다 — 다음 단계에도 같은 원자료를 다시 준다.

**편집이 바꾼 것은 코드가 잰다.** 모델의 편집 메모를 믿지 않는다. 장 초안과 편집본을
문장 · 사실 단위로 맞대어 옮김 · 합침 · 나눔 · 덜어 냄을 edit_trace 로 남긴다.

**첫 실패에서 멈춘다.** 재시도는 없다. 장 하나가 실패하면 남은 장 · 편집 · 검증을
부르지 않고 partial 이다. 성공한 장은 실행 기록에만 남는다.

**고치지 않는다.** 모델이 낸 번호 · 키가 어긋나면 맞춰 주지 않고 실패다. 응답을
자르지 않는다 — 출력 상한에서 멈춘 응답은 JSON 이 맞아 보여도 truncated 다.

**모델 pass 는 품질 승인이 아니다.** model_verdict 는 사실 대조, model_quality 는 구성
채점(코드가 근거 없는 점수를 되돌린다)이다. approved 는 human_review 로만 된다 —
코드는 늘 not_run 으로 쓴다.

저장하지 않는다. DB 를 부르지 않는다. 설정은 MEMOIR_PIPE_* 만 읽는다 — 서비스의
MEMOIR_* 와 섞지 않는다.
"""

from __future__ import annotations

import asyncio
import difflib
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
COMMON_DOC = PROMPTS / "자서전_v4.md"
ROLE_DIR = PROMPTS / "파이프라인"
# v1 — 첫 실측(fe94baf). v2 — 구성 · 제외(9231a70). v3 — 편집 메모 작업 종류 · 장 분할 원칙 ·
# 목차 메모 혼입 방지(5ae6c1c · d3deb2b). v4 — 1인칭 회고 수필체 · 사건과 끈 · code_gate(84c2f11).
# v5 — 사실 원장과 기억 단위 · 책 설계도 · 문단 단위 서사 · 구성 편집 · 사실 + 구성 채점
# (redesign-v5-book-quality.md). 옛 판 파일은 실행 기록으로 남긴다. 계약은 판마다 달라 옛 판은
# 그 커밋에서만 돈다.
# v7 — 독립 일화 · 필수 경위 보존, 주된 구간과 재언급, 불확실성 · 감정의 범위, 삭제보다 통합, Q4 · 제목 판정
# (naemalssami-memoir-editor 기준 · 2026-10-29 합의 명세). 출력 계약은 v5 그대로다. v6 이름은 편집 단독 실험
# (4_편집_v6.md · edit_contract "v6")이 쓰고 있어 섞이지 않게 v7 로 건너뛴다.
PROMPT_VERSION = "v7"
ROLE_FILES = {
    "analysis": "1_분석_v7.md",
    "outline": "2_목차_v7.md",
    "chapter": "3_장집필_v7.md",
    "edit": "4_편집_v7.md",
    "verify": "5_검증_v7.md",
}
STAGES = tuple(ROLE_FILES)

# 실측용 값이다. v4 C 실측에서 분석 출력이 4,887/5,000 토큰으로 상한에 붙어 늘렸다.
DEFAULT_LIMITS = {               # 초, 출력 토큰
    "analysis": (90.0, 8000),
    "outline": (60.0, 6000),
    "chapter": (90.0, 6000),     # 장마다
    "edit": (150.0, 10000),
    "verify": (90.0, 6000),
}
DEFAULT_TEMPERATURE = 0.3
DEFAULT_TOTAL_TIMEOUT = 600.0
MIN_CHAPTERS, MAX_CHAPTERS = 1, 5    # 독립 실험의 안전 상한. 넘으면 자르지 않고 실패
RETRIES = 0
# 장 집필 비교(--chapter-only)의 장 단계 상한 — 생각 토큰도 출력 상한에 들어가는 모델이 계약 밖 이유로
# 잘리지 않게 넉넉히 둔다(초, 출력 토큰). 기본 실행의 상한은 그대로다
CHAPTER_ONLY_LIMITS = (240.0, 32768)
EDIT_ONLY_LIMITS = (300.0, 32768)       # 편집 단독 시험의 편집 단계 상한 — 같은 까닭

# 상태 값
GENERATED, PARTIAL, FAILED = "generated", "partial", "failed"
DRAFT_ONLY = "draft_only"          # 장 집필 비교 — 편집 · 검증을 부르지 않았다. 완성본이 아니다
EDIT_ONLY = "edit_only"            # 편집 단독 시험 — 남긴 초안을 편집만 했다. 검증을 부르지 않았다
INSUFFICIENT, NEEDS_CONTEXT = "insufficient_material", "needs_context"
KINDS = ("input", "call", "timeout", "truncated", "format", "reference",
         "context", "chapter_limit", "budget", "memo_leak")

# 사실 원장의 값
SOURCES = ("self", "heard", "view")              # 직접 겪은 일 / 들은 이야기 / 화자의 평가 · 생각(객관적 사실이 아니다)
CERTAINTIES = ("stated", "approx", "uncertain")  # 분명히 말함 / 대략("쯤") / 화자도 확신하지 않음
WEIGHTS = ("main", "minor")
THREAD_KINDS = ("person", "object", "place", "theme")
STRENGTHS = ("clear", "partial", "weak")
CHECK_STATUSES = ("resolved", "kept")

# 검증 issue 는 사실과 구성을 나눈다. code 는 자기 category 의 것만 쓴다.
FACT_CODES = ("unsupported_claim", "source_mismatch", "time_distortion",
              "identity_inference", "material_omission", "exclusion_violation",
              "editorial_misuse")
COMPOSITION_CODES = ("summary_listing", "over_split", "role_overlap", "weak_transition",
                     "theme_contradiction", "style_mismatch")
ISSUE_CODES = {"fact": FACT_CODES, "composition": COMPOSITION_CODES}
RESOLUTIONS = ("auto_fix", "ask_user", "provide_context", "accept_limit")

# 구성 채점 — 검증 모델이 0 · 1 · 2 로, 항목마다 근거 위치를 단다. 사실(Q7) · 독자 시험(Q8)은 사람 몫
QUALITY_ITEMS = {
    "Q1": "장의 중심과 목적",
    "Q2": "기억의 통합",
    "Q3": "배치와 연결",
    "Q4": "선택",
    "Q5": "문장의 종합",
    "Q6": "목소리",
}
# 발언 나열 신호 — 장 안 문장이 이 정도면 Q2 · Q3 · Q5 의 2점을 코드가 1점으로 내린다 (목표치가 아니다)
LISTING_MIN_SENTENCES = 5
LISTING_ONE_TO_ONE = 0.6
LISTING_ORDER_KEPT = 0.85

# 독자에게 보일 문장에 섞이면 안 되는 안내문 말투 — 글 바깥에서 설명하는 문장
_META = re.compile(r"이\s?장(에서|은|는|에)|보여\s?(줍|드립)니다|보여\s?준다|이어집니다|마무리합니다"
                   r"|엮어\s?냅니다|다룹니다|다룬다|담았습니다")
# 인터뷰를 멈추거나 미루는 말 — 본문에 남으면 막는다 (같은 발언 속 사실은 써도 된다)
_STOP = re.compile(r"그만\s?할게요|그만\s?하자|오늘은\s?여기까지|다음에\s?(할게요|얘기)|나중에\s?할게요"
                   r"|넘어갈게요|말\s?안\s?할래요|얘기는\s?길어서|얘긴\s?(…|\.\.\.)")
# 질문에 대한 답의 흔적 — 문장 첫머리의 답 말
_ANSWER = re.compile(r"^\s*(아니요|아뇨|네[,.\s]|예[,.\s]|응[,.\s]|가끔요|글쎄요|그럼요|그렇죠|음\s?[…,.]|아[,.\s]\s*그거)")
# 직접 인용 — 원문 말투가 허용되는 부분. 문체 검사에서 뺀다
_QUOTE = re.compile(r"'[^']*'|\"[^\"]*\"|“[^”]*”|‘[^’]*’")

# 원문(사용자 발언)의 전언 · 불확실 표지 — 코드가 먼저 찾아 분석에 표시로 준다 (모델 판단을 돕는 표시일 뿐)
# 전언 — 남에게 들은 지난 일("울었대요", "업어 키웠다고 하더라고요"). 화자가 직접 받은 말("편지로 고맙다고
# 했어요")은 전언이 아니라 직접 들은 말(reported)이다 — 그 말의 내용은 사실 메모에 남아야 한다
_HEARD_SRC = re.compile(r"(?<!그러)대요|다고\s?(하더라고요|하데요|하더라|들었)|라고\s?(하더라고요|들었)"
                        r"|들었어요|그러더라고요|(?<!그)래요")
_REPORTED_SRC = re.compile(r"[다라자냐]고\s?(했어요|하셨어요|그러셨어요|말했어요)|그러대요|그러더라고요")
# 화자의 평가 · 생각 — "닮았다고 제가 그래요", "…라고 생각해요". 객관적 사실로 확정하지 않는다
_VIEW_SRC = re.compile(r"[다라]고\s?(제가|내가)\s?(그래요|그러죠|해요)|[다라]고\s?(생각해요|봐요|여겨요)")
# 부정 표현 — "쳐다보지도 않았어요", "안 왔어요", "못 갔어요", "별말 없었어요". 사실 메모에도 부정이 남아야 한다
_NEG_SRC = re.compile(r"지\s?(도|는)?\s?않|(?<![가-힣])안\s[가-힣]+(요|다|었|았|였|고|서)"
                      r"|(?<![가-힣])못\s?[가-힣]|없었|없어요|없고")
# 질문에 대한 답 말만인 첫머리("없어요." · "아니요,")는 사실의 부정이 아니다 — 부정 검사에서 뺀다
_ANSWER_HEAD = re.compile(r"^\s*(없어요|없습니다|아니요|아뇨|네|예)[.,!…]?\s*")
# 수 보존 검사는 시간 · 나이 · 기간 · 금액 · 넓이만 (횟수 · 인원 · 개수는 다른 사실로 드러나므로 보지 않는다)
NUMBER_UNITS = ("년", "살", "세", "개월", "달", "해", "시", "원", "평")
_NEG_FACT = re.compile(r"않|(?<![가-힣])안\s?[가-힣]|못|없|모르|아니")
# 망설임 · 의심 — "대단한 게 있나 싶은데". 화자의 생각(view)으로 남기거나 메모에 그 말이 있어야 한다
_DOUBT_SRC = re.compile(r"[나가]\s?싶|잘\s?모르겠|글쎄")
_DOUBT_FACT = re.compile(r"싶|망설|모르|글쎄|대단|의문")
# 직접 말한 감정 — 원문에 있으면 그 턴의 사실 메모에도 같은 무리의 말이 있어야 한다 (말을 바꿔도 된다)
EMOTION_GROUPS = {
    "좋음 · 기쁨": r"좋았|좋더|좋아|기뻤|기쁘|기뻐|즐거",
    "싫음": r"싫|괴로",
    "미안함": r"미안|죄송",
    "아쉬움 · 서운함": r"아쉬|서운|섭섭",
    "고마움": r"고마|고맙|감사",
    "뿌듯함 · 자부심": r"뿌듯|자랑|자부|해냈|했다\s?싶",
    "뭉클함 · 울음": r"뭉클|울었|울어|울지|눈물",
    "그리움": r"그리웠|그립|보고\s?싶",
    "슬픔": r"슬펐|슬프|슬퍼",
    "무서움": r"무서|겁",
    "힘듦": r"힘들|고생",
}
_UNCERTAIN_SRC = re.compile(r"쯤|인가|땐가|던가|했나|았나|었나|였나|[일을]\s?거예요|것\s?같|아마|년\?")
_CORRECTION_SRC = re.compile(r"다시\s?생각해\s?보니|고칠게요|잘못\s?말|정정|이\s?아니라|가\s?아니라")
# 본문의 전언 · 흐림 표지 — 들은 사실 · 대략의 사실을 단정으로 바꿨는지 볼 때
_HEARD_BODY = re.compile(r"다고|라고|자고|냐고|다며|라며|단다|대서|댔|들었|들은|전해|하더라")
_VIEW_BODY = re.compile(r"다고|라고|생각|싶|여긴|여겼|보인|같다|말하곤|그러곤|하곤")
_HEDGE_BODY = re.compile(r"쯤|무렵|것\s?같|듯|인지|였을|았을|었을|던가|인가|아마|정도|즈음|기억이|확실하지|약\s|대략|남짓|어림"
                         r"|모르겠|모른다|나\s?싶")
# 문단 첫머리의 시간 표지 — 시간을 거슬러 올라가는 문단에 있어야 한다
_TIME_MARK = re.compile(r"\d{2,4}년|년\s?(전|뒤|후)|무렵|시절|때|이듬해|그다음|그\s?뒤|그\s?후|지금|요즘"
                        r"|어릴|어렸|처음|그해|몇\s?년|오래전|그 전|그보다")

_KEY = re.compile(r"^ch-\d{1,2}$")
_FACT_ID = re.compile(r"^f\d{1,3}$")
_UNIT_ID = re.compile(r"^m\d{1,3}$")
_THREAD_ID = re.compile(r"^t\d{1,3}$")
_COMMON_HEAD = re.compile(r"^## 2\.[^\n]*\n(.*?)(?=^#{1,3} |\Z)", re.S | re.M)
_FENCE = re.compile(r"^(?:```|~~~)[^\n]*\n?", re.M)


class PipelineError(RuntimeError):
    """한 단계의 실패. kind 는 KINDS 중 하나 — 서로 다른 실패를 섞지 않는다."""

    def __init__(self, stage: str, kind: str, message: str, chapter_key: str | None = None):
        super().__init__(f"{stage}{'/' + chapter_key if chapter_key else ''} {kind} — {message}")
        self.stage, self.kind, self.message, self.chapter_key = stage, kind, message, chapter_key
        self.details: list[str] = []          # 한 번에 모은 문제 전부 (분석 계약 위반 등)
        self.warnings: list[str] = []

    def as_dict(self) -> dict:
        out = {"stage": self.stage, "chapter_key": self.chapter_key, "kind": self.kind, "message": self.message}
        if self.details:
            out["details"] = self.details
        return out


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
    """자서전_v4.md 의 「## 2. 공통 지침」 절 본문만. 다른 절은 장 구조와 부딪혀 싣지 않는다."""
    try:
        doc = COMMON_DOC.read_text(encoding="utf-8")
    except OSError as e:
        raise PipelineError("input", "input", f"공통 지침을 읽지 못했다: {COMMON_DOC.name} ({e})") from e
    m = _COMMON_HEAD.search(doc)
    body = _FENCE.sub("", m.group(1)).strip() if m else ""
    if not body:
        raise PipelineError("input", "input", f"{COMMON_DOC.name} 에 「## 2.」 절이 없거나 비었다")
    return body


def role_text(stage: str, file: str | None = None) -> str:
    path = ROLE_DIR / (file or ROLE_FILES[stage])
    try:
        text = _FENCE.sub("", path.read_text(encoding="utf-8")).strip()
    except OSError as e:
        raise PipelineError(stage, "input", f"지시문을 읽지 못했다: {path.name} ({e})") from e
    if not text:
        raise PipelineError(stage, "input", f"{path.name} 이 비었다")
    return text


def prompt(stage: str, file: str | None = None) -> str:
    """시스템 지시 = 공통 지침 + 이 역할의 지시문 하나. 원문은 여기에 넣지 않는다. file 은 같은 역할의 다른 판."""
    return common_rules() + "\n\n" + role_text(stage, file)


def edit_prompt(contract: str = "v5") -> str:
    """편집 지시문 — v5 는 ROLE_FILES 그대로, v6 는 문단 산문 + 근거 표현 계약(EDIT_V6_FILE)."""
    return prompt("edit", EDIT_V6_FILE if contract == "v6" else None)


def prompt_hashes() -> dict[str, str]:
    h = {s: "sha256:" + hashlib.sha256(prompt(s).encode("utf-8")).hexdigest()[:16] for s in STAGES}
    h["edit_v6"] = "sha256:" + hashlib.sha256(edit_prompt("v6").encode("utf-8")).hexdigest()[:16]
    return h


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


def turn_marks(data: dict) -> list[dict]:
    """
    원문 턴의 표지 — 사용자 발언에서 코드가 찾는다.

        heard      남에게 들은 지난 일 ("~대요", "~다고 하더라고요")
        reported   화자가 직접 받은 말 ("~다고 했어요", "그러대요") — 전언이 아니다, 말의 내용을 남긴다
        view       화자의 평가 · 생각 ("~다고 제가 그래요") — 객관적 사실로 확정하지 않는다
        uncertain  흐린 말투 ("~쯤", "~였나", "~일 거예요")
        correction 고쳐 말하는 말투 ("다시 생각해 보니", "~가 아니라")
        emotions   직접 말한 감정의 무리 (EMOTION_GROUPS)

    분석이 사실마다 source · certainty 를 정할 때 참고하는 **표시**다(판정이 아니다). 한 턴에
    들은 이야기와 직접 기억이 섞일 수 있어 턴 표시를 사실 값으로 그대로 옮기지 않는다.
    """
    out = []
    for u in data["utterances"]:
        s = u["elder"]
        mark = {"heard": bool(_HEARD_SRC.search(s)), "reported": bool(_REPORTED_SRC.search(s)),
                "view": bool(_VIEW_SRC.search(s)), "uncertain": bool(_UNCERTAIN_SRC.search(s)),
                "correction": bool(_CORRECTION_SRC.search(s)),
                "negation": bool(_NEG_SRC.search(_ANSWER_HEAD.sub("", s))), "doubt": bool(_DOUBT_SRC.search(s)),
                "numbers": [shown for shown, value in _fact_tokens(s) if _counts_as_number(shown, value)],
                "emotions": [g for g, rx in EMOTION_GROUPS.items() if re.search(rx, s)]}
        if any(mark.values()):
            out.append({"turn": u["turn"], **mark})
    return out


def source_texts(data: dict) -> dict[int, str]:
    return {u["turn"]: u["elder"] for u in data["utterances"]}


def source_asked(data: dict) -> dict[int, str]:
    return {u["turn"]: u["asked"] for u in data["utterances"]}


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


# ---------------------------------------------------------------- 사실 원장


def ledger(analysis: dict) -> dict[str, dict]:
    """사실 id → 사실. 본문 문장의 facts 는 이 안이어야 한다."""
    return {f["id"]: f for f in analysis.get("facts", [])}


def must_keep(analysis: dict) -> set[str]:
    """
    근거 없이 빠지면 안 되는 사실 — 분석이 keep 으로 표시한 것(중요한 사건 · 직접 말한 중요한
    감정 · 마지막 핵심 발언)과 정정된 사실. 빠뜨리려면 목차 omit · 편집 omitted 에 이유가 있어야 한다.
    """
    return ({f["id"] for f in analysis.get("facts", []) if f.get("keep")}
            | {c["fact"] for c in analysis.get("corrections", [])})


def fact_turns(fact_ids, book: dict[str, dict]) -> list[int]:
    return sorted({t for f in fact_ids or [] if f in book for t in book[f]["turns"]})


def expand_turns(chapters: list[dict], book: dict[str, dict], title: dict | None = None) -> None:
    """문장 · 제목의 facts → turns 를 코드가 붙인다 (모델이 turns 를 따로 쓰지 않는다)."""
    items = [title] if title else []
    for ch in chapters:
        items.append(ch["title"])
        items += [x for para in ch["paragraphs"] for x in para]
    for x in items:
        x["turns"] = fact_turns(x.get("facts"), book)


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


def _full_years(text: str) -> set[int]:
    """연도 끝 두 자리 → 네 자리 (30 이상은 1900년대). 시간 순서를 견줄 때만 쓴다."""
    return {(1900 if int(y) >= 30 else 2000) + int(y) for y in _years(text)}


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

    def items(self, v, where: str) -> list:
        if not isinstance(v, list):
            raise self.fail("format", f"{where} 가 목록이 아니다")
        return v

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

    def ids(self, v, allowed, where: str, *, nonempty: bool = False, what: str = "사실") -> list[str]:
        if not _str_list(v):
            raise self.fail("format", f"{where} 가 문자열 목록이 아니다")
        if nonempty and not v:
            raise self.fail("reference", f"{where} 가 비었다")
        bad = [x for x in v if x not in allowed]
        if bad:
            raise self.fail("reference", f"{where} {bad} — 없는 {what}")
        return v

    def text(self, v, where: str, *, nonempty: bool = True) -> str:
        if not isinstance(v, str) or (nonempty and not v.strip()):
            raise self.fail("format", f"{where} 가 비었거나 문자열이 아니다")
        return v

    def sentence(self, s, allowed: set[str], where: str, outside: str = "쓸 수 없는 사실") -> dict:
        """문장 항목 · 제목. supported 는 근거 사실이 있어야 하고, editorial 은 비어야 한다."""
        if not isinstance(s, dict):
            raise self.fail("format", f"{where} 가 객체가 아니다")
        self.text(s.get("text"), f"{where}.text")
        kind = s.get("kind")
        if kind not in ("supported", "editorial"):
            raise self.fail("format", f"{where}.kind={kind!r}")
        fs = s.get("facts")
        if not _str_list(fs):
            raise self.fail("format", f"{where}.facts 가 문자열 목록이 아니다")
        if kind == "supported" and not fs:
            raise self.fail("reference", f"{where} 는 supported 인데 facts 가 비었다")
        if kind == "editorial" and fs:
            raise self.fail("reference", f"{where} 는 editorial 인데 facts 가 있다 — 사실이 있으면 supported")
        bad = [f for f in fs if f not in allowed]
        if bad:
            raise self.fail("reference", f"{where}.facts {bad} — {outside}")
        return s

    def notes(self, v, allowed: set[str], where: str, outside: str = "쓸 수 없는 사실") -> None:
        for i, n in enumerate(self.items(v, where)):
            if not isinstance(n, dict):
                raise self.fail("format", f"{where}[{i}] 가 객체가 아니다")
            self.text(n.get("issue"), f"{where}[{i}].issue")
            bad = [f for f in (n.get("facts") or []) if f not in allowed]
            if not _str_list(n.get("facts", [])) or bad:
                raise self.fail("reference", f"{where}[{i}].facts {bad} — {outside}")

    def paragraphs(self, v, allowed: set[str], where: str, outside: str = "쓸 수 없는 사실") -> list:
        if not isinstance(v, list) or not v:
            raise self.fail("format", f"{where}.paragraphs 가 비었거나 목록이 아니다")
        for p, para in enumerate(v):
            if not isinstance(para, list) or not para:
                raise self.fail("format", f"{where}/p{p} 가 비었거나 목록이 아니다")
            for s, sent in enumerate(para):
                self.sentence(sent, allowed, f"{where}/p{p}/s{s}", outside)
        return v


# ---------------------------------------------------------------- ① 분석 검사


KEEP_ERROR_RATIO = 0.5          # keep 이 사실의 절반을 넘으면 「핵심」 표시가 아니다 — 실패
KEEP_WARN_RATIO = 0.3
UNIT_SPAN_YEARS = 15            # 한 기억 단위의 연도 폭이 이만큼 넘고 사실이 많으면 여러 시기를 묶은 것인지 본다
UNIT_SPAN_FACTS = 6
# 원문에 없으면 주제 이름으로 단정하지 않는 말 — 감정 · 희생 서사 (편집적 해석이 화자의 사실처럼 되지 않게)
_LOADED_THEME = re.compile(r"그리움|그리워|희생|헌신|치열|사랑|한평생|보람|감사|숙명|운명|눈물")
_REPORTED = re.compile(r"다고|라고|자고|냐고|대요|들음|들었")


def _year_forms(text: str) -> set[str]:
    return _years(text or "")


FACT_SOURCE_MIN_OVERLAP = 0.08  # 사실 메모의 글자 조각 가운데 근거 턴 **화자 발언**에 있는 비율 — 실측 정상 0.09 이상 · 엉뚱한 턴 0.05
# 질문에 대한 짧은 답만 — 이것만으로는 질문의 내용을 사실로 세울 수 없다(공통 지침 3)
_BARE_ANSWER = re.compile(r"(네|예|응|그렇죠|그럼요|맞아요|그래요|그랬죠|아마도요)[.!…\s]*")


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"[^가-힣0-9]", "", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1)}


def analysis_diagnostics(out: dict, T: set[int], marks: list[dict] | None = None,
                         texts: dict[int, str] | None = None, asked: dict[int, str] | None = None
                         ) -> tuple[list[str], list[str]]:
    """
    모양 검사를 통과한 분석 출력의 뜻 검사 — **문제를 모두 모아** (errors, warnings) 로 돌려준다.
    errors 가 하나라도 있으면 check_analysis 가 실패로 멈춘다(다음 단계로 넘기지 않는다). 한 번에 여러
    문제가 있어도 첫 문제에서 멈추지 않고 전체 진단을 남긴다.

        errors   (보호 항목) 빼 달라고 한 턴의 사용 · 빠진 턴 · 사실 ↔ 근거 턴 불일치 · 사실의 단위 중복 ·
                 단위 없는 사실 · 정정 오류(정정 전 값이 별개 사실 · 유효 사실에 정정 전 값 · 불명확한 정정) ·
                 출처의 명백한 오분류(들은 이야기 표지 턴에 heard 없음 · 평가 표지 턴에 view 없음)
        warnings 메모 뉘앙스 — 수 · 기간 · 부정 · 감정 · 직접 받은 말 · 망설임이 메모에 없음(원문 턴이 뒤 단계에
                 함께 가므로 실패로 막지 않는다) · keep 과다 · 불확실 표지인데 stated · 정정 표지인데 기록 없음 ·
                 큰 기억 단위 · 무관한 묶음 · 원문에 없는 감정 · 희생 말의 주제 · 시점이 여럿인 사실 · 주제와 방향의 앞뒤
    """
    errors: list[str] = []
    warnings: list[str] = []
    asked = asked or {}
    gone = excluded_turns(out)
    facts = {f["id"]: f for f in out["facts"]}

    # 빼 달라고 한 턴 · 빠진 턴
    covered: set[int] = set()
    for f in facts.values():
        bad = sorted(set(f["turns"]) & gone)
        if bad:
            errors.append(f"{f['id']}.turns {bad} — 빼 달라고 한 턴을 사실 근거로 씀")
        covered |= set(f["turns"])
    left = {t for x in out["not_in_facts"] for t in x["turns"]}
    missing = sorted(T - covered - left - gone)
    if missing:
        errors.append(f"턴 {missing} 이 사실 · not_in_facts · exclusions 어디에도 없다")

    # 사실 ↔ 근거 턴 대응 (보조 검사) — **화자의 발언(elder)만** 근거로 센다. AI 질문(asked)은 지시대상 · 문맥을
    # 알아보는 데만 쓰고, 질문에만 있는 내용은 사실의 근거가 아니다. 메모가 그 턴 발언과 글자 조각을 거의 나누지
    # 않고 발언의 수 표현도 담지 않으면 다른 턴을 가리켰거나 질문 · 상상에서 온 사실이다.
    # 글자가 닮았다고 뜻이 맞는 것은 아니다 — 뜻의 대조는 검증 단계와 사람이 한다.
    for f in facts.values() if texts else []:
        said = " ".join(texts.get(t, "") for t in f["turns"])
        if all(_BARE_ANSWER.fullmatch(texts.get(t, "").strip()) for t in f["turns"]):
            errors.append(f"사실 {f['id']} 의 근거 턴 {f['turns']} 은 질문에 대한 짧은 답뿐이다 — 질문 내용을 사실로 세우지 않는다")
            continue
        fb = _bigrams(f["text"])
        if len(fb) < 3:
            continue
        overlap = len(fb & _bigrams(said)) / len(fb)
        memo = re.sub(r"\s+", "", f["text"] + " " + f["time"])
        memo_digits = set(re.findall(r"\d+", f["text"] + " " + f["time"]))
        numbers = any(_num_supported(v, memo, memo_digits) for _, v in _fact_tokens(said))
        if overlap < FACT_SOURCE_MIN_OVERLAP and not numbers:
            errors.append(f"사실 {f['id']} 메모가 근거 턴 {f['turns']} 의 화자 발언과 맞지 않는다 — 다른 턴을 가리켰거나 "
                          "질문에만 있는 내용 · 원문에 없는 사실")

    # 기억 단위 — 사실은 정확히 한 주 기억 단위에. 같은 사람 · 물건이 여러 단위에 나오면 끈으로 잇는다
    home: dict[str, list[str]] = {}
    for u in out["units"]:
        for fid in u["facts"]:
            home.setdefault(fid, []).append(u["id"])
    for fid in sorted(home, key=lambda x: int(x[1:])):
        if len(home[fid]) > 1:
            errors.append(f"사실 {fid} 이 기억 단위 {home[fid]} 에 함께 있다 — 주 기억 단위 하나에만, 이어지는 것은 threads 로")
    lost = sorted(set(facts) - set(home), key=lambda x: int(x[1:]))
    if lost:
        errors.append(f"사실 {lost} 이 어느 기억 단위에도 없다")
    for u in out["units"]:
        ys = {y for fid in u["facts"] if fid in facts for y in _full_years(facts[fid]["time"] + " " + facts[fid]["text"])}
        if len(u["facts"]) >= UNIT_SPAN_FACTS and ys and max(ys) - min(ys) > UNIT_SPAN_YEARS:
            warnings.append(f"기억 단위 {u['id']}({u['name']}) 가 {min(ys)}~{max(ys)}년 사실 {len(u['facts'])}개를 묶었다 — "
                            "여러 시기의 다른 이야기를 한 단위로 묶었는지 본다(같은 사람 · 물건은 threads 로)")
    threaded = {uid for th in out["threads"] for uid in th["units"]}
    for u in out["units"]:
        fs = [facts[fid] for fid in u["facts"] if fid in facts]
        yrs = [_full_years(f["time"] + " " + f["text"]) for f in fs]
        dated = [y for y in yrs if y]
        if (len(fs) >= 2 and u["id"] not in threaded and len(dated) >= 2
                and not any(a & b for i, a in enumerate(dated) for b in dated[i + 1:])):
            warnings.append(f"기억 단위 {u['id']}({u['name']}) 의 사실들이 시기로도 끈으로도 이어지지 않는다 — "
                            "다른 사람의 다른 일을 한 묶음으로 만들었는지 본다")
    singles = sum(1 for u in out["units"] if len(u["facts"]) == 1)
    if len(out["units"]) > 3 and singles / len(out["units"]) >= 0.7:
        warnings.append(f"기억 단위 {len(out['units'])}개 중 {singles}개가 사실 하나 — 기억을 묶는 판단을 다시 본다")

    # 정정 — 하나의 정정된 유효 사실(정정 뒤 값 · 정정 전 · 뒤 턴 모두)과 정정 이력(before)만. 추측해서 고치지 않는다
    corrected: set[str] = set()
    for i, x in enumerate(out["corrections"]):
        at = f"corrections[{i}]"
        fid, ts = x["fact"], set(x["turns"])
        corrected.add(fid)
        f = facts.get(fid)
        if f is None:
            errors.append(f"{at}.fact {fid!r} — 원장에 없는 사실")
            continue
        if len(ts) < 2 or ts - set(f["turns"]):
            errors.append(f"{at}.turns {sorted(ts)} — 정정 전 · 뒤 턴이 모두 사실 {fid} 의 turns 에 있어야 한다")
        before, after = x.get("before", "").strip(), x.get("after", "").strip()
        clear = bool(before and after and _norm(before) != _norm(after))
        if not clear:
            errors.append(f"{at} — 정정 이력 before · after 가 없거나 같다: 정정 전 · 뒤 값을 적거나, 불명확한 정정이면 "
                          "corrections 에 넣지 않고 unclear 로")
        b_years, a_years = (_year_forms(before), _year_forms(after)) if clear else (set(), set())
        if clear:
            own = f["time"] + " " + f["text"]
            if b_years - a_years and _year_forms(own) & (b_years - a_years):
                errors.append(f"{at} — 유효 사실 {fid} 에 정정 전 값({before})이 남아 있다")
            if a_years and not _year_forms(own) & a_years:
                errors.append(f"{at} — 유효 사실 {fid} 에 정정 뒤 값({after})이 없다")
        # 정정 턴에 시점을 가진 사실이 따로 있으면 — 정정 전 값이 별개 사실로 남았거나, 유효 사실이 둘로 나뉜 것
        for g in facts.values():
            if g["id"] == fid or not set(g["turns"]) & ts:
                continue
            g_years = _year_forms(g["time"] + " " + g["text"])
            if (b_years - a_years) & g_years or (clear and not b_years and _norm(before) in _norm(g["text"])):
                errors.append(f"{at} — 정정 전 값({before})을 별개 사실 {g['id']} 로 남겼다: 정정 이력(before)으로만 둔다")
            elif g_years:
                errors.append(f"{at} — 정정 턴의 다른 사실 {g['id']} 에도 시점({sorted(g_years)})이 있다: "
                              f"정정 전 사실({fid})과 정정 뒤 사실이 나뉘었다 — 정정된 유효 사실 하나로")
    for fid, f in facts.items():
        years = _years(f["time"])
        if len(years) > 1 and fid not in corrected:
            warnings.append(f"사실 {fid} 의 시점이 여럿 {sorted(years)} — 별개의 일을 합쳤는지 본다")
    in_corr = {t for x in out["corrections"] for t in x["turns"]}
    for m in marks or []:
        if m.get("correction") and m["turn"] not in in_corr:
            warnings.append(f"턴 {m['turn']} 에 정정 말투가 있는데 정정 기록이 없다 — 검토 대상(추측해서 고치지 않는다)")

    # 들은 이야기 · 흐린 기억 — 한 발언에 섞이면 사실 수준에서 나눈다
    by_turn: dict[int, list[dict]] = {}
    for f in facts.values():
        for t in f["turns"]:
            by_turn.setdefault(t, []).append(f)
    # 정정 턴(정정 전 값이 원문에 있다) · 빼 달라고 한 턴 · 일부 제외 턴은 수 · 부정 · 망설임 대조에서 뺀다
    skip = in_corr | gone | {t for x in out["exclusions"] if x.get("mode") == "partial" for t in x.get("turns", [])}
    for m in marks or []:
        fs = by_turn.get(m["turn"], [])
        if not fs:
            continue
        memo = " ".join(f["text"] for f in fs)
        if m["heard"] and not any(f["source"] == "heard" for f in fs):
            errors.append(f"턴 {m['turn']} 에 남에게 들은 이야기 말투가 있는데 그 턴에 heard 사실이 없다 — "
                          "들은 부분과 직접 기억을 사실로 나눈다")
        if m["turn"] in skip:
            continue
        if m.get("reported") and not m["heard"] and not any(_REPORTED.search(f["text"]) for f in fs):
            warnings.append(f"턴 {m['turn']} 에서 화자가 직접 받은 말(…다고 했어요)의 내용이 사실 메모에 없다 — "
                          "전언은 아니지만 그 말은 남긴다(source self)")
        if m.get("negation") and not _NEG_FACT.search(memo):
            warnings.append(f"턴 {m['turn']} 원문의 부정 표현(…지 않았다 · 안 · 못 · 없었다)이 사실 메모에 없다")
        if m.get("doubt") and not any(f["source"] == "view" or _DOUBT_FACT.search(f["text"]) for f in fs):
            warnings.append(f"턴 {m['turn']} 원문의 망설임 · 의심(…나 싶다)이 사실 메모에 없다 — 화자의 생각(view)으로 남긴다")
        support = re.sub(r"\s+", "", memo + " " + " ".join(f["time"] for f in fs))
        digits = set(re.findall(r"\d+", memo + " " + " ".join(f["time"] for f in fs)))
        miss = [shown for shown, value in _fact_tokens(texts.get(m["turn"], "") if texts else "")
                if _counts_as_number(shown, value) and not _num_supported(value, support, digits)]
        if miss:
            warnings.append(f"턴 {m['turn']} 원문의 수 · 기간 표현 {miss} 이 사실 메모에 없다 — 대략의 표현도 그대로 남긴다")
        if m.get("view") and not any(f["source"] == "view" for f in fs):
            errors.append(f"턴 {m['turn']} 은 화자의 평가 · 생각(…다고 제가 그래요)인데 view 사실이 없다 — "
                          "객관적 사실로 확정하지 않는다")
        lost = [g for g in m.get("emotions", []) if not re.search(EMOTION_GROUPS[g], memo)]
        if lost:
            warnings.append(f"턴 {m['turn']} 원문의 감정 말 {lost} 이 그 턴의 사실 메모에 없다 — "
                          "복합적인 감정(지난날 싫었던 것 · 지금 떠오르는 것)은 사실을 나눠서라도 모두 남긴다")
        if m["uncertain"] and m["turn"] not in in_corr and all(f["certainty"] == "stated" for f in fs):
            warnings.append(f"턴 {m['turn']} 에 불확실 표지가 있는데 모든 사실이 stated")

    # keep — 핵심 사실에만. 일반 사실을 본문에 쓸지는 목차가 정한다
    keeps = sum(1 for f in facts.values() if f["keep"])
    if facts and keeps / len(facts) > KEEP_ERROR_RATIO:
        warnings.append(f"keep 이 사실 {len(facts)}개 중 {keeps}개 — 핵심 사실에만 둔다(본문 사용 여부는 목차가 정한다)")
    elif facts and keeps / len(facts) > KEEP_WARN_RATIO:
        warnings.append(f"keep 이 사실 {len(facts)}개 중 {keeps}개 — 핵심 사실인지 다시 본다")

    # 주제 — 원문 근거가 있는 편집적 해석은 되지만, 원문에 없는 감정 · 희생 말을 화자의 것으로 단정하지 않는다
    for t in out["themes"] if texts is not None else []:
        words = set(_LOADED_THEME.findall(t["theme"]))
        said = " ".join(texts.get(x, "") for x in t["supporting"])
        unsaid = sorted(w for w in words if w not in said)
        if unsaid:
            warnings.append(f"주제 「{t['theme']}」의 {unsaid} 는 근거 턴 원문에 없는 말 — 화자의 감정 · 서사로 단정하지 않는다")
    d = out["direction"]
    clear = [t["theme"] for t in out["themes"] if t["strength"] == "clear"]
    if d["neutral"] and d["theme"].strip():
        warnings.append("direction.neutral=true 인데 theme 을 정했다")
    if not d["neutral"] and not clear:
        warnings.append("clear 인 주제가 없는데 direction.neutral=false")
    return errors, warnings


_STRIP_YEAR = r"(?<!\d)(?:19|20)?{yy}\s?년(?:\s?(?:쯤|경|께|무렵|이었을\s?것|일\s?것))?(?:에는|에|엔)?\s?"


def normalize_corrections(out: dict) -> list[dict]:
    """
    **명시적인 정정만** 코드가 하나의 유효 사실로 정리한다(제자리에서 고친다). 돌려주는 것은 기록.

    조건 — 모두 맞을 때만:
        정정 기록에 before · after 가 있고 서로 다르며, turns 가 둘 이상이고, before 에 연도가 있다
        정정 턴의 사실 가운데 after 의 연도를 가진 사실이 **정확히 하나**(A)
        before 의 연도를 가진 사실이 **하나 이하**(B, A 와 다름)
    하는 일:
        A 를 유효 사실로 — 정정 턴을 모두 A 의 turns 에 붙이고, 정정 기록이 A 를 가리키게 한다
        B 에서는 **정정 전 연도만** 지운다(시점 · 메모의 그 연도 표현). 나머지 내용(장소 · 일)은 남긴다.
        B 의 시점이 비면 확실성은 그 연도에 걸린 것이었으므로 stated 로 둔다. 메모가 비면 B 를 없앤다
    그 밖의 모양(after 사실이 없거나 여럿, before 사실이 여럿, 연도 없는 정정)은 **고치지 않는다** —
    analysis_diagnostics 가 실패로 멈춘다. 추측해서 적용하지 않는다. 특정 자료의 값을 코드에 두지 않는다.
    """
    log = []
    facts = {f["id"]: f for f in out["facts"]}
    for i, c in enumerate(out["corrections"]):
        before, after = (c.get("before") or "").strip(), (c.get("after") or "").strip()
        ts = set(c.get("turns") or [])
        b_years, a_years = _years(before) - _years(after), _years(after)
        if not before or not after or _norm(before) == _norm(after) or len(ts) < 2 or not b_years or not a_years:
            log.append({"correction": i, "applied": False, "why": "정정 전 · 뒤 연도가 분명하지 않다 — 고치지 않음"})
            continue
        near = [f for f in out["facts"] if set(f["turns"]) & ts]
        A = [f for f in near if _years(f["time"] + " " + f["text"]) & a_years]
        B = [f for f in near if _years(f["time"] + " " + f["text"]) & b_years and f not in A]
        if len(A) != 1 or len(B) > 1:
            log.append({"correction": i, "applied": False,
                        "why": f"정정 뒤 값을 가진 사실 {[f['id'] for f in A]} · 정정 전 값 {[f['id'] for f in B]} — 하나로 정할 수 없다"})
            continue
        a = A[0]
        rec = {"correction": i, "applied": True, "changed": False, "valid_fact": a["id"], "was": c["fact"],
               "turns_added": sorted(ts - set(a["turns"])), "stripped": None, "removed": None}
        a["turns"] = sorted(set(a["turns"]) | ts)
        c["fact"] = a["id"]
        if B:
            b = B[0]
            for yy in b_years:
                rx = _STRIP_YEAR.format(yy=yy)
                b["time"] = re.sub(rx, "", b["time"]).strip(" ,·")
                b["text"] = re.sub(rx, "", b["text"]).strip()
            if not _years(b["time"]) and b["certainty"] != "stated" and not b["time"]:
                b["certainty"] = "stated"
            rec["stripped"] = b["id"]
            if not _norm(b["text"]):
                out["facts"] = [f for f in out["facts"] if f["id"] != b["id"]]
                for u in out["units"]:
                    u["facts"] = [x for x in u["facts"] if x != b["id"]]
                rec["removed"] = b["id"]
        rec["changed"] = bool(rec["turns_added"] or rec["stripped"] or rec["was"] != a["id"])
        if not rec["changed"]:
            rec.update(applied=False, why="이미 하나의 유효 사실로 정정돼 있다 — 바꾸지 않음")
        log.append(rec)
        facts = {f["id"]: f for f in out["facts"]}
    return log


def check_analysis(out, T: set[int], marks: list[dict] | None = None,
                   texts: dict[int, str] | None = None, asked: dict[int, str] | None = None) -> tuple[str, list[str]]:
    """
    사실 원장(facts)과 기억 단위(units)를 나눠 본다.

        facts   원문에서 나온 사실 하나하나 — 무엇 · 언제 · 직접 겪음/들음 · 확실/대략/불확실.
                사실마다 문장 하나를 쓰라는 뜻이 아니다. 서로 다른 해의 방문 · 서로 다른 사람의
                일은 서로 다른 사실이다
        units   독자가 하나의 이야기로 읽을 기억 덩어리 — 사실 여럿을 묶는다. 모든 사실은 정확히
                한 주 기억 단위에 든다
        corrections  정정된 유효 사실 하나(정정 뒤 값, 정정 전 · 뒤 턴 모두) + 정정 이력 before · after

    모양이 틀리면 바로 멈추고, 모양이 맞으면 analysis_diagnostics 로 뜻의 문제를 모두 모은 뒤
    하나라도 있으면 그 전체를 details 에 담아 멈춘다.
    """
    c = _Check("analysis")
    if isinstance(out, dict):
        out.pop("normalized", None)                    # 코드가 붙이는 기록 — 모델 출력이 아니다
    out = c.obj(out, ("status", "facts", "units", "threads", "people", "corrections", "themes",
                      "direction", "exclusions", "not_in_facts", "unclear", "missing_context"))
    status = out["status"]
    if status not in ("ready", INSUFFICIENT, NEEDS_CONTEXT):
        raise c.fail("format", f"status={status!r}")
    for k in ("facts", "units", "threads", "people", "corrections", "themes", "exclusions",
              "not_in_facts", "unclear"):
        c.items(out[k], k)
    if not _str_list(out["missing_context"]):
        raise c.fail("format", "missing_context 가 문자열 목록이 아니다")
    if status != "ready":
        return status, c.warnings
    if not out["facts"] or not out["units"]:
        raise c.fail("format", "ready 인데 facts · units 가 비었다")

    # ---- 모양 (틀리면 바로 멈춘다)
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
    for i, x in enumerate(out["not_in_facts"]):
        if not isinstance(x, dict):
            raise c.fail("format", f"not_in_facts[{i}] 가 객체가 아니다")
        c.turns(x.get("turns"), T, f"not_in_facts[{i}]")
        c.text(x.get("reason"), f"not_in_facts[{i}].reason")
    ids: set[str] = set()
    for i, f in enumerate(out["facts"]):
        at = f"facts[{i}]"
        if not isinstance(f, dict):
            raise c.fail("format", f"{at} 가 객체가 아니다")
        fid = f.get("id")
        if not isinstance(fid, str) or not _FACT_ID.match(fid):
            raise c.fail("format", f"{at}.id={fid!r} — f<숫자>")
        if fid in ids:
            raise c.fail("reference", f"사실 id {fid} 가 겹친다")
        ids.add(fid)
        c.turns(f.get("turns"), T, fid, nonempty=True)
        c.text(f.get("text"), f"{fid}.text")
        if not isinstance(f.get("time"), str):
            raise c.fail("format", f"{fid}.time 이 문자열이 아니다")
        if f.get("source") not in SOURCES:
            raise c.fail("format", f"{fid}.source={f.get('source')!r} — self · heard · view")
        if f.get("certainty") not in CERTAINTIES:
            raise c.fail("format", f"{fid}.certainty={f.get('certainty')!r} — stated · approx · uncertain")
        if not isinstance(f.get("keep"), bool):
            raise c.fail("format", f"{fid}.keep 이 참/거짓이 아니다")
    for i, x in enumerate(out["corrections"]):
        at = f"corrections[{i}]"
        if not isinstance(x, dict) or not isinstance(x.get("fact"), str):
            raise c.fail("format", f"{at} 모양이 다르다")
        c.turns(x.get("turns"), T, at, nonempty=True)
        for k in ("before", "after", "note"):
            if not isinstance(x.get(k, ""), str):
                raise c.fail("format", f"{at}.{k} 가 문자열이 아니다")
    unit_ids: set[str] = set()
    for i, u in enumerate(out["units"]):
        at = f"units[{i}]"
        if not isinstance(u, dict):
            raise c.fail("format", f"{at} 가 객체가 아니다")
        uid = u.get("id")
        if not isinstance(uid, str) or not _UNIT_ID.match(uid) or uid in unit_ids:
            raise c.fail("format", f"{at}.id={uid!r} — m<숫자>, 겹치지 않게")
        unit_ids.add(uid)
        c.text(u.get("name"), f"{uid}.name")
        c.ids(u.get("facts"), ids, f"{uid}.facts", nonempty=True)
        if not isinstance(u.get("time"), str):
            raise c.fail("format", f"{uid}.time 이 문자열이 아니다")
        if u.get("weight") not in WEIGHTS:
            raise c.fail("format", f"{uid}.weight={u.get('weight')!r}")
    seen: set[str] = set()
    for i, th in enumerate(out["threads"]):
        at = f"threads[{i}]"
        if not isinstance(th, dict):
            raise c.fail("format", f"{at} 가 객체가 아니다")
        tid = th.get("id")
        if not isinstance(tid, str) or not _THREAD_ID.match(tid) or tid in seen:
            raise c.fail("format", f"{at}.id={tid!r} — t<숫자>, 겹치지 않게")
        seen.add(tid)
        c.text(th.get("name"), f"{tid}.name")
        if th.get("kind") not in THREAD_KINDS:
            raise c.fail("format", f"{tid}.kind={th.get('kind')!r}")
        c.ids(th.get("units"), unit_ids, f"{tid}.units", nonempty=True, what="기억 단위")
        c.turns(th.get("link_turns", []), T - gone, f"{tid}.link", outside="입력에 없거나 빼 달라고 한 턴")
    for i, p in enumerate(out["people"]):
        if not isinstance(p, dict):
            raise c.fail("format", f"people[{i}] 가 객체가 아니다")
        c.text(p.get("name"), f"people[{i}].name")
        c.text(p.get("relation"), f"people[{i}].relation", nonempty=False)
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
    for i, n in enumerate(out["unclear"]):
        if not isinstance(n, dict):
            raise c.fail("format", f"unclear[{i}] 가 객체가 아니다")
        c.text(n.get("issue"), f"unclear[{i}].issue")
        c.turns(n.get("turns"), T, f"unclear[{i}]")

    # ---- 명시적 정정은 코드가 하나의 유효 사실로 정리한 뒤 뜻을 본다 (기록은 normalized 에)
    out["normalized"] = normalize_corrections(out)
    for n in out["normalized"]:
        if n.get("changed"):
            c.warnings.append(f"정정 정규화(코드가 바꿈) — 유효 사실 {n['valid_fact']}(턴 {n['turns_added']} 붙임)"
                              + (f", {n['stripped']} 에서 정정 전 연도를 지움" if n["stripped"] else ""))

    # ---- 뜻 (전부 모은 뒤, 하나라도 있으면 멈춘다)
    errors, warnings = analysis_diagnostics(out, T, marks, texts, asked)
    c.warnings += warnings
    if errors:
        e = c.fail("reference", f"분석 계약 위반 {len(errors)}건 — " + " | ".join(errors)[:600])
        e.details, e.warnings = errors, c.warnings
        raise e
    return status, c.warnings


# ---------------------------------------------------------------- ② 목차(책 설계도) 검사


def plan_facts(chapter: dict) -> list[str]:
    """장 설계도의 문단 계획에 놓인 사실 — 문단 순서대로, 겹치지 않게."""
    out: list[str] = []
    for para in chapter.get("paragraphs", []):
        for f in list(para.get("facts") or []) + list(para.get("brief") or []):
            if f not in out:
                out.append(f)
    return out


def plan_core(outline_out: dict) -> dict[str, str]:
    """
    문단 계획의 핵심 사실(core) → 그 문단 위치(ch-1/p1). core 는 문단이 꼭 담아야 할 사실이고, 나머지
    facts · brief 는 흐름에 맞게 골라 쓰는 보조 사실이다. core 를 적지 않은 목차는 빈 dict(구분 없음).
    """
    out: dict[str, str] = {}
    for ch in outline_out.get("chapters", []):
        for p, para in enumerate(ch.get("paragraphs", [])):
            for f in para.get("core") or []:
                out.setdefault(f, f"{ch['chapter_key']}/p{p}")
    return out


def plan_coverage(chapters: list[dict], outline_out: dict) -> dict:
    """목차가 계획한 사실 가운데 원고가 근거로 단 것 — 핵심 · 보조를 따로. 판정이 아니라 지표다."""
    cited = {f for _, _, _, x in _sentences(chapters) for f in (x.get("facts") or [])}
    planned = [f for ch in outline_out.get("chapters", []) for f in plan_facts(ch)]
    core = plan_core(outline_out)
    support = [f for f in planned if f not in core]
    return {"planned": len(planned), "planned_used": sum(f in cited for f in planned),
            "core": len(core), "core_used": sum(f in cited for f in core),
            "core_missing": sorted((f for f in core if f not in cited), key=_fid),
            "support": len(support), "support_used": sum(f in cited for f in support)}


def _fid(f: str) -> int:
    return int(f[1:]) if f[1:].isdigit() else 0


def _para_years(fact_ids, book: dict[str, dict]) -> set[int]:
    return {y for f in fact_ids if f in book for y in _full_years(book[f].get("time", ""))}


OMIT_UNIT_RATIO = 2 / 3     # 장이 고른 기억 단위의 사실을 이 비율 넘게 빼면 일괄 생략 경고 (문단 · 문장 수를 강제하지 않는다)


def check_outline(out, analysis: dict, T: set[int], focus: str | None = None) -> tuple[str, list[str]]:
    """
    책 설계도. 장마다 중심(center) · 핵심 경험(experience) · 문단 계획 · 시간 재배치 이유.

    **모든 발언을 넣지 않는다.** 원장의 모든 사실은 어느 문단 계획(facts · brief)이나 omit 중
    한 곳에 있어야 하고, omit 에는 이유가 있어야 한다 — 쓴 것 · 줄인 것 · 뺀 것을 거슬러 갈 수
    있게. 근거 없이 빠지면 안 되는 사실(must_keep)을 빼면 경고로 남겨 편집 · 사람이 본다.
    focus 가 있으면(한 장 시험) 장은 정확히 하나다.
    """
    c = _Check("outline")
    out = c.obj(out, ("status", "book", "chapters", "omit", "missing_context"))
    status = out["status"]
    if status not in ("ready", NEEDS_CONTEXT):
        raise c.fail("format", f"status={status!r}")
    if not _str_list(out["missing_context"]):
        raise c.fail("format", "missing_context 가 문자열 목록이 아니다")
    if status != "ready":
        return status, c.warnings

    book = ledger(analysis)
    units = {u["id"]: u for u in analysis.get("units", [])}
    allowed = set(book)
    b = out["book"]
    if not isinstance(b, dict):
        raise c.fail("format", "book 이 객체가 아니다")
    c.sentence(b.get("title"), allowed, "book.title")
    c.text(b.get("center"), "book.center")
    c.text(b.get("flow", ""), "book.flow", nonempty=False)
    opening = c.ids(b.get("opening_facts", []), allowed, "book.opening_facts")
    closing = c.ids(b.get("closing_facts"), allowed, "book.closing_facts", nonempty=True)

    chapters = out["chapters"]
    if not isinstance(chapters, list) or not chapters:
        raise c.fail("format", "chapters 가 비었다 — 0장")
    if focus and len(chapters) != 1:
        raise c.fail("chapter_limit", f"{len(chapters)}장 — 한 장 시험(focus)은 정확히 1장")
    if len(chapters) > MAX_CHAPTERS:
        raise c.fail("chapter_limit", f"{len(chapters)}장 — 상한 {MAX_CHAPTERS}장 (자르지 않는다)")

    used: dict[str, str] = {}
    keys: list[str] = []
    centers: list[str] = []
    for i, ch in enumerate(chapters):
        at = f"chapters[{i}]"
        if not isinstance(ch, dict):
            raise c.fail("format", f"{at} 가 객체가 아니다")
        key = ch.get("chapter_key")
        if not isinstance(key, str) or not _KEY.match(key) or key in keys:
            raise c.fail("format", f"{at}.chapter_key={key!r} — ch-<숫자>, 겹치지 않게")
        keys.append(key)
        c.sentence(ch.get("title"), allowed, f"{key}.title")
        centers.append(c.text(ch.get("center"), f"{key}.center").strip())
        c.text(ch.get("experience"), f"{key}.experience")
        c.ids(ch.get("units"), units, f"{key}.units", nonempty=True, what="기억 단위")
        paras = ch.get("paragraphs")
        if not isinstance(paras, list) or not paras:
            raise c.fail("format", f"{key}.paragraphs 가 비었다 — 문단 계획이 없다")
        for p, para in enumerate(paras):
            pat = f"{key}/p{p}"
            if not isinstance(para, dict):
                raise c.fail("format", f"{pat} 가 객체가 아니다")
            c.text(para.get("role"), f"{pat}.role")
            fs = c.ids(para.get("facts"), allowed, f"{pat}.facts", nonempty=True)
            if "core" in para:
                core = c.ids(para.get("core"), allowed, f"{pat}.core")
                stray = [f for f in core if f not in (para.get("facts") or [])]
                if stray:
                    raise c.fail("format", f"{pat}.core {stray} — 핵심 사실은 그 문단 facts 안에서만 고른다(brief 는 보조)")
            fs = fs + c.ids(para.get("brief", []), allowed, f"{pat}.brief")
            if not isinstance(para.get("time", ""), str):
                raise c.fail("format", f"{pat}.time 이 문자열이 아니다")
            for f in fs:
                if f in used and used[f] != key:
                    c.warnings.append(f"사실 {f} 을 {used[f]} 와 {key} 가 함께 쓴다 — 일부러 다시 떠올리는지 본다")
                used.setdefault(f, key)
        reorder = c.items(ch.get("reorder", []), f"{key}.reorder")
        moved = set()
        for j, r in enumerate(reorder):
            if not isinstance(r, dict) or not _is_int(r.get("paragraph")) or not 0 <= r["paragraph"] < len(paras):
                raise c.fail("format", f"{key}.reorder[{j}].paragraph — 문단 번호가 아니다")
            c.text(r.get("reason"), f"{key}.reorder[{j}].reason")
            c.ids(r.get("facts", []), allowed, f"{key}.reorder[{j}].facts")
            moved.add(r["paragraph"])
        # 시간을 거슬러 올라가는 문단 — 재배치 이유가 있어야 한다
        prev_max = None
        for p, para in enumerate(paras):
            ys = _para_years(list(para["facts"]) + list(para.get("brief") or []), book)
            if ys:
                if prev_max is not None and min(ys) < prev_max and p not in moved:
                    c.warnings.append(f"{key}/p{p} 가 앞 문단보다 이른 시기인데 reorder 에 이유가 없다")
                prev_max = max(ys) if prev_max is None else max(prev_max, max(ys))
        single = sum(1 for para in paras if len(para["facts"]) + len(para.get("brief") or []) == 1)
        if len(paras) >= 4 and single / len(paras) >= 0.7:
            c.warnings.append(f"{key} 문단 계획 {len(paras)}개 중 {single}개가 사실 하나 — 발언 나열 계획인지 본다")
    if len(set(centers)) < len(centers):
        c.warnings.append("장 중심(center)이 겹친다 — 장마다 다른 중심이어야 한다")

    # 쓴 것 · 뺀 것 — 원장의 모든 사실이 어딘가에, 뺀 것은 이유와 함께
    omitted: dict[str, str] = {}
    for i, x in enumerate(c.items(out["omit"], "omit")):
        if not isinstance(x, dict):
            raise c.fail("format", f"omit[{i}] 가 객체가 아니다")
        reason = c.text(x.get("reason"), f"omit[{i}].reason")
        for f in c.ids(x.get("facts"), allowed, f"omit[{i}].facts", nonempty=True):
            omitted[f] = reason
    both = sorted(set(used) & set(omitted), key=lambda x: int(x[1:]))
    if both:
        raise c.fail("reference", f"사실 {both} 이 문단 계획에도 omit 에도 있다")
    lost = sorted(allowed - set(used) - set(omitted), key=lambda x: int(x[1:]))
    if lost:
        raise c.fail("reference", f"사실 {lost} 이 어느 문단 계획에도 · omit 에도 없다")
    # 한 문단에 끈으로도 같은 단위로도 이어지지 않는 기억 단위가 섞였는가 — 다른 사람의 무관한 일이 끼는 것
    home = {f: u["id"] for u in analysis.get("units", []) for f in u.get("facts", [])}
    thread_units = [set(th.get("units", [])) for th in analysis.get("threads", [])]
    for ch in chapters:
        for pi, para in enumerate(ch["paragraphs"]):
            us = sorted({home[f] for f in list(para["facts"]) + list(para.get("brief") or []) if f in home})
            loose = [u for u in us if len(us) > 1 and not any(u in s and (s & set(us)) - {u} for s in thread_units)]
            if loose:
                c.warnings.append(f"{ch['chapter_key']}/p{pi} 에 다른 기억 단위와 끈으로 이어지지 않는 단위 {loose} 가 섞였다 — "
                                  "무관한 인물 · 사건이 한 문단에 들어왔는지 본다")
    # 장이 고른 기억 단위의 사실을 대부분 뺐는가 — 중심 소재의 핵심 기억을 한꺼번에 생략했는지
    for ch in chapters:
        used_here = {f for para in ch["paragraphs"] for f in list(para["facts"]) + list(para.get("brief") or [])}
        for uid in ch.get("units", []):
            fs = units.get(uid, {}).get("facts", [])
            gone_here = [f for f in fs if f in omitted]
            if len(fs) >= 3 and len(gone_here) / len(fs) > OMIT_UNIT_RATIO:
                c.warnings.append(f"{ch['chapter_key']} 이 고른 기억 단위 {uid} 의 사실 {len(fs)}개 중 {len(gone_here)}개를 뺐다 — "
                                  "장의 핵심 기억을 한꺼번에 생략했는지 본다")
    # 핵심 경위(core) 미지정 — facts 에 배정된 주된 서술 일화마다 그 단위의 사실이 core 에 하나도 없으면 경고.
    # 개수 · 비율은 강제하지 않는다(형식 오류 · code_gate 실패가 아니다). 단계 경고라 verify_plan → plan.checks 로 간다
    for ch in chapters:
        main_facts = {f for para in ch["paragraphs"] for f in para["facts"]}
        core_here = {f for para in ch["paragraphs"] for f in (para.get("core") or [])}
        for u in analysis.get("units", []):
            fs = set(u.get("facts", []))
            if fs & main_facts and not fs & core_here:
                c.warnings.append(f"{ch['chapter_key']} 이 facts 로 서술하는 일화 {u['id']}({(u.get('name') or '')[:30]}) 에 "
                                  "핵심 경위(core)가 지정되지 않았다 — 편집 단계에서 핵심 누락 보호가 없다")
    dropped_keep = sorted(must_keep(analysis) & set(omitted), key=lambda x: int(x[1:]))
    if dropped_keep:
        c.warnings.append(f"근거 없이 빠지면 안 되는 사실 {dropped_keep} 을 뺐다 — 이유를 사람이 본다")
    for f in opening + closing:
        if f not in used:
            c.warnings.append(f"책을 열거나 닫을 사실 {f} 이 어느 문단 계획에도 없다")
    return status, c.warnings


# ---------------------------------------------------------------- ③ 장 집필 입력 · 검사


def chapter_source(data: dict, analysis: dict, chapter: dict) -> tuple[dict, list[int]]:
    """
    장 하나에 줄 원자료. 전체 원문을 장마다 주지 않는다.

        이 장 문단 계획의 사실(facts · brief)이 가리키는 원문 턴만 — 앞뒤 문맥 턴을 붙이지 않는다
        (v4 실측: 문맥 턴의 사실이 출처 없이 본문에 들어왔다). 정정 전 · 뒤 턴은 그 사실의 turns 라
        함께 간다
        − 턴째로 막을 제외 범위. partial 제외 턴은 남기고 메시지에 제외 알림을 함께 준다

    항목은 merge 출력 그대로 고른다 — 번호도 글도 바꾸지 않는다. **순서는 문단 계획 순서**다.
    """
    book = ledger(analysis)
    gone = excluded_turns(analysis)
    order: list[int] = []
    for f in plan_facts(chapter):
        for t in book[f]["turns"] if f in book else []:
            if t not in order and t not in gone:
                order.append(t)
    rank = {t: i for i, t in enumerate(order)}
    picked = sorted((u for u in data["utterances"] if u["turn"] in rank), key=lambda u: rank[u["turn"]])
    used_sessions = {u["session_id"] for u in picked}
    partial = {t for x in analysis.get("exclusions") or [] if x.get("mode") == "partial"
               for t in (x.get("turns") or [])}
    src = {
        "shared_state": {"facts_found": [x for x in data["shared_state"].get("facts_found", [])
                                         if x.get("turn") in rank and x.get("turn") not in partial]},
        "sessions": [s for s in data["sessions"] if s["session_id"] in used_sessions],
        "utterances": picked,
    }
    return src, sorted(rank)


def check_chapter(out, chapter: dict, allowed: set[str], memos: list[str] | None = None) -> list[str]:
    key = chapter["chapter_key"]
    c = _Check("chapter", key)
    out = c.obj(out, ("chapter_key", "title", "paragraphs", "review_notes"))
    if out["chapter_key"] != key:
        raise c.fail("reference", f"chapter_key={out['chapter_key']!r} — 부른 장은 {key}")
    outside = "이 장 문단 계획에 없는 사실"
    c.sentence(out["title"], allowed, f"{key}/title", outside)
    c.paragraphs(out["paragraphs"], allowed, key, outside)
    c.notes(out["review_notes"], allowed, f"{key}/review_notes", outside)
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


def listing_signals(chapters: list[dict], data: dict) -> list[dict]:
    """
    장마다 발언 나열 신호 (redesign-v5 1절 측정과 같은 식). **목표치가 아니다** — 편집에는 할 일의
    단서로, 검증 채점에는 상한으로 쓴다.

        one_to_one   한 턴만 근거로 쓰고 그 턴을 다른 문장이 쓰지 않는 문장 비율 (턴 하나 = 문장 하나)
        order_kept   장 안에서 이어진 두 문장의 근거 턴 번호가 줄지 않는 비율 (인터뷰 순서 그대로)
        links        editorial 문장 + 시간 표지로 시작하는 문장
        multi_session_paragraphs  두 회차 이상의 말이 만나는 문단
    """
    session = {u["turn"]: u["session_id"] for u in data["utterances"]}
    out = []
    for ch in chapters:
        sents = [x for para in ch["paragraphs"] for x in para]
        sup = [x for x in sents if x["kind"] == "supported" and x["turns"]]
        use: dict[int, int] = {}
        for x in sup:
            for t in x["turns"]:
                use[t] = use.get(t, 0) + 1
        one = sum(1 for x in sup if len(x["turns"]) == 1 and use[x["turns"][0]] == 1)
        pairs = sum(1 for _ in zip(sup, sup[1:]))
        kept = sum(1 for a, b in zip(sup, sup[1:]) if min(b["turns"]) >= max(a["turns"]))
        links = sum(1 for x in sents if x["kind"] == "editorial" or _TIME_MARK.match(x["text"].strip()))
        multi = sum(1 for para in ch["paragraphs"]
                    if len({session[t] for x in para for t in x["turns"] if t in session}) > 1)
        n = len(sup)
        sig = {"chapter_key": ch["chapter_key"], "sentences": len(sents), "supported": n,
               "one_to_one": round(one / n, 2) if n else None,
               "order_kept": round(kept / pairs, 2) if pairs else None,
               "facts_per_sentence": round(sum(len(x.get("facts") or []) for x in sup) / n, 2) if n else None,
               "links": links, "paragraphs": len(ch["paragraphs"]), "multi_session_paragraphs": multi}
        sig["listing"] = bool(n >= LISTING_MIN_SENTENCES and (
            (sig["one_to_one"] or 0) >= LISTING_ONE_TO_ONE or (sig["order_kept"] or 0) >= LISTING_ORDER_KEPT))
        out.append(sig)
    return out


def locations(edited: dict) -> set[str]:
    """편집본에 실제로 있는 위치. 검증의 location 은 이 안이어야 한다."""
    locs = {"artifact", "title"}
    for ch in edited.get("chapters", []):
        k = ch["chapter_key"]
        locs |= {k, f"{k}/title"}
        for p, para in enumerate(ch["paragraphs"]):
            locs |= {f"{k}/p{p}"} | {f"{k}/p{p}/s{s}" for s in range(len(para))}
    return locs


def outline_memos(outline_out: dict) -> list[str]:
    """목차의 내부 메모(중심 · 경험 · 문단 역할 · 이유) — 본문에 그대로 들어가면 안 되는 글."""
    b = outline_out.get("book", {})
    texts = [b.get(k, "") for k in ("center", "flow")]
    for ch in outline_out.get("chapters", []):
        texts += [ch.get("center", ""), ch.get("experience", "")]
        texts += [p.get("role", "") for p in ch.get("paragraphs", []) if isinstance(p, dict)]
        texts += [r.get("reason", "") for r in ch.get("reorder", []) if isinstance(r, dict)]
    texts += [x.get("reason", "") for x in outline_out.get("omit", []) if isinstance(x, dict)]
    return [m for m in (_norm(t) for t in texts if isinstance(t, str)) if len(m) >= 8]


def memo_leaks(chapters: list[dict], memos: list[str]) -> list[str]:
    """
    목차 메모를 그대로 옮긴 editorial 문장의 위치. 글자(공백 · 부호 뺀)가 메모와 같거나
    메모 안에 통째로 들어 있으면 옮긴 것으로 본다.
    """
    out = []
    for ch in chapters:
        for p, para in enumerate(ch.get("paragraphs", [])):
            for s, x in enumerate(para):
                t = _norm(x.get("text", ""))
                if x.get("kind") == "editorial" and len(t) >= 8 and any(t in m or m in t for m in memos):
                    out.append(f"{ch['chapter_key']}/p{p}/s{s}")
    return out


def meta_sentences(chapters: list[dict]) -> list[str]:
    """글 바깥에서 설명하는 안내문 말투의 문장 위치."""
    return [f"{ch['chapter_key']}/p{p}/s{s}"
            for ch in chapters for p, para in enumerate(ch.get("paragraphs", []))
            for s, x in enumerate(para) if _META.search(x.get("text", ""))]


def _narration(text: str) -> str:
    """직접 인용을 뺀 서술 부분. 인용은 원문 말투를 그대로 둘 수 있다."""
    return _QUOTE.sub("", text or "").strip()


def _essay_ending(text: str) -> bool:
    """1인칭 회고 수필체 종결(~다 · ~했다)인가. 합니다체(~니다)와 해요체(~요)는 아니다."""
    t = _narration(text).rstrip(" .!?…\"'”’)")
    if not t:
        return True                               # 통째로 인용인 문장
    return t.endswith("다") and not t.endswith("니다")


# ---------------------------------------------------------------- 코드 판정 — 모델 판정과 따로 선다
#
#   block  stop_phrase      인터뷰를 멈추거나 미루는 말이 본문에 남음
#          memo_leak        목차 메모를 그대로 옮긴 editorial 문장
#          stale_correction 정정 전 값(정정 이력 before)이 본문 · 제목에 다시 나옴
#   fix    style_mix        인용 밖 서술이 ~다 로 끝나지 않음
#          answer_trace     질문에 대한 답 말로 시작
#          meta_text        글 바깥에서 설명하는 안내문
#          repeat_fact *    같은 사실을 두 장 이상이 근거로 씀 — 의도한 회상인지 편집이 판단
#          fact_token *     숫자 · 연도 · 나이 · 지명이 근거 턴에 없음 (보조 검사)
#          hearsay_lost     들은 이야기(heard)를 근거로 단 문장에 전언 표지가 없음
#          certainty_lost   대략 · 불확실한 사실을 근거로 단 문장에 흐림 표지가 없음
#          opinion_as_fact  화자의 평가 · 생각(view)을 근거로 단 문장이 객관적 사실처럼 씀
#          time_reversal    앞 문단보다 이른 시기의 문단인데 첫 문장에 시간 표지가 없음
#          must_keep_missing  근거 없이 빠지면 안 되는 사실이 본문에도 생략 목록에도 없음
#          core_missing     목차 문단 계획의 핵심 사실(core)이 본문에도 편집의 생략 목록에도 없음
#          edit_claim_mismatch 편집이 조치를 적었는데 결과물(edit_trace)은 그대로
#   info   must_keep_omitted  그런 사실을 이유와 함께 뺐다 (사람이 이유를 본다)
#          core_omitted     편집이 핵심 사실을 이유와 함께 뺐다 (정당한 생략인지 사람이 본다)
#          verbatim_run     원문 한 턴을 그대로 옮긴 문장이 셋 이상 잇달음
#
#   * 편집이 kept + 이유로 두면 code_gate 가 남은 것으로 치지 않는다 (말을 바꿔 쓴 경우를 막지 않기 위해).
#     hearsay_lost · certainty_lost 는 필수 사실 조건이라 kept 로 넘기지 못한다 — 사실 원장은 사실 단위라
#     문장이 그 사실을 근거로 달았으면 들은 말 · 흐림을 지켜야 한다(아니면 근거 사실을 바로잡는다).
#     그 밖의 fix 는 kept 여도 남은 문제다. 출처 · 참조 오류와 제외 턴은 여기 없다 — 단계 검사가 멈춘다.

KEPT_ACCEPTED = {"repeat_fact": "fact", "fact_token": "token"}


def _finding(rule, severity, location, detail, **extra) -> dict:
    tail = extra.get("fact") or extra.get("token")
    return {"id": f"{rule}:{location}" + (f":{tail}" if tail else ""), "rule": rule, "severity": severity,
            "location": location, "detail": detail, **extra}


def _sentences(chapters: list[dict]):
    for ch in chapters:
        for p, para in enumerate(ch.get("paragraphs", [])):
            for s, x in enumerate(para):
                yield f"{ch['chapter_key']}/p{p}/s{s}", ch, p, x


def code_findings(chapters: list[dict], outline_out: dict) -> list[dict]:
    """문체 · 흔적 · 메모 혼입 · 같은 사실의 중복."""
    memos = outline_memos(outline_out)
    out: list[dict] = []
    for ch in chapters:
        title = (ch.get("title") or {}).get("text", "")
        if _STOP.search(title):
            out.append(_finding("stop_phrase", "block", f"{ch['chapter_key']}/title", "인터뷰 진행을 멈추는 말"))
    for loc, ch, p, x in _sentences(chapters):
        text = x.get("text", "")
        if _STOP.search(text):
            out.append(_finding("stop_phrase", "block", loc, "인터뷰 진행을 멈추는 말"))
        t = _norm(text)
        if x.get("kind") == "editorial" and len(t) >= 8 and any(t in m or m in t for m in memos):
            out.append(_finding("memo_leak", "block", loc, "목차 메모를 그대로 옮김"))
        if not _essay_ending(text):
            out.append(_finding("style_mix", "fix", loc, "인용 밖 서술이 ~다 로 끝나지 않는다"))
        if _ANSWER.search(_narration(text) or text):
            out.append(_finding("answer_trace", "fix", loc, "질문에 대한 답 말로 시작한다"))
        if _META.search(_narration(text)):
            out.append(_finding("meta_text", "fix", loc, "글 바깥에서 설명하는 안내문"))
    cited: dict[str, set[str]] = {}
    where: dict[str, list[str]] = {}
    for loc, ch, p, x in _sentences(chapters):
        if x.get("kind") == "supported":
            for f in x.get("facts") or []:
                cited.setdefault(f, set()).add(ch["chapter_key"])
                where.setdefault(f, []).append(loc)
    for f in sorted(cited, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0):
        if len(cited[f]) > 1:
            out.append(_finding("repeat_fact", "fix", where[f][0], f"사실 {f} 을 {sorted(cited[f])} 가 함께 근거로 씀",
                                fact=f, locations=where[f]))
    return out


_NATIVE_NUM = r"(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)?(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉)?"
_SINO_NUM = r"(?:[이삼사오육칠팔구]?십[일이삼사오육칠팔구]?|[일이삼사오육칠팔구])"
_FACT_NUM = re.compile(
    r"(?<![가-힣\d])(\d+)\s?(?=년|살|세|시|명|월|일|번|개|층|대|주|시간|분|원|평)"   # 2010년 · 17살 · 9시
    r"|(?<![가-힣\d])((?:19|20)\d{2})(?!\d)"                                     # 숫자만 쓴 연도
    rf"|(?<![가-힣])((?=[열스서마쉰예일여아한두세네다])(?:{_NATIVE_NUM}))(?:\s(살|시|명|달|해|번|개|층|대)|(살))"
    rf"|(?<![가-힣])({_SINO_NUM})\s(년|살|세|평|명|개월|층|번)"                    # 이십오 년 · 육 년
)
_PLACE = re.compile(r"(?<![가-힣])([가-힣]{2,}?)(?=\s?(?:근처|쪽)|에서|으로|에(?!요)|(?<!으)로)")
_PLACE_STOP = {"처음", "다음", "나중", "그때", "거기", "여기", "저기", "정도", "마지막", "정말", "진짜",
               "그대", "실제", "이쪽", "저쪽", "그쪽", "자기", "혼자", "서로", "따로", "그다음", "아니", "지난번", "한편"}
PLACE_MAX_TURNS = 3              # 원문 전체에서 이보다 많은 턴에 나오는 말은 지명 · 장소가 아니라 흔한 말로 본다


def _fact_tokens(text: str) -> list[tuple[str, str]]:
    """문장의 명시적 숫자 사실 — (보이는 글, 대조할 값). 숫자 · 연도 · 나이 · 시각 · 인원 · 기간."""
    out = []
    for m in _FACT_NUM.finditer(text or ""):
        if m.group(1) or m.group(2):
            out.append((m.group(0).strip(), m.group(1) or m.group(2)))
        elif m.group(3):
            out.append((m.group(0).strip(), m.group(3) + "|" + (m.group(4) or m.group(5))))
        elif m.group(6):
            out.append((m.group(0).strip(), m.group(6) + "|" + m.group(7)))
    return out


_SINO_DIGIT = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_NATIVE_ONES = {"한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4, "다섯": 5, "여섯": 6,
                "일곱": 7, "여덟": 8, "아홉": 9}
_NATIVE_TENS = {"열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70,
                "여든": 80, "아흔": 90}


def _korean_number(num: str) -> int | None:
    """이십오 → 25 · 육 → 6 · 열일곱 → 17 · 네 → 4. 모르면 None."""
    if num and all(ch in _SINO_DIGIT or ch == "십" for ch in num):
        if "십" in num:
            a, _, b = num.partition("십")
            return (_SINO_DIGIT.get(a, 1) if a else 1) * 10 + (_SINO_DIGIT.get(b, 0) if b else 0)
        return _SINO_DIGIT.get(num) if len(num) == 1 else None
    for tens, tv in _NATIVE_TENS.items():
        if num.startswith(tens):
            rest = num[len(tens):]
            return tv + (_NATIVE_ONES.get(rest, 0) if rest else 0) if not rest or rest in _NATIVE_ONES else None
    return _NATIVE_ONES.get(num)


def _counts_as_number(shown: str, value: str) -> bool:
    """수 보존 검사 대상 — 연도 · 시각 · 나이 · 기간 · 금액 · 넓이 (NUMBER_UNITS)."""
    if "|" in value:
        return value.split("|")[1] in NUMBER_UNITS
    return any(u in shown for u in NUMBER_UNITS) or len(value) == 4


def _num_supported(value: str, support: str, support_digits: set[str]) -> bool:
    if "|" not in value:                                    # 아라비아 숫자 — 연도는 끝 두 자리도 같다고 본다
        return (value in support_digits or (len(value) == 4 and value[2:] in support_digits)
                or (len(value) == 2 and any(len(x) == 4 and x.endswith(value) for x in support_digits)))
    num, unit = value.split("|")
    n = _korean_number(num)
    return (num + unit in support or (len(num) >= 2 and num in support)    # "열일곱에" 처럼 단위 없이 말한 나이
            or (n is not None and str(n) in support_digits))              # "한 육 년" ↔ "약 6년"


def fact_findings(chapters: list[dict], data: dict) -> list[dict]:
    """
    **보조 검사** — 문장에 쓴 숫자 · 연도 · 나이 · 지명 같은 명시적 사실이 그 문장의 근거 턴
    (질문 + 답)에 있는가. 없으면 fact_token(fix) — 다른 턴에 있으면 그 턴을 알려 준다.

    - 근거 표시가 빠진 것을 찾으려는 것이다. 문장의 뜻이 근거와 맞는지는 보지 않는다 —
      **의미상의 출처 오류를 이 검사가 다 잡지 못한다** (검증 · 사람 몫)
    - 지명 · 장소는 원문에서 '에 · 에서 · 로 · 근처 · 쪽' 앞에 온 말 가운데 원문 PLACE_MAX_TURNS 턴
      이하에만 나오는 말로 어림한다. 말을 바꿔 쓴 경우 잘못 걸릴 수 있어 경고로 둔다
    """
    utts = {u["turn"]: f"{u.get('asked', '')} {u['elder']}" for u in data["utterances"]}
    flat = {t: re.sub(r"\s+", "", s) for t, s in utts.items()}
    digits = {t: set(re.findall(r"\d+", s)) for t, s in utts.items()}
    seen: dict[str, set[int]] = {}
    for t, s in utts.items():
        for w in _PLACE.findall(s):
            if w not in _PLACE_STOP and not re.fullmatch(_NATIVE_NUM, w):     # "열일곱에" 는 숫자 쪽에서 본다
                seen.setdefault(w, set())
    for w in seen:
        seen[w] = {t for t, s in flat.items() if w in s}
    places = {w for w, ts in seen.items() if len(ts) <= PLACE_MAX_TURNS}

    out = []
    for loc, ch, p, x in _sentences(chapters):
        text = x.get("text", "")
        cited = [t for t in x.get("turns", []) if t in utts]
        support = "".join(flat[t] for t in cited)
        sdig = set().union(*(digits[t] for t in cited)) if cited else set()
        misses = []
        for shown, value in _fact_tokens(text):
            if not _num_supported(value, support, sdig):
                found = [t for t in utts if _num_supported(value, flat[t], digits[t])]
                misses.append((shown, found))
        flat_text = re.sub(r"\s+", "", text)
        for w in sorted(places):
            if w in flat_text and w not in support:
                misses.append((w, sorted(seen[w])))
        for shown, found in misses:
            where = f"턴 {found} 에 있다" if found else "원문 어디에도 없다"
            out.append(_finding("fact_token", "fix", loc, f"'{shown}' 이(가) 근거 턴 {cited} 에 없다 — {where}. "
                                "근거 사실을 바로잡거나, 같은 뜻을 바꿔 쓴 것이면 kept + 이유",
                                token=shown, found_in=found))
    return out


def voice_findings(chapters: list[dict], book: dict[str, dict]) -> list[dict]:
    """
    들은 이야기 · 대략의 사실을 단정으로 바꿨는가 — 사실 원장의 source · certainty 와 문장의 표지를
    견준다. 사실 단위로 보므로 kept 로 넘기지 못한다(fix) — 문장이 그 사실을 쓰지 않았다면 근거를 바로잡는다.
    """
    out = []
    for loc, ch, p, x in _sentences(chapters):
        if x.get("kind") != "supported":
            continue
        text = x.get("text", "")
        for f in x.get("facts") or []:
            fact = book.get(f)
            if not fact:
                continue
            if fact["source"] == "heard" and not _HEARD_BODY.search(text):
                out.append(_finding("hearsay_lost", "fix", loc, f"사실 {f} 은 들은 이야기인데 문장에 전언 표지가 없다",
                                    fact=f))
            if fact["source"] == "view" and not _VIEW_BODY.search(text):
                out.append(_finding("opinion_as_fact", "fix", loc,
                                    f"사실 {f} 은 화자의 평가 · 생각인데 문장이 객관적 사실처럼 쓴다", fact=f))
            if fact["certainty"] in ("approx", "uncertain") and not _HEDGE_BODY.search(text):
                out.append(_finding("certainty_lost", "fix", loc,
                                    f"사실 {f} 은 {fact['certainty']} 인데 문장이 단정한다", fact=f))
    return out


def time_findings(chapters: list[dict], book: dict[str, dict]) -> list[dict]:
    """앞 문단보다 이른 시기로 돌아가는 문단 — 첫 문장에 시간 표지가 없으면 fix (재배치는 허용, 표지는 필요)."""
    out = []
    for ch in chapters:
        prev_max = None
        for p, para in enumerate(ch.get("paragraphs", [])):
            ys = _para_years([f for x in para for f in (x.get("facts") or [])], book)
            if not ys:
                continue
            first = para[0].get("text", "")
            if prev_max is not None and min(ys) < prev_max and not _TIME_MARK.search(first):
                out.append(_finding("time_reversal", "fix", f"{ch['chapter_key']}/p{p}",
                                    f"앞 문단({prev_max}년)보다 이른 {min(ys)}년으로 돌아가는데 첫 문장에 시간 표지가 없다"))
            prev_max = max(ys) if prev_max is None else max(prev_max, max(ys))
    return out


def keep_findings(chapters: list[dict], keep: set[str], outline_omit: dict[str, str],
                  edit_omitted: dict[str, str] | None = None) -> list[dict]:
    """
    근거 없이 빠지면 안 되는 사실이 본문에 남았는가. 목차의 생략과 편집의 생략을 나눠 본다.

        must_keep_excluded  review  목차가 이유와 함께 뺐다 — 책 설계의 결정. 검증 · 사람이 본다(code_gate 밖)
        must_keep_omitted   fix     목차가 쓰기로 한 것을 편집이 뺐다 — **이유가 있어도 미해결 보호 누락**.
                                    정당한 통합인지는 검증 · 사람 검수가 본다(자동 통과 없음)
        must_keep_missing   fix     본문에도 생략 목록에도 없다

    목차 omit 이 먼저다 — 편집이 목차의 생략을 다시 적어도(v5 편집은 그렇게 했다) 편집 생략으로 세지 않는다.
    """
    cited = {f for _, _, _, x in _sentences(chapters) for f in (x.get("facts") or [])}
    edit_omitted = edit_omitted or {}
    out = []
    for f in sorted(keep - cited, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0):
        if outline_omit.get(f, "").strip():
            out.append(_finding("must_keep_excluded", "review", "artifact",
                                f"목차가 사실 {f} 을 뺐다 — 이유: {outline_omit[f][:80]}", fact=f))
        elif edit_omitted.get(f, "").strip():
            out.append(_finding("must_keep_omitted", "fix", "artifact",
                                f"편집이 사실 {f} 을 뺐다 — 이유가 있어도 미해결 보호 누락: {edit_omitted[f][:80]}", fact=f))
        else:
            out.append(_finding("must_keep_missing", "fix", "artifact",
                                f"사실 {f} 이 본문에도 생략 목록에도 없다 — 중요한 사건 · 정정 · 직접 말한 감정 · 마지막 발언",
                                fact=f))
    return out


def core_findings(chapters: list[dict], core: dict[str, str], omitted: dict[str, str],
                  book: dict[str, dict]) -> list[dict]:
    """
    목차 문단 계획의 핵심 사실이 원고에 남았는가. 보조 사실은 보지 않는다(골라 쓰는 것이다).

        core_missing   fix   본문에도 편집의 생략 목록에도 없다 — 실수로 빠진 것. kept 로 넘기지 못한다
        core_omitted   fix   편집이 omitted 에 이유와 함께 뺐다 — **이유가 있어도 미해결 보호 누락**. 이유에 적힌
                             다른 사실 id 는 대응 내용을 찾는 데만 쓴다(그 id 가 남았다고 낮추지 않는다).
                             정당한 통합인지는 검증(plan.protected_omissions) · 사람 검수가 본다

    omitted 는 **편집의 생략 목록만** 받는다(장 초안 단계에는 없다) — 목차 omit 은 핵심 사실을 담지 않는다.
    사실은 문장의 facts 로 센다 — 근거로 단 사실이 글에 실제로 드러났는지는 fact_token · 사람 대조가 본다.
    """
    cited = {f for _, _, _, x in _sentences(chapters) for f in (x.get("facts") or [])}
    out = []
    for f in sorted(set(core) - cited, key=_fid):
        what = (book.get(f) or {}).get("text", "")[:40]
        if omitted.get(f, "").strip():
            out.append(_finding("core_omitted", "fix", "artifact",
                                f"목차 {core[f]} 의 핵심 사실 {f}({what}) 을 편집이 뺐다 — 이유가 있어도 미해결: {omitted[f][:80]}",
                                fact=f, plan=core[f]))
        else:
            out.append(_finding("core_missing", "fix", "artifact",
                                f"목차 {core[f]} 의 핵심 사실 {f}({what}) 이 본문에도 생략 목록에도 없다",
                                fact=f, plan=core[f]))
    return out


def correction_findings(chapters: list[dict], analysis: dict, title: dict | None = None) -> list[dict]:
    """
    정정 전 값이 본문 · 제목에 되살아났는가 — block. 연도는 끝 두 자리로 견주고, 연도가 없는 정정은
    정정 전 값의 글자가 그대로 들어 있는지 본다(정정 이력 before 는 분석 기록에만 남는다).
    """
    out = []
    items = ([("title", title)] if title else []) + [(f"{ch['chapter_key']}/title", ch.get("title") or {}) for ch in chapters]
    items += [(loc, x) for loc, _, _, x in _sentences(chapters)]
    for c in analysis.get("corrections", []):
        before, after = (c.get("before") or "").strip(), (c.get("after") or "").strip()
        stale_years = _years(before) - _years(after)
        for loc, x in items:
            text = x.get("text", "")
            if (stale_years and _years(text) & stale_years) or (
                    not _years(before) and len(_norm(before)) >= 2 and _norm(before) in _norm(text)):
                out.append(_finding("stale_correction", "block", loc,
                                    f"사실 {c['fact']} 의 정정 전 값이 다시 나왔다 — 정정 뒤 값만 쓴다", fact=c["fact"]))
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
                        out.append(_finding("verbatim_run", "info", loc, f"원문 한 턴 그대로인 문장 {run}개 잇달음"))
                    run = 0
    return out


def all_findings(chapters: list[dict], outline_out: dict, data: dict, analysis: dict,
                 omitted: dict[str, str] | None = None, *, final: bool = False,
                 edit_omitted: dict[str, str] | None = None) -> list[dict]:
    """
    한 원고(장 초안 묶음 · 편집본)에 대한 코드 판정 전부. 핵심 사실(plan_core)은 core_findings 가 보고
    must_keep 검사에서는 뺀다(한 사실에 두 번 경고하지 않는다). omitted 는 **목차의 생략 목록**, edit_omitted 는
    편집의 생략 목록 — 둘을 섞지 않는다. final 이면 일화 전체 누락(episode_findings)도 본다.
    """
    book = ledger(analysis)
    core = plan_core(outline_out)
    out = (code_findings(chapters, outline_out) + fact_findings(chapters, data)
           + voice_findings(chapters, book) + time_findings(chapters, book)
           + keep_findings(chapters, must_keep(analysis) - set(core), omitted or {}, edit_omitted)
           + core_findings(chapters, core, edit_omitted or {}, book)
           + correction_findings(chapters, analysis))
    if final:
        out += verbatim_runs(chapters, data)
        out += episode_findings(chapters, outline_out, analysis, edit_omitted or {}, omitted or {})
    return out


# ---------------------------------------------------------------- 일화 전체 누락 · 누락 검토 후보 (v7)
#
#   일화 = 분석의 기억 단위(units). main · minor 로 검토 대상을 가르지 않는다.
#   채택 = 그 단위의 사실이 목차 문단 계획의 facts **또는 brief** 에 하나라도 있음 (brief 로만 계획된 일화도 채택이다)
#
#       episode_missing   fix     채택한 일화가 최종본에서 통째로 사라졌고 편집의 생략 이유가 없다
#       episode_omitted   fix     같은 경우인데 편집이 이유를 적었다 — 이유가 있어도 미해결(사람 · 검증이 본다)
#       episode_excluded  review  목차가 일화 전체를 뺐다 — 책 설계의 결정. 한 장 시험의 범위 밖 일화도 여기다(편집 누락이 아니다)


def _planned(outline_out: dict, with_brief: bool = True) -> set[str]:
    return {f for ch in outline_out.get("chapters", []) for p in ch.get("paragraphs", [])
            for f in list(p.get("facts") or []) + (list(p.get("brief") or []) if with_brief else [])}


def episode_findings(chapters: list[dict], outline_out: dict, analysis: dict,
                     edit_omitted: dict[str, str], outline_omit: dict[str, str]) -> list[dict]:
    cited = {f for _, _, _, x in _sentences(chapters) for f in (x.get("facts") or [])}
    planned = _planned(outline_out)
    out = []
    for u in analysis.get("units", []):
        fs = [f for f in u.get("facts", [])]
        if not fs:
            continue
        name = (u.get("name") or "")[:40]
        if set(fs) & cited:
            continue                                   # 본문에 남았다 — 일부 사실의 손실은 omission_candidates 가 본다
        if not set(fs) & planned:
            if all(outline_omit.get(f, "").strip() for f in fs):
                reasons = sorted({outline_omit[f][:60] for f in fs})
                out.append(_finding("episode_excluded", "review", "artifact",
                                    f"목차가 일화 {u['id']}({name}) 전체를 뺐다 — 이유: {' / '.join(reasons)[:120]}",
                                    unit=u["id"], token=u["id"]))
            continue
        why = [edit_omitted[f] for f in fs if edit_omitted.get(f, "").strip()]
        if why:
            out.append(_finding("episode_omitted", "fix", "artifact",
                                f"목차가 쓰기로 한 일화 {u['id']}({name}) 를 편집이 통째로 뺐다 — 이유가 있어도 미해결: {why[0][:80]}",
                                unit=u["id"], token=u["id"]))
        else:
            out.append(_finding("episode_missing", "fix", "artifact",
                                f"목차가 쓰기로 한 일화 {u['id']}({name}) 가 최종본에서 통째로 사라졌다 — 생략 이유도 없다",
                                unit=u["id"], token=u["id"]))
    return out


PROTECTED_RULES = ("core_missing", "core_omitted", "must_keep_missing", "must_keep_omitted", "must_keep_excluded",
                   "episode_missing", "episode_omitted", "episode_excluded")


def _fact_sentences(chapters: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for loc, _, _, x in _sentences(chapters):
        for f in x.get("facts") or []:
            out.setdefault(f, []).append({"loc": loc, "text": x.get("text", "")})
    return out


def _fact_source(f: str, book: dict[str, dict], elder: dict[int, str]) -> list[dict]:
    return [{"turn": t, "elder": elder[t]} for t in (book.get(f) or {}).get("turns", []) if t in elder]


def _marker_changes(fact: dict, draft_text: str, final_text: str) -> list[str]:
    """
    **사실 범위**의 표지 비교 — 후보 탐지에만 쓴다. 그 사실의 메모 · time 에 있는 수 · 연도와, 메모의 부정 ·
    출처의 전언 · certainty 의 흐림이 초안 표현에는 있고 그 사실을 단 편집본 문장에는 없으면 적는다.
    같은 숫자가 장 어딘가에 있어도 그 사실의 문장에 없으면 후보다(보존을 확정하지 않는다).
    """
    memo = f"{fact.get('text', '')} {fact.get('time', '')}"
    out = [v for _, v in _fact_tokens(memo) if _norm(v) in _norm(draft_text) and _norm(v) not in _norm(final_text)]
    if _NEG_FACT.search(fact.get("text", "")) and _NEG_FACT.search(draft_text) and not _NEG_FACT.search(final_text):
        out.append("부정")
    if fact.get("source") == "heard" and _HEARD_BODY.search(draft_text) and not _HEARD_BODY.search(final_text):
        out.append("전언")
    if fact.get("certainty") in ("approx", "uncertain") and _HEDGE_BODY.search(draft_text) and not _HEDGE_BODY.search(final_text):
        out.append("흐림")
    return out


def omission_candidates(drafts: list[dict], final: list[dict], trace: dict, analysis: dict, data: dict,
                        edit_omitted: dict[str, str], outline_omit: dict[str, str],
                        protected: set[str]) -> list[dict]:
    """
    편집 전후의 누락 **검토 후보** — 확정 누락이 아니다. edit_trace 를 다시 쓰고 그 반환 모양은 건드리지 않는다.
    검증(plan.omission_review)이 원문과 대조해 정상 통합 · 부수 축약과 의미 손실을 가른다. 코드 오류를 내지 않는다.

        fact_dropped  초안에 있던 사실이 편집본에 없다 (편집이 이유를 적었어도 후보)
        fact_changed  같은 id 가 남았지만 그 사실을 쓴 초안 문장이 덜어 낸 문장(dropped)에 들었거나,
                      사실 범위의 수 · 부정 · 전언 · 흐림 표지가 편집본 문장에서 사라졌다 — 같은 id 가 남았다고 빼지 않는다
        fact_new      초안에 없던 사실이 편집본에 들어왔다 — 초안은 사실의 기준이 아니니 원문 · 원장과 대조한다

    후보에는 그 사실의 원문 근거 · 초안 표현 · 편집본 표현만 담는다(초안 전체를 다시 보내지 않는다).
    """
    book = ledger(analysis)
    elder = {u["turn"]: u["elder"] for u in data["utterances"]}
    home = {f: u["id"] for u in analysis.get("units", []) for f in u.get("facts", [])}
    D, F = _fact_sentences(drafts), _fact_sentences(final)
    dropped_locs = set(trace.get("dropped", []))
    rows = []

    def row(f, kind, signals):
        fact = book.get(f) or {}
        rows.append({"fact": f, "kind": kind, "unit": home.get(f), "protected": f in protected,
                     "memo": fact.get("text", ""), "source": fact.get("source"), "certainty": fact.get("certainty"),
                     "signals": signals, "evidence": _fact_source(f, book, elder),
                     "draft": D.get(f, []), "final": F.get(f, []),
                     "omitted_reason": edit_omitted.get(f) or outline_omit.get(f) or ""})
    for f in sorted(set(D) - set(F), key=_fid):
        row(f, "fact_dropped", ["편집본에 없음" + (" (생략 이유 있음)" if edit_omitted.get(f, "").strip() else " (생략 이유 없음)")])
    for f in sorted(set(D) & set(F), key=_fid):
        sig = []
        merged = [d["loc"] for d in D[f] if d["loc"] in dropped_locs]
        if merged:
            sig.append(f"초안 문장 {merged} 이 덜어 낸 문장이다(통합일 수 있다)")
        changes = _marker_changes(book.get(f) or {}, " ".join(d["text"] for d in D[f]), " ".join(x["text"] for x in F[f]))
        if changes:
            sig.append(f"사실 범위 표지가 편집본 문장에 없다: {changes}")
        if sig:
            row(f, "fact_changed", sig)
    for f in sorted(set(F) - set(D), key=_fid):
        row(f, "fact_new", ["초안에 없던 사실 — 원문 · 원장과 대조"])
    return rows


def protected_omissions(findings: list[dict], analysis: dict, data: dict, final: list[dict]) -> list[dict]:
    """보호 대상 누락 판정을 검증 입력으로 — 대상 사실(또는 일화의 사실) · 지적 · 원문 근거 · 편집본의 대응 표현."""
    book = ledger(analysis)
    elder = {u["turn"]: u["elder"] for u in data["utterances"]}
    units = {u["id"]: u for u in analysis.get("units", [])}
    F = _fact_sentences(final)
    out = []
    for x in findings:
        if x["rule"] not in PROTECTED_RULES:
            continue
        facts = [x["fact"]] if x.get("fact") else list((units.get(x.get("unit")) or {}).get("facts", []))
        refs = sorted({r for r in re.findall(r"f\d{1,3}", x.get("detail", "")) if r in book and r not in facts}, key=_fid)
        out.append({"rule": x["rule"], "severity": x["severity"], "detail": x["detail"], "unit": x.get("unit"),
                    "facts": [{"fact": f, "memo": (book.get(f) or {}).get("text", ""),
                               "evidence": _fact_source(f, book, elder)} for f in facts],
                    "referenced": [{"fact": r, "final": F.get(r, [])} for r in refs]})
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
        attention  fix 가 남음. 단 KEPT_ACCEPTED 규칙은 편집이 같은 대상(사실 · 낱말)의 경고를
                   kept + 이유로 처리했으면 남은 것으로 치지 않는다
        pass       block · fix 없음 (info 는 사람 검수 참고로만)
    """
    kept: dict[str, set] = {rule: set() for rule in KEPT_ACCEPTED}
    for c in draft_checks or []:
        key = KEPT_ACCEPTED.get(c["rule"])
        if key and resolutions.get(c["id"], {}).get("status") == "kept":
            kept[c["rule"]].add(c.get(key))

    def accepted(f):
        key = KEPT_ACCEPTED.get(f["rule"])
        return bool(key) and f.get(key) in kept[f["rule"]]
    blocks = [f for f in final if f["severity"] == "block"]
    fixes = [f for f in final if f["severity"] == "fix" and not accepted(f)]
    state = "blocked" if blocks else "attention" if fixes else "pass"
    return {"state": state, "findings": final,
            "accepted": {r: sorted(str(v) for v in vs if v is not None) for r, vs in kept.items() if vs},
            "counts": {s: sum(1 for f in final if f["severity"] == s) for s in ("block", "fix", "info", "review")}}


# ---------------------------------------------------------------- 편집 추적 — 결과물끼리 견준다


def _flat_sentences(chapters: list[dict]) -> list[dict]:
    out = []
    for c, ch in enumerate(chapters):
        for p, para in enumerate(ch["paragraphs"]):
            for s, x in enumerate(para):
                out.append({"loc": f"{ch['chapter_key']}/p{p}/s{s}", "chapter": ch["chapter_key"],
                            "para": f"{ch['chapter_key']}/p{p}", "i": len(out), "kind": x["kind"],
                            "norm": _norm(x["text"]), "facts": set(x.get("facts") or [])})
    return out


def _lis_members(seq: list[int]) -> set[int]:
    """가장 긴 증가 부분 수열에 든 값 — 그 밖의 것이 순서를 바꿔 옮긴 문장이다."""
    import bisect
    tails, tails_i, prev = [], [], [-1] * len(seq)
    for i, v in enumerate(seq):
        k = bisect.bisect_left(tails, v)
        if k == len(tails):
            tails.append(v)
            tails_i.append(i)
        else:
            tails[k], tails_i[k] = v, i
        prev[i] = tails_i[k - 1] if k else -1
    out, i = set(), tails_i[-1] if tails_i else -1
    while i >= 0:
        out.add(seq[i])
        i = prev[i]
    return out


def edit_trace(drafts: list[dict], final: list[dict], omitted: dict[str, str] | None = None) -> dict:
    """
    장 초안 → 편집본에서 **실제로 바뀐 것**을 코드가 잰다. 모델의 편집 메모에 기대지 않는다.

    편집본 문장마다 근거 사실이 겹치는 초안 문장(editorial 은 editorial 끼리) 가운데 글이 가장
    닮은 것을 짝으로 고른다.

        kept      닮음 0.9 이상 — 거의 그대로
        revised   0.5 이상 — 다듬음
        rewritten 0.5 미만이지만 같은 사실 — 다시 씀
        new       짝 없음 — 새 연결 문장이거나 초안에 없던 사실을 들임
        moved     짝의 순서가 초안과 달라짐(가장 긴 증가 부분 수열 밖) 또는 다른 장에서 옴
        dropped   어느 편집본 문장의 짝도 되지 않은 초안 문장

    장 합침: 초안 두 장 이상에서 문장이 들어온 편집본 장. 장 나눔: 한 초안 장의 문장이 편집본
    두 장 이상으로 간 것. 문단도 같은 식으로 센다.
    """
    D, F = _flat_sentences(drafts), _flat_sentences(final)
    pairs = []
    for f in F:
        best, ratio = None, 0.0
        for d in D:
            if (f["kind"] == "editorial") != (d["kind"] == "editorial"):
                continue
            if f["kind"] == "supported" and not (f["facts"] & d["facts"]):
                continue
            r = difflib.SequenceMatcher(None, f["norm"], d["norm"]).ratio()
            if r > ratio:
                best, ratio = d, r
        if f["kind"] == "editorial" and ratio < 0.5:
            best = None                     # 잇는 문장은 글이 닮아야 같은 것으로 본다
        pairs.append((f, best, ratio))
    matched = [d["i"] for f, d, r in pairs if d]
    in_order = _lis_members(matched)
    rows, by_kind = [], {"kept": 0, "revised": 0, "rewritten": 0, "new": 0}
    ch_from: dict[str, dict[str, int]] = {}
    para_from: dict[str, set[str]] = {}
    para_to: dict[str, set[str]] = {}
    moved = 0
    for f, d, r in pairs:
        if d is None:
            kind = "new"
        else:
            kind = "kept" if r >= 0.9 else "revised" if r >= 0.5 else "rewritten"
            ch_from.setdefault(f["chapter"], {}).setdefault(d["chapter"], 0)
            ch_from[f["chapter"]][d["chapter"]] += 1
            para_from.setdefault(f["para"], set()).add(d["para"])
            para_to.setdefault(d["para"], set()).add(f["para"])
        by_kind[kind] += 1
        is_moved = bool(d) and d["i"] not in in_order
        moved += is_moved
        rows.append({"at": f["loc"], "from": d["loc"] if d else None, "kind": kind,
                     "ratio": round(r, 2), "moved": is_moved})
    used = {d["i"] for d in (p[1] for p in pairs) if d}
    dropped = [d for d in D if d["i"] not in used]
    final_facts = {x for f in F for x in f["facts"]}
    draft_facts = {x for d in D for x in d["facts"]}
    dropped_facts = sorted(draft_facts - final_facts, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
    omitted = omitted or {}
    ch_to: dict[str, set[str]] = {}
    for fk, src in ch_from.items():
        for dk, n in src.items():
            ch_to.setdefault(dk, set()).add(fk)
    merges = sorted(k for k, src in ch_from.items() if len([n for n in src.values() if n >= 2]) >= 2)
    splits = sorted(k for k, dst in ch_to.items() if len([fk for fk in dst if ch_from[fk].get(k, 0) >= 2]) >= 2)
    summary = {
        "draft_chapters": len(drafts), "final_chapters": len(final),
        "draft_sentences": len(D), "final_sentences": len(F),
        **by_kind, "dropped": len(dropped), "moved": moved,
        "chapter_merges": merges, "chapter_splits": splits,
        "paragraph_merges": sum(1 for v in para_from.values() if len(v) >= 2),
        "paragraph_splits": sum(1 for v in para_to.values() if len(v) >= 2),
        "unchanged_ratio": round(by_kind["kept"] / len(F), 2) if F else None,
    }
    summary["structure_changed"] = bool(
        len(drafts) != len(final) or merges or splits or moved or summary["paragraph_merges"]
        or summary["paragraph_splits"])
    return {"summary": summary, "sentences": rows, "dropped": [d["loc"] for d in dropped],
            "dropped_facts": dropped_facts,
            "draft_facts_at": {d["loc"]: sorted(d["facts"], key=_fid) for d in D},
            "unexplained_dropped_facts": [f for f in dropped_facts if not omitted.get(f, "").strip()],
            "new_facts": sorted(final_facts - draft_facts, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)}


# ---------------------------------------------------------------- ④ 편집 · ⑤ 검증 검사


EDIT_UNCHANGED_RATIO = 0.8   # 편집본 문장 가운데 초안 그대로인 비율 — 이 이상이고 구조 변화가 없으면 '고치지 않은 편집'


def edit_claim_findings(edited: dict, trace: dict) -> list[dict]:
    """
    편집이 진단 · 메모에 조치를 적었는데 결과물에는 바뀐 것이 없다 — fix(kept 불가). 모델의 보고가 아니라
    코드가 잰 edit_trace 를 기준으로 본다. 진단에 조치가 없거나 실제로 바뀌었으면 아무것도 내지 않는다.
    """
    s = trace.get("summary") or {}
    claimed = [d.get("action", "") for d in edited.get("diagnosis", []) if str(d.get("action", "")).strip()]
    unchanged = (s.get("unchanged_ratio") or 0) >= EDIT_UNCHANGED_RATIO and not s.get("structure_changed")
    if claimed and unchanged:
        return [_finding("edit_claim_mismatch", "fix", "artifact",
                         f"편집 진단에 조치 {len(claimed)}개를 적었지만 결과는 초안 그대로 {s.get('kept')}/{s.get('final_sentences')}문장 · "
                         "구조 변화 없음 — 고쳤다는 보고를 믿지 않는다")]
    return []


def check_final(out, analysis: dict, T: set[int], focus: str | None = None) -> tuple[dict[str, str], list[str]]:
    """
    편집본의 최종 근거검사. 편집은 **구성을 바꿀 수 있다** — 장을 합치고 나누고 순서를 바꾸고,
    문단을 옮기고, 문장을 덜어 낼 수 있다(장 1~5, 한 장 시험은 1장). 대신:

        모든 문장의 facts 는 사실 원장 안 (제외 턴의 사실은 원장에 없다)
        diagnosis(먼저 본 문제)가 하나 이상
        omitted 의 사실 · 이유 — 뺀 것을 거슬러 갈 수 있게

    돌려주는 것은 (생략 사실 → 이유, 경고).
    """
    c = _Check("final_check")
    out = c.obj(out, ("diagnosis", "title", "chapters", "omitted", "checks_resolution", "notes"))
    allowed = set(ledger(analysis))
    diag = c.items(out["diagnosis"], "diagnosis")
    if not diag:
        raise c.fail("format", "diagnosis 가 비었다 — 원고 전체를 본 기록이 없다")
    for i, d in enumerate(diag):
        if not isinstance(d, dict) or not _str_list(d.get("where", [])):
            raise c.fail("format", f"diagnosis[{i}] 모양이 다르다")
        c.text(d.get("issue"), f"diagnosis[{i}].issue")
        c.text(d.get("action", ""), f"diagnosis[{i}].action", nonempty=False)
    c.sentence(out["title"], allowed, "title")
    chapters = out["chapters"]
    if not isinstance(chapters, list) or not chapters:
        raise c.fail("format", "chapters 가 비었거나 목록이 아니다")
    if focus and len(chapters) != 1:
        raise c.fail("chapter_limit", f"{len(chapters)}장 — 한 장 시험(focus)은 정확히 1장")
    if len(chapters) > MAX_CHAPTERS:
        raise c.fail("chapter_limit", f"{len(chapters)}장 — 상한 {MAX_CHAPTERS}장")
    keys = [ch.get("chapter_key") if isinstance(ch, dict) else None for ch in chapters]
    if keys != [f"ch-{n}" for n in range(1, len(keys) + 1)]:
        raise c.fail("reference", f"편집본 장 키 {keys} — ch-1 부터 차례여야 한다")
    for ch in chapters:
        k = ch["chapter_key"]
        if "title" not in ch or "paragraphs" not in ch:
            raise c.fail("format", f"{k} 에 title · paragraphs 가 없다")
        c.text(ch.get("center", ""), f"{k}.center", nonempty=False)
        c.sentence(ch["title"], allowed, f"{k}/title")
        c.paragraphs(ch["paragraphs"], allowed, k)
    omitted = _omitted(c, out, allowed)
    cited = {f for _, _, _, x in _sentences(chapters) for f in (x.get("facts") or [])}
    both = sorted(cited & set(omitted))
    if both:
        c.warnings.append(f"사실 {both} 을 본문에 쓰고 omitted 에도 적었다")
    return omitted, c.warnings


def _omitted(c: _Check, out: dict, allowed: set[str]) -> dict[str, str]:
    """편집의 omitted(생략 사실 → 이유)와 notes 모양."""
    omitted: dict[str, str] = {}
    for i, x in enumerate(c.items(out["omitted"], "omitted")):
        if not isinstance(x, dict):
            raise c.fail("format", f"omitted[{i}] 가 객체가 아니다")
        reason = c.text(x.get("reason"), f"omitted[{i}].reason")
        for f in c.ids(x.get("facts"), allowed, f"omitted[{i}].facts", nonempty=True):
            omitted[f] = reason
    if not _str_list(out["notes"]):
        raise c.fail("format", "notes 가 문자열 목록이 아니다")
    return omitted


# ---------------------------------------------------------------- ④ 편집 v6 — 문단 산문 + 근거 표현(claims)
#
# v5 편집은 문장마다 {text, kind, facts} 객체를 냈다. 사실 메모 하나가 문장 하나가 되고(문장-메모 유사도
# 초안 0.74 → 편집 0.82), 초안 문장 객체를 짝지어 복사하기 쉬웠다(edit-contract-review-v5.md).
# v6 편집은 문단을 산문 한 덩어리(text)로 쓰고, 근거는 본문 표현(span)마다 따로 단다(claims).
# 코드가 문단을 문장으로 나눠 **문장 · 표현 단위**로 검사한다 — 문단 단위 근거에 문장의 사실 오류가
# 묻히지 않게. 변환한 문장 목록은 v5 와 같은 모양이라 뒤 검사(fact_token · 들은 말 · 흐림 · 핵심 사실 ·
# edit_trace · 검증 위치)를 그대로 쓴다. 장 집필 · 검증 계약은 v5 그대로다.
#
#   block  span_missing          claim 의 span 이 문단 본문에 없다
#          span_misplaced        span 이 본문에 있지만 앞 span 과 겹치거나 순서가 다르다
#          span_crosses_sentence span 이 문장 경계를 넘는다 (넓은 span 이 문장들의 근거를 섞는다)
#   fix    uncovered_text        span 이 덮지 않은 서술이 UNCOVERED_MAX 자 이상 — 근거 없는 주장일 수 있다
#          link_content          사실 없는 잇는 말(link)에 감정 · 동기 · 인과가 들었다
#          negation_lost         원문 · 사실 메모의 부정 표현이 그 사실을 쓴 표현에서 사라졌다
#          causal_unsupported    인과 접속("때문에 · 그래서 · 덕분에 · ~니까")이 근거 턴에 없는 인과다
#          time_reversal_undeclared  앞 문단보다 이른 시기로 가는데 composition.reorder 에 사실 · 이유가 없다
#          edit_claim_mismatch   진단 항목의 change 가 result 위치의 실제 변화(edit_trace)와 맞지 않다
#          composition_missing   composition 이 편집본 문단을 하나씩 덮지 않는다
#   review (사람 확인 — 문학적 판단 · 오탐이 있을 수 있는 표면 검사. code_gate 를 바꾸지 않는다)
#          claim_weak            span 이 인용한 사실의 근거 턴과 글자가 거의 겹치지 않는다 — 뜻이 맞는지 본다
#          causal_suspect        "~아서/~어서" 로 두 사실을 이었는데 근거 턴에 그런 말이 없다
#          spoken_carryover      인용 밖 서술에 원문 구어("그거 · 말이다 · ~겠어서 · 걔")가 남았다
#          meta_suspect          글 쓰기 자체를 말하는 안내("기억을 따라가다 · 거슬러 올라가")
#          repeat_phrase         이웃 두 문장에 같은 연도 · 같은 말 묶음이 되풀이된다
#          time_reversal_declared  재배치를 이유와 함께 적었다 — 이유가 납득되는지 사람이 본다
#          composition_mismatch  composition.from 이 실제로 문장이 온 초안 문단과 다르다
#
# 출처가 붙었다고 뜻이 맞다고 보지 않는다 — 위 검사는 표지 · 글자 · 구조만 본다. 뜻의 대조는 검증 · 사람 몫.

EDIT_V6_FILE = "4_편집_v6.md"
EDIT_CONTRACTS = ("v5", "v6")
CLAIM_KINDS = ("claim", "link")
EDIT_CHANGES = ("rewrite", "move", "merge", "split", "cut", "compress", "link", "fact_fix")
UNCOVERED_MAX = 8              # span 밖 서술의 글자(공백 · 부호 뺀) — 이음말 몇 글자는 덮지 않아도 된다
CLAIM_MIN_OVERLAP = 0.15       # span 글자 조각 중 근거 턴 화자 발언에 있는 비율 — 기준선 Pro 초안 · 편집 문장 실측 최저 0.19 · 0.20
REWRITE_RATIO = 0.7            # rewrite 라고 적은 결과 문장의 절반 이상이 초안과 이만큼 덜 닮아야 한다

_QUOTE_PAIRS = {"'": "'", '"': '"', "“": "”", "‘": "’"}
_SENT_END = ".!?…"
_CAUSAL_STRONG = re.compile(r"그래서|그러니|때문에|때문이|덕분에|덕분이|덕에|탓에|탓이|바람에|(?<=[가-힣])니까|므로|는\s?통에")
_CAUSAL_SRC = re.compile(r"그래서|그러니|때문|덕분|덕에|탓|바람에|니까|므로|통에")
_CAUSAL_WEAK = re.compile(r"([가-힣]+)서(?![가-힣])")
_CAUSAL_WEAK_SKIP = re.compile(r"(에|에게|한테|로|으로|부터|께|에게서|그래|서|면)$")     # 「~면서」 는 동시
_MOTIVE = re.compile(r"위해|하려고|싶어서|싶은\s?마음|마음에|생각에|결심|다짐|마음먹")
_SPOKEN = re.compile(r"그거|이거|저거|요거|말이다|거든|더라고|더라\b|잖아|잖니|겠어서|걔|쟤|뭐랄까")
_SPOKEN_TAIL = re.compile(r"는데\s*$")
_META_NARRATIVE = re.compile(r"기억을\s?따라|거슬러\s?올라|이야기를\s?(시작|꺼내|하자면|해\s?보려)|되짚어\s?보"
                             r"|돌이켜\s?보(면|니)|떠올려\s?보(면|니)|이야기(는|가)\s?(여기|이렇게)|기억(들)?을\s?더듬")
_YEAR_EXPR = re.compile(r"(?:19|20)\d{2}\s?년")
_LINK_FEELING = r"그리워|그리운|그리움|외로|쓸쓸|서글|애틋|안타까|가슴|마음이|설레|두려|후회|원망"
_LINK_BAN = re.compile("|".join([*EMOTION_GROUPS.values(), _LINK_FEELING, _CAUSAL_STRONG.pattern, _MOTIVE.pattern]))


def split_sentences(text: str) -> list[tuple[int, int]]:
    """문단 산문을 문장 (시작, 끝) 으로. 인용부호 안의 마침표에서는 끊지 않는다."""
    out, start, quote, i, n = [], 0, None, 0, len(text)

    def close(j):
        nonlocal start
        if text[start:j].strip():
            s = start + (len(text[start:j]) - len(text[start:j].lstrip()))
            out.append((s, j))
        while j < n and text[j].isspace():
            j += 1
        start = j
        return j
    while i < n:
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None             # 인용 뒤에 서술이 이어지는 일이 많아 닫는 따옴표에서는 끊지 않는다
        elif ch in _QUOTE_PAIRS:
            quote = _QUOTE_PAIRS[ch]
        elif ch in _SENT_END:
            j = i + 1
            while j < n and text[j] in _SENT_END + "”’)\"'":
                j += 1
            if j >= n or text[j].isspace():
                i = close(j)
                continue
        i += 1
    end = len(text.rstrip())
    if start < end:
        out.append((start, end))
    return out


def _v6_paragraph(para: dict, where: str) -> tuple[list[dict], list[dict]]:
    """
    문단 산문 → v5 모양의 문장 목록(text · kind · facts · spans). 문장의 facts 는 그 문장 안 claim 들의
    사실 합. span 은 claims 순서대로 본문 앞에서부터 찾는다 — 없거나 겹치면 block.
    """
    text = para["text"]
    findings: list[dict] = []
    placed, cursor = [], 0
    for k, it in enumerate(para["claims"]):
        sp = it["span"]
        pos = text.find(sp, cursor)
        if pos < 0:
            rule, why = (("span_misplaced", "앞 span 과 겹치거나 순서가 다르다") if sp in text
                         else ("span_missing", "문단 본문에 없다"))
            findings.append(_finding(rule, "block", where, f"claims[{k}] span 「{sp[:30]}」 이 {why}", token=f"c{k}"))
            continue
        placed.append({"span": sp, "kind": it["kind"], "facts": list(it["facts"]), "start": pos, "end": pos + len(sp)})
        cursor = pos + len(sp)
    bounds = split_sentences(text)
    for x in placed:
        hit = [i for i, (s, e) in enumerate(bounds) if x["start"] < e and x["end"] > s]
        if len(hit) > 1:
            findings.append(_finding("span_crosses_sentence", "block", f"{where}/s{hit[0]}",
                                     f"span 「{x['span'][:30]}」 이 문장 {len(hit)}개에 걸친다 — 표현은 한 문장 안에서 단다",
                                     token=f"x{x['start']}"))
        x["sentences"] = hit
    sents = []
    for i, (s, e) in enumerate(bounds):
        mine = [x for x in placed if i in x["sentences"]]
        facts: list[str] = []
        for x in mine:
            facts += [f for f in x["facts"] if f not in facts]
        covered = [False] * (e - s)
        for x in mine:
            for j in range(max(x["start"], s), min(x["end"], e)):
                covered[j - s] = True
        runs, cur = [], ""
        for j, ok in enumerate(covered):
            if ok:
                runs.append(cur)
                cur = ""
            else:
                cur += text[s + j]
        runs.append(cur)
        longest = max((_norm(r) for r in runs), key=len, default="")
        if not mine:
            findings.append(_finding("uncovered_text", "fix", f"{where}/s{i}", "근거 표현(claim · link)이 하나도 없는 문장"))
        elif len(longest) >= UNCOVERED_MAX:
            findings.append(_finding("uncovered_text", "fix", f"{where}/s{i}",
                                     f"span 이 덮지 않은 서술 「{longest[:30]}」 — 사실을 말하면 claim, 아니면 link 로 단다"))
        sents.append({"text": text[s:e], "kind": "supported" if facts else "editorial", "facts": facts,
                      "spans": [{k: x[k] for k in ("span", "kind", "facts")} for x in mine]})
    return sents, findings


def check_final_v6(out, analysis: dict, T: set[int], focus: str | None = None) -> tuple[dict, dict[str, str], list[str], list[dict]]:
    """
    v6 편집본의 계약 검사와 변환. 모양이 틀리면 멈추고(PipelineError), 표현 위치 문제는 판정(block · fix)으로
    남긴다 — 편집본을 사람이 볼 수 있게. 돌려주는 것은 (변환한 편집본, 생략 사실 → 이유, 경고, 판정).

    변환한 편집본은 v5 편집본과 같은 키에 chapters[].paragraphs 가 문장 목록이고, 장마다 prose(문단 산문) ·
    composition 을 덧붙인다.
    """
    c = _Check("final_check")
    out = c.obj(out, ("diagnosis", "title", "chapters", "omitted", "checks_resolution", "notes"))
    allowed = set(ledger(analysis))
    diag = c.items(out["diagnosis"], "diagnosis")
    if not diag:
        raise c.fail("format", "diagnosis 가 비었다 — 원고 전체를 본 기록이 없다")
    for i, d in enumerate(diag):
        if not isinstance(d, dict) or not _str_list(d.get("where", [])) or not _str_list(d.get("result", [])):
            raise c.fail("format", f"diagnosis[{i}] 모양이 다르다 (where · result 는 위치 목록)")
        c.text(d.get("issue"), f"diagnosis[{i}].issue")
        c.text(d.get("action", ""), f"diagnosis[{i}].action", nonempty=False)
        if d.get("change") not in EDIT_CHANGES:
            raise c.fail("format", f"diagnosis[{i}].change={d.get('change')!r} — {list(EDIT_CHANGES)} 중 하나")
    c.sentence(out["title"], allowed, "title")
    chapters = out["chapters"]
    if not isinstance(chapters, list) or not chapters:
        raise c.fail("format", "chapters 가 비었거나 목록이 아니다")
    if focus and len(chapters) != 1:
        raise c.fail("chapter_limit", f"{len(chapters)}장 — 한 장 시험(focus)은 정확히 1장")
    if len(chapters) > MAX_CHAPTERS:
        raise c.fail("chapter_limit", f"{len(chapters)}장 — 상한 {MAX_CHAPTERS}장")
    keys = [ch.get("chapter_key") if isinstance(ch, dict) else None for ch in chapters]
    if keys != [f"ch-{n}" for n in range(1, len(keys) + 1)]:
        raise c.fail("reference", f"편집본 장 키 {keys} — ch-1 부터 차례여야 한다")
    findings: list[dict] = []
    converted = []
    for ch in chapters:
        k = ch["chapter_key"]
        missing = [x for x in ("title", "composition", "paragraphs") if x not in ch]
        if missing:
            raise c.fail("format", f"{k} 에 {missing} 가 없다")
        c.text(ch.get("center", ""), f"{k}.center", nonempty=False)
        c.sentence(ch["title"], allowed, f"{k}/title")
        paras = ch["paragraphs"]
        if not isinstance(paras, list) or not paras:
            raise c.fail("format", f"{k}.paragraphs 가 비었거나 목록이 아니다")
        sent_paras = []
        for p, para in enumerate(paras):
            at = f"{k}/p{p}"
            if not isinstance(para, dict):
                raise c.fail("format", f"{at} 가 객체가 아니다 — {{text, claims}}")
            c.text(para.get("text"), f"{at}.text")
            claims = c.items(para.get("claims"), f"{at}.claims")
            if not claims:
                raise c.fail("format", f"{at}.claims 가 비었다")
            for j, x in enumerate(claims):
                w = f"{at}.claims[{j}]"
                if not isinstance(x, dict):
                    raise c.fail("format", f"{w} 가 객체가 아니다")
                c.text(x.get("span"), f"{w}.span")
                if x.get("kind") not in CLAIM_KINDS:
                    raise c.fail("format", f"{w}.kind={x.get('kind')!r}")
                fs = c.ids(x.get("facts"), allowed, f"{w}.facts", nonempty=x["kind"] == "claim")
                if x["kind"] == "link" and fs:
                    raise c.fail("reference", f"{w} 는 link 인데 facts 가 있다 — 사실이 있으면 claim")
            sents, f = _v6_paragraph(para, at)
            findings += f
            if not sents:
                raise c.fail("format", f"{at}.text 에 문장이 없다")
            sent_paras.append(sents)
        comp = c.items(ch["composition"], f"{k}.composition")
        for j, e in enumerate(comp):
            w = f"{k}.composition[{j}]"
            if not isinstance(e, dict) or not _is_int(e.get("paragraph")) or not _str_list(e.get("from", [])):
                raise c.fail("format", f"{w} 모양이 다르다 (paragraph 정수 · from 위치 목록)")
            c.text(e.get("role", ""), f"{w}.role", nonempty=False)
            c.text(e.get("after_previous", ""), f"{w}.after_previous", nonempty=False)
            r = e.get("reorder")
            if r is not None:
                if not isinstance(r, dict):
                    raise c.fail("format", f"{w}.reorder 가 객체가 아니다")
                c.ids(r.get("facts"), allowed, f"{w}.reorder.facts", nonempty=True)
                c.text(r.get("reason"), f"{w}.reorder.reason")
        idx = [e["paragraph"] for e in comp]
        if sorted(idx) != list(range(len(paras))):
            findings.append(_finding("composition_missing", "fix", k,
                                     f"composition 문단 {sorted(idx)} — 편집본 문단 0~{len(paras) - 1} 을 하나씩 적는다"))
        converted.append({"chapter_key": k, "center": ch.get("center", ""), "title": ch["title"],
                          "paragraphs": sent_paras, "prose": [p["text"] for p in paras], "composition": comp})
    omitted = _omitted(c, out, allowed)
    cited = {f for _, _, _, x in _sentences(converted) for f in (x.get("facts") or [])}
    both = sorted(cited & set(omitted))
    if both:
        c.warnings.append(f"사실 {both} 을 본문에 쓰고 omitted 에도 적었다")
    edited = {**{k: out[k] for k in ("diagnosis", "title", "omitted", "checks_resolution", "notes")},
              "chapters": converted, "contract": "v6"}
    return edited, omitted, c.warnings, findings


def _span_texts(x: dict, fact: str | None = None) -> list[str]:
    """문장에서 사실 하나를 쓴 표현들 — v6 는 그 사실을 단 span, v5 는 문장 전체."""
    spans = x.get("spans")
    if spans is None:
        return [x.get("text", "")]
    return [s["span"] for s in spans if fact is None or fact in s["facts"]]


def negation_findings(chapters: list[dict], book: dict[str, dict], data: dict) -> list[dict]:
    """
    원문 화자 발언과 사실 메모에 모두 부정 표현("안 나요 · 못 · 없 · 모르")이 있는 사실을 본문이 썼는데,
    그 사실을 쓴 표현 어디에도 부정 표현이 없다 — fix. 사실 단위로 모아 본다(같은 사실을 두 문장에 나눠 쓴 것은 된다).
    말을 바꿔 써 부정이 사라진 것처럼 보이는 경우(오탐)는 사람이 본다.
    """
    elder = {u["turn"]: _ANSWER_HEAD.sub("", u["elder"]) for u in data["utterances"]}
    uses: dict[str, list[tuple[str, str]]] = {}
    for loc, _, _, x in _sentences(chapters):
        for f in x.get("facts") or []:
            uses.setdefault(f, []).extend((loc, t) for t in _span_texts(x, f))
    out = []
    for f, rows in sorted(uses.items(), key=lambda kv: _fid(kv[0])):
        fact = book.get(f)
        if not fact or not _NEG_FACT.search(fact["text"]):
            continue
        if not any(_NEG_FACT.search(elder.get(t, "")) for t in fact["turns"]):
            continue
        if not any(_NEG_FACT.search(_narration(t) + " " + t) for _, t in rows):
            out.append(_finding("negation_lost", "fix", rows[0][0],
                                f"사실 {f}({fact['text'][:40]}) 의 부정 표현이 본문에서 사라졌다", fact=f))
    return out


def causal_findings(chapters: list[dict], data: dict) -> list[dict]:
    """인과 접속이 근거 턴에 없는 인과인가. 분명한 접속은 fix, "~아서/~어서" 는 사람 확인(review)."""
    elder = {u["turn"]: u["elder"] for u in data["utterances"]}
    out = []
    for loc, _, _, x in _sentences(chapters):
        narr = _narration(x.get("text", ""))
        src = " ".join(elder.get(t, "") for t in x.get("turns", []))
        strong = _CAUSAL_STRONG.search(narr)
        if strong and not _CAUSAL_SRC.search(src):
            out.append(_finding("causal_unsupported", "fix", loc,
                                f"「{strong.group(0)}」 — 근거 턴 {x.get('turns', [])} 에 인과를 말한 곳이 없다"))
            continue
        weak = [m.group(0) for m in _CAUSAL_WEAK.finditer(narr) if not _CAUSAL_WEAK_SKIP.search(m.group(1))]
        src_weak = [m for m in _CAUSAL_WEAK.finditer(src) if not _CAUSAL_WEAK_SKIP.search(m.group(1))]
        if weak and len(x.get("facts") or []) >= 2 and not src_weak and not _CAUSAL_SRC.search(src):
            out.append(_finding("causal_suspect", "review", loc,
                                f"「{weak[0]}」 로 두 사실을 이었다 — 근거 턴에 이은 말이 없다. 인과로 읽히는지 사람이 본다"))
    return out


def style_review_findings(chapters: list[dict]) -> list[dict]:
    """서술 속 원문 구어 · 글 쓰기 안내 · 이웃 문장 반복 — 모두 사람 확인(review)."""
    out = []
    flat = list(_sentences(chapters))
    for loc, _, _, x in flat:
        narr = _narration(x.get("text", ""))
        words = [m.group(0) for m in _SPOKEN.finditer(narr)]
        if _SPOKEN_TAIL.search(narr.rstrip(" .!?…")):
            words.append("~는데(끝)")
        if words:
            out.append(_finding("spoken_carryover", "review", loc, f"서술에 구어 {words} — 인용이 아니면 수필 문장으로"))
        if _META_NARRATIVE.search(narr) and not _META.search(narr):
            out.append(_finding("meta_suspect", "review", loc, "글 쓰기 자체를 말하는 안내 문장일 수 있다"))
    for (la, ca, _, a), (lb, cb, _, b) in zip(flat, flat[1:]):
        if ca is not cb:
            continue
        ta, tb = _narration(a.get("text", "")), _narration(b.get("text", ""))
        years = {re.sub(r"\s", "", y) for y in _YEAR_EXPR.findall(ta)} & {re.sub(r"\s", "", y) for y in _YEAR_EXPR.findall(tb)}
        wa, wb = re.findall(r"[가-힣0-9]{2,}", ta), re.findall(r"[가-힣0-9]{2,}", tb)
        pairs = set(zip(wa, wa[1:])) & set(zip(wb, wb[1:]))
        if years or pairs:
            what = sorted(years) + [" ".join(p) for p in sorted(pairs)]
            out.append(_finding("repeat_phrase", "review", lb, f"앞 문장({la})과 같은 말 {what[:3]}"))
    return out


def reorder_findings(chapters: list[dict], book: dict[str, dict]) -> list[dict]:
    """
    앞 문단보다 이른 시기로 가는 문단 — 시간 표지만으로는 부족하다. 편집이 composition.reorder 에 그
    문단의 이른 사실과 이유를 적었으면 review(이유는 사람이 본다), 아니면 fix. v5 원고는 composition 이
    없어 모두 적지 않은 것으로 본다.
    """
    out = []
    for ch in chapters:
        comp = {e["paragraph"]: e for e in ch.get("composition") or [] if isinstance(e, dict)}
        prev_max = None
        for p, para in enumerate(ch.get("paragraphs", [])):
            fs = [f for x in para for f in (x.get("facts") or [])]
            ys = _para_years(fs, book)
            if not ys:
                continue
            if prev_max is not None and min(ys) < prev_max:
                early = {f for f in fs if any(y < prev_max for y in _full_years((book.get(f) or {}).get("time", "")))}
                r = (comp.get(p) or {}).get("reorder") or {}
                loc = f"{ch['chapter_key']}/p{p}"
                if r.get("reason", "").strip() and early & set(r.get("facts") or []):
                    out.append(_finding("time_reversal_declared", "review", loc,
                                        f"{prev_max}년 뒤에 {min(ys)}년으로 — 이유: {r['reason'][:80]}"))
                else:
                    out.append(_finding("time_reversal_undeclared", "fix", loc,
                                        f"앞 문단({prev_max}년)보다 이른 {min(ys)}년으로 돌아가는데 composition.reorder 에 "
                                        f"사실 {sorted(early, key=_fid)} 과 이유가 없다"))
            prev_max = max(ys) if prev_max is None else max(prev_max, max(ys))
    return out


def span_findings(chapters: list[dict], data: dict, book: dict[str, dict]) -> list[dict]:
    """v6 표현 단위 — 잇는 말의 감정 · 동기 · 인과(fix), 근거 턴과 거의 안 겹치는 claim(review)."""
    elder = {u["turn"]: u["elder"] for u in data["utterances"]}
    out = []
    for loc, _, _, x in _sentences(chapters):
        for j, s in enumerate(x.get("spans") or []):
            if s["kind"] == "link":
                m = _LINK_BAN.search(_narration(s["span"]))
                if m:
                    out.append(_finding("link_content", "fix", loc,
                                        f"잇는 말 「{s['span'][:30]}」 에 「{m.group(0)}」 — 감정 · 동기 · 인과는 근거가 있는 claim 으로만",
                                        token=f"l{j}"))
                continue
            src = _bigrams(_norm(" ".join(elder.get(t, "") for t in fact_turns(s["facts"], book))))
            mine = _bigrams(_norm(_narration(s["span"]) or s["span"]))
            ratio = len(mine & src) / len(mine) if mine else 1.0
            if ratio < CLAIM_MIN_OVERLAP:
                out.append(_finding("claim_weak", "review", loc,
                                    f"「{s['span'][:30]}」 이 사실 {s['facts']} 의 근거 턴과 {ratio:.2f} 만 겹친다 — 뜻이 맞는지 본다",
                                    token=f"c{j}"))
    return out


def v6_findings(chapters: list[dict], data: dict, analysis: dict) -> list[dict]:
    """v6 에서 더한 사실 · 문체 검사. v5 모양 원고(문장 목록)에도 돈다 — 기준선 회귀용."""
    book = ledger(analysis)
    return (negation_findings(chapters, book, data) + causal_findings(chapters, data)
            + style_review_findings(chapters) + reorder_findings(chapters, book)
            + span_findings(chapters, data, book))


def _para_of(loc: str | None) -> str | None:
    return loc.rsplit("/s", 1)[0] if loc else None


def _rows_at(locs: list[str], rows: list[dict], key: str) -> tuple[list[dict], list[str]]:
    """위치(장 · 문단 · 문장) 목록에 드는 추적 행과 해당 행이 없는 위치."""
    got, bad = [], []
    for loc in locs:
        hit = [r for r in rows if r[key] and (r[key] == loc or r[key].startswith(loc + "/"))]
        if not hit:
            bad.append(loc)
        got += [r for r in hit if r not in got]
    return got, bad


def claim_findings(edited: dict, trace: dict) -> list[dict]:
    """
    진단 항목마다 change 가 result(편집본 위치) · where(초안 위치)의 실제 변화와 맞는가 — 코드가 잰
    edit_trace 로 본다. 맞지 않으면 edit_claim_mismatch(fix). 바꾼 양이 적어도 적은 대로 맞게 적었으면 걸리지 않는다.

        rewrite   result 문장의 절반 이상이 새 문장이거나 초안과 REWRITE_RATIO 미만으로 닮음
        move      result 에 순서가 바뀐(옮긴) 문장이 있음
        merge     result 의 한 문단에 초안 두 문단 이상의 문장이 들어옴
        split     where 의 초안 문단 하나가 편집본 두 문단 이상으로 감
        cut · compress  where 의 초안 문장이 빠졌거나 그 사실이 편집본에서 빠짐
        link      result 에 초안에 없던 잇는 문장(editorial)이 있음
        fact_fix  result 에 초안 그대로가 아닌 문장이 있음
    """
    rows = trace.get("sentences", [])
    kinds = {loc: x["kind"] for loc, _, _, x in _sentences(edited.get("chapters", []))}
    draft_facts: dict[str, set] = trace.get("draft_facts_at", {})
    dropped_facts = set(trace.get("dropped_facts", []))
    out = []
    for i, d in enumerate(edited.get("diagnosis", [])):
        change, result, where = d.get("change"), d.get("result") or [], d.get("where") or []
        res, bad_res = _rows_at(result, rows, "at")
        why = None
        if change in ("rewrite", "move", "merge", "link", "fact_fix") and (not result or bad_res):
            why = f"result 위치 {bad_res or '없음'} 가 편집본에 없다"
        elif change == "rewrite":
            low = sum(1 for r in res if r["kind"] == "new" or r["ratio"] < REWRITE_RATIO)
            if low * 2 < len(res):
                why = f"다시 썼다는 문장 {len(res)}개 중 {low}개만 초안과 달라졌다"
        elif change == "move" and not any(r["moved"] for r in res):
            why = "result 에 옮긴 문장이 없다"
        elif change == "merge":
            by_para: dict[str, set] = {}
            for r in res:
                if r["from"]:
                    by_para.setdefault(_para_of(r["at"]), set()).add(_para_of(r["from"]))
            if not any(len(v) >= 2 for v in by_para.values()):
                why = "result 의 어느 문단도 초안 두 문단 이상에서 오지 않았다"
        elif change == "split":
            src, bad = _rows_at(where, rows, "from")
            to: dict[str, set] = {}
            for r in src:
                to.setdefault(_para_of(r["from"]), set()).add(_para_of(r["at"]))
            if not where or not any(len(v) >= 2 for v in to.values()):
                why = "where 의 초안 문단이 편집본 두 문단 이상으로 가지 않았다"
        elif change in ("cut", "compress"):
            gone = [x for x in trace.get("dropped", []) if any(x == w or x.startswith(w + "/") for w in where)]
            lost = {f for w, fs in draft_facts.items() if any(w == x or w.startswith(x + "/") for x in where)
                    for f in fs} & dropped_facts
            if not where or not (gone or lost):
                why = "where 의 초안 문장 · 사실이 빠지지 않았다"
        elif change == "link" and not any(r["kind"] == "new" and kinds.get(r["at"]) == "editorial" for r in res):
            why = "result 에 새 잇는 문장(editorial)이 없다"
        elif change == "fact_fix" and not any(r["kind"] != "kept" for r in res):
            why = "result 문장이 초안 그대로다"
        if why:
            out.append(_finding("edit_claim_mismatch", "fix", "artifact",
                                f"diagnosis[{i}] change={change} — {why}. 진단: {str(d.get('issue', ''))[:60]}",
                                token=f"d{i}"))
    return out


def composition_findings(edited: dict, trace: dict) -> list[dict]:
    """composition.from 과 실제로 문장이 온 초안 문단(edit_trace) — 다르면 사람 확인(review)."""
    actual: dict[str, set] = {}
    for r in trace.get("sentences", []):
        if r["from"]:
            actual.setdefault(_para_of(r["at"]), set()).add(_para_of(r["from"]))
    out = []
    for ch in edited.get("chapters", []):
        for e in ch.get("composition") or []:
            at = f"{ch['chapter_key']}/p{e['paragraph']}"
            said, real = set(e.get("from") or []), actual.get(at, set())
            if said != real and (real - said or said - real):
                out.append(_finding("composition_mismatch", "review", at,
                                    f"composition.from {sorted(said)} · 실제 {sorted(real)} — 새 문장만 있으면 비어 있다"))
    return out


def composition_leaks(edited: dict) -> list[dict]:
    """편집의 구성 메모(role · after_previous · reorder.reason)를 잇는 문장에 그대로 옮겼다 — block(memo_leak)."""
    memos = [m for ch in edited.get("chapters", []) for e in ch.get("composition") or []
             for m in (_norm(e.get("role", "")), _norm(e.get("after_previous", "")),
                       _norm((e.get("reorder") or {}).get("reason", ""))) if len(m) >= 8]
    return [_finding("memo_leak", "block", loc, "편집 구성 메모를 본문에 그대로 옮김")
            for loc in memo_leaks(edited.get("chapters", []), memos)]


_LOC_ALIAS = re.compile(r"^(ch-\d+)/paragraphs?/(\d+)(?:/(?:sentences?/)?(\d+))?$")


def normalize_location(x, locs: set[str]):
    """
    같은 위치의 다른 표기만 계약 표기로 — ch-1/paragraphs/0 → ch-1/p0, ch-1/paragraphs/0/1 ·
    ch-1/paragraphs/0/sentences/1 → ch-1/p0/s1. 바꾼 값이 편집본에 없으면 **그대로 둔다** — 없는 위치를
    통과시키지 않는다(뒤 검사가 막는다). ch-1/omitted 같은 다른 이름은 건드리지 않는다.
    """
    if not isinstance(x, str) or x in locs:
        return x
    m = _LOC_ALIAS.match(x.strip())
    if not m:
        return x
    y = f"{m[1]}/p{m[2]}" + (f"/s{m[3]}" if m[3] else "")
    return y if y in locs else x


def _normalize_verify_locations(out: dict, locs: set[str]) -> list[str]:
    changed: list[str] = []

    def norm(x):
        y = normalize_location(x, locs)
        if y != x:
            changed.append(f"{x}→{y}")
        return y
    for x in out["issues"] if isinstance(out.get("issues"), list) else []:
        if isinstance(x, dict) and "location" in x:
            x["location"] = norm(x["location"])
    for x in out["quality"] if isinstance(out.get("quality"), list) else []:
        if isinstance(x, dict) and _str_list(x.get("locations")):
            x["locations"] = list(dict.fromkeys(norm(y) for y in x["locations"]))
    rl = out.get("reviewed_locations")
    if _str_list(rl) and len(set(rl)) == len(rl):          # 처음부터 겹친 목록은 바꾸지 않는다 — 뒤 검사가 막는다
        out["reviewed_locations"] = list(dict.fromkeys(norm(y) for y in rl))
    return changed


def check_verify(out, T: set[int], locs: set[str]) -> list[str]:
    """
    검증 출력. 사실 issues(지금과 같음)에 구성 채점 quality 가 더해진다 — Q1~Q6 각각 한 번,
    점수 0 · 1 · 2. 근거 위치(locations) 가운데 편집본에 없는 것은 근거가 아니므로 지우고 경고로
    남긴다 — 근거 위치가 빈 점수는 실패로 막지 않고 adjust_quality 가 0점으로 센다.
    """
    c = _Check("verify")
    out = c.obj(out, ("review_status", "verdict", "issues", "quality", "reviewed_locations", "missing_context"))
    changed = _normalize_verify_locations(out, locs)
    if changed:
        c.warnings.append(f"위치 표기 {len(changed)}개를 같은 뜻의 계약 표기로 바꿨다 — {changed[:4]}")
    rs, verdict = out["review_status"], out["verdict"]
    if rs not in ("completed", "needs_context", "not_applicable"):
        raise c.fail("format", f"review_status={rs!r}")
    if rs == "completed" and verdict not in ("pass", "revise", "ask_user"):
        raise c.fail("format", f"completed 인데 verdict={verdict!r}")
    if rs != "completed" and verdict is not None:
        raise c.fail("format", f"{rs} 인데 verdict={verdict!r}")
    for i, x in enumerate(c.items(out["issues"], "issues")):
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
    q = c.items(out["quality"], "quality")
    if rs == "completed":
        items = [x.get("item") if isinstance(x, dict) else None for x in q]
        if sorted(items, key=str) != sorted(QUALITY_ITEMS):
            raise c.fail("format", f"quality 항목 {items} — {list(QUALITY_ITEMS)} 를 한 번씩")
        for x in q:
            at = f"quality.{x['item']}"
            if x.get("score") not in (0, 1, 2) or isinstance(x.get("score"), bool):
                raise c.fail("format", f"{at}.score={x.get('score')!r} — 0 · 1 · 2")
            if not _str_list(x.get("locations")):
                raise c.fail("format", f"{at}.locations 가 문자열 목록이 아니다")
            unknown = [y for y in x["locations"] if y not in locs]
            if unknown:
                c.warnings.append(f"{at}.locations {unknown[:3]} — 편집본에 없는 위치라 근거에서 뺐다")
                x["locations"] = [y for y in x["locations"] if y in locs]
            c.text(x.get("reason"), f"{at}.reason")
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


def adjust_quality(quality: list[dict], signals: list[dict], findings: list[dict]) -> dict:
    """
    검증 모델의 구성 채점을 코드가 다시 본다 — 같은 계열 모델이 자기 글을 관대하게 채점하는 것을 막는다.

        근거 위치가 빈 점수            → 0
        발언 나열 신호가 있는 장이 있음 → Q2 · Q3 · Q5 는 1 을 넘지 않는다
        문체 · 답 흔적 경고가 남음      → Q6 은 1 을 넘지 않는다

    meets_bar: Q1~Q5 가운데 2점이 넷 이상이고 0점이 없으며 Q6 이 2점. **출판 가능 판정이 아니다** —
    사실(Q7)과 독자 시험(Q8)은 사람이 한다.
    """
    raw = {x["item"]: x["score"] for x in quality}
    scores = dict(raw)
    adjusted = []

    def cap(item, to, why):
        if scores.get(item, 0) > to:
            adjusted.append({"item": item, "from": scores[item], "to": to, "why": why})
            scores[item] = to
    for x in quality:
        if not x.get("locations"):
            cap(x["item"], 0, "근거 위치 없음")
    listing = [s["chapter_key"] for s in signals if s.get("listing")]
    if listing:
        for item in ("Q2", "Q3", "Q5"):
            cap(item, 1, f"발언 나열 신호 {listing}")
    if any(f["rule"] in ("style_mix", "answer_trace") for f in findings):
        cap("Q6", 1, "문체 · 답 흔적 코드 경고가 남음")
    core = [scores.get(k, 0) for k in ("Q1", "Q2", "Q3", "Q4", "Q5")]
    meets = sum(1 for v in core if v == 2) >= 4 and min(core) >= 1 and scores.get("Q6", 0) == 2
    return {"raw": raw, "scores": scores, "adjusted": adjusted, "meets_bar": bool(quality) and meets}


def overall_state(generation_state: str, gate: dict | None, verification: dict, human: str,
                  quality: dict | None = None) -> str:
    """
    최종 상태. **approved 는 사람만 만든다** — 코드 · 모델 판정으로는 awaiting_human 까지다.

        draft_only       장 집필 비교 실행 — 편집 · 검증을 부르지 않았다(완성본이 아니다)
        edit_only        편집 단독 시험 — 코드 판정 pass, 검증을 부르지 않았다 (blocked · attention 이면
                         blocked_by_code · needs_revision)
        not_generated    생성이 끝나지 않음 (failed · partial · needs_context · insufficient)
        blocked_by_code  code_gate=blocked
        needs_revision   code_gate=attention · 사실 대조가 revise/ask_user · 구성 채점 기준 미달 · 검증이 끝나지 않음
        awaiting_human   코드 pass · 사실 대조 pass · 구성 채점 기준 충족 — 사람 검수 대기
        approved         human_review=passed
    """
    if generation_state == DRAFT_ONLY:
        return "draft_only"                       # 장 집필 비교 — 편집 · 검증 전이라 판정하지 않는다
    if generation_state == EDIT_ONLY:                 # 검증 전 — 코드 판정만 본다
        state = (gate or {}).get("state")
        return "blocked_by_code" if state == "blocked" else "needs_revision" if state == "attention" else "edit_only"
    if generation_state != GENERATED:
        return "not_generated"
    if (gate or {}).get("state") == "blocked":
        return "blocked_by_code"
    if human == "passed":
        return "approved"
    if ((gate or {}).get("state") != "pass" or verification.get("state") != "completed"
            or verification.get("verdict") != "pass" or not (quality or {}).get("meets_bar")):
        return "needs_revision"
    return "awaiting_human"


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
    "source 는 고른 회차의 말씀을 합친 원자료다. utterances.turn 은 이 요청의 전역 원문 번호다. "
    "elder 는 사용자 발언, asked 는 AI 질문이다. sessions.recorded_order 는 기록 순서이며 사건 "
    "순서가 아니다. shared_state.facts_found 는 대화 중 정리한 메모이고 원문이 아니다."
)
_EXCLUSION_HEAD = (
    "\nexclusions 는 사용자가 빼 달라고 한 범위다. mode=whole 인 턴과 요청 턴(requested_in)은 "
    "source 에서 이미 뺐다. mode=partial 인 턴은 남길 내용이 있어 source 에 남아 있다 — 그 턴에서 "
    "scope 에 해당하는 내용은 본문 · 제목 · 메모 어디에도 쓰지 않는다."
)


def analysis_message(data: dict) -> str:
    head = (_SOURCE_HEAD + "\nturn_marks 는 코드가 발언 말끝에서 찾은 표시다 — heard 는 들은 이야기의 "
            "말투(~대요 · ~다고 하더라고요), uncertain 은 흐린 말투(~쯤 · ~였나 · ~일 거예요)가 있다는 "
            "뜻이다. 한 턴에 들은 이야기와 직접 기억이 섞일 수 있으니 사실마다 다시 정한다.")
    return _user(head, {"turn_marks": turn_marks(data), "source": data})


def _analysis_for_next(analysis: dict) -> dict:
    """
    뒤 단계에 넘길 분석 — 상태 · 모름 목록은 빼고 원장 · 단위 · 끈 · 정정 · 주제만. 정정은 **정정 이력
    (before)을 빼고** 유효 사실 id · 턴 · 정정 뒤 값만 넘긴다 — 정정 전 값이 목차 · 본문으로 가는 길을 막는다.
    """
    keep = ("facts", "units", "threads", "people", "themes", "direction", "exclusions")      # normalized 는 기록만
    out = {k: analysis.get(k) for k in keep}
    out["corrections"] = [{"fact": c["fact"], "turns": c["turns"], "after": c.get("after", "")}
                          for c in analysis.get("corrections", [])]
    return out


def outline_message(data: dict, analysis: dict, focus: str | None = None) -> str:
    head = (_SOURCE_HEAD + "\nanalysis 는 앞 단계의 사실 원장(facts) · 기억 단위(units) · 끈(threads) · "
            "정정(corrections)이다. 편집 참고일 뿐 사실 근거가 아니다 — source 와 다시 대조한다. "
            "must_keep 은 근거 없이 빠지면 안 되는 사실 id 다.")
    payload: dict = {"analysis": _analysis_for_next(analysis),
                     "must_keep": sorted(must_keep(analysis), key=lambda x: int(x[1:]))}
    if focus:
        head += ("\nfocus 는 이번 원고의 범위다 — 이 소재로 **장 하나만** 설계한다. 이 장에 쓰지 않는 "
                 "사실은 omit 에 이유와 함께 적는다.")
        payload["focus"] = {"theme": focus, "chapters": 1}
    if analysis.get("exclusions"):
        head += _EXCLUSION_HEAD
    payload["source"] = stage_source(data, analysis)
    return _user(head, payload)


def chapter_message(src: dict, analysis: dict, outline_out: dict, chapter: dict) -> str:
    head = (_SOURCE_HEAD + "\n이 source 는 이번 장 문단 계획의 사실이 가리키는 원문만 남긴 것이다. "
            "다른 장의 원문은 일부러 뺐다. utterances 는 문단 계획 순서로 놓았다(번호와 글은 그대로). "
            "book 은 책 전체 설계, chapter 는 이번에 쓸 장의 설계도(중심 · 핵심 경험 · 문단 계획 · 재배치 "
            "이유), other_chapters 는 앞뒤 장의 이름과 중심이다. facts 는 이 장에서 쓸 사실 원장 — "
            "source(heard = 들은 이야기)와 certainty(approx · uncertain = 흐린 기억)를 그대로 지킨다. "
            "문장의 facts 에는 이 facts 의 id 만 쓴다.")
    book = ledger(analysis)
    mine = plan_facts(chapter)
    payload: dict = {
        "book": {k: outline_out["book"].get(k) for k in ("title", "center", "flow", "opening_facts", "closing_facts")},
        "chapter": chapter,
        "other_chapters": [{"chapter_key": c["chapter_key"], "title": c["title"]["text"], "center": c["center"]}
                           for c in outline_out["chapters"] if c["chapter_key"] != chapter["chapter_key"]],
        "facts": [book[f] for f in mine if f in book],
        "people": analysis.get("people", []),
    }
    if any(p.get("core") for p in chapter.get("paragraphs", [])):
        head += ("\n문단 계획의 core 는 그 문단이 꼭 담아야 할 핵심 사실이다. 나머지 facts · brief 는 흐름에 맞게 "
                 "골라 쓰는 보조 사실이다.")
    notices = exclusion_notices(analysis, set(fact_turns(mine, book)))
    if notices:
        head += _EXCLUSION_HEAD
        payload["exclusions"] = notices
    payload["source"] = src
    return _user(head, payload)


def edit_message(data: dict, analysis: dict, outline_out: dict, drafts: list[dict],
                 checks: list[dict], signals: list[dict], focus: str | None = None,
                 review_notes: list[dict] | None = None) -> str:
    head = (_SOURCE_HEAD + "\nbook_plan 은 목차의 책 설계도다 — **제안일 뿐이고 바꿀 수 있다.** drafts 는 장마다 "
            "따로 쓴 초안이다(문장의 turns 는 코드가 facts 에서 펼친 것). 초안은 사실 근거가 아니다 — "
            "source · facts 와 다시 대조한다. facts 는 전체 사실 원장, must_keep 은 근거 없이 빠지면 안 되는 "
            "사실, outline_omit 은 목차가 뺀 사실과 이유다. checks 는 코드가 초안에서 찾은 고칠 곳(location 은 "
            "초안 위치)이고, signals 는 장마다 발언 나열 신호다(listing=true 면 그 장은 발언을 한 턴씩 옮긴 "
            "꼴이다). 문장의 facts 에는 facts 의 id 만 쓴다.")
    payload: dict = {
        "book_plan": {"book": outline_out["book"], "chapters": outline_out["chapters"]},
        "drafts": drafts,
        "facts": analysis.get("facts", []),
        "units": analysis.get("units", []),
        "must_keep": sorted(must_keep(analysis), key=lambda x: int(x[1:])),
        "outline_omit": outline_out.get("omit", []),
        "checks": checks,
        "signals": signals,
    }
    missing = missing_core(checks, analysis, outline_out)
    if missing:
        head += ("\nmissing_core 는 장 초안이 빠뜨린 목차의 **핵심 사실**이다(보조 사실은 골라 쓴다). 원문의 사실 · "
                 "들은 이야기 · 흐린 기억 · 감정을 그대로 지켜 본문에 되살리거나, 빼야 할 까닭이 있으면 omitted 에 "
                 "이유와 함께 적는다. 이유 없이 빠진 채 남으면 고칠 곳으로 남는다.")
        payload["missing_core"] = missing
    if review_notes:
        head += ("\nreview_notes 는 사람 검토가 초안에서 찾은 문제다(location 은 초안 위치, turns 는 근거 원문 턴). "
                 "고칠 문장은 주지 않는다 — 원문 · 사실 원장과 대조해 판단하고, 진단(diagnosis)에 반영한다.")
        payload["review_notes"] = review_notes
    if focus:
        head += "\nfocus 는 이번 원고의 범위다 — 한 장 시험이라 편집본도 **장 하나**다(나누지 않는다)."
        payload["focus"] = {"theme": focus, "chapters": 1}
    if analysis.get("exclusions"):
        head += _EXCLUSION_HEAD
        payload["exclusions"] = exclusion_notices(analysis)
    payload["source"] = stage_source(data, analysis)
    return _user(head, payload)


def edit_message_v6(data: dict, analysis: dict, outline_out: dict, drafts: list[dict],
                    checks: list[dict], signals: list[dict], focus: str | None = None,
                    review_notes: list[dict] | None = None) -> str:
    """
    v6 편집 자료. v5 와 다른 것: 초안을 **문단 산문**(문단 위치 · 산문 · 그 문단의 사실 id)으로 주고 문장 객체를
    주지 않는다. 목차는 장의 중심 · 핵심 경험과 문단의 역할 · 시기 · 핵심 사실만(문단별 facts 배열은 뺀다).
    checks 는 block · fix 만, 초안 문장 위치에는 그 문장을 quote 로 붙인다.
    """
    head = (_SOURCE_HEAD + "\nbook_plan 은 목차의 장 중심 · 핵심 경험과 문단 역할 · 시기 · 핵심 사실(core)이다 — "
            "**제안일 뿐이고 바꿀 수 있다**(core 사실은 지킨다). drafts 는 장 초안을 문단 산문으로 옮긴 것이다(location 은 "
            "초안 문단 위치, facts 는 그 문단이 쓴 사실 id). 초안은 사실 근거가 아니다 — source · facts 와 다시 대조한다. "
            "facts 는 전체 사실 원장이다. 원장의 text 는 사실 메모이지 문장이 아니다 — 메모의 말투를 서술에 옮기지 않는다. "
            "core_facts 는 빠뜨리면 안 되는 핵심 사실, must_keep 은 근거 없이 빠지면 안 되는 사실, outline_omit 은 목차가 "
            "뺀 사실이다(다시 적지 않는다). checks 는 코드가 초안에서 찾은 고칠 곳(quote 는 그 초안 문장)이고, signals 는 "
            "발언 나열 신호다. claims 의 facts 에는 facts 의 id 만 쓴다.")
    loc_text = {loc: x["text"] for loc, _, _, x in _sentences(drafts)}
    plan_chapters = []
    for ch in outline_out["chapters"]:
        plan_chapters.append({
            "chapter_key": ch["chapter_key"], "title": ch["title"]["text"], "center": ch.get("center", ""),
            "experience": ch.get("experience", ""),
            "paragraphs": [{"role": p.get("role", ""), "time": p.get("time", ""), "core": p.get("core") or []}
                           for p in ch.get("paragraphs", [])]})
    prose = []
    for d in drafts:
        paras = []
        for p, para in enumerate(d["paragraphs"]):
            fs: list[str] = []
            for x in para:
                fs += [f for f in x.get("facts") or [] if f not in fs]
            paras.append({"location": f"{d['chapter_key']}/p{p}", "text": " ".join(x["text"] for x in para),
                          "facts": fs})
        prose.append({"chapter_key": d["chapter_key"], "title": d["title"]["text"], "paragraphs": paras})
    core = plan_core(outline_out)
    payload: dict = {
        "book_plan": {"book": {k: outline_out["book"].get(k) for k in ("title", "center", "flow")},
                      "chapters": plan_chapters},
        "drafts": prose,
        "facts": analysis.get("facts", []),
        "core_facts": sorted(core, key=_fid),
        "must_keep": sorted(must_keep(analysis) - set(core), key=_fid),
        "outline_omit": outline_out.get("omit", []),
        "checks": [{**{k: c[k] for k in ("id", "rule", "severity", "location", "detail")},
                    **({"quote": loc_text[c["location"]]} if c["location"] in loc_text else {})}
                   for c in checks if c["severity"] in ("block", "fix")],
        "signals": signals,
    }
    missing = missing_core(checks, analysis, outline_out)
    if missing:
        head += ("\nmissing_core 는 장 초안이 빠뜨린 핵심 사실이다. 원문의 사실 · 들은 이야기 · 흐린 기억 · 감정을 그대로 "
                 "지켜 본문에 되살리거나, 빼야 할 까닭이 있으면 omitted 에 이유와 함께 적는다.")
        payload["missing_core"] = missing
    if review_notes:
        head += ("\nreview_notes 는 사람 검토가 초안에서 찾은 문제다(location 은 초안 위치, quote 는 그 초안 문장, turns 는 "
                 "근거 원문 턴). 고칠 문장은 주지 않는다 — 원문 · 사실 원장과 대조해 고치고, 고친 것은 diagnosis 에 "
                 "change \"fact_fix\" 로 적는다. 지적 목록이 구성 진단을 대신하지 않는다.")
        payload["review_notes"] = [{**n, **({"quote": loc_text[n["location"]]} if n["location"] in loc_text else {})}
                                   for n in review_notes]
    if focus:
        head += "\nfocus 는 이번 원고의 범위다 — 한 장 시험이라 편집본도 **장 하나**다(나누지 않는다)."
        payload["focus"] = {"theme": focus, "chapters": 1}
    if analysis.get("exclusions"):
        head += _EXCLUSION_HEAD
        payload["exclusions"] = exclusion_notices(analysis)
    payload["source"] = stage_source(data, analysis)
    return _user(head, payload)


def missing_core(checks: list[dict], analysis: dict, outline_out: dict) -> list[dict]:
    """장 초안 판정의 core_missing → 편집에 넘길 목록. 사실 원장의 출처 · 흐림 · 턴과 문단 역할을 함께."""
    book = ledger(analysis)
    roles = {f"{ch['chapter_key']}/p{p}": para.get("role", "")
             for ch in outline_out.get("chapters", []) for p, para in enumerate(ch.get("paragraphs", []))}
    out = []
    for c in checks:
        f = c.get("fact")
        if c.get("rule") != "core_missing" or f not in book:
            continue
        x = book[f]
        out.append({"check_id": c["id"], "fact": f, "plan": c.get("plan"), "role": roles.get(c.get("plan"), ""),
                    **{k: x.get(k) for k in ("text", "turns", "time", "source", "certainty")}})
    return out


def verify_plan(analysis: dict, outline_out: dict, steps: list[dict] | None = None) -> dict:
    """구성 채점에 쓸 계획 — 책 · 장의 중심과 핵심 경험, 앞 단계 코드 경고. 사실 근거가 아니다."""
    checks = [f"{s['stage']}{'/' + s['chapter_key'] if s.get('chapter_key') else ''}: {w}"
              for s in steps or [] for w in s.get("warnings") or []]
    return {
        "checks": checks,
        "direction": analysis.get("direction"),
        "book": {"center": outline_out["book"].get("center", ""), "flow": outline_out["book"].get("flow", "")},
        "chapters": [{"chapter_key": ch["chapter_key"], "center": ch["center"], "experience": ch["experience"]}
                     for ch in outline_out["chapters"]],
    }


def verify_message(data: dict, analysis: dict, edited: dict, T: set[int], plan: dict,
                   exclusions: list | None = None) -> str:
    """검증은 재등장을 찾아야 하니 원자료 전부를 받는다 — 빼 달라고 한 턴도 source 에 있다."""
    head = (_SOURCE_HEAD + "\ncandidate 는 검증할 편집본이다(문장의 facts 는 사실 원장 id, turns 는 코드가 "
            "펼친 원문 턴). facts 는 사실 원장이다 — source(heard = 들은 이야기) · certainty 를 문장과 견준다. "
            "plan 은 목차의 책 · 장 설계이고 구성 채점에만 쓴다(사실 근거가 아니다). plan.signals 는 장마다 "
            "발언 나열 신호, plan.edit_trace 는 코드가 잰 편집 전후 변화, plan.code_findings 는 편집본의 코드 "
            "판정이다. plan.omission_review 는 코드가 찾은 누락 검토 후보(확정 누락이 아니다 — 사실마다 원문 근거 · "
            "초안 표현 · 편집본 표현), plan.protected_omissions 는 보호 대상(핵심 사실 · must_keep · 일화 전체)의 "
            "미해결 누락이다 — 원문과 대조해 정상 통합 · 부수 축약과 의미 손실을 가른다. review_scope.turns 는 이번 검토 범위 전체이고 complete=true 는 그 원문이 빠짐없이 "
            "source 에 있다는 뜻이다.")
    payload = {"artifact_type": "memoir_chapters", "candidate": edited, "facts": analysis.get("facts", []),
               "plan": plan}
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
                  chapter_key: str | None = None, system: str | None = None) -> tuple[Any, dict]:
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

        spec = CallSpec(stage, chapter_key, system or prompt(stage), user,
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
            metrics: dict | None = None, gate: dict | None = None, quality: dict | None = None,
            trace: dict | None = None, focus: str | None = None) -> dict:
    edited = edited if state in (GENERATED, DRAFT_ONLY, EDIT_ONLY) else None
    verification = verification or {"state": "not_run", "verdict": None, "issues": [],
                                    "reviewed_locations": [], "missing_context": []}
    human = "not_run"                            # 코드는 늘 not_run 으로 쓴다 — 사람이 R1 에 적는다
    gate = gate or {"state": "not_run", "findings": [], "counts": {}}
    return {
        "generation_state": state,
        "pipeline_complete": complete,
        "code_gate": gate["state"],
        "model_verdict": verification.get("verdict"),
        "model_quality": quality,
        "human_review": human,
        "overall": overall_state(state, gate if gate["state"] != "not_run" else None, verification, human, quality),
        "failure": failure.as_dict() if failure else None,
        "focus": focus,
        "title": edited["title"] if edited else None,
        "chapters": edited["chapters"] if edited else [],
        "diagnosis": edited.get("diagnosis", []) if edited else [],
        "omitted": edited.get("omitted", []) if edited else [],
        "verification": verification,
        "code_findings": gate.get("findings", []),
        "edit_trace": (trace or {}).get("summary"),
        "metrics": metrics or {},
        "calls": calls,
        "prompt_version": PROMPT_VERSION,
        "analysis_source": "model", "outline_source": "model",
    }


REVIEWED_FIXTURE = "reviewed_fixture"     # 분석이 모델이 아니라 사람이 고친 시험용 스냅샷에서 왔다
_FIXTURE_EDIT_KINDS = ("fact.set", "fact.add", "unit.set", "unit.move", "unit.split", "unit.add",
                       "thread.set", "thread.add", "theme.set", "direction.set")


def load_analysis_fixture(fx, data: dict, T: set[int]) -> dict:
    """
    후속 단계 시험용 분석 스냅샷을 받는다 — 맞지 않으면 모델을 부르지 않고 입력 거부.

        fixture=analysis_snapshot · analysis_source=reviewed_fixture · synthetic=true
        input_ref 가 지금 입력과 같다 (같은 원문)
        edits — 모델 원본에서 고친 것을 하나하나(종류 · 대상 · 이유 · 근거 턴) 적었다. 비면 안 된다
        based_on — 어느 모델 실행의 출력을 고쳤는지
        analysis — 분석 계약 검사를 **오류 없이** 통과 (경고는 남긴다)

    스냅샷은 시험 도구다. 서비스의 분석 단계를 대신하지 않고, 결과에는 analysis_source 로 늘 표시한다.
    """
    def bad(why):
        return PipelineError("input", "input", f"분석 스냅샷: {why}")
    if not isinstance(fx, dict) or fx.get("fixture") != "analysis_snapshot":
        raise bad("fixture=analysis_snapshot 이 아니다")
    if fx.get("analysis_source") != REVIEWED_FIXTURE or fx.get("synthetic") is not True:
        raise bad("analysis_source=reviewed_fixture · synthetic=true 가 아니다")
    if fx.get("input_ref") != input_ref(data):
        raise bad(f"input_ref {fx.get('input_ref')!r} — 지금 입력 {input_ref(data)} 과 다르다")
    based = fx.get("based_on")
    if not isinstance(based, dict) or not based.get("run_ref") or not based.get("model"):
        raise bad("based_on(고친 바탕이 된 모델 실행)이 없다")
    edits = fx.get("edits")
    if not isinstance(edits, list) or not edits:
        raise bad("edits(고친 기록)가 없다")
    for i, e in enumerate(edits):
        if (not isinstance(e, dict) or e.get("kind") not in _FIXTURE_EDIT_KINDS or not str(e.get("reason", "")).strip()
                or not _int_list(e.get("turns")) or set(e["turns"]) - T):
            raise bad(f"edits[{i}] 모양이 다르다(종류 · 이유 · 근거 턴)")
    analysis = json.loads(json.dumps(fx.get("analysis")))
    try:
        status, _ = check_analysis(analysis, T, turn_marks(data), source_texts(data), source_asked(data))
    except PipelineError as e:
        raise bad(f"분석 계약 위반 — {e.message[:300]}") from e
    if status != "ready":
        raise bad(f"status={status}")
    return analysis


def load_outline_fixture(fx, analysis: dict, analysis_fixture: dict, T: set[int]) -> tuple[dict, str]:
    """
    사람이 검토한 시험용 목차를 받는다 — 맞지 않으면 모델을 부르지 않고 입력 거부. 돌려주는 것은 (목차, focus).

        fixture=outline_snapshot · outline_source=reviewed_fixture · synthetic=true
        analysis_fixture 의 sha256(앞 16자)이 지금 받은 분석 스냅샷과 같다 — 같은 사실 원장 위의 목차
        memories — 시험이 꼭 다뤄야 할 기억과 그 사실 id. 모두 원장에 있고, 목차에서 빼지 않았다
        목차 메모(center · experience · flow · role · reason)는 짧은 메모 — 완성된 본문 문장(…다.)을 넣지 않는다
        outline — 목차 계약 검사를 오류 없이 통과, 혼입 · 일괄 생략 경고가 없다

    자동 목차 생성이 성공한 것이 아니다. 결과에는 outline_source=reviewed_fixture 로 늘 표시한다.
    """
    def bad(why):
        return PipelineError("input", "input", f"목차 스냅샷: {why}")
    if not isinstance(fx, dict) or fx.get("fixture") != "outline_snapshot":
        raise bad("fixture=outline_snapshot 이 아니다")
    if fx.get("outline_source") != REVIEWED_FIXTURE or fx.get("synthetic") is not True:
        raise bad("outline_source=reviewed_fixture · synthetic=true 가 아니다")
    sha = hashlib.sha256(json.dumps(analysis_fixture, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    if (fx.get("analysis_fixture") or {}).get("sha256") != sha:
        raise bad("analysis_fixture.sha256 이 지금 분석 스냅샷과 다르다 — 다른 사실 원장 위의 목차")
    focus = fx.get("focus")
    if not isinstance(focus, str) or not focus.strip():
        raise bad("focus 가 없다")
    outline = json.loads(json.dumps(fx.get("outline")))
    status, warnings = check_outline(outline, analysis, T, focus)
    if status != "ready":
        raise bad(f"status={status}")
    risky = [w for w in warnings if "섞였다" in w or "한꺼번에 생략" in w]
    if risky:
        raise bad(f"목차 경고 — {risky[:2]}")
    used = {f for ch in outline["chapters"] for p in ch["paragraphs"] for f in list(p["facts"]) + list(p.get("brief") or [])}
    book = ledger(analysis)
    mem = fx.get("memories")
    if not isinstance(mem, list) or not mem:
        raise bad("memories(다뤄야 할 기억)가 없다")
    for m in mem:
        fs = (m or {}).get("facts") or []
        if not fs or set(fs) - set(book) or set(fs) - used:
            raise bad(f"기억 「{(m or {}).get('name')}」 의 사실 {sorted(set(fs) - used)} 이 원장에 없거나 목차에서 빠졌다")
    core = plan_core(outline)
    if core:                                  # 핵심 · 보조를 나눈 목차 — 다뤄야 할 기억마다 핵심 사실이 있어야 한다
        for m in mem:
            if not set(m["facts"]) & set(core):
                raise bad(f"기억 「{m.get('name')}」 에 핵심 사실(core)이 없다 — 빠져도 잡히지 않는다")
    memos = [outline["book"].get("center", ""), outline["book"].get("flow", "")]
    for ch in outline["chapters"]:
        memos += [ch.get("center", ""), ch.get("experience", "")] + [p.get("role", "") for p in ch["paragraphs"]]
        memos += [r.get("reason", "") for r in ch.get("reorder", [])]
    if any(re.search(r"다\.\s*$", m or "") or len(m or "") > TRIAL_MAX_MEMO for m in memos):
        raise bad("목차 메모에 완성된 본문 문장(…다.)이나 긴 글이 있다 — 예상 본문을 넣지 않는다")
    return outline, focus


TRIAL_MAX_MEMO = 80         # 시험용 목차 메모 한 칸의 최대 글자 — 본문 같은 글이 들어오지 않게


def load_draft_fixture(fx, outline_fixture: dict, outline: dict, analysis: dict, data: dict) -> tuple[list[dict], dict]:
    """
    편집 단독 시험의 입력 — 장 집필 비교(--chapter-only)가 남긴 초안을 **그대로** 받는다. 돌려주는 것은
    (초안들, 출처). 맞지 않으면 모델을 부르지 않고 입력 거부.

        fx = {"run": 그 실행의 run.json, "outline_fixture": 그 실행의 02_outline_fixture.json, "drafts": [03_ch-*.json]}
        draft_only 실행 · 분석 · 목차 출처 reviewed_fixture · 같은 input_ref · 같은 목차 스냅샷
        장 단계가 모두 성공했고 초안 수 · chapter_key 가 목차와 같다
        초안마다 장 집필 계약 검사(check_chapter)를 다시 통과
    """
    def bad(why):
        return PipelineError("input", "input", f"초안 스냅샷: {why}")
    if not isinstance(fx, dict) or not isinstance(fx.get("run"), dict) or not isinstance(fx.get("drafts"), list):
        raise bad("run · drafts 가 없다")
    run_doc = fx["run"]
    if run_doc.get("generation_state") != DRAFT_ONLY or not (run_doc.get("settings") or {}).get("chapter_only"):
        raise bad("장 집필 비교(draft_only) 실행이 아니다")
    if run_doc.get("analysis_source") != REVIEWED_FIXTURE or run_doc.get("outline_source") != REVIEWED_FIXTURE:
        raise bad("분석 · 목차 출처가 reviewed_fixture 가 아니다")
    if run_doc.get("input_ref") != input_ref(data):
        raise bad(f"input_ref {run_doc.get('input_ref')!r} — 지금 입력 {input_ref(data)} 과 다르다")
    if fx.get("outline_fixture") != outline_fixture:
        raise bad("초안을 쓴 목차 스냅샷이 지금 받은 목차 스냅샷과 다르다")
    keys = [ch["chapter_key"] for ch in outline["chapters"]]
    steps = [s for s in run_doc.get("steps") or [] if s.get("stage") == "chapter"]
    if [s.get("chapter_key") for s in steps] != keys or not all(s.get("ok") for s in steps):
        raise bad("장 단계가 목차의 장마다 성공한 기록이 아니다")
    drafts = json.loads(json.dumps(fx["drafts"]))
    if [d.get("chapter_key") if isinstance(d, dict) else None for d in drafts] != keys:
        raise bad("초안의 chapter_key 가 목차와 다르다")
    memos = outline_memos(outline)
    for d, ch in zip(drafts, outline["chapters"]):
        try:
            check_chapter(json.loads(json.dumps(d)), ch, set(plan_facts(ch)), memos)
        except PipelineError as e:
            raise bad(f"{ch['chapter_key']} 장 집필 계약 위반 — {e.message[:200]}") from e
    cfg = run_doc.get("settings") or {}
    source = {"run_ref": run_doc.get("run_ref"), "model": cfg.get("MEMOIR_PIPE_TEXT_MODEL"),
              "temperature": cfg.get("MEMOIR_PIPE_TEMPERATURE"),
              "sha256": [hashlib.sha256(json.dumps(d, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
                         for d in drafts]}
    return drafts, source


REVIEW_NOTE_KEYS = {"location", "issue", "turns"}
REVIEW_NOTE_MAX = 160       # 지적 한 칸의 최대 글자 — 고칠 문장 · 예상 본문이 들어오지 않게


def check_review_notes(doc, drafts: list[dict], draft_run_ref: str | None, T: set[int]) -> list[dict]:
    """
    편집에 넘길 사람 검토 지적 — 초안의 어디가 왜 문제인지만. 고칠 방법 · 바꿀 문장은 받지 않는다.

        based_on 이 초안 실행(run_ref)과 같다 · reviewed_by 가 있다
        지적마다 {location, issue, turns} 만 — location 은 초안에 실제로 있는 위치, turns 는 원문 턴
    """
    def bad(why):
        return PipelineError("input", "input", f"검토 지적: {why}")
    if not isinstance(doc, dict) or doc.get("based_on") != draft_run_ref or not str(doc.get("reviewed_by", "")).strip():
        raise bad("based_on(초안 실행) · reviewed_by 가 맞지 않다")
    notes = doc.get("notes")
    if not isinstance(notes, list) or not notes:
        raise bad("notes 가 없다")
    locs = locations({"chapters": drafts})
    for i, n in enumerate(notes):
        if not isinstance(n, dict) or set(n) - REVIEW_NOTE_KEYS:
            raise bad(f"notes[{i}] 에 {sorted(set(n) - REVIEW_NOTE_KEYS) if isinstance(n, dict) else n!r} — "
                      "위치 · 문제 · 근거 턴만 적는다(고칠 문장은 넣지 않는다)")
        if n.get("location") not in locs:
            raise bad(f"notes[{i}].location={n.get('location')!r} — 초안에 없는 위치")
        issue = n.get("issue")
        if not isinstance(issue, str) or not issue.strip() or len(issue) > REVIEW_NOTE_MAX:
            raise bad(f"notes[{i}].issue 가 비었거나 {REVIEW_NOTE_MAX}자를 넘는다")
        turns = n.get("turns", [])
        if not isinstance(turns, list) or (turns and not _int_list(turns)) or set(turns) - T:
            raise bad(f"notes[{i}].turns 가 원문 턴이 아니다")        # 장 전체 지적은 빈 목록
    return json.loads(json.dumps(notes))


async def run(data: dict, turn_map: list[dict], *, call: Call = call_model,
              recorder: Recorder | None = None, meta: dict | None = None, focus: str | None = None,
              analysis_fixture: dict | None = None, outline_fixture: dict | None = None,
              chapter_only: bool = False, model: str | None = None,
              draft_fixture: dict | None = None, review_notes: dict | None = None,
              edit_contract: str = "v5") -> dict:
    """
    다섯 단계를 차례로. 돌려주는 것은 result (result.json 과 같은 것).

    analysis_fixture 를 주면 **후속 단계 시험**이다 — 분석을 부르지 않고 검증된 시험용 스냅샷
    (load_analysis_fixture)에서 시작해 목차 → 장 → 편집 → 검증만 부른다(호출 장 수 + 3).
    outline_fixture 까지 주면 목차도 부르지 않고 사람이 검토한 시험용 목차(load_outline_fixture)에서
    장 → 편집 → 검증만 부른다(호출 장 수 + 2). 결과 · 기록에 analysis_source · outline_source 를 남긴다.

    meta 는 실행 기록에 그대로 덧붙이는 식별(run_ref · seed · alias)이다. focus 를 주면 한 장
    시험이다 — 같은 다섯 단계를 돌되 목차 · 편집이 그 소재로 장 하나만 만든다(호출 5회).

    chapter_only 는 **장 집필 비교**다 — 두 스냅샷에서 장 집필만 부르고(호출 장 수만큼) 초안의 코드 판정 ·
    계획 사실 사용률을 남긴다. 결과는 draft_only(완성본이 아니다). model 은 이 실행에만 쓰는 모델이다 —
    기본 모델(settings)은 바꾸지 않는다. 장 단계 상한은 CHAPTER_ONLY_LIMITS 까지 올린다.

    draft_fixture 를 주면 **편집 단독 시험**이다 — 장 집필 비교가 남긴 초안(load_draft_fixture)을 그대로
    받아 편집만 부른다(호출 1회). 초안 판정 · 편집 자료 · 최종 근거검사 · 편집 추적 · 코드 판정은 보통
    실행과 같은 함수다. 검증은 부르지 않는다(결과 edit_only). review_notes 는 사람 검토 지적
    (check_review_notes) — 편집 자료에 그대로 싣는다. 편집 단계 상한은 EDIT_ONLY_LIMITS 까지 올린다.

    edit_contract "v6" 은 편집만 문단 산문 + 근거 표현(claims) 계약으로 부른다(edit_message_v6 · check_final_v6 ·
    v6_findings · claim_findings). 편집 단독 시험에서만 받는다 — 장 집필 · 검증 계약은 v5 그대로다.
    """
    rec = recorder or Recorder()
    cfg = settings()
    edit_only = draft_fixture is not None
    if model:
        cfg["MEMOIR_PIPE_TEXT_MODEL"] = model
    for on, stage, (sec, tok) in ((chapter_only, "CHAPTER", CHAPTER_ONLY_LIMITS), (edit_only, "EDIT", EDIT_ONLY_LIMITS)):
        if on:
            cfg[f"MEMOIR_PIPE_{stage}_TIMEOUT"] = max(cfg[f"MEMOIR_PIPE_{stage}_TIMEOUT"], sec)
            cfg[f"MEMOIR_PIPE_{stage}_MAX_OUTPUT_TOKENS"] = max(cfg[f"MEMOIR_PIPE_{stage}_MAX_OUTPUT_TOKENS"], tok)
    cfg["chapter_only"] = chapter_only
    cfg["edit_only"] = edit_only
    cfg["edit_contract"] = edit_contract
    v6 = edit_contract == "v6"
    draft_source: dict | None = None
    meta = dict(meta or {})
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    st: _Run | None = None
    result = _result(FAILED, focus=focus)     # 아래에서 반드시 덮어쓴다. 예상 못 한 오류에도 기록은 남긴다

    try:
        try:
            T = check_input(data, turn_map)
        except PipelineError as e:
            rec.json("00_input.json", {"input_ref": None, "rejected": e.message})
            raise
        ref = input_ref(data)
        meta["input_ref"] = ref
        rec.json("00_input.json", {"input_ref": ref, "focus": focus, "turn_marks": turn_marks(data),
                                   "input": data, "turn_map": turn_map})
        st = _Run(data, T, call, rec, cfg)
        if (chapter_only or edit_only) and (analysis_fixture is None or outline_fixture is None):
            raise PipelineError("input", "input", "장 집필 비교 · 편집 단독 시험은 분석 · 목차 스냅샷과 함께만 쓴다")
        if chapter_only and edit_only:
            raise PipelineError("input", "input", "장 집필 비교와 편집 단독 시험은 함께 하지 않는다")
        if review_notes is not None and not edit_only:
            raise PipelineError("input", "input", "검토 지적은 편집 단독 시험에서만 받는다")
        if edit_contract not in EDIT_CONTRACTS:
            raise PipelineError("input", "input", f"편집 계약 {edit_contract!r} — {list(EDIT_CONTRACTS)} 중 하나")
        if v6 and not edit_only:
            raise PipelineError("input", "input", "편집 계약 v6 은 편집 단독 시험에서만 쓴다")

        # ① 분석 — 사실 원장 · 기억 단위 (또는 검증된 시험용 스냅샷)
        if analysis_fixture is not None:
            analysis = load_analysis_fixture(analysis_fixture, data, T)
            rec.json("01_analysis_fixture.json", analysis_fixture)
            status = "ready"
        else:
            analysis, step = await st.ask("analysis", analysis_message(data), "01_analysis")
            status, step["warnings"] = check_analysis(analysis, T, turn_marks(data), source_texts(data),
                                                      source_asked(data))
            step["ok"] = True
        if status == INSUFFICIENT:
            result = _result(INSUFFICIENT, calls=st.calls, focus=focus)
            return result
        if status == NEEDS_CONTEXT:
            raise PipelineError("analysis", "context", "; ".join(analysis["missing_context"])[:300])
        book = ledger(analysis)
        if analysis_fixture is None:
            step["metrics"] = {"facts": len(analysis["facts"]), "units": len(analysis["units"]),
                               "must_keep": len(must_keep(analysis))}

        # ② 목차 — 책 설계도 (또는 사람이 검토한 시험용 목차)
        if outline_fixture is not None:
            if analysis_fixture is None:
                raise PipelineError("input", "input", "목차 스냅샷은 분석 스냅샷과 함께만 쓴다")
            outline_out, fixture_focus = load_outline_fixture(outline_fixture, analysis, analysis_fixture, T)
            if focus and focus != fixture_focus:
                raise PipelineError("input", "input", f"focus {focus!r} 가 목차 스냅샷의 focus {fixture_focus!r} 와 다르다")
            focus = fixture_focus
            rec.json("02_outline_fixture.json", outline_fixture)
            status = "ready"
        else:
            outline_out, step = await st.ask("outline", outline_message(data, analysis, focus), "02_outline")
            status, step["warnings"] = check_outline(outline_out, analysis, T, focus)
            step["ok"] = True
        if status == NEEDS_CONTEXT:
            raise PipelineError("outline", "context", "; ".join(outline_out["missing_context"])[:300])
        chapters_plan = outline_out["chapters"]
        st.max_calls = (1 if edit_only else len(chapters_plan) + (0 if chapter_only else 2 if outline_fixture is not None
                                                                  else 3 if analysis_fixture is not None else 4))
        memos = outline_memos(outline_out)

        # ③ 장별 집필 — 순서대로, 첫 실패에서 멈춘다 (편집 단독 시험은 남긴 초안을 받는다)
        drafts: list[dict] = []
        notes = None
        if edit_only:
            drafts, draft_source = load_draft_fixture(draft_fixture, outline_fixture, outline_out, analysis, data)
            rec.json("03_draft_fixture.json", {"source": draft_source, "drafts": drafts})
            expand_turns(drafts, book)
            if review_notes is not None:
                notes = check_review_notes(review_notes, drafts, draft_source["run_ref"], T)
                rec.json("03_review_notes.json", review_notes)
        for ch in [] if edit_only else chapters_plan:
            key = ch["chapter_key"]
            src, given = chapter_source(data, analysis, ch)
            try:
                draft, step = await st.ask("chapter", chapter_message(src, analysis, outline_out, ch),
                                           f"03_{key}", key)
                step["warnings"] = check_chapter(draft, ch, set(plan_facts(ch)), memos)
                expand_turns([draft], book)
                step["given_turns"] = given
                step["metrics"] = {**text_metrics([draft], data), **listing_signals([draft], data)[0],
                                   "plan_coverage": plan_coverage([draft], {"chapters": [ch]})}
                step["ok"] = True
            except PipelineError as e:
                st.steps[-1]["error"] = e.as_dict()
                result = _result(PARTIAL, failure=e, calls=st.calls, focus=focus)
                return result
            drafts.append(draft)

        # 코드 판정 ① — 장 초안에서. 편집이 고칠 곳 · 나열 신호로 넘긴다
        outline_omit = {f: x["reason"] for x in outline_out.get("omit", []) for f in x["facts"]}
        draft_checks = all_findings(drafts, outline_out, data, analysis, outline_omit)
        if v6:
            draft_checks += v6_findings(drafts, data, analysis)
        draft_signals = listing_signals(drafts, data)
        rec.json("03_checks.json", {"checks": draft_checks, "signals": draft_signals,
                                    "plan_coverage": plan_coverage(drafts, outline_out)})
        if chapter_only:
            gate = code_gate(draft_checks, {}, [])
            metrics = {"facts": len(analysis["facts"]), "units": len(analysis["units"]),
                       "outline_chapters": len(chapters_plan), "outline_omitted_facts": len(outline_omit),
                       **text_metrics(drafts, data), "signals": draft_signals,
                       "plan_coverage": {"draft": plan_coverage(drafts, outline_out)}}
            title = drafts[0]["title"] if len(drafts) == 1 else outline_out["book"]["title"]
            result = _result(DRAFT_ONLY, edited={"title": title, "chapters": drafts}, calls=st.calls,
                             metrics=metrics, gate=gate, focus=focus)
            return result

        # ④ 전체 편집 → 최종 근거검사 → 편집 추적 → 코드 판정 ②
        span_checks: list[dict] = []
        if v6:
            raw, step = await st.ask("edit", edit_message_v6(data, analysis, outline_out, drafts, draft_checks,
                                                             draft_signals, focus, notes), "04_edited",
                                     system=edit_prompt("v6"))
        else:
            edited, step = await st.ask("edit", edit_message(data, analysis, outline_out, drafts, draft_checks,
                                                             draft_signals, focus, notes), "04_edited")
        step["ok"] = True
        try:
            if v6:
                edited, omitted, step["warnings"], span_checks = check_final_v6(raw, analysis, T, focus)
            else:
                omitted, step["warnings"] = check_final(edited, analysis, T, focus)
        except PipelineError:
            step["ok"] = False
            raise
        expand_turns(edited["chapters"], book, edited["title"])
        if v6:
            rec.json("04_edited_sentences.json", edited)
        omitted_all = {**outline_omit, **omitted}
        trace = edit_trace(drafts, edited["chapters"], omitted_all)
        rec.json("04_edit_trace.json", trace)
        resolutions, res_warnings = check_resolutions(edited, draft_checks)
        step["warnings"] += res_warnings
        final_findings = (all_findings(edited["chapters"], outline_out, data, analysis, outline_omit, final=True,
                                       edit_omitted=omitted)
                          + correction_findings([], analysis, edited["title"]) + edit_claim_findings(edited, trace))
        protected = set(plan_core(outline_out)) | must_keep(analysis)
        omission_review = omission_candidates(drafts, edited["chapters"], trace, analysis, data, omitted,
                                              outline_omit, protected)
        rec.json("04_omission_review.json", {"candidates": omission_review,
                                             "protected_omissions": protected_omissions(final_findings, analysis, data,
                                                                                        edited["chapters"])})
        if v6:
            final_findings += (span_checks + v6_findings(edited["chapters"], data, analysis)
                               + composition_leaks(edited) + claim_findings(edited, trace)
                               + composition_findings(edited, trace))
        gate = code_gate(final_findings, resolutions, draft_checks)
        gate["draft_checks"] = len(draft_checks)
        gate["resolutions"] = {s: sum(1 for r in resolutions.values() if r["status"] == s) for s in CHECK_STATUSES}
        rec.json("04_code_gate.json", gate)
        final_signals = listing_signals(edited["chapters"], data)
        metrics = {"facts": len(analysis["facts"]), "units": len(analysis["units"]),
                   "outline_chapters": len(chapters_plan), "outline_omitted_facts": len(outline_omit),
                   **text_metrics(edited["chapters"], data),
                   "draft_verbatim_ratio": text_metrics(drafts, data)["verbatim_ratio"],
                   "signals": final_signals, "draft_signals": draft_signals,
                   "plan_coverage": {"draft": plan_coverage(drafts, outline_out),
                                     "final": plan_coverage(edited["chapters"], outline_out)}}
        step["metrics"] = {"edit_trace": trace["summary"]}
        if edit_only:
            result = _result(EDIT_ONLY, edited=edited, calls=st.calls, metrics=metrics, gate=gate, trace=trace,
                             focus=focus)
            return result

        # ⑤ 검증 — 사실 대조 + 구성 채점. 실패해도 편집본은 생성된 것이다. 완성 실행은 아니다
        locs = locations(edited)
        plan = verify_plan(analysis, outline_out, st.steps)
        plan["code_findings"] = [{k: f[k] for k in ("rule", "severity", "location")} for f in final_findings]
        plan["signals"] = final_signals
        plan["edit_trace"] = trace["summary"]
        plan["omission_review"] = omission_review
        plan["protected_omissions"] = protected_omissions(final_findings, analysis, data, edited["chapters"])
        try:
            verdict_out, step = await st.ask(
                "verify", verify_message(data, analysis, edited, T, plan, exclusion_notices(analysis)), "05_verify")
            step["warnings"] = check_verify(verdict_out, T, locs)
            step["ok"] = True
        except PipelineError as e:
            st.steps[-1]["error"] = e.as_dict()
            result = _result(GENERATED, failure=e, edited=edited, calls=st.calls, metrics=metrics, gate=gate,
                             trace=trace, focus=focus,
                             verification={"state": "failed", "verdict": None, "issues": [],
                                           "reviewed_locations": [], "missing_context": []})
            return result
        quality = adjust_quality(verdict_out["quality"], final_signals, final_findings)
        verification = {"state": verdict_out["review_status"], "verdict": verdict_out["verdict"],
                        "issues": verdict_out["issues"], "quality": verdict_out["quality"],
                        "reviewed_locations": verdict_out["reviewed_locations"],
                        "missing_context": verdict_out["missing_context"]}
        result = _result(GENERATED, edited=edited, verification=verification, calls=st.calls,
                         complete=verdict_out["review_status"] == "completed", metrics=metrics, gate=gate,
                         quality=quality, trace=trace, focus=focus)
        return result

    except PipelineError as e:
        if st is not None and st.steps and st.steps[-1]["error"] is None and not st.steps[-1]["ok"]:
            st.steps[-1]["error"] = e.as_dict()
        state = NEEDS_CONTEXT if e.kind == "context" else FAILED
        result = _result(state, failure=e, calls=st.calls if st else 0, focus=focus)
        return result

    finally:
        result.update({k: meta[k] for k in ("run_ref", "input_ref") if k in meta})
        result["analysis_source"] = REVIEWED_FIXTURE if analysis_fixture is not None else "model"
        result["outline_source"] = REVIEWED_FIXTURE if outline_fixture is not None else "model"
        if draft_source is not None:
            result["draft_source"] = draft_source
        result["edit_contract"] = edit_contract
        rec.json("result.json", result)               # 출처 표시를 넣은 뒤에 쓴다
        run_doc = {**meta, "focus": focus, "analysis_source": result["analysis_source"],
                   "outline_source": result["outline_source"], "draft_source": draft_source,
                   "started_at": started_at,
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


# ---------------------------------------------------------------- 분석만 따로 — 기억 지도 검증 (호출 1회)


def memory_map(analysis: dict, data: dict) -> dict:
    """분석 출력의 모양을 사람이 보기 쉽게 — 숫자 · 목록. 판정이 아니다."""
    facts = {f["id"]: f for f in analysis.get("facts", []) if isinstance(f, dict) and "id" in f}
    session = {u["turn"]: u["session_id"] for u in data["utterances"]}
    units = []
    for u in analysis.get("units", []):
        fs = [facts[x] for x in u.get("facts", []) if x in facts]
        ys = {y for f in fs for y in _full_years(f.get("time", "") + " " + f.get("text", ""))}
        units.append({"id": u.get("id"), "name": u.get("name"), "weight": u.get("weight"), "time": u.get("time"),
                      "facts": len(fs), "years": [min(ys), max(ys)] if ys else [],
                      "sessions": sorted({session[t] for f in fs for t in f.get("turns", []) if t in session})})
    return {
        "facts": len(facts), "units": len(units), "unit_sizes": units,
        "keep": sum(1 for f in facts.values() if f.get("keep")),
        "heard": sorted((f["id"] for f in facts.values() if f.get("source") == "heard"), key=lambda x: int(x[1:])),
        "view": sorted((f["id"] for f in facts.values() if f.get("source") == "view"), key=lambda x: int(x[1:])),
        "approx_or_uncertain": sorted((f["id"] for f in facts.values() if f.get("certainty") in ("approx", "uncertain")),
                                      key=lambda x: int(x[1:])),
        "corrections": analysis.get("corrections", []),
        "threads": [{"id": th.get("id"), "name": th.get("name"), "units": th.get("units"),
                     "link_turns": th.get("link_turns")} for th in analysis.get("threads", [])],
        "themes": [{"theme": x.get("theme"), "strength": x.get("strength"), "supporting": x.get("supporting"),
                    "counter": x.get("counter")} for x in analysis.get("themes", [])],
        "direction": analysis.get("direction"),
        "not_in_facts": analysis.get("not_in_facts", []),
    }


def memory_map_text(analysis: dict, mm: dict, diagnostics: list[str], warnings: list[str],
                    checked: bool = True) -> str:
    """사람 검토용 기억 지도 (eval/runs 안에만 남는다 — 원문 요약이 들어 있다)."""
    facts = {f["id"]: f for f in analysis.get("facts", []) if isinstance(f, dict) and "id" in f}
    home: dict[str, list] = {}
    for u in analysis.get("units", []):
        for x in u.get("facts", []):
            home.setdefault(x, []).append(u.get("id"))
    lines = ["# 기억 지도 — 분석만 따로 본 결과", "",
             f"- 사실 {mm['facts']} · 기억 단위 {mm['units']} · keep {mm['keep']} · 들은 이야기 {len(mm['heard'])} · "
             f"화자의 평가 {len(mm['view'])} · "
             f"대략/불확실 {len(mm['approx_or_uncertain'])} · 정정 {len(mm['corrections'])}", "",
             "## 계약 위반 (있으면 다음 단계로 넘기지 않는다)", ""]
    lines += [f"- {x}" for x in diagnostics] or ["- 없음"]
    if not checked:
        lines += ["- **뜻 검사 미실행** — 형식 오류에서 멈춰 정정 · 기억 단위 · 전언 · 감정 검사를 하지 않았다"]
    lines += ["", "## 검토할 점 (경고)", ""]
    lines += ([f"- {x}" for x in warnings] or ["- 없음"]) if checked else ["- 검사 미실행 (경고 0건이 아니다)"]
    lines += ["", "## 정정", "", "| 유효 사실 | 턴 | 정정 전(이력) | 정정 뒤 |", "|---|---|---|---|"]
    norm = [f"- 코드 정규화: {n}" for n in analysis.get("normalized", [])]
    lines += [f"| {c.get('fact')} | {c.get('turns')} | {c.get('before', '')} | {c.get('after', '')} |"
              for c in mm["corrections"]]
    lines += [""] + norm if norm else []
    for u in analysis.get("units", []):
        info = next(x for x in mm["unit_sizes"] if x["id"] == u.get("id"))
        lines += ["", f"## {u.get('id')} {u.get('name')} — {u.get('weight')} · {u.get('time')} · 사실 {info['facts']} · "
                      f"연도 {info['years']} · 회차 {info['sessions']}", "",
                  "| 사실 | 턴 | 시점 | 출처 | 확실성 | keep | 메모 |", "|---|---|---|---|---|---|---|"]
        for x in u.get("facts", []):
            f = facts.get(x, {})
            dup = " (중복)" if len(home.get(x, [])) > 1 else ""
            lines.append(f"| {x}{dup} | {f.get('turns')} | {f.get('time', '')} | {f.get('source')} | {f.get('certainty')} | "
                         f"{'O' if f.get('keep') else ''} | {f.get('text', '')} |")
    lines += ["", "## 끈", ""] + [f"- {th['id']} {th['name']} — 단위 {th['units']} · 화자가 이은 턴 {th['link_turns']}"
                                  for th in mm["threads"]]
    lines += ["", "## 주제", ""] + [f"- {x['theme']} ({x['strength']}) — 근거 {x['supporting']} · 반대/복합 {x['counter']}"
                                    for x in mm["themes"]]
    lines += [f"- 방향: {mm['direction']}", "", "## 사실로 쓰지 않은 턴", ""]
    lines += [f"- {x.get('turns')} — {x.get('reason')}" for x in mm["not_in_facts"]] or ["- 없음"]
    lines += ["", "## 사람 검토 (직접 적는다)", "",
              "- 정정이 하나의 유효 사실로 처리됐는가:", "- 기억 단위가 한 시기 · 한 이야기인가:",
              "- 들은 이야기와 직접 기억이 나뉘었는가:", "- keep 이 핵심 사실에만 있는가:",
              "- 주제가 원문 근거의 편집적 해석인가 (감정 · 희생 단정이 아닌가):", "- 나머지 단계를 돌려도 되는가:", ""]
    return "\n".join(lines)


async def run_analysis_only(data: dict, turn_map: list[dict], *, call: Call = call_model,
                            recorder: Recorder | None = None, meta: dict | None = None) -> dict:
    """
    분석 단계만 따로 — 모델 호출 **1회**. 새 역할이 아니라 같은 분석 지시문 · 같은 검사다. 계약 위반이
    여럿이면 모두 모아 남기고(diagnostics), 목차 이후 단계는 부르지 않는다.
    """
    rec = recorder or Recorder()
    cfg = settings()
    meta = dict(meta or {})
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    st: _Run | None = None
    result: dict = {"mode": "analysis_only", "generation_state": FAILED, "analysis_ok": False,
                    "semantic_checks": "not_run", "diagnostics": [], "warnings": [], "memory_map": None, "failure": None,
                    "human_review": "not_run", "calls": 0, "prompt_version": PROMPT_VERSION}
    try:
        T = check_input(data, turn_map)
        meta["input_ref"] = input_ref(data)
        marks = turn_marks(data)
        rec.json("00_input.json", {"input_ref": meta["input_ref"], "turn_marks": marks})
        st = _Run(data, T, call, rec, cfg)
        st.max_calls = 1
        analysis, step = await st.ask("analysis", analysis_message(data), "01_analysis")
        try:
            status, warnings = check_analysis(analysis, T, marks, source_texts(data), source_asked(data))
            step["warnings"], step["ok"] = warnings, True
            result.update(generation_state="analyzed" if status == "ready" else status,
                          analysis_ok=status == "ready", warnings=warnings, semantic_checks="run")
        except PipelineError as e:
            step["error"] = e.as_dict()
            ran = bool(e.details)                       # 뜻 검사까지 갔으면 details 가 있다 — 형식 오류면 없다
            result.update(failure=e.as_dict(), diagnostics=e.details or [e.message], warnings=e.warnings,
                          semantic_checks="run" if ran else "not_run")
        if isinstance(analysis, dict) and analysis.get("normalized"):
            rec.json("01_analysis_normalized.json", analysis)
            result["normalized"] = analysis["normalized"]
        if isinstance(analysis, dict) and isinstance(analysis.get("facts"), list):
            mm = memory_map(analysis, data)
            result["memory_map"] = mm
            rec.text("01_memory_map.md", memory_map_text(analysis, mm, result["diagnostics"], result["warnings"],
                                                         result.get("semantic_checks") == "run"))
        result["calls"] = st.calls
        return result
    except PipelineError as e:
        if st is not None and st.steps and st.steps[-1]["error"] is None:
            st.steps[-1]["error"] = e.as_dict()
        result.update(failure=e.as_dict(), diagnostics=e.details or [e.message], calls=st.calls if st else 0)
        return result
    finally:
        result.update({k: meta[k] for k in ("run_ref", "input_ref") if k in meta})
        rec.json("result.json", result)
        rec.json("run.json", {**meta, "mode": "analysis_only", "started_at": started_at,
                              "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "settings": cfg, "prompts": _safe_hashes(), "steps": st.steps if st else [],
                              "calls": result["calls"], "generation_state": result["generation_state"],
                              "failure": result["failure"]})


# ---------------------------------------------------------------- R1 요약


def r1_summary(run_doc: dict, result: dict) -> str:
    """
    팀 공유용 요약. **본문 · 원문 · 검증 설명문 · 비밀값을 넣지 않는다** — 숫자 · 상태 ·
    위치 · 코드만. 사람 검수 칸은 비워 둔다.
    """
    cfg = run_doc.get("settings", {})
    v = result["verification"]
    f = result["failure"]
    q = result.get("model_quality") or {}
    lines = [
        f"# R1 — 자서전 파이프라인 실행 {run_doc.get('run_ref', '(이름 없음)')}",
        "",
        "## 실행 식별",
        f"- input_ref: `{run_doc.get('input_ref')}` · seed: `{run_doc.get('seed')}` · "
        f"alias: {', '.join(run_doc.get('aliases') or [])}" + (f" · focus: 있음(한 장)" if run_doc.get("focus") else ""),
        f"- 시각: {run_doc.get('started_at')} ~ {run_doc.get('finished_at')}",
        "",
        "## 설정",
        f"- 모델 `{cfg.get('MEMOIR_PIPE_TEXT_MODEL')}` · 온도 {cfg.get('MEMOIR_PIPE_TEMPERATURE')} · "
        f"전체 상한 {cfg.get('MEMOIR_PIPE_TOTAL_TIMEOUT')}초 · 재시도 {cfg.get('retries')} · "
        f"장 {cfg.get('chapters')}"
        + (" · **장 집필 비교(chapter_only) — 편집 · 검증을 부르지 않았다**" if cfg.get("chapter_only") else "")
        + (f" · **편집 단독 시험(edit_only) — 초안 {(run_doc.get('draft_source') or {}).get('run_ref')} "
           f"({(run_doc.get('draft_source') or {}).get('model')})을 편집만, 검증을 부르지 않았다**"
           if cfg.get("edit_only") else "")
        + (" · **편집 계약 v6 — 문단 산문 + 근거 표현(claims), 지시문 4_편집_v6.md**"
           if cfg.get("edit_contract") == "v6" else ""),
        "- 단계 상한: " + " · ".join(
            f"{s} {cfg.get(f'MEMOIR_PIPE_{s.upper()}_TIMEOUT')}초/"
            f"{cfg.get(f'MEMOIR_PIPE_{s.upper()}_MAX_OUTPUT_TOKENS')}" for s in STAGES),
        f"- 지시문 판: {result.get('prompt_version')} · 분석 출처: **{result.get('analysis_source', 'model')}** · "
        f"목차 출처: **{result.get('outline_source', 'model')}**"
        + (" — 사람이 검토한 시험용 목차(자동 목차 생성 결과 아님)" if result.get("outline_source") == REVIEWED_FIXTURE else "")
        + (" — 시험용 스냅샷(모델 원본 아님), 분석 단계를 부르지 않았다"
           if result.get("analysis_source") == REVIEWED_FIXTURE else ""),
        "",
        "## 상태",
        f"- generation_state: **{result['generation_state']}** · pipeline_complete: "
        f"**{str(result['pipeline_complete']).lower()}** · 호출 {result['calls']}회",
        f"- 사실 대조: {v['state']} · verdict: {v['verdict']}",
        f"- 구성 채점(코드 보정 뒤): {q.get('scores')} · 기준 충족 {q.get('meets_bar')} · 보정 {len(q.get('adjusted') or [])}건",
        f"- code_gate: **{result.get('code_gate')}** · model_verdict: {result.get('model_verdict')} · "
        f"human_review: {result['human_review']} → **overall: {result.get('overall')}**",
        "- approved 는 사람 검수로만 된다 — 모델 pass · 구성 채점 · 코드 pass 는 출판 품질 승인이 아니다",
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
    m = result.get("metrics") or {}
    if m:
        lines += ["", "## 비교 지표 (판정 아님)", "",
                  f"- 사실 {m.get('facts')} · 기억 단위 {m.get('units')} · 목차 장 {m.get('outline_chapters')} · "
                  f"목차가 뺀 사실 {m.get('outline_omitted_facts')} → 편집본 장 {m.get('chapters')}",
                  f"- 문장 {m.get('sentences')} · editorial {m.get('editorial_sentences')} · 여러 턴을 묶은 문장 "
                  f"{m.get('multi_turn_sentences')} · 원문 그대로 {m.get('verbatim_ratio')}"]
        for stage, pc in (m.get("plan_coverage") or {}).items():
            lines.append(f"- 계획 사실 사용({stage}): 전체 {pc['planned_used']}/{pc['planned']} · 핵심 "
                         f"{pc['core_used']}/{pc['core']} · 보조 {pc['support_used']}/{pc['support']} · 빠진 핵심 "
                         f"{pc['core_missing']}")
        for s in m.get("signals") or []:
            lines.append(f"- {s['chapter_key']} 나열 신호: 1:1 {s['one_to_one']} · 턴 순서 유지 {s['order_kept']} · "
                         f"잇는 문장 {s['links']} · 여러 회차 문단 {s['multi_session_paragraphs']}/{s['paragraphs']} · "
                         f"listing={s['listing']}")
    t = result.get("edit_trace") or {}
    if t:
        lines += ["", "## 편집 추적 (코드가 잰 것)", "",
                  f"- 장 {t.get('draft_chapters')} → {t.get('final_chapters')} · 합친 장 {t.get('chapter_merges')} · "
                  f"나눈 장 {t.get('chapter_splits')} · 문단 합침 {t.get('paragraph_merges')} · 나눔 {t.get('paragraph_splits')}",
                  f"- 문장 {t.get('draft_sentences')} → {t.get('final_sentences')} · 그대로 {t.get('kept')} · 다듬음 "
                  f"{t.get('revised')} · 다시 씀 {t.get('rewritten')} · 새 문장 {t.get('new')} · 덜어 냄 {t.get('dropped')} · "
                  f"옮김 {t.get('moved')} · 구조 변화 {t.get('structure_changed')}"]
    cf = result.get("code_findings") or []
    if cf:
        by_rule: dict[str, int] = {}
        for x in cf:
            key = f"{x['rule']}({x['severity']})"
            by_rule[key] = by_rule.get(key, 0) + 1
        lines += ["", f"## 코드 판정 (편집본) — {by_rule}", ""]
        if any(x["severity"] == "review" for x in cf):
            lines += ["- review 는 사람 확인 항목(문학적 판단 · 오탐 가능한 표면 검사)이다 — code_gate 에 넣지 않는다", ""]
        lines += ["| 위치 | 규칙 | severity |", "|---|---|---|"]
        lines += [f"| {x['location']} | {x['rule']} | {x['severity']} |" for x in cf]
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
              "- Q7 사실 충실 (필수 — 문장마다 원문 대조, 들은 말 · 불확실성 포함):",
              "- Q8 블라인드 독자 시험 (평가자 · 선호 · 질문/답 흔적 위치):",
              "- Q1~Q6 사람 채점:",
              "- 문제 위치와 이유:",
              "- 검수자 · 시각:", ""]
    return "\n".join(lines)
