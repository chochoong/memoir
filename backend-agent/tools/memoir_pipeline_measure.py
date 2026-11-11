"""
자서전 다섯 단계의 시간 · 토큰 · 비용을 잰다 (단위 8S — 서비스 연결 비교 기준)

    python tools/memoir_pipeline_measure.py 39          39회차 한 번
    python tools/memoir_pipeline_measure.py 5 13 39     크기별로 차례로

**합성 seed C · A · B 회차만 쓴다.** 차례로 돌려 n 개를 채운다 (13개 뒤로는 같은 회차가
되풀이된다 — 내용 품질이 아니라 입력 크기에 따른 시간 · 토큰을 보는 자료다). DB · 서버를
쓰지 않고, 서비스와 같은 memoir.merge → memoir_pipeline.run 을 부른다.

설정은 지금 환경의 MEMOIR_PIPE_* 그대로다. 운영과 같게 재려면 같은 값을 넣고 돌린다
(docs/8S-R1_자서전_파이프라인_실측.md 의 설정 표). 본문 · 원문은 찍지 않는다 —
단계별 시간 · 토큰과 결과 상태만. 비용은 memoir.usage (단가를 모르는 모델은 적지 않는다).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.session import memoir, memoir_pipeline as mp  # noqa: E402
from tools import seed_sessions as seed  # noqa: E402


def sessions() -> list[dict]:
    out = []
    for name in ("C", "A", "B"):
        doc = json.loads((ROOT / "eval" / f"memoir_seed_{name}.json").read_text(encoding="utf-8"))
        out += doc["sessions"]
    return out


def records(n: int) -> list[dict]:
    """합성 회차 n 개를 store.load_session 모양으로. 연 시각은 한 시간씩 뒤로."""
    base = sessions()
    recs = []
    for i in range(n):
        s = base[i % len(base)]
        turn_rows, closing = seed.rows(s)
        day, hour = 1 + i // 24, i % 24
        recs.append({"session_id": f"00000000-0000-4000-8000-{i:012d}", "user_id": "measure", "title": s["title"],
                     "created_at": f"2026-10-{day:02d}T{hour:02d}:00:00+00:00",
                     "closed_at": f"2026-10-{day:02d}T{hour:02d}:50:00+00:00",
                     "fragments": turn_rows, "closing_decision": closing, "postcard": None, "elder_id": "e"})
    return recs


async def one(n: int) -> None:
    data, turn_map = memoir.merge(records(n))
    rec = mp.Recorder()
    model = mp.settings()["MEMOIR_PIPE_TEXT_MODEL"]
    t0 = time.monotonic()
    res = await mp.run(data, turn_map, recorder=rec)
    total = time.monotonic() - t0
    steps = json.loads(rec.files.get("run.json", "{}")).get("steps", [])
    print(f"[{n}회차] 말씀 {len(turn_map)}턴 · 입력 {len(json.dumps(data, ensure_ascii=False))}자 · 모델 {model} → "
          f"{res['generation_state']} · 총 {total:.1f}초 · 호출 {res.get('calls')} · 장 {len(res.get('chapters') or [])}"
          f" · 검증 {(res.get('verification') or {}).get('state')}", flush=True)
    for x in steps:
        u = x.get("usage") or {}
        print(f"    · {x['stage']}{'/' + x['chapter_key'] if x.get('chapter_key') else ''}: "
              f"입력 {u.get('prompt') or 0:,} · 출력 {u.get('output') or 0:,} · 생각 {u.get('thoughts') or 0:,}"
              f" · {x['ms'] / 1000:.1f}초{'' if x['ok'] else ' (실패)'}", flush=True)
    use = memoir.usage(model, steps)
    print(f"    합계 입력 {use['input']:,} · 출력 {use['output']:,} · 생각 {use['thoughts']:,} · 비용 "
          + (f"약 ${use['usd']:.3f}" if use["usd"] is not None else "단가 모름"), flush=True)
    fail = res.get("failure")
    if fail:
        print(f"    실패 {fail.get('stage')} {fail.get('kind')} {str(fail.get('message'))[:160]}", flush=True)


async def main() -> None:
    sizes = [int(a) for a in sys.argv[1:]] or [39]
    print("설정 " + json.dumps({k: v for k, v in mp.settings().items() if k.startswith("MEMOIR_PIPE_")},
                              ensure_ascii=False), flush=True)
    for n in sizes:
        await one(n)


if __name__ == "__main__":
    asyncio.run(main())
