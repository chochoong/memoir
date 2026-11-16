"""
화자 이름 바꾸기 · 지우기 — PATCH · DELETE /api/elders/{elder_id}

    python -m pytest tests/test_elder_edit.py -q

DB 없이 돈다 — store.rename_elder · unlink_elder 를 메모리로 바꿔 끼운다. 신원은 X-User-Id (tests/_auth).
기록 세기의 SQL 자체(숨긴 회차 · 지운 자서전 · 쓸 수 없는 링크는 세지 않는다)는 store.unlink_elder 에 있다.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.session import controller as sc, store                          # noqa: E402
from app.session.machine import State                                    # noqa: E402
from tests._auth import AsHeader                                          # noqa: E402
from tests._nodb import NoDb                                              # noqa: E402

ME = {"X-User-Id": "u_me"}


@pytest.fixture
def env(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    db = {
        "names": {"e_1": "어머니", "e_2": "아버지", "e_x": "남의 화자"},
        "links": {("u_me", "e_1"), ("u_me", "e_2"), ("u_other", "e_x")},
        "records": {},          # (user, elder) -> {"sessions": n, ...}
        "live_seen": [],
    }

    async def rename(user_id, elder_id, name):
        if (user_id, elder_id) not in db["links"]:
            return False
        db["names"][elder_id] = name
        return True

    async def unlink(user_id, elder_id, live=0):
        db["live_seen"].append(live)
        if (user_id, elder_id) not in db["links"]:
            return None
        rec = {"sessions": 0, "memoirs": 0, "links": 0, **db["records"].get((user_id, elder_id), {})}
        rec["sessions"] = max(rec["sessions"], live)
        if any(rec.values()):
            return {"deleted": False, "records": rec}
        db["links"].discard((user_id, elder_id))
        return {"deleted": True, "records": rec}

    monkeypatch.setattr(store, "rename_elder", rename)
    monkeypatch.setattr(store, "unlink_elder", unlink)
    monkeypatch.setattr(sc, "live_sessions", lambda: [])
    with NoDb(), AsHeader(), TestClient(app) as c:
        yield db, c


def test_rename(env):
    db, c = env
    r = c.patch("/api/elders/e_1", json={"name": "  말랑이 "}, headers=ME)
    assert r.status_code == 200 and r.json() == {"elder_id": "e_1", "name": "말랑이"}
    assert db["names"]["e_1"] == "말랑이"


def test_rename_bad_name(env):
    db, c = env
    assert c.patch("/api/elders/e_1", json={"name": "   "}, headers=ME).status_code == 422
    assert c.patch("/api/elders/e_1", json={}, headers=ME).status_code == 422
    assert c.patch("/api/elders/e_1", json={"name": "가" * 41}, headers=ME).status_code == 422
    assert db["names"]["e_1"] == "어머니"


def test_rename_not_mine(env):
    db, c = env
    for eid in ("e_x", "e_none"):
        r = c.patch(f"/api/elders/{eid}", json={"name": "바꿈"}, headers=ME)
        assert r.status_code == 404 and r.json()["code"] == "elder_not_found"
    assert db["names"]["e_x"] == "남의 화자"


def test_delete_without_records(env):
    db, c = env
    r = c.delete("/api/elders/e_2", headers=ME)
    assert r.status_code == 200 and r.json() == {"elder_id": "e_2", "deleted": True}
    assert ("u_me", "e_2") not in db["links"]
    r = c.delete("/api/elders/e_2", headers=ME)
    assert r.status_code == 404 and r.json()["code"] == "elder_not_found"


def test_delete_with_records_refused(env):
    db, c = env
    db["records"][("u_me", "e_1")] = {"sessions": 3, "memoirs": 1}
    r = c.delete("/api/elders/e_1", headers=ME)
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "has_records" and body["records"] == {"sessions": 3, "memoirs": 1, "links": 0}
    assert ("u_me", "e_1") in db["links"]


def test_delete_refused_while_interview_live(env, monkeypatch):
    """DB 에 회차가 안 적혔어도 메모리에 진행 중인 회차가 있으면 지우지 않는다."""
    db, c = env

    def live(user_id, elder_id, state=State.LISTENING):
        return types.SimpleNamespace(user_id=user_id, elder_id=elder_id,
                                     machine=types.SimpleNamespace(state=state))
    monkeypatch.setattr(sc, "live_sessions", lambda: [
        live("u_me", "e_2"), live("u_other", "e_2"), live("u_me", "e_1")])
    r = c.delete("/api/elders/e_2", headers=ME)
    assert r.status_code == 409 and r.json()["records"]["sessions"] == 1
    assert db["live_seen"][-1] == 1 and ("u_me", "e_2") in db["links"]


def test_delete_not_mine(env):
    db, c = env
    r = c.delete("/api/elders/e_x", headers=ME)
    assert r.status_code == 404 and r.json()["code"] == "elder_not_found"
    assert ("u_other", "e_x") in db["links"]


def test_login_and_origin(env):
    db, c = env
    assert c.patch("/api/elders/e_1", json={"name": "x"}).status_code == 401
    assert c.delete("/api/elders/e_1").status_code == 401
    evil = {**ME, "Origin": "https://evil.example"}
    r = c.patch("/api/elders/e_1", json={"name": "x"}, headers=evil)
    assert r.status_code == 403 and r.json()["code"] == "bad_origin"
    r = c.delete("/api/elders/e_1", headers=evil)
    assert r.status_code == 403 and r.json()["code"] == "bad_origin"
    assert db["names"]["e_1"] == "어머니" and ("u_me", "e_1") in db["links"]


def test_store_unavailable_is_503(env, monkeypatch):
    db, c = env

    async def down(*a, **k):
        raise store.StoreUnavailable("화자 지우기에 실패했습니다")
    monkeypatch.setattr(store, "unlink_elder", down)
    monkeypatch.setattr(store, "rename_elder", down)
    assert c.delete("/api/elders/e_1", headers=ME).status_code == 503
    assert c.patch("/api/elders/e_1", json={"name": "x"}, headers=ME).status_code == 503
