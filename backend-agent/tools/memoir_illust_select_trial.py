"""
삽화 장면 선정만 실제 모델로 시험하는 실행기 — 합성 자료의 다섯 항목 (로컬 실험 · 서비스 · DB · API · UI 와 이어져 있지 않다).

    python tools/memoir_illust_select_trial.py --dry-run
    python tools/memoir_illust_select_trial.py --mock-from-cases --out eval/runs/illust-select-trial-C-mock-20261116
    python tools/memoir_illust_select_trial.py --live --out eval/runs/illust-select-trial-C-live-20261116 \
        --confirm <dry-run 의 live_confirm> --env-file <키 파일> --authorized-by <이름> --authorization-note <승인 내용>

**그림을 만들지 않는다.** 이 실행기에는 그림 모델을 부르는 길이 없다 — tools/memoir_illust_image 를 불러오지도 않는다.
그림 지시문(한국어)은 자동 판정 뒤 로컬에서 만들어 image_prompt.txt 로 남길 뿐 아무 데도 보내지 않는다.
결과의 그림 칸은 「선정 전용이라 부르지 않음」(not_requested_select_only)이다 — 그림 생성 실패와 다르다.

- 항목마다 장면 선정 최대 1회 · 전체 최대 5회. 재시도는 끈다(attempts=1). 오류 · 형식 불일치 · 후보 없음이어도 다시 부르지 않는다.
- 부르기 직전에 select_attempt.json 을 남긴다 — 같은 폴더로 다시 돌리면 그 항목은 부르지 않는다
  (저장된 응답이 있으면 판정만 로컬에서 다시 하고, 없으면 「시도했으나 결과 없음」 으로 남긴다).
- 지시문 v5 · 그림 양식 · 판정 코드 · 선정 호출 코드 · 이 실행기 · 시험 기준(기대값) · 합성 자료의 해시를 고정한다.
  하나라도 바뀌면 live_confirm 이 달라져 부르지 않고, 이미 돌린 폴더에는 판정을 다시 쓰지 않는다
  (바뀐 기준으로 같은 시험의 성공을 만들지 않는다 — 재판정은 새 폴더에 따로 한다).
- 받는 자료는 시험 기준 파일에 적힌 그 합성 자료(synthetic: true · 그 해시)뿐이다. 실제 인터뷰 자료는 받지 않는다.
- 평가 기준 · 기대값 · 대조 의견은 AI 가 적은 것이다 — 사람이 확인한 정답이 아니다. 사람 확인 · 사용자 선택 단계는 없다.

평가는 항목마다 여섯 가지를 따로 적는다 — 모델 쪽 ① 중심 제안 ② 중심을 담은 후보 ③ 공동 작업의 참여자 · 행동 근거,
코드 쪽 ④ 적절한 후보를 골랐나 ⑤ 적절한 후보를 잘못 탈락시켰나 ⑥ 주변 소재만 있는 후보를 잘못 통과시켰나.
사람마다 대표성 등급(core · linked · supporting · narrator)과 행동 참여 여부도 따로 적는다.

결과 (--out 아래 · git 제외)

    manifest.json   고정한 파일 해시 · 설정 · live_confirm · 승인 기록 — 첫 실행 때 쓰고 다시 쓰지 않는다
    items/<항목>/   select_request.json · select_attempt.json · select_response.txt(원본 응답) · select_run.json(모델명 · 토큰 · 오류)
                    selection.json(자동 판정 · 선택 이유) · image_prompt.txt(보내지 않은 그림 지시문) · evaluation.json
    items.json · report.md · run.json(이번 실행과 누적 호출 수)

종료 코드: 0 끝남 / 2 조건 거부
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_illust as il            # noqa: E402
from app.session import memoir_illust_book as book     # noqa: E402
from tools import memoir_illust as seltool             # noqa: E402 — 장면 선정 호출(gemini_call) · 키 읽기만 쓴다

RUNS = ROOT / "eval" / "runs"
TRIAL = ROOT / "eval" / "illust_select_trial_C.json"
SELECT_MODEL = "gemini-3.5-flash-lite"
MAX_CALLS = 5
SELECT_CONFIG = {
    "model": SELECT_MODEL, "temperature": 0.2, "response_mime_type": "application/json",
    "max_output_tokens": seltool.LIVE_MAX_OUTPUT_TOKENS, "timeout_ms": seltool.LIVE_TIMEOUT_MS,
    "retries": "off (HttpRetryOptions attempts=1)", "automatic_function_calling": "disabled",
    "thinking": "따로 정하지 않음(모델 기본값) — 앞선 실제 호출 두 번에서 생각 토큰은 기록되지 않았다",
    "call_function": "tools/memoir_illust.py gemini_call (앞선 e01 실제 호출과 같은 설정)",
}
# 공식 단가 — 호출 전에 다시 확인한다. 출력 단가에 생각 토큰이 들어간다
PRICE = {"model": SELECT_MODEL, "tier": "Standard · Paid", "input_usd_per_1m": 0.30, "output_usd_per_1m": 2.50,
         "output_includes_thinking": True, "source": "https://aistudio.google.com/docs/pricing", "checked_at": "2026-11-16"}
# 토큰 어림의 근거 — 같은 모델 · 같은 설정 · 지시문 v5 의 실제 호출 한 번 (e01 · 후보 2개)
USAGE_BASIS = {"run": "illust-book1-e01-auto-live2-20261116", "chars": 4178 + 1186, "prompt_tokens": 2604,
               "output_tokens": 1256, "candidates": 2}
TYPICAL_OUTPUT = 2000          # 후보를 max_scenes(3)개까지 내면 — 위 기록(후보 2개 · 1,256)에서 어림한 값이다
IMAGE_STATE = {"status": "not_requested_select_only", "calls": 0,
               "note": "선정 전용 실행 — 그림 API 를 부르지 않는다. 그림 생성 실패가 아니다"}
FROZEN = {"select_prompt_v5": il.PROMPTS / book.SELECT_FILE, "picture_style": il.PROMPTS / il.STYLE_FILE,
          "judge_book": ROOT / "app" / "session" / "memoir_illust_book.py",
          "judge_core": ROOT / "app" / "session" / "memoir_illust.py",
          "select_call": ROOT / "tools" / "memoir_illust.py", "runner": Path(__file__).resolve()}
AI_NOTE = ("평가 기준 · 기대값 · 대조 의견은 AI(Claude)가 실제 호출 전에 적은 것이다 — 사람이 확인한 정답이 아니다. "
           "결과를 본 뒤 고쳐 같은 시험의 성공으로 세지 않는다.")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise il.IllustError("input", f"{path.name} 을 읽지 못했다 ({type(e).__name__})") from e


def dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha_file(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return "missing"


def rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return p.name


# ---------------------------------------------------------------- 시험 대상 고정

def load_trial(path: Path = TRIAL) -> tuple[dict, dict, dict]:
    """시험 기준 · 합성 자료 · 사례 파일. 자료와 사례가 기준에 적힌 해시와 다르면 거부한다."""
    trial = load(path)
    data_path, cases_path = ROOT / trial["input"]["path"], ROOT / trial["cases"]["path"]
    for p, want in ((data_path, trial["input"]["sha256"]), (cases_path, trial["cases"]["sha256"])):
        if sha_file(p) != want:
            raise il.IllustError("frozen", f"{p.name} 이 시험 기준에 적힌 해시와 다르다 — 고정한 자료가 아니다")
    data, cases = load(data_path), load(cases_path)["chapters"]
    if data.get("synthetic") is not True or data.get("set_id") != trial["input"]["set_id"]:
        raise il.IllustError("input", "합성 자료(synthetic: true · 시험 기준의 set_id)만 받는다")
    targets = trial["targets"]
    if not targets or len(targets) > MAX_CALLS or len(set(targets)) != len(targets):
        raise il.IllustError("cap", f"시험 대상은 서로 다른 1~{MAX_CALLS}개여야 한다 (항목마다 선정 1회)")
    toc = {t["ident"]: t for t in book.toc(data)}
    photos = book.photo_states(data)
    for k in targets:
        if k not in toc or k not in cases or k not in trial["items"]:
            raise il.IllustError("input", f"{k} 가 자료 · 사례 · 기준 가운데 어딘가에 없다")
        if photos[k]["state"] != "no_photo_confirmed":
            raise il.IllustError("input", f"{k} 는 사진이 없는 것이 확인된 항목이 아니다 — 삽화 대상이 아니다")
    return trial, data, cases


def frozen(trial_path: Path, trial: dict) -> dict:
    files = dict(FROZEN, trial=trial_path, cases=ROOT / trial["cases"]["path"], input=ROOT / trial["input"]["path"])
    return {k: {"path": rel(p), "sha256": sha_file(p)} for k, p in files.items()}


def request_for(data: dict, t: dict) -> dict:
    return {"system": book.select_prompt(), "user": il.select_message(data, [t["ident"]]),
            "prompt_file": book.SELECT_FILE, "prompt_hash": book.prompt_hash(), "config": SELECT_CONFIG}


def estimate(rows: list[dict]) -> dict:
    pin, pout = PRICE["input_usd_per_1m"] / 1e6, PRICE["output_usd_per_1m"] / 1e6
    tin = sum(r["estimated_prompt_tokens"] for r in rows)
    typ, top = TYPICAL_OUTPUT * len(rows), SELECT_CONFIG["max_output_tokens"] * len(rows)
    return {"price": PRICE, "basis": USAGE_BASIS,
            "prompt_tokens_estimated": tin,
            "typical": {"output_tokens": typ, "usd": round(tin * pin + typ * pout, 4)},
            "if_every_reply_reaches_max_output_tokens": {"output_tokens": top, "usd": round(tin * pin + top * pout, 4)},
            "image_usd": 0,
            "not_a_cap": ("예상일 뿐 보장된 상한이 아니다 — 입력 토큰은 글자 수로 어림했고, 생각 토큰이 출력 상한(max_output_tokens) "
                          "안에 묶이는지는 확인하지 못했다. 실제 비용은 응답에 기록된 토큰으로 다시 계산해 남긴다")}


def plan(trial_path: Path, trial: dict, data: dict) -> dict:
    toc = {t["ident"]: t for t in book.toc(data)}
    utts = {u["turn"]: u for u in data["source"]["utterances"]}
    rows = []
    for k in trial["targets"]:
        t, req = toc[k], request_for(data, toc[k])
        payload = json.loads(req["user"].split("\n", 1)[1])
        chars = len(req["system"]) + len(req["user"])
        rows.append({"toc_item": k, "chapter_no": t["no"], "title": t["title"],
                     "sentences": sum(len(c["sentences"]) for c in payload["chapters"]),
                     "source_turns": [u["turn"] for u in payload["utterances"]],
                     "elder_chars": sum(len(utts[u["turn"]]["elder"]) for u in payload["utterances"]),
                     "photo_clues": len(payload["photo_clues"]),
                     "system_chars": len(req["system"]), "user_chars": len(req["user"]),
                     "system_sha256": sha_text(req["system"])[:16], "user_sha256": sha_text(req["user"])[:16],
                     "estimated_prompt_tokens": round(chars * USAGE_BASIS["prompt_tokens"] / USAGE_BASIS["chars"])})
    body = {"trial_id": trial["trial_id"], "targets": trial["targets"], "config": SELECT_CONFIG,
            "max_calls": {"select_per_item": 1, "select_total": MAX_CALLS, "image": 0},
            "frozen": frozen(trial_path, trial), "items": rows}
    token = sha_text(json.dumps(body, ensure_ascii=False, sort_keys=True))[:12]
    return {**body, "estimate": estimate(rows), "live_confirm": token}


# ---------------------------------------------------------------- 평가 (AI 가 적은 기준 · 모델 쪽과 코드 쪽을 따로)

_SENT = re.compile(r"(?<=[.?!])\s+")
_PAREN = re.compile(r"\s*\(.*?\)")


def _cover(ref: str, text: str) -> float:
    a = il._bigrams(ref)
    return len(a & il._bigrams(text)) / len(a) if a else 0.0


def _overlap(a: str, b: str) -> float:
    x, y = il._bigrams(a), il._bigrams(b)
    return len(x & y) / min(len(x), len(y)) if x and y else 0.0


def _quote_ok(e: dict, utt: dict) -> bool:
    q = il._compact(e.get("quote") or "")
    return len(q) >= il.QUOTE_MIN and q in il._compact(utt.get(e.get("turn"), ""))


def _same_person(text: str, who: str) -> bool:
    return il.is_self(text) if who == "SELF" else il._compact(text) == il._compact(who)


def _mentions(sentence: str, who: str) -> bool:
    return bool(il._SELF_IN_QUOTE.search(sentence)) if who == "SELF" else il._compact(who) in il._compact(sentence)


def center_refs(case: dict, rub: dict) -> list[dict]:
    """중심 요소 — 사례 파일의 center_elements + 기준의 also_center(따로 표시) + 행동 열쇠말(행동 요소에만)."""
    return ([dict(r, origin="center") for r in case["center_elements"]]
            + [dict(r, origin="also") for r in rub.get("also_center", [])]
            + [{"kind": "action_keyword", "text": w, "origin": "keyword"} for w in rub.get("center_action_keywords", [])])


def _center_hits(e: dict, center: list[dict]) -> list[str]:
    return [r["text"] for r in _center_refs_hit(e, center)]


def _center_refs_hit(e: dict, center: list[dict]) -> list[dict]:
    a = il._compact(e["text"])
    out = []
    for r in center:
        b = il._compact(r["text"])
        if e["kind"] == "person" or r["kind"] == "person":
            ok = e["kind"] == r["kind"] == "person" and a == b
        elif r["kind"] == "action_keyword":
            ok = e["kind"] == "action" and b in a
        elif r["kind"] == "action":
            ok = e["kind"] == "action" and _overlap(r["text"], e["text"]) >= il.PARAPHRASE_COVER
        else:
            ok = b in a or (e["kind"] == r["kind"] and len(a) >= 2 and a in b)
        if ok:
            out.append(r)
    return out


def _central(c: dict) -> dict | None:
    key = c.get("central_action")
    acts = [e for e in c["elements"] if e["kind"] == "action"]
    return next((e for e in acts if key is not None and e.get("key") == key), acts[0] if acts else None)


def classify(c: dict, rub: dict, case: dict, utt: dict, *, derived: bool = False) -> dict:
    """모델 후보 하나(derived 면 그 후보의 사물 · 장소만)가 기준으로 적절한가 — 코드의 판정을 쓰지 않는다."""
    center = center_refs(case, rub)
    peripheral = [_PAREN.sub("", p["text"]) for p in case["peripheral"]]
    els = [e for e in c["elements"] if not derived or e["kind"] in ("object", "place", "time")]
    bad_quotes = [e["text"] for e in els if not _quote_ok(e, utt)]
    real = [e for e in els if _quote_ok(e, utt)]
    refs = {e["text"]: h for e in real if e["kind"] != "person" and (h := _center_refs_hit(e, center))}
    hits = {t: [r["text"] for r in h] for t, h in refs.items()}
    person_hits = [e["text"] for e in real if e["kind"] == "person" and _center_hits(e, center)]
    periph = [e["text"] for e in real if any(il._compact(p) and (il._compact(p) in il._compact(e["text"])
                                                                 or il._compact(e["text"]) in il._compact(p)) for p in peripheral)]
    kind = ("center" if hits else "center_person_only" if person_hits else "peripheral_only" if periph else "no_center")
    people = [] if derived else participants(c, rub, utt, center)
    problems = []
    if kind != "center":
        problems.append({"center_person_only": "중심 사람만 있고 중심 사물 · 행동이 없다", "peripheral_only": "주변 소재만 담았다",
                         "no_center": "중심 요소를 담지 않았다"}[kind])
    if people and people.get("applies") and not people["ok"]:
        problems += people["problems"]
    return {"kind": kind, "center_hits": hits,
            "only_also_center": bool(refs) and all(r["origin"] == "also" for h in refs.values() for r in h),
            "peripheral": periph, "quotes_not_in_source": bad_quotes, "participants": people or None,
            "appropriate": kind == "center" and not (people and people.get("applies") and not people["ok"]),
            "problems": problems}


def participants(c: dict, rub: dict, utt: dict, center: list[dict]) -> dict:
    """
    사람을 그리는 후보 — 그 후보의 중심 행동이 이 목차의 중심 행동일 때만 본다(주변 인물이 제 할 일을 하는 장면은 여기서 따지지 않는다).
    공동 작업의 참여자가 다 있고 각자의 근거가 행동까지 받치는가. 주변 인물을 중심 행동의 주인공으로 넣지 않았는가.
    """
    persons = [e for e in c["elements"] if e["kind"] == "person"]
    if not persons:
        return {}
    joint = rub.get("joint_action")
    act = _central(c)
    act_center = bool(act) and bool(_center_hits(act, center))
    non =(joint or {}).get("non_participants", []) + rub.get("non_participants_of_center", [])
    rows, problems = [], []
    for e in persons:
        r = e.get("relation") or {}
        ev = [v for v in r.get("evidence") or [] if isinstance(v, dict)]
        quotes = [v.get("quote") or "" for v in ev]
        in_center = bool(act) and r.get("action") == act.get("key") and r.get("role") in ("actor", "co_actor")
        who = "SELF" if il.is_self(e["text"]) else e["text"]
        text = utt.get(e.get("turn"), "")
        rows.append({"text": e["text"], "role": r.get("role"), "acts_in_central_action": in_center,
                     "evidence": quotes, "evidence_in_source": bool(ev) and all(_quote_ok(v, utt) for v in ev),
                     "evidence_covers_action": bool(act) and _cover(act["text"], "".join(quotes)) >= il.PARAPHRASE_COVER,
                     "source_sentence_supports": bool(act) and any(_mentions(s, who) and _cover(act["text"], s) >= il.PARAPHRASE_COVER
                                                                   for s in _SENT.split(text)),
                     "non_participant": any(_same_person(e["text"], n) for n in non)})
    out = {"applies": False, "central_action_is_center": act_center, "people": rows, "problems": problems, "ok": True}
    if not act_center:
        return out
    for row in rows:
        if row["non_participant"] and row["acts_in_central_action"]:
            problems.append(f"주변 인물 {row['text']} 을 중심 행동의 주인공으로 그렸다")
    out["ok"] = not problems
    if joint:
        out["applies"] = True
        for who in joint["participants"]:
            row = next((x for x in rows if _same_person(x["text"], who)), None)
            name = "화자" if who == "SELF" else who
            if row is None:
                problems.append(f"공동 작업의 참여자 {name} 이 빠졌다")
            elif not row["acts_in_central_action"]:
                problems.append(f"{name} 이 중심 행동의 actor · co_actor 로 이어지지 않았다")
            elif not row["evidence_in_source"]:
                problems.append(f"{name} 의 근거 인용이 원문에 없다")
            elif not (row["evidence_covers_action"] or row["source_sentence_supports"]):
                problems.append(f"{name} 이 그 행동을 했다는 원문 근거가 없다")
        out["ok"] = not problems
    elif non:
        out["applies"] = bool(problems)
    return out


def _model_focus(focus: dict | None, case: dict, rub: dict) -> dict:
    if focus is None:
        return {"verdict": "없음", "detail": "응답에 focus 가 없거나 모양이 다르다"}
    center = center_refs(case, rub)
    peripheral = [_PAREN.sub("", p["text"]) for p in case["peripheral"]]
    core = focus["core"]
    hit = sorted({h for e in core if e["kind"] != "person" for h in _center_hits(e, center)})
    person = sorted({h for e in core if e["kind"] == "person" for h in _center_hits(e, center)})
    wrong = [e["text"] for e in core if not _center_hits(e, center)
             and any(il._compact(p) in il._compact(e["text"]) or il._compact(e["text"]) in il._compact(p) for p in peripheral)]
    missing = [r["text"] for r in case["center_elements"] if r["text"] not in hit + person]
    verdict = ("맞음" if hit and not wrong else "일부" if hit or person else "어긋남")
    return {"verdict": verdict, "core_proposed": [f"{e['kind']} {e['text']}" for e in core],
            "background_proposed": [f"{e['kind']} {e['text']}" for e in focus["background"]],
            "matched_center": hit + person, "peripheral_as_core": wrong, "center_not_proposed": missing}


def evaluate(data: dict, trial: dict, cases: dict, k: str, reply: str | None, sel: dict) -> dict:
    rub, case = trial["items"][k], cases[k]
    utt = {u["turn"]: u["elder"] for u in data["source"]["utterances"]}
    cands, fmt_error = [], None
    if reply is not None:
        try:
            cands = il.check_candidates(reply)
        except il.IllustError as e:
            fmt_error = e.message
    focus = book.parse_focus(reply) if reply is not None and fmt_error is None else None
    judged = [classify(c, rub, case, utt) for c in cands]

    # ── 모델 쪽 (코드의 판정과 섞지 않는다)
    m1 = (_model_focus(focus, case, rub) if reply is not None and fmt_error is None
          else {"verdict": "응답 없음" if reply is None else "형식 오류", "detail": fmt_error})
    with_center = [i for i, j in enumerate(judged) if j["kind"] == "center"]
    m2 = {"verdict": "예" if with_center else ("응답 없음" if reply is None else "형식 오류" if fmt_error else "아니오"),
          "candidates_with_center": with_center,
          "per_candidate": [{"index": i, "scene_title": c["scene_title"], "kind": j["kind"], "center_hits": j["center_hits"],
                             "peripheral": j["peripheral"], "quotes_not_in_source": j["quotes_not_in_source"]}
                            for i, (c, j) in enumerate(zip(cands, judged))]}
    joint = rub.get("joint_action")
    scenes = [(i, j["participants"]) for i, j in enumerate(judged) if j["participants"] and j["kind"] == "center"
              and any(p["acts_in_central_action"] for p in j["participants"]["people"])]
    if reply is None or fmt_error:
        m3 = {"verdict": m2["verdict"], "problems": []}
    elif not joint:
        bad = [(i, p) for i, j in enumerate(judged) if (p := j["participants"]) and p["problems"]]
        m3 = {"verdict": "해당 없음 (공동 작업 항목이 아니다)" if not bad else "주변 인물을 주인공으로 그림",
              "problems": [f"후보 {i}: " + "; ".join(p["problems"]) for i, p in bad]}
    elif not scenes:
        m3 = {"verdict": "공동 작업을 사람으로 그린 후보가 없다", "problems": ["중심 행동을 사람으로 그린 후보를 내지 않았다"]}
    else:
        m3 = {"verdict": "빠뜨림 없음" if any(p["ok"] for _, p in scenes) else "빠뜨림 · 근거 부족",
              "problems": [f"후보 {i}: " + "; ".join(p["problems"]) for i, p in scenes if p["problems"]],
              "scenes":[{"index": i, "ok": p["ok"], "problems": p["problems"], "people": p["people"]} for i, p in scenes],
              "evidence_cut_short": [f"후보 {i}: {x['text']}" for i, p in scenes for x in p["people"]
                                     if x["evidence_in_source"] and not x["evidence_covers_action"] and x["source_sentence_supports"]]}

    # ── 코드 쪽
    rows = []
    for r in sel.get("comparison") or []:
        j = classify(cands[r["candidate_index"]], rub, case, utt, derived=r["source"] == "derived_symbolic")
        rows.append({"source": r["source"], "candidate_index": r["candidate_index"], "scene_title": r["scene_title"],
                     "mode": r["mode"], "code_accepted": r["accepted"], "code_represents": r["represents"],
                     "code_blocking": r["blocking"], "chosen": r["chosen"], "appropriate": j["appropriate"],
                     "rubric_kind": j["kind"], "rubric_problems": j["problems"], "only_also_center": j["only_also_center"],
                     "code_reason": r["reason"]})
    chosen = next((x for x in rows if x["chosen"]), None)
    kl = rub.get("known_limit")

    def limit_of(x: dict) -> str | None:
        """이 탈락이 미리 적어 둔 알려진 한계에 해당하는가."""
        if not kl:
            return None
        hit = {"always": True, "focus_core_missing": m1.get("verdict") in ("없음", "어긋남"),
               "only_also_center": x["only_also_center"]}[kl["when"]]
        return kl["case"] if hit else None

    wrong_reject = []
    for x in rows:
        if chosen and chosen["appropriate"] and x["source"] == "derived_symbolic":
            continue                              # 적절한 것을 골랐으면 코드가 만든 견줄 거리(사람을 뺀 그림)의 탈락은 세지 않는다
        if x["appropriate"] and not x["chosen"] and not (x["code_accepted"] and x["code_represents"]):
            why = ("중심 판정 — 코드가 중심을 담지 않는다고 봤다" if x["code_accepted"]
                   else "형식 검사 — " + ", ".join(x["code_blocking"]))
            effect = ("항목이 실패했다" if sel["status"] != "selected" else
                      "사람을 뺀 그림으로 바뀌었다" if chosen and chosen["source"] == "derived_symbolic"
                      and chosen["candidate_index"] == x["candidate_index"] else
                      "영향 없음 — 다른 적절한 후보가 골라졌다" if chosen and chosen["appropriate"] else "다른 후보가 골라졌다")
            wrong_reject.append({"source": x["source"], "candidate_index": x["candidate_index"], "scene_title": x["scene_title"],
                                 "why": why, "effect": effect, "known_limit": limit_of(x)})
    c4 = ("예" if chosen and chosen["appropriate"] else "아니오 — 골랐지만 기준에 맞지 않는다" if chosen
          else "선택 없음 — 적절한 후보가 없었다 (코드 탓 아님)" if not any(x["appropriate"] for x in rows)
          else "아니오 — 적절한 후보가 있었는데 실패했다")
    c6 = ([{"scene_title": chosen["scene_title"], "kind": chosen["rubric_kind"], "problems": chosen["rubric_problems"]}]
          if chosen and not chosen["appropriate"] else [])

    # ── 사람 — 대표성 등급과 행동 참여를 따로
    tiers = sel.get("focus")
    people = []
    for i, (c, j) in enumerate(zip(cands, judged)):
        for p in (j["participants"] or {}).get("people", []):
            e = next(x for x in c["elements"] if x["kind"] == "person" and x["text"] == p["text"])
            t = book._tier(tiers, e) if tiers else None
            people.append({"candidate_index": i, "text": p["text"], "tier": (t or {}).get("tier"),
                           "role": p["role"], "acts_in_central_action": p["acts_in_central_action"],
                           "required_participant": any(_same_person(p["text"], w) for w in (joint or {}).get("participants", []))})
    dropped_by_tier = [f"후보 {x['candidate_index']} ({x['scene_title']})" for x in rows
                       if x["source"] == "candidate" and x["mode"] == "SCENE" and x["code_accepted"] and not x["code_represents"]
                       and any(p["candidate_index"] == x["candidate_index"] and p["required_participant"] for p in people)]
    if chosen and chosen["source"] == "derived_symbolic" and any(
            x["source"] == "candidate" and x["candidate_index"] == chosen["candidate_index"] and x["code_accepted"] for x in rows):
        dropped_by_tier.append(f"후보 {chosen['candidate_index']} — 사람 장면이 통과했는데 사람을 뺀 그림이 골라졌다")

    # ── 알려진 한계 · 문제의 자리
    hits = sorted({w["known_limit"] for w in wrong_reject if w["known_limit"] and not w["effect"].startswith("영향 없음")})
    limit = {"case": kl["case"], "text": kl["text"]} if kl and hits else None
    model_problems, run_problems = [], []
    if reply is None:
        run_problems.append("응답 없음 — " + ", ".join(sel.get("reasons") or []) + " (다시 부르지 않았다)")
    elif m1["verdict"] not in ("맞음",):
        model_problems.append(f"중심 제안: {m1['verdict']}")
    if reply is not None and m2["verdict"] != "예":
        model_problems.append(f"중심을 담은 후보: {m2['verdict']}")
    if m3.get("problems") and m3["verdict"] not in ("빠뜨림 없음",) and not m3["verdict"].startswith("해당 없음"):
        model_problems.append(f"참여자 · 근거: {m3['verdict']}")
    code_problems, code_notes = [], []
    for w in wrong_reject:
        line = (f"[알려진 한계 {w['known_limit']}] " if w["known_limit"] else "") + \
               f"잘못 탈락 — {w['scene_title']} ({w['why']} · {w['effect']})"
        (code_notes if w["effect"].startswith("영향 없음") else code_problems).append(line)
    for w in c6:
        code_problems.append(f"잘못 통과 — {w['scene_title']} ({', '.join(w['problems'])})")
    for d in dropped_by_tier:
        code_problems.append(f"사람 장면이 대표성 등급 때문에 빠짐 — {d}")
    return {
        "written_by": AI_NOTE, "toc_item": k, "center_expected": case["center"],
        "expect": rub["expect"], "known_limit": kl,
        "model": {"q1_center_proposed": m1, "q2_candidate_with_center": m2, "q3_participants_and_evidence": m3},
        "code": {"status": sel["status"], "reasons": sel.get("reasons"),
                 "chosen": ({k2: chosen[k2] for k2 in ("source", "candidate_index", "scene_title", "mode")} if chosen else None),
                 "q4_chose_appropriate": c4, "q5_wrongly_rejected": wrong_reject, "q6_wrongly_passed": c6,
                 "candidates": rows},
        "people_tier_vs_participation": {"rows": people, "scene_dropped_by_tier": dropped_by_tier,
                                         "note": "대표성 등급은 그림이 목차를 대표하는지 잴 때만 쓴다 — 사람을 장면에서 빼는 데 쓰지 않는다"},
        "known_limit_hit": limit,
        "model_problems": model_problems, "code_problems": code_problems, "run_problems": run_problems,
        "code_notes_no_effect": code_notes,
    }


# ---------------------------------------------------------------- 실행

def _check_manifest(out: Path, p: dict, mock: bool) -> dict | None:
    m_path = out / "manifest.json"
    if not m_path.is_file():
        return None
    m = load(m_path)
    if bool(m.get("mock")) != mock:
        raise il.IllustError("mode", f"이 폴더는 {'모의' if m.get('mock') else '실제'} 실행의 것이다 — "
                                     f"{'실제' if m.get('mock') else '모의'} 실행에 다시 쓸 수 없다. 새 --out 을 쓴다")
    if m.get("frozen") != p["frozen"] or m.get("live_confirm") != p["live_confirm"]:
        changed = sorted(k for k in p["frozen"] if (m.get("frozen") or {}).get(k) != p["frozen"][k])
        raise il.IllustError("frozen", "이 폴더의 시험을 시작한 뒤 고정한 것이 바뀌었다(" + (", ".join(changed) or "보낼 자료") + ") — "
                                       "같은 폴더에 다시 판정하지 않는다. 바뀐 기준으로 같은 시험의 성공을 만들지 않는다 — 재판정은 새 --out 에 따로 한다")
    return m


def run(trial_path: Path, trial: dict, data: dict, cases: dict, out: Path, *, call, mock: bool,
        authorization: dict | None = None) -> tuple[list[dict], dict]:
    """
    다섯 항목을 차례로 — 항목마다 선정을 많아야 한 번 부르고, 판정 · 그림 지시문 · 평가는 로컬에서 한다.
    call(system, user) 은 장면 선정 자리다(글 또는 {text, …실행 정보}). 그림을 부르는 자리는 없다.
    """
    p = plan(trial_path, trial, data)
    if _check_manifest(out, p, mock) is None:
        out.mkdir(parents=True, exist_ok=True)
        dump(out / "manifest.json", {"trial_id": trial["trial_id"], "mock": mock, "created_at": now(),
                                     "live_confirm": p["live_confirm"], "frozen": p["frozen"], "config": SELECT_CONFIG,
                                     "targets": trial["targets"], "max_calls": p["max_calls"], "authorization": authorization,
                                     "written_by": AI_NOTE, "image": IMAGE_STATE})
    toc = {t["ident"]: t for t in book.toc(data)}
    calls = {"select": 0, "image": 0}
    items = []
    for k in trial["targets"]:
        t, folder = toc[k], out / "items" / k
        folder.mkdir(parents=True, exist_ok=True)
        attempt, resp, runf = folder / "select_attempt.json", folder / "select_response.txt", folder / "select_run.json"
        it = {"ident": k, "chapter_no": t["no"], "title": t["title"], "run_mode": "select_only",
              "image": dict(IMAGE_STATE), "automatic": True, "user_selected": False, "user_approved": False}
        reply, meta = None, None
        if attempt.is_file():                     # 앞선 실행이 이미 불렀다 — 다시 부르지 않는다
            meta = load(runf) if runf.is_file() else load(attempt)
            if resp.is_file():
                reply, it["select_call"] = resp.read_text(encoding="utf-8"), "not_called_reused_saved_response"
            else:
                it["select_call"] = ("not_called_previous_error" if meta.get("failure")
                                     else "not_called_attempted_without_result")
        else:
            if calls["select"] >= MAX_CALLS:      # 대상이 MAX_CALLS 를 넘지 않으므로 오지 않는다 — 그래도 막는다
                raise il.IllustError("cap", f"이번 실행의 장면 선정이 {MAX_CALLS}회에 닿았다")
            req = request_for(data, t)
            dump(folder / "select_request.json", req)
            meta = {"mock": mock, "started_at": now(), "call": 1, "prompt_file": req["prompt_file"],
                    "prompt_hash": req["prompt_hash"], "model_requested": "mock" if mock else SELECT_MODEL}
            dump(attempt, meta)                   # 부르기 직전에 — 중간에 멈춰도 다시 부르지 않게
            calls["select"] += 1
            try:
                res = call(req["system"], req["user"])
            except Exception as e:                # noqa: BLE001 — 다시 부르지 않는다
                meta.update(finished_at=now(), failure={"type": type(e).__name__,
                                                       "http_status": getattr(e, "status_code", None) or getattr(e, "code", None)})
                it["select_call"] = "called_error"
            else:
                if isinstance(res, dict):         # 실제 호출 — 글과 함께 실제 모델 판 · 응답 식별자 · 토큰이 온다
                    meta.update({x: v for x, v in res.items() if x != "text"})
                    res = res.get("text") or ""
                meta["finished_at"] = now()
                resp.write_text(res, encoding="utf-8")
                reply, it["select_call"] = res, "called"
            dump(runf, meta)
        it["select_run"] = {x: (meta or {}).get(x) for x in ("mock", "model_requested", "model_version", "response_id", "usage",
                                                              "finish", "retries", "started_at", "finished_at", "failure")}
        u = (meta or {}).get("usage") or {}
        it["cost_usd_from_usage"] = (None if not u or u.get("prompt") is None else round(
            (u.get("prompt") or 0) * PRICE["input_usd_per_1m"] / 1e6
            + ((u.get("output") or 0) + (u.get("thoughts") or 0)) * PRICE["output_usd_per_1m"] / 1e6, 5))

        if reply is None:
            why = "select_call_error" if (meta or {}).get("failure") else "select_attempt_without_result"
            sel = {"status": "failed", "reasons": [why], "tried": [],
                   "detail": "장면 선정 응답이 없다 — 다시 부르지 않는다 (선정 전용 실행 · 그림 생성 실패가 아니다)"}
        else:
            sel = book.choose(data, k, reply)
        dump(folder / "selection.json", sel)
        if sel["status"] == "selected":
            (folder / "image_prompt.txt").write_text(
                "# 보내지 않은 그림 지시문 — 선정 전용 실행이라 그림 API 를 부르지 않았다\n\n" + sel["prompt"]["text"], encoding="utf-8")
        ev = evaluate(data, trial, cases, k, reply, sel)
        dump(folder / "evaluation.json", ev)
        it.update(status=sel["status"], reasons=sel.get("reasons"), mode=sel.get("mode"), source=sel.get("source"),
                  scene_title=(sel.get("scene") or {}).get("scene_title"), choice_reason=sel.get("choice_reason") or sel.get("detail"),
                  model_problems=ev["model_problems"], code_problems=ev["code_problems"], run_problems=ev["run_problems"],
                  known_limit_hit=ev["known_limit_hit"])
        items.append(it)

    attempted = sorted(f.parent.name for f in (out / "items").glob("*/select_attempt.json"))
    summary = {"trial_id": trial["trial_id"], "mock": mock, "finished_at": now(), "calls_this_run": calls,
               "select_attempted_total": len(attempted), "attempted_items": attempted, "image_calls_total": 0,
               "max_calls": p["max_calls"], "live_confirm": p["live_confirm"],
               "cost_usd_from_usage": round(sum(i["cost_usd_from_usage"] or 0 for i in items), 5) if not mock else None}
    dump(out / "items.json", {"summary": summary, "items": items})
    prev = load(out / "run.json") if (out / "run.json").is_file() else {"runs": []}
    dump(out / "run.json", {"runs": prev["runs"] + [summary]})
    (out / "report.md").write_text(report(trial, items, out, summary), encoding="utf-8")
    return items, calls


def report(trial: dict, items: list[dict], out: Path, summary: dict) -> str:
    md = [f"# 장면 선정 전용 시험 — {trial['trial_id']} ({'모의' if summary['mock'] else '실제 모델'})", "",
          f"작성: 실행기 자동 기록. {AI_NOTE}",
          f"그림 API 호출: **0회** (선정 전용). 이번 실행의 장면 선정 호출: {summary['calls_this_run']['select']}회 · "
          f"이 폴더에서 시도한 항목 누적: {summary['select_attempted_total']}개 / 상한 {MAX_CALLS}.", ""]
    md += ["| 항목 | 선정 결과 | ① 모델 중심 제안 | ② 중심 후보 | ③ 참여자 · 근거 | ④ 코드 선택 적절 | ⑤ 잘못 탈락 | ⑥ 잘못 통과 | 알려진 한계 |",
           "|---|---|---|---|---|---|---|---|---|"]
    for it in items:
        ev = load(out / "items" / it["ident"] / "evaluation.json")
        m, c = ev["model"], ev["code"]
        res = (f"{it['scene_title']} · {it['mode']}" + (" · 사람을 뺀 그림" if it["source"] == "derived_symbolic" else "")
               if it["status"] == "selected" else f"{it['status']} ({', '.join(it['reasons'] or [])})")
        hit = [w for w in c["q5_wrongly_rejected"] if not w["effect"].startswith("영향 없음")]
        note = len(c["q5_wrongly_rejected"]) - len(hit)
        q5 = (f"{len(hit)}" if hit else "없음") + (f" (결과에 영향 없는 탈락 {note})" if note else "")
        md.append(f"| {it['ident']} 「{it['title']}」 | {res} | {m['q1_center_proposed']['verdict']} | {m['q2_candidate_with_center']['verdict']} | "
                  f"{m['q3_participants_and_evidence']['verdict']} | {c['q4_chose_appropriate']} | "
                  f"{q5} | {len(c['q6_wrongly_passed']) or '없음'} | "
                  f"{ev['known_limit_hit']['case'] if ev['known_limit_hit'] else '-'} |")
    md.append("")
    for it in items:
        ev = load(out / "items" / it["ident"] / "evaluation.json")
        run_ = it["select_run"]
        md += [f"## {it['ident']} 「{it['title']}」", "",
               f"- 기대(AI 작성): {ev['expect']['why']}",
               f"- 호출: {it['select_call']} · 모델 {run_.get('model_version') or run_.get('model_requested')} · 토큰 {run_.get('usage')} · "
               f"오류 {run_.get('failure') or '-'}",
               f"- 선택 이유(코드): {it['choice_reason']}",
               f"- 그림: {it['image']['status']} — {it['image']['note']}",
               *(["- 실행 문제: " + "; ".join(ev["run_problems"])] if ev["run_problems"] else []),
               "- 모델 쪽 문제: " + ("; ".join(ev["model_problems"]) or "없음"),
               "- 코드 쪽 문제: " + ("; ".join(ev["code_problems"]) or "없음"),
               *(["- 결과에 영향 없는 탈락(참고): " + "; ".join(ev["code_notes_no_effect"])] if ev["code_notes_no_effect"] else [])]
        if ev["known_limit"]:
            md.append(f"- 알려진 한계 {ev['known_limit']['case']}: {ev['known_limit']['text']}"
                      + (" — **이번에 해당**" if ev["known_limit_hit"] else " — 이번에는 해당하지 않음"))
        rows = ev["code"]["candidates"]
        if rows:
            md += ["", "| 후보 | 코드: 형식 · 원문 대조 | 코드: 중심을 담는가 | 기준(AI): 적절한가 | 결과 |", "|---|---|---|---|---|"]
            for x in rows:
                md.append(f"| {x['candidate_index']} {x['scene_title']}{' (사람을 뺀 그림)' if x['source'] == 'derived_symbolic' else ''} | "
                          f"{'통과' if x['code_accepted'] else '막힘 — ' + ', '.join(x['code_blocking'])} | "
                          f"{'예' if x['code_represents'] else '아니오'} | "
                          f"{'예' if x['appropriate'] else '아니오 — ' + '; '.join(x['rubric_problems'])} | {'선택' if x['chosen'] else '-'} |")
        pt = ev["people_tier_vs_participation"]["rows"]
        if pt:
            md += ["", "| 후보 | 사람 | 대표성 등급(코드) | 역할 | 중심 행동 참여 | 공동 작업에 필요한 사람 |", "|---|---|---|---|---|---|"]
            for x in pt:
                md.append(f"| {x['candidate_index']} | {x['text']} | {x['tier'] or '-'} | {x['role'] or '-'} | "
                          f"{'예' if x['acts_in_central_action'] else '아니오'} | {'예' if x['required_participant'] else '-'} |")
        md.append("")
    return "\n".join(md)


def mock_from_cases(cases: dict, targets: list[str]) -> dict:
    """사례 파일의 첫 사례(후보 · focus)로 만든 모의 응답 — 모델이 낸 것이 아니다."""
    out = {}
    for k in targets:
        c = cases[k]["cases"][0]
        doc = {"candidates": [cases[k]["candidates"][n] for n in c["candidates"]]}
        if c["focus"]:
            doc["focus"] = cases[k]["focus"][c["focus"]]
        out[k] = doc
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="삽화 장면 선정만 실제 모델로 시험한다 — 합성 자료 다섯 항목 (그림 API 없음)")
    ap.add_argument("--trial", type=Path, default=TRIAL)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mock-from-cases", action="store_true")
    ap.add_argument("--mock-select", type=Path, help='{"by_chapter": {"c01": <응답 글 또는 객체>, …}}')
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--confirm")
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--authorized-by")
    ap.add_argument("--authorization-note")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        trial_path = a.trial.resolve()
        trial, data, cases = load_trial(trial_path)
        p = plan(trial_path, trial, data)
        if a.dry_run:
            existing = None
            if a.out and (a.out / "manifest.json").is_file():
                existing = {"mode": "mock" if load(a.out / "manifest.json").get("mock") else "live",
                            "attempted": sorted(f.parent.name for f in (a.out / "items").glob("*/select_attempt.json"))}
            print(json.dumps({"dry_run": True, "api_called": False, "written_by": AI_NOTE, **p,
                              "sent_scope": "항목마다 그 항목의 제목 · 본문 문장과 그 문장이 근거로 쓰는 원문 턴 하나(합성). "
                                            "사진 단서 없음. 실제 인터뷰 자료 없음. 다른 항목의 글은 보내지 않는다",
                              "calls_if_live": {"select": len([t for t in trial["targets"]
                                                               if not (existing and t in existing["attempted"])]), "image": 0},
                              "existing_out": existing, "live_approved": False}, ensure_ascii=False, indent=1))
            return 0
        if not a.out or RUNS.resolve() not in a.out.resolve().parents:
            raise il.IllustError("input", "--out 은 eval/runs/ 아래여야 한다 (git 제외 경로)")
        if a.live:
            if a.mock_select or a.mock_from_cases:
                raise il.IllustError("input", "--live 와 --mock-… 을 함께 쓸 수 없다")
            if (a.confirm != p["live_confirm"] or not a.env_file or not (a.authorized_by or "").strip()
                    or not (a.authorization_note or "").strip()):
                raise il.IllustError("not_approved", "--live 에는 --confirm(dry-run 의 live_confirm) · --env-file · --authorized-by · "
                                                     "--authorization-note 가 모두 있어야 한다. 지시문 · 코드 · 기준 · 자료가 바뀌면 값도 바뀐다")
            _check_manifest(a.out, p, mock=False)         # 키를 읽기 전에 폴더부터 본다
            key = seltool.read_key(a.env_file)
            authorization = {"authorized_by": a.authorized_by, "note": a.authorization_note, "recorded_at": now(),
                             "targets": trial["targets"], "live_confirm": p["live_confirm"]}

            def call(system, user):
                return seltool.LIVE_CALL(system, user, model=SELECT_MODEL, key=key)
            mock = False
        else:
            if a.mock_select and a.mock_from_cases or not (a.mock_select or a.mock_from_cases):
                raise il.IllustError("not_approved", "--dry-run · --mock-from-cases · --mock-select · --live 가운데 하나를 쓴다")
            by = mock_from_cases(cases, trial["targets"]) if a.mock_from_cases else load(a.mock_select).get("by_chapter", {})
            authorization, mock = None, True

            which = {il.select_message(data, [k]): k for k in trial["targets"]}

            def call(system, user):
                reply = by.get(which[user], {"candidates": []})
                return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        items, calls = run(trial_path, trial, data, cases, a.out, call=call, mock=mock, authorization=authorization)
    except il.IllustError as e:
        print(f"거부 — {e}", file=sys.stderr)
        return 2
    print(json.dumps({"out": str(a.out), "mock": mock, "calls": calls,
                      "items": [{"ident": it["ident"], "title": it["title"], "select_call": it["select_call"], "status": it["status"],
                                 "scene_title": it["scene_title"], "image": it["image"]["status"],
                                 "model_problems": it["model_problems"], "code_problems": it["code_problems"]} for it in items]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
