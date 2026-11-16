"""
자서전 5단계의 ③ 집필 — 문체(수필체 · 문학체 · 소설체)로 쓰는 장 초안

    ① 분석 → ② 목차 → **③ 집필(문체)** → ④ 편집 → ⑤ 검증        memoir_pipeline.run(style=…)

분석 · 목차 · 편집 · 검증은 공통(구어체와 같은 지시문 · 같은 검사)이고, 달라지는 것은 ③ 뿐이다.
이 모듈은 ③ 에 필요한 것만 가진다 — 전체 생성 경로가 아니다. 혼자서는 책을 만들지 않는다.

    입력   공통 분석(사실 원장) · 목차의 장 설계 · 그 장의 원문        → 문체 프롬프트의 사용자 메시지
    호출   Claude 한 번 (장마다) — memoir_novel._call · memoir_styled._call 을 그대로 쓴다
    출력   문체가 낸 글 → 편집이 받는 공통 초안 {chapter_key, title, paragraphs[[{text, kind, facts}]], review_notes}

**문체 프롬프트는 고치지 않는다.** 소설체는 `{{SOURCE_TEXT}}` 한 군데에 그 장의 원문을 넣고, 수필체 · 문학체는
참조 구현(문체/reference/bundle_reference.py)으로 장 자료 묶음을 만든다. 모델 · effort · 출력 상한도
memoir_novel · memoir_styled 의 설정 그대로다.

**공통 분석 → 묶음 (bundle_book).** 수필체 · 문학체의 묶음은 문체 전용 분석(문체/analysis)의 모양을 받는다.
공통 분석(v7)에서 **있는 것만** 옮기고, 없는 것은 지어내지 않고 비운다.

    옮기는 것   사실 원장(id · source · certainty · text — 그 장 문단 계획의 사실) · 반드시 남길 세부(keep · core)
                · 들은 이야기(source=heard) · 때(사실의 time) · 인물(분석의 people 가운데 그 원문에 이름이 나오는 사람)
                · 이야기 이름(기억 단위의 name) · 원문의 따옴표 인용 · 장의 중심(center) · 핵심 경험(experience)
    비우는 것   감정 기록(emotion_notes — 누구 · 대상 · 세기 · 명시 여부) · 지금의 회고(reflections_now) · 곳(places)
                · 장의 중심 감정(emotion) · 픽션 허용 메모(fiction_notes)   ← 공통 분석에 그런 칸이 없다
    감정 · 회고는 사실 원장의 줄로는 그대로 간다 (분석이 사실로 적은 만큼). 비운 칸은 MISSING_FIELDS 에 적어 둔다.

**초안의 근거 표시 (to_draft).** 근거를 지어 달지 않는다.
    수필체 · 문학체   문체 출력의 facts[{id, where}] — 모델이 「이 사실을 여기에 썼다」 고 적은 것 — 가 가리키는 문장만
                      supported + 그 사실 id. 그 장에 준 사실이 아닌 id 는 버린다. 나머지 문장은 editorial(facts []).
    소설체           출력에 사실 표시가 없다 → 모든 줄이 editorial(facts []). 줄 하나가 문단 하나다 (대사 줄을 합치지 않는다).
    editorial 은 「근거를 달지 않은 문장」 이라는 뜻일 뿐이다. 사실 원장과의 대조 · 근거 달기는 ④ 편집이 하고
    (편집 계약: supported 는 facts 필수 · editorial 은 facts []), 원문과의 대조는 ⑤ 검증이 한다.

**편집 · 검증에 붙이는 문체 조건** (edit_note · verify_note). 공통 편집 지시문은 「담백한 1인칭 회고 수필체로 문체 통일」 을
요구한다 — 그대로 두면 소설체 · 문학체가 사라진다. 지시문 파일은 고치지 않고(구어체는 글자까지 그대로), 문체 실행에서만
시스템 프롬프트 끝에 이 조건을 덧붙인다.

**편집 전후 비교 (style_trace).** 분량 · 문단 · 따옴표 대화 · 그대로 남은 초안 문장의 비율을 코드가 잰다. 문학적 품질의
판정이 아니다 — 크게 줄었을 때 사람이 보라는 신호다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from . import memoir_novel, memoir_styled
from .conf import env_str

STYLES = ("essay", "literary", "novel")
NAMES = {"essay": "수필체", "literary": "문학체", "novel": "소설체"}
FEATURES = {
    "essay": "문장의 리듬과 회고의 어조, 문단의 호흡",
    "literary": "서정적인 표현 · 이미지 · 비유, 길고 짧은 문장의 배치, 문단 안의 줄 나눔",
    "novel": "장면 구성 · 따옴표 대화 · 대사마다 줄을 바꾼 문단(문단 하나가 한 줄이다)",
}
# 공통 분석(v7)에 없어 문체 묶음에서 비우는 칸 — 보고 · 실행 기록용
MISSING_FIELDS = ("stories[].emotion_notes", "stories[].reflections_now", "stories[].places",
                  "chapters[].emotion", "chapters[].fiction_notes")
_NOT_GIVEN = "공통 분석에 따로 정한 것이 없다 — 원문과 사실 원장, 문체 지시문의 기준을 따른다"
_QUOTE = re.compile(r"“[^”]+”|\"[^\"]+\"|‘[^’]+’|「[^」]+」")
_OPEN_QUOTE = ("“", '"', "‘", "「", "『")


@dataclass
class StyleCall:
    """문체 집필 호출 하나. schema 가 None 이면 소설체 (시스템 없음 · 출력 형식 강제 없음)."""
    style: str
    chapter_key: str
    system: str | None
    user: str
    schema: dict | None
    model: str
    max_tokens: int
    effort: str
    timeout: float


StyleCaller = Callable[[StyleCall], Awaitable[tuple[str, dict]]]      # (글, {"stop", "model", "input", "output"})


class Claude:
    """기본 호출 — memoir_novel._call · memoir_styled._call 그대로. 실행 하나에 클라이언트 하나, 다시 부르지 않는다."""

    def __init__(self):
        self._client = None

    async def __call__(self, spec: StyleCall) -> tuple[str, dict]:
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=env_str("ANTHROPIC_API_KEY", ""), max_retries=1)
        if spec.schema is None:
            return await memoir_novel._call(self._client, spec.user, {
                "MEMOIR_NOVEL_MODEL": spec.model, "MEMOIR_NOVEL_MAX_TOKENS": spec.max_tokens, "MEMOIR_NOVEL_EFFORT": spec.effort})
        return await memoir_styled._call(self._client, spec.system, spec.user, spec.schema, spec.model, spec.max_tokens, spec.effort)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


def ready() -> str | None:
    """문체 집필을 부를 수 있나 — 못 부르면 까닭. 분석을 부르기 전에 본다 (앞 단계 비용을 쓰고 멈추지 않게)."""
    return None if env_str("ANTHROPIC_API_KEY", "") else "ANTHROPIC_API_KEY 가 없다 — 문체 집필은 Claude 로 쓴다"


def timeout(style: str) -> float:
    return memoir_novel.settings()["MEMOIR_NOVEL_TIMEOUT"] if style == "novel" else memoir_styled.settings(style)["timeout"]


def parallel(style: str) -> int:
    return memoir_novel.settings()["MEMOIR_NOVEL_PARALLEL"] if style == "novel" else memoir_styled.settings(style)["parallel"]


# ---------------------------------------------------------------- 공통 분석 · 목차 → 문체의 입력

def stories(src: dict, analysis: dict | None = None, chapter: dict | None = None) -> dict[int, str]:
    """
    그 장의 원문 — {전역 턴: 어르신 말씀}. 목차의 문단 계획 순서 (chapter_source 가 놓은 순서) 그대로.

    **일부를 빼 달라고 한 말씀(exclusions 의 partial 턴)은 원문 그대로 주지 않는다.** 문체 프롬프트에는 「이 부분은 쓰지 말라」 를
    전할 자리가 없다(소설체는 원문 한 군데뿐) — 원문을 그대로 주면 빼 달라고 한 내용과 그 요청의 말이 초안에 들어갈 수 있다.
    그 말씀은 분석이 사실로 남긴 메모(빼 달라고 한 내용은 사실로 쓰지 않는다 — 분석 지시문 15)로 바꿔 준다. 이 장에 놓인
    사실이 없으면 그 말씀은 주지 않는다. 통째로 뺀 턴은 chapter_source 가 이미 뺐다. 편집 · 검증은 제외 알림을 그대로 받는다.
    """
    from . import memoir_pipeline as mp

    notes = (analysis or {}).get("exclusions") or []
    partial = {t for x in notes if x.get("mode") == "partial" for t in (x.get("turns") or [])}
    mine = set(mp.plan_facts(chapter)) if chapter else None
    out: dict[int, str] = {}
    for u in src["utterances"]:
        text = (u.get("elder") or "").strip()
        if text and u["turn"] in partial:
            text = "\n".join(f["text"] for f in (analysis or {}).get("facts", [])
                             if u["turn"] in f.get("turns", []) and (mine is None or f["id"] in mine))
        if text:
            out[u["turn"]] = text
    return out


def bundle_book(analysis: dict, outline_out: dict, chapter_stories: dict[str, dict[int, str]]) -> dict:
    """
    공통 분석 + 목차 → 수필체 · 문학체 묶음이 받는 분석 모양 (문체/schemas/analysis_output.schema.json 의 칸).
    있는 것만 옮긴다 — 없는 칸은 빈 목록이거나 _NOT_GIVEN 이다. 장 id 는 목차 순서대로 c1 · c2 ….
    """
    from . import memoir_pipeline as mp

    ledger = mp.ledger(analysis)
    keep = mp.must_keep(analysis) | set(mp.plan_core(outline_out))
    unit_name = {f: u.get("name", "") for u in analysis.get("units", []) for f in u.get("facts", [])}
    people = [p for p in analysis.get("people", []) if isinstance(p, dict) and str(p.get("name", "")).strip()]
    out_stories, chapters = [], []
    plans = outline_out["chapters"]
    for no, ch in enumerate(plans, start=1):
        st = chapter_stories[ch["chapter_key"]]
        first: dict[int, list[dict]] = {t: [] for t in st}
        for f in mp.plan_facts(ch):
            fact = ledger.get(f)
            at = next((t for t in (fact or {}).get("turns", []) if t in first), None)
            if at is not None:                                # 사실은 그 장 원문 가운데 처음 나온 이야기 밑에 한 번만
                first[at].append(fact)
        for t, text in st.items():
            facts = first[t]
            out_stories.append({
                "turn": t,
                "title_hint": next((unit_name[f["id"]] for f in facts if unit_name.get(f["id"])), ""),
                "facts": [{"id": f["id"], "source": f["source"], "certainty": f["certainty"], "text": f["text"]} for f in facts],
                "must_keep": [f["text"] for f in facts if f["id"] in keep],
                "emotion_notes": [], "reflections_now": [], "places": [],
                "people": [f"{p['name']}({p['relation']})" if p.get("relation") else p["name"] for p in people if p["name"] in text],
                "time": list(dict.fromkeys(f["time"] for f in facts if f.get("time"))),
                "heard": [f["text"] for f in facts if f["source"] == "heard"],
                "quotes": [m.group(0) for m in _QUOTE.finditer(text)],
            })
        others = [f"{c['chapter_key']} 「{c['title']['text']}」 — {c['center']}" for c in plans if c is not ch]
        chapters.append({"id": f"c{no}", "title": ch["title"]["text"], "stories": list(st),
                         "center_scene": ch.get("experience", ""), "direction": ch.get("center", ""),
                         "emotion": _NOT_GIVEN, "fiction_notes": _NOT_GIVEN,
                         "avoid_overlap": " / ".join(others) if others else "다른 장이 없다"})
    return {"book_title": outline_out["book"]["title"]["text"], "stories": out_stories, "chapters": chapters}


def call_spec(style: str, key: str, cid: str, st: dict[int, str], book: dict | None) -> StyleCall:
    """그 장의 문체 호출 — 프롬프트 · 모델 설정은 memoir_novel · memoir_styled 의 것 그대로."""
    if style == "novel":
        s = memoir_novel.settings()
        return StyleCall(style, key, None, memoir_novel.user_message("\n\n".join(st.values())), None, s["MEMOIR_NOVEL_MODEL"],
                         s["MEMOIR_NOVEL_MAX_TOKENS"], s["MEMOIR_NOVEL_EFFORT"], s["MEMOIR_NOVEL_TIMEOUT"])
    s = memoir_styled.settings(style)
    system, _ = memoir_styled.prompt(style)
    return StyleCall(style, key, system, memoir_styled.style_message(style, book, st, cid),
                     memoir_styled.schema(memoir_styled.STYLES[style]["schema"]), s["model"], s["max_tokens"], s["effort"], s["timeout"])


def prompt_sha(style: str) -> str:
    return (memoir_novel.template()[1] if style == "novel" else memoir_styled.prompt(style)[1])[:16]


# ---------------------------------------------------------------- 문체의 출력 → 편집이 받는 초안

def to_draft(style: str, chapter: dict, out, allowed: set[str]) -> tuple[dict, dict]:
    """
    (초안, 기록). out 은 소설체면 본문 글, 수필체 · 문학체면 문체 스키마의 JSON 이다.
    기록 — {"marked": 근거를 단 문장 수, "unmarked": 달지 않은 문장 수, "dropped_marks": 버린 표시, "adaptations": 각색 기록}.
    문단이 하나도 없으면 ValueError.
    """
    paras: list[list[dict]] = []
    info = {"marked": 0, "unmarked": 0, "dropped_marks": [], "adaptations": []}
    if style == "novel":
        for ln in str(out).splitlines():
            if ln.strip():
                paras.append([{"text": ln.strip(), "kind": "editorial", "facts": []}])
    else:
        if not isinstance(out, dict):
            raise ValueError("문체 출력이 객체가 아니다")
        marks = []
        for x in out.get("facts") or []:
            fid, where = (x or {}).get("id"), memoir_styled.norm(str((x or {}).get("where") or ""))
            if fid in allowed and where:
                marks.append((where[:20], fid))
            elif fid is not None:
                info["dropped_marks"].append(str(fid)[:12])
        for para in out.get("paragraphs") or []:
            for line in str(para).splitlines():
                row = []
                for s in memoir_styled.split_sentences(line):
                    bare = memoir_styled.norm(s)
                    fs = list(dict.fromkeys(f for w, f in marks if w in bare))
                    row.append({"text": s, "kind": "supported" if fs else "editorial", "facts": fs})
                if row:
                    paras.append(row)
        info["adaptations"] = [f for f in out.get("fiction") or [] if isinstance(f, dict)]
    if not paras:
        raise ValueError("문체 출력에 본문이 없다")
    flat = [s for p in paras for s in p]
    info["marked"] = sum(1 for s in flat if s["facts"])
    info["unmarked"] = len(flat) - info["marked"]
    title = {"text": chapter["title"]["text"], "kind": chapter["title"].get("kind", "editorial"),
             "facts": list(chapter["title"].get("facts") or [])}
    return {"chapter_key": chapter["chapter_key"], "title": title, "paragraphs": paras, "review_notes": []}, info


# 문체 초안에는 대지 않는 코드 판정 — 「인용 밖 서술은 ~다 로 끝난다」 는 1인칭 회고 수필체(구어체 책)의 규칙이다
RULES_OFF = ("style_mix",)
# 근거 표시가 없는 초안(소설체)에는 「사실이 본문에 없다」 를 대지 않는다 — 없는 것은 표시이지 내용이 아니다. 편집본에는 댄다
UNMARKED_RULES_OFF = ("must_keep_missing", "core_missing")


def draft_checks(findings: list[dict], marked: bool) -> list[dict]:
    off = RULES_OFF + (() if marked else UNMARKED_RULES_OFF)
    return [f for f in findings if f.get("rule") not in off]


def final_checks(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f.get("rule") not in RULES_OFF]


# ---------------------------------------------------------------- ④ 편집 · ⑤ 검증에 붙이는 문체 조건

def edit_note(style: str) -> str:
    name, feature = NAMES[style], FEATURES[style]
    return (
        f"\n\n[문체 조건 — 이번 원고는 {name}로 쓴 초안입니다. 아래는 위 지시 가운데 문체에 관한 부분을 이 원고에 한해 바꿉니다]\n"
        f"- 「담백한 1인칭 회고 수필체」 와 「문체 통일」 은 적용하지 않습니다. 초안의 문체를 지킵니다 — {feature}. "
        "style_mix 를 이유로 서술을 고치지 않습니다.\n"
        "- 요약문 · 설명문으로 바꾸지 않습니다. 고쳐 쓰는 것은 원문과 어긋난 사실 · 겹친 내용 · 끊긴 흐름을 바로잡을 때로 한정하고, "
        "그 밖의 문장 · 문단 나눔 · 줄 나눔은 초안 그대로 둡니다. 분량을 줄이는 것이 목적이 아닙니다.\n"
        "- 장의 수와 순서는 초안 그대로 둡니다 (합치거나 나누지 않습니다).\n"
        "- 초안 문장의 kind · facts 는 집필 단계가 달지 않았거나 일부만 단 것입니다 (소설체는 모든 문장이 editorial 로 들어옵니다). "
        "편집본에서는 문장마다 사실 원장 · 원문과 대조해, 원장의 사실을 전하는 문장은 supported 와 그 사실 id 로, 원문에 근거가 없는 "
        "장면 묘사 · 가상 대화 · 잇는 말은 editorial(facts [])로 적습니다. 근거가 없는 문장에 사실 id 를 달지 않습니다.\n"
        "- 원문에 없는 사건 · 인물 · 결과를 새로 넣지 않습니다. 초안에 원문과 어긋나는 사실(이름 · 수 · 때 · 결과 · 부정 · 고쳐 말한 값)이 "
        "있으면 원문대로 바로잡고 diagnosis 에 적습니다. 뜻을 확정할 수 없는 원문 표현은 짐작해 고치지 않습니다."
    )


def verify_note(style: str) -> str:
    name, feature = NAMES[style], FEATURES[style]
    return (
        f"\n\n[문체 조건 — 검증할 원고는 {name}입니다]\n"
        f"- {feature}은 이 문체의 특징입니다. 그것만으로 composition 문제(style_mismatch 등)로 적거나 점수를 낮추지 않습니다.\n"
        "- editorial 문장의 장면 묘사 · 가상 대화는 문학적 각색으로 봅니다. 다만 그 안에 원문에 없는 인물 · 중요한 사건 · 행동의 결과 · "
        "수 · 때 · 이름이 사실처럼 들어 있거나, 원문의 부정 · 고쳐 말한 값 · 불확실하다는 말 · 감정과 회고의 시점 · 인물의 동기가 "
        "달라졌으면 fact 문제로 적습니다 (editorial_misuse · unsupported_claim · source_mismatch · time_distortion · identity_inference).\n"
        "- 원문에 분명히 있는 사건이 원고에서 빠졌으면 material_omission 으로, 인터뷰 진행 잡담이 본문에 들어왔으면 unsupported_claim 으로 적습니다.\n"
        "- 받아 적기가 틀린 듯해 뜻을 확정할 수 없는 원문 표현이 원고에 쓰였으면 고쳐 적지 말고 resolution \"ask_user\" 로 남깁니다."
    )


# ---------------------------------------------------------------- 편집 전후 비교 (코드가 잰다)

def _stats(chapters: list[dict]) -> dict:
    sents = [s["text"] for ch in chapters for p in ch["paragraphs"] for s in p]
    return {"chars": sum(len(re.sub(r"\s", "", t)) for t in sents), "chapters": len(chapters),
            "paragraphs": sum(len(ch["paragraphs"]) for ch in chapters), "sentences": len(sents),
            "dialogue": sum(1 for t in sents if any(q in t for q in _OPEN_QUOTE))}


CHARS_KEPT_MIN = 0.7          # 편집본 글자가 초안의 이 비율 아래면 알린다
DIALOGUE_KEPT_MIN = 0.6       # 따옴표 대화가 든 문장 (초안에 셋 이상일 때)
SENTENCES_KEPT_MIN = 0.5      # 글자까지 그대로 남은 초안 문장


def style_trace(style: str, drafts: list[dict], final: list[dict]) -> dict:
    """편집 전(문체 초안) · 후(편집본)의 분량과 겉모양. warnings 는 사람이 볼 신호다 — 품질 판정이 아니다."""
    a, b = _stats(drafts), _stats(final)
    after = {re.sub(r"\s", "", s["text"]) for ch in final for p in ch["paragraphs"] for s in p}
    before = [re.sub(r"\s", "", s["text"]) for ch in drafts for p in ch["paragraphs"] for s in p]
    kept = sum(1 for t in before if t in after) / len(before) if before else 0.0
    ratio = {"chars": round(b["chars"] / a["chars"], 3) if a["chars"] else 0.0,
             "dialogue": round(b["dialogue"] / a["dialogue"], 3) if a["dialogue"] else None,
             "sentences_unchanged": round(kept, 3)}
    warnings = []
    if ratio["chars"] < CHARS_KEPT_MIN:
        warnings.append(f"편집 뒤 분량이 초안의 {ratio['chars']:.0%} 다 — 장면 · 표현이 줄었는지 확인")
    if a["dialogue"] >= 3 and ratio["dialogue"] < DIALOGUE_KEPT_MIN:
        warnings.append(f"따옴표 대화가 든 문장이 {a['dialogue']} → {b['dialogue']} 로 줄었다")
    if b["chapters"] != a["chapters"]:
        warnings.append(f"장 수가 {a['chapters']} → {b['chapters']} 로 바뀌었다")
    if kept < SENTENCES_KEPT_MIN:
        warnings.append(f"초안 문장 가운데 그대로 남은 것이 {kept:.0%} 다 — {NAMES[style]}가 지켜졌는지 사람이 본다")
    return {"style": style, "draft": a, "final": b, "ratio": ratio, "warnings": warnings,
            "note": "분량 · 겉모양만 잰다 — 문학적 품질의 판정이 아니다"}
