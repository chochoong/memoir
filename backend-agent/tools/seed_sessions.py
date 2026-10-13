"""
시험 회차를 DB 에 넣고 엽서를 굽는다 — 자서전 시험용 (업무지시서 01 v1.1 2-1 · 2-2)

    python tools/seed_sessions.py --input eval/memoir_seed_A.json \
        --manifest eval/memoir_seed_A.ids.json --api-base http://127.0.0.1:8010 --bake-postcards

    --bake-postcards 를 빼면 회차와 턴만 넣는다. 서버가 떠 있지 않아도 된다.

**합성 자료 전용이다.** 실제 어르신의 말씀을 이 도구로 넣지 않는다.

--------------------------------------------------------------------------
판단은 한 칸 뒤에 넣는다

seed JSON 의 facts_found · facts_retracted 는 **같은 줄의 answer** 에 대한 값이다.
DB 는 그렇게 두지 않는다. turn N 의 decision 은 N-1 번 말씀을 듣고 낸 판단이고
(store.save_turn), 마지막 말씀의 판단은 갈 턴이 없어 회차의 closing_decision 에
남는다. 읽는 쪽(postcard.material)이 그 규칙으로 되돌리므로 여기서도 같은 규칙으로
넣는다 — rows() 가 그 자리다. 그대로 넣으면 사실이 한 칸 앞의 말씀에 붙는다.

--------------------------------------------------------------------------
지우지 않고, 덮어쓰지 않는다

넣는 것은 새 UUID 의 회차뿐이다. 있는 행은 건드리지 않는다. 어디에 넣는지 먼저
보여 주고, 이 PC 의 DB 가 아니면 --allow-remote 없이는 쓰지 않는다.

같은 manifest 로 다시 돌리면 이미 넣은 회차와 구운 엽서는 그대로 쓴다. 엽서 굽기는
모델을 부르는 값이 드는 일이라 --bake-postcards 를 줄 때만, 아직 안 된 것만 굽는다.

회차를 연 시각은 recorded_order 순서다 (manifest 의 seeded_at + 순서 분). 자서전이
기록 순서를 이 시각으로 세운다 — recorded_order 를 담는 컬럼은 없다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

SCHEMA = "memoir-seed-v1.1"
SET_IDS = ("A", "B")
USER_ID = "dev-user"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

LOADED, COMPLETED, NOT_REQUESTED, FAILED = "loaded", "completed", "not_requested", "failed"


# ---------------------------------------------------------------- 입력 검사


def check_seed(doc) -> list[str]:
    """
    잘못된 곳을 전부 모아 돌려준다. 하나라도 있으면 아무것도 쓰지 않는다.

    set_id 와 제목 접두어 검사는 여기 한 곳에 있다 — 받는 세트를 넓히게 되면
    SET_IDS 만 고치면 된다.
    """
    if not isinstance(doc, dict):
        return ["최상위가 객체가 아니다"]
    bad: list[str] = []
    if doc.get("schema_version") != SCHEMA:
        bad.append(f"schema_version 이 {SCHEMA} 가 아니다")
    set_id = doc.get("set_id")
    if set_id not in SET_IDS:
        bad.append(f"set_id 는 {' · '.join(SET_IDS)} 중 하나여야 한다 (지금 {set_id!r})")
    if doc.get("user_id") != USER_ID:
        bad.append(f"user_id 는 {USER_ID} 여야 한다")
    sessions = doc.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        return bad + ["sessions 가 비었거나 목록이 아니다"]

    aliases, orders = [], []
    for n, s in enumerate(sessions):
        at = f"sessions[{n}]"
        if not isinstance(s, dict):
            bad.append(f"{at} 가 객체가 아니다")
            continue
        alias = s.get("alias")
        at = f"{at}({alias})"
        if not isinstance(alias, str) or not alias.strip():
            bad.append(f"{at} alias 가 없다")
        aliases.append(alias)
        title = s.get("title")
        if not isinstance(title, str) or not title.startswith(f"[{set_id}] "):
            bad.append(f"{at} 제목이 「[{set_id}] 」로 시작하지 않는다")
        orders.append(s.get("recorded_order"))
        if s.get("seed") != {"question": None, "answer": ""}:
            bad.append(f'{at} seed 는 {{"question": null, "answer": ""}} 여야 한다')

        turns = s.get("turns")
        if not isinstance(turns, list) or not turns:
            bad.append(f"{at} turns 가 비었거나 목록이 아니다")
            continue
        idxs = []
        for t in turns:
            if not isinstance(t, dict):
                bad.append(f"{at} 턴이 객체가 아니다")
                continue
            idxs.append(t.get("idx"))
            where = f"{at} idx={t.get('idx')}"
            if not isinstance(t.get("question"), str):
                bad.append(f"{where} question 이 문자열이 아니다")
            if not isinstance(t.get("answer"), str) or not t["answer"].strip():
                bad.append(f"{where} answer 가 비었다")
            for k in ("facts_found", "facts_retracted"):
                v = t.get(k)
                if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                    bad.append(f"{where} {k} 가 문자열 목록이 아니다")
        if idxs != list(range(1, len(turns) + 1)):
            bad.append(f"{at} idx 가 1부터 차례가 아니다 {idxs}")

    if len(set(aliases)) != len(aliases):
        bad.append(f"alias 가 겹친다 {aliases}")
    if orders != list(range(1, len(sessions) + 1)):
        bad.append(f"recorded_order 가 1부터 차례가 아니다 {orders}")
    return bad


# ---------------------------------------------------------------- 행 만들기


def rows(sess: dict) -> tuple[list[dict], dict | None]:
    """
    seed 회차 하나 → (턴 행들, closing_decision).

    0번은 씨앗이다 — question 없음, answer 빈 글. 말씀은 1번부터 원문 그대로다.
    k 번 말씀의 판단은 k+1 번 행에, 마지막 말씀의 판단은 closing_decision 에 둔다.
    1번 행의 decision 은 씨앗을 듣고 낸 판단 자리라 비운다.
    """
    out = [{"idx": 0, "question": sess["seed"]["question"],
            "answer": sess["seed"]["answer"], "decision": None}]
    heard: dict | None = None
    for t in sess["turns"]:
        out.append({"idx": t["idx"], "question": t["question"],
                    "answer": t["answer"], "decision": heard})
        heard = {"facts_found": list(t["facts_found"]),
                 "facts_retracted": list(t["facts_retracted"])}
    return out, heard


def created_at(seeded_at: datetime, order: int) -> datetime:
    return seeded_at + timedelta(minutes=order)


# ---------------------------------------------------------------- DB


def _env() -> dict:
    """서버와 같은 순서로 .env 를 읽는다 (main.py 머리). 값은 찍지 않는다."""
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    if os.environ.get("MEMOIR_DB") == "supabase":
        load_dotenv(ROOT / ".env.supabase", override=True)

    from app.session import store

    return store._dsn()


async def _exists(con, sid: str) -> dict | None:
    r = await con.fetchrow(
        "SELECT user_id, title, (SELECT count(*) FROM turn t WHERE t.session_id = s.session_id) AS n"
        "  FROM session s WHERE session_id = $1", uuid.UUID(sid))
    return dict(r) if r else None


async def _insert(con, sid: str, user_id: str, sess: dict, at: datetime) -> None:
    """회차 하나를 한 번에. 중간에 실패하면 그 회차는 아무것도 남지 않는다."""
    turn_rows, closing = rows(sess)
    async with con.transaction():
        await con.execute(
            """
            INSERT INTO session (session_id, user_id, title, state, turn, max_turn, t2_seconds,
                                 closed_reason, created_at, closed_at, closing_decision)
            VALUES ($1, $2, $3, 'CLOSED', $4, 0, 5.0, 'finish', $5, $6, $7)
            """,
            uuid.UUID(sid), user_id, sess["title"], len(sess["turns"]), at,
            at + timedelta(seconds=50),
            json.dumps(closing, ensure_ascii=False) if closing else None)
        for r in turn_rows:
            await con.execute(
                """
                INSERT INTO turn (session_id, idx, question, answer, decision, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                uuid.UUID(sid), r["idx"], r["question"], r["answer"],
                json.dumps(r["decision"], ensure_ascii=False) if r["decision"] else None,
                at + timedelta(seconds=r["idx"]))


