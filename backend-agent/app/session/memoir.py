"""
자서전 초안 — 고른 회차 3~5개를 한 입력으로 합쳐 한 번 쓰게 한다 (업무지시서 01 v1.1)

    검사      check_selection   개수 · 중복 · 모양               → BadSelection (400)
    조회      collect           있나 · 내 것인가                  → NotFound (404)
                                말씀이 있나 · 한 화자인가          → BadSelection (400)
                                DB 를 못 읽었다                   → SourceUnavailable (422)
    합치기    merge             전역 턴 · turn_map
    쓰기      write             자서전.md + 자료                  → GenerationFailed (502)
                                                                   GenerationTimeout (504)
    검사      check             7개 키 · 본문 줄마다 출처 하나    → GenerationFailed (502)
                                확인 필요 · 자료 누락              → NotFinal (503)

**저장하지 않는다.** 초안은 응답으로만 나간다. 자서전 표도, 작업 ID 도 없다.

**전역 턴은 이 요청 안에서만 뜻이 있다.** 회차마다 턴이 1부터라 그대로 합치면
「턴 1」이 여럿이 된다. 고른 회차를 기록 순서로 세워 말씀에 1부터 번호를 다시
매기고, 그 번호를 utterances · facts_found · turn_map 세 곳에 똑같이 쓴다.
DB 의 턴 번호는 건드리지 않는다. 다음 요청은 다시 1부터다.

**회차 안의 자료는 엽서와 같은 함수로 세운다** (postcard.material). 판단이 어느
말씀의 것인지 — turn N 의 decision 은 N-1 번 말씀의 판단이고 마지막은
closing_decision 이다 — 를 두 군데서 따로 정하면 어긋난다.

**회차를 넘는 정리는 하지 않는다.** 한 회차에서 「1998년」, 다른 회차에서
「1996년」이라고 하셨으면 둘 다 그대로 준다. 어느 쪽이 맞는지는 서버가 정하지
않는다 — 원문을 다 주고 정정의 뜻은 자서전.md 의 규칙이 읽는다.

**고치지 않는다.** 모델이 낸 구조가 어긋나면 빈 줄을 지우거나 출처 번호를 맞춰
주지 않고 502 다. 자료 부족(insufficient_material)은 실패가 아니라 200 이고,
실패를 자료 부족으로 바꿔 내보내지도 않는다.

환경변수는 함수 안에서 읽는다 (store.py 머리와 같은 이유).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from functools import lru_cache
from pathlib import Path

from . import postcard, roledoc, store
from .conf import env_float, env_int, env_str
from .question import _client

log = logging.getLogger("memoir")

PROMPT = Path(__file__).resolve().parents[2] / "첨부프롬프트_md" / "자서전_v4.md"

MIN_SESSIONS = 3
# 상한은 **단일 호출 구조의 임시 시험 제한**이다 (태헌 10-26). 최종 정책은 같은 화자의
# 쓸 수 있는 기록을 전부 고르고 빼는 것이라 상수로 박지 않는다 — 다섯 단계 구조가
# 품질 시험을 지나면 올리거나 없앤다.
DEFAULT_MAX_SESSIONS = 5


def max_sessions() -> int:
    return env_int("MEMOIR_MAX_SESSIONS", DEFAULT_MAX_SESSIONS)


def require_speaker() -> bool:
    """
    화자 미지정 회차를 거절하나. 화면이 화자를 정할 수 있게 될 때까지 끈다 (기본 0).
    꺼져 있어도 **서로 다른 화자를 섞는 것은 언제나 거절한다.**
    """
    return env_int("MEMOIR_REQUIRE_SPEAKER", 0) == 1

# 서버와 독립 실행(03)이 같은 이름 · 같은 값을 읽는다. 엽서 설정과 섞지 않는다.
DEFAULT_TEXT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MIME = "application/json"
# 지시서의 처음 값은 2000 이었다. 자서전.md v1.3 부터 글이 길어져(40문장이면 1700~1800
# 토큰쯤) 올렸다. 걸리면 JSON 이 잘려 502 다. README 「재 본 것」.
DEFAULT_MAX_OUTPUT_TOKENS = 3000
DEFAULT_TEXT_TIMEOUT = 20.0

# 자서전.md §8-2 — 작성 공통 7키. 화면에는 앞의 다섯 개만 나간다 (preview).
KEYS = ("status", "title", "body", "sources", "to_confirm",
        "missing_context", "coverage_notes")
SHOWN = KEYS[:5]
READY, INSUFFICIENT = "ready", "insufficient_material"
NOT_FINAL = ("needs_confirmation", "needs_context")

# MEMOIR_FAIL_INJECT — 시험 서버에서만 켠다. 요청으로는 고를 수 없다.
INJECT_SOURCE = "source_material_unavailable"
INJECT_FAILED = "generation_failed"
INJECT_TIMEOUT = "generation_timeout"
_INJECTS = (INJECT_SOURCE, INJECT_FAILED, INJECT_TIMEOUT)


class MemoirError(RuntimeError):
    """화면에 나갈 말은 라우트가 정한다. 여기 담긴 글은 로그용이다."""


class BadSelection(MemoirError):
    """개수 · 중복 · 모양 · 말씀이 없는 회차. 400."""

    code = "bad_selection"


class MixedSpeakers(BadSelection):
    """고른 회차의 화자가 다르다. 한 자서전에는 한 사람의 이야기만 든다. 400."""

    code = "mixed_speakers"


class SpeakerUnassigned(BadSelection):
    """화자 미지정 회차가 끼었다 (MEMOIR_REQUIRE_SPEAKER=1 일 때). 400 — 먼저 화자를 정한다."""

    code = "speaker_unassigned"


class NotFound(MemoirError):
    """회차가 없다 · 남의 것이다. 404 — 둘을 구분해 알려 주지 않는다."""


class SourceUnavailable(MemoirError):
    """고른 회차의 원자료를 읽지 못했다. 422. 엽서 글로 대신하지 않는다."""


class GenerationFailed(MemoirError):
    """모델을 못 불렀다 · 낸 구조가 어긋났다. 502."""


class GenerationTimeout(MemoirError):
    """모델이 제시간에 답하지 않았다. 504."""


class NotFinal(MemoirError):
    """
    모델이 needs_confirmation · needs_context 로 답했다. 503 — 초안을 내보내지 않는다.

    화면에는 같은 503 이지만 status 와 사유(to_confirm · missing_context)는 여기
    남는다. needs_confirmation 이어도 다시 묻지 않는다.
    """

    def __init__(self, status: str, reasons: list):
        super().__init__(f"{status} — {json.dumps(reasons, ensure_ascii=False)[:200]}")
        self.status = status
        self.reasons = reasons


def inject() -> str:
    """지금 걸린 실패 주입. 모르는 값은 끈 것으로 읽고 로그에 남긴다."""
    v = env_str("MEMOIR_FAIL_INJECT").strip().lower()
    if v in ("", "off"):
        return ""
    if v not in _INJECTS:
        log.error("MEMOIR_FAIL_INJECT=%s 는 모르는 값이다 — 끈 것으로 읽는다", v)
        return ""
    return v


# ---------------------------------------------------------------- 고르기


def check_selection(session_ids) -> list[str]:
    """
    화면이 보낸 session_ids 를 본다. DB 는 아직 보지 않는다.

    UUID 는 소문자 표기로 맞춘다 — 대소문자만 다른 같은 회차를 두 번 고른 것도
    중복이다.
    """
    if not isinstance(session_ids, list):
        raise BadSelection("session_ids 가 목록이 아니다")
    top = max_sessions()
    if not MIN_SESSIONS <= len(session_ids) <= top:
        raise BadSelection(f"회차 {len(session_ids)}개 — {MIN_SESSIONS}~{top}개여야 한다")
    ids: list[str] = []
    for s in session_ids:
        if not isinstance(s, str):
            raise BadSelection("session_id 가 문자열이 아니다")
        try:
            ids.append(str(uuid.UUID(s.strip())))
        except ValueError as e:
            raise BadSelection("session_id 가 UUID 가 아니다") from e
    if len(set(ids)) != len(ids):
        raise BadSelection("같은 회차를 두 번 골랐다")
    return ids


async def collect(session_ids: list[str], user_id: str) -> list[dict]:
    """
    고른 회차의 기록을 읽는다. 고른 순서 그대로 돌려준다 — 순서는 merge 가 세운다.

    하나라도 없거나 남의 것이면 전부 404 다. 되는 것만 골라 쓰지 않는다 —
    고르신 것과 다른 자료로 쓴 글이 된다.

    **엽서는 조건이 아니다** (태헌 10-26). 자서전의 근거는 인터뷰 원문이므로 어르신
    말씀이 하나라도 있으면 된다. 정정 · 제외 경로가 생기면 그것을 빼고 남은 말씀으로 본다.
    """
    recs: list[dict] = []
    for sid in session_ids:
        try:
            rec = await store.load_session(sid)
        except store.StoreUnavailable as e:
            raise SourceUnavailable(f"회차를 읽지 못했다 {sid}") from e
        if rec is None or rec["user_id"] != user_id:
            raise NotFound(f"회차가 없다 {sid}")
        if not postcard.material(rec["fragments"], None, rec.get("closing_decision"))["utterances"]:
            raise BadSelection(f"어르신 말씀이 없는 회차다 {sid}")
        recs.append(rec)

    speakers = {rec.get("elder_id") for rec in recs}
    if len(speakers - {None}) > 1:
        raise MixedSpeakers(f"화자가 섞였다 {sorted(speakers - {None})}")
    if None in speakers and (require_speaker() or len(speakers) > 1):
        # 화자 있는 회차와 미지정 회차가 섞였으면 꺼져 있어도 거절한다 — 미지정 쪽이
        # 다른 분의 이야기일 수 있다.
        raise SpeakerUnassigned("화자 미지정 회차가 있다")
    if inject() == INJECT_SOURCE:
        raise SourceUnavailable("MEMOIR_FAIL_INJECT=source_material_unavailable")
    return recs


# ---------------------------------------------------------------- 합치기


def merge(records: list[dict]) -> tuple[dict, list[dict]]:
    """
    회차 기록들을 모델 입력 하나와 turn_map 으로.

    **기록 순서는 회차를 연 시각이다** (recorded_order, 1부터). 고른 순서가
    아니다. 인생의 순서도 아니다 — 서버가 아는 것은 언제 들었는지뿐이다.
    시각이 같은 회차가 있으면 순서를 지어내지 않고 멈춘다.

    사진 단서는 싣지 않는다. 자서전의 근거는 말씀이다.
    """
    order = sorted(records, key=lambda r: r["created_at"])
    stamps = [r["created_at"] for r in order]
    if len(set(stamps)) != len(stamps):
        raise SourceUnavailable("시작 시각이 같은 회차가 있어 기록 순서를 정할 수 없다")

    confirmed: list[str] = []
    found: list[dict] = []
    sessions: list[dict] = []
    utterances: list[dict] = []
    turn_map: list[dict] = []

    g = 0
    for n, rec in enumerate(order, start=1):
        sid = rec["session_id"]
        m = postcard.material(rec["fragments"], None, rec.get("closing_decision"))
        sessions.append({"session_id": sid, "recorded_order": n})

        to_global: dict[int, int] = {}
        for u in m["utterances"]:
            g += 1
            to_global[u["turn"]] = g
            utterances.append({"turn": g, "session_id": sid,
                               "asked": u["asked"], "elder": u["elder"]})
            turn_map.append({"global_turn": g, "session_id": sid, "turn": u["turn"]})

        for fact in m["shared_state"]["confirmed_facts"]:
            if fact not in confirmed:
                confirmed.append(fact)
        for x in m["shared_state"]["facts_found"]:
            found.append({"turn": to_global[x["turn"]], "facts": x["facts"]})

    data = {
        "shared_state": {"confirmed_facts": confirmed, "facts_found": found},
        "sessions": sessions,
        "utterances": utterances,
    }
    return data, turn_map


# ---------------------------------------------------------------- 모델


@lru_cache(maxsize=1)
def _prompt() -> str:
    """자서전.md 에서 실행할 절만 잇는다 (roledoc). 자서전 역할 절은 §5-2."""
    try:
        return roledoc.assemble(PROMPT.read_text(encoding="utf-8"), "5-2")
    except (OSError, ValueError) as e:
        raise GenerationFailed(f"자서전 프롬프트를 읽지 못했다: {PROMPT.name} ({e})") from e


def _input(data: dict) -> str:
    """
    자료 메시지. 원문은 시스템 지시에 박지 않고 여기에만 싣는다.

    자서전.md(v1.3~)가 여러 회차 입력(sessions · session_id · 전역 턴)과 분량 기준을
    직접 담는다. 여기서는 이 입력이 어떤 모양인지만 짧게 알리고 **분량은 말하지
    않는다** — 두 곳에서 말하면 프롬프트를 고쳐도 옛 기준이 되살아난다.
    """
    return (
        "[자료]\n"
        "여러 회차의 말씀을 하나로 합친 입력이다.\n"
        "sessions 는 고른 회차 목록이다. recorded_order 는 서버가 기록한 순서(1부터)이며 "
        "인생 사건이 일어난 순서나 연도가 아니다. session_id · recorded_order 는 인생 사실의 "
        "근거가 아니다.\n"
        "utterances 의 turn 은 이 입력 안에서 1부터 이어 매긴 번호이고 session_id 가 그 말씀의 "
        "회차다. elder 가 사용자 원문, asked 는 AI 질문이다.\n"
        "shared_state.facts_found 의 turn 과 출력 sources · to_confirm 의 turns 는 모두 이 "
        "utterances.turn 번호다. 없는 번호를 만들지 않는다.\n"
        "소제목을 달지 않는다.\n"
        "전달된 회차가 쓸 수 있는 기록 전부다. 다른 회차나 추가 기록을 요구하지 않는다.\n"
        "승인 버전 값은 전달하지 않는다 — 버전을 비교하지 않는다. 원문이 빠졌거나 서로 "
        "어긋날 때만 needs_context 다.\n"
        "length_config 는 없다 — 문서의 기본 분량을 쓴다.\n\n"
        + json.dumps(data, ensure_ascii=False, indent=1)
    )


def settings() -> dict:
    """지금 적용되는 모델 설정. 보고용으로도 쓴다 — 비밀키는 없다."""
    return {
        "MEMOIR_TEXT_MODEL": env_str("MEMOIR_TEXT_MODEL", DEFAULT_TEXT_MODEL),
        "MEMOIR_TEMPERATURE": env_float("MEMOIR_TEMPERATURE", DEFAULT_TEMPERATURE),
        "MEMOIR_RESPONSE_MIME_TYPE": env_str("MEMOIR_RESPONSE_MIME_TYPE", DEFAULT_MIME),
        "MEMOIR_MAX_OUTPUT_TOKENS": env_int("MEMOIR_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS),
        "MEMOIR_TEXT_TIMEOUT": env_float("MEMOIR_TEXT_TIMEOUT", DEFAULT_TEXT_TIMEOUT),
    }


async def write(data: dict):
    """
    합친 자료로 한 번 쓴다. 다시 부르지 않는다. 시험이 갈아 끼우는 자리다.

    돌려주는 것은 모델이 낸 JSON 그대로다. 맞는지는 check 가 본다.
    모델을 못 찾아도 다른 모델로 바꾸지 않는다 — 실패다.
    """
    hook = inject()
    if hook == INJECT_FAILED:
        raise GenerationFailed("MEMOIR_FAIL_INJECT=generation_failed")
    if hook == INJECT_TIMEOUT:
        raise GenerationTimeout("MEMOIR_FAIL_INJECT=generation_timeout")

    client = _client()
    if client is None:
        raise GenerationFailed("GEMINI_API_KEY 가 없다")

    from google.genai import types

    s = settings()
    cfg = types.GenerateContentConfig(
        system_instruction=_prompt(),
        response_mime_type=s["MEMOIR_RESPONSE_MIME_TYPE"],
        temperature=s["MEMOIR_TEMPERATURE"],
        max_output_tokens=s["MEMOIR_MAX_OUTPUT_TOKENS"],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    timeout = s["MEMOIR_TEXT_TIMEOUT"]
    try:
        res = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=s["MEMOIR_TEXT_MODEL"], contents=_input(data), config=cfg),
            timeout=timeout)
    except asyncio.TimeoutError as e:
        raise GenerationTimeout(f"자서전 글이 {timeout:.0f}초 안에 오지 않았다") from e
    except Exception as e:                                   # noqa: BLE001
        raise GenerationFailed(f"모델 호출 실패 ({type(e).__name__}: {str(e)[:200]})") from e

    text = (res.text or "").strip()
    try:
        return json.loads(text)
    except ValueError as e:
        # 출력 토큰 상한에 걸려 잘린 것도 여기로 온다. 길이를 남겨 구분할 수 있게 한다.
        raise GenerationFailed(f"invalid_model_output — JSON 이 아니다 ({len(text)}자)") from e


# ---------------------------------------------------------------- 검사


def _ints(v) -> list[int] | None:
    """정수 목록이면 그대로, 아니면 None. True/False 는 정수로 치지 않는다."""
    if not isinstance(v, list):
        return None
    if not all(isinstance(t, int) and not isinstance(t, bool) for t in v):
        return None
    return v


def check(out, turns: set[int]) -> dict:
    """
    모델이 낸 것이 약속한 모양인지 본다. **뜻이 맞는지는 보지 않는다** — 구조가
    맞다고 「왜곡 없음」이 되지는 않는다.

    어긋나면 고치지 않고 GenerationFailed 다. 길다는 이유로 자르지도 않는다.
    """
    def bad(why: str):
        return GenerationFailed(f"invalid_model_output — {why}")

    if not isinstance(out, dict):
        raise bad("객체가 아니다")
    if set(out) != set(KEYS):
        raise bad(f"키가 다르다 {sorted(out)}")

    status, title, body = out["status"], out["title"], out["body"]
    sources, to_confirm = out["sources"], out["to_confirm"]
    if not isinstance(title, str) or not isinstance(body, str):
        raise bad(f"title({type(title).__name__}) · body({type(body).__name__}) 가 문자열이 아니다")
    if not isinstance(sources, list) or not isinstance(to_confirm, list):
        raise bad("sources · to_confirm 이 목록이 아니다")
    for k in ("missing_context", "coverage_notes"):
        if not isinstance(out[k], list) or not all(isinstance(x, str) for x in out[k]):
            raise bad(f"{k} 가 문자열 목록이 아니다")

    for c in to_confirm:
        if (not isinstance(c, dict) or not isinstance(c.get("issue"), str)
                or _ints(c.get("turns")) is None):
            raise bad("to_confirm 항목의 모양이 다르다")

    if status == INSUFFICIENT:
        if title or body or sources:
            raise bad("insufficient_material 인데 title · body · sources 가 비지 않았다")
    elif status == READY:
        if not title.strip() or not body.strip():
            raise bad("ready 인데 title 이나 body 가 비었다")
        lines = body.split("\n")
        if any(not ln.strip() for ln in lines):
            raise bad("본문에 빈 줄이 있다")
        if any(ln.lstrip().startswith("#") for ln in lines):
            raise bad("본문에 소제목 · 마크다운이 있다")

        seen: list[int] = []
        for s in sources:
            if not isinstance(s, dict):
                raise bad("sources 항목이 객체가 아니다")
            i, ts = s.get("sentence"), _ints(s.get("turns"))
            if not isinstance(i, int) or isinstance(i, bool):
                raise bad("sources.sentence 가 정수가 아니다")
            if not ts:
                raise bad(f"sources[{i}].turns 가 비었거나 정수 목록이 아니다")
            if not all(t in turns for t in ts):
                raise bad(f"sources[{i}].turns {ts} 에 없는 턴이 있다")
            seen.append(i)
        if sorted(seen) != list(range(len(lines))):
            raise bad(f"본문 {len(lines)}줄에 출처 번호 {sorted(seen)}")
    elif status in NOT_FINAL:
        raise NotFinal(status, out["to_confirm" if status == "needs_confirmation"
                                   else "missing_context"])
    else:
        raise bad(f"status={status!r}")

    return {k: out[k] for k in KEYS}


# ---------------------------------------------------------------- 한 요청


async def preview(session_ids, user_id: str, style: str = "spoken") -> dict:
    """
    고른 회차로 초안 하나. 돌려주는 것은 5개 키(SHOWN)에 요청받은 style 을 더한
    6키다 — turn_map 은 이 요청 안에서 출처를 따져 보는 데만 쓰고 화면에 내보내지
    않는다. missing_context · coverage_notes 는 로그에만 남긴다.

    style 은 라우트가 거른 값이다. 지금은 spoken 뿐이라 모델에 보내지 않는다
    (style.py 머리). 화면은 늦게 온 응답의 문체를 이 값으로 알아본다.

    로그에는 회차 ID 와 개수만 남긴다. 원문은 남기지 않는다.
    """
    ids = check_selection(session_ids)
    recs = await collect(ids, user_id)
    data, turn_map = merge(recs)
    turns = {t["global_turn"] for t in turn_map}
    log.info("자서전 요청 — 회차 %d개 %s · 말씀 %d턴 · 모델 %s",
             len(ids), ",".join(s[:8] for s in ids), len(turns),
             env_str("MEMOIR_TEXT_MODEL", DEFAULT_TEXT_MODEL))
    out = check(await write(data), turns)
    log.info("자서전 응답 — %s · 본문 %d줄 · 확인 %d건 · 범위 메모 %s",
             out["status"], len(out["body"].split("\n")) if out["body"] else 0,
             len(out["to_confirm"]), out["coverage_notes"])
    return {**{k: out[k] for k in SHOWN}, "style": style}
