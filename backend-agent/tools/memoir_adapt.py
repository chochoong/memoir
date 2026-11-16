"""
자서전 각색 실험 (단위 8P 뒤 6단계 시험) — 검증을 마친 파이프라인 실행 결과에 장면 · 대사만 입힌다.

    python tools/memoir_adapt.py --run-dir eval/runs/argon/20261030T060013Z-C5-b9f8 --dry-run
    python tools/memoir_adapt.py --run-dir eval/runs/argon/20261030T060013Z-C5-b9f8 --run
    python tools/memoir_adapt.py --run-dir eval/runs/argon/20261030T060013Z-C5-b9f8 --run --prompt v1
    python tools/memoir_adapt.py --run-dir eval/runs/fix_.../...-focus-fixture-outline --run --paragraphs 1-3

사실 판(result.json)은 고치지 않는다. 각색본은 새 폴더에 따로 남고, 문장마다 kind 가 붙는다 —
kept(사실 판 문장) · scene(장면 살리기) · dialogue(대사 재구성). 각색 문장은 각색본.md 에서 표시된다.

받는 것은 tools/memoir_pipeline.py 가 만든 실행 폴더뿐이다(합성 seed 전용 — 00_input.json 이 있어야 한다).
지시문은 공통 지침(자서전_v4.md)을 싣지 않는다 — 공통 지침의 「원문에 없는 장면 금지」가 이 단계의 일과 부딪힌다.
대신 각색이 넘으면 안 되는 선은 각색 지시문(6_각색_v*.md)과 이 도구의 코드 검사(adapt_findings)가 지킨다.

지시문은 --prompt 로 고른다(기본 v2). v1 은 장면을 사실 원장에만 붙이고 상한만 둔다 — 모델이 몸을 사려
각색이 거의 없었다. v2 는 원문 턴의 세부를 장면 재료로 열고(turns 만으로 근거), 문단마다 한 곳 · 5분의 1
하한을 둔다.

호출은 --run 일 때 1회, 재시도 0. 모델은 --model 이 없으면 .env 의 MEMOIR_PIPE_TEXT_MODEL.

종료 코드: 0 호출 성공(검사 결과와 무관 — 사람이 본다) / 1 호출 · 해석 실패 / 2 입력 거부
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
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

# 지시문 판마다: 파일 · 장면 근거로 원문 턴만 받는지 · 각색 문장 하한(지시문 「분량」 절과 같은 값)
PROMPTS = {"v1": {"file": "6_각색_v1.md", "turn_anchor": False, "min_share": None},
           "v2": {"file": "6_각색_v2.md", "turn_anchor": True, "min_share": 1 / 5}}
KINDS = ("kept", "scene", "dialogue")
# 장면 · 대사는 원고 문장의 3분의 1까지 — 지시문 「분량」 절과 같은 값
FICTION_MAX_SHARE = 1 / 3
# 장면 문장의 글자 두 개 묶음 가운데 이웃 원고 문장에도 있는 몫. 이보다 크면 되풀이로 본다 —
# 11-02 각색 실행에서 사람이 좋다고 본 장면은 0.18 이하, 앞 문장을 바꿔 말한 장면은 0.45 이상이었다
RESTATED_OVERLAP = 0.4
# 사실 판보다 표현의 폭이 필요해 파이프라인(0.3)보다 높인다
TEMPERATURE = 0.7
MAX_OUTPUT_TOKENS = 32768
TIMEOUT = 300.0


class InputRejected(ValueError):
    """이 도구가 받지 않는 실행 폴더. 모델을 부르지 않는다."""


def sid(chapter_key: str, p: int, s: int) -> str:
    """검증 단계의 위치 표기와 같은 문장 id — ch-1/p2/s3."""
    return f"{chapter_key}/p{p + 1}/s{s + 1}"


def load_run(folder: Path, analysis_path: Path | None = None) -> dict:
    """실행 폴더에서 사실 판 · 사실 원장 · 원문을 읽는다. 끝까지 돈 실행만 받는다."""
    if not (folder / "00_input.json").exists() or not (folder / "result.json").exists():
        raise InputRejected(f"{folder} 는 tools/memoir_pipeline.py 실행 폴더가 아니다 (00_input.json · result.json)")
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    if not result.get("pipeline_complete") or not result.get("chapters"):
        raise InputRejected(f"끝까지 돈 실행이 아니다 — generation_state {result.get('generation_state')}")
    if analysis_path is None:
        found = sorted(p for p in folder.glob("01_analysis*.json") if ".raw" not in p.name)
        if len(found) != 1:
            raise InputRejected(f"분석 파일을 하나로 못 정했다 {[p.name for p in found]} — --analysis 로 고른다")
        analysis_path = found[0]
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    analysis = analysis.get("analysis", analysis)          # 시험용 스냅샷은 analysis 아래에 있다
    if "facts" not in analysis:
        raise InputRejected(f"{analysis_path.name} 에 facts 가 없다")
    inp = json.loads((folder / "00_input.json").read_text(encoding="utf-8"))
    return {"result": result, "analysis": analysis, "analysis_file": analysis_path.name,
            "utterances": inp["input"]["utterances"], "input_ref": inp["input_ref"]}


def select_paragraphs(run: dict, span: str) -> dict:
    """
    한 장짜리 원고에서 문단 범위(1부터, 양끝 포함)만 남긴다 — 일부만 각색해 볼 때.
    붙여 넣은 글이 아니라 실행 폴더에서 고르므로 문장마다 근거 사실 · 원문 턴이 그대로 따라온다.
    """
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", span)
    chapters = run["result"]["chapters"]
    if not m or len(chapters) != 1:
        raise InputRejected(f"--paragraphs 는 한 장짜리 원고에 1-3 꼴로만 받는다 (장 {len(chapters)}개 · {span!r})")
    lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
    paras = chapters[0]["paragraphs"]
    if not 1 <= lo <= hi <= len(paras):
        raise InputRejected(f"문단 범위 {span} — 이 원고는 문단 {len(paras)}개다")
    chapter = chapters[0] | {"paragraphs": paras[lo - 1:hi]}
    return run | {"result": run["result"] | {"chapters": [chapter]}}


def build(run: dict, prompt: str = "v2") -> tuple[str, str, dict]:
    """(시스템 지시, 사용자 메시지, 검사에 쓸 사실 판 색인). 원문 글자는 바꾸지 않는다."""
    result, analysis = run["result"], run["analysis"]
    sentences: dict[str, dict] = {}
    chapters = []
    for ch in result["chapters"]:
        paras = []
        for p, para in enumerate(ch["paragraphs"]):
            row = []
            for s, x in enumerate(para):
                i = sid(ch["chapter_key"], p, s)
                sentences[i] = x
                row.append({"id": i, "text": x["text"], "facts": x.get("facts") or [], "turns": x.get("turns") or []})
            paras.append(row)
        chapters.append({"chapter_key": ch["chapter_key"], "title": ch["title"]["text"], "paragraphs": paras})
    used_facts = sorted({f for x in sentences.values() for f in x.get("facts") or []}, key=_fact_order)
    used_turns = sorted({t for x in sentences.values() for t in x.get("turns") or []})
    by_turn = {u["turn"]: u for u in run["utterances"]}
    ledger = {f["id"]: f for f in analysis["facts"]}
    # 다른 실행의 원장이 섞여 있으면 id 는 맞아도 내용이 다르다 — 문장의 근거 턴과 사실의 턴이 겹치는지로 가린다
    off = [f"{i}:{f}" for i, x in sentences.items() for f in x.get("facts") or []
           if f not in ledger or not set(ledger[f].get("turns") or []) & set(x.get("turns") or [])]
    if off:
        raise InputRejected(f"분석 원장이 이 원고와 맞지 않는다({run['analysis_file']}) — 어긋난 근거 {len(off)}곳 "
                            f"{off[:3]}. 이 실행의 분석 파일을 --analysis 로 준다")
    exclusions = analysis.get("exclusions") or []
    whole = {t for e in exclusions if e.get("mode") == "whole" for t in e.get("turns") or []}
    payload = {
        "chapters": chapters,
        "facts": [{k: ledger[f].get(k) for k in ("id", "text", "time", "source", "certainty")}
                  for f in used_facts if f in ledger],
        "people": analysis.get("people") or [],
        "corrections": [{"fact": c.get("fact"), "after": c.get("after")} for c in analysis.get("corrections") or []],
        "exclusions": [{"mode": e.get("mode"), "turns": e.get("turns"), "scope": e.get("scope")} for e in exclusions],
        "turns": [{"turn": t, "asked": by_turn[t].get("asked", ""), "elder": by_turn[t]["elder"]}
                  for t in used_turns if t in by_turn and t not in whole],
    }
    system = pipe.role_text("adapt", PROMPTS[prompt]["file"])
    user = json.dumps(payload, ensure_ascii=False)
    index = {"sentences": sentences, "facts": set(used_facts), "ledger": ledger,
             "turns": {t["turn"] for t in payload["turns"]}, "exclusions": exclusions,
             "corrections": analysis.get("corrections") or [], "chapter_keys": [c["chapter_key"] for c in chapters],
             "contract": PROMPTS[prompt]}
    return system, user, index


def _fact_order(f: str) -> tuple[int, str]:
    m = re.fullmatch(r"f(\d+)", f)
    return (int(m.group(1)), f) if m else (10 ** 9, f)


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[\W_]+", "", text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def restated(para: list[dict], s: int) -> float:
    """장면 문장이 바로 앞 · 뒤 문장과 겹치는 몫(0~1) — 원고를 바꿔 말했을 뿐인 장면을 찾는다."""
    mine = _bigrams(para[s].get("text", ""))
    if not mine:
        return 0.0
    return max((len(mine & _bigrams(para[j].get("text", ""))) / len(mine)
                for j in (s - 1, s + 1) if 0 <= j < len(para)), default=0.0)


def parse(text: str) -> dict:
    """응답 JSON — 코드 울타리가 붙어 와도 받는다."""
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    doc = json.loads(body)
    if not isinstance(doc, dict) or not isinstance(doc.get("chapters"), list):
        raise ValueError("chapters 배열이 없다")
    return doc


def adapt_findings(doc: dict, index: dict) -> list[dict]:
    """
    각색본 코드 검사. fix = 각색이 사실 판을 깨뜨린 것, review = 사람이 볼 곳.
    장면 · 대사의 내용이 원문을 벗어났는지는 코드가 판정하지 못한다 — 사람 검수표로 넘긴다.
    """
    out: list[dict] = []
    contract = index.get("contract") or PROMPTS["v1"]

    def add(severity: str, rule: str, where: str, detail: str) -> None:
        out.append({"severity": severity, "rule": rule, "where": where, "detail": detail})

    keys = [c.get("chapter_key") for c in doc["chapters"]]
    if keys != index["chapter_keys"]:
        add("fix", "chapter_order", "-", f"장 순서 · 이름이 사실 판과 다르다 {keys}")
    kept_from: set[str] = set()
    kept_facts: set[str] = set()
    partial = {t for e in index["exclusions"] if e.get("mode") == "partial" for t in e.get("turns") or []}
    whole = {t for e in index["exclusions"] if e.get("mode") == "whole" for t in e.get("turns") or []}
    for ch in doc["chapters"]:
        ck = ch.get("chapter_key")
        total = fiction = 0
        for p, para in enumerate(ch.get("paragraphs") or []):
            for s, x in enumerate(para):
                where = sid(ck, p, s)
                kind, facts, turns, src = x.get("kind"), x.get("facts") or [], x.get("turns") or [], x.get("from") or []
                total += 1
                if kind not in KINDS:
                    add("fix", "bad_kind", where, f"kind {kind!r}")
                    continue
                for f in facts:
                    if f not in index["ledger"]:
                        add("fix", "unknown_fact", where, f)
                for i in src:
                    if i not in index["sentences"]:
                        add("fix", "unknown_from", where, i)
                for t in turns:
                    if t in whole:
                        add("fix", "excluded_turn", where, f"제외된 턴 {t}")
                    elif t not in index["turns"]:
                        add("fix", "unknown_turn", where, f"턴 {t}")
                if kind in ("kept", "dialogue"):
                    kept_from.update(src)
                    kept_facts.update(facts)
                if kind == "kept":
                    continue
                fiction += 1
                # 제외 · 모르는 턴은 근거가 못 된다
                if not facts and not (contract["turn_anchor"] and kind == "scene" and set(turns) & index["turns"]):
                    add("fix", "unanchored", where, f"{kind} 에 붙은 사실" + (" · 원문 턴" if contract["turn_anchor"] else "")
                        + "이 없다")
                if kind == "scene" and restated(para, s) > RESTATED_OVERLAP:
                    add("review", "restated", where, f"앞뒤 문장과 {restated(para, s):.0%} 겹친다 — 장면이 아니라 되풀이인지 본다")
                if kind == "dialogue" and not turns:
                    add("fix", "dialogue_without_turn", where, "대사에 근거 턴이 없다")
                if set(turns) & partial:
                    add("review", "partial_exclusion", where, f"일부 제외 턴 {sorted(set(turns) & partial)} 에 각색을 붙였다")
                heard = [f for f in facts if (index["ledger"].get(f) or {}).get("source") == "heard"]
                if heard:
                    add("review", "heard_dramatized", where, f"들은 이야기 {heard} — 전해 들은 틀이 남았는지 본다")
        if total and fiction / total > FICTION_MAX_SHARE:
            add("review", "fiction_share", ck, f"각색 문장 {fiction}/{total} — 3분의 1을 넘는다")
        if total and contract["min_share"] and fiction / total < contract["min_share"]:
            add("review", "fiction_low", ck, f"각색 문장 {fiction}/{total} — 5분의 1에 못 미친다")
    for i in sorted(set(index["sentences"]) - kept_from):
        add("fix", "sentence_dropped", i, "사실 판 문장이 각색본 어디에도 이어지지 않는다")
    for f in sorted(index["facts"] - kept_facts, key=_fact_order):
        add("fix", "fact_lost", f, "사실 판의 사실이 kept · dialogue 어디에도 없다")
    text = "\n".join(x.get("text", "") for ch in doc["chapters"] for para in ch.get("paragraphs") or [] for x in para)
    for c in index["corrections"]:
        before = (c.get("before") or "").strip()
        if before and before in text:
            add("fix", "pre_correction", c.get("fact") or "-", f"정정 전 값 「{before}」 이 다시 나왔다")
    return out


def render(doc: dict) -> str:
    """각색본.md — 장면은 *기울임*, 대사는 「」 표시를 문단 안에서 그대로 보인다."""
    lines = ["# 각색본 (사실 판 아님)", "",
             "> 장면 살리기 = *기울임* · 대사 재구성 = ⟨대사⟩ 표시. 표시 없는 문장은 검증된 사실 판 문장이다.", ""]
    for ch in doc["chapters"]:
        lines += [f"## {ch.get('title') or ch.get('chapter_key')}", ""]
        for para in ch.get("paragraphs") or []:
            parts = []
            for x in para:
                t = x.get("text", "").strip()
                parts.append(f"*{t}*" if x.get("kind") == "scene" else f"⟨{t}⟩" if x.get("kind") == "dialogue" else t)
            lines += [" ".join(parts), ""]
    return "\n".join(lines)


def review_sheet(doc: dict, index: dict, findings: list[dict], utterances: list[dict]) -> str:
    """각색 문장마다 근거 원문을 나란히 — 판정 칸은 사람이 채운다."""
    by_turn = {u["turn"]: u for u in utterances}
    lines = ["# 각색 검수표 (검수자용)", "",
             "각색 문장마다 근거를 대조한다. 하나라도 있으면 실패다: 새 사건 · 인물 · 인과, 원문에 없는 감정 단정, "
             "대사가 원문의 뜻을 벗어남, 들은 이야기를 직접 본 일처럼, 흐린 기억 확정, 상처 · 별세 대목의 각색.", "",
             "## 코드 검사", ""]
    lines += [f"- [{f['severity']}] {f['rule']} · {f['where']} — {f['detail']}" for f in findings] or ["- 없음"]
    lines += ["", "## 각색 문장", "", "| 위치 | 종류 | 각색 문장 | 근거 사실 | 근거 원문 | 판정 |", "|---|---|---|---|---|---|"]
    for ch in doc["chapters"]:
        for p, para in enumerate(ch.get("paragraphs") or []):
            for s, x in enumerate(para):
                if x.get("kind") == "kept":
                    continue
                facts = "<br>".join(f"{f}: {(index['ledger'].get(f) or {}).get('text', '?')}" for f in x.get("facts") or [])
                turns = "<br>".join(f"턴 {t}: {by_turn[t]['elder']}" for t in x.get("turns") or [] if t in by_turn)
                cell = [sid(ch.get("chapter_key"), p, s), x.get("kind"), x.get("text", ""), facts, turns, ""]
                lines.append("| " + " | ".join(str(c).replace("|", "｜").replace("\n", " ") for c in cell) + " |")
    lines += ["", "## 판정 (사람)", "", "- 장면이 새 사실을 만들었는가:", "- 대사가 원문의 뜻 안에 있는가:",
              "- 전언 · 흐림 · 정정이 지켜졌는가:", "- 각색이 글을 낫게 했는가 (사실 판과 나란히 읽고):", "- 검수자 · 시각:", ""]
    return "\n".join(lines)


def estimate(system: str, user: str, model: str, chapters: int) -> str:
    n_in = round((len(system) + len(user)) / cli.CHARS_PER_TOKEN)
    line = f"입력 약 {n_in:,} 토큰(지시문 {len(system):,}자 + 자료 {len(user):,}자) · 출력 상한 {MAX_OUTPUT_TOKENS:,} · 시간 상한 {TIMEOUT:.0f}초"
    # 원고 전체를 다시 쓰는 일이라 편집 단계 실측으로 어림한다
    sample = (cli.TIME_SAMPLES.get(model) or {}).get("edit")
    line += (f"\n  예상 시간 약 {sample[0] + chapters * sample[1]:.0f}초 — {model} 편집 단계 실측으로 잡은 어림"
             if sample else f"\n  예상 시간 — {model} 실측이 없다")
    price = cli.price_of(model)
    if price:
        cost = [(n_in * price[0] + out * price[1]) / 1e6 for out in (*cli.OUT_GUESS, MAX_OUTPUT_TOKENS)]
        line += (f"\n  예상 비용 {model} — 출력 {cli.OUT_GUESS[0]:,} 이면 ${cost[0]:.3f} · {cli.OUT_GUESS[1]:,} 이면 "
                 f"${cost[1]:.3f} · 상한을 다 쓰면 ${cost[2]:.3f}")
    else:
        line += f"\n  예상 비용 — {model} 단가를 모른다"
    return line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="자서전 각색 실험 — 장면 살리기 · 대사 재구성, 호출 1회")
    ap.add_argument("--run-dir", type=Path, required=True, help="tools/memoir_pipeline.py 실행 폴더")
    ap.add_argument("--analysis", type=Path, help="분석 파일이 여럿이거나 이름이 다를 때")
    ap.add_argument("--model", help="이 실행에만 쓰는 모델 — 없으면 MEMOIR_PIPE_TEXT_MODEL")
    ap.add_argument("--prompt", choices=sorted(PROMPTS), default="v2", help="각색 지시문 판 (기본 v2)")
    ap.add_argument("--paragraphs", help="한 장짜리 원고의 문단 범위만 — 예: 1-3")
    ap.add_argument("--out-dir", type=Path, default=cli.EVAL / "runs")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="입력만 만들고 부르지 않는다")
    mode.add_argument("--run", action="store_true", help="실제 호출 1회")
    a = ap.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    try:
        run = load_run(a.run_dir, a.analysis)
        if a.paragraphs:
            run = select_paragraphs(run, a.paragraphs)
        system, user, index = build(run, a.prompt)
    except (InputRejected, pipe.PipelineError, OSError, ValueError, KeyError) as e:
        print(f"입력 거부 — {getattr(e, 'message', e)}", file=sys.stderr)
        return 2
    model = a.model or pipe.settings()["MEMOIR_PIPE_TEXT_MODEL"]
    src = run["result"]
    print(f"사실 판 {src.get('run_ref')} — 장 {len(index['chapter_keys'])} · 문장 {len(index['sentences'])} · "
          f"사실 {len(index['facts'])} · 원문 턴 {len(index['turns'])} · 분석 {run['analysis_file']} · "
          f"overall {src.get('overall')} · human_review {src.get('human_review')}")
    prompt_file = PROMPTS[a.prompt]["file"]
    print(f"모델 {model} · 온도 {TEMPERATURE} · 호출 1회 · 재시도 0 · 지시문 {prompt_file}")
    print(estimate(system, user, model, len(index["chapter_keys"])))
    if a.dry_run:
        print("--dry-run — 모델을 부르지 않았다")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = re.sub(r"[^a-z0-9]+", "", model.lower().removeprefix("gemini-"))
    part = f"-p{a.paragraphs}" if a.paragraphs else ""
    folder = a.out_dir / f"{stamp}-adapt{a.prompt}-{src.get('run_ref', 'run')}{part}-{short}"
    folder.mkdir(parents=True, exist_ok=True)
    settings = {"model": model, "temperature": TEMPERATURE, "max_output_tokens": MAX_OUTPUT_TOKENS,
                "timeout": TIMEOUT, "retries": 0, "prompt_file": prompt_file}
    (folder / "00_input.json").write_text(json.dumps(
        {"source_run": str(a.run_dir), "source_run_ref": src.get("run_ref"), "paragraphs": a.paragraphs,
         "input_ref": run["input_ref"],
         "system": system, "user": user, "settings": settings}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record = {"source_run_ref": src.get("run_ref"), "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "settings": settings, "calls": 1, "ok": False, "error": None}
    spec = pipe.CallSpec(stage="adapt", chapter_key=None, system=system, user=user, model=model,
                         temperature=TEMPERATURE, max_output_tokens=MAX_OUTPUT_TOKENS)
    t0 = time.monotonic()
    findings: list[dict] = []
    try:
        reply = asyncio.run(asyncio.wait_for(cli.call_any(spec), timeout=TIMEOUT))
        record.update(finish=reply.finish, usage=reply.usage, out_chars=len(reply.text))
        (folder / "06_adapted.raw.txt").write_text(reply.text, encoding="utf-8")
        doc = parse(reply.text)
        findings = adapt_findings(doc, index)
        (folder / "06_adapted.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (folder / "06_adapt_checks.json").write_text(json.dumps(findings, ensure_ascii=False, indent=2) + "\n",
                                                     encoding="utf-8")
        (folder / "각색본.md").write_text(render(doc), encoding="utf-8")
        (folder / "각색_검수표.md").write_text(review_sheet(doc, index, findings, run["utterances"]), encoding="utf-8")
        record["ok"] = True
    except Exception as e:                                                  # noqa: BLE001 — 기록하고 멈춘다
        record["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    record["ms"] = int((time.monotonic() - t0) * 1000)
    record["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (folder / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    u = record.get("usage") or {}
    print(f"호출 1회 {record['ms']}ms · finish {record.get('finish')} · 토큰 {u.get('prompt')}/{u.get('output')}/"
          f"{u.get('thoughts')} · 출력 {record.get('out_chars')}자" + (f" · 실패 {record['error']}" if record["error"] else ""))
    if record["ok"]:
        by: dict[str, int] = {}
        for f in findings:
            by[f"{f['rule']}({f['severity']})"] = by.get(f"{f['rule']}({f['severity']})", 0) + 1
        print(f"코드 검사 {by or '없음'} — 장면 · 대사의 내용은 각색_검수표.md 로 사람이 본다")
    print(f"기록 {folder}")
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
