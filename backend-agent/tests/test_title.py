"""
엽서 목록 제목 — 목록의 postcard_title 과 상세의 postcard.title (TITLE-T01 ~ T06)

    python -m tests.test_title

**로컬 DB 를 쓰되 남기지 않는다.** 연결 하나를 열어 트랜잭션 안에서 합성 회차 ·
엽서를 넣고, 라우트(GET /api/sessions · /record · POST /postcard)를 그 연결로
돌린 뒤 되돌린다. 실제 사용자 행은 T02 에서 읽기만 하고 제목은 찍지 않는다 (개수만).
모델은 부르지 않는다 — T05 의 굽기는 _make 를 바꿔 끼워 저장만 한다.

신원은 tests/_auth.py 의 X-User-Id 대역이다. 실제 구글 로그인 격리는 여기서 보지 않는다.

    [T01] 날짜형 회차 제목과 내용형 엽서 제목 — 둘 다 그대로, 목록 = 상세
    [T02] 이미 저장된 엽서 — 다시 굽지 않고 목록 = 상세 (실제 행, 읽기만)
    [T03] 엽서 없는 회차 — false / null, 회차 제목은 그대로 (빈 제목 포함)
    [T04] 엽서는 있고 제목이 "" · 공백 · NULL — true 유지, 저장값 그대로
    [T05] 다시 굽기 A → B, 실패 뒤에도 B, 목록을 읽어도 굽지 않는다
    [T06] 계정 분리 · 정렬 · limit · has_postcard 필터 · DB 실패는 503
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app.session import postcard, store                                  # noqa: E402
from tests._auth import AsHeader                                          # noqa: E402

PASS, FAIL = [], []
A, B = "t_title_A", "t_title_B"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else '!! '}{name}{'  — ' + detail if detail else ''}")


class _OnePool:
    """store 의 풀 자리에 연결 하나 — 모든 읽기 · 쓰기가 같은 트랜잭션 안에서 돈다."""

    def __init__(self, con):
        self.con = con

    @asynccontextmanager
    async def acquire(self):
        yield self.con


class _BrokenPool:
    @asynccontextmanager
    async def acquire(self):
        raise ConnectionError("시험: DB 를 읽을 수 없다")
        yield


async def _connect():
    import asyncpg
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    return await asyncpg.connect(host=os.getenv("PG_HOST", "localhost"),
                                 port=int(os.getenv("PG_PORT", "5432")),
                                 user=os.getenv("PG_USER"), password=os.getenv("PG_PASSWORD"),
                                 database=os.getenv("PG_DB"), timeout=5)


async def _session(con, user, title, at, *, answer=True) -> str:
    sid = str(uuid.uuid4())
    await con.execute(
        "INSERT INTO session (session_id, user_id, title, state, closed_reason, created_at, closed_at)"
        " VALUES ($1, $2, $3, 'CLOSED', 'finish', $4, $4)", uuid.UUID(sid), user, title, at)
    if answer:
        await con.execute("INSERT INTO turn (session_id, idx, question, answer) VALUES ($1, 1, $2, $3)",
                          uuid.UUID(sid), "어떤 이야기를 나누고 싶으세요?", "합성 말씀입니다.")
    return sid


async def _card(sid, user, title):
    return await store.save_postcard({
        "session_id": sid, "user_id": user, "text": "합성 엽서 글", "storage_key": f"t/{uuid.uuid4().hex}.jpg",
        "mime": "image/jpeg", "bytes": 1, "width": 1500, "height": 1000, "title": title,
        "caption": "", "sources": None, "style": "spoken"})


async def run(con, c):
    base = datetime(2026, 10, 22, tzinfo=timezone.utc)
    at = lambda m: base + timedelta(minutes=m)                          # noqa: E731

    def listed(r):
        return {s["session_id"]: s for s in r.json()["sessions"]}

    async def detail(sid, user=A):
        r = await c.get(f"/api/sessions/{sid}/record", headers={"X-User-Id": user})
        return r.json().get("postcard") if r.status_code == 200 else r.status_code

    # ------------------------------------------------------------ T01
    print("\n[T01] 날짜형 회차 제목 · 내용형 엽서 제목")
    s1 = await _session(con, A, "2026-10-22 기록", at(1))
    await _card(s1, A, "처음 열었던 작은 가게")
    r = await c.get("/api/sessions", headers={"X-User-Id": A})
    row = listed(r)[s1]
    check("목록 200", r.status_code == 200, str(r.status_code))
    check("회차 title 은 덮어쓰지 않는다", row["title"] == "2026-10-22 기록", row["title"])
    check("postcard_title 은 저장된 엽서 제목", row["postcard_title"] == "처음 열었던 작은 가게",
          str(row["postcard_title"]))
    check("has_postcard true", row["has_postcard"] is True)
    check("상세 postcard.title 과 같다", (await detail(s1))["title"] == row["postcard_title"])
    check("created_at 은 회차 시각", row["created_at"] == at(1).isoformat(), row["created_at"])

    # ------------------------------------------------------------ T03
    print("\n[T03] 엽서 없는 회차")
    s3a = await _session(con, A, "가족 이야기", at(2))
    s3b = await _session(con, A, "", at(3))
    rows = listed(await c.get("/api/sessions", headers={"X-User-Id": A}))
    for sid, title in ((s3a, "가족 이야기"), (s3b, "")):
        rw = rows[sid]
        check(f"회차 제목 {title!r}: has_postcard false · postcard_title null · 칸은 있다",
              rw["has_postcard"] is False and "postcard_title" in rw and rw["postcard_title"] is None, str(rw))
        check(f"회차 제목 {title!r} 그대로", rw["title"] == title)
        check(f"회차 제목 {title!r}: 상세 postcard 도 null", await detail(sid) is None)
    only = listed(await c.get("/api/sessions?has_postcard=1", headers={"X-User-Id": A}))
    check("엽서 전용 필터에서는 빠진다", s3a not in only and s3b not in only and s1 in only)

    # ------------------------------------------------------------ T04
    print("\n[T04] 엽서는 있고 제목이 비었다")
    for title in ("", "   ", None):
        sid = await _session(con, A, "빈 제목 시험", at(4))
        await _card(sid, A, title)
        rw = listed(await c.get("/api/sessions", headers={"X-User-Id": A}))[sid]
        check(f"제목 {title!r}: has_postcard true", rw["has_postcard"] is True)
        check(f"제목 {title!r}: 저장값 그대로 (서버는 다듬지 않는다)", rw["postcard_title"] == title,
              repr(rw["postcard_title"]))
        check(f"제목 {title!r}: 상세와 같다", (await detail(sid))["title"] == title)
    rows = (await c.get("/api/sessions?limit=100", headers={"X-User-Id": A})).json()["sessions"]
    check("모든 행의 postcard_title 은 문자열 또는 null",
          all(r["postcard_title"] is None or isinstance(r["postcard_title"], str) for r in rows))

    # ------------------------------------------------------------ T05
    print("\n[T05] 다시 굽기 A → B · 실패 · 목록은 굽지 않는다")
    s5 = await _session(con, A, "2026-10-22 기록", at(5))
    await _card(s5, A, "제목 A")
    made: list[str] = []
    fail = {"on": False}

    async def fake_make(rec, said, style):
        if fail["on"]:
            raise postcard.PostcardUnavailable("시험: 엽서 글을 만들지 못했다")
        made.append(rec["session_id"])
        title = f"제목 {'B' if len(made) == 1 else 'C'}"
        _, created = await _card(rec["session_id"], rec["user_id"], title)
        return {"storage_key": "t/x.jpg", "title": title, "text": "합성 엽서 글", "caption": "",
                "width": 1500, "height": 1000, "bytes": 1, "style": style, "created_at": created}

    real = postcard._make
    postcard._make = fake_make
    try:
        await c.get("/api/sessions", headers={"X-User-Id": A})
        await c.get(f"/api/sessions/{s5}/record", headers={"X-User-Id": A})
        check("목록 · 상세를 읽는 것으로는 굽지 않는다", made == [], str(made))
        r = await c.post(f"/api/sessions/{s5}/postcard", json={}, headers={"X-User-Id": A})
        check("다시 굽기 200 · 제목 B", r.status_code == 200 and r.json()["title"] == "제목 B", r.text[:80])
        rw = listed(await c.get("/api/sessions", headers={"X-User-Id": A}))[s5]
        check("목록이 B 를 읽는다", rw["postcard_title"] == "제목 B", str(rw["postcard_title"]))
        check("상세가 B 를 읽는다", (await detail(s5))["title"] == "제목 B")
        check("회차 title 은 그대로", rw["title"] == "2026-10-22 기록")
        fail["on"] = True
        r = await c.post(f"/api/sessions/{s5}/postcard", json={}, headers={"X-User-Id": A})
        check("실패한 다시 굽기 503", r.status_code == 503, r.text[:80])
        rw = listed(await c.get("/api/sessions", headers={"X-User-Id": A}))[s5]
        check("실패 뒤에도 목록 · 상세는 B (실패한 새 제목을 싣지 않는다)",
              rw["postcard_title"] == "제목 B" and (await detail(s5))["title"] == "제목 B",
              str(rw["postcard_title"]))
    finally:
        postcard._make = real

    # ------------------------------------------------------------ T06
    print("\n[T06] 계정 분리 · 정렬 · limit · 필터 · 실패")
    sb = await _session(con, B, "B 의 회차", at(6))
    await _card(sb, B, "B 의 엽서 제목")
    ra = (await c.get("/api/sessions?limit=100", headers={"X-User-Id": A})).json()["sessions"]
    rb = (await c.get("/api/sessions?limit=100", headers={"X-User-Id": B})).json()["sessions"]
    check("A 목록에 B 의 회차 · 제목이 없다",
          sb not in {r["session_id"] for r in ra} and all(r["postcard_title"] != "B 의 엽서 제목" for r in ra))
    check("B 목록은 B 의 것 하나", [r["session_id"] for r in rb] == [sb], str(len(rb)))
    check("B 는 A 의 상세를 못 본다 · 404", await detail(s1, B) == 404)
    check("최근 순 정렬", [r["created_at"] for r in ra] == sorted((r["created_at"] for r in ra), reverse=True))
    want = {"session_id", "user_id", "title", "photo_id", "state", "turn", "max_turn",
            "closed_reason", "created_at", "closed_at", "fragment_count", "has_postcard", "postcard_title"}
    check("기존 칸이 빠지지 않았다", want <= set(ra[0]), str(sorted(want - set(ra[0]))))
    r2 = (await c.get("/api/sessions?limit=2", headers={"X-User-Id": A})).json()["sessions"]
    check("limit=2 → 2개 · 가장 최근 둘", [r["session_id"] for r in r2] == [r["session_id"] for r in ra[:2]])
    only = (await c.get("/api/sessions?has_postcard=1&limit=100", headers={"X-User-Id": A})).json()["sessions"]
    check("has_postcard=1 은 엽서 있는 회차만 · 순서 유지",
          [r["session_id"] for r in only] == [r["session_id"] for r in ra if r["has_postcard"]])
    good = store._pool
    store._pool = _BrokenPool()
    try:
        r = await c.get("/api/sessions", headers={"X-User-Id": A})
        check("DB 를 못 읽으면 빈 목록이 아니라 503", r.status_code == 503, f"{r.status_code} {r.text[:60]}")
    finally:
        store._pool = good

    # ------------------------------------------------------------ T02
    print("\n[T02] 이미 저장된 엽서 (실제 행 · 읽기만 · 제목은 찍지 않는다)")
    olds = await con.fetch("SELECT session_id, user_id FROM postcard"
                           " WHERE user_id NOT IN ($1, $2)", A, B)
    same = seen = 0
    for o in olds:
        sid = str(o["session_id"])
        rows = (await store.list_sessions(o["user_id"], 100))
        rw = next((r for r in rows if r["session_id"] == sid), None)
        if rw is None:                                   # 그 사람의 최근 100개 밖
            continue
        seen += 1
        rec = await store.load_session(sid)
        same += rw["has_postcard"] and rw["postcard_title"] == rec["postcard"]["title"]
    check(f"기존 엽서 {len(olds)}장 중 목록에 나온 {seen}장 — 다시 굽지 않고 목록 = 상세",
          seen > 0 and same == seen, f"{same}/{seen}")


async def main():
    import httpx

    try:
        con = await _connect()
    except Exception as e:                                   # noqa: BLE001
        print(f"로컬 DB 에 붙지 못했다 — 확인 불가 ({type(e).__name__})")
        return 2
    from app.main import app
    tr = con.transaction()
    await tr.start()
    old = store._pool
    store._pool = _OnePool(con)
    try:
        with AsHeader():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="https://testserver") as c:
                await run(con, c)
    finally:
        store._pool = old
        await tr.rollback()
        await con.close()
    print("\n" + "=" * 52)
    print(f"통과 {len(PASS)} · 실패 {len(FAIL)}  (로컬 DB · 트랜잭션 되돌림 · 모델 호출 없음)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
