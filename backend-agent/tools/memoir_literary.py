"""
문학형 자서전 v4 — 편 단위 집필 · 검사 · 조립 · 출력.

    prepare   편마다 집필 자료(원문 · v3 · 사실 원장 · 민감 여부)를 work/bundles 에 쓴다.
    run       Anthropic API 로 아직 없는 편만 집필한다(--confirm-paid, 비용 상한, 체크포인트).
    check     편 원고(work/essays/eXX.json)를 원문 · 원장과 기계 대조한다 → work/checks.json
    assemble  52편을 책으로 묶는다. 없는 편은 v3 를 쓰고 표시한다 → manuscript.md · book.json
    render    book.html · book.pdf(Edge 헤드리스)
    report    comparison.md · fiction_register.md · work/stats.json(v3 대비 분량 · 각색 · 반복)
    pipeline  run(--confirm-paid 일 때) → check → assemble → render, 끝나면 work/status.json

편 원고는 API 실행기든 다른 집필 경로든 같은 JSON 형식(첨부프롬프트 7_문학수필.md)을 따른다.
v3 는 읽기만 한다.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BOOK1 = ROOT / "eval" / "exp" / "book1"
V3 = BOOK1 / "v3"
OUT = BOOK1 / "v4_literary"
WORK = OUT / "work"
CORR = ROOT / "eval" / "exp" / "corrections_split1" / "analysis_corrected.json"
INPUT = ROOT / "eval" / "exp" / "input_59.json"
PROMPT = ROOT / "첨부프롬프트_md" / "파이프라인_통합" / "7_문학수필.md"

MODEL = "claude-opus-5-5"
PRICE = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0)}   # $/1M 입력 · 출력
BUDGET_USD = 60.0

# 지시서가 엄격 규칙을 정한 이야기 + 죽음 · 사고 · 역사적 사건 낱말이 있는 이야기
SENSITIVE_STORIES = {16, 25, 28, 37, 41, 48}
_SENSITIVE_WORD = re.compile(r"죽(었|음|은|고|는)|돌아가(셨|시)|사고(가|를|로|사|였|예|\s?났)|장례|계엄|총을|총소리|빨갱이|북한군|목숨|임종|부고")

NOTICE = "이 책은 인터뷰를 바탕으로 일부 장면과 표현을 문학적으로 재구성한 원고입니다."
STATUS = "문학적 재구성을 포함한 검토용 완성 원고 — 사람 검토 전, 출판 승인 전"

_QUOTE = re.compile(r"\"([^\"]+)\"|“([^”]+)”")
_DIGITS = re.compile(r"\d+")
_HEARD = re.compile(r"다는 것|다는 거|다고|라고|자고|냐고|다며|라며|단다|대서|댔|들었|들은|전해|하더라|말이 돌|소문")
_HEDGE = re.compile(r"쯤|무렵|것\s?같|듯|인지|였을|았을|었을|던가|인가|였나|았나|었나|아마|정도|즈음|기억이|확실하지|남짓|어림|한\s")
# 원문에 없을 때 세기를 바꾸는 강조어(v3 검토 P-01~P-06)
INTENSIFIERS = ["늘", "항상", "언제나", "끊임없이", "도무지", "절대", "한 번도", "매일", "날마다", "평생", "결코", "몹시"]
# 책 전체에서 지나친 반복을 볼 말
WATCH = ["얼마나", "참", "마치", "처럼", "듯", "문득", "가만히", "조용히", "고개를", "지금도", "아직도", "그 시절", "여전히",
         "냄새", "바람", "햇살", "숨을", "한참"]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def jload(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def jdump(p: Path, obj) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def nchars(s: str) -> int:
    """분량 — 공백을 뺀 글자 수."""
    return len(re.sub(r"\s", "", s))


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text) if s.strip()]


# ---------------------------------------------------------------- 자료

def load() -> tuple[dict, dict[int, str], dict[str, dict]]:
    v3 = jload(V3 / "book.json")
    stories = {int(u["turn"]): u["elder"] for u in jload(INPUT)["data"]["utterances"]}
    facts = {f["id"]: f for f in jload(CORR)["analysis"]["facts"]}
    return v3, stories, facts


def essay_list(v3: dict) -> list[dict]:
    out, n = [], 0
    for pi, part in enumerate(v3["parts"], 1):
        for e in part["essays"]:
            n += 1
            out.append({"key": e["key"], "no": n, "part": pi, "part_title": part["title"], "title": e["title"],
                        "stories": e["stories"], "paragraphs": e["paragraphs"]})
    return out


def v3_text(e: dict) -> list[str]:
    return [t for t in (" ".join(x["text"] for x in p if x["text"]) for p in e["paragraphs"]) if t]


def is_sensitive(stories: list[int], texts: dict[int, str]) -> bool:
    return bool(set(stories) & SENSITIVE_STORIES) or any(_SENSITIVE_WORD.search(texts[s]) for s in stories)


def bundle(e: dict, texts: dict[int, str], facts: dict[str, dict]) -> dict:
    fs = [f for f in facts.values() if set(f["turns"]) & set(e["stories"])]
    src = "\n\n".join(texts[s] for s in e["stories"])
    return {"essay_id": e["key"], "no": e["no"], "part": e["part"], "part_title": e["part_title"], "title": e["title"],
            "stories": e["stories"], "sensitive": is_sensitive(e["stories"], texts),
            "source": {str(s): texts[s] for s in e["stories"]}, "source_chars": nchars(src),
            "target_chars": [round(nchars(src) * 2), round(nchars(src) * 3)],
            "v3": v3_text(e),
            "facts": [{"id": f["id"], "text": f["text"], "source": f["source"], "certainty": f["certainty"],
                       "story": f["turns"]} for f in fs]}


def bundle_md(b: dict) -> str:
    L = [f"# {b['essay_id']} 「{b['title']}」 — 제{b['part']}부 {b['part_title']}", "",
         f"- 이야기: {', '.join(map(str, b['stories']))} · 민감: {'true' if b['sensitive'] else 'false'}",
         f"- 원문 {b['source_chars']}자(공백 제외) → 목표 {b['target_chars'][0]}~{b['target_chars'][1]}자", "", "## 원문", ""]
    for s, t in b["source"].items():
        L += [f"### 이야기 {s}", "", t, ""]
    L += ["## v3", ""] + [p + "\n" for p in b["v3"]]
    L += ["## 사실 원장", ""]
    L += [f"- {f['id']} [{f['source']}/{f['certainty']}] {f['text']}" for f in b["facts"]]
    return "\n".join(L) + "\n"


def cmd_prepare(_a) -> int:
    v3, texts, facts = load()
    es = essay_list(v3)
    for e in es:
        b = bundle(e, texts, facts)
        jdump(WORK / "bundles" / f"{e['key']}.json", b)
        (WORK / "bundles" / f"{e['key']}.md").write_text(bundle_md(b), encoding="utf-8")
    jdump(WORK / "plan.json", {"title": v3["title"], "essays": [
        {k: e[k] for k in ("key", "no", "part", "part_title", "title", "stories")} for e in es]})
    print(f"편 {len(es)} · 이야기 {sum(len(e['stories']) for e in es)} · 사실 {len(facts)} → {WORK / 'bundles'}")
    return 0


# ---------------------------------------------------------------- API 실행기

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["essay_id", "title", "paragraphs", "facts", "quotes_kept", "fiction", "notes"],
    "properties": {
        "essay_id": {"type": "string"}, "title": {"type": "string"}, "notes": {"type": "string"},
        "paragraphs": {"type": "array", "items": {"type": "string"}},
        "quotes_kept": {"type": "array", "items": {"type": "string"}},
        "facts": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "where"],
                                             "properties": {"id": {"type": "string"}, "where": {"type": "string"}}}},
        "fiction": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["text", "type", "basis", "risk", "human_check"],
            "properties": {"text": {"type": "string"}, "type": {"type": "string"}, "basis": {"type": "string"},
                           "risk": {"type": "string"}, "human_check": {"type": "boolean"}}}},
    },
}


def cost(model: str, usage: dict) -> float:
    pin, pout = PRICE[model]
    return (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout) / 1e6


def ledger_total(log: list[dict]) -> float:
    return round(sum(x.get("cost_usd", 0) for x in log), 4)


def call_api(client, model: str, system: str, messages: list[dict], effort: str) -> tuple[dict, dict, str, str]:
    """한 번 호출 — 스트리밍, 구조화 출력. (편 JSON, usage, stop_reason, 원문 텍스트)"""
    with client.beta.messages.stream(
        model=model, max_tokens=32000, system=system, messages=messages,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()
    usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}
    text = "".join(b.text for b in msg.content if b.type == "text")
    if msg.stop_reason != "end_turn":
        return {}, usage, msg.stop_reason, text
    return json.loads(text), usage, msg.stop_reason, text


REVISE_ROUNDS = 2   # 검사에 걸린 편을 고쳐 쓰게 하는 횟수 상한
# 고쳐 쓰게 할 경고(사실 · 세기 · 분량). 각색 기록 누락 같은 기록 문제는 고쳐 쓰기까지 하지 않는다.
_FIX_WARN = ("들은 말", "흐린 사실", "원문 직접 인용", "원문에 없는 강조어", "확장률")


def _fix_items(r: dict) -> list[str]:
    return r["errors"] + [w for w in r["warnings"] if w.startswith(_FIX_WARN)]


def _rank(r: dict) -> tuple[int, int]:
    return len(r["errors"]), len(_fix_items(r))


def cmd_run(a, client=None) -> int:
    """아직 없는 편만 순서대로. 쓰고 → 검사 → 걸리면 고쳐 쓰기(REVISE_ROUNDS 번까지) → 가장 나은 판을 저장.
    집필 호출이 실패한 편은 기록하고 다음으로(편마다 집필 2번까지)."""
    if not a.confirm_paid:
        print("유료 호출입니다. --confirm-paid 를 붙여야 실행합니다.")
        return 2
    if client is None:
        import anthropic  # 실행할 때만 필요
        client = anthropic.Anthropic()
    system = PROMPT.read_text(encoding="utf-8")
    logp = WORK / "api_log.json"
    log = jload(logp) if logp.exists() else []

    def over_budget() -> bool:
        spent = ledger_total(log)
        if spent + a.reserve > a.budget:
            print(f"비용 상한 ${a.budget} 에 가까움(누적 ${spent}) — 멈춤")
            return True
        return False

    def call(k: str, kind: str, messages: list[dict]):
        t0 = time.time()
        entry = {"essay": k, "kind": kind, "model": a.model, "at": now()}
        out, text = {}, ""
        try:
            out, usage, stop, text = call_api(client, a.model, system, messages, a.effort)
            entry.update(usage=usage, stop_reason=stop, cost_usd=round(cost(a.model, usage), 4), ok=bool(out))
        except Exception as ex:  # 기록하고 넘어간다
            entry.update(ok=False, error=f"{type(ex).__name__}: {str(ex)[:300]}", cost_usd=0)
        entry["seconds"] = round(time.time() - t0, 1)
        log.append(entry)
        jdump(logp, log)
        return entry, out, text

    keys = a.only.split(",") if a.only else [e["key"] for e in jload(WORK / "plan.json")["essays"]]
    for k in keys:
        dst = WORK / "essays" / f"{k}.json"
        if dst.exists():
            continue
        if sum(1 for x in log if x["essay"] == k and x.get("kind", "write") == "write") >= 2:
            print(f"{k} 두 번 실패 — 검토 대상으로 두고 넘어감")
            continue
        if over_budget():
            break
        b = jload(WORK / "bundles" / f"{k}.json")
        msgs = [{"role": "user", "content": bundle_md(b) + "\n위 자료로 이 편을 집필해 JSON 하나만 출력하세요."}]
        entry, out, text = call(k, "write", msgs)
        if not out:
            print(f"{k} FAIL 누적 ${ledger_total(log)}")
            continue
        r = check_essay(out, b)
        best, best_r, rounds = out, r, 0
        while _fix_items(best_r) and rounds < REVISE_ROUNDS and not over_budget():
            rounds += 1
            msgs = msgs + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "자동 검사에서 아래 문제가 나왔습니다. 집필 규칙을 지키며 고친 편 전체를 "
                                            "같은 JSON 형식으로 다시 출력하세요. 문제 없는 문장은 그대로 두세요.\n"
                                            + "\n".join(f"- {x}" for x in _fix_items(best_r))},
            ]
            entry, out, text = call(k, "revise", msgs)
            if not out:
                break
            r = check_essay(out, b)
            if _rank(r) <= _rank(best_r):
                best, best_r = out, r
        best.update(generator=f"anthropic-api:{a.model}", generated_at=now(), api_revisions=rounds)
        jdump(dst, best)
        print(f"{k} ok 오류 {len(best_r['errors'])} 경고 {len(best_r['warnings'])} ×{best_r['ratio']} "
              f"고쳐쓰기 {rounds} 누적 ${ledger_total(log)}")
    return 0


# ---------------------------------------------------------------- 검사

def check_essay(out: dict, b: dict) -> dict:
    body = "\n".join(out.get("paragraphs", []))
    flat = norm(body)
    src = "\n".join(b["source"].values())
    err, warn = [], []
    if out.get("essay_id") != b["essay_id"]:
        err.append(f"essay_id {out.get('essay_id')} != {b['essay_id']}")
    # 사실 — 원장 전부, 본문 구절과 글자 그대로
    want = {f["id"]: f for f in b["facts"]}
    got = {}
    for x in out.get("facts", []):
        got.setdefault(x["id"], []).append(x["where"])
    for fid, f in want.items():
        if fid not in got:
            err.append(f"사실 {fid} 표시 없음 — {f['text']}")
            continue
        wh = [w for w in got[fid] if norm(w) in flat]
        if not wh:
            err.append(f"사실 {fid} 의 where 가 본문에 없음 — {got[fid][0][:40]}")
            continue
        sent = next((s for s in sentences(flat) if norm(wh[0])[:20] in s), norm(wh[0]))
        if f["source"] == "heard" and not _HEARD.search(sent) and not _HEARD.search(wh[0]):
            warn.append(f"들은 말 {fid} 의 문장에 전언 표지가 없음 — {sent[:70]}")
        if f["certainty"] in ("uncertain", "approx") and not _HEDGE.search(sent):
            warn.append(f"흐린 사실 {fid} 의 문장에 흐림 표지가 없음 — {sent[:70]}")
    extra = sorted(set(got) - set(want))
    if extra:
        err.append(f"이 편의 원장에 없는 사실 id {extra}")
    # 직접 인용 — 원문 인용은 글자 그대로, 원문에 없는 따옴표 대사 금지
    sq = [m.group(1) or m.group(2) for m in _QUOTE.finditer(src)]
    for q in sq:
        if norm(q) not in flat:
            warn.append(f"원문 직접 인용이 그대로 실리지 않음 — \"{q[:50]}\"")
    for m in _QUOTE.finditer(body):
        q = m.group(1) or m.group(2)
        if not any(norm(q) in norm(s) or norm(s) in norm(q) for s in sq):
            err.append(f"원문에 없는 따옴표 대사 — \"{q[:50]}\"")
    # 숫자 — 원문에 없는 숫자
    sd = set(_DIGITS.findall(src))
    for d in sorted(set(_DIGITS.findall(body)) - sd):
        err.append(f"원문에 없는 숫자 {d}")
    for d in sorted(sd - set(_DIGITS.findall(body))):
        warn.append(f"원문 숫자 {d} 가 본문에 없음")
    # 강조어 — 원문에 없는데 새로 들어간 것
    for w in INTENSIFIERS:
        pat = re.compile(rf"(?<![가-힣]){w}(?![가-힣])" if len(w) == 1 else re.escape(w))
        if pat.search(body) and not pat.search(src):
            warn.append(f"원문에 없는 강조어 '{w}'")
    # 각색 기록 — 구절이 본문에 있는지
    fic = out.get("fiction", [])
    for x in fic:
        if norm(x["text"]) not in flat:
            warn.append(f"각색 기록 구절이 본문에 없음 — {x['text'][:40]}")
    if not fic:
        warn.append("각색 기록이 비었다")
    # 반복 · 겹침
    ss = sentences(flat)
    dup = [s for s, c in Counter(ss).items() if c > 1]
    if dup:
        err.append(f"같은 문장 반복 {dup[:3]}")
    chars = nchars(body)
    ratio = round(chars / max(1, b["source_chars"]), 2)
    low = 1.2 if b["sensitive"] else 1.8   # 민감한 편은 경위를 지키느라 덜 늘어나도 된다
    if ratio < low:
        warn.append(f"확장률 {ratio} — 목표({'민감 편 1.2배 이상' if b['sensitive'] else '2~3배'})보다 낮음")
    if ratio > 3.6:
        warn.append(f"확장률 {ratio} — 목표(2~3배)보다 높음")
    return {"essay": b["essay_id"], "ok": not err, "errors": err, "warnings": warn, "chars": chars,
            "source_chars": b["source_chars"], "ratio": ratio, "paragraphs": len(out.get("paragraphs", [])),
            "sentences": len(ss), "fiction": len(fic), "fiction_high": sum(1 for x in fic if x.get("risk") == "높음"),
            "facts": f"{len(set(want) & set(got))}/{len(want)}", "sensitive": b["sensitive"]}


def cmd_check(a) -> int:
    plan = jload(WORK / "plan.json")["essays"]
    keys = a.only.split(",") if a.only else [e["key"] for e in plan]
    res, allsent = [], Counter()
    for k in keys:
        p = WORK / "essays" / f"{k}.json"
        if not p.exists():
            res.append({"essay": k, "ok": False, "missing": True, "errors": ["편 원고 없음"], "warnings": []})
            continue
        out = jload(p)
        r = check_essay(out, jload(WORK / "bundles" / f"{k}.json"))
        res.append(r)
        allsent.update(sentences(norm("\n".join(out["paragraphs"]))))
    cross = [s for s, c in allsent.items() if c > 1 and len(s) > 12]
    summary = {"checked_at": now(), "essays": len(res), "ok": sum(1 for r in res if r["ok"]),
               "errors": sum(len(r["errors"]) for r in res), "warnings": sum(len(r["warnings"]) for r in res),
               "cross_duplicates": cross}
    if not a.only:
        jdump(WORK / "checks.json", {"summary": summary, "essays": res})
    for r in res:
        print(f"{r['essay']} {'OK ' if r['ok'] else 'ERR'} {r.get('chars', '-')}자 ×{r.get('ratio', '-')} "
              f"사실 {r.get('facts', '-')} 각색 {r.get('fiction', '-')}")
        for e in r["errors"]:
            print("   E", e)
        for w in r["warnings"]:
            print("   w", w)
    print(json.dumps({k: v for k, v in summary.items() if k != "cross_duplicates"}, ensure_ascii=False),
          f"책 전체 겹친 문장 {len(cross)}")
    return 0 if all(r["ok"] for r in res) else 1


# ---------------------------------------------------------------- 조립

def collect() -> tuple[dict, list[dict]]:
    """v4 편 원고 + 없는 편은 v3(표시)."""
    plan = jload(WORK / "plan.json")
    v3 = {e["key"]: e for e in essay_list(jload(V3 / "book.json"))}
    out = []
    for e in plan["essays"]:
        p = WORK / "essays" / f"{e['key']}.json"
        if p.exists():
            d = jload(p)
            out.append({**e, "title": d.get("title") or e["title"], "paragraphs": d["paragraphs"], "from": "v4",
                        "generator": d.get("generator", "")})
        else:
            out.append({**e, "paragraphs": v3_text(v3[e["key"]]), "from": "v3"})
    return plan, out


def cmd_assemble(_a) -> int:
    plan, es = collect()
    L = [f"# {plan['title']}", "", f"> {NOTICE}", ">", f"> 상태: {STATUS}", ""]
    part = 0
    for e in es:
        if e["part"] != part:
            part = e["part"]
            L += [f"## 제{part}부 {e['part_title']}", ""]
        mark = " ※ v3 원고(문학형 미완료)" if e["from"] == "v3" else ""
        L += [f"### {e['no']}. {e['title']}{mark}", ""]
        for p in e["paragraphs"]:
            L += [p, ""]
    (OUT / "manuscript.md").write_text("\n".join(L), encoding="utf-8")
    jdump(OUT / "book.json", {"title": plan["title"], "notice": NOTICE, "status": STATUS, "built_at": now(),
                              "essays": es})
    v4n = sum(1 for e in es if e["from"] == "v4")
    print(f"편 {len(es)} (v4 {v4n} · v3 {len(es) - v4n}) · 본문 {sum(nchars(' '.join(e['paragraphs'])) for e in es)}자")
    return 0


# ---------------------------------------------------------------- 출력

CSS = """
:root{--bg:#fbf8f2;--fg:#2a2622;--mut:#7a7066;--line:#e4dccf;--acc:#8a5a2b;--fs:18px}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#1c1a18;--fg:#e9e3d9;--mut:#a59a8c;--line:#3a352f;--acc:#d6a46c}}
:root[data-theme=dark]{--bg:#1c1a18;--fg:#e9e3d9;--mut:#a59a8c;--line:#3a352f;--acc:#d6a46c}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font-family:'Noto Serif KR','Nanum Myeongjo','Batang',serif;
 font-size:var(--fs);line-height:1.95;word-break:keep-all;overflow-wrap:break-word}
article,section,nav.toc{scroll-margin-top:56px}
.wrap{max-width:680px;margin:0 auto;padding:0 16px 120px}
.bar{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);display:flex;gap:8px;
 align-items:center;justify-content:flex-end;padding:8px 16px;font-family:system-ui,'Malgun Gothic',sans-serif;font-size:14px}
