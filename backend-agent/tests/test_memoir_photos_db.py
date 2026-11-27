"""
자서전 사진 배치 — 실제 Postgres 에서 store 의 SQL (018 · 020)

    MEMOIR_TEST_PG_DSN=postgresql://…/빈_시험_DB  python -m pytest tests/test_memoir_photos_db.py -q

**빈 시험용 DB 에서만 돈다.** DSN 이 없으면 건너뛴다.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.session import memoir_photos as mp, migrate, store

DSN = os.environ.get("MEMOIR_TEST_PG_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="MEMOIR_TEST_PG_DSN 없음 — 시험용 빈 DB 에서만 돈다")
P = "11111111-1111-4111-8111-111111111111"


def test_auto_rows_keep_their_anchor_and_books_do_not_collide():
    import asyncpg

    async def main():
        pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
        async with pool.acquire() as con:
            await migrate.apply(con)
            me, a, b = f"u_{uuid.uuid4().hex[:8]}", f"m_{uuid.uuid4().hex}", f"m_{uuid.uuid4().hex}"
            await con.execute("INSERT INTO app_user (user_id, provider, subject) VALUES ($1, 't', $1)", me)
            for m in (a, b):
                await con.execute("INSERT INTO memoir (memoir_id, user_id, session_ids, result) VALUES ($1, $2, '{}', '{}')", m, me)
        store._pool = pool
        try:
            base = {"user_id": me, "photo_id": P, "origin": "auto", "chapter_no": 1, "after_paragraph": 0,
                    "display_order": 0, "hidden": True, "width": 1, "height": 1}
            ra = await store.save_photo_placement({**base, "placement_id": mp.auto_id(a, P, "S1"), "memoir_id": a,
                                                   "sessions": ["S1", "S2"], "anchor_session": "S1"})
            rb = await store.save_photo_placement({**base, "placement_id": mp.auto_id(b, P, "S1"), "memoir_id": b,
                                                   "sessions": ["S1", "S2"], "anchor_session": "S1"})
            assert ra and rb and ra["placement_id"] != rb["placement_id"]          # 같은 사진 · 회차, 다른 책 — 둘 다 저장
            again = await store.save_photo_placement({**base, "placement_id": ra["placement_id"], "memoir_id": a,
                                                      "hidden": False, "sessions": ["S2"], "anchor_session": "S2"})
            assert again["sessions"] == ["S2"] and again["anchor_session"] == "S1" and again["hidden"] is False
            keep = await store.save_photo_placement({**base, "placement_id": ra["placement_id"], "memoir_id": a,
                                                     "sessions": None, "anchor_session": None})
            assert keep["sessions"] == ["S2"] and keep["anchor_session"] == "S1"
            assert await store.save_photo_placement({**base, "placement_id": ra["placement_id"], "memoir_id": b}) is None
            got = await store.list_photo_placements(a, me)
            assert [r["placement_id"] for r in got] == [ra["placement_id"]]
        finally:
            store._pool = None
            await pool.close()

    asyncio.run(main())
