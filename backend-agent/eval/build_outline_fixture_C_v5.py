"""
사람이 검토한 시험용 목차를 만든다 — Seed C 「큰언니와 재봉틀」 (단위 8P). 모델을 부르지 않는다.

    python eval/build_outline_fixture_C_v5.py

목적: 좋은 목차가 주어졌을 때 장 집필 · 편집 · 검증이 책다운 글을 만드는지 **목차 설계와 떼어서** 본다.
바탕 사실 원장은 `eval/analysis_fixture_C_v5_reviewed.json`(시험용 분석 스냅샷)이다.

- 목차는 사실 id 와 짧은 내부 메모(문단이 하는 일)만 담는다. 완성된 문장 · 예상 본문을 넣지 않는다
- 배치는 편집적 선택이다(지금의 소리에서 열고, 시간 순으로 돌아갔다가, 지금으로 닫는다). 새 사건 · 감정 ·
  심리 · 인과를 메모에도 쓰지 않는다
- 쓰지 않는 사실은 기억 단위별 이유와 함께 omit — 다른 인물의 무관한 사건이 문단에 섞이지 않게
- 결과 `eval/outline_fixture_C_v5_reviewed.json` 은 `outline_source: reviewed_fixture` 로 표시한 **시험용 목차**다.
  자동 목차 생성이 성공한 것이 아니다. 만든 뒤 목차 계약 · 혼입 · 일괄 생략 · 필수 기억 검사를 통과해야 저장한다
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_pipeline as pipe                           # noqa: E402
from tools import memoir_pipeline as cli                                  # noqa: E402

ANALYSIS = ROOT / "eval" / "analysis_fixture_C_v5_reviewed.json"
OUT = ROOT / "eval" / "outline_fixture_C_v5_reviewed.json"
SEED = ROOT / "eval" / "memoir_seed_C.json"
FOCUS = "큰언니와 재봉틀"

# 시험이 꼭 다뤄야 할 기억 — 사용자 지시 2항의 일곱 가지와 그 사실 id
MEMORIES = [
    ("어린 시절 큰언니에게 바느질을 배운 경험", ["f17", "f18", "f19"]),
    ("서울 공장에서의 미싱 소리", ["f22", "f23"]),
    ("가게 개업 후 큰언니가 재봉틀을 보내 준 경험", ["f34", "f40", "f41", "f6"]),
    ("재봉틀과 함께한 수선집 생활", ["f4"]),
    ("큰언니의 병문안과 별세", ["f44", "f52"]),
    ("가게 정리 후에도 남겨 둔 재봉틀", ["f2", "f3", "f54", "f65"]),
    ("지금 재봉틀 소리를 들으면 언니가 생각나는 기억", ["f57", "f58", "f59", "f60"]),
]

PARAGRAPHS = [
    {"role": "지금도 남아 있는 언니의 재봉틀과 그 소리로 장을 연다", "facts": ["f57", "f58"], "brief": [], "time": "지금"},
    {"role": "어린 시절 언니에게 바느질을 배운 일과 언니가 시집간 날", "facts": ["f17", "f18", "f19", "f20", "f21", "f61"],
     "brief": ["f16"], "time": "열 살쯤~열다섯 무렵"},
    {"role": "서울 봉제 공장 기숙사의 미싱 소리", "facts": ["f22", "f23"], "brief": ["f26"], "time": "열일곱 살 이후"},
    {"role": "가게를 연 뒤 언니가 쓰던 발틀이 편지와 함께 온 일", "facts": ["f33", "f34", "f40", "f41", "f64", "f6"],
     "brief": [], "time": "1985년 봄 · 한 달쯤 뒤"},
    {"role": "그 재봉틀 앞에서 보낸 가게의 하루하루", "facts": ["f4"], "brief": ["f62"], "time": "가게 시절"},
    {"role": "언니의 병문안과 별세", "facts": ["f44", "f52"], "brief": ["f53"], "time": "2003~2004년"},
    {"role": "가게를 정리하고도 집으로 가져온 재봉틀, 그리고 지금 그 소리에 겹치는 기억", "facts": ["f2", "f3", "f54", "f65",
     "f55", "f59", "f60"], "brief": [], "time": "2010년~지금"},
]

# 쓰지 않는 사실 — 기억 단위별 이유 (이 장의 끈인 큰언니 · 재봉틀 · 미싱 소리와 닿지 않거나 다른 장면)
OMIT_REASONS = {
    "m1": "출신 · 나이 차 — 이 장에는 배경으로만 필요해 뺀다",
    "m2": "첫 월급 · 엄마의 편지 · 서울 생활 기간 · 결혼은 공장 소리와 다른 이야기 — 다른 장 몫",
    "m3": "좌판 · 간판 · 첫 손님 · 첫 천 원은 가게를 연 무렵의 다른 장면 — 이 장은 재봉틀이 온 일에 집중",
    "m4": "남편의 일 · 김 사장 · 운동회 · 자녀 대학은 가게 시절의 다른 사람 이야기 — 다른 장 몫",
    "m5": "1977년 부산 첫 방문 · 바다 — 큰언니 끈이지만 이 장은 언니의 마지막을 병문안 · 별세로 다룬다",
    "m6": "딸의 결혼 드레스 — 딸의 이야기, 다른 장 몫",
    "m8": "아들 이야기 — 다른 장 몫",
    "m9": "남편의 별세 — 화자가 말을 멈춘 대목, 이 장에 넣지 않는다",
    "m11": "딸의 책 제안과 화자의 망설임 — 책 전체의 머리말 · 맺음말 몫",
}


def build() -> dict:
    afx = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    doc = cli._seed_doc(SEED)
    data, turn_map = pipe.build_input(cli.records_from_seed(doc, afx["aliases"]))
    T = pipe.check_input(data, turn_map)
    analysis = pipe.load_analysis_fixture(afx, data, T)
    used = {f for p in PARAGRAPHS for f in p["facts"] + p["brief"]}
    home = {f: u["id"] for u in analysis["units"] for f in u["facts"]}
    omit: dict[str, list[str]] = {}
    for f in analysis["facts"]:
        if f["id"] not in used:
            omit.setdefault(home[f["id"]], []).append(f["id"])
    outline = {
        "status": "ready",
        "book": {"title": {"text": "언니의 발틀", "kind": "editorial", "facts": []},
                 "center": "큰언니가 보내 준 발틀 재봉틀", "flow": "지금의 소리에서 열고 시간 순으로 돌아갔다가 지금으로 닫는다",
                 "opening_facts": ["f58"], "closing_facts": ["f60"]},
        "chapters": [{
            "chapter_key": "ch-1", "title": {"text": "언니의 발틀", "kind": "editorial", "facts": []},
            "center": "큰언니와 언니가 보낸 재봉틀", "experience": "한 대의 재봉틀에 여러 시기의 언니 기억이 겹쳐 있다",
            "units": ["m7", "m1", "m2", "m3", "m10"],          # m4(가게 나날)는 사실 둘만 빌려 쓴다 — 중심 단위가 아니다
            "paragraphs": PARAGRAPHS,
            "reorder": [{"paragraph": 1, "reason": "지금의 재봉틀 소리에서 시작해 언니에게 바느질을 배운 어린 시절로 돌아간다",
                         "facts": ["f58"]}],
        }],
        "omit": [{"facts": fs, "reason": OMIT_REASONS[u]} for u, fs in sorted(omit.items())],
        "missing_context": [],
    }
    fx = {
        "fixture": "outline_snapshot",
        "outline_source": pipe.REVIEWED_FIXTURE,
        "synthetic": True,
        "note": "사람이 검토한 시험용 목차 — 자동 목차 생성 결과가 아니다. 장 집필 · 편집 · 검증 시험에만 쓴다.",
        "focus": FOCUS,
        "analysis_fixture": {"file": str(ANALYSIS.relative_to(ROOT)).replace("\\", "/"),
                             "sha256": hashlib.sha256(json.dumps(afx, ensure_ascii=False, sort_keys=True)
                                                      .encode("utf-8")).hexdigest()[:16]},
        "input_ref": afx["input_ref"],
        "reviewed": "Claude 가 원문 · 사실 원장 대조로 짬 — 사람 확인 전",
        "memories": [{"name": n, "facts": fs} for n, fs in MEMORIES],
        "outline": outline,
    }
    pipe.load_outline_fixture(fx, analysis, afx, T)          # 계약 · 혼입 · 일괄 생략 · 필수 기억 · 메모 검사
    status, warnings = pipe.check_outline(json.loads(json.dumps(outline)), analysis, T, FOCUS)
    fx["check"] = {"status": status, "warnings": warnings}
    return fx


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    fx = build()
    OUT.write_text(json.dumps(fx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ch = fx["outline"]["chapters"][0]
    print(f"{OUT.name} — 문단 계획 {len(ch['paragraphs'])} · 쓰는 사실 "
          f"{sum(len(p['facts']) + len(p['brief']) for p in ch['paragraphs'])} · 경고 {len(fx['check']['warnings'])}")
    for w in fx["check"]["warnings"]:
        print("  경고", w)
