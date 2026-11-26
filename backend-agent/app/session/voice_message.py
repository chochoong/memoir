"""
가족 음성편지 — 자서전당 1개 · 최대 5분 (2026-11-26 업무지시서 「가족 음성편지 1차 구현」, 019).

흐름 (화면 · 서버 공통)
    ① 녹음 · 미리듣기는 화면 탭 안에서만. 「저장」 전에는 올리지 않는다.
    ② POST /api/voice-message-uploads — 원본 바이트 + X-Request-ID → state=uploaded · upload_id (기한 24시간)
    ③ 책이 아직 없으면(memoir_id 없음) 화면은 「책에 연결 대기」 — 저장 완료가 아니다.
    ④ PUT /api/memoirs/saved/{memoir_id}/voice-message {upload_id, request_id, expected_revision} → state=ready 가 저장 완료.
생성 작업(job_id)은 메모리에만 있어 사라질 수 있다 — 업로드는 사용자 · 요청 id 로만 남기고, 다른 책에 저절로 붙이지 않는다.

서버가 하는 검사 (process)
    - 앞머리 바이트로 형식을 가린다: webm(크롬 · 안드로이드, Opus) · mp4(사파리 · 아이폰, AAC). 그 밖은 415.
    - ffprobe 로 코덱을 보고(영상이 섞이면 415), ffmpeg 로 재생용 AAC 사본을 만든 뒤 **그 사본의 실제 길이**를 잰다.
      크롬 webm 은 머리에 길이가 없어서 원본 머리를 믿을 수 없다. 300초 + 녹음 끝 여유 2초를 넘으면 422 too_long.
    - 원본은 그대로 둔다(받아 적기 · 무음 제거 · AI 변환 없음). 사본은 아이폰 · 안드로이드 모두 재생되게 하려는 것뿐이다.
    - 유료 호출 없음.

재생
    - 책 주인: /api/memoirs/saved/{id}/voice-message/audio (로그인 쿠키, Range 206 — 아이폰 <audio> 가 요구한다)
    - 공유받은 사람: /api/b 응답의 voice_message.playback_url — 짧게 만료되는 서명 주소. 재생할 때마다 공유가 꺼졌는지 ·
      그 메시지가 아직 그 책의 것인지 다시 본다. 만료되면 /api/b 를 다시 읽으면 새 주소가 나온다. 영구 공개 주소는 없다.

정리 (sweep_forever) — 1시간마다: 기한 지난 미연결 업로드 · 버린 것 · 교체 · 삭제로 참조가 끊긴 파일의 바이트를 지운다.
연결된 파일은 지우지 않는다. 지우기에 실패하면 다음 차례에 다시 한다.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import photostore, store
from .conf import env_int, env_str

log = logging.getLogger("voice_message")

MAX_MS = 300_000            # 5분 — 사용자 확정
GRACE_MS = 2_000            # 녹음 끝 여유. 300초 상한을 늘리는 값이 아니다
MIN_MS = 500
PLAY_MIME = "audio/mp4"
KINDS = {"webm": ("audio/webm", {"opus", "vorbis"}), "mp4": ("audio/mp4", {"aac"})}
URL_SECONDS = 600           # 공유 재생 주소의 수명


def max_bytes() -> int:
    return env_int("VOICE_MAX_MB", 8) * 1024 * 1024


def upload_hours() -> int:
    return max(1, env_int("VOICE_UPLOAD_HOURS", 24))


class VoiceError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def sniff(data: bytes) -> str | None:
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[4:8] == b"ftyp":
        return "mp4"
    return None


# ---------------------------------------------------------------- ffmpeg

_slots = asyncio.Semaphore(2)       # t3.small — 동시에 두 개까지만 변환


def tools() -> tuple[str, str] | None:
    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    return (ff, fp) if ff and fp else None


async def _run(*args: str, timeout: float = 90) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise VoiceError(503, "voice_busy", "음성을 처리하는 데 너무 오래 걸렸어요. 잠시 뒤 다시 저장해 주세요") from None
    return proc.returncode, out, err


@dataclass
class Prepared:
    kind: str
    mime: str
    data: bytes
    sha256: str
    duration_ms: int
    play: bytes


async def probe_streams(path: str, ffprobe: str) -> list[dict]:
    code, out, err = await _run(ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", path)
    if code != 0:
        raise VoiceError(415, "unsupported_audio", "음성 파일을 읽지 못했어요")
    return json.loads(out or b"{}").get("streams") or []


async def probe_duration_ms(path: str, ffprobe: str) -> int:
    code, out, _ = await _run(ffprobe, "-v", "error", "-show_entries", "format=duration", "-of",
                              "default=noprint_wrappers=1:nokey=1", path)
    try:
        return int(round(float(out.decode().strip()) * 1000)) if code == 0 else -1
    except ValueError:
        return -1


async def process(data: bytes) -> Prepared:
    """받은 바이트 → 검사한 원본 + 재생용 사본. 실패는 VoiceError."""
    kind = sniff(data)
    if kind is None:
        raise VoiceError(415, "unsupported_audio", "webm 또는 mp4 음성만 저장할 수 있어요")
    mime, codecs = KINDS[kind]
    have = tools()
    if have is None:
        log.error("ffmpeg · ffprobe 가 없다 — 음성편지를 받을 수 없다 (sudo apt-get install -y ffmpeg)")
        raise VoiceError(503, "voice_unavailable", "지금은 음성편지를 저장할 수 없어요")
    ffmpeg, ffprobe = have
    async with _slots:
        with tempfile.TemporaryDirectory(prefix="voice-") as d:
            src, dst = os.path.join(d, f"in.{kind}"), os.path.join(d, "play.m4a")
            Path(src).write_bytes(data)
            streams = await probe_streams(src, ffprobe)
            if any(s.get("codec_type") == "video" for s in streams):
                raise VoiceError(415, "unsupported_audio", "영상은 저장할 수 없어요. 음성만 녹음해 주세요")
            audio = [s.get("codec_name") for s in streams if s.get("codec_type") == "audio"]
            if not audio or audio[0] not in codecs:
                raise VoiceError(415, "unsupported_audio", "지원하지 않는 음성 형식이에요")
            # -t 로 변환 시간을 묶는다 — 넘친 파일도 끝까지 변환하지 않고 「너무 길다」 는 알 수 있다
            code, _, err = await _run(ffmpeg, "-nostdin", "-v", "error", "-i", src, "-vn", "-map", "0:a:0", "-ac", "1",
                                      "-c:a", "aac", "-b:a", "96k", "-t", str((MAX_MS + GRACE_MS) / 1000 + 3),
                                      "-movflags", "+faststart", "-y", dst)
            if code != 0 or not os.path.exists(dst):
                log.warning("음성 변환 실패 — %s", err.decode(errors="replace")[:200])
                raise VoiceError(415, "unsupported_audio", "음성 파일을 읽지 못했어요")
            ms = await probe_duration_ms(dst, ffprobe)
            play = Path(dst).read_bytes()
    if ms < 0:
        raise VoiceError(415, "unsupported_audio", "음성 길이를 알 수 없어요")
    if ms > MAX_MS + GRACE_MS:
        raise VoiceError(422, "too_long", "음성편지는 5분까지 저장할 수 있어요")
    if ms < MIN_MS:
        raise VoiceError(422, "too_short", "녹음이 너무 짧아요")
    return Prepared(kind, mime, data, hashlib.sha256(data).hexdigest(), min(ms, MAX_MS), play)


def keys(upload_id: str, kind: str, when: datetime | None = None) -> tuple[str, str]:
    at = when or datetime.now(timezone.utc)
    base = f"voice/{at.year:04d}/{at.month:02d}/{upload_id}"
    return f"{base}/original.{'webm' if kind == 'webm' else 'm4a'}", f"{base}/play.m4a"


def new_upload_id() -> str:
    return "vu_" + uuid.uuid4().hex


def expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=upload_hours())


# ---------------------------------------------------------------- 화면에 내보내는 모양

def upload_view(rec: dict) -> dict:
    return {"upload_id": rec["upload_id"], "state": "uploaded" if rec["state"] == "uploaded" else rec["state"],
            "duration_ms": rec["duration_ms"], "mime": rec["mime"], "size_bytes": rec["size_bytes"],
            "expires_at": rec["expires_at"], "memoir_id": rec.get("memoir_id")}


def message_view(memoir_id: str, cur: dict) -> dict:
    up = cur.get("upload")
    if not up:
        return {"revision": cur["revision"], "message": None}
    return {"revision": cur["revision"],
            "message": {"message_id": up["upload_id"], "state": "ready", "duration_ms": up["duration_ms"],
                        "mime": up["play_mime"], "created_at": up["attached_at"] or up["created_at"],
                        "playback_url": f"/api/memoirs/saved/{memoir_id}/voice-message/audio?v={up['sha256'][:12]}"}}


# ---------------------------------------------------------------- 공유 재생 주소 (서명 · 만료)

_secret_cache: bytes | None = None


def _secret() -> bytes:
    """VOICE_URL_SECRET 이 없으면 프로세스마다 새로 — 재시작하면 앞 주소가 풀리지 않을 뿐이다 (화면이 다시 읽는다)."""
    global _secret_cache
    if _secret_cache is None:
        raw = env_str("VOICE_URL_SECRET").strip()
        _secret_cache = raw.encode() if raw else secrets.token_bytes(32)
    return _secret_cache


def _sig(share_id: str, message_id: str, exp: int) -> str:
    mac = hmac.new(_secret(), f"{share_id}|{message_id}|{exp}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:18]).decode().rstrip("=")


def share_url(share_id: str, message_id: str, now: float | None = None) -> tuple[str, int]:
    exp = int(now if now is not None else time.time()) + URL_SECONDS
    return f"/api/b/voice?s={share_id}&m={message_id}&e={exp}&k={_sig(share_id, message_id, exp)}", exp


def check_url(share_id: str, message_id: str, exp: int, sig: str, now: float | None = None) -> bool:
    if exp < int(now if now is not None else time.time()):
        return False
    return hmac.compare_digest(_sig(share_id, message_id, exp), sig or "")


def shared_view(share_id: str, cur: dict | None) -> dict | None:
    """공유받은 사람에게 — 지금 그 책의 음성편지 요약. 없으면 None."""
    up = (cur or {}).get("upload")
    if not up:
        return None
    url, exp = share_url(share_id, up["upload_id"])
    return {"message_id": up["upload_id"], "duration_ms": up["duration_ms"], "mime": up["play_mime"],
            "playback_url": url, "url_expires_at": datetime.fromtimestamp(exp, timezone.utc).isoformat()}


# ---------------------------------------------------------------- 정리

async def purge_once(limit: int = 50) -> int:
    """지울 파일의 바이트를 지운다. 지운 개수. 저장소에서 지우기에 실패한 것은 다음 차례에 다시."""
    done = 0
    for rec in await store.voice_to_purge(limit):
        try:
            for k in (rec["storage_key"], rec["play_key"]):
                try:
                    await photostore.current().delete(k)
                except photostore.PhotoMissing:
                    pass
        except Exception as e:                                   # noqa: BLE001
            log.warning("음성편지 바이트 정리 실패 %s (%s) — 다음 차례에 다시", rec["upload_id"][:11], type(e).__name__)
            continue
        if await store.mark_voice_purged(rec["upload_id"]):
            done += 1
    if done:
        log.info("음성편지 정리 — %d개", done)
    return done


async def sweep_forever(every: float = 3600, first: float = 120) -> None:
    await asyncio.sleep(first)
    while True:
        try:
            if store.enabled() and store._pool is not None:
                await purge_once()
        except Exception as e:                                   # noqa: BLE001
            log.warning("음성편지 정리 실패 (%s: %s)", type(e).__name__, str(e)[:120])
        await asyncio.sleep(every)
