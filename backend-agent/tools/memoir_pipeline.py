"""
자서전 5단계 파이프라인을 합성 seed 로 돌린다 (단위 8P). DB 도 서버도 쓰지 않는다.

    python tools/memoir_pipeline.py --seed eval/memoir_seed_A.json --aliases s-a,s-b,s-c
    python tools/memoir_pipeline.py --input eval/memoir_input_A3.json
    python tools/memoir_pipeline.py --seed eval/memoir_seed_A.json --aliases s-a,s-b,s-c --dry-run
    python tools/memoir_pipeline.py --seed eval/memoir_seed_C.json --aliases c1,c2,c3,c4,c5 --focus "소재"

**받는 자료는 합성 seed A · B · C 에서 만든 입력뿐이다** (설계 Q3). C 는 이 실행기 전용
합성 세트다(팀 seed 도구로 DB 에 넣지 않는다 — check_pipeline_seed). --input 은
tools/memoir_input.py 의 출력이고, 그 안의 말씀이 모두 해당 seed 원문과 글자까지
같을 때만 받는다. 실제 사용자 자료는 이 도구로 모델에 보내지 않는다.

결과는 eval/runs/<run_ref>/ 에 남는다 (git 제외). 팀에 넘길 것은 그 안의
r1_summary.md 다 — 본문 · 원문 · 비밀값이 없다.

--dry-run 은 입력만 만들어 보이고 모델을 부르지 않는다.

--focus 는 한 장 시험이다 — 같은 다섯 단계를 돌되 목차 · 편집이 그 소재로 장 하나만 만든다
(호출 5회). 소재 이름만 받는다. 예상 정답 글 · 목차는 받지 않는다(FOCUS_MAX_CHARS).

--analysis-only 는 분석 단계만 따로 본다 — 같은 분석 지시문 · 검사로 호출 1회, 목차 이후는 부르지 않는다.
계약 위반을 모두 모아 남기고 사람이 볼 기억 지도(01_memory_map.md)를 쓴다.

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

# 이 실행기에서만 쓰는 합성 세트. 팀 seed 도구(seed_sessions.SET_IDS = A · B)는 DB 에 넣는
# 도구라 넓히지 않는다 — C 는 DB 에 들어가지 않고 이 실행기로만 돈다.
PIPELINE_SET_IDS = ("C",)


class InputRejected(ValueError):
    """이 도구가 받지 않는 입력. 모델을 부르지 않는다."""


def check_pipeline_seed(doc) -> list[str]:
    """
    seed 검사. A · B 는 팀 도구의 check_seed 그대로다.

    파이프라인 전용 세트(C)는 **같은 check_seed 를 그대로 쓰되** set_id 규칙만 바꿔 끼운다 —
    set_id 를 팀 세트 이름으로, 제목 접두어 「[C] 」를 그에 맞춰 바꾼 사본을 넘긴다. 그
    밖의 검사(schema · user_id · alias · recorded_order · seed · idx · answer · facts)는 한
    줄도 다시 쓰지 않는다. 대신 「합성 자료」 표시(synthetic: true)를 요구한다.
    """
    if not isinstance(doc, dict):
        return ["최상위가 객체가 아니다"]
    set_id = doc.get("set_id")
    if set_id in seed.SET_IDS:
        return seed.check_seed(doc)
    if set_id not in PIPELINE_SET_IDS:
        return [f"set_id 는 {' · '.join(seed.SET_IDS + PIPELINE_SET_IDS)} 중 하나여야 한다 (지금 {set_id!r})"]
    bad = [] if doc.get("synthetic") is True else ["파이프라인 전용 seed 는 synthetic: true 여야 한다"]
    sessions = doc.get("sessions")
    if not isinstance(sessions, list):
        return bad + seed.check_seed(doc)
    stand_in, mine, theirs = seed.SET_IDS[0], f"[{set_id}] ", f"[{seed.SET_IDS[0]}] "
    probe_sessions = []
    for s in sessions:
        if isinstance(s, dict) and isinstance(s.get("title"), str):
            if not s["title"].startswith(mine):
                bad.append(f"{s.get('alias')} 제목이 「{mine}」로 시작하지 않는다")
            s = {**s, "title": theirs + s["title"][len(mine):]} if s["title"].startswith(mine) else s
        probe_sessions.append(s)
    probe = {**doc, "set_id": stand_in, "sessions": probe_sessions}
    return bad + [m.replace(theirs, mine) for m in seed.check_seed(probe)]


def _seed_doc(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputRejected(f"seed 를 읽지 못했다: {path.name} ({e})") from e
    bad = check_pipeline_seed(doc)
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
    if doc["set_id"] not in seed.SET_IDS + PIPELINE_SET_IDS:
        raise InputRejected(f"set_id={doc['set_id']!r} — 합성 seed {seed.SET_IDS + PIPELINE_SET_IDS} 만 받는다")
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


def analysis_only(a, data: dict, turn_map: list[dict], meta: dict, cfg: dict) -> int:
    """--analysis-only — 분석 단계만 1회. 계약 위반 · 경고 · 기억 지도 숫자를 찍는다."""
    print(f"모델 {cfg['MEMOIR_PIPE_TEXT_MODEL']} · 온도 {cfg['MEMOIR_PIPE_TEMPERATURE']} · 재시도 {cfg['retries']} · "
          f"지시문 {pipe.PROMPT_VERSION} · 분석만 · 예상 호출 1회 (출력 상한 {cfg['MEMOIR_PIPE_ANALYSIS_MAX_OUTPUT_TOKENS']})")
    if a.dry_run:
        print("--dry-run — 모델을 부르지 않았다")
        return 0
    meta["run_ref"] += "-analysis"
    folder = a.out_dir / meta["run_ref"]
    r = asyncio.run(pipe.run_analysis_only(data, turn_map, recorder=pipe.Recorder(folder), meta=meta))
    steps = json.loads((folder / "run.json").read_text(encoding="utf-8"))["steps"]
    for s in steps:
        u = s.get("usage") or {}
        print(f"  {s['stage']:<8} {'O' if s['ok'] else 'X'} {s['ms']:>6}ms  출력 {s['out_chars']}자  "
              f"토큰 {u.get('prompt')}/{u.get('output')}/{u.get('thoughts')}  {s.get('finish') or ''}")
    mm = r.get("memory_map") or {}
    print(f"결과 {r['generation_state']} · 계약 통과 {r['analysis_ok']} · 호출 {r['calls']}회 · 사실 {mm.get('facts')} · "
          f"기억 단위 {mm.get('units')} · keep {mm.get('keep')} · 정정 {len(mm.get('corrections') or [])}")
    warn = f"{len(r['warnings'])}건" if r.get("semantic_checks") == "run" else "뜻 검사 미실행"
    print(f"계약 위반 {len(r['diagnostics'])}건 · 경고 {warn} — 기억 지도 {folder / '01_memory_map.md'}")
    for x in r["diagnostics"]:
        print(f"  위반 {x}")
    print(f"기록 {folder}")
    return 0 if r["analysis_ok"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="자서전 5단계 파이프라인을 합성 seed 로 돌린다")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--seed", type=Path, help="합성 seed 파일 (eval/memoir_seed_A.json 등)")
    src.add_argument("--input", type=Path, help="tools/memoir_input.py 출력 (합성 seed 에서 만든 것만)")
    ap.add_argument("--aliases", help="--seed 와 함께. 고를 회차 3~5개, 쉼표 (예: s-a,s-b,s-c)")
    ap.add_argument("--out-dir", type=Path, default=EVAL / "runs")
    ap.add_argument("--dry-run", action="store_true", help="입력만 만들고 모델을 부르지 않는다")
    ap.add_argument("--focus", help=f"한 장 시험 — 소재 이름({FOCUS_MAX_CHARS}자 이하). 다섯 단계 · 호출 5회, 장 1개")
    ap.add_argument("--analysis-only", action="store_true", help="분석 단계만 — 호출 1회, 기억 지도를 남긴다")
    ap.add_argument("--from-analysis", type=Path,
                    help="후속 단계 시험 — 검증된 시험용 분석 스냅샷(reviewed_fixture)에서 시작, 분석을 부르지 않는다")
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
    focus = (a.focus or "").strip() or None
    if focus and (len(focus) > FOCUS_MAX_CHARS or "\n" in focus):
        print(f"입력 거부 — --focus 는 {FOCUS_MAX_CHARS}자 이하 한 줄 소재 이름만 받는다", file=sys.stderr)
        return 2
    if focus and a.analysis_only:
        print("입력 거부 — --focus 와 --analysis-only 는 함께 쓰지 않는다", file=sys.stderr)
        return 2
    if a.analysis_only:
        if a.from_analysis:
            print("입력 거부 — --analysis-only 와 --from-analysis 는 함께 쓰지 않는다", file=sys.stderr)
            return 2
        return analysis_only(a, data, turn_map, meta, cfg)
    fixture = None
    if a.from_analysis:
        try:
            fixture = json.loads(a.from_analysis.read_text(encoding="utf-8"))
            analysis = pipe.load_analysis_fixture(fixture, data, pipe.check_input(data, turn_map))
        except (OSError, ValueError, pipe.PipelineError) as e:
            print(f"입력 거부 — {getattr(e, 'message', e)}", file=sys.stderr)
            return 2
        print(f"분석 출처: 시험용 스냅샷 {a.from_analysis.name} (analysis_source=reviewed_fixture · 바탕 "
              f"{fixture['based_on']['run_ref']} · 고친 항목 {len(fixture['edits'])}) — 사실 {len(analysis['facts'])} · "
              f"기억 단위 {len(analysis['units'])} · 분석 호출 없음")
    extra = 3 if fixture is not None else 4
    calls = (f"{1 + extra}회 (장 1 + {extra})" if focus else
             f"{pipe.MIN_CHAPTERS + extra}~{pipe.MAX_CHAPTERS + extra}회 (장 수 + {extra})")
    print(f"모델 {cfg['MEMOIR_PIPE_TEXT_MODEL']} · 온도 {cfg['MEMOIR_PIPE_TEMPERATURE']} · "
          f"전체 상한 {cfg['MEMOIR_PIPE_TOTAL_TIMEOUT']:.0f}초 · 재시도 {cfg['retries']} · 지시문 {pipe.PROMPT_VERSION} · "
          f"예상 호출 {calls}" + (f" · 한 장 시험 focus「{focus}」" if focus else ""))
    if a.dry_run:
        print("--dry-run — 모델을 부르지 않았다")
        return 0

    if focus:
        meta["run_ref"] += "-focus"
    if fixture is not None:
        meta["run_ref"] += "-fixture"
    folder = a.out_dir / meta["run_ref"]
    result = asyncio.run(pipe.run(data, turn_map, recorder=pipe.Recorder(folder), meta=meta, focus=focus,
                                  analysis_fixture=fixture))
    steps = json.loads((folder / "run.json").read_text(encoding="utf-8"))["steps"]
    for s in steps:
        u = s.get("usage") or {}
        print(f"  {s['stage']:<8} {s.get('chapter_key') or '':<5} {'O' if s['ok'] else 'X'} "
              f"{s['ms']:>6}ms  출력 {s['out_chars']}자  토큰 {u.get('prompt')}/{u.get('output')}/"
              f"{u.get('thoughts')}  {s.get('finish') or ''}")
    v = result["verification"]
    q = result.get("model_quality") or {}
    t = result.get("edit_trace") or {}
    print(f"편집 추적 장 {t.get('draft_chapters')}→{t.get('final_chapters')} · 문장 그대로 {t.get('kept')} · 다시 씀 "
          f"{t.get('rewritten')} · 옮김 {t.get('moved')} · 덜어 냄 {t.get('dropped')} · 구조 변화 {t.get('structure_changed')}")
    print(f"구성 채점(코드 보정 뒤) {q.get('scores')} · 기준 충족 {q.get('meets_bar')}")
    print(f"분석 출처 {result.get('analysis_source')}")
    print(f"판정 code_gate={result.get('code_gate')} · model_verdict={result.get('model_verdict')} · "
          f"human_review={result['human_review']} → overall={result.get('overall')}")
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
FOCUS_MAX_CHARS = 30              # 소재 이름만 — 계획 · 정답 글이 들어오지 않게
MAX_CALLS = pipe.MAX_CHAPTERS + 4

if __name__ == "__main__":
    raise SystemExit(main())
