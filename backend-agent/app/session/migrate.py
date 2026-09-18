"""
스키마 마이그레이션 — 「DROP 후 다시 만든다」를 졸업하는 자리

예전에는 app/schema.sql 한 장이었고, 바꿀 때는 파일을 고치고 DROP 후 다시 만들었다.
4주 프로젝트에는 그게 정말 가장 쌌다. 그런데 **실사용자가 한 명이라도 들어오면
DROP 이 불가능해진다.** 그 뒤 첫 스키마 변경을 운영 DB 에서 손으로 SQL 을 쳐서
하게 되고, 그게 사고가 나는 자리다.

그래서 번호 붙인 파일 + 적용 기록 표로 바꾼다. 도구를 새로 들이지 않은 이유는
필요한 게 이 백 줄이 전부여서다 — Alembic 은 모델에서 스키마를 유추하는 도구인데
여기에는 ORM 이 없다. 우리가 원하는 것은 「순서대로, 한 번만, 고쳐지지 않은 채로」다.

    app/migrations/001_init.sql      이미 적용됨. 고치지 않는다
    app/migrations/002_photo.sql     사진의 소유자와 바이트
    …                                앞으로의 변경은 새 번호를 더한다

지키는 것 넷.

    한 번만       schema_migration 에 기록하고, 기록된 것은 다시 걸지 않는다
    순서대로      번호순. 번호가 겹치면 기동을 멈춘다 (둘이 동시에 003 을 만든 것)
    고쳐지지 않은  적용된 파일의 체크섬을 들고 있다. 바뀌면 멈춘다
    혼자서        advisory lock. 인스턴스 둘이 같이 떠도 한 쪽만 적용한다

**체크섬은 줄 끝을 맞춘 뒤에 낸다.** 이걸 빼면 Windows 에서 CRLF 로 체크아웃된
파일과 LF 로 커밋된 파일의 해시가 달라져, 아무도 고치지 않았는데 모든 개발자의
기동이 막힌다. 한 번 겪으면 원인을 찾는 데 반나절이 든다.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("migrate")

DIR = Path(__file__).resolve().parents[1] / "migrations"

# NNN_이름.sql
NAME = re.compile(r"^(\d{3})_[A-Za-z0-9_]+\.sql$")

# advisory lock 키. 이 프로젝트 안에서만 유일하면 된다 —
# 같은 Postgres 에 다른 앱이 살아도 키가 겹치지 않게 임의의 큰 수를 쓴다.
LOCK_KEY = 8_241_207_553_100_311

LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version    TEXT PRIMARY KEY,
    checksum   TEXT        NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class MigrationError(RuntimeError):
    """
    스키마를 기대한 모습으로 만들지 못했다. **기동을 멈추는 예외다.**

    store.py 의 쓰기 함수들은 실패를 삼킨다 — 어르신이 말씀하시는 중에 DB 가
    비틀거렸다고 인터뷰가 끊기면 안 되기 때문이다. 그 관대함 때문에 **스키마가
    틀린 채로 뜨는 것이 가장 위험하다.** 모든 INSERT 가 조용히 실패하고, 화면은
    멀쩡하고, 어르신은 한 시간을 말씀하시고, 아무것도 남지 않는다. 그건 DB 가
    없는 것보다 나쁘다 — 없으면 적어도 로그 첫 줄에 「DB 없이 간다」가 찍힌다.
    """


def _digest(sql: str) -> str:
    """줄 끝과 뒤쪽 공백을 맞춘 뒤 해시. 위 모듈 주석 참조."""
    lines = [ln.rstrip() for ln in sql.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    body = "\n".join(lines).strip() + "\n"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def files() -> list[tuple[str, Path]]:
    """
    번호순 마이그레이션 목록. 이름이 규칙에 안 맞는 파일은 **조용히 넘기지 않는다.**

    `002_photo.sql.bak` 이나 `002 photo.sql` 같은 것을 넘겨 버리면, 적용했다고
    믿는 변경이 실제로는 안 걸린 상태로 돈다. 번호가 겹치는 것도 멈춘다 — 둘이
    같은 번호로 만든 것이고, 둘 다 걸리면 리뷰한 순서와 적용된 순서가 달라진다.
    """
    if not DIR.is_dir():
        raise MigrationError(f"마이그레이션 폴더가 없습니다: {DIR}")

    out: dict[str, Path] = {}
    for path in sorted(DIR.iterdir()):
        if not path.is_file():
            continue
        m = NAME.match(path.name)
        if not m:
            raise MigrationError(
                f"마이그레이션 이름이 규칙에 안 맞습니다: {path.name} "
                f"(NNN_이름.sql 이어야 합니다)")
        version = m.group(1)
        if version in out:
            raise MigrationError(
                f"번호 {version} 이 겹칩니다: {out[version].name} · {path.name} "
                f"— 둘 중 하나에 새 번호를 주세요")
        out[version] = path

    if not out:
        raise MigrationError(f"마이그레이션 파일이 없습니다: {DIR}")
    return sorted(out.items())


async def applied(con: Any) -> dict[str, str]:
    """이미 적용된 {번호: 체크섬}. 표가 없으면 만든다."""
    await con.execute(LEDGER)
    rows = await con.fetch("SELECT version, checksum FROM schema_migration")
    return {r["version"]: r["checksum"] for r in rows}


async def apply(con: Any) -> list[str]:
    """
    스키마를 최신으로 올린다. **이번에 새로 적용한 번호들**을 돌려준다.

    락을 먼저 잡는다. 인스턴스 둘이 동시에 떠서 같은 ALTER 를 걸면 한 쪽이
    실패하는데, 그 실패가 「스키마가 틀렸다」와 구분되지 않는다. 세션 수준 락이라
    finally 에서 반드시 놓는다 — 트랜잭션 락(pg_advisory_xact_lock)을 쓰면
    마이그레이션마다 트랜잭션을 따로 여는 아래 구조와 맞지 않는다.

    **마이그레이션 하나가 트랜잭션 하나다.** 통째로 한 트랜잭션에 넣으면 002 가
    실패했을 때 001 의 기록까지 사라지고, 나눠 걸면 002 만 다음에 다시 걸린다.
    """
    await con.execute("SELECT pg_advisory_lock($1)", LOCK_KEY)
    try:
        done = await applied(con)
        found = files()
        have = {v for v, _ in found}

        # 적용 기록은 있는데 파일이 사라졌다. 누군가 지웠거나, 브랜치를 잘못
        # 옮겼다. 그대로 두면 다음 사람이 그 번호를 재사용해 전혀 다른 SQL 을
        # 「이미 적용됨」으로 만든다.
        gone = sorted(set(done) - have)
        if gone:
            raise MigrationError(
                f"적용 기록은 있는데 파일이 없습니다: {', '.join(gone)} "
                f"— 지우지 말고 새 번호로 되돌리는 마이그레이션을 더하세요")

        fresh: list[str] = []
        for version, path in found:
            sql = path.read_text(encoding="utf-8")
            digest = _digest(sql)

            if version in done:
                if done[version] != digest:
                    raise MigrationError(
                        f"{path.name} 이 적용된 뒤에 바뀌었습니다. "
                        f"되돌리고, 바꾸려던 것은 새 번호로 더하세요 "
                        f"(기록 {done[version][:12]} · 파일 {digest[:12]})")
                continue

            async with con.transaction():
                await con.execute(sql)
                await con.execute(
                    "INSERT INTO schema_migration (version, checksum) VALUES ($1, $2)",
                    version, digest)
            log.info("마이그레이션 %s 적용 — %s", version, path.name)
            fresh.append(version)

        if fresh:
            log.info("스키마를 올렸다: %s", ", ".join(fresh))
        else:
            log.info("스키마는 최신이다 (%d개 적용됨)", len(done))
        return fresh
    finally:
        # 락을 못 놓으면 다음 기동이 영원히 기다린다. 놓기 자체가 실패해도
        # (연결이 끊긴 경우) 세션이 끝나면 Postgres 가 알아서 놓는다.
        try:
            await con.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
        except Exception as e:                                   # noqa: BLE001
            log.warning("advisory lock 해제 실패 (%s) — 연결이 끝나면 풀린다",
                        type(e).__name__)
