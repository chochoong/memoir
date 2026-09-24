"""
저장 — PostgreSQL (asyncpg)

세션·조각·사진을 남긴다. 대상 테이블은 `migrations/` 가 정의한다.

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
from typing import TYPE_CHECKING, Any

from . import migrate

if TYPE_CHECKING:
    from .controller import SessionController

log = logging.getLogger("store")

_pool: Any = None


def enabled() -> bool:
    return _pool is not None


def _sid(ctl: "SessionController") -> uuid.UUID:
    """
    asyncpg 는 UUID 컬럼에 str 을 받지 않는다. controller 는 session_id 를 str 로
    들고 다니므로(HTTP·JSON 에 그대로 나가야 한다) 여기서만 변환한다.
    """
    return uuid.UUID(ctl.session_id)


def _pid(value: str | None) -> "uuid.UUID | None":
    """
    사진 id 를 UUID 로. **모양이 틀리면 예외가 아니라 None 이다.**

    여기서 올리면 save_session 의 except 가 받아 회차 행이 통째로 안 써진다 —
    화면이 보낸 사진 id 한 줄 때문에 어르신의 이야기가 저장되지 않는 것은
    바꿀 수 없는 손해다. 틀린 id 는 controller._analyze_photo 가 사진을 못
    읽는 것으로 드러나고, 그쪽이 까닭을 로그에 적는다.
    """
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


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
    기동 시 한 번. **두 실패를 다르게 다룬다.**

        DB 에 못 붙었다        메모리 전용으로 계속 간다 (예전과 같다)
        붙었는데 스키마 실패   기동을 멈춘다 — MigrationError 를 올린다

    앞은 관대해야 한다. DB 가 없다고 서버가 안 뜨면 프론트 작업이 Postgres
    셋업을 기다리게 된다.

    **뒤는 관대하면 안 된다.** 이 파일의 쓰기 함수들이 전부 실패를 삼키기
    때문이다. 스키마가 틀린 채로 뜨면 모든 INSERT 가 조용히 실패하고, 화면은
    멀쩡하고, 어르신은 한 시간을 말씀하시고, 아무것도 남지 않는다. DB 가 없는
    것보다 나쁘다 — 없으면 적어도 로그 첫 줄에 「DB 없이 간다」가 찍힌다.
    prompt.load() 를 기동 실패로 둔 것과 같은 이유다 (main.py lifespan 참조).
    """
    global _pool
    try:
        import asyncpg
        _pool = await asyncpg.create_pool(**_dsn(), min_size=1, max_size=5,
                                          command_timeout=5, timeout=5)
    except Exception as e:                                   # noqa: BLE001
        _pool = None
        log.warning("DB 없이 간다 (%s: %s) — 세션이 메모리에만 남는다",
                    type(e).__name__, str(e)[:120])
        return

    try:
        con = await _pool.acquire()
        try:
            await migrate.apply(con)
        finally:
            await _pool.release(con)
    except Exception as e:
        await _pool.close()
        _pool = None
        raise migrate.MigrationError(
            f"스키마를 올리지 못했습니다 ({type(e).__name__}: {str(e)[:200]})") from e

    log.info("DB 연결 · 스키마 확인 완료")


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def save_session(ctl: "SessionController") -> None:
    """회차를 연다. 0번 조각(씨앗)은 controller 가 따로 save_turn 으로 넣는다."""
    if _pool is None:
        return
    try:
        async with _pool.acquire() as con:
            await con.execute(
                """
                INSERT INTO session (session_id, user_id, title, state, turn,
                                     max_turn, t2_seconds, photo_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (session_id) DO NOTHING
                """,
                _sid(ctl), ctl.user_id, ctl.title, ctl.machine.state.value,
                ctl.machine.turn, ctl.machine.max_turn,
                Decimal(str(ctl.timers.t2_seconds)), _pid(ctl.photo_id))
    except Exception as e:                                   # noqa: BLE001
        log.error("세션 저장 실패 (%s: %s)", type(e).__name__, str(e)[:120])


