"""
자서전 5단계 파이프라인을 합성 seed 로 돌린다 (단위 8P). DB 도 서버도 쓰지 않는다.

    python tools/memoir_pipeline.py --seed eval/memoir_seed_A.json --aliases s-a,s-b,s-c
    python tools/memoir_pipeline.py --input eval/memoir_input_A3.json
    python tools/memoir_pipeline.py --seed eval/memoir_seed_A.json --aliases s-a,s-b,s-c --dry-run

**받는 자료는 합성 seed A/B 에서 만든 입력뿐이다** (설계 Q3). --input 은
tools/memoir_input.py 의 출력이고, 그 안의 말씀이 모두 해당 seed 원문과 글자까지
같을 때만 받는다. 실제 사용자 자료는 이 도구로 모델에 보내지 않는다.

결과는 eval/runs/<run_ref>/ 에 남는다 (git 제외). 팀에 넘길 것은 그 안의
r1_summary.md 다 — 본문 · 원문 · 비밀값이 없다.

--dry-run 은 입력만 만들어 보이고 모델을 부르지 않는다.

종료 코드: 0 pipeline_complete · insufficient_material / 1 그 밖의 결과 / 2 입력 거부
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app.session import memoir                                            # noqa: E402
from app.session import memoir_pipeline as pipe                           # noqa: E402
from tools import seed_sessions as seed                                   # noqa: E402

EVAL = ROOT / "eval"


class InputRejected(ValueError):
    """이 도구가 받지 않는 입력. 모델을 부르지 않는다."""


def _seed_doc(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputRejected(f"seed 를 읽지 못했다: {path.name} ({e})") from e
    bad = seed.check_seed(doc)
    if bad:
        raise InputRejected("합성 seed 가 아니다: " + "; ".join(bad[:5]))
    return doc


def session_range() -> tuple[int, int]:
    """
    고를 수 있는 회차 수. 서버가 정한 값을 그대로 따른다 — 두 판이 다르게 둔다.

        develop                  MIN_SESSIONS, MAX_SESSIONS = 3, 5        (상수)
        feature/theme-interview  MIN_SESSIONS = 3 · max_sessions()        (MEMOIR_MAX_SESSIONS, 기본 5)

    함수가 있으면 함수를 먼저 본다. 둘 다 없으면 값을 지어내지 않고 멈춘다.
    """
    hi = getattr(memoir, "max_sessions", None)
    top = hi() if callable(hi) else getattr(memoir, "MAX_SESSIONS", None)
    lo = getattr(memoir, "MIN_SESSIONS", None)
    if not isinstance(lo, int) or not isinstance(top, int):
        raise InputRejected("memoir 모듈에서 회차 수 범위(MIN_SESSIONS · max_sessions/MAX_SESSIONS)를 찾지 못했다")
    return lo, top


def records_from_seed(doc: dict, aliases: list[str]) -> list[dict]:
    """
    seed 회차 → store.load_session 모양 기록. seed 도구와 같은 rows() 를 쓴다.

    session_id 는 alias 그대로, 시작 시각은 recorded_order 로 만든다 (test_memoir.record 와
    같은 방식 — merge 는 시각으로 기록 순서를 세운다).
    """
    lo, hi = session_range()
    if not lo <= len(aliases) <= hi:
        raise InputRejected(f"회차 {len(aliases)}개 — {lo}~{hi}개여야 한다")
    if len(set(aliases)) != len(aliases):
        raise InputRejected("같은 회차를 두 번 골랐다")
    by_alias = {s["alias"]: s for s in doc["sessions"]}
    missing = [a for a in aliases if a not in by_alias]
    if missing:
        raise InputRejected(f"seed 에 없는 alias: {', '.join(missing)}")
    out = []
    for a in aliases:
        sess = by_alias[a]
        turn_rows, closing = seed.rows(sess)
        out.append({
            "session_id": a, "user_id": doc["user_id"], "title": sess["title"],
            "created_at": f"2026-10-12T10:{sess['recorded_order']:02d}:00+00:00",
            "fragments": turn_rows, "closing_decision": closing,
        })
    return out


def load_input(path: Path) -> tuple[dict, list[dict], dict]:
    """
    memoir_input.py 출력 → (merge 출력, turn_map, 식별). 합성 seed 에서 나온 것만 받는다.

    UUID 판(input · turn_map)을 쓴다 — 서버가 모델에 주는 그대로다. 말씀 하나하나가
    그 set_id 의 seed 원문에 있어야 한다. 하나라도 없으면 실제 자료일 수 있어 거부한다.
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputRejected(f"입력을 읽지 못했다: {path.name} ({e})") from e
    if not isinstance(doc, dict) or not {"set_id", "aliases", "input", "turn_map"} <= set(doc):
        raise InputRejected("memoir_input.py 출력 모양이 아니다 (set_id · aliases · input · turn_map)")
    if doc["set_id"] not in seed.SET_IDS:
        raise InputRejected(f"set_id={doc['set_id']!r} — 합성 seed {seed.SET_IDS} 만 받는다")
    src = _seed_doc(EVAL / f"memoir_seed_{doc['set_id']}.json")
    said = {t["answer"].strip() for s in src["sessions"] for t in s["turns"]}
    try:
        pipe.check_input(doc["input"], doc["turn_map"])
    except pipe.PipelineError as e:
        raise InputRejected(e.message) from e
    foreign = [u["turn"] for u in doc["input"]["utterances"] if u["elder"].strip() not in said]
    if foreign:
        raise InputRejected(f"seed {doc['set_id']} 에 없는 말씀이 있다 (턴 {foreign[:5]}) — 합성 자료만 받는다")
    return doc["input"], doc["turn_map"], {"seed": f"memoir_seed_{doc['set_id']}.json",
                                           "set_id": doc["set_id"], "aliases": doc["aliases"]}


