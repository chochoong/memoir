"""수필체 · 문학체의 '장 자료 묶음'(사용자 메시지) 조립 — 참조 구현.

표준 라이브러리만 쓴다. 모델을 부르지 않는다. 실험 실행기가 실제로 보낸 사용자 메시지와 **글자까지 같게** 나오도록 옮긴 것이다
(로컬에서 수필체 6건 · 문학체 1건 · 소설체 1건의 실제 입력과 대조해 확인 — 인수인계 문서의 validation_report.md). 운영 코드가 아니라 규격을 대신하는 예시다.

입력
    analysis  분석 결과(schemas/analysis_output.schema.json 모양). 수필체는 장마다 확정 제목(chapters[].title)이 더 있어야 한다.
    stories   {이야기 번호(int): 원문 전문(str)}
    sensitive 민감한 기억(죽음 · 사고 · 질병 · 역사적 사건)이 든 장인가 — 판단은 호출하는 쪽이 한다. 실험에서는 낱말 규칙과 사람이 고른 목록으로 정했다.

소설체는 묶음을 쓰지 않는다 — novel_user_message() 처럼 프롬프트의 {{SOURCE_TEXT}} 한 군데에 원문을 넣을 뿐이다.
"""
from __future__ import annotations

import re

ESSAY_SUFFIX = "\n위 자료로 이 편을 집필해 JSON 하나만 출력하세요."
LITERARY_SUFFIX = "\n위 자료로 이 장을 극서정 문학체로 집필해 JSON 하나만 출력하세요."
TITLE_PLACEHOLDER = "제목 미확정"          # 문학체 — 제목이 정해지지 않았을 때 쓰는 임시값. 최종 제목으로 저장하지 않는다
NOVEL_PLACEHOLDER = "{{SOURCE_TEXT}}"


def nchars(s: str) -> int:
    """공백을 뺀 글자 수."""
    return len(re.sub(r"\s", "", s))


def _chapter(analysis: dict, chapter_id: str) -> tuple[int, dict]:
    for i, c in enumerate(analysis["chapters"], 1):
        if c["id"] == chapter_id:
            return i, c
    raise KeyError(chapter_id)


def _fact_lines(analysis: dict, numbers: list[int]) -> list[str]:
    by = {s["turn"]: s for s in analysis["stories"]}
    return [f"- {f['id']} [{f['source']}/{f['certainty']}] {f['text']}" for n in numbers for f in by[n]["facts"]]


# ---------------------------------------------------------------- 수필체

def essay_user_message(analysis: dict, stories: dict[int, str], chapter_id: str, sensitive: bool, extra_cautions: list[str] | None = None) -> str:
    """수필체(7c 리듬 v1)의 사용자 메시지. 장 제목은 analysis["chapters"][].title — 검증된 확정 제목이어야 한다."""
    by = {s["turn"]: s for s in analysis["stories"]}
    no, c = _chapter(analysis, chapter_id)
    nums = list(c["stories"])
    src = {str(n): stories[n] for n in nums}
    chars = nchars("\n".join(src.values()))
    toc = " / ".join(f"{x['id']} 「{x['title']}」(이야기 {', '.join(map(str, x['stories']))})" for x in analysis["chapters"])
    emo = [f"({n}) {e['who']} — {e['kind']} · 대상 {e['target']} · 세기 {e['intensity']} · {e['when']} · {'명시' if e['explicit'] else '추론(확정 금지)'} · 근거 「{e['evidence']}」"
           for n in nums for e in by[n]["emotion_notes"]]
    directions = [f"중심 장면: {c['center_scene']}", f"중심 감정 · 회고: {c['emotion']}", f"구성 방향: {c['direction']}",
                  f"이 책의 목차(이 장은 {no}/{len(analysis['chapters'])}): {toc} — 이 장은 자기 이야기만 쓰고, 다른 장의 사건은 되풀이하지 않는다."]
    if emo:
        directions.append("감정 · 회고의 관계(분석에서 뽑음 — 세기와 변화를 지키고, 추론은 확정하지 않음): " + " / ".join(emo))
    cautions = [f"픽션 허용과 주의: {c['fiction_notes']}", f"다른 장과 겹치지 않을 것: {c['avoid_overlap']}"] + list(extra_cautions or [])
    L = [f"# {chapter_id} 「{c['title']}」", "", f"- 이야기: {nums[0]} · 민감: {'true' if sensitive else 'false'}",      # 실험 실행기는 첫 이야기 번호만 찍는다 — 그대로 옮겼다
         f"- 원문 {chars}자(공백 제외) → 참고 목표 {chars * 2}~{chars * 3}자. 분량을 채우려 반복하거나 불필요한 장면을 만들지 않습니다.", "", "## 원문", ""]
    for s, t in src.items():
        L += [f"### 이야기 {s}", "", t, ""]
    L += ["## 사실 원장", ""] + _fact_lines(analysis, nums)
    L += ["", "## 반드시 남길 세부(분석에서 뽑음)", ""] + [f"- {x}" for n in nums for x in by[n]["must_keep"]]
    L += ["", "## 이 편의 집필 방향", ""] + [f"- {x}" for x in directions]
    L += ["", "## 이 편의 주의", ""] + [f"- {x}" for x in cautions]
    return "\n".join(L) + "\n" + ESSAY_SUFFIX