async def load(doc: dict, man: dict, dsn: dict) -> None:
    """manifest 에 적힌 대로 회차를 넣는다. 넣을 때마다 manifest 의 그 줄을 고친다."""
    import asyncpg

    seeded_at = datetime.fromisoformat(man["seeded_at"])
    by_alias = {s["alias"]: s for s in doc["sessions"]}
    con = await asyncpg.connect(**dsn, timeout=10)
    try:
        if await con.fetchval("SELECT to_regclass('public.session')") is None:
            raise SystemExit("이 DB 에 session 표가 없다 — 서버를 한 번 띄워 스키마를 올린 뒤 다시 돌린다")
        for m in man["sessions"]:
            sess = by_alias[m["alias"]]
            have = await _exists(con, m["session_id"])
            if have:
                want = (man["user_id"], sess["title"], len(sess["turns"]) + 1)
                if (have["user_id"], have["title"], have["n"]) != want:
                    raise SystemExit(f"{m['alias']} {m['session_id']} 가 DB 에 다른 내용으로 있다 — 멈춘다")
                m["session_status"] = LOADED
                print(f"  {m['alias']:6} 있음   {m['session_id']}  {sess['title']}")
                continue
            if m.get("session_status") == LOADED:
                raise SystemExit(
                    f"{m['alias']} 는 manifest 에 넣었다고 적혀 있는데 이 DB 에 없다 — "
                    "다른 DB 의 manifest 다. 멈춘다")
            await _insert(con, m["session_id"], man["user_id"], sess,
                          created_at(seeded_at, sess["recorded_order"]))
            m["session_status"] = LOADED
            print(f"  {m['alias']:6} 넣음   {m['session_id']}  {sess['title']}")
    finally:
        await con.close()