def run_ref(set_id: str, n: int, data: dict) -> str:
    at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{at}-{set_id}{n}-{pipe.input_ref(data)[:4]}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="자서전 5단계 파이프라인을 합성 seed 로 돌린다")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--seed", type=Path, help="합성 seed 파일 (eval/memoir_seed_A.json 등)")
    src.add_argument("--input", type=Path, help="tools/memoir_input.py 출력 (합성 seed 에서 만든 것만)")
    ap.add_argument("--aliases", help="--seed 와 함께. 고를 회차 3~5개, 쉼표 (예: s-a,s-b,s-c)")
    ap.add_argument("--out-dir", type=Path, default=EVAL / "runs")
    ap.add_argument("--dry-run", action="store_true", help="입력만 만들고 모델을 부르지 않는다")
    a = ap.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")      # .env.supabase 는 읽지 않는다 — DB 를 쓰지 않는다

    try:
        if a.seed:
            if not a.aliases:
                raise InputRejected("--seed 에는 --aliases 가 필요하다")
            doc = _seed_doc(a.seed)
            aliases = [x.strip() for x in a.aliases.split(",") if x.strip()]
            data, turn_map = pipe.build_input(records_from_seed(doc, aliases))
            meta = {"seed": a.seed.name, "set_id": doc["set_id"], "aliases": aliases}
        else:
            data, turn_map, meta = load_input(a.input)
    except (InputRejected, pipe.PipelineError) as e:
        print(f"입력 거부 — {e}", file=sys.stderr)
        return 2

    meta["run_ref"] = run_ref(meta["set_id"], len(data["sessions"]), data)
    cfg = pipe.settings()
    print(f"입력 {meta['seed']} {','.join(meta['aliases'])} — 회차 {len(data['sessions'])}개 · "
          f"말씀 {len(data['utterances'])}턴 · input_ref {pipe.input_ref(data)}")
    print(f"모델 {cfg['MEMOIR_PIPE_TEXT_MODEL']} · 온도 {cfg['MEMOIR_PIPE_TEMPERATURE']} · "
          f"전체 상한 {cfg['MEMOIR_PIPE_TOTAL_TIMEOUT']:.0f}초 · 재시도 {cfg['retries']} · "
          f"예상 호출 {MIN_CALLS}~{MAX_CALLS}회 (장 수 + 4)")
    if a.dry_run:
        print("--dry-run — 모델을 부르지 않았다")
        return 0

    folder = a.out_dir / meta["run_ref"]
    result = asyncio.run(pipe.run(data, turn_map, recorder=pipe.Recorder(folder), meta=meta))
    steps = json.loads((folder / "run.json").read_text(encoding="utf-8"))["steps"]
    for s in steps:
        u = s.get("usage") or {}
        print(f"  {s['stage']:<8} {s.get('chapter_key') or '':<5} {'O' if s['ok'] else 'X'} "
              f"{s['ms']:>6}ms  출력 {s['out_chars']}자  토큰 {u.get('prompt')}/{u.get('output')}/"
              f"{u.get('thoughts')}  {s.get('finish') or ''}")
    v = result["verification"]
    print(f"결과 {result['generation_state']} · pipeline_complete={str(result['pipeline_complete']).lower()} · "
          f"검증 {v['state']}/{v['verdict']} · 호출 {result['calls']}회 · 장 {len(result['chapters'])}개")
    print(f"human_review={result['human_review']} — 사람 검수 전이다. 최종 완성본이 아니다")
    if result["failure"]:
        f = result["failure"]
        print(f"실패 {f['stage']}{'/' + f['chapter_key'] if f['chapter_key'] else ''} {f['kind']} — {f['message']}")
    print(f"기록 {folder}")
    done = result["pipeline_complete"] or result["generation_state"] == pipe.INSUFFICIENT
    return 0 if done else 1


MIN_CALLS = pipe.MIN_CHAPTERS + 4
MAX_CALLS = pipe.MAX_CHAPTERS + 4

if __name__ == "__main__":
    raise SystemExit(main())
