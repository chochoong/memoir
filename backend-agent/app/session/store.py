"""
저장 — PostgreSQL (asyncpg)

세션과 조각을 남긴다. `schema.sql` 의 세 테이블이 그대로 대상이다.

**DB 가 없어도, 중간에 끊겨도 회차는 돈다.**

이게 이 파일의 유일한 규칙이다. 어르신이 말씀하시는 도중에 Postgres 가 한 번
비틀거렸다고 인터뷰가 끊기면 안 된다. 그래서 모든 함수가 실패를 삼키고 로그만
남긴다 — 조각은 이미 controller 의 메모리에 있고, 화면은 그걸로 계속 돈다.

잃는 것은 그 턴의 기록뿐이고, 그건 회차가 끊기는 것보다 싸다. 대신 조용히
넘어가지는 않는다. 로그에 ERROR 로 남겨 나중에 셀 수 있게 한다.

환경변수는 **함수 안에서** 읽는다. main.py 가 load_dotenv() 를 import 뒤에 부르기
때문에, 모듈 수준에서 읽으면 .env 가 아직 로드되기 전이라 빈 값을 잡는다.
(question.py 와 같은 이유다)
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .controller import SessionController

log = logging.getLogger("store")

_pool: Any = None
_SCHEMA = Path(__file__).resolve().parents[1] / "schema.sql"


def enabled() -> bool:
    return _pool is not None


def _sid(ctl: "SessionController") -> uuid.UUID:
    """
    asyncpg 는 UUID 컬럼에 str 을 받지 않는다. controller 는 session_id 를 str 로
    들고 다니므로(HTTP·JSON 에 그대로 나가야 한다) 여기서만 변환한다.
    """
    return uuid.UUID(ctl.session_id)


def _dsn() -> dict[str, Any]:
    return dict(
        host=os.environ.get("PG_HOST", "localhost"),
        port=int(os.environ.get("PG_PORT", "5432")),
        user=os.environ.get("PG_USER", "memoir"),
        password=os.environ.get("PG_PASSWORD", ""),
        database=os.environ.get("PG_DB", "memoir"),
    )


async def open_pool() -> None:
    """
    기동 시 한 번. 붙지 못하면 **메모리 전용으로 계속 간다.**

    DB 가 없다고 서버가 안 뜨면 프론트 작업이 Postgres 셋업을 기다리게 된다.
    1주차 게이트는 텍스트 3턴이지 영속성이 아니다.

    스키마도 여기서 적용한다. schema.sql 이 전부 CREATE TABLE IF NOT EXISTS 라
    몇 번을 걸어도 같고, 마이그레이션 도구를 쓰지 않기로 한 이상 이게 가장 싸다.
    """
    global _pool
    try:
        import asyncpg
        _pool = await asyncpg.create_pool(**_dsn(), min_size=1, max_size=5,
                                          command_timeout=5, timeout=5)
        async with _pool.acquire() as con:
            await con.execute(_SCHEMA.read_text(encoding="utf-8"))
        log.info("DB 연결 · 스키마 적용 완료")
    except Exception as e:                                   # noqa: BLE001
        _pool = None
        log.warning("DB 없이 간다 (%s: %s) — 세션이 메모리에만 남는다",
                    type(e).__name__, str(e)[:120])


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def save_session(ctl: "SessionController") -> None:
    """회차를 연다. 0번 조각(엽서)은 controller 가 따로 save_turn 으로 넣는다."""
    if _pool is None:
        return
    try:
        async with _pool.acquire() as con:
            await con.execute(
                """
                INSERT INTO session (session_id, user_id, title, state, turn,
                                     max_turn, t2_seconds)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (session_id) DO NOTHING
                """,
                _sid(ctl), ctl.user_id, ctl.title, ctl.machine.state.value,
                ctl.machine.turn, ctl.machine.max_turn, Decimal(str(ctl.timers.t2_seconds)))
    except Exception as e:                                   # noqa: BLE001
        log.error("세션 저장 실패 (%s: %s)", type(e).__name__, str(e)[:120])


async def save_turn(ctl: "SessionController", fragment: dict) -> None:
    """
    조각 하나. **확정되자마자 넣는다** — 지연 숫자를 기다리지 않는다.

    어르신의 말을 잃지 않는 게 먼저다. latency 와 decision 은 나중에
    update_turn_marks 로 채운다. UNIQUE(session_id, idx) 라 재시도해도 안전하다.
    """
    if _pool is None:
        return
    try:
        async with _pool.acquire() as con:
            await con.execute(
                """
                INSERT INTO turn (session_id, idx, question, answer, decision)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (session_id, idx) DO UPDATE
                   SET question = EXCLUDED.question,
                       answer   = EXCLUDED.answer
                """,
                _sid(ctl), fragment["idx"], fragment["question"],
                fragment["answer"],
                json.dumps(ctl.last_decision, ensure_ascii=False)
                if ctl.last_decision else None)
    except Exception as e:                                   # noqa: BLE001
        log.error("조각 저장 실패 idx=%s (%s: %s)",
                  fragment.get("idx"), type(e).__name__, str(e)[:120])


async def update_turn_marks(ctl: "SessionController", idx: int,
                            latency: dict | None) -> None:
    """
    구간별 지연(FR-AD-314)을 뒤늦게 채운다. **decision 은 건드리지 않는다.**

    여기서 같이 쓰면 근거가 한 칸씩 밀린다. 이 함수가 불릴 때쯤이면
    _make_question 이 이미 **다음** 질문을 만들면서 ctl.last_decision 을
    덮어쓴 뒤다. 그걸 이 턴에 쓰면 「창밖 풍경을 물었는데 근거는 고구마 맛」이 된다.

    decision 은 save_turn 시점에 이미 맞게 들어가 있다. 그대로 둔다.
    """
    if _pool is None:
        return
    try:
        async with _pool.acquire() as con:
            await con.execute(
                """
                UPDATE turn SET latency = COALESCE($3, latency)
                 WHERE session_id = $1 AND idx = $2
                """,
                _sid(ctl), idx,
                json.dumps(latency, ensure_ascii=False) if latency else None)
    except Exception as e:                                   # noqa: BLE001
        log.error("지연 기록 실패 idx=%s (%s: %s)", idx, type(e).__name__, str(e)[:120])


async def update_session(ctl: "SessionController",
                         closed_reason: str | None = None) -> None:
    """상태·턴을 맞추고, 닫혔으면 이유와 시각을 남긴다."""
    if _pool is None:
        return
    try:
        async with _pool.acquire() as con:
            await con.execute(
                """
                UPDATE session
                   SET state = $2, turn = $3,
                       closed_reason = COALESCE($4, closed_reason),
                       closed_at = CASE WHEN $2 = 'CLOSED' AND closed_at IS NULL
                                        THEN now() ELSE closed_at END
                 WHERE session_id = $1
                """,
                _sid(ctl), ctl.machine.state.value, ctl.machine.turn,
                closed_reason)
    except Exception as e:                                   # noqa: BLE001
        log.error("세션 갱신 실패 (%s: %s)", type(e).__name__, str(e)[:120])


# ---------------------------------------------------------------- 읽기
#
# **읽기는 실패를 삼키지 않는다.** 위의 쓰기 함수들과 정반대다.
#
# 쓰기를 삼키는 이유는 분명하다. 어르신이 말씀하시는 중에 Postgres 가 한 번
# 비틀거렸다고 인터뷰가 끊기면 안 된다. 잃는 건 그 턴의 기록 하나뿐이다.
#
# 읽기는 반대다. 실패를 삼키고 빈 목록을 돌려주면 화면에 「기록이 없습니다」가
# 뜬다. 어르신에게 그건 **조각이 사라졌다는 말**이다. 있는데 못 읽은 것과
# 정말 없는 것은 전혀 다른 사건이고, 화면도 다르게 말해야 한다. 그래서 올린다.


class StoreUnavailable(RuntimeError):
    """DB 가 없거나 읽기에 실패했다. 「기록이 없다」와 구분하려고 따로 둔다."""


def _need_pool():
    if _pool is None:
        raise StoreUnavailable("DB 에 연결되어 있지 않습니다")
    return _pool


def _jsonb(v: Any) -> Any:
    """
    asyncpg 는 JSONB 를 파싱하지 않고 str 로 돌려준다.

    풀에 코덱을 걸어 해결할 수도 있지만, 그러면 쓰기 쪽에서 이미 json.dumps 로
    넘기는 값이 이중 인코딩된다. 읽는 자리에서만 푸는 쪽이 안전하다.
    """
    if v is None or isinstance(v, (dict, list)):
        return v
    return json.loads(v)


def _session_row(r: Any) -> dict:
    """DB 행 → JSON 으로 내보낼 수 있는 형태. UUID·Decimal·datetime 이 섞여 있다."""
    return {
        "session_id": str(r["session_id"]),
        "user_id": r["user_id"],
        "title": r["title"],
        "state": r["state"],
        "turn": r["turn"],
        "max_turn": r["max_turn"],
        "t2_seconds": float(r["t2_seconds"]),
        "closed_reason": r["closed_reason"],
        "created_at": r["created_at"].isoformat(),
        "closed_at": r["closed_at"].isoformat() if r["closed_at"] else None,
    }


async def list_sessions(user_id: str, limit: int = 20) -> list[dict]:
    """
    지난 회차 목록. 최근 순. 조각 개수를 같이 센다.

    user_id 로 거른다. 지금은 X-User-Id 헤더를 그대로 믿으므로 막아 주지는
    못하지만, 로그인이 붙으면 이 조건이 그대로 실효를 가진다.
    """
    pool = _need_pool()
    try:
        async with pool.acquire() as con:
            rows = await con.fetch(
                """
                SELECT s.*, (SELECT count(*) FROM turn t
                              WHERE t.session_id = s.session_id) AS fragment_count
                  FROM session s
                 WHERE s.user_id = $1
                 ORDER BY s.created_at DESC
                 LIMIT $2
                """,
                user_id, limit)
    except Exception as e:                                   # noqa: BLE001
        log.error("회차 목록 읽기 실패 (%s: %s)", type(e).__name__, str(e)[:120])
        raise StoreUnavailable("회차 목록을 읽지 못했습니다") from e
    return [{**_session_row(r), "fragment_count": r["fragment_count"]} for r in rows]


async def load_session(session_id: str) -> dict | None:
    """
    회차 하나를 조각까지 통째로. 없으면 None — 그건 오류가 아니다.

    조각은 idx 순으로 준다. **idx 가 곧 서사의 시간 순서다** (FR-AD-401).
    created_at 으로 정렬하지 않는다 — 0번 조각(엽서)과 1번이 같은 초에 들어가면
    순서가 뒤집힌다.
    """
    pool = _need_pool()
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        return None                      # UUID 가 아니면 있을 수 없는 id 다
    try:
        async with pool.acquire() as con:
            srow = await con.fetchrow(
                "SELECT * FROM session WHERE session_id = $1", sid)
            if srow is None:
                return None
            trows = await con.fetch(
                """
                SELECT idx, question, answer, decision, latency, created_at
                  FROM turn WHERE session_id = $1 ORDER BY idx
                """, sid)
    except Exception as e:                                   # noqa: BLE001
        log.error("회차 읽기 실패 %s (%s: %s)", session_id, type(e).__name__, str(e)[:120])
        raise StoreUnavailable("회차를 읽지 못했습니다") from e

    return {
        **_session_row(srow),
        "fragments": [{
            "idx": t["idx"],
            "question": t["question"],
            "answer": t["answer"],
            "decision": _jsonb(t["decision"]),
            "latency": _jsonb(t["latency"]),
            "created_at": t["created_at"].isoformat(),
        } for t in trows],
    }
