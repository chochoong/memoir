"""
자서전 검증 — seed · 합치기 · 응답 검사 · 라우트 (업무지시서 01 v1.1)

    python -m tests.test_memoir

모델도 DB 도 부르지 않는다. write 를 갈아 끼우고 회차는 seed JSON 에서 세운다.
여기서 지키는 것.

    seed     eval/ 의 A · B 는 통과하고, 틀린 입력은 쓰기 전에 걸린다
    seed     판단은 한 칸 뒤에, 마지막 판단은 closing_decision 에 넣는다
    S1       A 3회차 — 지시서 4절의 입력 JSON · 3절의 대응표와 글자까지 같다
    S2       A 5회차 — 고른 것이 전부 들어간다
    B        정정 전 사실도 지우지 않는다 · 제외 요청도 원문으로 남는다
    S3 · S4  잘못 고르면 400 · 404, 모델을 부르지 않는다
    S5       정상 · 자료 부족은 200, 어긋난 구조는 502
    S8 · S9  실패 주입 — 422 · 502 · 504, 모델을 부르지 않는다
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app.session import memoir, store                                     # noqa: E402
from tests._nodb import NoDb                                              # noqa: E402
from tools import seed_sessions as seed                                   # noqa: E402

PASS, FAIL = [], []

SEED_A = json.loads((ROOT / "eval" / "memoir_seed_A.json").read_text(encoding="utf-8"))
SEED_B = json.loads((ROOT / "eval" / "memoir_seed_B.json").read_text(encoding="utf-8"))

ME, OTHER = "dev-user", "other-test-user"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK ' if cond else '!! '}{name}{'  — ' + detail if detail else ''}")


class _Env:
    def __init__(self, **kv):
        self.kv = {k: str(v) for k, v in kv.items()}
        self.old: dict[str, str | None] = {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def record(sess: dict, sid: str | None = None, user_id: str = ME, card: bool = True) -> dict:
    """seed 회차 하나를 store.load_session 이 돌려주는 모양으로. seed 도구와 같은 rows() 를 쓴다."""
    turn_rows, closing = seed.rows(sess)
    return {
        "session_id": sid or sess["alias"], "user_id": user_id, "title": sess["title"],
        "created_at": f"2026-10-12T10:{sess['recorded_order']:02d}:00+00:00",
        "closed_at": f"2026-10-12T10:{sess['recorded_order']:02d}:50+00:00",
        "fragments": turn_rows,
        "closing_decision": closing,
        "postcard": {"title": "엽서", "text": "글", "caption": "", "storage_key": "k",
                     "created_at": "2026-10-12T11:00:00+00:00"} if card else None,
    }


def records(doc: dict, aliases: list[str]) -> list[dict]:
    by = {s["alias"]: s for s in doc["sessions"]}
    return [record(by[a]) for a in aliases]


# ---------------------------------------------------------------- seed


def test_seed():
    print("\n[seed] 입력 검사 · 판단 자리")
    check("A 는 통과한다", seed.check_seed(SEED_A) == [], str(seed.check_seed(SEED_A)))
    check("B 는 통과한다", seed.check_seed(SEED_B) == [], str(seed.check_seed(SEED_B)))

    def broken(fn) -> list[str]:
        doc = copy.deepcopy(SEED_A)
        fn(doc)
        return seed.check_seed(doc)

    def setv(path, value):
        def fn(doc):
            cur = doc
            for k in path[:-1]:
                cur = cur[k]
            cur[path[-1]] = value
        return fn

    cases = {
        "모르는 세트는 거절한다": setv(["set_id"], "P"),
        "다른 사용자는 거절한다": setv(["user_id"], "kim"),
        "제목 접두어가 다르면 거절한다": setv(["sessions", 0, "title"], "[B] 첫 월급"),
        "alias 가 겹치면 거절한다": setv(["sessions", 1, "alias"], "s-a"),
        "recorded_order 가 겹치면 거절한다": setv(["sessions", 1, "recorded_order"], 1),
        "idx 가 겹치면 거절한다": setv(["sessions", 0, "turns", 1, "idx"], 1),
        "씨앗에 글이 있으면 거절한다": setv(["sessions", 0, "seed"], {"question": None, "answer": "첫 월급"}),
        "빈 말씀은 거절한다": setv(["sessions", 0, "turns", 0, "answer"], " "),
        "사실 칸이 없으면 거절한다": lambda d: d["sessions"][0]["turns"][0].pop("facts_found"),
        "규격 이름이 다르면 거절한다": setv(["schema_version"], "memoir-seed-v1.0"),
    }
    for name, fn in cases.items():
        check(name, len(broken(fn)) >= 1)

    s_r2 = SEED_B["sessions"][1]
    turn_rows, closing = seed.rows(s_r2)
    check("0번은 씨앗이다 — 질문 없음 · 빈 글",
          turn_rows[0] == {"idx": 0, "question": None, "answer": "", "decision": None})
    check("말씀은 1번부터 원문 그대로다",
          [r["answer"] for r in turn_rows[1:]] == [t["answer"] for t in s_r2["turns"]])
    check("1번 행의 판단은 비운다", turn_rows[1]["decision"] is None)
    check("k 번 말씀의 판단은 k+1 번 행에 있다",
          turn_rows[2]["decision"]["facts_found"] == ["꽃집 첫 손님"]
          and turn_rows[3]["decision"]["facts_found"] == ["누나에게 삼백만 원 빌림"])
    check("마지막 말씀의 판단은 closing_decision 이다 — 한 번만",
          closing == {"facts_found": [], "facts_retracted": []})


# ---------------------------------------------------------------- 합치기

# 지시서 4절 「모델 입력 JSON 예시」와 3절 「대응표 예시」 그대로.
WANT_A3 = {
    "shared_state": {
        "confirmed_facts": ["광주 인쇄소 첫 월급", "어머니께 빨간 목도리", "동생과 전주 여행",
                            "동생의 첫 기차", "딸 초등학교 입학", "노란 가방"],
        "facts_found": [
            {"turn": 1, "facts": ["광주 인쇄소 첫 월급"]},
            {"turn": 2, "facts": ["어머니께 빨간 목도리"]},
            {"turn": 3, "facts": ["동생과 전주 여행"]},
            {"turn": 4, "facts": ["동생의 첫 기차"]},
            {"turn": 5, "facts": ["딸 초등학교 입학"]},
            {"turn": 6, "facts": ["노란 가방"]},
        ],
    },
    "sessions": [
        {"session_id": "s-a", "recorded_order": 1},
        {"session_id": "s-b", "recorded_order": 2},
        {"session_id": "s-c", "recorded_order": 3},
    ],
    "utterances": [
        {"turn": 1, "session_id": "s-a", "asked": "",
         "elder": "1979년에 광주 인쇄소에서 첫 월급을 받았어요."},
        {"turn": 2, "session_id": "s-a", "asked": "",
         "elder": "그 돈으로 어머니께 빨간 목도리를 사 드려 참 뿌듯했어요."},
        {"turn": 3, "session_id": "s-b", "asked": "",
         "elder": "1985년쯤 동생과 기차를 타고 전주로 놀러 갔어요."},
        {"turn": 4, "session_id": "s-b", "asked": "",
         "elder": "기차를 처음 탄 건 동생이에요. 저는 전에도 타 봤어요."},
        {"turn": 5, "session_id": "s-c", "asked": "",
         "elder": "1996년에 딸이 초등학교에 입학해서 제가 데려다줬어요."},
        {"turn": 6, "session_id": "s-c", "asked": "",
         "elder": "노란 가방을 메고 교실에 들어가는 딸을 보니 마음이 뭉클했어요."},
    ],
}
WANT_MAP_A3 = [
    {"global_turn": 1, "session_id": "s-a", "turn": 1},
    {"global_turn": 2, "session_id": "s-a", "turn": 2},
    {"global_turn": 3, "session_id": "s-b", "turn": 1},
    {"global_turn": 4, "session_id": "s-b", "turn": 2},
    {"global_turn": 5, "session_id": "s-c", "turn": 1},
    {"global_turn": 6, "session_id": "s-c", "turn": 2},
]


def test_merge():
    print("\n[S1 · S2 · B] 합치기")
    data, turn_map = memoir.merge(records(SEED_A, ["s-a", "s-b", "s-c"]))
    check("A 3회차 입력이 지시서 4절과 같다", data == WANT_A3)
    check("열쇠 순서도 같다 (JSON 글자까지)",
          json.dumps(data, ensure_ascii=False) == json.dumps(WANT_A3, ensure_ascii=False))
    check("대응표가 지시서 3절과 같다", turn_map == WANT_MAP_A3)

    back, back_map = memoir.merge(records(SEED_A, ["s-c", "s-a", "s-b"]))
    check("고른 순서가 아니라 기록 순서로 세운다", back == WANT_A3 and back_map == WANT_MAP_A3)

    five, five_map = memoir.merge(records(SEED_A, ["s-a", "s-b", "s-c", "s-d", "s-e"]))
    check("A 5회차 — 말씀 8개가 전부 들어간다",
          [u["turn"] for u in five["utterances"]] == list(range(1, 9))
          and five["utterances"][-1]["elder"] == "2010년에 집 베란다에서 화분을 키우기 시작했어요.")
    check("1턴짜리 회차의 사실도 마지막 판단에서 살아난다",
          {"turn": 7, "facts": ["동네 도서관 책 정리 봉사"]} in five["shared_state"]["facts_found"]
          and {"turn": 8, "facts": ["베란다 화분 키우기 시작"]} in five["shared_state"]["facts_found"])
    check("5회차의 기록 순서는 1~5 다",
          [s["recorded_order"] for s in five["sessions"]] == [1, 2, 3, 4, 5]
          and five_map[-1] == {"global_turn": 8, "session_id": "s-e", "turn": 1})

    b, b_map = memoir.merge(records(SEED_B, ["s-r1", "s-r2", "s-r3"]))
    facts = b["shared_state"]["confirmed_facts"]
    check("B — 말씀 7개 · 회차마다 턴이 이어진다",
          [(m["session_id"], m["turn"]) for m in b_map]
          == [("s-r1", 1), ("s-r1", 2), ("s-r2", 1), ("s-r2", 2), ("s-r2", 3), ("s-r3", 1), ("s-r3", 2)])
    check("B — 정정 전 사실을 서버가 지우지 않는다",
          "딸 입학 1998년" in facts and "딸 입학 1996년" in facts)
    check("B — 제외 요청은 원문으로 남고, 빌린 돈 사실도 지우지 않는다",
          b["utterances"][4]["elder"].startswith("누나에게 돈을 빌린 이야기와 금액은 자서전에서 빼 주세요")
          and "누나에게 삼백만 원 빌림" in facts)
    check("B — 사실이 없는 말씀에는 facts_found 줄이 없다",
          [x["turn"] for x in b["shared_state"]["facts_found"]] == [1, 2, 3, 4, 6, 7])
    check("B — 마지막 말씀과 마지막 판단이 남는다",
          b["utterances"][-1]["elder"] == "그 입학 때 딸은 울지 않았고, 저는 딸을 보며 마음이 뭉클했어요."
          and b["shared_state"]["facts_found"][-1] == {"turn": 7, "facts": ["딸은 울지 않음"]})
    check("모든 말씀에 회차가 붙어 있다", all(u["session_id"] for u in b["utterances"]))

    same = records(SEED_A, ["s-a", "s-b", "s-c"])
    same[1]["created_at"] = same[0]["created_at"]
    try:
        memoir.merge(same)
        ok = False
    except memoir.SourceUnavailable:
        ok = True
    check("시각이 같은 회차는 순서를 지어내지 않는다", ok)

    text = memoir._input(data)
    check("원문은 자료 메시지에만 있고 시스템 지시에는 없다",
          "광주 인쇄소" in text and "광주 인쇄소" not in memoir._prompt())
    check("시스템 지시는 자서전.md 그대로다",
          memoir._prompt() == memoir.PROMPT.read_text(encoding="utf-8").strip())


# ---------------------------------------------------------------- 고르기 · 응답 검사

READY = {
    "status": "ready",
    "title": "세 가지 기억",
    "body": "1979년, 광주 인쇄소에서 첫 월급을 받았습니다.\n"
            "그 돈으로 어머니께 빨간 목도리를 사 드려 참 뿌듯했습니다.\n"
            "1985년쯤 동생과 기차를 타고 전주에 다녀왔습니다.",
    "sources": [{"sentence": 0, "turns": [1]}, {"sentence": 1, "turns": [1, 2]},
                {"sentence": 2, "turns": [3]}],
    "to_confirm": [],
}
EMPTY = {"status": "insufficient_material", "title": "", "body": "", "sources": [], "to_confirm": []}
TURNS = {1, 2, 3, 4, 5, 6}


def _with(base: dict, **kv) -> dict:
    out = copy.deepcopy(base)
    out.update(kv)
    return out


BROKEN = {
    "없는 턴을 가리키는 출처": _with(READY, sources=[{"sentence": 0, "turns": [1]},
                                              {"sentence": 1, "turns": [9]},
                                              {"sentence": 2, "turns": [3]}]),
    "sentence 번호가 겹치는 출처": _with(READY, sources=[{"sentence": 0, "turns": [1]},
                                                 {"sentence": 0, "turns": [2]},
                                                 {"sentence": 2, "turns": [3]}]),
    "출처가 모자란 본문": _with(READY, sources=READY["sources"][:2]),
    "turns 가 빈 출처": _with(READY, sources=[{"sentence": 0, "turns": []},
                                          {"sentence": 1, "turns": [2]},
                                          {"sentence": 2, "turns": [3]}]),
    "빈 줄이 낀 본문": _with(READY, body=READY["body"].replace("\n", "\n\n", 1)),
    "소제목이 든 본문": _with(READY, body="# 첫 월급\n" + READY["body"],
                         sources=READY["sources"] + [{"sentence": 3, "turns": [3]}]),
    "제목이 빈 ready": _with(READY, title=" "),
    "모르는 status": _with(READY, status="completed"),
    "키가 하나 빠진 응답": {k: v for k, v in READY.items() if k != "to_confirm"},
    "키가 하나 더 있는 응답": _with(READY, chapters=[]),
    "본문이 남은 자료 부족": _with(EMPTY, body="한 줄"),
    "객체가 아닌 응답": [READY],
}


def test_check():
    print("\n[S3 · S5] 고르기 · 응답 구조")
    a, b, c, d, e, f = (f"00000000-0000-4000-8000-00000000000{n}" for n in range(1, 7))

    def refused(ids) -> bool:
        try:
            memoir.check_selection(ids)
            return False
        except memoir.BadSelection:
            return True

    check("3개는 받는다", memoir.check_selection([a, b, c]) == [a, b, c])
    check("5개는 받는다", len(memoir.check_selection([a, b, c, d, e])) == 5)
    check("2개는 거절한다", refused([a, b]))
    check("6개는 거절한다", refused([a, b, c, d, e, f]))
    check("같은 회차 두 번은 거절한다", refused([a, b, a]))
    check("대소문자만 다른 같은 회차도 거절한다",
          refused(["ABCDEF00-0000-4000-8000-000000000001", "abcdef00-0000-4000-8000-000000000001", c]))
    check("UUID 가 아니면 거절한다", refused(["s-a", "s-b", "s-c"]))
    check("목록이 아니면 거절한다", refused(None) and refused("x") and refused({"a": 1}))

    check("정상 응답은 그대로 통과한다", memoir.check(copy.deepcopy(READY), TURNS) == READY)
    check("자료 부족은 그대로 통과한다", memoir.check(copy.deepcopy(EMPTY), TURNS) == EMPTY)
    check("자료 부족에도 확인할 것은 남길 수 있다",
          memoir.check(_with(EMPTY, to_confirm=[{"issue": "말씀이 없음", "turns": [1]}]), TURNS)["to_confirm"])
    for name, out in BROKEN.items():
        try:
            memoir.check(copy.deepcopy(out), TURNS)
            ok = False
        except memoir.GenerationFailed:
            ok = True
        check(f"{name} — 고치지 않고 걸러 낸다", ok)

    long_body = "\n".join(f"문장 {i}." for i in range(12))
    long_out = _with(READY, body=long_body, sources=[{"sentence": i, "turns": [1]} for i in range(12)])
    check("8문장을 넘어도 자르지 않는다", memoir.check(long_out, TURNS)["body"] == long_body)


# ---------------------------------------------------------------- 라우트


class _Fake:
    """store.load_session 을 seed 회차로, memoir.write 를 정해 둔 응답으로 갈아 끼운다."""

    def __init__(self):
        self.ids = {s["alias"]: f"00000000-0000-4000-8000-0000000000{n:02d}"
                    for n, s in enumerate(SEED_A["sessions"], start=1)}
        self.recs = {self.ids[s["alias"]]: record(s, self.ids[s["alias"]])
                     for s in SEED_A["sessions"]}
        self.out = copy.deepcopy(READY)
        self.writes = 0
        self.seen: dict | None = None
        self.db_down = False

    def pick(self, *aliases) -> dict:
        return {"session_ids": [self.ids[a] for a in aliases]}

    def __enter__(self):
        self._saved = (store.load_session, memoir.write)

        async def load_session(sid):
            if self.db_down:
                raise store.StoreUnavailable("회차를 읽지 못했습니다")
            rec = self.recs.get(sid)
            return copy.deepcopy(rec) if rec else None

        async def write(data):
            self.writes += 1
            self.seen = data
            return copy.deepcopy(self.out)

        store.load_session, memoir.write = load_session, write
        return self

    def __exit__(self, *a):
        store.load_session, memoir.write = self._saved


def test_routes():
    print("\n[S3 · S4 · S5 · S8 · S9] 라우트")
    from fastapi.testclient import TestClient

    from app.main import app

    url = "/api/memoirs/preview"
    me, other = {"X-User-Id": ME}, {"X-User-Id": OTHER}

    with _Env(AZURE_SPEECH_KEY="", GEMINI_API_KEY="", MEMOIR_FAIL_INJECT="off"), _Fake() as fake, NoDb():
        with TestClient(app) as c:
            three = fake.pick("s-a", "s-b", "s-c")

            def only_detail(r) -> bool:
                body = r.json()
                return list(body) == ["detail"] and isinstance(body["detail"], str) and "요" in body["detail"]

            r = c.post(url, json=three, headers=me)
            check("3개를 고르면 200 · 모델 응답 그대로", r.status_code == 200 and r.json() == READY,
                  f"{r.status_code} {r.text[:80]}")
            check("모델은 한 번만 부른다", fake.writes == 1, str(fake.writes))
            check("모델에 간 입력은 합치기 결과다 (말씀 6개 · 회차 3개)",
                  len(fake.seen["utterances"]) == 6 and len(fake.seen["sessions"]) == 3)
            check("응답에 turn_map 이 실리지 않는다", set(r.json()) == set(memoir.KEYS))

            r = c.post(url, json=fake.pick("s-a", "s-b", "s-c", "s-d", "s-e"), headers=me)
            check("5개를 고르면 말씀 8개가 전부 간다",
                  r.status_code == 200 and len(fake.seen["utterances"]) == 8, f"{r.status_code}")

            fake.writes = 0
            for name, body in {
                "2개": fake.pick("s-a", "s-b"),
                "6개": {"session_ids": three["session_ids"] * 2},
                "중복": {"session_ids": three["session_ids"][:2] + three["session_ids"][:1]},
                "UUID 가 아닌 것": {"session_ids": ["s-a", "s-b", "s-c"]},
                "session_ids 가 없는 본문": {"ids": three["session_ids"]},
            }.items():
                r = c.post(url, json=body, headers=me)
                check(f"{name} → 400 · detail", r.status_code == 400 and only_detail(r),
                      f"{r.status_code} {r.text[:60]}")
            r = c.post(url, content=b"{not json", headers={**me, "Content-Type": "application/json"})
            check("깨진 본문 → 400 · detail", r.status_code == 400 and only_detail(r), f"{r.status_code}")

            ghost = {"session_ids": three["session_ids"][:2] + ["00000000-0000-4000-8000-0000000000ff"]}
            r = c.post(url, json=ghost, headers=me)
            check("없는 회차 → 404 · detail", r.status_code == 404 and only_detail(r), f"{r.status_code}")

            r = c.post(url, json=three, headers=other)
            check("다른 X-User-Id → 404 · detail (S4)", r.status_code == 404 and only_detail(r),
                  f"{r.status_code}")

            fake.recs[fake.ids["s-b"]]["postcard"] = None
            r = c.post(url, json=three, headers=me)
            check("엽서가 없는 회차 → 404", r.status_code == 404, f"{r.status_code}")
            fake.recs[fake.ids["s-b"]] = record(SEED_A["sessions"][1], fake.ids["s-b"])
            check("잘못 고른 요청은 모델을 부르지 않는다", fake.writes == 0, str(fake.writes))

            fake.out = copy.deepcopy(EMPTY)
            r = c.post(url, json=three, headers=me)
            check("자료 부족은 200 · insufficient_material", r.status_code == 200 and r.json() == EMPTY,
                  f"{r.status_code} {r.text[:60]}")

            for name in ("없는 턴을 가리키는 출처", "sentence 번호가 겹치는 출처"):
                fake.out = copy.deepcopy(BROKEN[name])
                r = c.post(url, json=three, headers=me)
                check(f"{name} → 502 · detail", r.status_code == 502 and only_detail(r),
                      f"{r.status_code} {r.text[:60]}")
            check("실패 응답에 본문이나 원문이 새지 않는다",
                  "광주" not in r.text and "invalid_model_output" not in r.text)
            fake.out = copy.deepcopy(READY)

            fake.db_down = True
            fake.writes = 0
            r = c.post(url, json=three, headers=me)
            check("DB 를 못 읽으면 422 · detail", r.status_code == 422 and only_detail(r), f"{r.status_code}")
            check("못 읽었으면 모델을 부르지 않는다", fake.writes == 0)
            fake.db_down = False

            with _Env(MEMOIR_FAIL_INJECT="source_material_unavailable"):
                r = c.post(url, json=three, headers=me)
                check("주입 source_material_unavailable → 422 (S8)",
                      r.status_code == 422 and only_detail(r), f"{r.status_code}")
                check("S8 — 모델을 부르지 않는다", fake.writes == 0)
                r = c.post(url, json=fake.pick("s-a", "s-b"), headers=me)
                check("S8 — 선택 검사가 주입보다 먼저다 (400)", r.status_code == 400, f"{r.status_code}")
                r = c.post(url, json=three, headers=other)
                check("S8 — 사용자 범위 검사가 주입보다 먼저다 (404)", r.status_code == 404, f"{r.status_code}")

            # S9 는 진짜 write 로 본다. 주입은 모델을 부르기 전에 걸린다.
            memoir.write = fake._saved[1]
            for hook, code in (("generation_failed", 502), ("generation_timeout", 504)):
                with _Env(MEMOIR_FAIL_INJECT=hook):
                    r = c.post(url, json=three, headers=me)
                    check(f"주입 {hook} → {code} · detail (S9)",
                          r.status_code == code and only_detail(r), f"{r.status_code} {r.text[:60]}")
                    check(f"{hook} — 가짜 본문도 자료 부족도 아니다", "status" not in r.json())

    with _Env(MEMOIR_FAIL_INJECT="nonsense"):
        check("모르는 주입 값은 끈 것으로 읽는다", memoir.inject() == "")


def test_all_checks_passed():
    """pytest 안전판 — test_flow.py 의 같은 함수 주석 참조."""
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 자서전 검증")
    test_seed()
    test_merge()
    test_check()
    test_routes()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