async def save_photo_clues(ctl: "SessionController", clues: dict) -> None:
    """
    사진 단서를 회차에 적는다. **회차당 한 번이다** (controller._analyze_photo).

    분석이 도는 동안 어르신이 중단하셨으면 UPDATE 가 0행을 고치고 조용히 끝난다.
    그게 맞다 — 닫힌 회차에 단서를 적을 일은 없다.
    """
    if _pool is None:
        return
    try:
        async with _pool.acquire() as con:
            await con.execute(
                "UPDATE session SET photo_clues = $2 WHERE session_id = $1",
                _sid(ctl), json.dumps(clues, ensure_ascii=False))
    except Exception as e:                                   # noqa: BLE001
        log.error("사진 단서 저장 실패 (%s: %s)", type(e).__name__, str(e)[:120])


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


def pool():
    """
    다른 모듈이 쓰는 풀. photostore.PgStore 가 이걸 쓴다.

    _pool 을 직접 import 하게 두지 않는 이유 — `from .store import _pool` 로
    가져가면 open_pool() 이 나중에 대입한 값을 못 본다. 함수로 감싸면 부를
    때마다 지금 값을 본다.
    """
    return _need_pool()


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
        # 엽서를 그릴 때 참고로 줄 사진. 사진 없이 연 회차는 None 이다.
        "photo_id": str(r["photo_id"]) if r["photo_id"] else None,
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
    created_at 으로 정렬하지 않는다 — 0번 조각(씨앗)과 1번이 같은 초에 들어가면
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
            prow = await con.fetchrow(
                "SELECT text, storage_key, created_at FROM postcard WHERE session_id = $1",
                sid)
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
        # 구운 엽서. 바이트 주소는 라우트가 붙이고 storage_key 는 거기서 떼어 낸다 —
        # 여기는 어디서 서빙되는지 모른다.
        "postcard": {
            "text": prow["text"],
            "storage_key": prow["storage_key"],
            "created_at": prow["created_at"].isoformat(),
        } if prow else None,
    }


# ---------------------------------------------------------------- 사진
#
# **여기부터가 이 파일의 유일한 예외다. 사진 쓰기는 실패를 삼키지 않는다.**
#
# 위의 save_session · save_turn 이 실패를 삼키는 이유는 분명하다. 어르신이
# 말씀하시는 중에 Postgres 가 비틀거렸다고 인터뷰가 끊기면 안 되고, 잃는 것은
# 그 턴의 기록 하나다. 아무도 「저장됐다」는 말을 듣지 않았다.
#
# 사진은 다르다. 어르신은 사진을 고르고 올리는 **행동**을 하셨고, 화면은 그
# 결과를 돌려준다. 여기서 실패를 삼키면 화면이 「올렸습니다」라고 말하는데 행이
# 없다. 다음에 열면 사진이 사라져 있고, 어르신에게 그건 기억이 지워진 일이다.
# 올리는 일은 다시 하면 되지만 「됐다고 들었는데 안 됐다」는 되돌릴 수 없다.
#
# 그래서 사진 함수는 올린다. 라우트가 그것을 503 으로 바꾸고 화면은 「지금은
# 저장하지 못했습니다」라고 말한다 — 다시 하면 된다는 뜻이 전달된다.


def _photo_row(r: Any) -> dict:
    return {
        "photo_id": str(r["photo_id"]),
        "session_id": str(r["session_id"]) if r["session_id"] else None,
        "user_id": r["user_id"],
        "storage_key": r["storage_key"],
        "mime": r["mime"],
        "status": r["status"],
        "bytes": r["bytes"],
        "sha256": r["sha256"],
        "width": r["width"],
        "height": r["height"],
        "exif_taken_at": r["exif_taken_at"].isoformat() if r["exif_taken_at"] else None,
        "created_at": r["created_at"].isoformat(),
        # 004 이전에 뜬 서버가 남긴 행에는 이 열이 없을 수 있다. 없으면 None 이고,
        # 그건 「아직 분석 안 됐다」와 같은 뜻이라 호출자가 따로 다룰 것이 없다.
        "clues": _jsonb(r["clues"]) if "clues" in r.keys() else None,
    }


