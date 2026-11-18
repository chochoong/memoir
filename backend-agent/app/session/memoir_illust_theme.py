"""
목차 주제 삽화 — 장 전체의 주제를 나타내는 그림 한 장 (chapter_theme_v1 · 기본 방식, 2026-11-18 ~)

두 방식은 목적이 다르고 검사도 다르다.

    장면 방식 scene_v5          한 장면을 원문 그대로 재현한다 (memoir_illust · memoir_illust_book.choose).
                                인물 · 행동 · 인용을 원문과 글자로 맞추고, 참여 관계 누락 · 부정 표지 · 나이 표지가 있으면 막는다.
    주제 방식 chapter_theme_v1  장 전체의 중심 주제와 분위기를 나타낸다 (이 파일). 장면을 재현하지 않으므로 위의 검사를 쓰지 않는다.

주제 방식의 흐름 — 장 전체 읽기 → 중심 주제와 분위기 → 대표 시각 소재와 구도 → 한국어 그림 지시문.

    theme_message       장 본문 전체(문단 번호) + 그 장의 원문 말씀 → 모델 (지시문 1_목차주제_v6)
    parse_plan          모델의 계획 — 주제 · 뒷받침하는 내용 · 그릴 소재(+ 본문 낱말 anchor) · 구도를 따로 받는다
    theme_checks        ① 주제와 어울리는가   중심 소재의 낱말이 본문(또는 제목)에 실제로 나오고, 제목 · 주제 · 뒷받침 내용과 이어지는가.
                                              반복 횟수 · 문단 비율은 참고로만 적는다 — 같은 낱말이 반복되지 않아도 주제는 분명할 수 있다.
                                              제목에만 있고 주제 · 뒷받침 어디와도 이어지지 않으면(비유적 제목) 중심으로 치지 않는다
                        ② 반대로 그리지 않는가 그 낱말에 걸린 부정만 센다 — 「카페에서 일한 적이 없다」 「카페가 없었다」 「카페에 가지 않았다」
                                              「커피를 안 마셨다」. 다른 낱말에 걸린 부정(「카페에는 손님이 없었다」)은 세지 않는다.
                                              낱말은 조사 · 어미까지만 같은 낱말로 본다 — 「카페인」 은 「카페」 가 아니다.
                                              그 낱말이 본문에서 부정으로만 나오면 그 소재를 빼고, 주제 문장이 그 낱말을 쓰면 실패다
                        ③ 없는 사건 · 관계    본문에 없는 관계(어머니 · 친구 …) · 숫자를 단 소재와 구도는 뺀다. 주제가 그런 관계를 만들면 실패다
                        ④ 그릴 수 있는가      중심 소재가 하나도 남지 않으면 실패다 — 지어내서 채우지 않는다
    build_theme_prompt  남은 소재 · 구도와 고정 양식(2_그림양식_v2)으로 그림 지시문을 조립한다
    choose_theme        위를 묶어 memoir_illust_book.choose 와 같은 모양의 결과를 낸다. 넣을 자리는 장의 첫 문단 뒤다

**막지 않는 것.** 짧은 인용 · 다른 낱말에 걸린 「없 · 안 · 못」 · 참여 인물의 누락 · 나이 표지 · 적은 반복 · 문단 나눔은 주제 그림을
막지 않는다. 옷차림 · 배경 질감 · 빛 · 색감 · 구도처럼 그림을 꾸미는 표현은 본문에 글자 그대로 없어도 된다. 일반화된 인물도 된다.

**사람이 확인한 것이 아니다.** 이 검사는 낱말이 본문 · 제목 · 뒷받침 내용 어디에 어떤 꼴(부정 문형)로 나오는지만 본다. 그림이 주제를
잘 나타내는지(뜻)는 보지 못한다. 결과에 policy · 한 검사 · 하지 못한 검사를 그대로 적는다 — 장면 방식의 원문 대조(quoted · verified)를
했다고 적지 않는다. 이 파일은 모델도 이미지 API 도 부르지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re

from . import memoir_illust as il

POLICY = "chapter_theme_v1"
MODE = "THEME"
SELECT_FILE = "1_목차주제_v6.md"
STYLE_FILE = "2_그림양식_v2.md"
STYLE_ID = "watercolor-recall-v2"
KINDS = ("object", "place", "activity", "person", "nature")
MAX_SUBJECTS, MAX_MAIN, MAX_SUB = 6, 3, 4
TEXT_MAX, THEME_MAX, SHORT_MAX, MOOD_MAX, PERIOD_MAX, COMPOSITION_MAX = 40, 120, 30, 40, 30, 220
DEFAULT_COMPOSITION = "중심 소재를 화면 가운데에 두고, 둘레는 이 장의 분위기에 맞게 여백을 두어 옅게 풀어 준다"

# 본문에 없으면 소재 · 구도 · 주제에 붙일 수 없는 사람 관계 · 역할 낱말 (일반화된 「아이 · 사람 · 여행자」 는 여기에 없다)
RELATIONS = ("어머니", "엄마", "아버지", "아빠", "할머니", "할아버지", "부모", "삼촌", "외삼촌", "이모", "고모", "숙모", "큰아버지",
             "작은아버지", "형", "누나", "언니", "오빠", "동생", "남편", "아내", "아들", "딸", "손자", "손녀", "사촌", "친구", "선생님",
             "사장", "회장", "비서", "손님", "단골", "애인", "연인", "남자친구", "여자친구", "가족", "식구")

# 낱말 뒤에 붙어도 같은 낱말로 보는 조사 · 서술격 어미 (긴 것부터 떼어 본다). 여기 없는 글자가 이어지면 다른 낱말이다 —
# 「카페인」 의 「인」, 「산책」 의 「책」, 「배낭여행」 의 「여행」. 붙은 말(합성어)은 그 낱말로 세지 않는다
_PARTICLES = sorted("""은 는 이 가 을 를 에 에서 에게 께 께서 한테 의 와 과 도 만 로 으로 랑 이랑 하고 까지 부터 처럼 보다 마다
    조차 밖에 이나 나 이며 며 이다 였다 이었다 였 이었 이라 라 이라고 라고 이야 야 이고 이지만 지만 이든 든 들 님 뿐 쯤 씩""".split(),
                    key=len, reverse=True)
_VERBAL = ("하", "했", "해", "한", "할", "합", "되", "됐", "된", "될")     # 「독서하던 · 알바했다」 — 그 낱말을 하는 일
_HANGUL = re.compile(r"[가-힣]")
_CLAUSE_END = re.compile(r"[,.?!…”\"]|는데|지만|면서|고서")
_ADV = r"(?:\s*(?:별로|전혀|잘|한\s*번도|한번도|아직|결코|다시는|좀처럼))?"
_PRT = r"(?:은|는|이|가|을|를|에|에서|에는|에서는|에도|에게|로|으로|와|과|랑|이랑|하고|도)?"
# 그 낱말에 걸린 부정 — 낱말 바로 뒤에서 시작하는 문형만 (사이에 다른 낱말이 주어로 끼면 그 낱말의 부정이다)
_NEG_PATTERNS = (
    ("없음 · 아님", re.compile(r"^(?:은|는|이|가|도)?" + _ADV + r"\s*(?:없|아니)")),                       # 카페가 없었다 · 카페는 아니었다
    ("~하지 않았다", re.compile(r"^" + _PRT + _ADV + r"\s*[가-힣]+(?:지|지는|지도)\s*(?:않|못|말)")),       # 카페에 가지 않았다
    ("안 · 못 ~", re.compile(r"^" + _PRT + _ADV + r"\s*(?:안|못)\s*[가-힣]")),                              # 커피를 안 마셨다
    ("~한 적이 없다", re.compile(r"^" + _PRT + r"(?:\s*[가-힣]+){1,2}?\s*(?:적|일)(?:이|은|도)?" + _ADV + r"\s*없")),  # 카페에서 일한 적이 없다
)

THEME_CHECKED = ["중심 소재의 낱말이 본문(또는 제목)에 실제로 나오는가 — 조사 · 어미까지만 같은 낱말로 본다 (「카페인」 ≠ 「카페」)",
                 "그 소재가 제목 · 주제 · 뒷받침 내용(또는 뒷받침이 가리킨 문단)과 이어지는가 — 반복 횟수 · 문단 비율은 참고로만 적는다",
                 "그 낱말에 걸린 부정 문형(…한 적이 없다 · …가 없다 · …하지 않았다 · 안/못 …)으로만 나오는가 — 다른 낱말의 부정은 세지 않는다",
                 "소재 · 구도 · 주제에 본문에 없는 사람 관계 낱말 · 숫자가 있는가",
                 "모델이 본문에 없다고 적은 것(not_in_story)을 소재로 삼았는가",
                 "중심 소재가 하나라도 남는가"]
THEME_NOT_CHECKED = ["그림이 이 장의 주제를 잘 나타내는가 (뜻) — 낱말이 나오는 곳과 이어짐으로만 어림한다",
                     "낱말 없이 뜻으로만 드러나는 부정 · 정정, 위 문형 밖의 부정",
                     "뜻이 다른 같은 낱말 (말 — 탈 것 · 말씀)",
                     "고유한 인물 이름 · 상표 · 랜드마크 (그림 양식이 그리지 말라고 적을 뿐 코드가 찾지 못한다)",
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
    """모델에 줄 자료 — 그 장의 본문 전체(문단 번호를 붙여)와 그 장이 근거로 쓰는 원문 말씀. 다른 장 · 사진 단서는 싣지 않는다."""
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
    """모델 응답 → 계획. 모양이 틀리면 IllustError("model_output"). 빠진 칸을 지어내지 않는다."""
    try:
        out = json.loads(reply) if isinstance(reply, str) else reply
    except (TypeError, ValueError) as e:
        raise il.IllustError("model_output", f"JSON 이 아니다 ({type(e).__name__})") from e
    if isinstance(out, dict) and isinstance(out.get("chapters"), list):
        pick = [c for c in out["chapters"] if isinstance(c, dict) and (chapter_no is None or c.get("chapter_no") == chapter_no)]
        out = pick[0] if pick else (out["chapters"][0] if out["chapters"] else None)
    if not isinstance(out, dict):
        raise il.IllustError("model_output", "계획이 객체가 아니다")
    theme = _text(out.get("theme"), THEME_MAX)
    if not theme:
        raise il.IllustError("model_output", "theme 이 비었다")
    subjects = []
    for s in out.get("subjects") or []:
        if not isinstance(s, dict) or not _text(s.get("text"), TEXT_MAX):
            continue
        kind = s.get("kind") if s.get("kind") in KINDS else "object"
        subjects.append({"text": _text(s.get("text"), TEXT_MAX), "kind": kind,
                         "kind_from_model": s.get("kind"), "role": "main" if s.get("role") == "main" else "sub",
                         "anchor": _text(s.get("anchor"), TEXT_MAX)})
    if not subjects:
        raise il.IllustError("model_output", "subjects 가 비었다")
    supports = [{"point": _text(x.get("point"), THEME_MAX),
                 "paragraphs": [p for p in x.get("paragraphs") or [] if isinstance(p, int) and not isinstance(p, bool)]}
                for x in out.get("supports") or [] if isinstance(x, dict) and _text(x.get("point"), THEME_MAX)]
    return {"chapter_no": out.get("chapter_no"), "theme": theme,
            "theme_short": _text(out.get("theme_short"), SHORT_MAX) or theme[:SHORT_MAX],
            "mood": _text(out.get("mood"), MOOD_MAX), "period": _text(out.get("period"), PERIOD_MAX),
            "supports": supports, "subjects": subjects[:MAX_SUBJECTS],
            "composition": _text(out.get("composition"), COMPOSITION_MAX),
            "not_in_story": [x.strip() for x in out.get("not_in_story") or [] if isinstance(x, str) and x.strip()]}


# ---------------------------------------------------------------- 검사

def _pattern(word: str) -> re.Pattern | None:
    key = il._compact(word)
    if not key:
        return None
    return re.compile(r"\s*".join(re.escape(ch) for ch in key))


def _tail_ok(run: str) -> bool:
    """낱말 바로 뒤에 붙은 한글 덩어리가 조사 · 서술격 어미뿐인가 (또는 「하다 · 되다」 로 그 낱말을 하는 일인가)."""
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
    """
    낱말이 나오는 자리 — 앞이 낱말 경계이고, 뒤에는 조사 · 어미만 붙은 곳. 「카페인 · 비서가(서가) · 산책(산) · 배낭여행(배낭)」 은
    그 낱말이 아니다. 특정 낱말을 따로 다루지 않는다 — 모든 낱말에 같은 규칙이다.
    """
    pat = _pattern(word)
    if pat is None:
        return []
    out = []
    for m in pat.finditer(text):
        before = text[m.start() - 1] if m.start() > 0 else " "
        if _HANGUL.match(before):
            continue
        run = re.match(r"[가-힣]*", text[m.end():]).group(0)
        if _tail_ok(run):
            out.append(m)
    return out


def _negation_at(text: str, m: re.Match) -> str | None:
    """그 낱말에 걸린 부정 문형 — 낱말 바로 뒤부터 같은 마디 안에서만 본다. 걸리면 문형 이름, 아니면 None."""
    rest = text[m.end():]
    end = _CLAUSE_END.search(rest)
    rest = rest[:end.start()] if end else rest
    return next((name for name, pat in _NEG_PATTERNS if pat.search(rest)), None)


def anchor_stats(word: str | None, ch: dict, utts: list[dict]) -> dict:
    """낱말이 장의 어디에 몇 번, 어떤 꼴로 나오는가. 횟수 · 문단은 참고 정보다 — 통과 조건으로 쓰지 않는다."""
    out = {"word": word, "mentions": 0, "paragraphs": [], "affirmed": 0, "negated": 0, "negations": [], "title": False,
           "in_source": False}
    if not word or _pattern(word) is None:
        return out
    paras = set()
    for i, p in enumerate(ch["paragraphs"]):
        for m in _hits(word, p):
            out["mentions"] += 1
            paras.add(i)
            neg = _negation_at(p, m)
            if neg:
                out["negated"] += 1
                out["negations"].append({"paragraph": i, "form": neg, "text": p[m.start():m.start() + 30]})
            else:
                out["affirmed"] += 1
    out["paragraphs"] = sorted(paras)
    out["title"] = bool(_hits(word, ch["title"]))
    out["in_source"] = any(_hits(word, u["elder"]) for u in utts)
    return out


def _links(word: str, plan: dict, st: dict, n_paras: int) -> list[str]:
    """그 낱말이 제목 · 주제 · 뒷받침 내용 · 뒷받침이 가리킨 문단 가운데 어디와 이어지는가."""
    out = []
    if st["title"]:
        out.append("title")
    if _hits(word, " ".join(x for x in (plan["theme"], plan["theme_short"]) if x)):
        out.append("theme")
    if any(_hits(word, s["point"]) for s in plan["supports"]):
        out.append("support_point")
    cited = {p for s in plan["supports"] for p in s["paragraphs"] if 0 <= p < n_paras}
    if cited & set(st["paragraphs"]):
        out.append("support_paragraph")
    return out


def _grounding(s: dict, st: dict, links: list[str], n_paras: int) -> tuple[bool, str]:
    """
    중심 소재로 인정하는가 — 본문(또는 제목)에 실제로 나오고, 제목 · 주제 · 뒷받침과 이어지면 된다. 횟수 · 비율은 따지지 않는다.
    본문에 없이 제목에만 있으면 주제나 뒷받침이 그것을 다룰 때만 (비유적 제목만으로는 아니다).
    """
    ref = f"참고: 본문 {st['mentions']}번 · 문단 {len(st['paragraphs'])}/{n_paras}"
    if not s["anchor"]:
        return False, "본문 낱말(anchor)이 없다 — 꾸밈 표현"
    if st["mentions"] and not st["affirmed"]:
        return False, f"본문에서 그 낱말에 걸린 부정으로만 나온다 ({ref})"
    if not links:
        return False, f"제목 · 주제 · 뒷받침 어디와도 이어지지 않는다 — 곁들이는 소재로만 ({ref})"
    if not st["mentions"]:
        if st["title"] and set(links) - {"title"}:
            return True, f"제목에 있고 {' · '.join(x for x in links if x != 'title')} 와 이어진다 (본문에는 없다)"
        return False, "제목에만 있고 주제 · 뒷받침과 이어지지 않는다 — 비유적 제목일 수 있다"
    return True, f"본문에 있고 {' · '.join(links)} 와 이어진다 ({ref})"


def _unsupported(text: str | None, known: str) -> list[str]:
    """본문 · 원문에 없는 관계 낱말 · 숫자."""
    if not text:
        return []
    bad = [f"relation:{r}" for r in RELATIONS if r in text and r not in known]
    # 「형」 같은 한 글자 관계는 다른 낱말 안(형태 · 모형)에서 걸리지 않게 낱말 경계로 다시 본다
    bad = [b for b in bad if len(b.split(":")[1]) > 1 or _hits(b.split(":")[1], text)]
    bad += [f"number:{d}" for d in re.findall(r"\d+", text) if d not in known]
    return bad


def theme_checks(data: dict, ident, plan: dict) -> dict:
    """계획을 본문에 비춰 본다. 소재를 빼기는 해도 고쳐 쓰지는 않는다."""
    ctx = il.check_input(data)
    ch = _chapter(data, ident)
    utts = _chapter_utts(ctx, ch)
    known = " ".join([ch["title"], *ch["paragraphs"], *[u["elder"] for u in utts]])
    n_paras = len(ch["paragraphs"])
    banned_listed = [il._compact(x) for x in plan["not_in_story"]]
    kept, dropped, negated_words = [], [], []
    for s in plan["subjects"]:
        st = anchor_stats(s["anchor"], ch, utts)
        links = _links(s["anchor"], plan, st, n_paras) if s["anchor"] else []
        central, why = _grounding(s, st, links, n_paras)
        row = {**s, "anchor_stats": st, "links": links, "central": central, "central_basis": why,
               "repeat_reference": {"mentions": st["mentions"], "paragraphs": len(st["paragraphs"]), "of": n_paras}}
        bad = _unsupported(s["text"], known)
        if il._BANNED_LABEL.search(s["text"]):
            bad.append("banned_label")
        cs = il._compact(s["text"])
        # 모델이 「본문에 없다」 고 적은 것 그 자체를 소재로 삼았을 때만 — 긴 설명문 안에 같은 글자가 있다고 빼지 않는다
        if any(b and (b == cs or (len(b) >= 2 and b in cs)) for b in banned_listed):
            bad.append("listed_not_in_story")
        if s["anchor"] and not st["mentions"] and not st["title"]:
            bad.append("anchor_not_in_chapter")            # 「본문 · 제목에 그대로 나오는 낱말」 이라 했는데 어디에도 없다
        elif s["anchor"] and not st["mentions"] and not central:
            bad.append("title_only_not_supported")         # 제목에만 있고 주제 · 뒷받침과 이어지지 않는다
        if st["mentions"] and not st["affirmed"]:
            bad.append("negated_in_chapter")
            negated_words.append(s["anchor"])
        if bad:
            dropped.append({**row, "dropped": bad})
        else:
            kept.append(row)
    blocking, notes = [], []
    theme_text = " ".join(x for x in (plan["theme"], plan["theme_short"]) if x)
    if any(w and _hits(w, theme_text) for w in negated_words):
        blocking.append("theme_negated")
    if [b for b in _unsupported(theme_text, known) if b.startswith("relation:")]:
        blocking.append("theme_adds_relation")
    composition = plan["composition"]
    comp_bad = _unsupported(composition, known) + (["banned_label"] if composition and il._BANNED_LABEL.search(composition) else [])
    if composition and any(w and _hits(w, composition) for w in negated_words):
        comp_bad.append("negated_subject")
    if comp_bad:
        notes.append({"composition_dropped": comp_bad})
        composition = None
    period = plan["period"] if plan["period"] and il._compact(plan["period"]) in il._compact(known) else None
    if plan["period"] and not period:
        notes.append({"period_dropped": "본문에 그 말이 없다"})
    central = [s for s in kept if s["central"]]
    if not central:
        blocking.append("no_central_subject")
    cited = [p for x in plan["supports"] for p in x["paragraphs"]]
    covered = sorted({p for p in cited if 0 <= p < n_paras})
    thirds = sorted({min(2, p * 3 // max(n_paras, 1)) for p in covered})
    checks = [{"check": "central_subject", "ok": bool(central),
               "detail": [{"text": s["text"], "anchor": s["anchor"], "links": s["links"], "basis": s["central_basis"]} for s in kept]},
              {"check": "not_negated", "ok": "theme_negated" not in blocking,
               "detail": [{"text": d["text"], "anchor": d["anchor"], "forms": d["anchor_stats"]["negations"]}
                          for d in dropped if "negated_in_chapter" in d["dropped"]]},
              {"check": "no_new_relation_or_number", "ok": "theme_adds_relation" not in blocking,
               "detail": [{"text": d["text"], "why": d["dropped"]} for d in dropped if any(":" in w for w in d["dropped"])]},
              # 아래 둘은 참고 정보 — 막지 않는다
              {"check": "supports_spread", "ok": True, "blocking": False,
               "detail": {"paragraphs": covered, "cited_but_missing": sorted({p for p in cited if not 0 <= p < n_paras}),
                          "parts_of_chapter": len(thirds), "of": min(3, n_paras)}},
              {"check": "repeat_reference", "ok": True, "blocking": False,
               "detail": [{"text": s["text"], **s["repeat_reference"]} for s in kept + dropped]}]
    return {"policy": POLICY, "chapter_no": ch["no"], "accept": not blocking, "blocking": blocking, "notes": notes,
            "theme": plan["theme"], "theme_short": plan["theme_short"], "mood": plan["mood"], "period": period,
            "supports": plan["supports"], "composition": composition, "composition_from_model": plan["composition"],
            "subjects": kept, "dropped": dropped, "not_in_story": plan["not_in_story"], "checks": checks}


# ---------------------------------------------------------------- 그림 지시문 · 자리

def build_theme_prompt(chk: dict) -> dict:
    """확인을 지난 계획과 고정 양식(v2)만으로 조립한다. 본문에 없다고 적힌 것(not_in_story)은 지시문에 넣지 않는다."""
    blocks = style_blocks()
    central = [s for s in chk["subjects"] if s["central"]]
    main = [s for s in central if s["role"] == "main"][:MAX_MAIN] or central[:MAX_MAIN]
    sub = [s for s in chk["subjects"] if s not in main][:MAX_SUB]
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
        return build_theme_prompt({**chk, "subjects": main + sub[:-1]})
    return {"style_id": STYLE_ID, "language": "ko", "policy": POLICY, "text": text, "scene_block": block,
            "elements_used": [s["text"] for s in main + sub],
            "composition": {"main": [s["text"] for s in main], "sub": [s["text"] for s in sub],
                            "layout": chk["composition"] or DEFAULT_COMPOSITION,
                            "layout_from": "model" if chk["composition"] else "default",
                            "facts": [{"text": s["text"], "anchor": s["anchor"], "paragraphs": s["anchor_stats"]["paragraphs"]}
                                      for s in main + sub if s["anchor"]],
                            "expression": [s["text"] for s in main + sub if not s["anchor"]]}}


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
    base = {"policy": POLICY, "mode": MODE, "automatic": True, "human": "not_reviewed"}
    try:
        plan = parse_plan(reply, ch["no"])
    except il.IllustError as e:
        return {**base, "status": "failed", "reasons": ["model_output"], "detail": e.message, "tried": []}
    chk = theme_checks(data, ident, plan)
    tried = [{"candidate_index": 0, "scene_title": plan["theme_short"], "mode": MODE, "accepted": chk["accept"],
              "blocking": chk["blocking"]}]
    verdict = {"policy": POLICY, "accept": chk["accept"], "blocking": chk["blocking"],
               "checked": THEME_CHECKED, "not_checked": THEME_NOT_CHECKED}
    if not chk["accept"]:
        why = {"no_central_subject": "본문(또는 제목)에 나오고 주제 · 뒷받침과 이어지는 소재를 찾지 못했다 — 지어내서 채우지 않는다",
               "theme_negated": "주제가 본문이 부정하는 것을 쓴다", "theme_adds_relation": "주제가 본문에 없는 관계를 만든다"}
        return {**base, "status": "failed", "reasons": chk["blocking"],
                "detail": " · ".join(why.get(b, b) for b in chk["blocking"]), "theme": chk, "verdict": verdict, "tried": tried}
    prompt = build_theme_prompt(chk)
    turns = sorted(set(ch["turns"]) | set(ch["chapter_turns"]))
    return {**base, "status": "selected", "source": "theme_plan", "candidate_index": 0,
            "scene": {"scene_title": plan["theme_short"], "scene_summary": plan["theme"], "central_action": None,
                      "source_turns": turns, "source_refs": [],
                      "evidence": [{"kind": s["kind"], "text": s["text"], "anchor": s["anchor"],
                                    "paragraphs": s["anchor_stats"]["paragraphs"], "central": s["central"]} for s in chk["subjects"]],
                      "not_used": [{"kind": d["kind"], "text": d["text"], "why": d["dropped"]} for d in chk["dropped"]],
                      "dropped_for_picture": []},
            "prompt": prompt, "placement": theme_placement(data, ident), "auto_checks": chk["checks"],
            "tolerated_reasons": [], "theme": chk, "verdict": verdict, "tried": tried,
            "choice_reason": f"주제 방식 — 중심 소재 {', '.join(prompt['composition']['main'])} 가 본문에 나오고 주제 · 뒷받침과 이어진다"}
