"""
목차 주제 삽화 — 장 전체의 주제를 나타내는 그림 한 장 (chapter_theme_v2 · 기본 방식, 2026-11-18 ~)

두 방식은 목적이 다르고 검사도 다르다.

    장면 방식 scene_v5          한 장면을 원문 그대로 재현한다 (memoir_illust · memoir_illust_book.choose).
                                인물 · 행동 · 인용을 원문과 글자로 맞추고, 참여 관계 누락 · 부정 표지 · 나이 표지가 있으면 막는다.
    주제 방식 chapter_theme_v2  장 전체의 중심 주제와 분위기를 나타낸다 (이 파일). 장면을 재현하지 않는다.

주제 방식의 흐름 — 장 전체 읽기 → 중심 주제와 분위기 → 대표 소재와 구도 → 한국어 그림 지시문 → 생성 · 저장 · 삽입.

    theme_message       제목 + 장 본문 전체(문단 번호) + 그 장의 원문 말씀 → 모델 (지시문 1_목차주제_v7)
    parse_plan          모델의 계획 — 주제 · 분위기 · 뒷받침 내용 · 그릴 소재 · 구도. 모양이 틀리면 model_output, 비었으면 empty_plan
    theme_checks        응답 모양 · 주제와 소재가 있는가 · 그림 지시문이 조립되는가만 본다
    build_theme_prompt  계획의 소재 · 구도와 고정 양식(2_그림양식_v2)으로 한국어 그림 지시문을 조립한다
    choose_theme        위를 묶어 memoir_illust_book.choose 와 같은 모양의 결과를 낸다. 넣을 자리는 장의 첫 문단 뒤다

**뜻은 모델이 판단한다 — 코드는 낱말로 막지 않는다 (v2).** 본문의 실제 경험과 부정 · 가정 · 희망으로 말한 일을 가리는 것,
본문과 반대되는 경험이나 새 사건을 만들지 않는 것은 지시문 v7 이 모델에게 맡긴다. 코드는 「안 · 못 · 없」 같은 낱말 · 반복 횟수 ·
짧은 인용 · 참여 인물 · 관계 낱말로 소재를 빼거나 생성을 막지 않는다. 그래서 코드는 그 판단을 검증했다고 적지 않는다 —
결과의 verdict 에 한 검사와 하지 않은 검사(뜻)를 그대로 적고, human 은 not_reviewed 그대로다.

앞선 판 chapter_theme_v1(지시문 1_목차주제_v6)은 낱말 검사로 소재를 빼고 생성을 막았다(theme_negated · no_central_subject ·
theme_adds_relation). 그 판으로 만든 기록은 그대로 남는다 — 이 판의 기준으로 다시 검사한 것처럼 바꾸지 않는다.

이 파일은 모델도 이미지 API 도 부르지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re

from . import memoir_illust as il

POLICY = "chapter_theme_v2"
CHECKS_VERSION = "theme_checks_v2"
MODE = "THEME"
SELECT_FILE = "1_목차주제_v7.md"           # v6 은 chapter_theme_v1 의 기록으로 남긴다
STYLE_FILE = "2_그림양식_v2.md"
STYLE_ID = "watercolor-recall-v2"
KINDS = ("object", "place", "activity", "person", "nature")
MAX_SUBJECTS, MAX_MAIN, MAX_SUB = 6, 3, 4
TEXT_MAX, THEME_MAX, SHORT_MAX, MOOD_MAX, PERIOD_MAX, COMPOSITION_MAX = 40, 120, 30, 40, 30, 220
DEFAULT_COMPOSITION = "중심 소재를 화면 가운데에 두고, 둘레는 이 장의 분위기에 맞게 여백을 두어 옅게 풀어 준다"

# 참고 정보(anchor 가 본문 어디에 나오는가)를 셀 때 낱말 뒤에 붙어도 같은 낱말로 보는 조사 · 서술격 어미. 판정에는 쓰지 않는다
_PARTICLES = sorted("""은 는 이 가 을 를 에 에서 에게 께 께서 한테 의 와 과 도 만 로 으로 랑 이랑 하고 까지 부터 처럼 보다 마다
    조차 밖에 이나 나 이며 며 이다 였다 이었다 였 이었 이라 라 이라고 라고 이야 야 이고 이지만 지만 이든 든 들 님 뿐 쯤 씩""".split(),
                    key=len, reverse=True)
_VERBAL = ("하", "했", "해", "한", "할", "합", "되", "됐", "된", "될")
_HANGUL = re.compile(r"[가-힣]")

THEME_CHECKED = ["응답이 JSON 계획 하나인가 (모양)",
                 "주제와 그릴 소재가 비어 있지 않은가",
                 "그림 지시문이 조립되는가 (고정 양식 · 길이 상한)"]
THEME_NOT_CHECKED = ["주제 · 소재가 이 장에 맞는가 (뜻) — 모델의 판단이다. 코드는 검증하지 않는다",
                     "본문에서 실제 경험한 일과 부정 · 가정 · 희망으로 말한 일을 모델이 바르게 가렸는가",
                     "본문과 반대되는 경험이나 본문에 없는 사건 · 인물 관계를 더하지 않았는가 — 지시문 · 그림 양식이 금지할 뿐 코드는 보지 않는다",
                     "이미지 모델이 지시문 밖의 것을 그려 넣는가 (생성 뒤 사람이 본다)"]


def _file_hash(name: str) -> str:
    try:
        return hashlib.sha256((il.PROMPTS / name).read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"


def select_prompt() -> str:
    b = il._blocks(il.PROMPTS / SELECT_FILE)
    if not b.get("1"):
        raise il.IllustError("prompt_file", f"{SELECT_FILE} 에 §1 블록이 없다")
    return b["1"]


def prompt_hash() -> str:
    return _file_hash(SELECT_FILE)


def style_hash() -> str:
    return _file_hash(STYLE_FILE)


def style_blocks() -> dict[str, str]:
    b = il._blocks(il.PROMPTS / STYLE_FILE)
    missing = [n for n in ("1", "2", "3") if not b.get(n)]
    if missing:
        raise il.IllustError("prompt_file", f"{STYLE_FILE} 에 §{' · §'.join(missing)} 블록이 없다")
    return {"style": b["1"], "people": b["2"], "negative": b["3"]}


# ---------------------------------------------------------------- 장과 모델 자료

def _chapter(data: dict, ident) -> dict:
    for c in il._chapters(data["memoir"]):
        if (c["key"] is not None and c["key"] == ident) or (c["key"] is None and c["no"] == ident) or c["no"] == ident:
            return c
    raise il.IllustError("input", f"{ident} 항목이 원고에 없다")


def _chapter_utts(ctx: dict, ch: dict) -> list[dict]:
    turns = set(ch["turns"]) | set(ch["chapter_turns"])
    return [{"turn": t, "asked": u.get("asked", ""), "elder": u["elder"]} for t, u in sorted(ctx["utts"].items()) if t in turns]


def theme_message(data: dict, ident) -> str:
    """모델에 줄 자료 — 그 장의 제목 · 본문 전체(문단 번호를 붙여)와 그 장이 근거로 쓰는 원문 말씀(참고). 다른 장 · 사진 단서는 싣지 않는다."""
    ctx = il.check_input(data)
    ch = _chapter(data, ident)
    payload = {"chapter": {"chapter_no": ch["no"], "title": ch["title"],
                           "paragraphs": [{"p": i, "text": t} for i, t in enumerate(ch["paragraphs"])]},
               "utterances": _chapter_utts(ctx, ch)}
    return "[자료]\n" + json.dumps(payload, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 모델의 계획

def _text(v, limit: int) -> str | None:
    return v.strip()[:limit] if isinstance(v, str) and v.strip() else None


def parse_plan(reply, chapter_no: int | None = None) -> dict:
    """
    모델 응답 → 계획. 빠진 칸을 지어내지 않는다.
        IllustError("model_output")  JSON 이 아니다 · 계획이 객체가 아니다 (응답 형식 오류)
        IllustError("empty_plan")    주제가 비었다 · 그릴 소재가 하나도 없다 (빈 계획)
    """
    try:
        out = json.loads(reply) if isinstance(reply, str) else reply
    except (TypeError, ValueError) as e:
        raise il.IllustError("model_output", f"JSON 이 아니다 ({type(e).__name__})") from e
    if isinstance(out, dict) and isinstance(out.get("chapters"), list):
        pick = [c for c in out["chapters"] if isinstance(c, dict) and (chapter_no is None or c.get("chapter_no") == chapter_no)]
        out = pick[0] if pick else (out["chapters"][0] if out["chapters"] else None)
    if isinstance(out, list) and len(out) == 1 and isinstance(out[0], dict):
        out = out[0]                                     # 계획 하나를 목록으로 감싸 낸 응답 — 모양만 벗긴다
    if not isinstance(out, dict):
        raise il.IllustError("model_output", "계획이 객체가 아니다")
    theme = _text(out.get("theme"), THEME_MAX)
    if not theme:
        raise il.IllustError("empty_plan", "theme 이 비었다")
    subjects = []
    for s in out.get("subjects") or []:
        if not isinstance(s, dict) or not _text(s.get("text"), TEXT_MAX):
            continue
        kind = s.get("kind") if s.get("kind") in KINDS else "object"
        subjects.append({"text": _text(s.get("text"), TEXT_MAX), "kind": kind,
                         "kind_from_model": s.get("kind"), "role": "main" if s.get("role") == "main" else "sub",
                         "anchor": _text(s.get("anchor"), TEXT_MAX)})
    if not subjects:
        raise il.IllustError("empty_plan", "그릴 소재(subjects)가 하나도 없다")
    supports = [{"point": _text(x.get("point"), THEME_MAX),
                 "paragraphs": [p for p in x.get("paragraphs") or [] if isinstance(p, int) and not isinstance(p, bool)]}
                for x in out.get("supports") or [] if isinstance(x, dict) and _text(x.get("point"), THEME_MAX)]
    return {"chapter_no": out.get("chapter_no"), "theme": theme,
            "theme_short": _text(out.get("theme_short"), SHORT_MAX) or theme[:SHORT_MAX],
            "mood": _text(out.get("mood"), MOOD_MAX), "period": _text(out.get("period"), PERIOD_MAX),
            "supports": supports, "subjects": subjects[:MAX_SUBJECTS],
            "composition": _text(out.get("composition"), COMPOSITION_MAX),
            "not_in_story": [x.strip() for x in out.get("not_in_story") or [] if isinstance(x, str) and x.strip()]}


# ---------------------------------------------------------------- 검사 — 모양과 존재만. 참고 정보는 판정에 쓰지 않는다

def _pattern(word: str) -> re.Pattern | None:
    key = il._compact(word)
    if not key:
        return None
    return re.compile(r"\s*".join(re.escape(ch) for ch in key))


def _tail_ok(run: str) -> bool:
    """낱말 바로 뒤에 붙은 한글 덩어리가 조사 · 서술격 어미뿐인가 (또는 「하다 · 되다」)."""
    for _ in range(4):
        if not run:
            return True
        if run.startswith(_VERBAL):
            return True
        hit = next((x for x in _PARTICLES if run.startswith(x)), None)
        if hit is None:
            return False
        run = run[len(hit):]
    return not run


def _hits(word: str, text: str) -> list[re.Match]:
    """참고용 — 낱말이 나오는 자리 (앞은 낱말 경계, 뒤는 조사 · 어미만). 판정에는 쓰지 않는다."""
    pat = _pattern(word)
    if pat is None:
        return []
    out = []
    for m in pat.finditer(text):
        before = text[m.start() - 1] if m.start() > 0 else " "
        if _HANGUL.match(before):
            continue
        if _tail_ok(re.match(r"[가-힣]*", text[m.end():]).group(0)):
            out.append(m)
    return out


def anchor_reference(word: str | None, ch: dict) -> dict:
    """참고 정보 — 모델이 적은 본문 낱말이 제목 · 본문 어디에 나오는가. 소재를 빼거나 생성을 막는 데 쓰지 않는다."""
    if not word or _pattern(word) is None:
        return {"word": word, "in_title": False, "mentions": 0, "paragraphs": []}
    paras = [i for i, p in enumerate(ch["paragraphs"]) for _ in _hits(word, p)]
    return {"word": word, "in_title": bool(_hits(word, ch["title"])), "mentions": len(paras), "paragraphs": sorted(set(paras))}


def theme_checks(data: dict, ident, plan: dict) -> dict:
    """
    계획을 그대로 쓴다 — 소재를 빼지 않고, 뜻을 따지지 않는다. 중심 소재는 모델이 main 으로 적은 것(없으면 적은 순서의 앞)이다.
    여기서 실패가 나는 것은 지시문을 조립할 수 없을 때뿐이다 (빈 계획은 parse_plan 이 이미 막았다).
    """
    il.check_input(data)
    ch = _chapter(data, ident)
    subjects = [{**s, "anchor_reference": anchor_reference(s["anchor"], ch)} for s in plan["subjects"]]
    main = [s for s in subjects if s["role"] == "main"][:MAX_MAIN]
    main_from = "model_main" if main else "model_order"
    main = main or subjects[:1]
    sub = [s for s in subjects if s not in main][:MAX_SUB]
    checks = [{"check": "format", "ok": True},
              {"check": "plan_present", "ok": True, "detail": {"theme": bool(plan["theme"]), "subjects": len(subjects),
                                                               "main": [s["text"] for s in main], "main_from": main_from}},
              # 참고 정보 — 막지 않는다. 모델이 적은 낱말이 본문 어디에 나오는지일 뿐, 뜻을 검증한 것이 아니다
              {"check": "anchor_reference", "ok": True, "blocking": False,
               "detail": [{"text": s["text"], **s["anchor_reference"]} for s in subjects]}]
    return {"policy": POLICY, "checks_version": CHECKS_VERSION, "chapter_no": ch["no"], "accept": True, "blocking": [],
            "theme": plan["theme"], "theme_short": plan["theme_short"], "mood": plan["mood"], "period": plan["period"],
            "supports": plan["supports"], "composition": plan["composition"], "not_in_story": plan["not_in_story"],
            "subjects": subjects, "main": main, "sub": sub, "main_from": main_from, "checks": checks}


# ---------------------------------------------------------------- 그림 지시문 · 자리

def build_theme_prompt(chk: dict) -> dict:
    """계획의 주제 · 소재 · 구도와 고정 양식(v2)으로 조립한다. 본문에 없다고 모델이 적은 것(not_in_story)은 지시문에 넣지 않는다."""
    blocks = style_blocks()
    main, sub = chk["main"], chk["sub"]
    theme = chk["theme_short"] + (f" — {chk['theme']}" if chk["theme"] and chk["theme"] != chk["theme_short"] else "")
    about = [f"- 주제: {theme}", f"- 분위기: {chk['mood'] or '차분하고 따뜻하게'}",
             f"- 때: {chk['period']} — 이보다 더 구체적으로 정하지 않는다" if chk["period"]
             else "- 때: 특정하지 않는다 — 연도 · 계절을 단정하지 않는다"]
    draw = [f"- 중심 소재: {', '.join(s['text'] for s in main)} — 화면의 중심에 둔다"]
    if sub:
        draw.append(f"- 함께 둘 수 있는 것: {', '.join(s['text'] for s in sub)} — 보조로 둔다")
    draw.append(f"- 구도: {chk['composition'] or DEFAULT_COMPOSITION}")
    draw.append("- 인물: 「그릴 것」 의 사람은 일반화된 모습으로만 — 얼굴 · 이름 · 관계를 정하지 않는다"
                if any(s["kind"] == "person" for s in main + sub)
                else "- 인물: 넣지 않아도 된다. 넣는다면 멀리서 본 작은 뒷모습으로만")
    block = "[이 장의 주제]\n" + "\n".join(about) + "\n\n[그릴 것]\n" + "\n".join(draw)
    text = "\n\n".join([blocks["style"], block, blocks["people"], blocks["negative"]])
    if len(text) > il.PROMPT_MAX and sub:                      # 길면 보조 소재부터 줄인다
        return build_theme_prompt({**chk, "sub": sub[:-1]})
    if len(text) > il.PROMPT_MAX:
        raise il.IllustError("prompt_too_long", f"그림 지시문이 {len(text)}자 — 상한 {il.PROMPT_MAX}자")
    return {"style_id": STYLE_ID, "language": "ko", "policy": POLICY, "text": text, "scene_block": block,
            "elements_used": [s["text"] for s in main + sub],
            "composition": {"main": [s["text"] for s in main], "sub": [s["text"] for s in sub],
                            "layout": chk["composition"] or DEFAULT_COMPOSITION,
                            "layout_from": "model" if chk["composition"] else "default",
                            "from_plan": [{"text": s["text"], "kind": s["kind"], "anchor": s["anchor"]} for s in main + sub]}}


def theme_placement(data: dict, ident) -> dict:
    """장의 주제 그림은 장의 첫머리 — 첫 문단(30자 이상인 첫 문단) 뒤. 자리는 장면 방식과 같은 모양이라 locate 로 다시 찾는다."""
    ch = _chapter(data, ident)
    i = next((k for k, p in enumerate(ch["paragraphs"]) if len(il._compact(p)) >= 30), 0)
    return {"chapter_no": ch["no"], "chapter_key": ch["key"], "chapter_title": ch["title"],
            "paragraph_count": len(ch["paragraphs"]), "chapter_hash": il._para_hash("".join(ch["paragraphs"])),
            "paragraph_index": i, "basis": "chapter_theme_start",
            "anchor": {"text": ch["paragraphs"][i][:il.ANCHOR_CHARS], "hash": il._para_hash(ch["paragraphs"][i])},
            "sentence_index": None, "sentence_count": None, "sentence_anchor": None}


def choose_theme(data: dict, ident, reply) -> dict:
    """목차 한 장의 주제 그림 — memoir_illust_book.choose 와 같은 모양 (status · mode · scene · prompt · placement …)."""
    ch = _chapter(data, ident)
    base = {"policy": POLICY, "checks_version": CHECKS_VERSION, "mode": MODE, "automatic": True, "human": "not_reviewed"}
    verdict = {"policy": POLICY, "checks_version": CHECKS_VERSION, "checked": THEME_CHECKED, "not_checked": THEME_NOT_CHECKED,
               "meaning_verified_by_code": False}
    try:
        plan = parse_plan(reply, ch["no"])
    except il.IllustError as e:
        return {**base, "status": "failed", "reasons": [e.kind], "detail": e.message, "tried": [],
                "verdict": {**verdict, "accept": False, "blocking": [e.kind]}}
    chk = theme_checks(data, ident, plan)
    try:
        prompt = build_theme_prompt(chk)
    except il.IllustError as e:
        return {**base, "status": "failed", "reasons": [e.kind], "detail": e.message, "theme": chk, "tried": [],
                "verdict": {**verdict, "accept": False, "blocking": [e.kind]}}
    turns = sorted(set(ch["turns"]) | set(ch["chapter_turns"]))
    return {**base, "status": "selected", "source": "theme_plan", "candidate_index": 0,
            "scene": {"scene_title": plan["theme_short"], "scene_summary": plan["theme"], "central_action": None,
                      "source_turns": turns, "source_refs": [],
                      "evidence": [{"kind": s["kind"], "text": s["text"], "anchor": s["anchor"], "role": s["role"],
                                    "anchor_reference": s["anchor_reference"]} for s in chk["subjects"]],
                      "not_used": [], "dropped_for_picture": []},
            "prompt": prompt, "placement": theme_placement(data, ident), "auto_checks": chk["checks"],
            "tolerated_reasons": [], "theme": chk, "verdict": {**verdict, "accept": True, "blocking": []},
            "tried": [{"candidate_index": 0, "scene_title": plan["theme_short"], "mode": MODE, "accepted": True, "blocking": []}],
            "choice_reason": f"주제 방식 — 모델 계획의 중심 소재 {', '.join(prompt['composition']['main'])} (코드는 뜻을 검증하지 않았다)"}
