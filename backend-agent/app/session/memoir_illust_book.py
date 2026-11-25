"""
자서전 삽화 — 목차별 자동 처리 (서비스 연결부 memoir_illust_service 와 로컬 실행기 tools/memoir_illust_book 이 함께 쓴다)

    목차 항목마다   photo_states     그 항목 본문에 사진이 있는가 — 있음 · 없음(확인됨) · 모름
    사진 없는 항목  choose_by        대표 그림 하나 — 방식(정책)에 따라
                      theme (기본)   목차 주제 삽화 chapter_theme_v2 — 장 전체의 주제와 분위기 (memoir_illust_theme.choose_theme).
                                     뜻은 모델이 판단하고, 코드는 응답 모양 · 주제와 소재의 존재만 본다 (낱말 검사로 막지 않는다)
                      scene          장면 재현 scene_v5 — 아래 choose. 모델 후보와 사람을 뺀 후보를 모두 자동 검사하고, 이 항목의
                                     중심 내용(focus_map)을 가장 많이 담은 것을 고른다. 배경만 남은 후보는 고르지 않는다
                                     두 방식의 검사는 다르다. 결과의 policy 칸과 지시문 해시로 어느 방식의 결과인지 남는다
    삽입            insert_position  그 장면의 문단 뒤. 문단을 못 찾으면 그 항목의 끝
                    build_book       원고는 그대로 두고, 사진 · 삽화가 든 별도 결과를 만든다
                    render_markdown · render_html   사람이 볼 미리보기

**판단 단위는 장면이 아니라 목차 항목이다.** 항목에 사진이 한 장이라도 있으면 삽화를 넣지 않는다(장면이 좋고 나쁨을 따지지 않는다).
사진이 없는 것이 확인된 항목에는 한 장씩 넣는다. 책 전체에서 몇 개까지라는 한도가 없다.

**사람이 고르거나 승인하는 단계가 없다.** 그래서 앞선 실험의 「사람이 관계를 확인하기 전에는 생성용 지시문을 만들지 않는다」 를
자동 검사로 바꿨다 (auto_verdict). 자동으로 통과시킨 것을 사람이 확인한 것처럼 적지 않는다 — human 은 not_reviewed 그대로고,
automatic: true 와 무엇을 근거로 통과시켰는지를 따로 적는다. user_selected · user_approved 는 false 다.

    사람을 그리는 장면(SCENE)   사람마다 관계 칸과 근거 인용이 있고 그 인용이 원문에 있으며 중심 행동에 이어져야 한다(structure_ok).
                               「○○랑 둘이」 꼴로 원문에 나오는데 빠진 사람이 없어야 한다. 전언 · 정정 · 부정 · 불확실 표지가 풀리지 않은 채
                               남아 있으면 안 된다 — 사람의 확인으로만 풀리던 것(같은 문장의 부정)도 여기서는 풀리지 않는다.
                               근거 인용이 그 사람과 그 행동을 함께 받쳐야 한다 — 「제가」 한 낱말로는 안 된다(thin_relations).
    사람을 뺀 그림             사람을 그리는 후보마다 사람 · 행동을 빼고 그 후보의 사물 · 풍경만으로 그리는 상징 그림(SYMBOLIC)도 견줄 거리로 만든다.
    고르기                     통과한 후보 가운데 이 항목의 중심 요소(제목 · 본문으로 가린 것)를 가장 많이 담은 것.
                               「원문에 있다(인용 일치 · 본문 등장)」 와 「이 목차의 중심이다」 를 따로 적는다 — 본문에 한 번 지나간
                               사물 · 사람만 담은 후보는 대표가 아니다(focus_map).
                               모델이 적은 중심 내용(focus)은 제안으로 남길 뿐, 그것만으로 배경을 중심으로 올리지 않는다.
                               형식 검사는 통과했어도 곁가지 · 배경만 남은 후보는 고르지 않는다.
    없으면                     그 항목은 실패(failed) 또는 보류(held — 민감한 말씀)다. 지어내서 채우지 않는다.
                               사용자에게 장면을 고르라고 넘기지 않는다. 실패 · 보류가 하나라도 있으면 책은 complete 가 아니다.

이 파일은 모델도 이미지 API 도 부르지 않는다 — 받은 응답을 검사하고 조립할 뿐이다. 부르는 일과 파일은 tools/memoir_illust_book.py 가 한다.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json

from . import memoir_illust as il

SELECT_FILE = "1_장면선정_v5_목차중심.md"     # v4 는 2026-11-15 e01 실제 시험의 기록으로 남긴다
BOOK_SCHEMA = "illust-book-v1"
# 사람만 확인할 수 있어서 붙던 사유 — 자동 흐름에서는 그것만으로 막지 않는다(대신 아래 구조 검사를 통과해야 한다)
HUMAN_ONLY = ("person_relation_not_human_confirmed", "participants_completeness_not_human_confirmed")
# 요약에만 있는 사람(「어머니가 캐 오신 자루」 의 어머니) — 그 사람을 그리지 않고, 원문에 「○○랑 둘이」 꼴로도 없으면 막지 않는다.
# 그 꼴로 있으면 possible_participant_omitted 가 따로 붙어 막는다.
TOLERATED = HUMAN_ONLY + ("summary_person_not_in_elements",)
AUTO_NOTE = ("자동 검사다 — 사람이 확인한 것이 아니다. 코드는 관계 칸 · 근거 인용의 글자 일치 · 중심 행동과의 이음 · 표지 낱말만 본다. "
             "그 사람이 정말 그 행동을 했는지(뜻)는 보지 못한다")


def select_prompt() -> str:
    b = il._blocks(il.PROMPTS / SELECT_FILE)
    if not b.get("1"):
        raise il.IllustError("prompt_file", f"{SELECT_FILE} 에 §1 블록이 없다")
    return b["1"]


def prompt_hash() -> str:
    try:
        return hashlib.sha256((il.PROMPTS / SELECT_FILE).read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"


# ---------------------------------------------------------------- 방식 (정책) — 주제(기본) · 장면

# theme  목차 주제 삽화 (chapter_theme_v2 · memoir_illust_theme) — 장 전체의 주제와 분위기. 2026-11-18 부터 기본.
#        앞선 판 chapter_theme_v1(지시문 v6 · 낱말 검사로 막음)의 기록은 그 판 이름 그대로 남는다
# scene  장면 재현 (scene_v5 · 이 파일의 choose) — 한 장면을 원문 그대로. 기록 · 견주기용으로 남긴다
DEFAULT_POLICY = "theme"
POLICY_IDS = {"theme": "chapter_theme_v2", "scene": "scene_v5"}
SCENE_ART_STYLE = "watercolor"          # 장면 방식이 그리는 그림체 — 그림 양식 v1 하나 (그림체 선택은 주제 방식에만)
CHECKS_VERSIONS = {"theme": "theme_checks_v2", "scene": "scene_checks_v5"}


def _theme():
    from . import memoir_illust_theme
    return memoir_illust_theme


def check_policy(policy: str) -> str:
    if policy not in POLICY_IDS:
        raise il.IllustError("policy", f"모르는 방식이다: {policy!r} (쓸 수 있는 값: {', '.join(POLICY_IDS)})")
    return policy


def policy_of(selection: dict | None) -> str:
    """앞선 선정 결과가 어느 방식으로 만들어졌나. 방식 칸이 없는 결과는 장면 방식(이 변경 전)이다."""
    return "theme" if str((selection or {}).get("policy") or "").startswith("chapter_theme") else "scene"


def policy_files(policy: str, art_style: str | None = None) -> dict:
    """
    그 방식의 지시문 · 그림 양식 파일과 해시 — 결과에 남겨 다른 방식의 결과와 섞이지 않게 한다.
    주제 방식은 그림체(art_style · 없으면 수채화)의 파일 · 해시도 함께. 장면 방식(scene_v5)은 그림 양식 v1(수채화)만 그린다.
    """
    if check_policy(policy) == "theme":
        t = _theme()
        art = t.stored_art_style(art_style)
        return {"policy": policy, "policy_id": POLICY_IDS[policy], "checks_version": CHECKS_VERSIONS[policy],
                "select_prompt": t.SELECT_FILE, "select_prompt_hash": t.prompt_hash(), "style": t.STYLE_FILE,
                "style_hash": t.style_hash(), "art_style": art, "art_style_file": t.ART_STYLES[art]["file"],
                "art_style_hash": t.art_style_hash(art)}
    return {"policy": policy, "policy_id": POLICY_IDS[policy], "checks_version": CHECKS_VERSIONS[policy], "select_prompt": SELECT_FILE,
            "select_prompt_hash": prompt_hash(), "style": il.STYLE_FILE, "style_hash": il.prompt_hashes().get(il.STYLE_FILE),
            "art_style": SCENE_ART_STYLE, "art_style_file": il.STYLE_FILE, "art_style_hash": il.prompt_hashes().get(il.STYLE_FILE)}


def select_system(policy: str = DEFAULT_POLICY) -> str:
    return _theme().select_prompt() if check_policy(policy) == "theme" else select_prompt()


def select_user(data: dict, ident, policy: str = DEFAULT_POLICY) -> str:
    return _theme().theme_message(data, ident) if check_policy(policy) == "theme" else il.select_message(data, [ident])


def choose_by(policy: str, data: dict, ident, reply, art_style: str | None = None) -> dict:
    """
    방식대로 고른다. art_style 은 주제 방식의 그림 지시문에만 쓴다 (없으면 수채화).
    장면 방식은 그림 양식 v1(수채화)만 그린다 — 다른 그림체를 달라고 하면 바꿔 그리지 않고 IllustError("art_style") 로 멈춘다.
    """
    if check_policy(policy) == "theme":
        t = _theme()               # 모르는 그림체는 choose_theme 가 failed(art_style) 로 돌려준다 — 지시문에 넣지 않는다
        return t.choose_theme(data, ident, reply, t.DEFAULT_ART_STYLE if art_style in (None, "") else art_style)
    if art_style not in (None, "", SCENE_ART_STYLE):
        raise il.IllustError("art_style", f"장면 방식(scene_v5)은 수채화만 그린다 — 받은 그림체 {art_style!r}")
    return choose(data, ident, reply)


# ---------------------------------------------------------------- 목차와 사진

def toc(data: dict) -> list[dict]:
    """
    실제 책의 목차 항목 — 입력의 memoir.chapters 하나가 항목 하나다. 문단이나 본문 안의 제목을 따로 항목으로 치지 않는다.
    식별자(chapter_key)는 있으면 그대로 쓰고, 없으면 번호로만 가리킨다 — 만들어 붙이지 않는다.
    """
    ctx = il.check_input(data)
    out = []
    for raw, ch in zip(data["memoir"]["chapters"], ctx["chapters"].values()):
        out.append({"no": ch["no"], "key": ch["key"], "ident": ch["key"] if ch["key"] is not None else ch["no"],
                    "title": ch["title"], "paragraphs": len(ch["paragraphs"]),
                    "chapter_hash": il._para_hash("".join(ch["paragraphs"])),
                    "source_turns": sorted(set(ch["turns"]) | set(ch["chapter_turns"])), "raw": raw})
    return out


def photo_states(data: dict) -> dict:
    """
    목차 항목마다 사진 상태. **그 항목에 놓인 사진만 센다** — 같은 인터뷰 회차의 사진, 다른 항목의 사진은 세지 않는다.

        has_photo            chapters[].photos 에 사진이 있거나, photos[] 의 사진이 chapter_keys · chapter_nos 로 이 항목을 가리킨다
        no_photo_confirmed   chapters[].photos 가 빈 목록 [] 이다, 또는 photo_placement.complete 가 true 인데 이 항목을 가리키는 사진이 없다
        unknown              위 어느 것도 아니다 — 사진이 없다고 보지 않는다. 삽화를 만들지 않고 「자료 부족」 으로 남긴다

    photo_placement.complete: true 는 「항목에 놓인 사진은 이 입력에 빠짐없이 적혀 있다」 는 서비스 쪽의 말이다.
    """
    items = toc(data)
    listed = data.get("photos")
    complete = isinstance(data.get("photo_placement"), dict) and data["photo_placement"].get("complete") is True
    out = {}
    for it in items:
        own = it["raw"].get("photos")
        if own is not None and (not isinstance(own, list) or not all(
                isinstance(p, dict) and isinstance(p.get("photo_id"), str) for p in own)):
            raise il.IllustError("input", f"{it['ident']} 항목의 photos 모양이 다르다 — [{{photo_id, …}}]")
        placed = [dict(p, link="chapter.photos") for p in own or []]
        for p in listed or []:
            if (it["key"] is not None and it["key"] in (p.get("chapter_keys") or [])) or it["no"] in (p.get("chapter_nos") or []):
                if p["photo_id"] not in [x["photo_id"] for x in placed]:
                    # 책 전체 사진 목록에서 이 항목으로 이어진 사진 — 파일 경로 · 주소 · 자리를 그대로 가져온다
                    placed.append({"photo_id": p["photo_id"], "link": "photos[].chapter",
                                   **{k: p[k] for k in ("after_paragraph", "path", "url", "caption") if k in p}})
        sessions = {u["session_id"] for u in (data.get("source") or {}).get("utterances", []) if u["turn"] in it["source_turns"]}
        nearby = [p["photo_id"] for p in listed or [] if p.get("session_id") in sessions
                  and p["photo_id"] not in [x["photo_id"] for x in placed]]
        if placed:
            state, basis = "has_photo", f"이 항목에 놓인 사진 {len(placed)}장"
        elif isinstance(own, list):
            state, basis = "no_photo_confirmed", "chapters[].photos 가 빈 목록이다"
        elif complete:
            state, basis = "no_photo_confirmed", "photo_placement.complete 가 true 이고 이 항목을 가리키는 사진이 없다"
        else:
            state = "unknown"
            basis = ("이 항목에 사진이 놓였는지 입력에 없다 (chapters[].photos 도, photo_placement.complete 도 없다)"
                     + (" — photos 가 null 이다" if listed is None else ""))
        out[it["ident"]] = {"state": state, "basis": basis, "photos": placed,
                            # 같은 회차의 사진 — 이 항목의 사진이라는 근거가 아니다. 알려 주기만 한다
                            "same_session_photos_not_counted": nearby}
    return out


# ---------------------------------------------------------------- 대표 그림 — 자동 검사와 후보 비교

def _judge(data: dict, ident, cands: list[dict]) -> list[dict]:
    """기존 판정(memoir_illust)을 그대로 돌린다 — 책 전체 한도 없이, 사진 사유 없이(사진은 항목 단위로 이미 정했다)."""
    one = copy.deepcopy(data)
    one["photos"] = []
    reply = json.dumps({"candidates": cands}, ensure_ascii=False)
    return il.run(one, call=lambda system, user: reply, only=[ident], pick=False, system="-")["scenes"]


def thin_relations(scene: dict) -> list[str]:
    """
    관계 칸과 인용이 갖춰졌어도(structure_ok) 그 인용이 관계를 받치지 못하는 사람 — 「제가」 한 낱말처럼.
    근거 인용들 가운데 그 사람을 가리키는 말이 있고, 근거 인용을 합친 글이 중심 행동의 말을 절반 이상 담아야 한다.
    (낱말로만 본다 — 그 사람이 정말 그 행동을 했는지는 보지 못한다)
    """
    central = scene.get("central_action")
    if not central:
        return []
    act = il._bigrams(central["text"])
    out = []
    for r in scene["people_review"]:
        if r["code"]["state"] != "structure_ok":
            continue
        quotes = [v["quote"] for v in (r["proposed"] or {}).get("evidence") or []]
        joined = "".join(il._compact(q) for q in quotes)
        who = (bool(il._SELF_IN_QUOTE.search(" ".join(quotes))) if il.is_self(r["text"])
               else any(il._compact(r["text"]) in il._compact(q) for q in quotes))
        cover = len(act & il._bigrams(joined)) / len(act) if act else 0.0
        if not who or cover < il.PARAPHRASE_COVER:
            out.append(r["text"])
    return out


def auto_verdict(scene: dict) -> dict:
    """
    사람 확인 없이 이 장면으로 그림을 만들어도 되는가. 돌려주는 것: {accept, mode, blocking[], tolerated[], checks}.
    held(민감한 말씀)는 받지 않는다. 사람이 확인한 것으로 적지 않는다. 통과는 「형식 검사」 일 뿐이다 —
    그 그림이 항목을 대표하는지는 choose 가 후보끼리 견주어 따로 정한다.
    """
    reasons = list(scene["decision_reasons"])
    blocking = [r for r in reasons if r not in TOLERATED]
    people = scene["people_review"]
    codes = {r["text"]: r["code"]["state"] for r in people}
    thin = []
    if scene["decision"] == "held":
        blocking = ["sensitive"]
    elif scene["visual_mode"] == "SKIP":
        blocking = blocking or ["no_visual_basis"]
    elif scene["visual_mode"] == "SCENE":
        blocking += [f"person_relation_{c}" for c in sorted(set(codes.values())) if c != "structure_ok"
                     and f"person_relation_{c}" not in blocking]
        if scene["participants_review"]["possible_omitted"] and "possible_participant_omitted" not in blocking:
            blocking.append("possible_participant_omitted")
        thin = thin_relations(scene)
        if thin:
            blocking.append("person_relation_evidence_thin")
    return {
        "accept": not blocking and scene["visual_mode"] in ("SCENE", "SYMBOLIC"),
        "mode": scene["visual_mode"], "blocking": blocking, "tolerated": [r for r in reasons if r in TOLERATED],
        "checks": {
            "automatic": True, "human_confirmed": False, "note": AUTO_NOTE,
            "verification": scene["verification"], "verification_effective": scene["verification_review"]["effective"],
            "open_causes": scene["verification_review"]["open"],
            "people": [{"text": r["text"], "role": (r["proposed"] or {}).get("role"), "code": r["code"]["state"],
                        "evidence_thin": r["text"] in thin, "human": r["human"]} for r in people],
            "participants_review_human": scene["participants_review"]["human"],
            "possible_omitted": [h["name"] for h in scene["participants_review"]["possible_omitted"]],
            "central_action": scene["checks"]["central_action"]["state"],
            "summary_persons_not_drawn": scene["checks"]["summary_consistency"]["persons_not_in_elements"],
        },
    }


def parse_focus(reply) -> dict | None:
    """응답의 focus(지시문 v5) — 없거나 모양이 다르면 None. 모양이 달라도 후보는 그대로 판정한다(focus 는 참고일 뿐이다)."""
    try:
        doc = json.loads(reply) if isinstance(reply, str) else reply
    except json.JSONDecodeError:
        return None
    f = doc.get("focus") if isinstance(doc, dict) else None
    if not isinstance(f, dict):
        return None
    rows = {k: [x for x in (f.get(k) or []) if isinstance(x, dict) and isinstance(x.get("text"), str)
                and isinstance(x.get("quote"), str) and isinstance(x.get("turn"), int) and x.get("kind") in il.KINDS]
            for k in ("core", "background")}
    return {"summary": f.get("summary") if isinstance(f.get("summary"), str) else None, **rows}


PLACE_SHARE = 0.5            # 본문 문장의 절반 이상에 나오면 「본문이 그것을 이야기한다」 — 두 문장짜리 글이면 한 번으로도 된다
REPEAT_SHARE = 1 / 3         # 사물 · 행동 · 인물이 두 문장 이상 · 본문 문장의 3분의 1 이상에 나오면 「되풀이된다」
FOCUS_TIERS = ("core", "linked", "supporting", "background", "narrator")


def focus_map(data: dict, ident, scenes: list[dict], model_focus: dict | None) -> dict:
    """
    이 항목의 중심 내용 — 후보들에 나온 요소 가운데 원문과 대조된 것(인용 일치 · 부정 아님)만 놓고, 무엇이 중심이고 무엇이 곁가지 · 배경인지 가른다.
    새 요소를 만들지 않는다. 특정 낱말 · 이야기 · 호칭을 따로 다루지 않는다.

    **두 판단을 나눠 적는다.**
        source_check   원문에 있는가 — 인용이 원문과 맞고 부정되지 않았다(후보 요소는 모두 여기를 지났다) · 본문에 나오는가 · 제목의 말인가
        centrality     이 목차의 중심을 나타내는가 — 아래 규칙. 원문에 있다 · 본문에 한 번 나온다는 것만으로는 중심이 아니다
    모델이 적은 focus(core · background)는 제안으로 남기고(model_proposed · model_agrees), 그것만으로는 어떤 요소도 중심이 되지 않는다.

        사물 · 행동 · 인물   core(중심)      목차 자체의 근거가 있다 — ① 제목의 말이고 본문에도 나온다 ② 본문 문장의 절반 이상에 나온다
                                            ③ 두 문장 이상 · 본문 문장의 3분의 1 이상에 되풀이된다.
                                            또는 — 이 항목에 그런 근거를 가진 사물 · 행동 · 인물이 하나도 없을 때만 — 본문에 나오고 모델 focus.core(인용 대조)에 있다
                            linked(딸린 것)  중심이 아니지만 중심 요소와 같은 본문 문장에 나온다 (그 혼자로는 대표가 되지 않는다)
                            supporting      원문 · 본문에 있지만 중심 근거가 없다 — 한 번 지나가는 말 · 주변 인물 · 주변 사물
        장소                 core(중심)      풍경 자체가 주제 — 신호 {제목 · 본문 문장의 절반 이상 · 모델 focus.core} 가운데 둘 이상이고,
                                            더 강한 사물 · 행동 · 인물이 없다(제목에 없는 장소면 제목에 든 사물 · 행동 · 인물이 없어야 하고,
                                            어느 사물 · 행동 · 인물도 본문 비율이 그 장소보다 높지 않아야 한다)
                            background      그 밖 — 이야기가 벌어진 배경 · 가는 곳
        화자                 narrator        1인칭 회고에는 거의 늘 있다 — 중심 판정에도, 견줄 대상에도 넣지 않는다

    「이 항목에 알려진 요소」 는 후보 요소와, 인용이 맞는 모델 focus 요소(core · background 어느 칸이든)다 — 모델이 중심을 배경이라고 적었어도
    그 요소의 목차 근거는 그대로 센다. 후보에 중심이 없으면 그 항목은 대표 그림이 없는 것이다 — 코드가 곁가지 · 배경으로 메우지 않는다.
    """
    ctx = il.check_input(data)
    ch = next(c for c in ctx["chapters"].values() if (c["key"] if c["key"] is not None else c["no"]) == ident)
    title = il._compact(ch["title"])
    raw_sentences = [s for s in il._SENT_END.split(" ".join(ch["paragraphs"])) if s.strip()]
    sentences = [il._compact(s) for s in raw_sentences]
    body = "".join(sentences)

    def evidence(kind: str, text: str) -> dict:
        n = il._compact(text)
        title_match = len(n) >= 2 and len(title) >= 2 and (n in title or title in n)
        if kind == "person" and il.is_self(text):      # 화자 — 글자 「나」 가 아니라 「나는 · 내가 …」 꼴로 센다
            hit = [i for i, s in enumerate(raw_sentences) if il._SELF_IN_QUOTE.search(s)]
            mentions, title_match = len(hit), False
        elif kind == "action":
            lb = il._bigrams(n)
            hit = [i for i, s in enumerate(sentences) if n in s or (lb and len(lb & il._bigrams(s)) / len(lb) >= 0.6)]
            mentions = len(hit)
        else:
            hit = [i for i, s in enumerate(sentences) if n and n in s]
            mentions = body.count(n) if n else 0
        share = round(len(hit) / len(sentences), 3) if sentences else 0.0
        return {"title_match": title_match, "body_mentions": mentions, "body_sentences": len(hit), "body_share": share,
                "sentences": hit}

    def own(ev: dict) -> list[str]:
        """사물 · 행동 · 인물의 목차 자체 근거 — 비어 있으면 근거 없음."""
        out = []
        if ev["title_match"] and ev["body_sentences"]:
            out.append("title_and_body")
        if ev["body_sentences"] and ev["body_share"] >= PLACE_SHARE:
            out.append("body_share")
        if ev["body_sentences"] >= 2 and ev["body_share"] >= REPEAT_SHARE:
            out.append("repeated")
        return out

    mf = {"summary": None, "core": [], "background": []}
    if model_focus:
        mf["summary"] = model_focus.get("summary")
        for part in ("core", "background"):
            for n, x in enumerate(model_focus.get(part) or [], start=1):
                e = il._element({**x, "quote": x["quote"]}, n, ctx)
                mf[part].append({"kind": x["kind"], "text": x["text"], "turn": x["turn"], "quote": x["quote"],
                                 "status": e["status"], "flags": e["flags"], "verified": e["status"] == "quoted"})

    def proposed(part: str, kind: str, n: str) -> bool:
        return any(x["verified"] and (x["kind"] == kind or {x["kind"], kind} <= {"place"})
                   and (n in il._compact(x["text"]) or il._compact(x["text"]) in n) for x in mf[part] if il._compact(x["text"]))

    def is_me(kind: str, text: str) -> bool:
        return kind == "person" and il.is_self(text)

    pool: dict[tuple, dict] = {}
    for s in scenes:
        for e in s["elements"]:
            if e["status"] == "quoted" and e["kind"] in ("object", "place", "action", "person"):
                pool.setdefault((e["kind"], il._compact(e["text"])), {"kind": e["kind"], "text": e["text"], "from": "candidate"})

    # 이 항목에 알려진 사물 · 행동 · 인물 (화자 빼고) — 후보 요소와 인용이 맞는 모델 focus 요소
    known: dict[tuple, dict] = {k: v for k, v in pool.items() if v["kind"] != "place" and not is_me(v["kind"], v["text"])}
    for part in ("core", "background"):
        for x in mf[part]:
            if x["verified"] and x["kind"] in ("object", "action", "person") and not is_me(x["kind"], x["text"]):
                known.setdefault((x["kind"], il._compact(x["text"])), {"kind": x["kind"], "text": x["text"], "from": f"model_focus.{part}"})
    ev_known = {k: evidence(v["kind"], v["text"]) for k, v in known.items()}
    strong = {k for k in known if own(ev_known[k])}
    # 목차 근거가 있는 사물 · 행동 · 인물이 하나도 없을 때만 — 본문에 나오고 모델이 중심이라 적은 것을 중심으로 본다
    weak_proposed = set() if strong else {k for k, v in known.items()
                                          if ev_known[k]["body_sentences"] and proposed("core", v["kind"], k[1])}
    rivals = [(known[k]["text"], ev_known[k]) for k in known if ev_known[k]["title_match"] or ev_known[k]["body_mentions"] > 0]
    rival_title = [t for t, ev in rivals if ev["title_match"]]

    place_rows: dict[tuple, dict] = {}
    for (kind, n), v in pool.items():
        if kind != "place":
            continue
        ev = evidence(kind, v["text"])
        prominent = bool(ev["body_sentences"]) and ev["body_share"] >= PLACE_SHARE
        signals = {"title": ev["title_match"], "body_share": prominent, "model_focus_core": proposed("core", kind, n)}
        stronger = [] if ev["title_match"] else ([f"제목에 든 {', '.join(dict.fromkeys(rival_title))}"] if rival_title else [])
        higher = list(dict.fromkeys(t for t, r in rivals if r["body_share"] > ev["body_share"]))
        if higher:
            stronger.append(f"본문 비율이 더 높은 {', '.join(higher)}")
        if sum(signals.values()) >= 2 and not stronger:
            tier, rule = "core", "풍경 자체가 주제 — 목차 근거와 신호 둘 이상, 더 강한 사물 · 행동 · 인물 없음"
        elif not (ev["title_match"] or prominent):
            tier, rule = "background", "목차 근거 없음 — 제목에 없고 본문 문장의 절반 이상에 나오지도 않는다"
        elif sum(signals.values()) < 2:
            tier, rule = "background", "신호가 하나뿐이다"
        else:
            tier, rule = "background", "더 강한 중심이 있다 — " + "; ".join(stronger)
        place_rows[(kind, n)] = {"ev": ev, "signals": signals, "tier": tier, "rule": rule}

    anchor_sentences: set[int] = set()
    for k in strong | weak_proposed:
        anchor_sentences |= set(ev_known[k]["sentences"])
    for r in place_rows.values():
        if r["tier"] == "core":
            anchor_sentences |= set(r["ev"]["sentences"])

    items = []
    for (kind, n), v in pool.items():
        in_core, in_bg = proposed("core", kind, n), proposed("background", kind, n)
        if kind == "place":
            r = place_rows[(kind, n)]
            ev, tier, rule, why = r["ev"], r["tier"], r["rule"], [s for s, ok in r["signals"].items() if ok]
        elif is_me(kind, v["text"]):
            ev = evidence(kind, v["text"])
            tier, rule, why = "narrator", "화자 — 1인칭 회고에는 거의 늘 있다. 중심 판정에 넣지 않는다", []
        else:
            ev = ev_known[(kind, n)]
            why = own(ev)
            if (kind, n) in strong:
                tier = "core"
                rule = "목차 근거 — " + ", ".join({"title_and_body": "제목의 말이고 본문에도 나온다",
                                                   "body_share": "본문 문장의 절반 이상에 나온다",
                                                   "repeated": "본문에 되풀이된다"}[w] for w in why)
            elif (kind, n) in weak_proposed:
                tier, why = "core", ["body", "model_focus_core"]
                rule = "본문에 나오고 모델이 중심이라 적었다 — 이 항목에 목차 근거가 더 강한 사물 · 행동 · 인물이 없다"
            elif ev["body_sentences"] and set(ev["sentences"]) & anchor_sentences:
                tier, why = "linked", ["body", "same_sentence_as_center"]
                rule = "중심 요소와 같은 문장에 나온다 — 중심에 딸린 것. 혼자로는 대표가 되지 않는다"
            elif ev["body_sentences"] or ev["title_match"]:
                tier, why = "supporting", ["body"] if ev["body_sentences"] else ["title"]
                rule = "원문 · 본문에 있지만 중심 근거가 없다 — 지나가는 말 · 주변 인물 · 주변 사물"
            else:
                tier, rule, why = "supporting", "제목 · 본문에 없다 (원문에는 있다)", []
        agrees = None
        if (in_core or in_bg) and tier != "narrator":
            agrees = (tier == "core") == in_core
        items.append({
            "kind": kind, "text": v["text"], "tier": tier, "why": why, "rule": rule,
            "body_mentions": ev["body_mentions"], "body_share": ev["body_share"], "title_match": ev["title_match"],
            "model_proposed": "core" if in_core else "background" if in_bg else None, "model_agrees": agrees,
            "self": tier == "narrator",
            # 원문에 있는가 — 중심인지와 따로 적는다
            "source_check": {"quoted": True, "in_body": bool(ev["body_sentences"]), "body_sentences": ev["body_sentences"],
                             "title_match": ev["title_match"],
                             "note": "원문 인용이 맞고 부정되지 않았다 — 원문에 있다는 것까지다. 대표하는지는 centrality 에 따로 적는다"},
            # 이 목차의 중심을 나타내는가
            "centrality": {"tier": tier, "is_center": tier == "core", "signals": why, "rule": rule},
        })
    center_known = [known[k]["text"] for k in known if k in strong or k in weak_proposed]
    center_known += [pool[k]["text"] for k, r in place_rows.items() if r["tier"] == "core"]
    return {"title": ch["title"], "model_focus": mf, "items": items,
            "core": [v["text"] for v in items if v["tier"] == "core"],
            "linked": [v["text"] for v in items if v["tier"] == "linked"],
            "supporting": [v["text"] for v in items if v["tier"] == "supporting"],
            "background": [v["text"] for v in items if v["tier"] == "background"],
            "center_known": list(dict.fromkeys(center_known)),
            "rivals": [{"text": t, **{k: x for k, x in ev.items() if k != "sentences"}}
                       for t, ev in dict((t, ev) for t, ev in rivals).items()],
            "note": "원문에 있는가(source_check)와 중심을 나타내는가(centrality)를 따로 적었다. 중심은 목차의 제목과 본문으로 가른 것이다 — "
                    "모델의 focus 는 제안으로만 남긴다. 낱말과 문장 비율로 본다 — 무엇이 정말 중심인지는 사람만 확정할 수 있다"}


def _tier(focus: dict, e: dict) -> dict | None:
    return next((v for v in focus["items"] if v["kind"] == e["kind"] and il._compact(v["text"]) == il._compact(e["text"])), None)


def _prompt_for(scene: dict, focus: dict | None = None) -> tuple[dict | None, list[str], list[dict]]:
    """
    통과한 장면의 그림 지시문 — 검토용 초안의 「사람이 확인하기 전」 표시 없이 다시 조립한다. (지시문, 검사에 걸린 것, 뺀 요소)
    사람을 그리지 않는 그림(SYMBOLIC)에서는 화자의 나이처럼 그림과 관계없어진 때(○ 살)를 뺀다.
    focus 를 주면 중심 소재를 화면의 주제로, 배경은 보조로 적는다.
    """
    base = scene["generation_prompt"] or scene["draft_prompt"]
    if not base:
        return None, ["no_prompt"], []
    els = [e for e in scene["elements"] if e["id"] in base["elements_used"]]
    dropped = []
    if scene["visual_mode"] == "SYMBOLIC":
        for e in [e for e in els if e["kind"] == "time" and (m := il._SUM_TIME.search(e["text"])) and "살" in m.group(1)]:
            els.remove(e)
            dropped.append({"kind": e["kind"], "text": e["text"], "why": "사람을 그리지 않는 그림이라 나이는 그림과 관계없다"})
    people = [r for r in scene["people_review"] if r["element"] in [e["id"] for e in els]]
    together = len(people) >= 2 and all((r["proposed"] or {}).get("role") in ("actor", "co_actor") for r in people)
    spec = None
    if focus is not None:
        tiers = {e["id"]: (_tier(focus, e) or {}).get("tier") for e in els}
        objs = [e["text"] for e in els if e["kind"] == "object" and tiers[e["id"]] == "core"]
        places = [e["text"] for e in els if e["kind"] == "place" and tiers[e["id"]] == "core"]
        if scene["visual_mode"] == "SCENE":
            acts = [e["text"] for e in els if e["kind"] == "action"]
            center = list(dict.fromkeys(objs or acts))
            spec = {"center": center, "landscape": False} if center else None
        elif objs:
            spec = {"center": list(dict.fromkeys(objs)), "landscape": False}
        elif places:
            spec = {"center": list(dict.fromkeys(places)), "landscape": True}
    prompt = il.build_prompt(scene["visual_mode"], els, together=together, focus=spec)
    bad = il.check_prompt(prompt, scene["visual_mode"], els)
    if spec and not all(c in prompt["scene_block"] for c in spec["center"]):
        bad.append("center_missing")
    return prompt, bad, dropped


def derive_symbolic(cand: dict) -> dict | None:
    """사람과 행동을 뺀 후보 — 그 후보가 원문에서 인용한 사물 · 풍경(과 때)만 남긴다. 새로 더하는 것은 없다."""
    keep = [{k: v for k, v in e.items() if k != "relation"} for e in cand["elements"] if e["kind"] in ("object", "place", "time")]
    if not any(e["kind"] in ("object", "place") for e in keep):
        return None
    # 제목 · 요약도 사람을 뺀 것으로 — 남긴 요소의 이름만 쓴다(새 말을 짓지 않는다). 원래 제목은 derived_from 에 남긴다
    names = " · ".join(dict.fromkeys([e["text"] for e in keep if e["kind"] == "object"]           # 사물을 앞에, 장소를 뒤에
                                     + [e["text"] for e in keep if e["kind"] == "place"]))[:il.TITLE_MAX]
    return {**{k: v for k, v in cand.items() if k != "central_action"}, "elements": keep,
            "scene_title": names, "scene_summary": f"{names} (사람을 그리지 않는다)"[:il.SUMMARY_MAX],
            "derived_from": {"scene_title": cand["scene_title"], "scene_summary": cand["scene_summary"]}}


def _selected(scene: dict, verdict: dict, prompt: dict, index: int, source: str, dropped: list[dict]) -> dict:
    used = set(prompt["elements_used"])
    return {
        "status": "selected", "mode": scene["visual_mode"], "source": source, "candidate_index": index,
        "scene": {"scene_title": scene["scene_title"], "scene_summary": scene["scene_summary"],
                  "central_action": scene["central_action"], "source_turns": scene["source_turns"],
                  "source_refs": scene["source_refs"],
                  "evidence": [{"kind": e["kind"], "text": e["text"], "turn": e["turn"], "quote": e["quote"], "flags": e["flags"]}
                               for e in scene["elements"] if e["id"] in used],
                  "not_used": [{"kind": e["kind"], "text": e["text"], "status": e["status"], "flags": e["flags"]}
                               for e in scene["elements"] if e["id"] not in used],
                  "dropped_for_picture": dropped},
        "prompt": prompt, "placement": scene["placement"], "auto_checks": verdict["checks"],
        "tolerated_reasons": verdict["tolerated"],
    }


def _represent(scene: dict, used: list[str], focus: dict) -> dict:
    """
    이 그림이 항목의 중심 내용을 얼마나 담는가 — 그려질 요소(used) 가운데 core · linked · supporting · background · narrator.
    중심(core)을 하나라도 담아야 대표한다. 딸린 것(linked) · 곁가지 · 배경 · 화자만으로는 대표하지 않는다.
    제목 점수(title_hits)는 제목의 말인 중심 요소에 준다 — 장소는 본문도 그 장소를 다룰 때(본문 문장의 절반 이상)만 준다
    (「서울로 이사하던 날」 의 서울처럼 제목의 장소가 가는 곳 · 배경일 수 있다).
    """
    drawn = [e for e in scene["elements"] if e["id"] in used and e["kind"] in ("object", "place", "action", "person")]
    rows = [(e, _tier(focus, e) or {"tier": "supporting", "title_match": False, "body_mentions": 0, "why": []}) for e in drawn]

    def names(tier: str) -> list[str]:
        return [e["text"] for e, t in rows if t["tier"] == tier]
    core = names("core")
    return {"core": core, "linked": names("linked"), "supporting": names("supporting"), "background": names("background"),
            "narrator": names("narrator"),
            "title_hits": sum(1 for e, t in rows if t["tier"] == "core" and t.get("title_match")
                              and (e["kind"] != "place" or "body_share" in t.get("why", []))),
            "body_mentions": sum(t.get("body_mentions", 0) for e, t in rows if t["tier"] == "core"),
            "represents": bool(core)}


def choose(data: dict, ident, reply) -> dict:
    """
    목차 항목 하나의 대표 그림. reply 는 모델(모의)이 낸 응답 글이다.

    ① 모델이 낸 후보 모두와, 사람을 그리는 후보마다 사람 · 행동을 뺀 상징 그림(derived_symbolic)을 한데 모은다.
    ② 하나하나 자동 검사(auto_verdict — 형식)를 한다.
    ③ 이 항목의 중심 내용(focus_map)을 정하고, 통과한 후보마다 그려질 요소가 그 중심을 얼마나 담는지 잰다.
    ④ 중심을 담는(represents) 후보 가운데 — 제목의 말을 담은 수 · 중심 요소 수 · 사람이 든 장면 · 본문에 나온 횟수 · 모델이 낸 후보 · 모델의 차례
       순으로 견주어 하나를 고른다. 모델의 main · minor 표시는 쓰지 않는다.
    ⑤ 형식 검사는 통과했어도 배경만 남은 후보는 고르지 않는다. 그런 후보밖에 없으면 그 항목은 실패다 — 빈칸만 채우지 않는다.
    """
    try:
        cands = il.check_candidates(reply)
    except il.IllustError as e:
        return {"status": "failed", "reasons": ["model_output"], "detail": e.message, "tried": []}
    if not cands:
        return {"status": "failed", "reasons": ["no_candidate"], "tried": [],
                "detail": "모델이 이 항목에서 그릴 것을 내지 않았다 — 지어내서 채우지 않는다"}
    scenes = _judge(data, ident, cands)
    pool = [{"source": "candidate", "candidate_index": i, "scene": s} for i, s in enumerate(scenes)]
    for i, c in enumerate(cands):                     # 사람을 뺀 그림 — 사람이 든 후보마다 (통과했든 아니든) 견줄 거리로 만든다
        if scenes[i]["visual_mode"] != "SCENE" or scenes[i]["decision"] == "held":
            continue
        slim = derive_symbolic(c)
        if slim is not None:
            pool.append({"source": "derived_symbolic", "candidate_index": i, "scene": _judge(data, ident, [slim])[0]})
    focus = focus_map(data, ident, [p["scene"] for p in pool], parse_focus(reply))
    for p in pool:
        v = auto_verdict(p["scene"])
        p["verdict"] = v
        p["prompt"], bad, p["dropped"] = _prompt_for(p["scene"], focus) if v["accept"] else (None, [], [])
        p["accepted"] = bool(v["accept"] and p["prompt"] and not bad)
        p["blocking"] = v["blocking"] + [f"prompt_{x}" for x in bad]
        # 대표성은 형식 검사와 따로 잰다 — 막힌 후보도 「통과했다면 무엇을 그렸을까(인용이 맞는 요소)」 로 적는다
        used = p["prompt"]["elements_used"] if p["accepted"] else [e["id"] for e in p["scene"]["elements"] if e["status"] == "quoted"]
        p["represent"] = {**_represent(p["scene"], used, focus), "evaluated_on": "prompt" if p["accepted"] else "quoted_elements"}
    eligible = [p for p in pool if p["accepted"] and p["represent"]["represents"]]

    def score(p):
        r = p["represent"]
        return (r["title_hits"], len(r["core"]), len(r["linked"]), p["scene"]["visual_mode"] == "SCENE", r["body_mentions"],
                p["source"] == "candidate", -p["candidate_index"])

    best = max(eligible, key=score) if eligible else None
    comparison = []
    for p in pool:
        r = p["represent"]
        side = ", ".join(r["linked"] + r["supporting"] + r["background"]) or "-"
        if p is best:
            why = "선택 — 이 항목의 중심 요소(" + ", ".join(r["core"]) + ")를 담는 후보 가운데 가장 많이 담았다"
        elif not p["accepted"]:
            why = ("탈락 — 자동 검사를 통과하지 못했다 (" + ", ".join(p["blocking"]) + ")"
                   + (" · 통과했더라도 중심 요소를 담지 않는다" if not r["represents"] else ""))
        elif not r["represents"]:
            why = f"탈락 — 형식 검사는 통과했지만 이 항목의 중심 요소를 담지 않는다 (그려질 것: {side} — 딸린 것 · 곁가지 · 배경)"
        else:
            why = "탈락 — 중심 요소를 담지만 선택된 후보보다 덜 담는다 (" + ", ".join(r["core"]) + ")"
        comparison.append({"source": p["source"], "candidate_index": p["candidate_index"],
                           "scene_title": p["scene"]["scene_title"], "mode": p["scene"]["visual_mode"],
                           "importance_from_model": cands[p["candidate_index"]].get("importance"),
                           "accepted": p["accepted"], "blocking": p["blocking"],
                           # 두 판단 — 형식 · 원문 대조를 통과했는가 / 이 목차의 중심을 담는가
                           "source_check": p["accepted"], "represents": r["represents"], "represent": r,
                           "score": list(score(p)) if p in eligible else None, "chosen": p is best, "reason": why})
    tried = [{"candidate_index": p["candidate_index"], "scene_title": p["scene"]["scene_title"], "mode": p["scene"]["visual_mode"],
              "accepted": p["accepted"], "blocking": p["blocking"],
              **({"derived_from_scene": True} if p["source"] == "derived_symbolic" else {})} for p in pool]
    if best is not None:
        out = _selected(best["scene"], best["verdict"], best["prompt"], best["candidate_index"], best["source"], best["dropped"])
        if best["source"] == "derived_symbolic":
            out["derived_note"] = ("사람을 그리는 후보가 자동 검사를 통과하지 못해("
                                   + ", ".join(next(p["blocking"] for p in pool if p["source"] == "candidate"
                                                    and p["candidate_index"] == best["candidate_index"]) or ["-"])
                                   + ") 사람과 행동을 빼고 그 후보의 사물 · 풍경만으로 그린다")
        return {**out, "focus": focus, "comparison": comparison, "choice_reason": next(c["reason"] for c in comparison if c["chosen"]),
                "tried": tried}
    all_held = all(s["decision"] == "held" for s in scenes)
    bg_only = [p for p in pool if p["accepted"]]
    if all_held:
        reasons, detail = ["sensitive"], "민감한 말씀이 있는 항목이다 — 자동으로 그리지 않는다"
    elif bg_only:
        reasons = ["no_representative_candidate"]
        named = focus["center_known"]
        detail = ("형식 검사를 통과한 후보는 있지만 모두 이 항목의 중심 요소를 담지 않는다(딸린 것 · 곁가지 · 배경뿐) — 그것만으로 빈칸을 채우지 않는다. "
                  + ("목차 근거로 본 중심: " + ", ".join(named) + " — 그것을 담은 후보가 없다" if named
                     else "후보와 모델 focus 에서 목차 근거가 있는 중심 요소를 찾지 못했다"))
    else:
        reasons = sorted({r for p in pool for r in p["blocking"]})
        detail = "어느 후보도 자동 검사를 통과하지 못했다 — 지어내서 채우지 않는다"
    return {"status": "held" if all_held else "failed", "reasons": reasons, "detail": detail, "focus": focus,
            "comparison": comparison, "tried": tried}


# ---------------------------------------------------------------- 삽입

def insert_position(data: dict, item: dict, placement: dict | None) -> dict:
    """
    삽화를 넣을 자리 — 그 장면의 문단 뒤. 원고가 달라져 그 문단을 못 찾으면 그 항목의 끝(기본 자리)이고 까닭을 적는다.
    그 항목 자체가 없으면 넣지 않는다(failed).
    """
    chapters = {c["no"]: c for c in il._chapters(data["memoir"])}
    ch = next((c for c in chapters.values() if (item["key"] is not None and c["key"] == item["key"])
               or (item["key"] is None and c["no"] == item["no"] and c["title"] == item["title"])), None)
    if ch is None:
        return {"status": "failed", "reason": "chapter_not_found", "detail": "이 목차 항목이 지금 원고에 없다"}
    end = len(ch["paragraphs"]) - 1
    base = {"status": "inserted", "chapter_no": ch["no"], "chapter_key": ch["key"]}
    if not placement or placement.get("paragraph_index") is None:
        return {**base, "after_paragraph": end, "basis": "default_chapter_end",
                "reason": "장면과 이어지는 문단을 정하지 못했다 — 항목의 끝에 둔다"}
    loc = il.locate(data["memoir"], placement)
    if loc["state"] in ("exact", "moved") and loc["chapter_no"] == ch["no"]:
        return {**base, "after_paragraph": loc["paragraph_index"], "basis": placement["basis"], "locate": loc["state"],
                "anchor": placement["anchor"]}
    return {**base, "after_paragraph": end, "basis": "default_chapter_end", "locate": loc["state"],
            "reason": "장면을 고를 때의 문단을 지금 원고에서 찾지 못했다(본문이 바뀌었다) — 다른 문단에 잘못 넣지 않고 항목의 끝에 둔다"}


def place_photos(photos: list[dict], paragraphs: int) -> list[dict]:
    """
    기존 사진의 자리 — **사진을 빼지 않는다.** 자리를 쓸 수 없을 뿐이면 같은 항목 안의 기본 자리로 옮기고 까닭을 적는다.

        given                           after_paragraph 가 0 … 문단 수-1 이다 — 그 문단 뒤에 둔다
        default_start_no_position       자리가 적혀 있지 않다 — 항목 머리에 둔다
        default_end_invalid_position    자리가 음수거나 본문 범위 밖이거나 수가 아니다(본문이 줄었을 수 있다) — 항목 끝에 둔다
    돌려주는 것은 사진마다 {… , slot, position_basis, position_note} — slot 은 -1(머리) 또는 그 뒤에 둘 문단 번호.
    """
    out = []
    for p in photos:
        pos = p.get("after_paragraph")
        row = {k: v for k, v in p.items() if k != "link"}
        if pos is None:
            row.update(slot=-1, position_basis="default_start_no_position", position_note="사진의 자리가 입력에 없다 — 항목 머리에 둔다")
        elif isinstance(pos, int) and not isinstance(pos, bool) and 0 <= pos < paragraphs:
            row.update(slot=pos, position_basis="given", position_note=None)
        else:
            row.update(slot=paragraphs - 1, position_basis="default_end_invalid_position",
                       position_note=f"사진의 자리(after_paragraph={pos!r})를 지금 본문(문단 {paragraphs}개)에서 쓸 수 없다 — "
                                     "사진을 빼지 않고 항목 끝에 둔다")
        out.append(row)
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def reuse_basis(data: dict, t: dict, selection: dict, image: dict) -> dict:
    """
    이 선정 결과(와 그 그림)가 무엇을 근거로 만들어졌는가 — 다음 실행이 다시 써도 되는지 견줄 값이다.
    항목 전체가 아니라 **그 장면이 기대는 것**만 담는다: 책 · 그 장면이 인용한 턴의 원문과 출처 · 그 장면의 본문 문단 ·
    지시문 · 그림 양식 · 그림 설정. 그래서 책의 다른 곳이 바뀌어도 이 항목은 다시 만들지 않는다.
    """
    src = data.get("source") or {}
    utts = {u["turn"]: u for u in src.get("utterances", [])}
    tmap = {m["global_turn"]: m for m in src.get("turn_map") or []}
    selected = selection.get("status") == "selected"
    turns = selection["scene"]["source_turns"] if selected else t["source_turns"]
    anchor = ((selection.get("placement") or {}).get("anchor") or {}).get("hash") if selected else None
    return {
        "book": {"memoir_id": data["memoir"].get("memoir_id")},
        "turns": {str(n): {"elder": _sha(utts[n]["elder"]), "session_id": utts[n]["session_id"],
                           "session_turn": (tmap.get(n) or {}).get("turn")} for n in turns if n in utts},
        "anchor": anchor,                             # 그 장면의 본문 문단(공백 무시 해시) — 문단이 옮겨져도 같다
        "chapter_hash": None if anchor else t["chapter_hash"],     # 문단을 못 정했던 장면 · 실패한 항목은 항목 본문 전체로 본다
        # 그 결과를 만든 방식의 지시문 · 양식 — 방식이 바뀌면 다른 값이 되어 앞선 그림을 새 방식의 결과로 쓰지 않는다
        "select_prompt": policy_files(policy_of(selection))["select_prompt_hash"],
        "style": policy_files(policy_of(selection))["style_hash"],
        "prompt": _sha(selection["prompt"]["text"]) if selected else None,
        "image": image,
    }


def reuse_check(data: dict, t: dict, prev: dict, image: dict, policy: str | None = None) -> list[dict]:
    """
    앞선 실행의 선정 결과와 그림을 지금 다시 써도 되는가. 쓸 수 없는 까닭들을 돌려준다(없으면 빈 목록 — 다시 쓴다).

        book_changed              다른 책이다
        source_changed            그 장면이 인용한 턴의 원문 · 회차 · 원래 턴 번호가 달라졌다 (「있었다」 → 「없었다」)
        memoir_paragraph_changed  그 장면의 본문 문단이 지금 항목에 없다 (글이 바뀌었다). 문단이 자리만 옮긴 것은 까닭이 아니다
        memoir_chapter_changed    문단을 정하지 못했던 장면 · 실패한 항목인데 항목 본문이 달라졌다
        select_prompt_changed · style_changed · image_settings_changed   지시문 · 그림 양식 · 그림 설정이 달라졌다
        no_basis                  앞선 실행이 근거를 남기지 않았다 (옛 형식의 상태 파일)
    """
    old = prev.get("basis")
    if not old:
        return [{"reason": "no_basis", "detail": "앞선 결과에 근거 기록이 없어 지금 것과 견줄 수 없다"}]
    now = reuse_basis(data, t, prev["selection"], image)
    if policy is not None:
        # 지금 돌리는 방식의 지시문 · 양식과 견준다 — 앞선 결과가 다른 방식이면 select_prompt_changed 로 남는다
        files = policy_files(check_policy(policy))
        now["select_prompt"], now["style"] = files["select_prompt_hash"], files["style_hash"]
    why = []
    if old["book"] != now["book"]:
        why.append({"reason": "book_changed", "detail": f"{old['book']} → {now['book']}"})
    moved = sorted(n for n in old["turns"] if old["turns"][n] != now["turns"].get(n))
    if moved:
        why.append({"reason": "source_changed", "turns": [int(n) for n in moved],
                    "detail": "그 장면이 인용한 원문(또는 그 출처)이 달라졌다"})
    if old.get("anchor"):
        ch = next((c for c in il._chapters(data["memoir"]) if (t["key"] is not None and c["key"] == t["key"])
                   or (t["key"] is None and c["no"] == t["no"])), None)
        if ch is None or old["anchor"] not in [il._para_hash(x) for x in ch["paragraphs"]]:
            why.append({"reason": "memoir_paragraph_changed", "detail": "그 장면의 본문 문단이 지금 이 항목에 없다"})
    elif old.get("chapter_hash") != now.get("chapter_hash"):
        why.append({"reason": "memoir_chapter_changed", "detail": "이 항목의 본문이 달라졌다"})
    for key, name in (("select_prompt", "select_prompt_changed"), ("style", "style_changed"), ("image", "image_settings_changed")):
        if old.get(key) != now.get(key):
            why.append({"reason": name, "detail": f"{old.get(key)} → {now.get(key)}"})
    return why


def build_book(data: dict, items: list[dict], mock: bool) -> dict:
    """원고(data)는 건드리지 않는다. 문단 · 기존 사진 · 삽화가 차례로 든 결과를 새로 만든다 — 몇 번을 만들어도 삽화는 항목에 한 장이다."""
    by = {it["ident"]: it for it in items}
    chapters = []
    for it in toc(data):
        item = by.get(it["ident"])
        paras = it["raw"]["paragraphs"]
        photos = place_photos((item or {}).get("photo", {}).get("photos", []), len(paras))
        blocks = [{"type": "photo", **{k: v for k, v in p.items() if k != "slot"}} for p in photos if p["slot"] == -1]
        ins = (item or {}).get("insertion") or {}
        for i, para in enumerate(paras):
            sents = para.get("sentences") if isinstance(para, dict) else para
            blocks.append({"type": "paragraph", "index": i, "text": " ".join(x["text"].strip() for x in sents)})
            here = [p for p in photos if p["slot"] == i]
            # 자리가 맞는 사진을 먼저, 자리를 쓸 수 없어 옮긴 사진은 그 뒤(항목의 맨 끝)에 둔다
            blocks += [{"type": "photo", **{k: v for k, v in p.items() if k != "slot"}}
                       for p in sorted(here, key=lambda p: p["position_basis"] != "given")]
            if ins.get("status") == "inserted" and ins.get("after_paragraph") == i:
                sel = item["selection"]
                blocks.append({"type": "illustration", "image": item["image"]["path"], "ai_generated": True, "automatic": True,
                               "mock": bool(item["image"].get("mock")), "mode": sel["mode"],
                               "scene_title": sel["scene"]["scene_title"], "after_paragraph": i, "basis": ins["basis"]})
        blocks += [dict(b, kept=True) for b in it["raw"].get("illustrations") or []]      # 이미 들어 있던 삽화는 그대로
        chapters.append({"no": it["no"], "chapter_key": it["key"], "title": it["title"], "blocks": blocks})
    return {"schema_version": BOOK_SCHEMA, "mock": mock, "automatic": True, "input_ref": il.input_ref(data),
            "memoir": {"title": (data["memoir"].get("title") or {}).get("text") if isinstance(data["memoir"].get("title"), dict)
                       else data["memoir"].get("title"), "memoir_id": data["memoir"].get("memoir_id")},
            "chapters": chapters}


def summarize(items: list[dict], mock: bool = False, doc: dict | None = None) -> dict:
    """
    책 한 권의 처리 요약. complete 는 아래가 모두 맞을 때뿐이다.
    대상 항목이 모두 삽입됐다 · 사진 상태를 모르는 항목이 없다 · 다시 처리해야 하는 항목이 없다 ·
    기존 사진이 한 장도 빠지지 않았고 읽지 못한 사진이 없다 · 실제 실행에 모의 그림이 섞이지 않았다.
    """
    def n(pred) -> int:
        return sum(1 for it in items if pred(it))

    targets = [it for it in items if it["target"]]
    counts = {
        "toc_items": len(items),
        "has_photo": n(lambda it: it["photo"]["state"] == "has_photo"),
        "no_photo_confirmed": n(lambda it: it["photo"]["state"] == "no_photo_confirmed"),
        "photo_unknown": n(lambda it: it["photo"]["state"] == "unknown"),
        "already_illustrated": n(lambda it: it.get("already_illustrated")),
        "targets": len(targets),
        "selected": n(lambda it: (it["selection"] or {}).get("status") == "selected"),
        "images": n(lambda it: it["image"]["status"] in ("generated", "mock_generated")),
        "inserted": n(lambda it: it["insertion"]["status"] == "inserted"),
        "failed": n(lambda it: it["target"] and it["status"] == "failed"),
        "held": n(lambda it: it["target"] and it["status"] == "held"),
        "pending": n(lambda it: it["target"] and it["status"] == "pending"),
        "needs_reprocess": n(lambda it: it["status"] == "needs_reprocess"),
        "photos_in": sum(len(it["photo"]["photos"]) for it in items),
        "photos_relocated": 0, "photo_errors": sum(1 for it in items for p in it["photo"]["photos"] if p.get("error")),
    }
    why = []
    if doc is not None:
        shown = [b for c in doc["chapters"] for b in c["blocks"] if b["type"] == "photo"]
        counts["photos_out"] = len(shown)
        counts["photos_relocated"] = sum(1 for b in shown if b.get("position_basis") == "default_end_invalid_position")
        if counts["photos_out"] != counts["photos_in"]:
            why.append(f"기존 사진 {counts['photos_in']}장 가운데 {counts['photos_out']}장만 결과에 있다 — 사진이 빠졌다")
    if counts["photo_errors"]:
        why.append(f"읽지 못한 사진 {counts['photo_errors']}장")
    if counts["needs_reprocess"]:
        why.append(f"다시 처리해야 하는 항목 {counts['needs_reprocess']}개 — 원문 · 본문 · 지시문 · 설정이 앞선 결과와 다르다")
    mixed = n(lambda it: it["insertion"]["status"] == "inserted" and bool(it["image"].get("mock")) != mock)
    if mixed:
        why.append(f"실행 모드와 다른 그림이 섞였다 {mixed}개 (모의 그림 ↔ 실제 그림)")
    if counts["photo_unknown"]:
        why.append(f"사진이 있는지 모르는 항목 {counts['photo_unknown']}개 — 자료 부족")
    for k, label in (("failed", "실패"), ("held", "보류"), ("pending", "아직 처리하지 않음")):
        if counts[k]:
            why.append(f"{label} {counts[k]}개")
    return {"status": "complete" if not why else "incomplete", "incomplete_reasons": why, "counts": counts}


# ---------------------------------------------------------------- 미리보기

def render_markdown(book: dict) -> str:
    out = [f"# {book['memoir']['title'] or '(제목 없음)'}", ""]
    if book["mock"]:
        out += ["> 모의 실행이다 — 그림은 시험용 자리 표시이고, 장면은 모델이 고른 것이 아니다.", ""]
    for ch in book["chapters"]:
        out += [f"## {ch['no']}. {ch['title']}", ""]
        for b in ch["blocks"]:
            if b["type"] == "paragraph":
                out += [b["text"], ""]
            elif b["type"] == "photo":
                out += [f"![사진 {b['photo_id']}]({b.get('path') or b.get('url') or 'photo:' + b['photo_id']})", ""]
            else:
                tag = "AI 삽화" + (" · 모의" if b.get("mock") else "")
                out += [f"![{tag} — {b.get('scene_title', '')}]({b['image']})", ""]
    return "\n".join(out)


def render_html(book: dict, items: list[dict], summary: dict, image_uri) -> str:
    """파일 하나로 열리는 미리보기. image_uri(경로) → 그림을 박아 넣을 data: 주소(없으면 None)."""
    e = html.escape
    by = {it["ident"]: it for it in items}
    css = ("body{font-family:'Noto Serif KR','Malgun Gothic',serif;max-width:760px;margin:40px auto;padding:0 20px;color:#2b2622;"
           "background:#faf7f2;line-height:1.85}h1{font-size:28px}h2{margin-top:56px;font-size:21px;border-bottom:1px solid #d8cfc2;"
           "padding-bottom:6px}p{margin:14px 0}figure{margin:22px 0;text-align:center}figure img{max-width:100%;border-radius:4px}"
           "figcaption{font-size:13px;color:#7a6f63;margin-top:6px}.photo{border:1px dashed #b9ad9c;padding:26px;color:#7a6f63;"
           "font-size:14px;background:#f1ebe1}.tag{font-size:12px;border-radius:10px;padding:2px 9px;margin-left:8px;"
           "vertical-align:middle;background:#e6ddcf;color:#5c5247}.fail{background:#f3d9d3;color:#8a2f1f}.banner{background:#fff3cd;"
           "border:1px solid #e6d28a;padding:10px 14px;font-size:14px;margin:18px 0}table{border-collapse:collapse;font-size:13px;"
           "width:100%;margin:18px 0}td,th{border:1px solid #d8cfc2;padding:5px 8px;text-align:left}")
    label = {"has_photo": "사진 있음", "no_photo_confirmed": "사진 없음", "unknown": "사진 정보 모름"}
    out = [f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>{e(book['memoir']['title'] or '')}</title>"
           f"<style>{css}</style></head><body><h1>{e(book['memoir']['title'] or '(제목 없음)')}</h1>"]
    if book["mock"]:
        out.append("<div class='banner'>모의 실행 결과입니다 — 그림은 시험용 자리 표시이고, 장면 후보는 모델이 낸 것이 아닙니다. "
                   "실제 모델 · 이미지 API 를 부르지 않았습니다.</div>")
    c = summary["counts"]
    out.append(f"<div class='banner'>책 상태: <b>{e(summary['status'])}</b> — 목차 {c['toc_items']}개 · 사진 있음 {c['has_photo']} · "
               f"사진 없음 {c['no_photo_confirmed']} · 모름 {c['photo_unknown']} · 삽화 삽입 {c['inserted']} · 실패 {c['failed']} · 보류 {c['held']}"
               f" · 다시 처리 필요 {c['needs_reprocess']} · 기존 사진 {c.get('photos_out', '?')}/{c['photos_in']}장"
               + (f"<br>{e(' / '.join(summary['incomplete_reasons']))}" if summary["incomplete_reasons"] else "") + "</div>")
    out.append("<table><tr><th>목차</th><th>사진</th><th>처리</th><th>그림</th><th>자리</th></tr>")
    for ch in book["chapters"]:
        it = by.get(ch["chapter_key"] if ch["chapter_key"] is not None else ch["no"]) or {}
        sel, ins = it.get("selection") or {}, it.get("insertion") or {}
        out.append(f"<tr><td>{ch['no']}. {e(ch['title'])}</td><td>{e(label.get(it.get('photo', {}).get('state'), '-'))}</td>"
                   f"<td>{e(it.get('status', '-'))}{' — ' + e(', '.join(it.get('failure') or [])) if it.get('failure') else ''}</td>"
                   f"<td>{e(sel.get('mode') or '-')} {e((sel.get('scene') or {}).get('scene_title', ''))}</td>"
                   f"<td>{e(str(ins.get('basis') or '-'))}</td></tr>")
    out.append("</table>")
    for ch in book["chapters"]:
        it = by.get(ch["chapter_key"] if ch["chapter_key"] is not None else ch["no"]) or {}
        state = it.get("photo", {}).get("state")
        tag = f"<span class='tag'>{e(label.get(state, ''))}</span>" if state else ""
        if it.get("status") in ("failed", "held", "needs_reprocess"):
            tag += f"<span class='tag fail'>삽화 {e(it['status'])}: {e(', '.join(it.get('failure') or []))}</span>"
        out.append(f"<h2>{ch['no']}. {e(ch['title'])}{tag}</h2>")
        for b in ch["blocks"]:
            if b["type"] == "paragraph":
                out.append(f"<p>{e(b['text'])}</p>")
            elif b["type"] == "photo":
                # 파일 경로가 있으면 그 사진을 박아 넣고, 주소가 있으면 그 주소로 보인다. 둘 다 없거나 읽지 못하면 그렇다고 적는다
                src = (image_uri(b["path"]) if b.get("path") and not b.get("error") else None) or b.get("url")
                moved = f" · {e(b['position_note'])}" if b.get("position_note") else ""
                cap = f"기존 사진 {e(b['photo_id'])} (그대로 둔다){moved}"
                if src:
                    out.append(f"<figure><img class='existing-photo' data-photo-id='{e(b['photo_id'])}' src='{e(src, quote=True)}' "
                               f"alt='기존 사진 {e(b['photo_id'])}'><figcaption>{cap}</figcaption></figure>")
                else:
                    why = "사진 파일을 읽지 못했다" if b.get("error") else "사진 파일 경로 · 주소가 입력에 없다"
                    out.append(f"<figure><div class='photo{' fail' if b.get('error') else ''}' data-photo-id='{e(b['photo_id'])}'>"
                               f"{why} — {e(b['photo_id'])}</div><figcaption>{cap}</figcaption></figure>")
            else:
                src = image_uri(b["image"]) or e(b["image"])
                cap = "AI 삽화" + (" · 모의 그림" if b.get("mock") else "") + f" — {e(b.get('scene_title', ''))}"
                out.append(f"<figure><img class='illustration' src='{src}' alt='{e(cap)}'><figcaption>{cap}</figcaption></figure>")
    out.append("</body></html>")
    return "".join(out)
