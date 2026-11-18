"""
운영자 도구 — 앞선 방식으로 실패한 장만 새 방식(목차 주제 삽화)으로 다시 처리하도록 표시한다.

    python tools/memoir_illust_reprocess.py --memoir m_5c0cf761            보기만 — 다시 처리할 장 · 부를 횟수 · 비용 어림
    python tools/memoir_illust_reprocess.py --memoir m_5c0cf761 --prepare  표시한다 (모델 · 그림을 부르지 않는다)

서버 컴퓨터에서 backend-agent 폴더에서 돌린다 — 서버와 같은 .env(PG_* · DB)를 읽는다. 키는 쓰지 않는다.

**이 도구는 부르지 않는다.** --prepare 는 그 책의 실패한 장을 「새 방식으로 다시」 로 표시하고 책 상태를 running 으로 둘 뿐이다.
실제 처리는 **새 코드로 다시 켠 서버**가 그 책을 다음에 열 때(자서전 보기에서 책을 펼치면) 이어서 한다 — 장마다 선정 1회 · 그림 1회.
한 책을 두 프로세스가 같이 처리하지 않도록 이 도구에서는 처리하지 않는다.

지키는 것 (memoir_illust_service.reprocess_targets)
- 실패한 장만. 사진 장 · 이미 넣은 삽화 · 보류 · 사진 정보를 모르는 장은 그대로 둔다.
- 새 방식으로 이미 부른 장은 다시 표시하지 않는다. 앞선 기록은 지우지 않고 그 장의 history 에 옮겨 둔다.
- --memoir 는 앞부분만 줘도 된다. 둘 이상 걸리면 멈춘다.

종료 코드: 0 됨 / 2 거부(책 없음 · 여럿 · DB 없음)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SELECT_USD = 0.004          # 선정 한 장 — gemini-3.5-flash-lite, 장 본문 · 원문 수천 토큰 기준 어림 (2026-11-16 실측 2,161/512 토큰 ≈ $0.002)
IMAGE_USD = 0.067           # 그림 1K 한 장 — 그림 출력 토큰 1,120 기준 (2026-11-16 실측). 부르기 전에 공식 단가를 다시 본다


async def _find(store, prefix: str) -> list[dict]:
    async with store.pool().acquire() as con:
        rows = await con.fetch(
            "SELECT memoir_id, user_id, title, illustrations FROM memoir WHERE memoir_id LIKE $1 AND deleted_at IS NULL",
            prefix.replace("%", "").replace("_", r"\_") + "%")
    return [dict(r) for r in rows]


async def main_async(args) -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from app.session import memoir_illust_book as book, memoir_illust_service as svc, store

    pol = book.check_policy(args.policy or svc.policy())
    await store.open_pool()
    if not store.enabled():
        print("DB 에 붙지 못했다 — 서버의 .env(PG_*)를 확인한다")
        return 2
    rows = await _find(store, args.memoir)
    if len(rows) != 1:
        print(f"책을 하나로 정하지 못했다 — {len(rows)}권이 걸린다 ({[r['memoir_id'][:12] for r in rows][:5]})")
        return 2
    row = rows[0]
    doc = store._jsonb(row["illustrations"])
    states = {k: {"state": c.get("state"), "failure": c.get("failure"), "policy": svc._policy_id_of(c) if c.get("select") else None}
              for k, c in sorted(((doc or {}).get("chapters") or {}).items(), key=lambda x: int(x[0]))}
    targets = svc.reprocess_targets(doc, pol)
    plan = {"memoir_id": row["memoir_id"], "title": row["title"], "status": (doc or {}).get("status"), "chapters_now": states,
            "to_policy": book.POLICY_IDS[pol], "targets": targets,
            "calls_expected": {"select": len(targets), "image": len(targets)},
            "usd_estimate": round(len(targets) * (SELECT_USD + IMAGE_USD), 3),
            "untouched": [int(k) for k in states if int(k) not in [t["no"] for t in targets]]}
    if args.prepare and targets:
        done = await svc.prepare_reprocess(row["memoir_id"], row["user_id"], pol)
        plan["prepared"] = done["changed"]
        plan["next"] = "새 코드로 다시 켠 서버에서 그 책을 펼치면 표시한 장만 처리한다"
    else:
        plan["prepared"] = False
    print(json.dumps(plan, ensure_ascii=False, indent=1, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="앞선 방식으로 실패한 장만 새 방식으로 다시 처리하도록 표시한다 (부르지 않는다)")
    ap.add_argument("--memoir", required=True, help="자서전 id 또는 앞부분 (예: m_5c0cf761)")
    ap.add_argument("--prepare", action="store_true", help="표시한다. 없으면 보기만 한다")
    ap.add_argument("--policy", choices=["theme", "scene"], help="다시 처리할 방식 (기본: 서버 설정 · theme)")
    args = ap.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
