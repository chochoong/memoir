"""
엽서 지우기 — 회차 숨기기 (015 · DELETE /api/sessions/{id})

    python -m pytest tests/test_session_hide.py -q

DB 없이 돈다 — store.hide_session 을 메모리로 바꿔 끼운다. 신원은 X-User-Id (tests/_auth).
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

SID = "00000000-0000-4000-8000-0000000000a1"


@pytest.fixture
def env(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    rows = {SID: {"user_id": "u_me", "hidden": False}}

    async def hide(session_id, user_id):
        r = rows.get(session_id)
        if not r or r["user_id"] != user_id or r["hidden"]:
            return False
        r["hidden"] = True
        return True

    monkeypatch.setattr(store, "hide_session", hide)
    with NoDb(), AsHeader(), TestClient(app) as c:
        yield rows, c


def test_hide_own_closed_session(env):
    rows, c = env
    assert c.delete(f"/api/sessions/{SID}", headers={"X-User-Id": "u_other"}).status_code == 404
    r = c.delete(f"/api/sessions/{SID}", headers={"X-User-Id": "u_me"})
    assert r.status_code == 200 and r.json() == {"session_id": SID, "deleted": True}
    assert rows[SID]["hidden"]
    assert c.delete(f"/api/sessions/{SID}", headers={"X-User-Id": "u_me"}).status_code == 404
    assert c.delete(f"/api/sessions/{SID}").status_code == 401


def test_open_session_refused(env, monkeypatch):
    rows, c = env
    live = types.SimpleNamespace(user_id="u_me", machine=types.SimpleNamespace(state=State.SPEAKING))
    monkeypatch.setattr(sc, "get", lambda sid: live if sid == SID else None)
    r = c.delete(f"/api/sessions/{SID}", headers={"X-User-Id": "u_me"})
    assert r.status_code == 409 and r.json()["code"] == "session_open" and not rows[SID]["hidden"]
    live.machine.state = State.CLOSED
    assert c.delete(f"/api/sessions/{SID}", headers={"X-User-Id": "u_me"}).status_code == 200
