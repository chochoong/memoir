"""
시험용 분석 스냅샷을 만든다 — Seed C · v5 분석 (단위 8P). 모델을 부르지 않는다.

    python eval/build_analysis_fixture_C_v5.py

바탕은 **모델이 실제로 낸 분석** `tests/data/v5_analysis_20261027T010241Z.json`
(run 20261027T010241Z-C5-b9f8-analysis · 커밋 02b423d · gemini-3.5-flash-lite) 이다.
그 위에 사실 원장의 오류와 잘못된 기억 단위**만** 고친다. 고친 것은 하나도 빠짐없이 EDITS
에 적고, 결과 파일의 `edits` 에 그대로 남긴다. 원문(Seed C)은 고치지 않고, 원문에 없는
사건 · 감정을 넣지 않는다 — 덧붙인 메모는 모두 해당 턴 원문의 말이다.

결과 `eval/analysis_fixture_C_v5_reviewed.json` 은 `analysis_source: reviewed_fixture` 로
표시된 **시험용 스냅샷**이다. 모델 원본으로 쓰지 않고, 서비스의 분석 단계를 대신하지 않는다.
후속 단계 시험(`--from-analysis`)만 받는다. 만든 뒤 분석 계약 검사를 통과해야 저장한다.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_pipeline as pipe                           # noqa: E402
from tools import memoir_pipeline as cli                                  # noqa: E402

BASE = ROOT / "tests" / "data" / "v5_analysis_20261027T010241Z.json"
OUT = ROOT / "eval" / "analysis_fixture_C_v5_reviewed.json"
SEED = ROOT / "eval" / "memoir_seed_C.json"
ALIASES = ["c1", "c2", "c3", "c4", "c5"]

# (종류, 대상, 바꿀 값, 이유, 근거 턴) — 바꾸기 전 값은 만들 때 원본에서 읽어 함께 남긴다
EDITS = [
    ("fact.set", "f56", {"source": "self"}, "source 계약 — 'reported' 는 허용 값이 아니다. 딸이 화자에게 직접 한 말이라 self", [37]),
    ("fact.set", "f21", {"source": "heard", "text": "언니가 시집가던 날 내가 많이 울었다고 들음"},
     "턴 13 '울었대요' 는 들은 이야기 — 직접 기억과 나눈다", [13]),
    ("fact.add", "f61", {"turns": [13], "text": "그날 버스 정류장은 진짜 기억남", "time": "", "source": "self",
                         "certainty": "stated", "keep": False, "unit": "m1"},
     "턴 13 '그건 진짜 기억나요, 버스 정류장에서' — 직접 기억", [13]),
    ("fact.set", "f16", {"text": "엄마가 밭일 나가면 큰언니가 업어 키웠다고 들음 · 나는 기억이 안 남"},
     "턴 10 '저는 기억은 안 나요' 보존", [10]),
    ("fact.set", "f22", {"text": "시골에 있어 봐야 할 게 없어서 열일곱 살에 서울 동대문 근처 봉제 공장으로 올라감"},
     "턴 14 상경 이유 보존", [14]),
    ("fact.set", "f23", {"text": "기숙사에서 여섯 명이 한 방을 썼고 미싱 소리가 시끄러워 밤에 누우면 귀에서 웅웅 소리가 났음"},
     "턴 15 '귀에서 웅웅' 보존", [15]),
    ("fact.set", "f24", {"text": "힘들었지만 첫 월급을 받아 집에 부칠 때는 좋았음"}, "턴 16 힘듦 · 좋았음 보존", [16]),
    ("fact.set", "f26", {"text": "재단하는 언니들 옆에서 어깨너머로 배운 걸로 평생 먹고살았음"}, "턴 17 '평생 먹고살았어요' 보존", [17]),
    ("fact.add", "f62", {"turns": [2], "text": "수선집을 한 이십오 년 했던 것 같음", "time": "", "source": "self",
                         "certainty": "uncertain", "keep": False, "unit": "m4"},
     "턴 2 '한 이십오 년 했나' — 대략 · 흐린 기간 보존", [2]),
    ("fact.add", "f63", {"turns": [8], "text": "그건 내가 했다 싶다고 함", "time": "", "source": "view",
                         "certainty": "stated", "keep": False, "unit": "m4"},
     "턴 8 자부심 — 화자의 평가(view)", [8]),
    ("fact.set", "f38", {"text": "첫 손님에게 천 원 받았던 것 같음", "certainty": "uncertain"},
     "턴 23 '천 원 받았나' — 화자도 확신하지 않음", [23]),
    ("fact.set", "f41", {"text": "편지 한 장이 같이 왔고 별말 없이 '기름 자주 쳐라' 그거 하나 적혀 있었음"},
     "턴 27 '별말 없었어요' 보존", [26, 27]),
    ("fact.add", "f64", {"turns": [27], "text": "그 편지가 언니다웠다고 함", "time": "", "source": "view",
                         "certainty": "stated", "keep": False, "unit": "m3"},
     "턴 27 '언니다웠어요' — 화자의 평가(view)", [27]),
    ("fact.set", "f44", {"text": "2003년에 언니가 아프다고 해서 부산 병원으로 병문안을 갔고 같은 부산인데 그때는 바다 쪽은 쳐다보지도 않았음"},
     "턴 29 '바다 쪽은 쳐다보지도 않았어요' 보존", [29]),
    ("fact.add", "f65", {"turns": [35], "text": "남들은 그 발틀을 고물이라고 팔라고 했음", "time": "", "source": "self",
                         "certainty": "stated", "keep": False, "unit": "m7"},
     "턴 35 화자가 직접 들은 남들의 말 보존", [35]),
    ("fact.add", "f66", {"turns": [37], "text": "나는 대단한 게 있나 싶지만 딸이 하자니까 하는 것", "time": "", "source": "view",
                         "certainty": "stated", "keep": False, "unit": "m11"},
     "턴 37 망설임 — 화자의 생각(view)", [37]),
    ("fact.set", "f60", {"text": "애들한테 그 재봉틀을 줄지는 아직 모르겠고 걔들이 쓸 일이 있겠나 싶음", "keep": True},
     "턴 39 마지막 발언 보존 · 마지막 핵심 발언이라 keep", [39]),
    ("fact.set", "f39", {"text": "첫 천 원을 한참 안 쓰고 지갑에 넣어 놓고 다님"}, "모델 메모의 글자 빠짐('넣어 고') 고침", [24]),
    ("fact.set", "f50", {"text": "말이 없는 아들이 큰언니를 닮았다고 내가 말함"},
     "턴 32 '닮았다고 제가 그래요' — 화자가 하는 말(view), '생각함' 보다 원문에 가깝게", [32]),
    # 기억 단위 — 하나의 이야기로. 개수를 맞추려는 분할이 아니라 서로 다른 사람 · 시기의 일을 떼어 놓는다
    ("unit.set", "m4", {"name": "가게를 꾸리던 나날", "time": "1985년 봄 이후 가게 시절"},
     "'고생' 은 원문 말이 아님 — 중립 이름으로", [1, 3, 5, 6, 7, 8]),
    ("unit.move", "f2", {"from": "m4", "to": "m7"}, "2010년 가게 정리는 정리 · 재봉틀을 집으로 가져온 기억(m7)과 한 이야기", [2]),
    ("unit.move", "f3", {"from": "m4", "to": "m7"}, "무릎 때문에 그만둔 일 — 가게 정리(m7)", [2]),
    ("unit.move", "f6", {"from": "m4", "to": "m3"}, "발틀이 큰언니가 보낸 것이라는 말 — 재봉틀이 온 기억(m3)과 한 이야기", [4]),
    ("unit.split", "m5", {"keep": {"name": "처음 가 본 부산과 바다", "time": "1977년쯤", "facts": ["f42", "f43"]},
                          "new": {"id": "m10", "name": "큰언니의 병과 별세", "time": "2003~2004년", "weight": "main",
                                  "facts": ["f44", "f52", "f53"]}},
     "1977 첫 방문과 2003 병문안 · 2004 별세는 다른 시기의 다른 이야기 — 부산 · 큰언니는 끈으로 잇는다", [28, 29, 34]),
    ("unit.split", "m6", {"keep": {"name": "딸의 결혼 드레스", "time": "2008년", "facts": ["f45", "f46", "f47", "f48"]},
                          "new": [{"id": "m8", "name": "말 없는 아들", "time": "", "weight": "minor", "facts": ["f49", "f50"]},
                                  {"id": "m9", "name": "남편의 별세", "time": "2015년", "weight": "minor", "facts": ["f51"]}]},
     "딸의 결혼 · 아들 · 남편의 별세는 다른 사람의 다른 일", [30, 31, 32, 33]),
    ("unit.move", "f56", {"from": "m7", "to": "m11"}, "딸의 책 제안은 재봉틀 정리와 다른 이야기", [37]),
    ("unit.add", "m11", {"name": "책으로 남기자는 딸의 말", "time": "지금", "weight": "minor", "facts": []},
     "딸의 제안 · 화자의 망설임(m11)", [37]),
    ("thread.set", "t1", {"units": ["m1", "m3", "m5", "m10", "m7"]}, "큰언니 끈 — 나눈 단위를 잇는다", [13, 26, 34, 38]),
    ("thread.set", "t3", {"units": ["m1", "m5", "m10"]}, "부산 끈 — 시집 · 첫 방문 · 병문안", [13, 28, 29]),
    ("thread.add", "t4", {"name": "미싱 소리", "kind": "object", "units": ["m2", "m7"], "link_turns": [38]},
     "턴 38 화자가 공장 때의 소리와 지금 소리를 직접 이었다", [15, 38]),
    ("theme.set", 0, {"counter": [15, 38]}, "복합 근거 — 공장 때 싫었던 소리 · 지금의 언니 생각", [15, 38]),
    ("theme.set", 1, {"theme": "가게를 꾸리며 자식을 키운 세월", "strength": "partial", "counter": [7, 31]},
     "'고생' 은 원문 말이 아님 — 중립 이름, 미안함 · 아쉬움은 counter", [3, 7, 8, 31]),
    ("direction.set", None, {"reason": "큰언니와의 어린 시절과 언니가 보내 준 재봉틀이 여러 시기에 걸쳐 다시 나온다"},
     "'큰 울림' 같은 평가 말을 빼고 근거만", [4, 11, 26, 38]),
]


def build() -> dict:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    a = copy.deepcopy(base)
    facts = {f["id"]: f for f in a["facts"]}
    units = {u["id"]: u for u in a["units"]}
    log = []
    for kind, target, change, reason, turns in EDITS:
        rec = {"kind": kind, "target": target, "reason": reason, "turns": turns}
        if kind == "fact.set":
            f = facts[target]
            rec["before"] = {k: f[k] for k in change}
            f.update(change)
        elif kind == "fact.add":
            assert target not in facts, target
            c = dict(change)
            unit = c.pop("unit")
            f = {"id": target, **c}
            a["facts"].append(f)
            facts[target] = f
            if unit in units:
                units[unit]["facts"].append(target)
            else:
                a.setdefault("_pending", {}).setdefault(unit, []).append(target)
            rec["before"] = None
        elif kind == "unit.set":
            u = units[target]
            rec["before"] = {k: u[k] for k in change}
            u.update(change)
        elif kind == "unit.move":
            units[change["from"]]["facts"].remove(target)
            if change["to"] in units:
                units[change["to"]]["facts"].append(target)
            else:
                a.setdefault("_pending", {}).setdefault(change["to"], []).append(target)
            rec["before"] = {"unit": change["from"]}
        elif kind == "unit.split":
            u = units[target]
            rec["before"] = {k: copy.deepcopy(u[k]) for k in ("name", "time", "facts")}
            u.update(change["keep"])
            for n in change["new"] if isinstance(change["new"], list) else [change["new"]]:
                a["units"].append(dict(n))
                units[n["id"]] = a["units"][-1]
        elif kind == "unit.add":
            u = {"id": target, **change}
            u["facts"] = list(a.get("_pending", {}).pop(target, []))
            a["units"].append(u)
            units[target] = u
            rec["before"] = None
        elif kind == "thread.set":
            th = next(x for x in a["threads"] if x["id"] == target)
            rec["before"] = {k: th[k] for k in change}
            th.update(change)
        elif kind == "thread.add":
            a["threads"].append({"id": target, **change})
            rec["before"] = None
        elif kind == "theme.set":
            th = a["themes"][target]
            rec["before"] = {k: th.get(k) for k in change}
            th.update(change)
        elif kind == "direction.set":
            rec["before"] = {k: a["direction"].get(k) for k in change}
            a["direction"].update(change)
        else:
            raise ValueError(kind)
        rec["after"] = change
        log.append(rec)
    assert not a.get("_pending"), a.get("_pending")
    a.pop("_pending", None)
    a.pop("normalized", None)

    doc = cli._seed_doc(SEED)
    data, turn_map = pipe.build_input(cli.records_from_seed(doc, ALIASES))
    T = pipe.check_input(data, turn_map)
    status, warnings = pipe.check_analysis(copy.deepcopy(a), T, pipe.turn_marks(data),
                                           pipe.source_texts(data), pipe.source_asked(data))
    assert status == "ready"
    return {
        "fixture": "analysis_snapshot",
        "analysis_source": pipe.REVIEWED_FIXTURE,
        "synthetic": True,
        "note": "시험용 분석 스냅샷 — 모델이 생성한 원본이 아니다. 서비스 분석 단계를 대신하지 않고 후속 단계 시험에만 쓴다.",
        "based_on": {"file": str(BASE.relative_to(ROOT)).replace("\\", "/"),
                     "sha256": hashlib.sha256(BASE.read_bytes()).hexdigest()[:16],
                     "run_ref": "20261027T010241Z-C5-b9f8-analysis", "commit": "02b423d",
                     "model": "gemini-3.5-flash-lite"},
        "seed": SEED.name, "aliases": ALIASES, "input_ref": pipe.input_ref(data),
        "reviewed": "Claude 가 원문 대조로 고침 — 사람 확인 전",
        "edits": log,
        "check": {"status": status, "warnings": warnings},
        "analysis": a,
    }


if __name__ == "__main__":
    for s in (sys.stdout,):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    fx = build()
    OUT.write_text(json.dumps(fx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{OUT.name} — 고친 항목 {len(fx['edits'])} · 사실 {len(fx['analysis']['facts'])} · "
          f"기억 단위 {len(fx['analysis']['units'])} · 경고 {len(fx['check']['warnings'])}")
    for w in fx["check"]["warnings"]:
        print("  경고", w)
