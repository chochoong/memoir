"""
화자 연결 — 회차의 elder_id 를 실제 SQL 로 (store.assign_elder · list_sessions 의 화자 필터)

    python -m tests.test_speaker

**로컬 DB 를 쓰되 남기지 않는다** (tests/test_title.py 와 같은 방식). 연결 하나의
트랜잭션 안에서 합성 자녀 · 화자 · 회차를 넣고 store 함수를 그 연결로 돌린 뒤 되돌린다.
실제 사용자 행은 읽지도 않는다. 모델은 부르지 않는다.

라우트의 갈래 (404 · 409 · 401) 는 tests/test_link.py [화자] 가 본다. 여기는 SQL 이다.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

from app.session import store
from tests.test_title import _connect, _OnePool, _session

PASS, FAIL = [], []
A, B = "t_speaker_A", "t_speaker_B"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else '!! '}{name}{'  — ' + detail if detail else ''}")


async def _user(con, user_id):
    await con.execute("INSERT INTO app_user (user_id, provider, subject) VALUES ($1, 'test', $1)", user_id)


async def _elder(con, user_id, name) -> str:
    elder_id = f"e_t_{uuid.uuid4().hex[:12]}"
    await con.execute("INSERT INTO elder (elder_id, display_name) VALUES ($1, $2)", elder_id, name)
    await con.execute("INSERT INTO user_elder (user_id, elder_id) VALUES ($1, $2)", user_id, elder_id)
    return elder_id


async def run(con):
    base = datetime(2026, 10, 26, tzinfo=timezone.utc)
    at = lambda m: base + timedelta(minutes=m)                          # noqa: E731
    await _user(con, A)
    await _user(con, B)
    mom, dad = await _elder(con, A, "어머니"), await _elder(con, A, "아버지")
    b_mom = await _elder(con, B, "어머니")

    s_none = await _session(con, A, "화자 미지정", at(1))
    s_other = await _session(con, A, "또 미지정", at(2))
    s_b = await _session(con, B, "B 의 회차", at(3))

    print("\n[S1] 미지정 회차에 화자를 한 번 정한다")
    check("남의 회차 → no_session", await store.assign_elder(s_b, A, mom) == "no_session")
    check("없는 회차 · UUID 아님 → no_session",
          await store.assign_elder(str(uuid.uuid4()), A, mom) == "no_session"
          and await store.assign_elder("not-a-uuid", A, mom) == "no_session")
    check("남의 화자 → no_elder", await store.assign_elder(s_none, A, b_mom) == "no_elder")
    check("미지정 → set", await store.assign_elder(s_none, A, mom) == "set")
    got = await con.fetchval("SELECT elder_id FROM session WHERE session_id = $1", uuid.UUID(s_none))
    check("DB 에 그 화자가 적혔다", got == mom, str(got))
    check("같은 화자를 다시 → same", await store.assign_elder(s_none, A, mom) == "same")
    check("다른 화자로 → taken · 바뀌지 않는다", await store.assign_elder(s_none, A, dad) == "taken"
          and await con.fetchval("SELECT elder_id FROM session WHERE session_id = $1",
                                 uuid.UUID(s_none)) == mom)
    check("거절된 요청은 다른 회차를 건드리지 않았다",
          await con.fetchval("SELECT elder_id FROM session WHERE session_id = $1", uuid.UUID(s_other)) is None
          and await con.fetchval("SELECT elder_id FROM session WHERE session_id = $1", uuid.UUID(s_b)) is None)

    print("\n[S2] 목록 — 회차마다 elder_id · 화자 필터")
    rows = {r["session_id"]: r for r in await store.list_sessions(A, 100)}
    check("목록에 elder_id 칸 — 정한 회차는 화자, 미지정은 None",
          rows[s_none]["elder_id"] == mom and "elder_id" in rows[s_other]
          and rows[s_other]["elder_id"] is None, str({k: v["elder_id"] for k, v in rows.items()}))
    only = [r["session_id"] for r in await store.list_sessions(A, 100, elder_id=mom)]
    check("elder_id 필터 → 그 화자 회차만 (미지정 빠짐)", only == [s_none], str(only))
    check("남의 화자로 거르면 빈 목록", await store.list_sessions(A, 100, elder_id=b_mom) == [])
    rec = await store.load_session(s_none)
    check("load_session 에도 elder_id (자서전 화자 확인이 읽는 값)", rec["elder_id"] == mom)


async def main():
    try:
        con = await _connect()
    except Exception as e:                                   # noqa: BLE001
        print(f"로컬 DB 에 붙지 못했다 — 확인 불가 ({type(e).__name__})")
        return 2
    tr = con.transaction()
    await tr.start()
    old = store._pool
    store._pool = _OnePool(con)
    try:
        await run(con)
    finally:
        store._pool = old
        await tr.rollback()
        await con.close()
    print("\n" + "=" * 52)
    print(f"통과 {len(PASS)} · 실패 {len(FAIL)}  (로컬 DB · 트랜잭션 되돌림 · 모델 호출 없음)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
