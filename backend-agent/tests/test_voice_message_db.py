"""
가족 음성편지 — 실제 Postgres 에서 store 의 SQL · 트랜잭션 (019)

    MEMOIR_TEST_PG_DSN=postgresql://…/빈_시험_DB  python -m pytest tests/test_voice_message_db.py -q

**빈 시험용 DB 에서만 돈다** — 마이그레이션 전부를 걸고, 시험 줄을 넣는다. 서비스 DB 를 가리키지 않는다.
DSN 이 없으면 건너뛴다. 동시에 두 연결이 같은 책에 연결할 때 하나만 이기는지도 본다.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.session import migrate, store

DSN = os.environ.get("MEMOIR_TEST_PG_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="MEMOIR_TEST_PG_DSN 없음 — 시험용 빈 DB 에서만 돈다")


def _up(uid, rid, minutes=60):
    i = uuid.uuid4().hex
    return {"upload_id": f"vu_{i}", "user_id": uid, "request_id": rid, "mime": "audio/webm", "size_bytes": 10,
            "duration_ms": 1000, "sha256": "0" * 64, "storage_key": f"voice/2026/11/vu_{i}/original.webm",
            "play_key": f"voice/2026/11/vu_{i}/play.m4a", "play_mime": "audio/mp4", "play_bytes": 5,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=minutes)}


def test_attach_replace_delete_conflict_and_purge_on_real_postgres():
    import asyncpg

    async def main():
        pool = await asyncpg.create_pool(DSN, min_size=2, max_size=4)
        async with pool.acquire() as con:
            await migrate.apply(con)
            me, mid, mid2 = f"u_{uuid.uuid4().hex[:8]}", f"m_{uuid.uuid4().hex}", f"m_{uuid.uuid4().hex}"
            await con.execute("INSERT INTO app_user (user_id, provider, subject) VALUES ($1, 't', $1)", me)
            for m in (mid, mid2):
                await con.execute("INSERT INTO memoir (memoir_id, user_id, session_ids, result) VALUES ($1, $2, '{}', '{}')", m, me)
        store._pool = pool
        try:
            a = await store.save_voice_upload(_up(me, "r1"))
            assert a["state"] == "uploaded"
            dup = await store.save_voice_upload(_up(me, "r1"))                 # 같은 요청 id
            assert dup["upload_id"] == a["upload_id"]
            assert await store.attach_voice(mid, me, a["upload_id"], "l1", 0) == ("ok", None)
            assert await store.attach_voice(mid, me, a["upload_id"], "l1", 0) == ("same", None)
            cur = await store.load_memoir_voice(mid, me)
            assert cur["revision"] == 1 and cur["upload"]["state"] == "attached" and cur["upload"]["memoir_id"] == mid
            assert await store.attach_voice(mid2, me, a["upload_id"], "l9", 0) == ("upload_in_use", None)
            assert await store.attach_voice(mid, "u_nobody", a["upload_id"], "l2", 1) == ("memoir_not_found", None)

            # 동시에 두 교체 — 같은 expected_revision 으로 둘 중 하나만
            b, c = await store.save_voice_upload(_up(me, "r2")), await store.save_voice_upload(_up(me, "r3"))
            got = await asyncio.gather(store.attach_voice(mid, me, b["upload_id"], "l2", 1),
                                       store.attach_voice(mid, me, c["upload_id"], "l3", 1))
            assert sorted(g[0] for g in got) == ["conflict", "ok"]
            async with pool.acquire() as con:
                assert await con.fetchval("SELECT count(*) FROM voice_upload WHERE memoir_id = $1 AND state = 'attached'", mid) == 1
                assert await con.fetchval("SELECT state FROM voice_upload WHERE upload_id = $1", a["upload_id"]) == "released"

            assert (await store.detach_voice(mid, me, 1))[0] == "conflict"
            assert await store.detach_voice(mid, me, 2) == ("ok", None)
            assert (await store.load_memoir_voice(mid, me))["upload"] is None
            assert await store.detach_voice(mid, me, 3) == ("no_message", None)
            assert await store.detach_voice(mid2, me, 0) == ("no_message", None)
            assert await store.detach_voice("m_none", me, 0) == ("memoir_not_found", None)

            old = await store.save_voice_upload(_up(me, "r4", minutes=-5))       # 기한 지남
            assert await store.attach_voice(mid, me, old["upload_id"], "l4", 3) == ("upload_expired", None)
            assert await store.discard_voice_upload(old["upload_id"], me) == "ok"
            assert await store.discard_voice_upload(old["upload_id"], "u_x") == "not_found"

            purge = {r["upload_id"] for r in await store.voice_to_purge(100)}
            assert a["upload_id"] in purge and old["upload_id"] in purge
            for u in purge:
                assert await store.mark_voice_purged(u)
            assert not {r["upload_id"] for r in await store.voice_to_purge(100)} & purge

            # 공유의 원본 — 내 책일 때만 단다
            async with pool.acquire() as con:
                await con.execute("INSERT INTO memoir_share (share_id, token_hash, user_id, book_id, title, book) "
                                  "VALUES ('s_t1', $1, $2, $3, 't', '{}')", uuid.uuid4().hex, me, mid)
            await store.set_share_source("s_t1", "u_x", mid)
            assert (await store.load_share_by_id("s_t1"))["source_memoir_id"] is None
            await store.set_share_source("s_t1", me, mid)
            assert (await store.load_share_by_id("s_t1"))["source_memoir_id"] == mid
        finally:
            store._pool = None
            await pool.close()

    asyncio.run(main())
