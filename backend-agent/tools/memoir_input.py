"""
합치기 함수가 실제로 만든 모델 입력과 turn_map 을 파일로 뽑는다 (업무지시서 01 v1.1 8절 「공통 예시」)

    python tools/memoir_input.py --manifest eval/memoir_seed_A.ids.json \
        --aliases s-a,s-b,s-c --out eval/memoir_input_A3.json

DB 에서 회차를 읽어 서버와 **같은 함수**(memoir.merge)로 합친다. 손으로 쓴 예시가
아니다. 모델은 부르지 않는다.

엽서가 있는지는 보지 않는다 — 그건 고를 수 있느냐의 조건이지 합친 결과를 바꾸지
않는다. 그래서 엽서를 굽기 전의 DB 에서도 돌릴 수 있다. 서버 라우트는 본다.

파일에는 두 벌이 들어간다.

    input · turn_map              서버가 모델에 주는 그대로. session_id 는 실제 UUID 다
    input_alias · turn_map_alias  UUID 만 manifest 의 alias 로 바꾼 것

뒤의 것은 03 의 정답(s-a 같은 가상 ID 로 쓴 것)과 글자 그대로 견주라고 둔다.
바꾸는 것은 session_id 값뿐이다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


def aliased(obj, names: dict[str, str]):
    """session_id 값만 alias 로 바꾼 사본."""
    if isinstance(obj, list):
        return [aliased(x, names) for x in obj]
    if isinstance(obj, dict):
        return {k: names.get(v, v) if k == "session_id" else aliased(v, names)
                for k, v in obj.items()}
    return obj


async def build(ids: list[str], user_id: str) -> tuple[dict, list[dict]]:
    from app.session import memoir, store

    await store.open_pool()
    if not store.enabled():
        raise SystemExit("DB 에 붙지 못했다")
    try:
        recs = []
        for sid in memoir.check_selection(ids):
            rec = await store.load_session(sid)
            if rec is None or rec["user_id"] != user_id:
                raise SystemExit(f"이 DB 에 없는 회차다 {sid}")
            recs.append(rec)
        return memoir.merge(recs)
    finally:
        await store.close_pool()


def main() -> int:
    ap = argparse.ArgumentParser(description="자서전 합치기 함수의 출력(입력 JSON · turn_map)을 뽑는다")
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--aliases", required=True, help="고를 회차. 쉼표로 3~5개 (예: s-a,s-b,s-c)")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    if os.environ.get("MEMOIR_DB") == "supabase":
        load_dotenv(ROOT / ".env.supabase", override=True)

    man = json.loads(a.manifest.read_text(encoding="utf-8"))
    by_alias = {m["alias"]: m["session_id"] for m in man["sessions"]}
    picked = [x.strip() for x in a.aliases.split(",") if x.strip()]
    missing = [x for x in picked if x not in by_alias]
    if missing:
        print("manifest 에 없는 alias:", ", ".join(missing))
        return 2

    data, turn_map = asyncio.run(build([by_alias[x] for x in picked], man["user_id"]))
    names = {sid: alias for alias, sid in by_alias.items()}
    out = {
        "set_id": man["set_id"],
        "aliases": picked,
        "session_ids": [by_alias[x] for x in picked],
        "input": data,
        "turn_map": turn_map,
        "input_alias": aliased(data, names),
        "turn_map_alias": aliased(turn_map, names),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8", newline="\n")
    print(f"{a.out} — 회차 {len(data['sessions'])}개 · 말씀 {len(turn_map)}턴 · "
          f"사실 {len(data['shared_state']['confirmed_facts'])}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
