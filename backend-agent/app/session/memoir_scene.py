"""
자서전 실험 — 장면 중심 한 장 시험 (exp/memoir-integrated, 2026-11-02). 서비스 경로와 따로 돈다.

    ① 장면 설계   call  → check_scene_plan     장 하나 · 절(section) · 장면(scene)마다 목적과 근거 사실
    ② 장면 집필   call  → check_scene_draft    절마다 문단 산문 + 근거 표현(claims) · 직접 인용(quotes)

기존 통합안(memoir_pipeline.run)의 「문단 계획 → 문장마다 사실 id」 계약 대신, 장면 목적으로 설계하고
문단을 산문으로 쓴다. **사실성 검사는 약화하지 않는다** — 문단을 문장으로 나누고, 근거 표현(claim)이 걸친
문장은 그 사실로, 걸치지 않은 문장은 문단 근거 턴으로 기존 검사(fact_token · hearsay_lost · certainty_lost ·
opinion_as_fact · causal_* · negation_lost)를 그대로 돌린다. 여기에 직접 인용 대조 · 감정 말 대조를 더한다.

분석은 부르지 않는다 — 보정 분석(사실 원장)의 그 장 이야기만 쓴다. 편집 · 검증은 이 시험에 없다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import memoir_pipeline as pipe

SCENE_PLAN_FILE = "2b_장면설계.md"
SCENE_WRITE_FILE = "3b_장면집필.md"
SCENE_WRITE_FILE_V2 = "3c_장면집필.md"     # 2026-11-02 — 간결한 장면 계획 · 절마다 짧은 수필 · 민감 사실만 근거 표현 필수
LABEL_MAX = 40
FEEL_KINDS = ("emotion_then", "thought_then", "reflection_now", "sense", "effect")
PURPOSES = ("opening", "background", "development", "turning", "result", "feeling_then", "reflection_now",
            "closing", "bridge")
_SECTION_KEY = re.compile(r"^s\d{1,2}$")
_SCENE_KEY = re.compile(r"^s\d{1,2}-\d{1,2}$")
SCENE_NOTE_MAX = 90          # 장면 메모 한 칸의 최대 글자 — 본문 같은 글이 들어오지 않게


def scene_prompt(stage: str, write_file: str = SCENE_WRITE_FILE) -> str:
    """공통 지침 + 통합안 지시문 묶음의 장면 지시문."""
    return pipe.prompt(stage, SCENE_PLAN_FILE if stage == "outline" else write_file, variant="integrated")


def compact_plan(plan: dict, labels: dict, analysis: dict, source_name: str) -> dict:
    """
    장면 계획의 긴 메모(note · focus)를 짧은 표지로 바꾼 사본 — 장면 · 목적 · 사실 배치 · core · time_shift 는 그대로.
    장면마다 feel(사실 원장 kind 가 그때의 감정 · 생각 · 지금의 회고 · 감각 · 영향인 사실)을 붙인다 — 집필이 살려야 할 표현의 근거.
    원 계획은 바꾸지 않는다. 표지는 사람(또는 Claude)이 정리한 것이라 provenance 에 남긴다.
    """
    book = pipe.ledger(analysis)
    out = json.loads(json.dumps(plan))
    keys = [sc["scene_key"] for s in out["chapter"]["sections"] for sc in s["scenes"]]
    missing = [k for k in keys if k not in labels.get("labels", {})]
    if missing:
        raise ValueError(f"표지가 없는 장면 {missing}")
    for s in out["chapter"]["sections"]:
        s["focus"] = labels.get("sections", {}).get(s["section_key"], s["focus"])
        for sc in s["scenes"]:
            lab = labels["labels"][sc["scene_key"]]
            if len(lab) > LABEL_MAX or re.search(r"다\.\s*$", lab):
                raise ValueError(f"{sc['scene_key']} 표지가 길거나 본문 문장이다")
            sc.pop("note", None)
            sc["label"] = lab
            sc["feel"] = [f for f in sc["facts"] if book.get(f, {}).get("kind") in FEEL_KINDS]
    out["chapter"]["why"] = ""
    out["provenance"] = {"based_on": source_name, "changed": "note → label(짧은 표지) · focus 짧게 · why 비움 · feel 추가",
                         "kept": "scene_key · purpose · facts · core · time_shift · omit", "by": labels.get("_note", "")}
    return out


def chapter_material(data: dict, analysis: dict, turns: list[int]) -> dict:
    """이 장 이야기들의 원문 · 사실 · 기억 단위 · 끈(이 장 단위가 걸린 것만) · 사람."""
    keep = set(turns)
    facts = [f for f in analysis["facts"] if set(f["turns"]) & keep]
    fids = {f["id"] for f in facts}
    units = [u for u in analysis["units"] if set(u["facts"]) & fids]
    uids = {u["id"] for u in units}
    threads = [{"id": t["id"], "name": t["name"], "kind": t["kind"], "units_here": [u for u in t["units"] if u in uids],
                "link_turns_here": [x for x in t.get("link_turns") or [] if x in keep]}
               for t in analysis.get("threads", []) if set(t["units"]) & uids]
    return {"source": pipe.part_source(data, sorted(keep)), "facts": facts, "units": units,
            "threads": [t for t in threads if len(t["units_here"]) >= 2 or t["link_turns_here"]],
            "must_keep": sorted(pipe.must_keep(analysis) & fids, key=pipe._fid)}


def scene_plan_message(data: dict, analysis: dict, turns: list[int], chapter_key: str,
                       watch: list[dict] | None, around: dict | None = None) -> str:
    m = chapter_material(data, analysis, turns)
    head = (pipe._SOURCE_HEAD + f"\n이번 호출은 책의 한 장({chapter_key})만 설계한다. source 는 이 장에 들어올 이야기 원문 "
            "전문이고, facts · units 는 그 이야기들의 사실 원장 · 기억 단위(일화)다. threads 는 이 장 안의 일화를 잇는 "
            "끈 가운데 화자가 직접 이은 것만이다. must_keep 은 근거 없이 빠지면 안 되는 사실이다. around 는 앞뒤 장 "
            "이름(그 내용은 이 장에 쓰지 않는다).")
    payload: dict[str, Any] = {"chapter_key": chapter_key, "around": around or {}, "facts": m["facts"],
                               "units": m["units"], "threads": m["threads"], "must_keep": m["must_keep"]}
    w = pipe.watch_for(watch, turns)
    if w:
        head += ("\npreserve_watch 는 사람이 원문에서 고른 보존 점검 대상이다 — 이것을 담는 사실을 장면의 facts · core 에 "
                 "둔다.")
        payload["preserve_watch"] = w
    payload["source"] = m["source"]
    return pipe._user(head, payload)


def check_scene_plan(out, analysis: dict, turns: list[int], chapter_key: str) -> tuple[dict, list[str], list[dict]]:
    """
    장면 설계의 모양과 보존. 실패(형식 · 참조)는 PipelineError, 그 밖은 경고 · 판정으로 남긴다.

        이 장 이야기의 모든 사실은 어느 장면의 facts 또는 omit 에 정확히 한 번
        core ⊂ 그 장면 facts · 장면 목적은 PURPOSES · 메모는 짧은 메모(본문 문장 아님)
        must_keep 을 omit 하면 fix · 기억 단위(일화)가 어느 장면에도 없으면 fix
    """
    c = pipe._Check("outline")
    prov = out.pop("provenance", None) if isinstance(out, dict) else None      # 간결본(compact_plan)의 출처 표시 — 모델 출력 키가 아니다
    out = c.obj(out, ("status", "chapter", "omit", "missing_context"))
    if prov is not None:
        out["provenance"] = prov
    if out["status"] != "ready":
        raise c.fail("context", f"status={out['status']!r} {out.get('missing_context')}")
    ch = out["chapter"]
    if not isinstance(ch, dict) or ch.get("chapter_key") != chapter_key:
        raise c.fail("reference", f"chapter_key — {chapter_key} 여야 한다")
    m = chapter_material({"utterances": [], "sessions": [], "shared_state": {}}, analysis, turns)
    allowed = {f["id"] for f in m["facts"]}
    c.sentence(ch.get("title"), allowed, f"{chapter_key}/title")
    c.text(ch.get("center"), f"{chapter_key}.center")
    seen: dict[str, str] = {}
    warnings: list[str] = []
    sections = c.items(ch.get("sections"), "sections")
    if not sections:
        raise c.fail("format", "sections 가 비었다")
    for i, s in enumerate(sections):
        if not isinstance(s, dict) or not _SECTION_KEY.match(str(s.get("section_key", ""))):
            raise c.fail("format", f"sections[{i}].section_key")
        c.sentence(s.get("title"), allowed, f"{s['section_key']}/title")
        c.text(s.get("focus"), f"{s['section_key']}.focus")
        scenes = c.items(s.get("scenes"), f"{s['section_key']}.scenes")
        if not scenes:
            raise c.fail("format", f"{s['section_key']} 장면이 없다")
        for j, sc in enumerate(scenes):
            where = f"{s['section_key']}/scenes[{j}]"
            if not isinstance(sc, dict) or not _SCENE_KEY.match(str(sc.get("scene_key", ""))):
                raise c.fail("format", f"{where}.scene_key")
            if sc.get("purpose") not in PURPOSES:
                raise c.fail("format", f"{where}.purpose={sc.get('purpose')!r}")
            fs = c.ids(sc.get("facts"), allowed, f"{where}.facts", nonempty=True)
            c.ids(sc.get("core", []), set(fs), f"{where}.core")
            for f in fs:
                if f in seen:
                    raise c.fail("reference", f"사실 {f} 이 장면 {seen[f]} 과 {sc['scene_key']} 에 두 번 — 주된 장면 하나에")
                seen[f] = sc["scene_key"]
            note = str(sc.get("note", sc.get("label", "")))
            if len(note) > SCENE_NOTE_MAX or re.search(r"다\.\s*$", note):
                warnings.append(f"{sc['scene_key']}.note 가 길거나 완성된 본문 문장이다 — 메모로 쓴다")
            c.ids(sc.get("feel", []), set(fs), f"{where}.feel")
    omit: dict[str, str] = {}
    for i, x in enumerate(c.items(out["omit"], "omit")):
        for f in c.ids((x or {}).get("facts"), allowed, f"omit[{i}].facts", nonempty=True):
            if f in seen:
                raise c.fail("reference", f"사실 {f} 을 장면과 omit 에 함께 적었다")
            if not str((x or {}).get("reason", "")).strip():
                raise c.fail("reference", f"omit[{i}] 에 이유가 없다")
            omit[f] = x["reason"]
    missing = sorted(allowed - set(seen) - set(omit), key=pipe._fid)
    if missing:
        raise c.fail("reference", f"장면에도 omit 에도 없는 사실 {missing[:8]}")
    findings = []
    for f in sorted(set(omit) & set(m["must_keep"]), key=pipe._fid):
        findings.append(pipe._finding("must_keep_excluded", "fix", chapter_key, f"must_keep 사실 {f} 을 설계에서 뺐다: {omit[f][:60]}", fact=f))
    for u in m["units"]:
        if not set(u["facts"]) & set(seen):
            findings.append(pipe._finding("episode_excluded", "fix", chapter_key, f"일화 {u['id']}({u['name'][:30]}) 가 어느 장면에도 없다",
                                          unit=u["id"]))
    return out, warnings + c.warnings, findings


def plan_metrics(plan: dict, analysis: dict) -> dict:
    """설계가 「일화 하나 = 문단 하나」 에서 벗어났는지 보는 수치 — 판정이 아니다."""
    unit_of = {f: u["id"] for u in analysis["units"] for f in u["facts"]}
    scenes = [sc for s in plan["chapter"]["sections"] for sc in s["scenes"]]
    per_unit: dict[str, int] = {}
    for sc in scenes:
        for u in {unit_of.get(f) for f in sc["facts"]} - {None}:
            per_unit[u] = per_unit.get(u, 0) + 1
    return {"sections": len(plan["chapter"]["sections"]), "scenes": len(scenes),
            "units": len(per_unit), "units_over_several_scenes": sum(1 for v in per_unit.values() if v > 1),
            "scenes_with_several_units": sum(1 for sc in scenes if len({unit_of.get(f) for f in sc["facts"]} - {None}) > 1),
            "purposes": {p: sum(1 for sc in scenes if sc["purpose"] == p) for p in PURPOSES if any(sc["purpose"] == p for sc in scenes)}}


def scene_write_message(data: dict, analysis: dict, turns: list[int], plan: dict, watch: list[dict] | None) -> str:
    m = chapter_material(data, analysis, turns)
    planned = {f for s in plan["chapter"]["sections"] for sc in s["scenes"] for f in sc["facts"]}
    head = (pipe._SOURCE_HEAD + "\nplan 은 이 장의 장면 설계(절 · 장면 목적 · 근거 사실)다 — 내부 메모이고 본문에 옮겨 적지 않는다. "
            "facts 는 이 장에서 쓸 사실 원장(source · certainty · kind 를 지킨다), source 는 이 장 이야기 원문 전문이다. "
            "문단의 facts · claims · quotes 에는 facts 의 id 만 쓴다. 장면 하나를 문단 하나로 옮기지 않아도 된다.")
    payload: dict[str, Any] = {"plan": plan["chapter"], "facts": [f for f in m["facts"] if f["id"] in planned]}
    w = pipe.watch_for(watch, turns)
    if w:
        head += "\npreserve_watch 는 사람이 고른 보존 점검 대상이다 — 그 경위 · 감정 · 직접 인용이 장면 안에 살아 있게 쓴다."
        payload["preserve_watch"] = w
    payload["source"] = m["source"]
    return pipe._user(head, payload)


def check_scene_draft(out, plan: dict, chapter_key: str) -> tuple[dict, list[str]]:
    """
    장면 집필의 모양. 절은 설계의 절 순서 그대로. 문단마다 text · facts(설계한 사실 안) · claims(문단 속 구절과 그 사실)
    · quotes(따옴표 인용과 그 사실). claim · quote 구절은 문단에 글자 그대로 있어야 하고 사실은 문단 facts 안이어야 한다.
    """
    c = pipe._Check("chapter", chapter_key)
    out = c.obj(out, ("chapter_key", "title", "sections", "review_notes"))
    if out["chapter_key"] != chapter_key:
        raise c.fail("reference", f"chapter_key {out['chapter_key']!r}")
    planned = {f for s in plan["chapter"]["sections"] for sc in s["scenes"] for f in sc["facts"]}
    c.sentence(out["title"], planned, f"{chapter_key}/title")
    want = [s["section_key"] for s in plan["chapter"]["sections"]]
    got = [s.get("section_key") for s in c.items(out["sections"], "sections")]
    if got != want:
        raise c.fail("reference", f"절 {got} — 설계의 절 {want} 순서 그대로여야 한다")
    for s in out["sections"]:
        c.sentence(s.get("title"), planned, f"{s['section_key']}/title")
        paras = c.items(s.get("paragraphs"), f"{s['section_key']}.paragraphs")
        if not paras:
            raise c.fail("format", f"{s['section_key']} 문단이 없다")
        for k, p in enumerate(paras):
            where = f"{chapter_key}/{s['section_key']}/p{k}"
            if not isinstance(p, dict):
                raise c.fail("format", f"{where} 가 객체가 아니다")
            text = c.text(p.get("text"), f"{where}.text")
            fs = c.ids(p.get("facts", []), planned, f"{where}.facts")
            for i, cl in enumerate(c.items(p.get("claims", []), f"{where}.claims")):
                span = c.text((cl or {}).get("span"), f"{where}.claims[{i}].span")
                if span not in text:
                    raise c.fail("reference", f"{where}.claims[{i}] 구절이 문단에 글자 그대로 없다: {span[:30]}")
                c.ids(cl.get("facts"), set(fs), f"{where}.claims[{i}].facts", nonempty=True)
            for i, q in enumerate(c.items(p.get("quotes", []), f"{where}.quotes")):
                span = c.text((q or {}).get("span"), f"{where}.quotes[{i}].span")
                if span not in text:
                    raise c.fail("reference", f"{where}.quotes[{i}] 인용이 문단에 글자 그대로 없다: {span[:30]}")
                c.ids([q.get("fact")], set(fs), f"{where}.quotes[{i}].fact")
            if fs and not p.get("claims"):
                c.warnings.append(f"{where} 에 근거 표현(claims)이 없다 — 문단 근거로만 검사한다")
    return out, c.warnings


# ---------------------------------------------------------------- 사실성 검사 — 문단을 문장으로 나눠 기존 검사를 돌린다


def sentence_items(draft: dict, book: dict[str, dict]) -> list[dict]:
    """
    검사용 장 모양(절은 순서대로 펼친다). 문장마다: 걸친 claim 들의 사실 → supported(그 사실로 검사),
    claim 이 없는 문장 → editorial(사실 없음)이되 turns 는 문단 근거 턴(숫자 · 지명 · 인과를 문단 원문과 대조).
    """
    paras = []
    for s in draft["sections"]:
        for p in s["paragraphs"]:
            text = p["text"]
            p_turns = pipe.fact_turns(p.get("facts"), book)
            rows = []
            for a, b in pipe.split_sentences(text):
                fs: list[str] = []
                for cl in p.get("claims") or []:
                    i = text.find(cl["span"])
                    while i != -1:
                        if i < b and i + len(cl["span"]) > a:
                            fs += [f for f in cl["facts"] if f not in fs]
                        i = text.find(cl["span"], i + 1)
                rows.append({"text": text[a:b], "kind": "supported" if fs else "editorial", "facts": fs,
                             "turns": pipe.fact_turns(fs, book) if fs else p_turns,
                             "adapted": [x for x in p.get("adapted") or [] if x in text[a:b]]})
            paras.append(rows)
    return [{"chapter_key": draft["chapter_key"], "title": draft["title"], "paragraphs": paras}]


_QUOTED = re.compile(r"[\"“'‘]([^\"”'’]{2,})[\"”'’]")


def text_findings(chs: list[dict], book: dict[str, dict], data: dict) -> list[dict]:
    """
    문장 모양 장(문장 항목에 facts · turns)에 대한 사실성 검사 — 장면 원고와 기존 편집본에 **같은 함수**를 쓴다.
    기존 검사(숫자 · 지명 · 전언 · 흐림 · 평가 · 인과 · 부정) + 따옴표 인용 대조 · 감정 말 대조.
    """
    elder = {u["turn"]: u["elder"] for u in data["utterances"]}
    f: list[dict] = []
    f += pipe.fact_findings(chs, data) + pipe.voice_findings(chs, book) + pipe.causal_findings(chs, data)
    f += pipe.negation_findings(chs, book, data) + qualifier_findings(chs, data)

    def norm(s):
        return re.sub(r"[\s.,!?…~]", "", s)
    for loc, _, _, x in pipe._sentences(chs):
        src = norm(" ".join(elder.get(t, "") for t in x["turns"]))
        for q in _QUOTED.findall(x["text"]):
            if norm(q) not in src and not any(q in a for a in x.get("adapted") or []):
                f.append(pipe._finding("quote_not_in_source", "fix", loc, f"따옴표 인용 「{q[:30]}」 이 근거 원문에 없다"))
        raw_src = " ".join(elder.get(t, "") for t in x["turns"])
        for w in sorted({m.group(0) for m in pipe._AFFECT.finditer(x["text"])}):
            if w not in raw_src and not any(w in a for a in x.get("adapted") or []):
                f.append(pipe._finding("affect_unsupported", "review", loc,
                                       f"감정 · 감각 말 「{w}」 이 근거 원문에 없고 각색 표시도 없다"))
    return f


def scene_findings(draft: dict, plan: dict, analysis: dict, data: dict, watch: list[dict] | None,
                   turns: list[int]) -> dict:
    """사실 · 보존 · 각색 검사. 판정(fix · review · info)은 기록이며 이 시험은 다시 부르지 않는다."""
    book = pipe.ledger(analysis)
    chs = sentence_items(draft, book)
    f: list[dict] = text_findings(chs, book, data)
    planned = {fid for s in plan["chapter"]["sections"] for sc in s["scenes"] for fid in sc["facts"]}
    core = {fid for s in plan["chapter"]["sections"] for sc in s["scenes"] for fid in sc.get("core", [])}
    used = {fid for s in draft["sections"] for p in s["paragraphs"] for fid in p.get("facts") or []}
    claimed = {fid for s in draft["sections"] for p in s["paragraphs"] for cl in p.get("claims") or [] for fid in cl["facts"]}
    m = chapter_material(data, analysis, turns)
    for fid in sorted((set(m["must_keep"]) & planned) - used, key=pipe._fid):
        f.append(pipe._finding("must_keep_missing", "fix", draft["chapter_key"], f"must_keep 사실 {fid} 이 어느 문단에도 없다", fact=fid))
    for fid in sorted(core - used - set(m["must_keep"]), key=pipe._fid):
        f.append(pipe._finding("core_missing", "fix", draft["chapter_key"], f"장면 core 사실 {fid} 이 어느 문단에도 없다", fact=fid))
    for u in m["units"]:
        if not set(u["facts"]) & used:
            f.append(pipe._finding("episode_missing", "fix", draft["chapter_key"], f"일화 {u['id']}({u['name'][:30]}) 가 본문에 없다", unit=u["id"]))
    for fid in sorted(used - claimed, key=pipe._fid):
        fact = book.get(fid, {})
        sensitive = fact.get("source") in ("heard", "view") or fact.get("certainty") in ("approx", "uncertain")
        # 전언 · 평가 · 흐린 기억은 그 구절을 claim 으로 표시해야 표지 검사(hearsay · opinion · certainty)가 걸린다
        f.append(pipe._finding("sensitive_unclaimed" if sensitive else "fact_unclaimed", "fix" if sensitive else "info",
                               draft["chapter_key"], f"사실 {fid}({fact.get('source')}/{fact.get('certainty')}) 이 문단 근거에만 있고 "
                               "근거 표현(claim)이 없다", fact=fid))
    watched = pipe.watch_check(chs, pipe.watch_for(watch, turns)) if watch else []     # 이 장 이야기의 점검 항목만
    counts = {s: sum(1 for x in f if x["severity"] == s) for s in ("block", "fix", "review", "info")}
    return {"findings": f, "counts": counts, "watch": watched,
            "coverage": {"planned": len(planned), "used": len(used & planned), "claimed": len(claimed),
                         "must_keep": len(m["must_keep"]), "must_keep_used": len(set(m["must_keep"]) & used)},
            "adaptations": pipe.adaptation_notes(chs)}


def regroup_plan(plan: dict, memories: list[dict]) -> dict:
    """
    장면 계획의 절을 기억 수필 단위로 다시 묶는다 — 장면 · 목적 · 사실 배치 · core · label · feel · time_shift 는 그대로,
    절 경계와 장면 번호만 바뀐다. memories: [{"key": "s1", "focus": 짧은 표지, "scenes": [옛 장면 키 …]}].
    모든 옛 장면이 정확히 한 번씩 들어가야 한다.
    """
    old = {sc["scene_key"]: sc for s in plan["chapter"]["sections"] for sc in s["scenes"]}
    used = [k for m in memories for k in m["scenes"]]
    if sorted(used) != sorted(old) or len(used) != len(set(used)):
        raise ValueError("기억 수필의 장면 묶음이 원 계획의 장면과 하나씩 맞지 않는다")
    out = json.loads(json.dumps(plan))
    sections = []
    for m in memories:
        scenes = []
        for i, k in enumerate(m["scenes"], start=1):
            sc = json.loads(json.dumps(old[k]))
            sc["scene_key"] = f"{m['key']}-{i}"
            sc["from_scene"] = k
            scenes.append(sc)
        label = re.sub(r"\s*\(.*?\)\s*$", "", m["focus"])          # 임시 절 이름 — 집필이 제 제목을 짓는다(3c)
        sections.append({"section_key": m["key"], "title": {"text": label, "kind": "editorial", "facts": []},
                         "focus": m["focus"], "scenes": scenes})
    out["chapter"]["sections"] = sections
    out.setdefault("provenance", {})["regrouped"] = [{"key": m["key"], "scenes": m["scenes"]} for m in memories]
    return out


# ---------------------------------------------------------------- 재구성 — 모델 호출 없이 기존 초안의 절 · 문단 경계만 바꾼다


def restructure(draft: dict, spec: dict, split: bool = True, corrections: bool = True) -> tuple[dict, list[dict]]:
    """
    기존 초안을 spec 의 기억 수필(절) 단위로 다시 묶는다. 문장은 바꾸지 않는다 — spec.corrections(원문 근거 복원)만 예외.
    split=False 면 원 문단 그대로(「제목만 붙인」 판), True 면 spec 의 문장 범위대로 문단을 나눈다(「서술 구조를 바꾼」 판).
    문단 facts 는 나뉜 문장에 걸친 claim 의 사실 + claim 이 없는 원 문단 사실(어디에 있는지 몰라 양쪽에 둔다).
    돌려주는 것은 (새 초안, 바꾼 기록).
    """
    paras = {(s["section_key"], k): p for s in draft["sections"] for k, p in enumerate(s["paragraphs"])}
    log: list[dict] = []
    fixed = {}
    for c in spec.get("corrections", []) if corrections else []:
        hits = [(key, p) for key, p in paras.items() if c["from"] in p["text"]]
        if len(hits) != 1:
            raise ValueError(f"고칠 구절을 정확히 한 곳에서 찾지 못했다: {c['from']}")
        key, p = hits[0]
        fixed[key] = {**p, "text": p["text"].replace(c["from"], c["to"], 1),
                      "claims": [{**cl, "span": cl["span"].replace(c["from"], c["to"])} for cl in p.get("claims") or []]}
        log.append({"kind": "text.restore", "where": f"{key[0]}/p{key[1]}", **c})
    paras.update(fixed)
    used: set = set()
    sections = []
    for m in spec["memories"]:
        out_paras = []
        for sec, k, (a, b) in m["from"]:
            p = paras[(sec, k)]
            if not split:
                if (sec, k) in used:
                    continue
                used.add((sec, k))
                out_paras.append(json.loads(json.dumps(p)))
                continue
            spans = pipe.split_sentences(p["text"])
            text = " ".join(p["text"][x:y] for x, y in spans[a:b])
            claims = [cl for cl in p.get("claims") or [] if cl["span"] in text]
            quotes = [q for q in p.get("quotes") or [] if q["span"] in text]
            claimed_all = {f for cl in p.get("claims") or [] for f in cl["facts"]}
            facts = sorted({f for cl in claims for f in cl["facts"]} | (set(p.get("facts") or []) - claimed_all), key=pipe._fid)
            out_paras.append({"text": text, "facts": facts, "claims": claims, "quotes": quotes,
                              "adapted": [x for x in p.get("adapted") or [] if x in text]})
            log.append({"kind": "paragraph.split", "from": f"{sec}/p{k}", "sentences": [a, b], "to": m["key"]})
        sections.append({"section_key": m["key"], "title": {"text": m["title"], "kind": "editorial", "facts": []},
                         "paragraphs": out_paras})
        log.append({"kind": "section.set", "section": m["key"], "title": m["title"], "stories": m["stories"], "why": m["why"]})
    title = {"text": spec["part"]["title"], "kind": "editorial", "facts": []}
    return {"chapter_key": draft["chapter_key"], "title": title, "sections": sections, "review_notes": []}, log


# ---------------------------------------------------------------- 의미를 한정하는 말이 빠졌나 — 원문 문장과 맞대어 본다

# 장소 · 범위 · 시간 · 대상을 좁히는 말(「지하상가 안으로」 · 「~까지」 · 「~만」), 흐림 · 전언 말끝, 부정
_QUAL = re.compile(r"([가-힣]+)\s?(안으로|안에서|안에는|밖으로|밖에서|까지|부터|에서만|에게만|만은|조차|마저|뿐)(?![가-힣])")
_SRC_HEDGE = re.compile(r"것\s?같|나\s?봐|였나|일\s?거|던가|쯤|무렵|남짓")
_SRC_HEARD = re.compile(r"대요|래요|다고\s?하더|라고\s?하더|다더라|라더라|다고\s?들었|라고\s?들었|했대")   # 「~더라고요」는 회상 말끝이지 전언이 아니다
_NEG = re.compile(r"(?<![가-힣])(안|못)(?=\s|하|했|해|한)|않|없|아니|아닌|아냐|모르")


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def qualifier_findings(chs: list[dict], data: dict, min_cover: float = 0.5) -> list[dict]:
    """
    본문 문장마다 근거 원문 문장 가운데 **그 내용이 본문 문장에 상당 부분 들어온 것**(원문 문장 글자 두 개 묶음의
    min_cover 이상이 본문 문장에 있음)을 모두 찾아 — 본문 한 문장이 원문 여러 문장을 합칠 수 있다 — 원문의 한정어 ·
    흐림 · 전언 · 부정이 본문 문장에서 사라졌는지 본다(review). 「지하상가 안으로 직접 쏜 건 아니었는데도」 →
    「직접 쏜 것이 아닌데도」 같은 축약을 잡으려는 것이다. 바꿔 써서 겹침이 적은 문장은 보지 않는다(사람 몫).
    """
    elder = {u["turn"]: u["elder"] for u in data["utterances"]}
    out = []
    for loc, _, _, x in pipe._sentences(chs):
        d = x.get("text", "")
        bd = _bigrams(d)
        if not bd:
            continue
        flat_d = re.sub(r"\s", "", d)
        matched = []
        for t_ in x.get("turns") or []:
            src = elder.get(t_, "")
            for a, b in pipe.split_sentences(src):
                s = src[a:b]
                bs = _bigrams(s)
                if bs and len(bd & bs) / len(bs) >= min_cover:
                    matched.append(s)
        # 한정어 바로 뒤의 말(4자)이 본문에 있는데 한정어가 없으면 — 원문 문장 전체가 겹치지 않아도(여러 문장을 합쳐 줄인 경우) 잡는다
        seen_q: set[str] = set()
        for t_ in x.get("turns") or []:
            src = elder.get(t_, "")
            for m in _QUAL.finditer(src):
                after = re.sub(r"\s", "", src[m.end():m.end() + 12])[:3]
                whole = re.sub(r"\s", "", m.group(0))
                if len(after) == 3 and after in flat_d and whole not in flat_d and m.group(0) not in seen_q:
                    seen_q.add(m.group(0))
                    out.append(pipe._finding("qualifier_lost", "review", loc,
                                             f"원문의 한정어 「{m.group(0)}」 뒤의 말 「{after}」 은 본문에 있는데 한정어가 없다",
                                             phrase=m.group(0)))
        for s in matched:
            for m in _QUAL.finditer(s):
                if m.group(0) in seen_q:
                    continue
                if re.sub(r"\s", "", m.group(0)) not in flat_d:
                    out.append(pipe._finding("qualifier_lost", "review", loc,
                                             f"원문의 한정어 「{m.group(0)}」 이 본문 문장에 없다 — 원문: {s[:50]}", phrase=m.group(0)))
            if _SRC_HEDGE.search(s) and not pipe._HEDGE_BODY.search(d):
                out.append(pipe._finding("hedge_lost", "review", loc,
                                         f"원문의 흐림 「{_SRC_HEDGE.search(s).group(0)}」 이 본문에서 사라졌다 — 원문: {s[:50]}"))
            if _SRC_HEARD.search(s) and not pipe._HEARD_BODY.search(d):
                out.append(pipe._finding("hearsay_marker_lost", "review", loc,
                                         f"원문의 전언 말끝 「{_SRC_HEARD.search(s).group(0)}」 이 본문에서 사라졌다 — 원문: {s[:50]}"))
            if _NEG.search(s) and not _NEG.search(d):
                out.append(pipe._finding("negation_scope", "review", loc, f"원문의 부정 표현이 본문 문장에 없다 — 원문: {s[:50]}"))
    return out


# ---------------------------------------------------------------- 글 모양 수치 — 기존 편집본과 같은 함수로 잰다


# 문단 첫머리(25자 안)의 시점 표현 — 나이 · 연도 · 「~때」 · 「그해」 등. 어림이다(「때」가 다른 뜻일 때도 걸린다)
_TIME_OPEN = re.compile(r"\d+\s?년|\d+\s?살|[가-힣]+\s?살(이|에|쯤|때| 때| 무렵|이던|이 되던| 되던)|살 때|때[,는에 ]|시절|무렵|이듬해|그해|"
                        r"그 뒤|그 후|그 무렵|당시|한번은|어느 날|(봄|여름|가을|겨울)[,에이]")


def text_shape(paragraphs: list[tuple[str, set[int]]]) -> dict:
    """(문단 글, 근거 턴) 목록 → 문단 · 문장 수, 이야기 하나짜리 문단, 시간 표현으로 여는 문단, 길이 분포."""
    sents = [p[a:b] for p, _ in paragraphs for a, b in pipe.split_sentences(p)]
    lens = [len(re.sub(r"\s", "", s)) for s in sents]
    plens = [len(re.sub(r"\s", "", p)) for p, _ in paragraphs]
    first = [p[:25] for p, _ in paragraphs]

    def spread(xs):
        if not xs:
            return {}
        xs = sorted(xs)
        return {"min": xs[0], "median": xs[len(xs) // 2], "max": xs[-1]}
    story_paras: dict[int, int] = {}
    for _, ts in paragraphs:
        for t in ts:
            story_paras[t] = story_paras.get(t, 0) + 1
    return {"paragraphs": len(paragraphs), "sentences": len(sents), "chars": sum(plens),
            "one_story_paragraphs": sum(1 for _, ts in paragraphs if len(ts) == 1),
            "stories_over_several_paragraphs": sum(1 for v in story_paras.values() if v > 1),
            "time_opening_paragraphs": sum(1 for s in first if _TIME_OPEN.search(s)),
            "sentence_chars": spread(lens), "paragraph_chars": spread(plens),
            "short_sentences_lt20": sum(1 for x in lens if x < 20), "long_sentences_gt80": sum(1 for x in lens if x > 80)}


def copy_overlap(texts: list[str], sources: list[str], n: int = 20) -> dict:
    """
    원문을 얼마나 그대로 옮겼나 — 문장마다 공백 · 문장부호를 뺀 글에서 원문과 n자 이상 같은 구간이 있는가, 그리고
    문장 글자 가운데 원문과 n자 이상 이어 같은 글자의 비율. **보고용 수치다** — 원문과 다르게 쓰는 것이 목표가 아니다.
    """
    def norm(s):
        return re.sub(r"[\s.,!?…~\"“”'‘’·]", "", s)
    src = norm(" ".join(sources))
    sents = [norm(t[a:b]) for t in texts for a, b in pipe.split_sentences(t)]
    hit, covered, total = 0, 0, 0
    for s in sents:
        total += len(s)
        mask = [False] * len(s)
        i = 0
        while i + n <= len(s):
            if s[i:i + n] in src:
                j = i + n
                while j < len(s) and s[i:j + 1] in src:
                    j += 1
                for k in range(i, j):
                    mask[k] = True
                i = j
            else:
                i += 1
        if any(mask):
            hit += 1
        covered += sum(mask)
    return {"sentences": len(sents), "sentences_with_copied_run": hit,
            "copied_char_ratio": round(covered / total, 2) if total else 0.0, "run_chars": n}


def draft_shape(draft: dict, book: dict[str, dict]) -> dict:
    return text_shape([(p["text"], set(pipe.fact_turns(p.get("facts"), book)))
                       for s in draft["sections"] for p in s["paragraphs"]])


def chapter_shape(chapter: dict, book: dict[str, dict]) -> dict:
    """기존 문장 계약 장(문단 = 문장 항목 목록)을 같은 수치로."""
    return text_shape([(" ".join(x["text"].strip() for x in para),
                        set(pipe.fact_turns([f for x in para for f in x.get("facts") or []], book)))
                       for para in chapter["paragraphs"]])


def draft_markdown(draft: dict) -> str:
    lines = [f"## {draft['title']['text']}", ""]
    for s in draft["sections"]:
        if len(draft["sections"]) > 1 and s["title"]["text"].strip():
            lines += [f"### {s['title']['text']}", ""]
        for p in s["paragraphs"]:
            lines += [p["text"].strip(), ""]
    return "\n".join(lines)


def chapter_markdown(chapter: dict) -> str:
    lines = [f"## {chapter['title']['text']}", ""]
    for para in chapter["paragraphs"]:
        lines += [" ".join(x["text"].strip() for x in para), ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- 실행 — 설계 1회 · 집필 1회. 재시도 없음


async def run_scene_chapter(data: dict, turn_map: list[dict], analysis: dict, turns: list[int], chapter_key: str, *,
                            call=pipe.call_model, recorder: pipe.Recorder | None = None, watch: list[dict] | None = None,
                            around: dict | None = None, stop_after: str | None = None, meta: dict | None = None,
                            plan_reuse: dict | None = None, write_file: str = SCENE_WRITE_FILE) -> dict:
    """
    장 하나를 장면 설계 → 장면 집필로. 호출은 최대 2회(plan_reuse 면 1회), 첫 실패에서 멈춘다(재시도 없음).
    결과 파일: 02s_scene_plan · 02s_plan_checks · 03s_<장> · 03s_checks · 03s_shape · run.json.
    """
    from datetime import datetime, timezone
    rec = recorder or pipe.Recorder()
    cfg = pipe.settings()
    meta = dict(meta or {})
    T = pipe.check_input(data, turn_map)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    st = pipe._Run(data, T, call, rec, cfg, max_calls=1 if plan_reuse else 2, variant="integrated")
    result: dict = {"state": "failed", "failure": None, "chapter_key": chapter_key, "turns": turns}
    try:
        if not set(turns) <= T:
            raise pipe.PipelineError("input", "input", f"없는 이야기 {sorted(set(turns) - T)}")
        if stop_after not in (None, "plan"):
            raise pipe.PipelineError("input", "input", f"stop_after {stop_after!r}")
        rec.json("00_scene_input.json", {"chapter_key": chapter_key, "turns": turns, "around": around,
                                         "analysis_facts": len(chapter_material(data, analysis, turns)["facts"]),
                                         "preserve_watch": pipe.watch_for(watch, turns)})
        if plan_reuse is not None:
            plan = json.loads(json.dumps(plan_reuse))
            step = {"warnings": []}
        else:
            plan, step = await st.ask("outline", scene_plan_message(data, analysis, turns, chapter_key, watch, around),
                                      "02s_scene_plan", system=scene_prompt("outline"))
        plan, warns, pf = check_scene_plan(plan, analysis, turns, chapter_key)
        step["warnings"] = warns
        step["ok"] = True
        rec.json("02s_plan_checks.json", {"warnings": warns, "findings": pf, "metrics": plan_metrics(plan, analysis)})
        result.update(plan_metrics=plan_metrics(plan, analysis), plan_findings=pf)
        blocking = [x for x in pf if x["severity"] in ("block", "fix")]
        if blocking:
            # 설계가 필수 사실 · 일화를 뺐으면 집필을 부르지 않는다 (2026-11-02 사용자 조건 4)
            raise pipe.PipelineError("outline", "reference",
                                     "장면 설계 보존 검사 실패 — " + "; ".join(x["detail"] for x in blocking)[:300])
        if stop_after == "plan":
            result["state"] = "stopped_after_plan"
            return result
        if plan_reuse is not None:
            rec.json("02s_scene_plan_reused.json", plan)
        draft, step = await st.ask("chapter", scene_write_message(data, analysis, turns, plan, watch),
                                   f"03s_{chapter_key}", chapter_key, system=scene_prompt("chapter", write_file))
        draft, step["warnings"] = check_scene_draft(draft, plan, chapter_key)
        step["ok"] = True
        checks = scene_findings(draft, plan, analysis, data, watch, turns)
        rec.json("03s_checks.json", checks)
        shape = draft_shape(draft, pipe.ledger(analysis))
        shape["copy"] = copy_overlap([p["text"] for s in draft["sections"] for p in s["paragraphs"]],
                                     [u["elder"] for u in data["utterances"] if u["turn"] in set(turns)])
        rec.json("03s_shape.json", shape)
        rec.text(f"03s_{chapter_key}.md", draft_markdown(draft))
        result.update(state="drafted", counts=checks["counts"], coverage=checks["coverage"], shape=shape,
                      watch_found=sum(1 for w in checks["watch"] if w["found"]), watch_items=len(checks["watch"]))
        return result
    except pipe.PipelineError as e:
        if st.steps and st.steps[-1]["error"] is None and not st.steps[-1]["ok"]:
            st.steps[-1]["error"] = e.as_dict()
        result["failure"] = e.as_dict()
        return result
    finally:
        rec.json("result.json", result)
        rec.json("run.json", {**meta, "mode": "scene_chapter", "chapter_key": chapter_key, "turns": turns,
                              "started_at": started,
                              "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "settings": cfg, "prompts": {"plan": SCENE_PLAN_FILE, "write": write_file,
                                                           "plan_sha256": pipe.hashlib.sha256(scene_prompt("outline").encode()).hexdigest()[:16],
                                                           "write_sha256": pipe.hashlib.sha256(scene_prompt("chapter", write_file).encode()).hexdigest()[:16]},
                              "plan_reused": plan_reuse is not None, "steps": st.steps, "calls": st.calls,
                              "state": result["state"], "failure": result["failure"]})
