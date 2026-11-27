"""
가족 음성편지 (2026-11-26 업무지시서 「가족 음성편지 1차 구현」, 019)

    python -m pytest tests/test_voice_message.py -q

DB · ffmpeg 없이 돈다 — store 의 음성편지 함수를 메모리로(SQL 과 같은 규칙), 저장소를 임시 폴더로 바꾼다.
ffmpeg 검사(process)는 따로 가짜 ffmpeg 로 시험한다. 실제 SQL 트랜잭션은 tests/test_voice_message_db.py (임시 DB).
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.session import photostore, share, store, voice_message as vm
from tests._auth import AsHeader
from tests._nodb import NoDb

ME, OTHER = "u_me", "u_other"
MID, MID2 = "m_" + "a" * 32, "m_" + "c" * 32
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 60
MP4 = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 60


def now():
    return datetime.now(timezone.utc)


class Db:
    """store 의 음성편지 · 공유 함수를 메모리로 — store.py 의 SQL 과 같은 규칙."""

    def __init__(self, monkeypatch, tmp_path):
        self.memoirs = {MID: ME, MID2: ME}
        self.uploads: dict[str, dict] = {}
        self.voice: dict[str, dict] = {}
        self.shares: dict[str, dict] = {}
        db = self

        async def load_memoir(mid, uid):
            if db.memoirs.get(mid) != uid:
                return None
            return {"memoir_id": mid, "user_id": uid, "title": "t", "result": {"chapters": []}, "illustrations": None}

        async def save_voice_upload(rec):
            for u in db.uploads.values():
                if (u["user_id"], u["request_id"]) == (rec["user_id"], rec["request_id"]):
                    return copy.deepcopy(u)
            row = {**rec, "state": "uploaded", "memoir_id": None, "created_at": now(), "attached_at": None, "released_at": None}
            db.uploads[rec["upload_id"]] = row
            return copy.deepcopy(row)

        async def find_voice_upload(uid, rid):
            return next((copy.deepcopy(u) for u in db.uploads.values() if (u["user_id"], u["request_id"]) == (uid, rid)), None)

        async def discard_voice_upload(upid, uid):
            u = db.uploads.get(upid)
            if u is None or u["user_id"] != uid:
                return "not_found"
            if u["state"] == "attached":
                return "attached"
            if u["state"] != "uploaded":
                return "gone"
            u["state"] = "discarded"
            return "ok"

        async def load_memoir_voice(mid, uid):
            v = db.voice.get(mid)
            if v is None or v["user_id"] != uid:
                return {"revision": 0, "last_request_id": None, "upload": None}
            return {"revision": v["revision"], "last_request_id": v["last_request_id"],
                    "upload": copy.deepcopy(db.uploads[v["upload_id"]]) if v["upload_id"] else None}

        async def attach_voice(mid, uid, upid, rid, rev):
            if db.memoirs.get(mid) != uid:
                return "memoir_not_found", None
            v = db.voice.setdefault(mid, {"user_id": uid, "revision": 0, "upload_id": None, "last_request_id": None})
            if v["upload_id"] == upid and (v["last_request_id"] == rid or v["revision"] == rev + 1):
                return "same", None
            if v["revision"] != rev:
                return "conflict", v["revision"]
            u = db.uploads.get(upid)
            if u is None or u["user_id"] != uid:
                return "upload_not_found", None
            if u["state"] == "attached":
                return "upload_in_use", None
            if u["state"] != "uploaded" or u["expires_at"] < now():
                return "upload_expired", None
            u.update(state="attached", memoir_id=mid, attached_at=now())
            if v["upload_id"]:
                db.uploads[v["upload_id"]]["state"] = "released"
            v.update(upload_id=upid, revision=v["revision"] + 1, last_request_id=rid)
            return "ok", None

        async def detach_voice(mid, uid, rev):
            v = db.voice.get(mid)
            if v is None or v["user_id"] != uid:
                return ("no_message" if db.memoirs.get(mid) == uid else "memoir_not_found"), None
            if v["revision"] != rev:
                return "conflict", v["revision"]
            if not v["upload_id"]:
                return "no_message", None
            db.uploads[v["upload_id"]]["state"] = "released"
            v.update(upload_id=None, revision=v["revision"] + 1, last_request_id=None)
            return "ok", None

        async def voice_to_purge(limit=50):
            return [copy.deepcopy(u) for u in db.uploads.values()
                    if (u["state"] == "uploaded" and u["expires_at"] < now()) or u["state"] in ("released", "discarded")]

        async def mark_voice_purged(upid):
            db.uploads[upid]["state"] = "purged"
            return True

        # 공유 (014 + 019 source_memoir_id)
        async def count_live_shares(uid):
            return sum(1 for s in db.shares.values() if s["user_id"] == uid and s["revoked_at"] is None)

        async def create_share(rec):
            db.shares[rec["share_id"]] = {**rec, "created_at": now(), "revoked_at": None, "source_memoir_id": None}

        async def set_share_source(sid, uid, mid):
            s = db.shares.get(sid)
            if s and s["user_id"] == uid and db.memoirs.get(mid) == uid:
                s["source_memoir_id"] = mid

        async def load_share_by_token(h):
            return next((copy.deepcopy(s) for s in db.shares.values() if s["token_hash"] == h), None)

        async def load_share_by_id(sid):
            return copy.deepcopy(db.shares.get(sid))

        for n, f in dict(load_memoir=load_memoir, save_voice_upload=save_voice_upload, find_voice_upload=find_voice_upload,
                         discard_voice_upload=discard_voice_upload, load_memoir_voice=load_memoir_voice,
                         attach_voice=attach_voice, detach_voice=detach_voice, voice_to_purge=voice_to_purge,
                         mark_voice_purged=mark_voice_purged, count_live_shares=count_live_shares, create_share=create_share,
                         set_share_source=set_share_source, load_share_by_token=load_share_by_token,
                         load_share_by_id=load_share_by_id).items():
            monkeypatch.setattr(store, n, f)
        monkeypatch.setattr(photostore, "_store", photostore.LocalStore(tmp_path / "blobs"))

        async def fake_process(data):
            """가짜 ffmpeg — 앞머리는 진짜로 보고, 길이는 본문 끝의 'ms=…' 로 정한다."""
            kind = vm.sniff(data)
            if kind is None:
                raise vm.VoiceError(415, "unsupported_audio", "x")
            ms = int(data.rsplit(b"ms=", 1)[1]) if b"ms=" in data else 12_000
            if ms > vm.MAX_MS + vm.GRACE_MS:
                raise vm.VoiceError(422, "too_long", "x")
            return vm.Prepared(kind, vm.KINDS[kind][0], data, hashlib.sha256(data).hexdigest(), min(ms, vm.MAX_MS),
                               b"PLAY:" + hashlib.sha256(data).hexdigest().encode() * 4)
        monkeypatch.setattr(vm, "process", fake_process)


@pytest.fixture
def env(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    db = Db(monkeypatch, tmp_path)
    with NoDb(), AsHeader(), TestClient(app) as c:
        yield db, c


def H(who=ME, **more):
    return {"X-User-Id": who, **more}


def upload(c, rid, body=None, who=ME):
    return c.post("/api/voice-message-uploads", content=body if body is not None else WEBM + rid.encode(),
                  headers=H(who, **{"X-Request-ID": rid, "Content-Type": "audio/webm"}))


def put(c, upid, rid, rev, mid=MID, who=ME):
    return c.put(f"/api/memoirs/saved/{mid}/voice-message", json={"upload_id": upid, "request_id": rid,
                                                                   "expected_revision": rev}, headers=H(who))


def get(c, mid=MID, who=ME):
    return c.get(f"/api/memoirs/saved/{mid}/voice-message", headers=H(who))


# ---------------------------------------------------------------- 업로드

def test_upload_is_temporary_and_retry_with_the_same_request_id_returns_the_same_file(env):
    db, c = env
    r = upload(c, "rec-1")
    assert r.status_code == 201
    u = r.json()
    assert u["state"] == "uploaded" and u["upload_id"].startswith("vu_") and u["mime"] == "audio/webm"
    assert u["duration_ms"] == 12_000 and u["expires_at"]
    again = upload(c, "rec-1")                                          # 응답을 잃고 다시 보냈다
    assert again.status_code == 200 and again.json()["upload_id"] == u["upload_id"] and len(db.uploads) == 1
    assert get(c).json() == {"revision": 0, "message": None}           # 올리기만으로는 책에 아무것도 없다
    assert c.post("/api/voice-message-uploads", content=WEBM, headers=H()).json()["code"] == "request_id_required"


def test_upload_checks_format_length_and_size(env, monkeypatch):
    db, c = env
    assert upload(c, "a", b"RIFF....WAVEfmt ").json()["code"] == "unsupported_audio"
    assert upload(c, "b", b"\x89PNG\r\n\x1a\n").status_code == 415
    assert upload(c, "c", WEBM + b"ms=302001").json()["code"] == "too_long"
    assert upload(c, "d", MP4 + b"ms=302000").status_code == 201                 # 녹음 끝 여유 2초까지
    assert upload(c, "d2", MP4 + b"ms=302000").json()["duration_ms"] == vm.MAX_MS  # 길이는 300초로 적는다
    monkeypatch.setenv("VOICE_MAX_MB", "1")
    assert upload(c, "e", WEBM + b"\x00" * (1024 * 1024 + 10)).status_code == 413
    assert len(db.uploads) == 2


# ---------------------------------------------------------------- 연결 · 재시도 · 교체 · 경합

def test_attach_then_play_with_range(env):
    db, c = env
    up = upload(c, "rec-1").json()["upload_id"]
    r = put(c, up, "link-1", 0)
    assert r.status_code == 200
    msg = r.json()
    assert msg["revision"] == 1 and msg["message"]["state"] == "ready" and msg["message"]["message_id"] == up
    assert get(c).json() == msg
    url = msg["message"]["playback_url"]
    full = c.get(url, headers=H())
    assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes" and full.headers["content-type"] == "audio/mp4"
    part = c.get(url, headers=H(Range="bytes=0-9"))
    assert part.status_code == 206 and part.content == full.content[:10]
    assert part.headers["content-range"] == f"bytes 0-9/{len(full.content)}"
    assert c.get(url, headers=H(Range="bytes=-4")).content == full.content[-4:]
    assert c.get(url, headers=H(Range=f"bytes={len(full.content)}-")).status_code == 416
    assert c.get(url, headers=H(OTHER)).status_code == 404                        # 남의 책


def test_lost_link_response_retry_does_not_make_a_second_message(env):
    db, c = env
    up = upload(c, "rec-1").json()["upload_id"]
    first = put(c, up, "link-1", 0).json()
    assert put(c, up, "link-1", 0).json() == first                                 # 같은 요청 id 로 다시
    assert put(c, up, "link-2", 0).json() == first                                 # 요청 id 를 잃었어도 같은 파일 · 같은 결과
    assert first["revision"] == 1


def test_replace_keeps_the_old_message_until_the_new_one_is_attached(env):
    db, c = env
    old = upload(c, "rec-1").json()["upload_id"]
    put(c, old, "link-1", 0)
    new = upload(c, "rec-2").json()["upload_id"]                                   # 재녹음 · 업로드 중
    assert get(c).json()["message"]["message_id"] == old                          # 아직 예전 메시지가 재생된다
    r = put(c, new, "link-2", 1).json()
    assert r["revision"] == 2 and r["message"]["message_id"] == new
    assert db.uploads[old]["state"] == "released" and db.uploads[new]["state"] == "attached"
    assert sum(1 for u in db.uploads.values() if u["state"] == "attached") == 1    # 활성 메시지는 하나


def test_stale_screen_gets_revision_conflict(env):
    db, c = env
    a = upload(c, "rec-1").json()["upload_id"]
    put(c, a, "link-1", 0)
    b = upload(c, "rec-2").json()["upload_id"]
    r = put(c, b, "link-2", 0)                                                     # 오래된 화면 (revision 0)
    assert r.status_code == 409 and r.json() == {"detail": r.json()["detail"], "code": "revision_conflict", "revision": 1}
    assert get(c).json()["message"]["message_id"] == a


def test_late_save_cannot_undo_a_delete(env):
    db, c = env
    a = upload(c, "rec-1").json()["upload_id"]
    put(c, a, "link-1", 0)
    b = upload(c, "rec-2").json()["upload_id"]
    assert c.delete(f"/api/memoirs/saved/{MID}/voice-message?expected_revision=0", headers=H()).status_code == 409
    assert c.delete(f"/api/memoirs/saved/{MID}/voice-message?expected_revision=1", headers=H()).status_code == 204
    assert get(c).json() == {"revision": 2, "message": None}
    assert put(c, b, "link-2", 1).status_code == 409                               # 삭제 전에 출발한 늦은 저장
    assert put(c, a, "link-1", 0).status_code == 409                               # 예전 연결 요청의 재시도
    assert get(c).json()["message"] is None
    assert c.delete(f"/api/memoirs/saved/{MID}/voice-message?expected_revision=2", headers=H()).json()["code"] == \
        "message_not_found"


def test_expired_discarded_and_used_uploads(env):
    db, c = env
    a = upload(c, "rec-1").json()["upload_id"]
    db.uploads[a]["expires_at"] = now() - timedelta(minutes=1)
    assert put(c, a, "link-1", 0).json()["code"] == "upload_expired"
    b = upload(c, "rec-2").json()["upload_id"]
    assert c.delete(f"/api/voice-message-uploads/{b}", headers=H()).status_code == 204
    assert put(c, b, "link-2", 0).status_code == 410                               # 버린 것
    assert upload(c, "rec-2").status_code == 410                                   # 버린 요청 id 로 다시 올리면 새 id 로
    d = upload(c, "rec-3").json()["upload_id"]
    assert put(c, d, "link-3", 0, mid=MID).status_code == 200
    assert put(c, d, "link-4", 0, mid=MID2).json()["code"] == "upload_in_use"      # 다른 책에 자동으로 붙지 않는다
    assert c.delete(f"/api/voice-message-uploads/{d}", headers=H()).json()["code"] == "upload_attached"


def test_other_users_cannot_touch_my_book_or_my_upload(env):
    db, c = env
    a = upload(c, "rec-1").json()["upload_id"]
    assert get(c, who=OTHER).status_code == 404
    assert put(c, a, "x", 0, who=OTHER).status_code == 404
    assert c.delete(f"/api/memoirs/saved/{MID}/voice-message?expected_revision=0", headers=H(OTHER)).status_code == 404
    assert c.delete(f"/api/voice-message-uploads/{a}", headers=H(OTHER)).status_code == 404
    db.memoirs["m_other"] = OTHER
    r = c.put("/api/memoirs/saved/m_other/voice-message", json={"upload_id": a, "request_id": "x", "expected_revision": 0},
              headers=H(OTHER))
    assert r.json()["code"] == "upload_not_found"                                  # 남의 업로드는 없는 것
    assert c.get(f"/api/memoirs/saved/{MID}/voice-message").status_code == 401
    assert put(c, a, "", 0).json()["code"] == "request_id_required"
    assert put(c, a, "x", "0").json()["code"] == "bad_revision"


# ---------------------------------------------------------------- 공유받은 사람

def _share(c, book_id=MID):
    r = c.post("/api/shares", json={"book_id": book_id, "book": {"title": "책", "chapters": [{"title": "1장", "paras": [["글"]]}]}},
               headers=H())
    assert r.status_code == 201, r.text
    return r.json()


def test_shared_link_plays_the_current_message_without_login_and_stops_when_revoked(env):
    db, c = env
    a = upload(c, "rec-1").json()["upload_id"]
    put(c, a, "link-1", 0)
    sh = _share(c)
    b = c.get("/api/b", headers={"X-Share-Token": sh["token"]}).json()
    vmsg = b["voice_message"]
    assert vmsg["message_id"] == a and vmsg["playback_url"].startswith("/api/b/voice?")
    assert c.get(vmsg["playback_url"]).status_code == 200                          # 로그인 없이
    assert c.get(vmsg["playback_url"], headers={"Range": "bytes=0-3"}).status_code == 206
    bad = vmsg["playback_url"][:-3] + "AAA"
    assert c.get(bad).json()["code"] == "url_expired"                              # 서명을 고치면
    # 교체 — 예전 주소는 끊기고, 다시 읽으면 새 메시지
    n = upload(c, "rec-2").json()["upload_id"]
    put(c, n, "link-2", 1)
    assert c.get(vmsg["playback_url"]).json()["code"] == "message_gone"
    assert c.get("/api/b", headers={"X-Share-Token": sh["token"]}).json()["voice_message"]["message_id"] == n
    # 공유를 끄면 새 재생 요청은 막힌다
    url = c.get("/api/b", headers={"X-Share-Token": sh["token"]}).json()["voice_message"]["playback_url"]
    db.shares[sh["share_id"]]["revoked_at"] = now()
    assert c.get(url).json()["code"] == "share_revoked"


def test_shared_link_without_source_and_after_delete_has_no_voice(env):
    db, c = env
    sh = _share(c, book_id="local-123")                                            # 기기에만 있던 책 — 글만 공유
    assert db.shares[sh["share_id"]]["source_memoir_id"] is None
    assert c.get("/api/b", headers={"X-Share-Token": sh["token"]}).json()["voice_message"] is None
    sh2 = _share(c)
    assert c.get("/api/b", headers={"X-Share-Token": sh2["token"]}).json()["voice_message"] is None   # 메시지 없음


def test_signed_url_expires():
    url, exp = vm.share_url("s_1", "vu_1", now=1000)
    q = dict(x.split("=", 1) for x in url.split("?", 1)[1].split("&"))
    assert vm.check_url("s_1", "vu_1", int(q["e"]), q["k"], now=1000 + vm.URL_SECONDS - 1)
    assert not vm.check_url("s_1", "vu_1", int(q["e"]), q["k"], now=1000 + vm.URL_SECONDS + 1)
    assert not vm.check_url("s_1", "vu_2", int(q["e"]), q["k"], now=1000)


# ---------------------------------------------------------------- 정리

def test_purge_removes_unlinked_bytes_and_keeps_attached_files(env):
    db, c = env
    keep = upload(c, "rec-1").json()["upload_id"]
    put(c, keep, "link-1", 0)
    old = upload(c, "rec-2").json()["upload_id"]
    exp = upload(c, "rec-3").json()["upload_id"]
    db.uploads[exp]["expires_at"] = now() - timedelta(hours=1)
    fresh = upload(c, "rec-4").json()["upload_id"]
    put(c, old, "link-2", 1)                                                       # keep → released
    assert asyncio.run(vm.purge_once()) == 2
    assert {k: u["state"] for k, u in db.uploads.items()} == {keep: "purged", old: "attached", exp: "purged",
                                                              fresh: "uploaded"}
    ps = photostore.current()
    with pytest.raises(photostore.PhotoMissing):
        asyncio.run(ps.get(db.uploads[keep]["play_key"]))
    assert asyncio.run(ps.get(db.uploads[old]["play_key"]))                        # 연결된 파일은 남는다
    assert c.get(get(c).json()["message"]["playback_url"], headers=H()).status_code == 200


# ---------------------------------------------------------------- process — 가짜 ffmpeg

def _fake_ffmpeg(monkeypatch, codec="opus", seconds=12.0, video=False, convert_ok=True):
    calls = []

    async def run(*args, timeout=90):
        calls.append(args[0])
        if args[0] == "ffprobe" and "stream=codec_type,codec_name" in args:
            streams = [{"codec_type": "audio", "codec_name": codec}] + ([{"codec_type": "video", "codec_name": "vp8"}] if video else [])
            return 0, json.dumps({"streams": streams}).encode(), b""
        if args[0] == "ffmpeg":
            if convert_ok:
                with open(args[-1], "wb") as f:
                    f.write(b"M4A-PLAY")
            return (0 if convert_ok else 1), b"", b"bad"
        return 0, f"{seconds}\n".encode(), b""
    monkeypatch.setattr(vm, "tools", lambda: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr(vm, "_run", run)
    return calls


def test_process_measures_the_converted_copy(monkeypatch):
    _fake_ffmpeg(monkeypatch, seconds=299.4)
    p = asyncio.run(vm.process(WEBM))
    assert (p.kind, p.mime, p.duration_ms, p.play, p.data) == ("webm", "audio/webm", 299_400, b"M4A-PLAY", WEBM)


@pytest.mark.parametrize("kw, data, code", [
    (dict(seconds=302.1), WEBM, "too_long"),
    (dict(seconds=0.2), WEBM, "too_short"),
    (dict(codec="aac"), WEBM, "unsupported_audio"),            # webm 에 AAC — 브라우저가 만들지 않는 조합
    (dict(codec="opus"), MP4, "unsupported_audio"),
    (dict(video=True), WEBM, "unsupported_audio"),             # 영상은 범위 밖
    (dict(convert_ok=False), WEBM, "unsupported_audio"),
])
def test_process_rejects(monkeypatch, kw, data, code):
    _fake_ffmpeg(monkeypatch, **kw)
    with pytest.raises(vm.VoiceError) as e:
        asyncio.run(vm.process(data))
    assert e.value.code == code


def test_process_without_ffmpeg_is_503(monkeypatch):
    monkeypatch.setattr(vm, "tools", lambda: None)
    with pytest.raises(vm.VoiceError) as e:
        asyncio.run(vm.process(WEBM))
    assert (e.value.status, e.value.code) == (503, "voice_unavailable")