# ---------------------------------------------------------------- 문학체

def literary_user_message(analysis: dict, stories: dict[int, str], chapter_id: str, sensitive: bool, target_chars: tuple[int, int],
                          title_placeholder: str = TITLE_PLACEHOLDER) -> str:
    """문학체(극서정 v2)의 사용자 메시지. target_chars 는 참고 분량 — 검증된 값은 원문 1,234자(공백 제외)에 (4500, 7000) 하나뿐이다."""
    by = {s["turn"]: s for s in analysis["stories"]}
    no, c = _chapter(analysis, chapter_id)
    nums = list(c["stories"])
    n = len(nums)
    label = " · ".join(map(str, nums))
    src = {str(k): stories[k] for k in nums}
    chars = nchars("\n".join(src.values()))
    L = [f"# {chapter_id} — 제{no}장(제목 미확정) · 이야기 {label}", "",
         f"- 이 장의 제목은 아직 정해지지 않았습니다. 출력의 `title` 에는 임시값 「{title_placeholder}」을 글자 그대로 적습니다. 본문에는 제목을 넣지 않습니다.",
         f"- 이 장의 이야기: {label} ({n}개). **{n}개 이야기가 모두 작품 안에서 충분한 문학적 무게를 가져야 합니다.** 순서와 배치는 자유입니다.",
         f"- 원문 {chars}자(공백 제외) → 참고 분량 {target_chars[0]}~{target_chars[1]}자. 넓게 펼쳐 쓰는 장입니다.",
         f"- 민감한 기억: {'있음(사고 · 위험 — 경위와 결과의 사실은 원문 그대로, 표현은 자유)' if sensitive else '없음'}", "",
         "## 책의 차례(이 장의 자리)", ""]
    for i, x in enumerate(analysis["chapters"], 1):
        mark = "**" if x["id"] == chapter_id else ""
        L.append(f"- {mark}제{i}장 — 이야기 {' · '.join(map(str, x['stories']))}{mark}")
    L += ["", "## 원문", ""]
    for s, t in src.items():
        L += [f"### 이야기 {s} — {by[int(s)]['title_hint']}", "", t, ""]
    L += ["## 사실 원장", ""] + _fact_lines(analysis, nums)
    L += ["", "## 반드시 남길 세부(이야기별)", ""] + [f"- 이야기 {k}: " + " · ".join(by[k]["must_keep"]) for k in nums]
    L += ["", "## 감정 기록(원문에서 확인된 것 — 작품이 자라나는 뿌리)", ""]
    for k in nums:
        for e in by[k]["emotion_notes"]:
            L.append(f"- ({k}) {e['who']} — {e['kind']} · 대상 {e['target']} · 세기 {e['intensity']} · {e['when']} · {'원문에 명시' if e['explicit'] else '추론'} · 근거 「{e['evidence']}」")
    refl = [(k, r) for k in nums for r in by[k]["reflections_now"]]
    L += ["", "## 지금의 회고(원문에 적힌 것 — 보존)", ""] + ([f"- ({k}) {r}" for k, r in refl] or ["- 없음"])
    L += ["", "## 인물 · 때 · 곳(이야기별)", ""]
    for k in nums:
        ps = by[k]
        L.append(f"- 이야기 {k}: 인물 {' · '.join(ps['people'])} / 때 {' · '.join(ps['time'])} / 곳 {' · '.join(ps['places'])}")
    heard = [(k, h) for k in nums for h in by[k]["heard"]]
    L += ["", "## 들은 이야기(화자가 그 자리에 없었던 것)", ""] + ([f"- ({k}) {h}" for k, h in heard] or ["- 없음"])
    quotes = [(k, q) for k in nums for q in by[k]["quotes"]]
    L += ["", "## 원문의 직접 인용(글자 그대로 보존)", ""] + ([f"- ({k}) {q}" for k, q in quotes] or ["- 없음 — 따라서 이 장의 따옴표 대화는 모두 창작이며 `가상 대화`로 기록"])
    L += ["", "## 주의", "", f"- {c['fiction_notes']}", f"- 다른 장과 겹치지 않을 것: {c['avoid_overlap']}",
          "- 이야기 사이에 원문에 없는 사건 · 원인 · 결과를 만들지 않습니다. 이미지 · 정서 · 상징으로 잇는 것은 자유입니다.",
          "- 날짜 · 금액 · 시각 · 이름 등 원문에 없는 숫자와 고유명사를 만들지 않습니다."]
    return "\n".join(L) + "\n" + LITERARY_SUFFIX


# ---------------------------------------------------------------- 소설체

def novel_user_message(prompt_template: str, source_text: str) -> str:
    """소설체(최소 수정 v1)의 입력 — 프롬프트의 {{SOURCE_TEXT}} 한 군데를 원문으로 바꾼 글 전체. 시스템 프롬프트 없이 사용자 메시지 하나로 보낸다."""
    if prompt_template.count(NOVEL_PLACEHOLDER) != 1:
        raise ValueError("프롬프트에 {{SOURCE_TEXT}} 가 정확히 한 군데 있어야 한다")
    return prompt_template.replace(NOVEL_PLACEHOLDER, source_text)
