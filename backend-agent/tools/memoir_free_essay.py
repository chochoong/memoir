"""
자유 산문형 집필 진단 실험 (단위 8P) — 다섯 단계 파이프라인의 대체가 아니다.

    python tools/memoir_free_essay.py --seed eval/memoir_seed_C.json --aliases c1,c2,c3,c4,c5 --dry-run
    python tools/memoir_free_essay.py --seed eval/memoir_seed_C.json --aliases c1,c2,c3,c4,c5 --run

v5 · v6 편집이 책다운 수필에 이르지 못한 까닭이 **글쓰기 계약**(JSON 문장 객체 · 사실 원장 메모 ·
초안)에 있는지 보려고, 같은 Seed C 원문만 주고 모델이 수필을 자유롭게 쓰게 한다.

    준다      큰언니 · 재봉틀과 직접 관련된 원문 턴(번호 · 회차 · 질문 · 어르신 답 그대로), 정정(1985년 봄),
              전언 · 부정 · 불확실성 · 감정을 지키는 규칙, 주제
    안 준다   사실 원장 · 메모 · 요약(shared_state), 목차, Pro 초안 · 편집본, 예상 정답 수필, JSON 계약

호출은 --run 일 때 **딱 1회**, 재시도 0. 응답은 JSON 이 아니라 글 그대로 받는다(response_mime_type 없음).
파이프라인 코드 · 기본 모델 설정은 건드리지 않는다 — 모델 · 온도는 이 도구 안에서만 정한다.
사실 대조는 생성 뒤 사람이 한다(검수자용 대조표).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app.session import memoir_pipeline as pipe                           # noqa: E402
from tools import memoir_pipeline as cli                                  # noqa: E402

PROMPT_FILE = ROOT / "eval" / "free_essay_C_prompt.md"
MODEL = "gemini-3.1-pro-preview"
TEMPERATURE = 1.0
MAX_OUTPUT_TOKENS = 32768
TIMEOUT = 300.0

# 큰언니 · 재봉틀과 직접 관련된 턴 — 목차 r2 의 장이 쓴 원문(장 집필 · v5 · v6 편집과 같은 범위) + 턴 28(부산 첫 방문 ·
# 바다, 편집이 되살린 것). 원문은 고치지 않는다.
TURNS = (2, 3, 4, 10, 11, 12, 13, 14, 15, 17, 21, 25, 26, 27, 28, 29, 34, 35, 36, 38, 39)
# 일부러 뺀 턴 — 33 은 남편의 별세(어르신이 "오늘은 그만할게요"로 멈춘 대목), 나머지는 다른 사람 · 다른 이야기
LEFT_OUT = {33: "남편 별세 — 어르신이 말을 멈춤", 1: "수선집 소개(대전)", 5: "남편 · 혼자 한 가게", 6: "단골 김 사장",
            7: "자녀 운동회", 8: "자녀 대학", 9: "고향 · 오 남매", 16: "첫 월급 · 엄마 편지", 18: "서울 6년 · 결혼",
            19: "좌판", 20: "좌판 실패", 22: "간판", 23: "첫 손님", 24: "첫 천 원", 30: "딸 결혼 드레스",
            31: "드레스 · 아쉬움", 32: "아들", 37: "딸의 책 제안"}
HEAD = ("아래는 한 어르신이 여러 날에 걸친 인터뷰에서 한 말 가운데 「큰언니와 재봉틀」에 관련된 것입니다. "
        "턴 번호와 말은 원문 그대로입니다. '질문'은 인터뷰어의 말이고, '어르신'이 실제로 한 말입니다.")


def build(data: dict) -> tuple[str, str, list[dict]]:
    """(시스템 지시, 사용자 메시지, 고른 턴). 원문 글자는 바꾸지 않는다."""
    by = {u["turn"]: u for u in data["utterances"]}
    missing = [t for t in TURNS if t not in by]
    if missing:
        raise ValueError(f"원문에 없는 턴 {missing}")
    order = {s["session_id"]: s["recorded_order"] for s in data["sessions"]}
    sel = [{"turn": t, "session": order[by[t]["session_id"]], "asked": by[t].get("asked", ""), "elder": by[t]["elder"]}
           for t in TURNS]
    lines = [HEAD, ""]
    for u in sel:
        lines += [f"[턴 {u['turn']} · {u['session']}회차]", f"질문: {u['asked']}", f"어르신: {u['elder']}", ""]
    system = PROMPT_FILE.read_text(encoding="utf-8").strip()
    return system, "\n".join(lines).rstrip() + "\n", sel


def estimate(system: str, user: str) -> str:
    n_in = round((len(system) + len(user)) / cli.CHARS_PER_TOKEN)
    p_in, p_out = cli.PRICES[MODEL]
    cost = [(n_in * p_in + out * p_out) / 1e6 for out in (*cli.OUT_GUESS, MAX_OUTPUT_TOKENS)]
    return (f"입력 약 {n_in:,} 토큰(지시문 {len(system):,}자 + 원문 {len(user):,}자) · 출력 상한 {MAX_OUTPUT_TOKENS:,}(생각 포함) · "
            f"시간 상한 {TIMEOUT:.0f}초\n  예상 비용 {MODEL} — 출력 {cli.OUT_GUESS[0]:,} 이면 ${cost[0]:.3f} · "
            f"{cli.OUT_GUESS[1]:,} 이면 ${cost[1]:.3f} · 상한을 다 쓰면 ${cost[2]:.3f}")


def check_sheet(sel: list[dict], essay: str | None) -> str:
    """검수자용 대조표 — 수필과 원문 턴을 나란히. 판정 칸은 사람이 채운다."""
    lines = ["# 사실 대조표 — 자유 산문 실험 (검수자용)", "",
             "수필의 문장마다 원문과 대조한다. 하나라도 있으면 문학적 완성도와 관계없이 실패다:",
             "원문에 없는 사실 · 들은 이야기를 기억처럼 · 흐린 기억을 확정 · 부정 · 감정 · 인물 관계 바뀜 · 정정 전 값(86년) · "
             "중요한 기억 누락.", "", "## 수필", "", essay or "(아직 없음)", "", "## 원문 턴", "",
             "| 턴 | 회차 | 어르신 | 반영 · 판정 |", "|---|---|---|---|"]
    lines += [f"| {u['turn']} | {u['session']} | {u['elder'].replace('|', '｜')} | |" for u in sel]
    lines += ["", "## 판정 (사람)", "", "- 원문에 없는 사실:", "- 전언 · 직접 기억 구분:", "- 불확실성:",
              "- 부정 · 감정 · 인물 관계:", "- 정정(1985년 봄):", "- 빠진 중요한 기억:", "- 검수자 · 시각:", ""]
    return "\n".join(lines)


async def call_once(system: str, user: str) -> dict:
    """한 번 부른다. 다시 부르지 않는다. 글 그대로 받는다(JSON 강제 없음)."""
    from google.genai import types

    from app.session.question import _client

    client = _client()
    if client is None:
        raise RuntimeError("GEMINI_API_KEY 가 없다")
    cfg = types.GenerateContentConfig(
        system_instruction=system, temperature=TEMPERATURE, max_output_tokens=MAX_OUTPUT_TOKENS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    res = await asyncio.wait_for(client.aio.models.generate_content(model=MODEL, contents=user, config=cfg),
                                 timeout=TIMEOUT)
    cands = getattr(res, "candidates", None) or []
    um = getattr(res, "usage_metadata", None)
    return {"text": res.text or "",
            "finish": str(cands[0].finish_reason) if cands and getattr(cands[0], "finish_reason", None) else None,
            "usage": None if um is None else {k: getattr(um, f"{k}_token_count", None)
                                              for k in ("prompt", "candidates", "thoughts", "total")}}


def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="자유 산문형 집필 진단 실험 — 호출 1회")
    ap.add_argument("--seed", type=Path, required=True)
    ap.add_argument("--aliases", required=True)
    ap.add_argument("--out-dir", type=Path, default=cli.EVAL / "runs")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="입력만 만들고 부르지 않는다")
    mode.add_argument("--run", action="store_true", help="실제 호출 1회")
    a = ap.parse_args(argv)
    try:
        doc = cli._seed_doc(a.seed)
        data, _ = pipe.build_input(cli.records_from_seed(doc, [x.strip() for x in a.aliases.split(",") if x.strip()]))
        system, user, sel = build(data)
    except (cli.InputRejected, pipe.PipelineError, ValueError, OSError) as e:
        print(f"입력 거부 — {e}", file=sys.stderr)
        return 2
    ref = pipe.input_ref(data)
    print(f"입력 {a.seed.name} — input_ref {ref} · 전달 턴 {len(sel)}개 {list(TURNS)} · 뺀 턴 {sorted(LEFT_OUT)}")
    print(f"모델 {MODEL} · 온도 {TEMPERATURE} · 호출 1회 · 재시도 0 · JSON 강제 없음 · 지시문 {PROMPT_FILE.name}")
    print(estimate(system, user))
    if a.dry_run:
        print("--dry-run — 모델을 부르지 않았다")
        return 0

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = a.out_dir / f"{stamp}-C5-{ref[:4]}-free-essay-{MODEL.removeprefix('gemini-').replace('-', '').replace('.', '')}"
    folder.mkdir(parents=True, exist_ok=True)
    settings = {"model": MODEL, "temperature": TEMPERATURE, "max_output_tokens": MAX_OUTPUT_TOKENS,
                "timeout": TIMEOUT, "retries": 0, "response_mime_type": None}
    (folder / "00_input.json").write_text(json.dumps(
        {"input_ref": ref, "turns": list(TURNS), "left_out": LEFT_OUT, "system": system, "user": user,
         "settings": settings}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    t0 = time.monotonic()
    run = {"input_ref": ref, "commit": _commit(), "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "settings": settings, "calls": 1, "ok": False, "error": None}
    try:
        reply = asyncio.run(call_once(system, user))
        run.update(ok=bool(reply["text"].strip()), finish=reply["finish"], usage=reply["usage"],
                   out_chars=len(reply["text"]))
        (folder / "01_essay.raw.txt").write_text(reply["text"], encoding="utf-8")
        (folder / "평가용_수필.md").write_text(reply["text"].strip() + "\n", encoding="utf-8")
        (folder / "검수자용_대조표.md").write_text(check_sheet(sel, reply["text"].strip()), encoding="utf-8")
    except Exception as e:                                                  # noqa: BLE001 — 기록하고 멈춘다
        run["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    run["ms"] = int((time.monotonic() - t0) * 1000)
    run["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (folder / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    u = run.get("usage") or {}
    print(f"호출 1회 {run['ms']}ms · finish {run.get('finish')} · 토큰 {u.get('prompt')}/{u.get('candidates')}/"
          f"{u.get('thoughts')} · 출력 {run.get('out_chars')}자" + (f" · 실패 {run['error']}" if run["error"] else ""))
    print(f"기록 {folder}")
    return 0 if run["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
