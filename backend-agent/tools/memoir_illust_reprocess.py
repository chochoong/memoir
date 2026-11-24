"""
운영자 도구 — 이름을 댄 실패 장만 지금 판(목차 주제 삽화 chapter_theme_v2)으로 다시 처리하도록 표시한다.

    python tools/memoir_illust_reprocess.py --memoir m_d1571e8e                         보기만 — 장 상태 · 다시 할 수 있는 장 · 비용 어림
    python tools/memoir_illust_reprocess.py --memoir m_d1571e8e --chapter 1 --prepare   1장만 표시한다 (모델 · 그림을 부르지 않는다)

서버 컴퓨터에서 backend-agent 폴더에서 돌린다 — 서버와 같은 .env(PG_* · DB)를 읽는다. 키는 쓰지 않는다.

**이 도구는 부르지 않는다.** --prepare 는 --chapter 로 이름을 댄 실패 장만 「지금 판으로 다시」 로 표시하고 책 상태를 running 으로 둘 뿐이다.
--chapter 없이 --prepare 하면 거부한다 — 실패한 장을 모두 저절로 다시 부르지 않는다.
실제 처리는 **새 코드로 다시 켠 서버**가 그 책을 다음에 열 때(자서전 보기에서 책을 펼치면) 이어서 한다 — 장마다 선정 1회 · 그림 1회.
한 책을 두 프로세스가 같이 처리하지 않도록 이 도구에서는 처리하지 않는다.

지키는 것 (memoir_illust_service.reprocess_targets)
- 이름을 댄 장 가운데 실패한 장만. 사진 장 · 이미 넣은 삽화 · 보류 · 사진 정보를 모르는 장은 이름을 대도 그대로 둔다(까닭을 보인다).
- 지금 판으로 이미 부른 장은 다시 표시하지 않는다. 판이 바뀌면(v1 → v2) 앞선 판으로 실패한 장은 한 번 다시 할 수 있다.
- 앞선 기록 · 호출 수는 지우지 않는다 — 앞선 기록은 그 장의 history 에 옮겨 둔다.
- --memoir 는 앞부분만 줘도 된다. 둘 이상 걸리면 멈춘다.

사진 다시 계산 (2026-11-24 — 회차 사진이 빠지던 규칙을 고친 뒤 이미 만든 책에)

    python tools/memoir_illust_reprocess.py --memoir m_d1571e8e --refresh-photos            보기만 — 사진이 새로 놓일 장 · 놓지 못한 사진
    python tools/memoir_illust_reprocess.py --memoir m_d1571e8e --refresh-photos --apply    적어 둔다 (모델 · 그림을 부르지 않는다)

    사진이 새로 놓이는 장은 photo 로 바뀐다 — 앞서 만든 AI 삽화 기록 · 저장된 그림은 지우지 않는다(화면에는 사진이 먼저 보인다).
    새로 그림을 만들 장은 생기지 않고, 책 상태를 running 으로 두지 않는다. 책마다 운영자가 고른다 — 모든 책을 한꺼번에 바꾸지 않는다.

종료 코드: 0 됨 / 2 거부(책 없음 · 여럿 · DB 없음 · --chapter 없는 --prepare · --refresh-photos 없는 --apply)
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
    if args.apply and not args.refresh_photos:
        print("--apply 는 --refresh-photos 와 함께만 쓴다")
        return 2
    if args.prepare and not args.chapter:
        print("--prepare 에는 --chapter 가 있어야 한다 — 다시 처리할 장을 이름 댄다 (실패한 장을 모두 저절로 다시 부르지 않는다)")
        return 2
    await store.open_pool()
    if not store.enabled():
        print("DB 에 붙지 못했다 — 서버의 .env(PG_*)를 확인한다")
        return 2
    rows = await _find(store, args.memoir)
    if len(rows) != 1:
        print(f"책을 하나로 정하지 못했다 — {len(rows)}권이 걸린다 ({[r['memoir_id'][:12] for r in rows][:5]})")
        return 2
    row = rows[0]
    if args.refresh_photos:                                  # 사진 배치만 다시 계산 — 부르지 않는다
        out = await svc.refresh_photos(row["memoir_id"], row["user_id"], apply=args.apply)
        print(json.dumps({"memoir_id": row["memoir_id"], "title": row["title"], "refresh_photos": out}, ensure_ascii=False,
                         indent=1, default=str))
        return 0
    doc = store._jsonb(row["illustrations"])
    states = {k: {"state": c.get("state"), "failure": c.get("failure"), "policy": svc._policy_id_of(c) if c.get("select") else None}
              for k, c in sorted(((doc or {}).get("chapters") or {}).items(), key=lambda x: int(x[0]))}
    eligible = svc.reprocess_targets(doc, pol)                       # 다시 할 수 있는 장 (이름을 대기 전)
    targets = svc.reprocess_targets(doc, pol, args.chapter) if args.chapter else []
    plan = {"memoir_id": row["memoir_id"], "title": row["title"], "status": (doc or {}).get("status"), "chapters_now": states,
            "to_policy": book.POLICY_IDS[pol], "eligible": [t["no"] for t in eligible], "requested": args.chapter or [],
            "targets": targets, "refused": svc.refused_chapters(doc, args.chapter or [], pol),
            "calls_expected": {"select": len(targets), "image": len(targets)},
            "usd_estimate": round(len(targets) * (SELECT_USD + IMAGE_USD), 3),
            "untouched": [int(k) for k in states if int(k) not in [t["no"] for t in targets]]}
    if args.prepare and targets:
        done = await svc.prepare_reprocess(row["memoir_id"], row["user_id"], pol, args.chapter)
        plan["prepared"] = done["changed"]
        plan["next"] = "새 코드로 다시 켠 서버에서 그 책을 펼치면 표시한 장만 처리한다"
    else:
        plan["prepared"] = False
    print(json.dumps(plan, ensure_ascii=False, indent=1, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="이름을 댄 실패 장만 지금 판으로 다시 처리하도록 표시한다 (부르지 않는다)")
    ap.add_argument("--memoir", required=True, help="자서전 id 또는 앞부분 (예: m_5c0cf761)")
    ap.add_argument("--chapter", type=int, action="append", help="다시 처리할 장 번호 (여러 번 쓸 수 있다)")
    ap.add_argument("--prepare", action="store_true", help="--chapter 로 댄 장을 표시한다. 없으면 보기만 한다")
    ap.add_argument("--policy", choices=["theme", "scene"], help="다시 처리할 방식 (기본: 서버 설정 · theme)")
    ap.add_argument("--refresh-photos", action="store_true", help="사진 배치만 지금 규칙으로 다시 계산한다 (부르지 않는다)")
    ap.add_argument("--apply", action="store_true", help="--refresh-photos 의 결과를 적어 둔다. 없으면 보기만 한다")
    args = ap.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
