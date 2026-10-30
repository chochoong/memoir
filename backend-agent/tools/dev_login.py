"""
시험 도구가 쓸 로그인 쿠키를 만든다 — 구글 없이 (3-C1 · P3-SV-02 뒤의 도구들)

    python tools/dev_login.py                   계정 「replay」의 msid 를 찍는다
    python tools/dev_login.py --alias a --alias b   계정 둘 (서로의 것이 404 인지 볼 때)

    curl -b "msid=<찍힌 값>" http://127.0.0.1:8010/api/auth/me

서버는 X-User-Id 를 더 이상 읽지 않는다. 도구도 브라우저처럼 msid 쿠키로 들어가야
한다. 구글 로그인을 거칠 수 없으니 **로그인이 남기는 두 줄을 DB 에 직접 쓴다** —
auth.login 이 쓰는 것과 같은 app_user · login_session 이다. 서버 쪽에는 아무것도
더하지 않는다 (auth.py 머리: 개발용으로 되살리는 스위치를 두지 않는다).

그래서 이 도구는 **DB 에 쓸 수 있는 사람만** 쓸 수 있다. 그 사람은 이미 모든 행을
고칠 수 있으니 새로 열리는 문이 아니다. 화면이나 링크로는 이 길에 닿지 않는다.

**구글 계정과 섞이지 않는다.** provider 가 'dev' 라 (provider, subject) 가 구글
계정과 겹칠 수 없다. 같은 alias 로 다시 돌리면 같은 계정에 새 쿠키만 준다.
쿠키 수명은 HOURS 로 짧게 둔다. 시험이 끝나면 저절로 죽는다.

이 PC 의 DB 가 아니면 --allow-remote 없이는 쓰지 않는다 (seed_sessions 와 같다).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROVIDER = "dev"
LABEL = "tools/dev_login"
HOURS = 12
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def dsn() -> dict:
    """서버와 같은 순서로 .env 를 읽는다 (main.py 머리). 값은 찍지 않는다."""
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    if os.environ.get("MEMOIR_DB") == "supabase":
        load_dotenv(ROOT / ".env.supabase", override=True)

    from app.session import store

    return store._dsn()


def target(d: dict) -> str:
    return f"{d['host']}:{d['port']}/{d['database']}"


async def _mint(d: dict, aliases: list[str]) -> list[tuple[str, str, str]]:
    import asyncpg

    con = await asyncpg.connect(**d)
    try:
        out = []
        for alias in aliases:
            user_id = await con.fetchval(
                """
                INSERT INTO app_user (user_id, provider, subject, name, last_login)
                VALUES ($1, $2, $3, $4, now())
                ON CONFLICT (provider, subject) DO UPDATE SET last_login = now()
                RETURNING user_id
                """,
                f"u_{uuid.uuid4().hex}", PROVIDER, alias, f"시험 {alias}")
            raw = secrets.token_urlsafe(32)
            await con.execute(
                """
                INSERT INTO login_session (sid, user_id, kind, label, expires_at, last_seen_at)
                VALUES ($1, $2, 'web', $3, $4, now())
                """,
                hashlib.sha256(raw.encode()).hexdigest(), user_id, LABEL,
                datetime.now(timezone.utc) + timedelta(hours=HOURS))
            out.append((alias, user_id, raw))
        return out
    finally:
        await con.close()


def mint(aliases: list[str], allow_remote: bool = False) -> list[tuple[str, str, str]]:
    """alias 마다 (alias, user_id, msid 원문). 원문은 표에 없다 — 여기서 한 번만 나간다."""
    d = dsn()
    if d["host"] not in LOCAL_HOSTS and not allow_remote:
        raise SystemExit(f"DB {target(d)} 는 이 PC 의 DB 가 아니다. "
                         "맞는 DB 인지 확인하고 --allow-remote 를 붙여 다시 돌린다.")
    return asyncio.run(_mint(d, aliases))


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="시험 도구용 로그인 쿠키 (구글 없이)")
    ap.add_argument("--alias", action="append", help="계정 이름. 여러 번 줄 수 있다 (기본 replay)")
    ap.add_argument("--allow-remote", action="store_true", help="이 PC 가 아닌 DB 에도 쓴다")
    a = ap.parse_args()

    print(f"DB {target(dsn())} · 쿠키 수명 {HOURS}시간", file=sys.stderr)
    for alias, user_id, raw in mint(a.alias or ["replay"], a.allow_remote):
        print(f"{alias}\t{user_id}\tmsid={raw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