# ---------------------------------------------------------------- 엽서


def _http(method: str, url: str, user_id: str, timeout: float) -> tuple[int, str, bytes]:
    req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None,
                                 headers={"X-User-Id": user_id})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("content-type") or "", r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type") or "", e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, "", str(e).encode()


def _detail(body: bytes) -> str:
    try:
        return str(json.loads(body.decode()).get("detail"))[:200]
    except (ValueError, AttributeError):
        return body.decode(errors="replace")[:200]


def _has_postcard(base: str, m: dict, user_id: str) -> bool:
    code, ctype, _ = _http("GET", f"{base}/api/sessions/{m['session_id']}/postcard", user_id, 30)
    return code == 200 and ctype.startswith("image/")


def bake(man: dict, base: str, timeout: float) -> None:
    """
    안 구워진 회차만 굽는다. 구운 뒤 이미지가 실제로 조회되어야 completed 다.

    안 되면 failed 와 까닭을 적는다. 성공한 것처럼 적지 않고, 행을 지어 넣지도 않는다.
    """
    for m in man["sessions"]:
        if m.get("session_status") != LOADED:
            continue
        if _has_postcard(base, m, man["user_id"]):
            m["postcard_status"] = COMPLETED
            m.pop("postcard_detail", None)
            print(f"  {m['alias']:6} 엽서 있음")
            continue
        code, _, body = _http("POST", f"{base}/api/sessions/{m['session_id']}/postcard",
                              man["user_id"], timeout)
        if code == 200 and _has_postcard(base, m, man["user_id"]):
            m["postcard_status"] = COMPLETED
            m.pop("postcard_detail", None)
            print(f"  {m['alias']:6} 엽서 구움")
        else:
            m["postcard_status"] = FAILED
            m["postcard_detail"] = (f"HTTP {code} · {_detail(body)}" if code != 200
                                    else "구웠다는 답은 왔는데 이미지가 조회되지 않는다")
            print(f"  {m['alias']:6} 엽서 실패 — {m['postcard_detail']}")


def verify(man: dict, base: str) -> None:
    """굽지 않는 실행. 적힌 completed 가 아직 맞는지만 본다 — 모델은 부르지 않는다."""
    for m in man["sessions"]:
        if m.get("postcard_status") == COMPLETED and not _has_postcard(base, m, man["user_id"]):
            m["postcard_status"] = FAILED
            m["postcard_detail"] = "completed 로 적혀 있었는데 이미지가 조회되지 않는다"
            print(f"  {m['alias']:6} 엽서 없음 — manifest 를 고쳤다")