.bar a{margin-right:auto;color:var(--acc);text-decoration:none}
.bar button{background:none;border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:4px 10px;font-size:14px;cursor:pointer}
.cover{min-height:88vh;display:flex;flex-direction:column;justify-content:center;text-align:center;padding:40px 0}
.cover h1{font-size:2.1em;line-height:1.4;margin:0 0 .6em;font-weight:700}
.cover .sub{color:var(--mut);font-size:.85em}
.notice{border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:14px 0;margin:48px 0;color:var(--mut);font-size:.82em;line-height:1.8}
nav.toc h2{font-size:1.2em;margin:2em 0 1em}
nav.toc ol{list-style:none;padding:0;margin:0}
nav.toc .p{margin:1.4em 0 .3em;font-weight:700;color:var(--acc);font-size:.92em}
nav.toc a{color:var(--fg);text-decoration:none;display:block;padding:3px 0;font-size:.9em}
nav.toc a:hover{color:var(--acc)}
section.part{text-align:center;padding:22vh 0 12vh}
section.part .n{color:var(--acc);letter-spacing:.2em;font-size:.85em}
section.part h2{font-size:1.6em;margin:.5em 0 0;font-weight:700}
article{margin:0 0 4em}
article h3{font-size:1.3em;margin:2.5em 0 1.4em;font-weight:700;line-height:1.5}
article h3 .no{display:block;color:var(--acc);font-size:.62em;letter-spacing:.15em;margin-bottom:.3em}
article p{margin:0 0 1.15em;text-indent:1em}
.v3mark{font-size:.7em;color:var(--mut);font-weight:400}
.end{text-align:center;color:var(--mut);margin-top:4em}
@media print{
 @page{size:A5;margin:20mm 16mm 20mm 16mm;@bottom-center{content:counter(page);font-family:'Malgun Gothic',sans-serif;font-size:9pt;color:#777}}
 @page:first{@bottom-center{content:none}}
 :root{--bg:#fff;--fg:#111;--mut:#555;--line:#ccc;--acc:#6b4320;--fs:10.5pt}
 body{line-height:1.85}.bar{display:none}.wrap{max-width:none;padding:0}
 .cover{min-height:auto;height:170mm;page-break-after:always}
 .notice{page-break-after:always;margin:40mm 0 0}
 nav.toc{page-break-after:always}nav.toc a{padding:0;font-size:9pt}nav.toc .p{margin:.8em 0 .2em}
 section.part{page-break-before:always;page-break-after:always;padding:55mm 0 0}
 article{page-break-before:always;margin:0}article h3{margin:8mm 0 7mm}
 article p{orphans:2;widows:2}a{color:inherit}
}
"""

JS = """
const r=document.documentElement;
function fs(d){let v=parseFloat(getComputedStyle(r).getPropertyValue('--fs'))||18;v=Math.min(26,Math.max(14,v+d));
 r.style.setProperty('--fs',v+'px');try{localStorage.setItem('fs',v)}catch(e){}}
function th(){const dark=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
 r.dataset.theme=dark?'light':'dark';try{localStorage.setItem('th',r.dataset.theme)}catch(e){}}
try{const v=localStorage.getItem('fs');if(v)r.style.setProperty('--fs',v+'px');const t=localStorage.getItem('th');if(t)r.dataset.theme=t}catch(e){}
"""


def to_html(plan: dict, es: list[dict], for_print: bool = False) -> str:
    esc = html.escape
    title = esc(plan["title"])
    toc, body, part = [], [], 0
    for e in es:
        if e["part"] != part:
            part = e["part"]
            toc.append(f'<li class="p"><a href="#part{part}">제{part}부 {esc(e["part_title"])}</a></li>')
            body.append(f'<section class="part" id="part{part}"><div class="n">제{part}부</div>'
                        f'<h2>{esc(e["part_title"])}</h2></section>')
        mark = ' <span class="v3mark">(v3 원고)</span>' if e["from"] == "v3" else ""
        toc.append(f'<li><a href="#{e["key"]}">{e["no"]}. {esc(e["title"])}</a></li>')
        ps = "".join(f"<p>{esc(p)}</p>" for p in e["paragraphs"])
        body.append(f'<article id="{e["key"]}"><h3><span class="no">{e["no"]}</span>{esc(e["title"])}{mark}</h3>{ps}</article>')
    bar = "" if for_print else ('<div class="bar"><a href="#toc">차례</a><button onclick="fs(-1)" aria-label="글자 작게">가-</button>'
                                '<button onclick="fs(1)" aria-label="글자 크게">가+</button><button onclick="th()">밝게/어둡게</button></div>')
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>{bar}<div class="wrap">
<header class="cover"><h1>{title}</h1><div class="sub">어느 갯마을 사람의 기억 수필 · 8부 52편</div></header>
<div class="notice">{esc(NOTICE)}<br>상태: {esc(STATUS)}</div>
<nav class="toc" id="toc"><h2>차례</h2><ol>{''.join(toc)}</ol></nav>
{''.join(body)}<p class="end">— 끝 —</p></div>{'' if for_print else f'<script>{JS}</script>'}</body></html>"""


EDGE = [Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")]


def cmd_render(_a) -> int:
    book = jload(OUT / "book.json")
    plan = {"title": book["title"]}
    (OUT / "book.html").write_text(to_html(plan, book["essays"]), encoding="utf-8")
    pr = WORK / "book_print.html"
    # 인쇄본은 바깥 글꼴을 쓰지 않는다(Windows 기본 바탕 · 맑은 고딕)
    pr.write_text(to_html(plan, book["essays"], for_print=True).replace(
        '<link href="https://fonts.googleapis.com', '<link data-off="https://fonts.googleapis.com'), encoding="utf-8")
    exe = next((p for p in EDGE if p.exists()), None)
    if not exe:
        print("Edge/Chrome 없음 — PDF 를 만들지 못함")
        return 1
    pdf = OUT / "book.pdf"
    if pdf.exists():
        pdf.unlink()
    # 따로 연 프로필 — 이미 떠 있는 브라우저에 작업이 넘어가 PDF 없이 끝나는 것을 막는다
    prof = Path(tempfile.gettempdir()) / "memoir-v4-pdf-profile"
    r = subprocess.run([str(exe), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={prof}",
                        f"--print-to-pdf={pdf}", pr.resolve().as_uri()], capture_output=True, text=True, timeout=300)
    for _ in range(120):  # Edge 는 띄운 프로세스가 먼저 끝나고 PDF 는 뒤에 나온다
        if pdf.exists() and pdf.stat().st_size > 0:
            time.sleep(2)
            break
        time.sleep(1)
    print("html", (OUT / "book.html").stat().st_size, "pdf", pdf.stat().st_size if pdf.exists() else "없음", r.returncode)
    return 0 if pdf.exists() else 1


def watch_counts(text: str) -> dict[str, int]:
    return {w: len(re.findall(re.escape(w), text)) for w in WATCH}


def cmd_report(_a) -> int:
    plan = jload(WORK / "plan.json")
    v3 = {e["key"]: e for e in essay_list(jload(V3 / "book.json"))}
    checks = {r["essay"]: r for r in jload(WORK / "checks.json")["essays"]} if (WORK / "checks.json").exists() else {}
    rows, fic_md, tot = [], [], Counter()
    v3_all, v4_all = [], []
    for e in plan["essays"]:
        k = e["key"]
        b = jload(WORK / "bundles" / f"{k}.json")
        old = " ".join(v3_text(v3[k]))
        p = WORK / "essays" / f"{k}.json"
        d = jload(p) if p.exists() else None
        new = " ".join(d["paragraphs"]) if d else old
        v3_all.append(old)
        v4_all.append(new)
        fic = d.get("fiction", []) if d else []
        c = checks.get(k, {})
        row = {"key": k, "no": e["no"], "title": e["title"], "stories": e["stories"], "sensitive": b["sensitive"],
               "src": b["source_chars"], "v3": nchars(old), "v4": nchars(new), "from": "v4" if d else "v3",
               "fiction": len(fic), "high": sum(1 for x in fic if x.get("risk") == "높음"),
               "mid": sum(1 for x in fic if x.get("risk") == "중간"), "human": sum(1 for x in fic if x.get("human_check")),
               "types": dict(Counter(x.get("type", "") for x in fic)), "errors": len(c.get("errors", [])),
               "warnings": c.get("warnings", []), "notes": d.get("notes", "") if d else "v4 원고 없음 — v3 사용"}
        rows.append(row)
        for t, n in row["types"].items():
            tot[t] += n
        fic_md += [f"## {e['no']}. {e['title']} ({k} · 이야기 {', '.join(map(str, e['stories']))}"
                   f"{' · 민감' if b['sensitive'] else ''})", ""]
        if not d:
            fic_md += ["v4 원고가 없어 v3 를 실었다(각색 없음).", ""]
            continue
        fic_md += ["**원문에 근거한 부분**: 사실 원장 " + f"{len(b['facts'])}개 — " +
                   "; ".join(f"{x['id']} 「{x['where'][:28]}」" for x in d.get("facts", [])), "",
                   "| # | 창작 · 확장한 본문 구절 | 유형 | 원문 근거 | 왜곡 위험 | 사람 확인 |", "|---|---|---|---|---|---|"]
        for i, x in enumerate(fic, 1):
            cell = lambda v: str(v).replace("|", "/").replace(chr(10), " ")
            fic_md.append(f"| {i} | {cell(x['text'])} | {cell(x['type'])} | {cell(x['basis'])} | {cell(x['risk'])} | "
                          f"{'필요' if x.get('human_check') else '-'} |")
        if d.get("notes"):
            fic_md += ["", f"메모: {d['notes']}"]
        fic_md.append("")
    src_t, v3_t, v4_t = (sum(r[x] for r in rows) for x in ("src", "v3", "v4"))
    stats = {"built_at": now(), "essays": len(rows), "v4_essays": sum(r["from"] == "v4" for r in rows),
             "source_chars": src_t, "v3_chars": v3_t, "v4_chars": v4_t,
             "ratio_v3": round(v3_t / src_t, 2), "ratio_v4": round(v4_t / src_t, 2),
             "fiction": sum(r["fiction"] for r in rows), "fiction_high": sum(r["high"] for r in rows),
             "fiction_mid": sum(r["mid"] for r in rows), "fiction_human": sum(r["human"] for r in rows),
             "fiction_types": dict(tot.most_common()),
             "watch_v3": watch_counts(" ".join(v3_all)), "watch_v4": watch_counts(" ".join(v4_all)), "rows": rows}
    jdump(WORK / "stats.json", stats)
    head = ["# 문학적 각색 기록 — v4", "", f"> {NOTICE} 이 문서는 본문 가운데 무엇이 화자의 실제 구술에 근거하고, "
            "무엇이 문학적으로 더한 표현인지 편마다 적은 것이다.", "",
            f"- 각색 항목 {stats['fiction']}개 — 위험 높음 {stats['fiction_high']} · 중간 {stats['fiction_mid']} · "
            f"사람 확인 표시 {stats['fiction_human']}",
            "- 유형: " + " · ".join(f"{t} {n}" for t, n in tot.most_common()),
            "- '창작 · 확장한 본문 구절'은 본문에 글자 그대로 있다(검사기 대조). '원문 근거'가 '원문에 없음'인 것은 순수한 문학적 연출이다.",
            "- 표에 없는 문장은 원문 내용을 옮기거나 다듬은 것이다. 사실 원장 대조는 각 편 머리의 '원문에 근거한 부분'에 있다.", ""]
    (OUT / "fiction_register.md").write_text("\n".join(head + fic_md), encoding="utf-8")
    L = ["# v3 · v4 비교 — 분량과 각색", "", f"- 원문(구술) {src_t:,}자 → v3 {v3_t:,}자(×{stats['ratio_v3']}) → "
         f"v4 {v4_t:,}자(×{stats['ratio_v4']}). 글자 수는 본문만, 공백 제외.",
         f"- v4 로 새로 쓴 편 {stats['v4_essays']}/{len(rows)}", "",
         "| 편 | 제목 | 이야기 | 원문 | v3 | v4 | v4/원문 | v4/v3 | 각색(높음) | 검사 경고 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['no']} | {r['title']}{' ※민감' if r['sensitive'] else ''}{' ※v3' if r['from'] == 'v3' else ''} | "
                 f"{', '.join(map(str, r['stories']))} | {r['src']} | {r['v3']} | {r['v4']} | ×{r['v4'] / r['src']:.2f} | "
                 f"×{r['v4'] / max(1, r['v3']):.2f} | {r['fiction']}({r['high']}) | {len(r['warnings'])} |")
    L += ["", "## 자주 쓴 말(책 전체 횟수)", "", "| 말 | v3 | v4 |", "|---|---|---|"]
    L += [f"| {w} | {stats['watch_v3'][w]} | {stats['watch_v4'][w]} |" for w in WATCH]
    (WORK / "comparison_table.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "rows"}, ensure_ascii=False))
    return 0


def cmd_pipeline(a) -> int:
    """한 번에 끝까지 — 단계마다 status.json 을 남겨 어디서 멈췄는지 알 수 있게."""
    st = {"started_at": now(), "steps": []}

    def step(name, fn, *x):
        t0 = time.time()
        try:
            rc = fn(*x)
        except Exception as ex:  # 다음 단계로 — 이미 된 결과는 남는다
            rc, st["error"] = 99, f"{name}: {type(ex).__name__}: {ex}"
        st["steps"].append({"step": name, "rc": rc, "seconds": round(time.time() - t0, 1)})
        jdump(WORK / "status.json", st)
        return rc
    if a.confirm_paid:
        step("run", cmd_run, a)
    step("check", cmd_check, argparse.Namespace(only=""))
    step("assemble", cmd_assemble, a)
    step("render", cmd_render, a)
    step("report", cmd_report, a)
    plan = jload(WORK / "plan.json")["essays"]
    done = [e["key"] for e in plan if (WORK / "essays" / f"{e['key']}.json").exists()]
    st.update(finished_at=now(), essays_v4=len(done), essays_total=len(plan),
              complete=len(done) == len(plan) and all(s["rc"] in (0, 1) for s in st["steps"]))
    jdump(WORK / "status.json", st)
    print(json.dumps(st, ensure_ascii=False))
    return 0 if st["complete"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    r = sub.add_parser("run")
    r.add_argument("--confirm-paid", action="store_true")
    r.add_argument("--model", default=MODEL, choices=sorted(PRICE))
    r.add_argument("--effort", default="high")
    r.add_argument("--budget", type=float, default=BUDGET_USD)
    r.add_argument("--reserve", type=float, default=1.5, help="한 편 최대 예상 비용 — 이만큼 남지 않으면 멈춘다")
    r.add_argument("--only", default="")
    c = sub.add_parser("check")
    c.add_argument("--only", default="")
    sub.add_parser("assemble")
    sub.add_parser("render")
    sub.add_parser("report")
    pl = sub.add_parser("pipeline")
    pl.add_argument("--confirm-paid", action="store_true")
    pl.add_argument("--model", default=MODEL, choices=sorted(PRICE))
    pl.add_argument("--effort", default="high")
    pl.add_argument("--budget", type=float, default=BUDGET_USD)
    pl.add_argument("--reserve", type=float, default=1.5)
    pl.add_argument("--only", default="")
    a = ap.parse_args(argv)
    return {"prepare": cmd_prepare, "run": cmd_run, "check": cmd_check, "assemble": cmd_assemble,
            "render": cmd_render, "report": cmd_report, "pipeline": cmd_pipeline}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