async def save_photo(rec: dict) -> None:
    """
    사진 행 하나. **실패하면 올린다** (위 절 주석 참조).

    바이트는 여기 넣지 않는다 — 이미 PhotoStore 에 들어가 있고, 이 행은 그
    바이트를 가리키는 표지다. 순서가 「바이트 먼저, 행 나중」인 이유는
    photo.py 에 적어 두었다.
    """
    pool_ = _need_pool()
    try:
        async with pool_.acquire() as con:
            await con.execute(
                """
                INSERT INTO photo (photo_id, session_id, user_id, storage_key,
                                   mime, status, bytes, sha256, width, height,
                                   exif_taken_at)
                VALUES ($1, $2, $3, $4, $5, 'stored', $6, $7, $8, $9, $10)
                """,
                uuid.UUID(rec["photo_id"]),
                uuid.UUID(rec["session_id"]) if rec.get("session_id") else None,
                rec["user_id"], rec["storage_key"], rec["mime"], rec["bytes"],
                rec.get("sha256"), rec.get("width"), rec.get("height"),
                rec.get("exif_taken_at"))
    except Exception as e:                                   # noqa: BLE001
        log.error("사진 행 저장 실패 %s (%s: %s)",
                  rec.get("photo_id"), type(e).__name__, str(e)[:120])
        raise StoreUnavailable("사진을 저장하지 못했습니다") from e


async def load_photo(photo_id: str) -> dict | None:
    """
    사진 한 장의 표지. 없으면 None — 그건 오류가 아니다.

    **status 로 거르지 않는다.** 거르면 라우트가 「없다」와 「아직 안 됐다」를
    구분할 수 없다. 지금 흐름에서는 행이 생길 때 이미 stored 지만, 나중에
    두 단계 저장이 필요해지면 그 구분이 라우트에 있어야 한다.
    """
    pool_ = _need_pool()
    try:
        pid = uuid.UUID(photo_id)
    except ValueError:
        return None                      # UUID 가 아니면 있을 수 없는 id 다
    try:
        async with pool_.acquire() as con:
            row = await con.fetchrow("SELECT * FROM photo WHERE photo_id = $1", pid)
    except Exception as e:                                   # noqa: BLE001
        log.error("사진 읽기 실패 %s (%s: %s)", photo_id, type(e).__name__, str(e)[:120])
        raise StoreUnavailable("사진을 읽지 못했습니다") from e
    return _photo_row(row) if row else None


async def save_photo_analysis(photo_id: str, clues: dict) -> None:
    """
    §2 단서를 **사진에** 적는다 — 회차가 아니라 사진에 (004 마이그레이션 참조).

    save_photo_clues 와 짝이지만 사는 곳이 다르다. 그쪽은 「이 회차가 무엇을 보고
    물었는가」라서 회차마다 다시 적히고, 이쪽은 「이 사진이 무엇을 담았는가」라서
    사진당 한 번이면 된다. 둘을 하나로 합치면 같은 사진을 쓰는 두 번째 회차가
    첫 회차의 기록을 덮어쓴다.

    **실패를 삼킨다.** 단서는 있으면 좋은 것이지 사진 저장의 조건이 아니다. 못
    적으면 다음 회차가 다시 분석할 뿐이고, 어르신에게는 아무 차이가 없다.
    """
    if _pool is None:
        return
    try:
        async with _pool.acquire() as con:
            await con.execute(
                "UPDATE photo SET clues = $2 WHERE photo_id = $1",
                uuid.UUID(photo_id), json.dumps(clues, ensure_ascii=False))
    except Exception as e:                                   # noqa: BLE001
        log.error("사진 단서 저장 실패 %s (%s: %s) — 다음 회차가 다시 분석한다",
                  photo_id[:8], type(e).__name__, str(e)[:120])