# ---------------------------------------------------------------- manifest


def manifest(doc: dict, path: Path) -> dict:
    """
    있으면 읽고, 없으면 새 UUID 로 만든다. 세트가 다르거나 회차가 어긋나면 멈춘다.

    열쇠는 01 v1.1 「manifest 형식 예시」 그대로에 둘을 더했다 — seeded_at(회차
    시각의 기준)과 session_status(회차 적재 결과).
    """
    if path.exists():
        man = json.loads(path.read_text(encoding="utf-8"))
        if man.get("set_id") != doc["set_id"] or man.get("user_id") != doc["user_id"]:
            raise SystemExit(f"{path.name} 는 다른 세트의 manifest 다")
        if [m["alias"] for m in man["sessions"]] != [s["alias"] for s in doc["sessions"]]:
            raise SystemExit(f"{path.name} 의 회차가 입력과 다르다 — 다른 manifest 경로를 쓴다")
        return man
    # 가장 늦은 회차도 지금보다 앞이게 한다. 앞날의 시각을 넣지 않는다.
    seeded_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
    return {
        "set_id": doc["set_id"],
        "user_id": doc["user_id"],
        "seeded_at": seeded_at.isoformat(),
        "sessions": [{"alias": s["alias"], "session_id": str(uuid.uuid4()), "title": s["title"],
                      "session_status": "pending", "postcard_status": NOT_REQUESTED}
                     for s in doc["sessions"]],
    }


def _save(man: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- 실행


def main() -> int:
    ap = argparse.ArgumentParser(description="자서전 시험 회차를 넣고 엽서를 굽는다 (합성 자료 전용)")
    ap.add_argument("--input", required=True, type=Path, help="seed JSON (memoir-seed-v1.1)")
    ap.add_argument("--manifest", required=True, type=Path, help="alias → 실제 session_id 대응 파일")
    ap.add_argument("--api-base", default="http://127.0.0.1:8010", help="엽서를 굽는 서버")
    ap.add_argument("--bake-postcards", action="store_true", help="엽서를 굽는다 (모델을 부른다)")
    ap.add_argument("--bake-timeout", type=float, default=180.0, help="엽서 한 장을 기다리는 초")
    ap.add_argument("--allow-remote", action="store_true", help="이 PC 가 아닌 DB 에도 쓴다")
    a = ap.parse_args()

    doc = json.loads(a.input.read_text(encoding="utf-8"))
    bad = check_seed(doc)
    if bad:
        print(f"{a.input.name} — 입력이 틀려 아무것도 쓰지 않았다")
        for b in bad:
            print("  ·", b)
        return 2

    dsn = _env()
    target = f"{dsn['host']}:{dsn['port']}/{dsn['database']}"
    print(f"세트 {doc['set_id']} · 회차 {len(doc['sessions'])}개 → DB {target}")
    if dsn["host"] not in LOCAL_HOSTS and not a.allow_remote:
        print("이 PC 의 DB 가 아니다. 맞는 DB 인지 확인하고 --allow-remote 를 붙여 다시 돌린다.")
        return 2

    man = manifest(doc, a.manifest)
    base = a.api_base.rstrip("/")
    try:
        asyncio.run(load(doc, man, dsn))
        if a.bake_postcards:
            print(f"엽서 — {base}")
            bake(man, base, a.bake_timeout)
        elif any(m.get("postcard_status") == COMPLETED for m in man["sessions"]):
            verify(man, base)
    finally:
        _save(man, a.manifest)

    done = [m for m in man["sessions"] if m.get("postcard_status") == COMPLETED]
    failed = [m for m in man["sessions"] if m.get("postcard_status") == FAILED]
    print(f"manifest {a.manifest} — 회차 {len(man['sessions'])}개 · 엽서 {len(done)}장"
          + (f" · 실패 {len(failed)}장" if failed else ""))
    print("session_ids:", json.dumps([m["session_id"] for m in man["sessions"]]))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
