"""
블라인드 품질 평가 자료를 만든다 (단위 8P). 모델도 DB 도 부르지 않는다.

    python tools/memoir_blind.py --seed eval/memoir_seed_C.json --aliases c1,c2,c3,c4,c5 \\
        --result eval/runs/<v4 실행>/result.json --result eval/runs/<v5 실행>/result.json

**같은 자료(input_ref)의 결과만 견준다.** 결과마다 본문만 꺼내 버전 · 실행 이름 · 근거 턴을
지우고, 무작위 순서로 「글 가 · 나 · 다 …」 이름을 붙인다.

    <out>/평가용/       평가자에게 주는 것 — 글_가.md … · 평가지.md (버전 표시 없음)
    <out>/검수자용/     최종 판단자만 보는 것 — 열쇠.json(이름 → 결과 · 입력 범위) · 사실대조표_<이름>.md
                        (문장마다 근거 턴과 원문 — 사실 검증은 평가와 따로 한다) · 비교조건.md

**입력 범위가 다를 수 있다.** v4 한 장 시험은 사람이 짠 계획(사건 · 순서 · 핵심 턴)으로 장 집필만
모델이 했고, v5 focus 시험은 분석 · 목차부터 모델이 원문 전체에서 골랐다. 같은 원자료라도 장이 받은
턴 · 계획한 주체가 다르다 — 비교조건.md 에 결과마다 적어, 결과 차이를 계약 효과만으로 읽지 않게 한다.

결과는 eval/runs/ 아래(git 제외)에 남긴다. 합성 seed 에서 만든 입력만 받는다.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app.session import memoir_pipeline as pipe                           # noqa: E402
from tools import memoir_pipeline as cli                                  # noqa: E402

LABELS = "가나다라마바"
CRITERIA = (
    ("자연스러움", "문장과 문단이 막힘없이 읽히는가"),
    ("몰입도", "읽는 동안 화자의 이야기에 빠져드는가"),
    ("수필 완성도", "처음 · 중간 · 끝이 있는 한 편의 글인가"),
)


def chapters_of(result: dict) -> tuple[str | None, list[dict]]:
    """결과 → (책 제목, 장 목록). 전체 실행(chapters)과 v4 한 장 시험(draft)을 같은 모양으로."""
    if result.get("chapters"):
        return (result.get("title") or {}).get("text"), result["chapters"]
    if result.get("draft"):
        return None, [result["draft"]]
    raise ValueError("본문이 없는 결과다 (generated 가 아니거나 모양이 다르다)")


def plain_text(title: str | None, chapters: list[dict], label: str) -> str:
    """평가자용 본문 — 근거 · 버전 · 위치 표시 없이 글만."""
    lines = [f"# 글 {label}", ""]
    if title:
        lines += [f"## {title}", ""]
    for ch in chapters:
        lines += [f"### {ch['title']['text']}", ""]
        for para in ch["paragraphs"]:
            lines += [" ".join(x["text"].strip() for x in para), ""]
    return "\n".join(lines)


def fact_sheet(chapters: list[dict], data: dict, label: str) -> str:
    """검수자용 사실대조표 — 문장마다 근거 턴의 원문(질문 · 답)을 붙인다."""
    utt = {u["turn"]: u for u in data["utterances"]}
    lines = [f"# 사실대조표 — 글 {label}", "",
             "문장마다 원문과 대조한다: 지어낸 사건 · 감정 · 인과, 들은 이야기를 기억처럼, 흐린 기억을 확정, "
             "근거 턴 오류. 하나라도 있으면 품질 승인하지 않는다.", "",
             "| 위치 | 문장 | 근거 턴 | 원문 | 판정 |", "|---|---|---|---|---|"]
    for ch in chapters:
        for p, para in enumerate(ch["paragraphs"]):
            for s, x in enumerate(para):
                src = " / ".join(f"[{t}] {utt[t]['elder']}" for t in x.get("turns", []) if t in utt)
                text = x["text"].replace("|", "｜")
                lines.append(f"| {ch['chapter_key']}/p{p}/s{s} | {text} | {x.get('turns', [])} | "
                             f"{src.replace('|', '｜') or '(editorial)'} | |")
    return "\n".join(lines) + "\n"


def input_scope(path: Path, result: dict) -> dict:
    """결과가 어떤 계획 · 입력으로 만들어졌는지 — 실행 폴더의 기록에서 읽는다(본문은 보지 않는다)."""
    folder = path.parent
    def read(name):
        try:
            return json.loads((folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    chapters = chapters_of(result)[1]
    cited = sorted({t for ch in chapters for p in ch["paragraphs"] for x in p for t in x.get("turns", [])})
    run = read("run.json")
    chapter_given = sorted({t for s in run.get("steps", []) if s.get("stage") == "chapter"
                            for t in s.get("given_turns") or []})
    if result.get("mode") == "chapter_trial":
        given = read("00_input.json").get("given_turns") or chapter_given
        how, stages = "사람이 짠 시험 계획(사건 묶음 · 순서 · 핵심 턴)으로 장 집필만 모델", ["chapter"]
    else:
        given = chapter_given
        how = ("모델이 분석 · 목차부터 원문 전체에서 골라 장 하나(focus 소재 이름만 줌)" if result.get("focus")
               else "모델이 분석 · 목차부터 원문 전체를 책으로")
        stages = [s.get("stage") for s in run.get("steps", [])]
    return {"how": how, "model_stages": stages, "chapters": len(chapters),
            "chapter_given_turns": given, "cited_turns": cited}


def scope_note(key: dict) -> str:
    lines = ["# 비교 조건 — 검수자용 (평가자에게 주지 않는다)", "",
             "같은 원자료(input_ref)지만 **만든 방식과 장이 받은 입력 범위가 다르다.** 결과 차이에는 지시문 계약뿐 아니라 "
             "계획을 누가 짰는지 · 장이 무엇을 받았는지가 함께 섞여 있다.", "",
             "| 글 | 버전 | 만든 방식 | 모델 단계 | 장 | 장이 받은 턴 | 본문 근거 턴 |", "|---|---|---|---|---|---|---|"]
    for lab, k in key.items():
        s = k["scope"]
        lines.append(f"| {lab} | {k['prompt_version']} | {s['how']} | {' · '.join(s['model_stages'])} | {s['chapters']} | "
                     f"{len(s['chapter_given_turns'])}개 {s['chapter_given_turns']} | {len(s['cited_turns'])}개 {s['cited_turns']} |")
    return "\n".join(lines) + "\n"


def rating_sheet(labels: list[str]) -> str:
    lines = ["# 평가지", "",
             "같은 사람의 인터뷰로 만든 자서전 글 여러 편입니다. 어느 글이 어떻게 만들어졌는지는 알리지 않았습니다.",
             "원문과 맞는지는 따로 확인하니, **책을 읽는 독자로서** 읽고 적어 주세요.", "",
             "점수는 1(아주 아니다) ~ 5(아주 그렇다).", ""]
    for lab in labels:
        lines += [f"## 글 {lab}", "", "| 항목 | 점수 | 한 줄 이유 |", "|---|---|---|"]
        lines += [f"| {name} — {hint} | | |" for name, hint in CRITERIA]
        lines += ["| 책의 한 장으로 읽히는가 (예 · 아니오) | | |",
                  "| 인터뷰 질문과 답이 느껴지는 곳 (문장을 옮겨 적기) | | |", ""]
    lines += ["## 선호", "", "- 가장 좋은 글부터 순서대로:", "- 이유:", "", "- 평가자 · 날짜:", ""]
    return "\n".join(lines)


def make(results: list[Path], data: dict, out: Path, rng: random.Random) -> dict:
    loaded = []
    for path in results:
        r = json.loads(path.read_text(encoding="utf-8"))
        title, chapters = chapters_of(r)
        loaded.append({"path": str(path), "run_ref": r.get("run_ref"), "input_ref": r.get("input_ref"),
                       "prompt_version": r.get("prompt_version"), "title": title, "chapters": chapters,
                       "scope": input_scope(path, r)})
    refs = {x["input_ref"] for x in loaded}
    if len(refs) != 1 or None in refs or refs != {pipe.input_ref(data)}:
        raise ValueError(f"같은 자료의 결과가 아니다 — input_ref {sorted(map(str, refs))} · 지금 입력 {pipe.input_ref(data)}")
    if len(loaded) > len(LABELS):
        raise ValueError(f"결과는 {len(LABELS)}개까지")
    rng.shuffle(loaded)
    labels = list(LABELS[:len(loaded)])
    (out / "평가용").mkdir(parents=True, exist_ok=True)
    (out / "검수자용").mkdir(parents=True, exist_ok=True)
    key = {}
    for lab, x in zip(labels, loaded):
        (out / "평가용" / f"글_{lab}.md").write_text(plain_text(x["title"], x["chapters"], lab), encoding="utf-8")
        (out / "검수자용" / f"사실대조표_{lab}.md").write_text(fact_sheet(x["chapters"], data, lab), encoding="utf-8")
        key[lab] = {k: x[k] for k in ("path", "run_ref", "prompt_version", "scope")}
    (out / "평가용" / "평가지.md").write_text(rating_sheet(labels), encoding="utf-8")
    (out / "검수자용" / "비교조건.md").write_text(scope_note(key), encoding="utf-8")
    (out / "검수자용" / "열쇠.json").write_text(json.dumps({"input_ref": refs.pop(), "labels": key},
                                                         ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return key


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="블라인드 품질 평가 자료를 만든다")
    ap.add_argument("--seed", type=Path, required=True)
    ap.add_argument("--aliases", required=True)
    ap.add_argument("--result", type=Path, action="append", required=True, help="결과 파일 (두 번 이상)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    if len(a.result) < 2:
        print("결과를 둘 이상 주어야 견줄 수 있다", file=sys.stderr)
        return 2
    try:
        doc = cli._seed_doc(a.seed)
        data, _ = pipe.build_input(cli.records_from_seed(doc, [x.strip() for x in a.aliases.split(",") if x.strip()]))
        out = a.out or cli.EVAL / "runs" / ("blind-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        make(a.result, data, out, random.SystemRandom())
    except (cli.InputRejected, pipe.PipelineError, ValueError, OSError) as e:
        print(f"거부 — {e}", file=sys.stderr)
        return 2
    print(f"평가용 {out / '평가용'} — 평가자에게 이 폴더만 준다")
    print(f"검수자용 {out / '검수자용'} — 열쇠 · 사실대조표 (평가자에게 주지 않는다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