async def delete_photo_row(photo_id: str) -> None:
    """
    보상 삭제. 바이트는 들어갔는데 행을 못 넣었을 때 되돌리는 쪽이다.

    **실패를 삼킨다.** 여기까지 왔다면 이미 어르신께 503 을 돌려주기로 정해진
    뒤고, 정리에 또 실패했다고 더 할 수 있는 일이 없다. 남는 것은 주인 없는
    바이트 몇백 KB 이고, 그건 조용히 로그에만 남으면 된다.
    """
    if _pool is None:
        return
    try:
        async with _pool.acquire() as con:
            await con.execute("DELETE FROM photo WHERE photo_id = $1",
                              uuid.UUID(photo_id))
    except Exception as e:                                   # noqa: BLE001
        log.error("사진 행 정리 실패 %s (%s: %s) — 고아 행이 남는다",
                  photo_id, type(e).__name__, str(e)[:120])


# ---------------------------------------------------------------- 엽서
#
# 사진 절과 같은 규칙이다. **실패하면 올린다.** 엽서는 어르신이 버튼을 눌러
# 기다리는 결과물이라, 못 넣었는데 성공했다고 말하면 보관함에 빈 칸이 생긴다.


def _postcard_row(r: Any) -> dict:
    return {
        "session_id": str(r["session_id"]),
        "user_id": r["user_id"],
        "text": r["text"],
        "storage_key": r["storage_key"],
        "mime": r["mime"],
        "bytes": r["bytes"],
        "width": r["width"],
        "height": r["height"],
        "photo_id": str(r["photo_id"]) if r["photo_id"] else None,
        "text_model": r["text_model"],
        "image_model": r["image_model"],
        "created_at": r["created_at"].isoformat(),
    }


async def save_postcard(rec: dict) -> str | None:
    """
    엽서 행을 넣거나 덮어쓴다. **덮어쓰기 전의 키를 돌려준다.**

    옛 바이트를 지우는 것은 호출자다. 여기서 지우면 행과 바이트를 한 함수가 같이
    쥐게 되는데, 바이트는 이 파일이 아니라 PhotoStore 의 일이다.

    옛 키는 CTE 로 같은 문장 안에서 읽는다. 따로 SELECT 하면 그 사이에 다른
    요청이 행을 바꿔 엉뚱한 키를 지울 수 있다.
    """
    pool_ = _need_pool()
    try:
        async with pool_.acquire() as con:
            return await con.fetchval(
                """
                WITH old AS (SELECT storage_key FROM postcard WHERE session_id = $1)
                INSERT INTO postcard (session_id, user_id, text, storage_key, mime,
                                      bytes, width, height, photo_id,
                                      text_model, image_model)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (session_id) DO UPDATE
                   SET user_id     = EXCLUDED.user_id,
                       text        = EXCLUDED.text,
                       storage_key = EXCLUDED.storage_key,
                       mime        = EXCLUDED.mime,
                       bytes       = EXCLUDED.bytes,
                       width       = EXCLUDED.width,
                       height      = EXCLUDED.height,
                       photo_id    = EXCLUDED.photo_id,
                       text_model  = EXCLUDED.text_model,
                       image_model = EXCLUDED.image_model,
                       created_at  = now()
                RETURNING (SELECT storage_key FROM old)
                """,
                uuid.UUID(rec["session_id"]), rec["user_id"], rec["text"],
                rec["storage_key"], rec["mime"], rec["bytes"], rec["width"],
                rec["height"], _pid(rec.get("photo_id")),
                rec.get("text_model"), rec.get("image_model"))
    except Exception as e:                                   # noqa: BLE001
        log.error("엽서 행 저장 실패 %s (%s: %s)",
                  rec.get("session_id"), type(e).__name__, str(e)[:120])
        raise StoreUnavailable("엽서를 저장하지 못했습니다") from e


async def load_postcard(session_id: str) -> dict | None:
    """회차의 엽서. 아직 안 구웠으면 None — 그건 오류가 아니다."""
    pool_ = _need_pool()
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        return None
    try:
        async with pool_.acquire() as con:
            row = await con.fetchrow("SELECT * FROM postcard WHERE session_id = $1", sid)
    except Exception as e:                                   # noqa: BLE001
        log.error("엽서 읽기 실패 %s (%s: %s)", session_id, type(e).__name__, str(e)[:120])
        raise StoreUnavailable("엽서를 읽지 못했습니다") from e
    return _postcard_row(row) if row else None
