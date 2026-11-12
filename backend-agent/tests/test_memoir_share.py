"""
만든 자서전 저장 (013) · 자서전 공유 링크 (014)

    python -m pytest tests/test_memoir_share.py -q

DB 없이 돈다 — store 의 자서전 · 공유 함수를 메모리로 바꿔 끼운다. 신원은 X-User-Id (tests/_auth).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.session import memoir_jobs, share, store                         # noqa: E402
from tests._auth import AsHeader                                            # noqa: E402
from tests._nodb import NoDb                                                # noqa: E402

ME, OTHER = "u_me", "u_other"
BOOK = {"title": "나의 봄날", "subtitle": "", "draft": "초안이에요", "made": "2026-11-10",
        "chapters": [{"no": 1, "title": "고향", "paras": [["첫 문장.", "둘째 문장."]]},
                     {"no": 2, "title": "서울", "paras": ["한 문단 글."], "draft": True}]}


class _Mem:
    """store 의 memoir · memoir_share 함수를 메모리로."""

    NAMES = ("enabled", "save_memoir", "list_memoirs", "load_memoir", "delete_memoir",
             "create_share", "load_share_by_token", "list_shares", "count_live_shares", "revoke_share")

    def __enter__(self):
        self.memoirs: dict[str, dict] = {}
        self.shares: dict[str, dict] = {}
        self.fail_save = False
        self._old = {n: getattr(store, n) for n in self.NAMES}
        now = lambda: datetime.now(timezone.utc)                            # noqa: E731

        async def save_memoir(rec):
            if self.fail_save:
                raise store.StoreUnavailable("x")
            self.memoirs[rec["memoir_id"]] = {**rec, "elder_id": None, "created_at": now(), "deleted_at": None}

        def view(r, full=False):
            d = {k: r[k] for k in ("memoir_id", "user_id", "elder_id", "session_ids", "style", "engine",
                                   "status", "title", "created_at")}
            if full:
                d["result"] = r["result"]
            return d

        async def list_memoirs(user_id, elder_id, limit):
            rows = [r for r in self.memoirs.values() if r["user_id"] == user_id and not r["deleted_at"]]
            return [view(r) for r in rows][:limit]

        async def load_memoir(mid, user_id):
            r = self.memoirs.get(mid)
            return view(r, True) if r and r["user_id"] == user_id and not r["deleted_at"] else None

        async def delete_memoir(mid, user_id):
            r = self.memoirs.get(mid)
            if r and r["user_id"] == user_id and not r["deleted_at"]:
                r["deleted_at"] = now()
                return True
            return False

        async def create_share(rec):
            self.shares[rec["share_id"]] = {**rec, "created_at": now(), "revoked_at": None}

        async def load_share_by_token(h):
            return next((dict(r) for r in self.shares.values() if r["token_hash"] == h), None)

        async def list_shares(user_id, limit):
            return [dict(r) for r in self.shares.values() if r["user_id"] == user_id][:limit]

        async def count_live_shares(user_id):
            return sum(1 for r in self.shares.values() if r["user_id"] == user_id and not r["revoked_at"])

        async def revoke_share(sid, user_id):
            r = self.shares.get(sid)
            if not r or r["user_id"] != user_id:
                return None
            r["revoked_at"] = r["revoked_at"] or now()
            return dict(r)

        for n, f in dict(enabled=lambda: True, save_memoir=save_memoir, list_memoirs=list_memoirs,
                         load_memoir=load_memoir, delete_memoir=delete_memoir, create_share=create_share,
                         load_share_by_token=load_share_by_token, list_shares=list_shares,
                         count_live_shares=count_live_shares, revoke_share=revoke_share).items():
            setattr(store, n, f)
        return self

    def __exit__(self, *a):
        for n, f in self._old.items():
            setattr(store, n, f)


@pytest.fixture
def env():
    from fastapi.testclient import TestClient
    from app.main import app
    with _Mem() as mem, NoDb(), AsHeader(), TestClient(app) as c:
        yield mem, c


def _me(who=ME):
    return {"X-User-Id": who}


# ---------------------------------------------------------------- 만든 자서전

def test_keep_saves_result_and_returns_id():
    with _Mem() as mem:
        res = {"status": "ready", "title": "봄날", "style": "spoken", "body": "글"}
        mid = asyncio.run(memoir_jobs.keep(res, ["00000000-0000-0000-0000-000000000001"], ME, "spoken"))
        assert mid and mid.startswith("m_")
        assert mem.memoirs[mid]["result"] == res and mem.memoirs[mid]["title"] == "봄날"


def test_keep_swallows_failure():
    with _Mem() as mem:
        mem.fail_save = True
        assert asyncio.run(memoir_jobs.keep({"status": "ready"}, [], ME, "spoken")) is None


def test_saved_routes_list_read_delete_and_isolation(env):
    mem, c = env
    mid = asyncio.run(memoir_jobs.keep({"status": "ready", "title": "봄날"}, [], ME, "spoken"))
    got = c.get("/api/memoirs/saved", headers=_me()).json()["memoirs"]
    assert [m["memoir_id"] for m in got] == [mid] and "result" not in got[0] and "user_id" not in got[0]
    assert c.get("/api/memoirs/saved", headers=_me(OTHER)).json()["memoirs"] == []
    one = c.get(f"/api/memoirs/saved/{mid}", headers=_me())
    assert one.status_code == 200 and one.json()["result"]["title"] == "봄날"
    assert c.get(f"/api/memoirs/saved/{mid}", headers=_me(OTHER)).status_code == 404
    assert c.delete(f"/api/memoirs/saved/{mid}", headers=_me(OTHER)).status_code == 404
    assert c.delete(f"/api/memoirs/saved/{mid}", headers=_me()).status_code == 200
    assert c.get(f"/api/memoirs/saved/{mid}", headers=_me()).status_code == 404
    assert c.get("/api/memoirs/saved").status_code == 401


def test_saved_route_is_not_read_as_job_id(env):
    _, c = env
    r = c.get("/api/memoirs/saved", headers=_me())
    assert r.status_code == 200 and "memoirs" in r.json()


# ---------------------------------------------------------------- 공유

def test_share_issue_read_revoke(env):
    mem, c = env
    r = c.post("/api/shares", json={"book_id": "b1", "book": BOOK}, headers=_me())
    assert r.status_code == 201, r.text
    out = r.json()
    tok = out["token"]
    assert out["url"].endswith(f"/b#{tok}") and out["chapters"] == 2
    row = mem.shares[out["share_id"]]
    assert tok not in str(row) and row["token_hash"] != tok                 # 표에는 해시만

    got = c.get("/api/b", headers={share.HEADER: tok})
    assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
    book = got.json()["book"]
    assert book["title"] == "나의 봄날"
    assert book["chapters"][1]["paras"] == [["한 문단 글."]] and book["chapters"][1]["draft"] is True

    lst = c.get("/api/shares", headers=_me()).json()["shares"]
    assert len(lst) == 1 and "token" not in lst[0] and lst[0]["live"] is True

    assert c.post(f"/api/shares/{out['share_id']}/revoke", headers=_me(OTHER)).status_code == 404
    rv = c.post(f"/api/shares/{out['share_id']}/revoke", headers=_me())
    assert rv.status_code == 200 and rv.json()["live"] is False
    gone = c.get("/api/b", headers={share.HEADER: tok})
    assert gone.status_code == 410 and "book" not in gone.json()


def test_share_reader_needs_no_login_and_rejects_unknown(env):
    _, c = env
    assert c.get("/api/b").status_code == 404
    assert c.get("/api/b", headers={share.HEADER: "nope"}).status_code == 404
    assert c.post("/api/shares", json={"book": BOOK}).status_code == 401


@pytest.mark.parametrize("book", [
    None, {}, {"title": "", "chapters": [{"title": "a", "paras": []}]},
    {"title": "t", "chapters": []},
    {"title": "t", "chapters": [{"title": "a", "paras": [[1, 2]]}]},
    {"title": "t" * 500, "chapters": [{"title": "a", "paras": []}]},
])
def test_share_rejects_bad_books(env, book):
    _, c = env
    r = c.post("/api/shares", json={"book": book}, headers=_me())
    assert r.status_code == 400 and r.json()["code"] == "bad_book"


def test_share_cap(env, monkeypatch):
    _, c = env
    monkeypatch.setenv("SHARE_MAX_LIVE", "2")
    for _ in range(2):
        assert c.post("/api/shares", json={"book": BOOK}, headers=_me()).status_code == 201
    r = c.post("/api/shares", json={"book": BOOK}, headers=_me())
    assert r.status_code == 409 and r.json()["code"] == "too_many_shares"


def test_share_page_served(env):
    _, c = env
    r = c.get("/b")
    assert r.status_code == 200 and "X-Share-Token" in r.text and "noindex" in r.headers.get("x-robots-tag", "")
