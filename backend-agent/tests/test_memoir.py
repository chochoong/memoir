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
from tests._auth import AsHeader                                          # noqa: E402
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
    p = memoir._prompt()
    check("시스템 지시는 자서전_v4.md 의 실행 절이다 (§2 · §5 · §5-2 · §7-4 · §8-2)",
          memoir.PROMPT.name == "자서전_v4.md"
          and p.startswith("당신은 한국어 인생기록 서비스") and "전달된 같은 화자의 회차만" in p
          and "자서전은 위 7개 키" in p and "회차당 3~8문장" in p and "상태 우선순위" in p, p[:30])
    check("다른 역할 절은 싣지 않는다", "사진 속 기억을 담은" not in p)
    check("울타리 줄(``` · ~~~)은 싣지 않는다", "~~~" not in p and "```" not in p)
    # 분량은 자서전.md 만 정한다. 자료 메시지에 남으면 프롬프트를 고쳐도 옛 기준이 같이 간다.
    head = text.split("\n\n", 1)[0]
    check("자료 메시지에 분량 지시가 없다",
          not any(w in head for w in ("3~8", "문장을 기준", "회차 하나에")), head[-80:])
    check("자료 메시지에 턴 설명과 소제목 금지는 남아 있다",
          "utterances.turn" in head and "소제목" in head)


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
    "missing_context": [],
    "coverage_notes": [],
}
EMPTY = {"status": "insufficient_material", "title": "", "body": "", "sources": [], "to_confirm": [],
         "missing_context": [], "coverage_notes": []}


def shown(out: dict, ids: list[str], style: str = "spoken") -> dict:
    """화면에 나가는 7키 — 모델 응답의 다섯 키에 요청받은 문체 · 실제로 쓴 회차."""
    return {**{k: out[k] for k in memoir.SHOWN}, "style": style, "run": {"session_ids": ids}}
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
    "예전 5키 응답": {k: READY[k] for k in ("status", "title", "body", "sources", "to_confirm")},
    "목록이 아닌 missing_context": _with(READY, missing_context="없음"),
    "문자열이 아닌 coverage_notes": _with(READY, coverage_notes=[{"note": 1}]),
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

    for status, key in (("needs_confirmation", "to_confirm"), ("needs_context", "missing_context")):
        reasons = [{"issue": "누구의 일인지", "turns": [2]}] if key == "to_confirm" else ["2회차 원문 없음"]
        try:
            memoir.check(_with(EMPTY, status=status, **{key: reasons}), TURNS)
            got = None
        except memoir.NotFinal as e:
            got = e
        check(f"{status} — 초안으로 내보내지 않고 상태 · 사유를 들고 간다",
              got is not None and got.status == status and got.reasons == reasons,
              repr(got))

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
        self._saved = (store.load_session, memoir.write, store.owns_elder, store.memoir_sessions)

        async def load_session(sid):
            if self.db_down:
                raise store.StoreUnavailable("회차를 읽지 못했습니다")
            rec = self.recs.get(sid)
            return copy.deepcopy(rec) if rec else None

        async def write(data):
            self.writes += 1
            self.seen = data
            return copy.deepcopy(self.out)

        # 빼기 요청 — 화자는 ME 의 e_mom 하나. 「전부」 는 SQL 과 같은 규칙을 seed 회차에 건다 (tests/test_speaker [S3])
        async def owns_elder(user_id, elder_id):
            if self.db_down:
                raise store.StoreUnavailable("화자 확인에 실패했습니다")
            return (user_id, elder_id) == (ME, "e_mom")

        async def memoir_sessions(user_id, elder_id):
            said = lambda r: any(f["idx"] > 0 and (f.get("answer") or "").strip()   # noqa: E731
                                 for f in r["fragments"])
            got = [r for r in self.recs.values() if r["user_id"] == user_id and r.get("elder_id") == elder_id
                   and r["closed_at"] and said(r)]
            return [r["session_id"] for r in sorted(got, key=lambda r: r["created_at"])]

        store.load_session, memoir.write = load_session, write
        store.owns_elder, store.memoir_sessions = owns_elder, memoir_sessions
        return self

    def __exit__(self, *a):
        store.load_session, memoir.write, store.owns_elder, store.memoir_sessions = self._saved


def test_routes():
    print("\n[S3 · S4 · S5 · S8 · S9] 라우트")
    from fastapi.testclient import TestClient

    from app.main import app

    url = "/api/memoirs/preview"
    me, other = {"X-User-Id": ME}, {"X-User-Id": OTHER}

    with _Env(AZURE_SPEECH_KEY="", GEMINI_API_KEY="", MEMOIR_FAIL_INJECT="off"), _Fake() as fake, NoDb(), AsHeader():
        with TestClient(app) as c:
            three = fake.pick("s-a", "s-b", "s-c")

            def failed(r, code: str) -> bool:
                """안내 문장 + 갈래 code 둘만 나간다."""
                body = r.json()
                return (set(body) == {"detail", "code"} and body["code"] == code
                        and isinstance(body["detail"], str) and "요" in body["detail"])

            r = c.post(url, json=three, headers=me)
            check("3개를 고르면 200 · 다섯 키 + style + run", r.status_code == 200 and r.json() == shown(READY, three["session_ids"]),
                  f"{r.status_code} {r.text[:80]}")
            check("모델은 한 번만 부른다", fake.writes == 1, str(fake.writes))
            check("모델에 간 입력은 합치기 결과다 (말씀 6개 · 회차 3개)",
                  len(fake.seen["utterances"]) == 6 and len(fake.seen["sessions"]) == 3)
            check("응답에 turn_map · missing_context · coverage_notes 가 실리지 않는다",
                  set(r.json()) == {*memoir.SHOWN, "style", "run"})

            r = c.post(url, json={**three, "style": "spoken"}, headers=me)
            check("style spoken 을 보내면 200 · 응답 style spoken",
                  r.status_code == 200 and r.json() == shown(READY, three["session_ids"]), f"{r.status_code} {r.text[:80]}")

            # 지원하지 않는 문체 — 고른 회차가 틀린 400 과 code 로 갈린다.
            fake.writes = 0
            for v in ("novel", "cyworld", "essay", "Spoken", "", 3, ["spoken"]):
                r = c.post(url, json={**three, "style": v}, headers=me)
                check(f"style {v!r} → 400 · code unsupported_style",
                      r.status_code == 400 and r.json() == {
                          "detail": "지원하지 않는 문체예요.", "code": "unsupported_style"},
                      f"{r.status_code} {r.text[:80]}")
            check("거절한 문체로는 모델을 안 불렀다", fake.writes == 0, str(fake.writes))

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
                check(f"{name} → 400 · code bad_selection", r.status_code == 400 and failed(r, "bad_selection"),
                      f"{r.status_code} {r.text[:60]}")
            r = c.post(url, content=b"{not json", headers={**me, "Content-Type": "application/json"})
            check("깨진 본문 → 400 · bad_selection", r.status_code == 400 and failed(r, "bad_selection"), f"{r.status_code}")

            ghost = {"session_ids": three["session_ids"][:2] + ["00000000-0000-4000-8000-0000000000ff"]}
            r = c.post(url, json=ghost, headers=me)
            check("없는 회차 → 404 · not_found", r.status_code == 404 and failed(r, "not_found"), f"{r.status_code}")

            r = c.post(url, json=three, headers=other)
            check("다른 X-User-Id → 404 · not_found (S4)", r.status_code == 404 and failed(r, "not_found"),
                  f"{r.status_code}")

            check("잘못 고른 요청은 모델을 부르지 않는다", fake.writes == 0, str(fake.writes))

            # 엽서는 조건이 아니다 — 근거는 말씀이다 (태헌 10-26).
            fake.recs[fake.ids["s-b"]]["postcard"] = None
            r = c.post(url, json=three, headers=me)
            check("엽서가 없어도 말씀이 있으면 200", r.status_code == 200, f"{r.status_code} {r.text[:60]}")
            fake.recs[fake.ids["s-b"]] = record(SEED_A["sessions"][1], fake.ids["s-b"])

            fake.writes = 0
            mute = fake.recs[fake.ids["s-b"]]
            kept_frags = mute["fragments"]
            mute["fragments"] = [f for f in kept_frags if f["idx"] == 0]
            r = c.post(url, json=three, headers=me)
            check("말씀이 없는 회차 → 400 · bad_selection", r.status_code == 400 and failed(r, "bad_selection"),
                  f"{r.status_code} {r.text[:60]}")
            mute["fragments"] = kept_frags

            # 한 자서전 = 한 사람. 화자가 섞이면 꺼져 있어도 거절한다.
            a, b = fake.ids["s-a"], fake.ids["s-b"]
            fake.recs[a]["elder_id"], fake.recs[b]["elder_id"] = "e_mom", "e_dad"
            r = c.post(url, json=three, headers=me)
            check("화자가 다르면 → 400 · mixed_speakers", r.status_code == 400 and failed(r, "mixed_speakers"),
                  f"{r.status_code} {r.text[:60]}")
            fake.recs[b]["elder_id"] = None
            r = c.post(url, json=three, headers=me)
            check("화자 있는 회차 + 미지정 회차 → 400 · speaker_unassigned",
                  r.status_code == 400 and failed(r, "speaker_unassigned"), f"{r.status_code} {r.text[:60]}")
            for s in three["session_ids"]:
                fake.recs[s]["elder_id"] = "e_mom"
            r = c.post(url, json=three, headers=me)
            check("모두 같은 화자면 200", r.status_code == 200, f"{r.status_code}")
            for s in three["session_ids"]:
                fake.recs[s]["elder_id"] = None
            r = c.post(url, json=three, headers=me)
            check("모두 미지정이면 지금은 200 (MEMOIR_REQUIRE_SPEAKER 꺼짐)", r.status_code == 200, f"{r.status_code}")
            with _Env(MEMOIR_REQUIRE_SPEAKER="1"):
                r = c.post(url, json=three, headers=me)
                check("MEMOIR_REQUIRE_SPEAKER=1 이면 미지정 → 400 · speaker_unassigned",
                      r.status_code == 400 and failed(r, "speaker_unassigned"), f"{r.status_code}")
            check("화자 거절은 모델을 부르지 않는다 (통과한 2번만 불렀다)", fake.writes == 2, str(fake.writes))

            # 5 는 임시 시험 제한이다 — 설정으로 바뀐다.
            r = c.post(url, json=fake.pick("s-a", "s-b", "s-c", "s-d"), headers=me)
            with _Env(MEMOIR_MAX_SESSIONS="3"):
                r2 = c.post(url, json=fake.pick("s-a", "s-b", "s-c", "s-d"), headers=me)
            check("MEMOIR_MAX_SESSIONS 로 상한이 바뀐다 (4개: 기본 200 · 상한 3 이면 400)",
                  r.status_code == 200 and r2.status_code == 400 and failed(r2, "bad_selection"),
                  f"{r.status_code} {r2.status_code}")
            fake.writes = 0

            fake.out = copy.deepcopy(EMPTY)
            r = c.post(url, json=three, headers=me)
            check("자료 부족은 200 · insufficient_material", r.status_code == 200 and r.json() == shown(EMPTY, three["session_ids"]),
                  f"{r.status_code} {r.text[:60]}")

            for name in ("없는 턴을 가리키는 출처", "sentence 번호가 겹치는 출처"):
                fake.out = copy.deepcopy(BROKEN[name])
                r = c.post(url, json=three, headers=me)
                check(f"{name} → 502 · invalid_model_output", r.status_code == 502 and failed(r, "invalid_model_output"),
                      f"{r.status_code} {r.text[:60]}")
            check("실패 응답에 본문이나 원문이 새지 않는다", "광주" not in r.text)
            for status in ("needs_confirmation", "needs_context"):
                fake.out = _with(EMPTY, status=status)
                r = c.post(url, json=three, headers=me)
                check(f"{status} → 503 · not_final", r.status_code == 503 and failed(r, "not_final"),
                      f"{r.status_code} {r.text[:60]}")
            fake.out = copy.deepcopy(READY)

            fake.db_down = True
            fake.writes = 0
            r = c.post(url, json=three, headers=me)
            check("DB 를 못 읽으면 422 · source_unavailable", r.status_code == 422 and failed(r, "source_unavailable"), f"{r.status_code}")
            check("못 읽었으면 모델을 부르지 않는다", fake.writes == 0)
            fake.db_down = False

            with _Env(MEMOIR_FAIL_INJECT="source_material_unavailable"):
                r = c.post(url, json=three, headers=me)
                check("주입 source_material_unavailable → 422 (S8)",
                      r.status_code == 422 and failed(r, "source_unavailable"), f"{r.status_code}")
                check("S8 — 모델을 부르지 않는다", fake.writes == 0)
                r = c.post(url, json=fake.pick("s-a", "s-b"), headers=me)
                check("S8 — 선택 검사가 주입보다 먼저다 (400)", r.status_code == 400, f"{r.status_code}")
                r = c.post(url, json=three, headers=other)
                check("S8 — 사용자 범위 검사가 주입보다 먼저다 (404)", r.status_code == 404, f"{r.status_code}")

            # S9 는 진짜 write 로 본다. 주입은 모델을 부르기 전에 걸린다.
            memoir.write = fake._saved[1]
            for hook, code, kind in (("generation_failed", 502, "invalid_model_output"),
                                     ("generation_timeout", 504, "generation_timeout")):
                with _Env(MEMOIR_FAIL_INJECT=hook):
                    r = c.post(url, json=three, headers=me)
                    check(f"주입 {hook} → {code} · {kind} (S9)",
                          r.status_code == code and failed(r, kind), f"{r.status_code} {r.text[:60]}")
                    check(f"{hook} — 가짜 본문도 자료 부족도 아니다", "status" not in r.json())

    with _Env(MEMOIR_FAIL_INJECT="nonsense"):
        check("모르는 주입 값은 끈 것으로 읽는다", memoir.inject() == "")


def test_exclude():
    print("\n[빼기] {elder_id, exclude_session_ids} — 화자의 전부에서 뺀다 · 상한 없음 (최충 · 태헌 10-28)")
    from fastapi.testclient import TestClient

    from app.main import app

    url = "/api/memoirs/preview"
    me, other = {"X-User-Id": ME}, {"X-User-Id": OTHER}

    with _Env(AZURE_SPEECH_KEY="", GEMINI_API_KEY="", MEMOIR_FAIL_INJECT="off"), \
            _Fake() as fake, NoDb(), AsHeader():
        for r in fake.recs.values():
            r["elder_id"] = "e_mom"
        ids = fake.ids
        every = sorted(ids.values(), key=lambda s: fake.recs[s]["created_at"])

        def ask(exclude, elder="e_mom", who=me, **kv):
            return c.post(url, json={"elder_id": elder, "exclude_session_ids": exclude, **kv}, headers=who)

        def failed(r, code: str) -> bool:
            body = r.json()
            return set(body) == {"detail", "code"} and body["code"] == code

        with TestClient(app) as c:
            r = ask([])
            check("뺄 것 없음 → 200 · 다섯 회차 전부",
                  r.status_code == 200 and r.json()["run"]["session_ids"] == every
                  and len(fake.seen["sessions"]) == 5, f"{r.status_code} {r.text[:80]}")
            check("응답은 고른 요청과 같은 모양 (다섯 키 + style + run)",
                  set(r.json()) == {*memoir.SHOWN, "style", "run"})
            with _Env(MEMOIR_MAX_SESSIONS="3"):
                r = ask([])
                check("한 번 호출(single) 계정은 빼기 요청에도 MEMOIR_MAX_SESSIONS — 5개 > 3 → 400",
                      r.status_code == 400 and failed(r, "bad_selection"), f"{r.status_code}")

            r = ask([ids["s-b"], ids["s-d"]])
            check("두 개를 빼면 → 200 · run 에 나머지 세 개 (뺀 것은 없다)",
                  r.status_code == 200 and r.json()["run"]["session_ids"] == [ids["s-a"], ids["s-c"], ids["s-e"]]
                  and len(fake.seen["sessions"]) == 3, f"{r.status_code} {r.text[:80]}")
            r = ask([ids["s-b"].upper()], style="spoken")
            check("대문자 UUID 로 빼도 같은 회차다", r.status_code == 200
                  and ids["s-b"] not in r.json()["run"]["session_ids"], f"{r.status_code}")

            # 「전부」 의 기준 — 진행 중 · 말씀 없음 · 다른 화자 · 미지정은 들지 않는다
            fake.recs[ids["s-a"]]["closed_at"] = None
            mute = fake.recs[ids["s-b"]]
            kept = mute["fragments"]
            mute["fragments"] = [f for f in kept if f["idx"] == 0]
            fake.recs[ids["s-c"]]["elder_id"] = None
            r = ask([])
            check("진행 중 · 말씀 없음 · 미지정 회차는 빠진다 → 남은 둘이라 400 · bad_selection",
                  r.status_code == 400 and failed(r, "bad_selection"), f"{r.status_code} {r.text[:80]}")
            fake.recs[ids["s-c"]]["elder_id"] = "e_mom"
            r = ask([ids["s-b"], "00000000-0000-4000-8000-0000000000ff"])
            check("전부에 없는 회차를 빼라고 해도 거절하지 않는다 (말씀 없는 회차 · 없는 회차)",
                  r.status_code == 200 and r.json()["run"]["session_ids"] == [ids["s-c"], ids["s-d"], ids["s-e"]],
                  f"{r.status_code} {r.text[:80]}")
            fake.recs[ids["s-a"]]["closed_at"] = "2026-10-12T10:01:50+00:00"
            mute["fragments"] = kept

            fake.writes = 0
            for name, r, code in (
                ("셋을 빼 두 개만 남으면", ask([ids["s-a"], ids["s-b"], ids["s-c"]]), "bad_selection"),
                ("elder_id 없음", c.post(url, json={"exclude_session_ids": []}, headers=me), "bad_selection"),
                ("elder_id 가 문자열이 아님", ask([], elder=3), "bad_selection"),
                ("exclude 가 목록이 아님", ask(ids["s-a"]), "bad_selection"),
                ("exclude 에 UUID 가 아닌 것", ask(["s-a"]), "bad_selection"),
                ("exclude 중복", ask([ids["s-a"], ids["s-a"]]), "bad_selection"),
            ):
                check(f"{name} → 400 · {code}", r.status_code == 400 and failed(r, code), f"{r.status_code} {r.text[:60]}")
            r = ask([], elder="e_dad")
            check("내 화자가 아니면 → 404 · not_found", r.status_code == 404 and failed(r, "not_found"), f"{r.status_code}")
            r = ask([], who=other)
            check("다른 자녀 → 404 · not_found", r.status_code == 404 and failed(r, "not_found"), f"{r.status_code}")
            fake.db_down = True
            r = ask([])
            check("DB 를 못 읽으면 → 422 · source_unavailable", r.status_code == 422 and failed(r, "source_unavailable"),
                  f"{r.status_code}")
            fake.db_down = False
            r = ask([], style="novel")
            check("문체 거절은 빼기 요청에도 같다 → 400 · unsupported_style",
                  r.status_code == 400 and r.json()["code"] == "unsupported_style", f"{r.status_code}")
            check("거절한 빼기 요청은 모델을 부르지 않는다", fake.writes == 0, str(fake.writes))

            r = c.post(url, json={"session_ids": every[:3]}, headers=me)
            check("exclude_session_ids 칸이 없으면 예전 고르기 그대로 (run 은 고른 것)",
                  r.status_code == 200 and r.json()["run"]["session_ids"] == every[:3], f"{r.status_code}")

            # 목록 — 화자로 거르면 그 화자의 「전부」 수를 함께 준다 (목록은 100개까지라)
            saved = store.list_sessions

            async def list_sessions(*a, **kv):
                return []

            store.list_sessions = list_sessions
            try:
                r1 = c.get("/api/sessions?elder_id=e_mom&limit=100", headers=me)
                r2 = c.get("/api/sessions?limit=100", headers=me)
            finally:
                store.list_sessions = saved
            check("?elder_id= 목록에 memoir_total (화자의 자서전 회차 전부 수)",
                  r1.status_code == 200 and r1.json() == {"sessions": [], "memoir_total": 5, **memoir.limits(ME)}, f"{r1.status_code} {r1.text[:80]}")
            check("화자 없이 부르면 memoir_total 이 없다 (예전 그대로)",
                  r2.status_code == 200 and r2.json() == {"sessions": []}, f"{r2.status_code} {r2.text[:80]}")


def test_pipeline_engine():
    print("\n[다섯 단계] MEMOIR_ENGINE=pipeline — 같은 고르기 · 7-C1 §3 응답 (단위 8S)")
    from fastapi.testclient import TestClient

    from app.main import app
    from app.session import memoir_pipeline as mp

    url = "/api/memoirs/preview"
    me = {"X-User-Id": ME}
    base = json.loads((ROOT / "tests" / "data" / "v5_edit_pro_20261027T024949Z" / "result.json")
                      .read_text(encoding="utf-8"))
    done = {**base, "generation_state": mp.GENERATED, "verification": {"state": "completed"}}

    def failed(r, code: str) -> bool:
        body = r.json()
        return set(body) == {"detail", "code"} and body["code"] == code

    saved_run = mp.run
    calls: list[tuple[dict, list]] = []
    out = {"res": done}

    async def run(data, turn_map, **kv):
        calls.append((data, turn_map))
        return copy.deepcopy(out["res"])

    mp.run = run
    try:
        with _Env(AZURE_SPEECH_KEY="", GEMINI_API_KEY="", MEMOIR_FAIL_INJECT="off", MEMOIR_ENGINE="pipeline",
                  MEMOIR_PIPELINE_USERS=ME), _Fake() as fake, NoDb(), AsHeader(), TestClient(app) as c:
            three = fake.pick("s-a", "s-b", "s-c")
            r = c.post(url, json=three, headers=me)
            body = r.json()
            ch = base["chapters"][0]
            check("200 · status ready · 장 · 문단 · 문장 (7-C1 §3)",
                  r.status_code == 200 and body["status"] == "ready" and body["title"] == base["title"]["text"]
                  and body["chapters"][0]["title"] == ch["title"]["text"]
                  and body["chapters"][0]["paragraphs"][0]["sentences"][0]["text"] == ch["paragraphs"][0][0]["text"],
                  f"{r.status_code} {r.text[:100]}")
            n = sum(len(p) for c_ in base["chapters"] for p in c_["paragraphs"])
            check("body · sources 는 장을 펼친 것 — 문장 수가 같다",
                  len(body["body"].split("\n")) == n == len(body["sources"]), f"{n}")
            check("run — 실제로 쓴 회차 · 장 수", body["run"] == {"session_ids": three["session_ids"],
                                                         "chapters_requested": len(base["chapters"])})
            check("모델 쪽 메모 (facts · kind · diagnosis · 검증 이슈) 는 내보내지 않는다",
                  "facts" not in r.text and "diagnosis" not in body and body["verification"] == {"state": "completed"})
            check("파이프라인 입력은 한 번 호출과 같은 merge (회차 3개 · 말씀 6개)",
                  len(calls[-1][0]["sessions"]) == 3 and len(calls[-1][0]["utterances"]) == 6)
            check("한 번 호출(write)은 부르지 않았다", fake.writes == 0, str(fake.writes))

            for name, res, status, code in (
                ("partial (일부 장 실패)", {**done, "generation_state": mp.PARTIAL, "chapters": [],
                                             "failure": {"stage": "chapter", "kind": "timeout", "chapter_key": "ch-2"}},
                 503, "incomplete"),
                ("failed · timeout", {**done, "generation_state": mp.FAILED, "chapters": [],
                                      "failure": {"stage": "edit", "kind": "timeout"}}, 504, "generation_timeout"),
                ("failed · budget (전체 시간)", {**done, "generation_state": mp.FAILED, "chapters": [],
                                                "failure": {"stage": "verify", "kind": "budget"}}, 504, "generation_timeout"),
                ("failed · format", {**done, "generation_state": mp.FAILED, "chapters": [],
                                     "failure": {"stage": "analysis", "kind": "format"}}, 502, "invalid_model_output"),
                ("needs_context", {**done, "generation_state": mp.NEEDS_CONTEXT, "chapters": [],
                                   "failure": {"stage": "analysis", "kind": "context", "message": "…"}}, 503, "not_final"),
                ("generated 인데 장이 비었다", {**done, "chapters": []}, 502, "invalid_model_output"),
                ("generated 인데 문장 모양이 다르다", {**done, "chapters": [{"title": "문자열", "paragraphs": []}]},
                 502, "invalid_model_output"),
            ):
                out["res"] = res
                r = c.post(url, json=three, headers=me)
                check(f"{name} → {status} · {code}", r.status_code == status and failed(r, code),
                      f"{r.status_code} {r.text[:80]}")
            out["res"] = {**done, "generation_state": mp.INSUFFICIENT, "chapters": [], "title": None}
            r = c.post(url, json=three, headers=me)
            check("자료 부족 → 200 insufficient_material · 빈 장",
                  r.status_code == 200 and r.json()["status"] == "insufficient_material" and r.json()["chapters"] == [],
                  f"{r.status_code} {r.text[:80]}")

            out["res"] = done
            for s in fake.recs.values():
                s["elder_id"] = "e_mom"
            r = c.post(url, json={"elder_id": "e_mom", "exclude_session_ids": [fake.ids["s-e"]]}, headers=me)
            check("빼기 요청도 다섯 단계로 — 네 회차", r.status_code == 200
                  and len(r.json()["run"]["session_ids"]) == 4 and len(calls[-1][0]["sessions"]) == 4,
                  f"{r.status_code} {r.text[:80]}")
            n_calls = len(calls)
            r = c.post(url, json=fake.pick("s-a", "s-b"), headers=me)
            check("잘못 고르면 400 · 파이프라인을 부르지 않는다", r.status_code == 400 and len(calls) == n_calls)
            with _Env(MEMOIR_FAIL_INJECT="generation_timeout"):
                r = c.post(url, json=three, headers=me)
                check("주입 generation_timeout → 504 · 부르지 않는다",
                      r.status_code == 504 and len(calls) == n_calls, f"{r.status_code}")
        with _Env(MEMOIR_ENGINE="single", MEMOIR_PIPELINE_USERS="*"):
            check("MEMOIR_ENGINE 이 pipeline 이 아니면 single", memoir.engine(ME) == "single")
        with _Env(MEMOIR_ENGINE=" Pipeline ", MEMOIR_PIPELINE_USERS="*"):
            check("대소문자 · 공백은 맞춘다", memoir.engine(ME) == "pipeline")
    finally:
        mp.run = saved_run


def test_jobs():
    print("\n[작업] POST /api/memoirs → GET /api/memoirs/{job_id} — 기다리지 않는다 (단위 8S)")
    import threading
    import time as _time

    from fastapi.testclient import TestClient

    from app.main import app
    from app.session import memoir_jobs
    from app.session import memoir_pipeline as mp

    me, other = {"X-User-Id": ME}, {"X-User-Id": OTHER}
    base = json.loads((ROOT / "tests" / "data" / "v5_edit_pro_20261027T024949Z" / "result.json")
                      .read_text(encoding="utf-8"))
    done = {**base, "generation_state": mp.GENERATED, "verification": {"state": "completed"}}
    gate, at_chapter = threading.Event(), threading.Event()
    out = {"res": done}

    async def run(data, turn_map, recorder=None, **kv):
        import asyncio
        recorder.json("01_analysis.json", {})
        recorder.json("02_outline.json", {"chapters": [{}, {}, {}, {}]})
        recorder.json("03_ch-1.json", {})
        at_chapter.set()
        while not gate.is_set():
            await asyncio.sleep(0.01)
        return copy.deepcopy(out["res"])

    def wait(c, job_id, who=me, until=("done", "failed")):
        for _ in range(300):
            r = c.get(f"/api/memoirs/{job_id}", headers=who)
            if r.status_code != 200 or r.json()["status"] in until:
                return r
            _time.sleep(0.01)
        return r

    saved_run = mp.run
    mp.run = run
    try:
        with _Env(AZURE_SPEECH_KEY="", GEMINI_API_KEY="", MEMOIR_FAIL_INJECT="off", MEMOIR_ENGINE="pipeline",
                  MEMOIR_PIPELINE_USERS=ME), _Fake() as fake, NoDb(), AsHeader(), TestClient(app) as c:
            three = fake.pick("s-a", "s-b", "s-c")
            r = c.post("/api/memoirs", json=three, headers=me)
            job = r.json()
            check("시작 → 202 · running · 작업 번호 · 회차", r.status_code == 202 and job["status"] == "running"
                  and len(job["job_id"]) == 32 and job["run"]["session_ids"] == three["session_ids"],
                  f"{r.status_code} {r.text[:80]}")
            at_chapter.wait(2)
            r = c.get(f"/api/memoirs/{job['job_id']}", headers=me)
            check("만드는 중 → stage chapter · 2/4 장 (단계 파일로 읽는다)",
                  r.json()["status"] == "running" and r.json()["stage"] == "chapter"
                  and (r.json()["chapter"], r.json()["chapters"]) == (2, 4), r.text[:120])
            r = c.post("/api/memoirs", json=three, headers=me)
            check("만드는 중에 또 시작 → 409 busy · 그 job_id", r.status_code == 409
                  and r.json()["code"] == "busy" and r.json()["job_id"] == job["job_id"], f"{r.status_code}")
            r = c.get(f"/api/memoirs/{job['job_id']}", headers=other)
            check("남의 작업 → 404 job_not_found", r.status_code == 404 and r.json()["code"] == "job_not_found")
            gate.set()
            r = wait(c, job["job_id"])
            res = r.json()
            check("다 되면 → done · result 는 preview 응답과 같다 (7-C1 §3)",
                  res["status"] == "done" and res["result"]["status"] == "ready"
                  and res["result"]["title"] == base["title"]["text"]
                  and res["result"]["run"]["session_ids"] == three["session_ids"], r.text[:120])
            check("끝난 작업에는 stage 가 없다", "stage" not in res)
            r = c.get("/api/memoirs/" + "0" * 32, headers=me)
            check("없는 작업 → 404 job_not_found", r.status_code == 404 and r.json()["code"] == "job_not_found")

            n = len(memoir_jobs._JOBS)
            r = c.post("/api/memoirs", json=fake.pick("s-a", "s-b"), headers=me)
            check("잘못 고르면 바로 400 bad_selection · 작업을 열지 않는다",
                  r.status_code == 400 and r.json()["code"] == "bad_selection" and len(memoir_jobs._JOBS) == n)
            r = c.post("/api/memoirs", json={**three, "style": "novel"}, headers=me)
            check("문체 거절 → 400 unsupported_style", r.status_code == 400 and r.json()["code"] == "unsupported_style")
            r = c.post("/api/memoirs", json=three, headers=other)
            check("남의 회차 → 404 not_found (바로)", r.status_code == 404 and r.json()["code"] == "not_found")

            out["res"] = {**done, "generation_state": mp.FAILED, "chapters": [],
                          "failure": {"stage": "analysis", "kind": "timeout"}}
            r = c.post("/api/memoirs", json=three, headers=me)
            r = wait(c, r.json()["job_id"])
            check("실패 → failed · code generation_timeout · 안내 문장",
                  r.json()["status"] == "failed" and r.json()["code"] == "generation_timeout"
                  and "요" in r.json()["detail"], r.text[:120])
            out["res"] = {**done, "generation_state": mp.PARTIAL, "chapters": [], "failure": {"kind": "timeout"}}
            r = wait(c, c.post("/api/memoirs", json=three, headers=me).json()["job_id"])
            check("일부 장 실패 → failed · code incomplete", r.json()["code"] == "incomplete", r.text[:80])
            out["res"] = done

            gate.clear()
            at_chapter.clear()
            j = c.post("/api/memoirs", json=three, headers=me).json()["job_id"]
            at_chapter.wait(2)
            r = c.delete(f"/api/memoirs/{j}", headers=me)
            check("그만두기 → failed · cancelled", r.status_code == 200 and r.json()["status"] == "failed"
                  and r.json()["code"] == "cancelled", r.text[:120])
            r = c.post("/api/memoirs", json=three, headers=me)
            check("그만둔 뒤에는 다시 시작할 수 있다 (202)", r.status_code == 202, f"{r.status_code}")
            gate.set()
            wait(c, r.json()["job_id"])

            with _Env(MEMOIR_ENGINE="single"):
                r = c.post("/api/memoirs", json=three, headers=me)
                check("single 엔진도 작업으로 — stage write", r.status_code == 202 and r.json()["stage"] == "write")
                r = wait(c, r.json()["job_id"])
                check("single 결과 — 예전 다섯 키 + style + run",
                      r.json()["status"] == "done" and r.json()["result"] == shown(READY, three["session_ids"]),
                      r.text[:120])

            with _Env(MEMOIR_JOB_KEEP_SECONDS="0"):
                j = c.post("/api/memoirs", json=three, headers=me).json()["job_id"]
                wait(c, j)
                _time.sleep(0.05)        # Windows 시계 한 칸은 약 16ms 다
                r = c.get(f"/api/memoirs/{j}", headers=me)
                check("보관 시간이 지나면 → 404 job_not_found", r.status_code == 404, f"{r.status_code}")
    finally:
        mp.run = saved_run
        memoir_jobs._JOBS.clear()


def test_policy():
    print("\n[정책] 시험 대상만 · 입력량 상한 · 분석 1회 재시도 · 사용량 · 최근 작업 (태헌 10-28)")
    import time as _time

    from fastapi.testclient import TestClient

    from app.main import app
    from app.session import memoir_jobs
    from app.session import memoir_pipeline as mp

    url = "/api/memoirs/preview"
    me, other = {"X-User-Id": ME}, {"X-User-Id": OTHER}
    base = json.loads((ROOT / "tests" / "data" / "v5_edit_pro_20261027T024949Z" / "result.json")
                      .read_text(encoding="utf-8"))
    done = {**base, "generation_state": mp.GENERATED, "verification": {"state": "completed"}}

    def failed_at(kind: str) -> dict:
        return {**done, "generation_state": mp.FAILED, "chapters": [], "calls": 1,
                "failure": {"stage": "analysis", "kind": kind, "message": "…"}}

    queue: list[dict] = []
    calls: list[int] = []

    async def run(data, turn_map, recorder=None, **kv):
        calls.append(1)
        recorder.json("run.json", {"steps": [{"stage": "analysis", "chapter_key": None, "ms": 10,
                                              "usage": {"prompt": 1000, "output": 100, "thoughts": 400}}]})
        return copy.deepcopy(queue.pop(0) if queue else done)

    def wait(c, job_id):
        for _ in range(300):
            r = c.get(f"/api/memoirs/{job_id}", headers=me)
            if r.status_code != 200 or r.json()["status"] != "running":
                return r
            _time.sleep(0.01)
        return r

    saved_run = mp.run
    mp.run = run
    try:
        with _Env(AZURE_SPEECH_KEY="", GEMINI_API_KEY="", MEMOIR_FAIL_INJECT="off", MEMOIR_ENGINE="pipeline",
                  MEMOIR_PIPELINE_USERS=f" {OTHER} , {ME} "), _Fake() as fake, NoDb(), AsHeader(), \
                TestClient(app) as c:
            three = fake.pick("s-a", "s-b", "s-c")

            # A — 시험 대상만
            check("목록에 든 계정은 pipeline (쉼표 · 공백 정리)", memoir.engine(ME) == "pipeline")
            with _Env(MEMOIR_PIPELINE_USERS=OTHER):
                check("목록에 없으면 single", memoir.engine(ME) == "single")
                n = len(calls)
                r = c.post(url, json=three, headers=me)
                check("목록에 없는 계정은 한 번 호출로 쓴다 (파이프라인을 부르지 않는다)",
                      r.status_code == 200 and len(calls) == n and fake.writes >= 1, f"{r.status_code}")
                check("limits — single 이면 memoir_max 가 MEMOIR_MAX_SESSIONS",
                      memoir.limits(ME)["memoir_engine"] == "single" and memoir.limits(ME)["memoir_max"] == 5)
            with _Env(MEMOIR_PIPELINE_USERS=""):
                check("목록이 비면 아무도 pipeline 을 쓰지 않는다", memoir.engine(ME) == "single")
            with _Env(MEMOIR_PIPELINE_USERS="*"):
                check("* 이면 모두", memoir.engine("anyone") == "pipeline")
            check("limits — pipeline 이면 memoir_max 없음 (None)",
                  memoir.limits(ME) == {"memoir_engine": "pipeline", "memoir_max": None,
                                        "memoir_max_chars": memoir.DEFAULT_MAX_INPUT_CHARS})

            # B — 입력량 상한: 빼지 않고 안내
            with _Env(MEMOIR_MAX_INPUT_CHARS="20"):
                n, jobs = len(calls), len(memoir_jobs._JOBS)
                r = c.post(url, json=three, headers=me)
                body = r.json()
                check("말씀이 상한을 넘으면 400 too_much · 무엇을 할지 안내",
                      r.status_code == 400 and body["code"] == "too_much" and "빼 주세요" in body["detail"],
                      f"{r.status_code} {r.text[:80]}")
                r = c.post("/api/memoirs", json=three, headers=me)
                check("작업 시작도 바로 400 too_much · 작업을 열지 않는다",
                      r.status_code == 400 and r.json()["code"] == "too_much" and len(memoir_jobs._JOBS) == jobs)
                check("상한을 넘으면 모델을 부르지 않는다", len(calls) == n)

            # C — 분석 1회 재시도
            for kind in ("format", "call"):
                calls.clear()
                queue[:] = [failed_at(kind), done]
                r = c.post(url, json=three, headers=me)
                check(f"분석 {kind} 실패 → 한 번 더 불러 200", r.status_code == 200 and len(calls) == 2,
                      f"{r.status_code} 호출 {len(calls)}")
            calls.clear()
            queue[:] = [failed_at("format"), failed_at("format"), done]
            r = c.post(url, json=three, headers=me)
            check("같은 문제가 또 나면 멈춘다 (2번까지) → 502", r.status_code == 502 and len(calls) == 2,
                  f"{r.status_code} 호출 {len(calls)}")
            queue.clear()
            for kind, status in (("reference", 502), ("timeout", 504), ("truncated", 502)):
                calls.clear()
                queue[:] = [failed_at(kind), done]
                r = c.post(url, json=three, headers=me)
                check(f"분석 {kind} 실패는 다시 부르지 않는다 → {status}", r.status_code == status and len(calls) == 1,
                      f"{r.status_code} 호출 {len(calls)}")
            queue.clear()
            calls.clear()
            queue[:] = [{**done, "generation_state": mp.PARTIAL, "chapters": [],
                         "failure": {"stage": "chapter", "kind": "format", "chapter_key": "ch-1"}}, done]
            r = c.post(url, json=three, headers=me)
            check("분석이 아닌 단계의 실패는 다시 부르지 않는다 (처음부터 다시 돌지 않는다)",
                  r.status_code == 503 and len(calls) == 1, f"{r.status_code} 호출 {len(calls)}")
            queue.clear()

            # 최근 작업
            r = c.get("/api/memoirs/latest", headers=me)
            check("작업이 없으면 latest → 404 job_not_found", r.status_code == 404
                  and r.json()["code"] == "job_not_found")
            j = c.post("/api/memoirs", json=three, headers=me).json()["job_id"]
            wait(c, j)
            r = c.get("/api/memoirs/latest", headers=me)
            check("latest → 내 가장 최근 작업 (GET {job_id} 와 같은 본문)",
                  r.status_code == 200 and r.json()["job_id"] == j and r.json()["status"] == "done", r.text[:80])
            r = c.get("/api/memoirs/latest", headers=other)
            check("다른 계정의 latest 에는 보이지 않는다", r.status_code == 404)

        # D — 사용량 · 비용
        steps = [{"usage": {"prompt": 42785, "output": 6522, "thoughts": 16387}},
                 {"usage": {"prompt": 210000, "output": 1000, "thoughts": 0}}, {"usage": None}]
        u = memoir.usage("gemini-3.1-pro-preview", steps)
        want = 42785 * 2 / 1e6 + (6522 + 16387) * 12 / 1e6 + 210000 * 4 / 1e6 + 1000 * 18 / 1e6
        check("사용량 — 토큰 합 · 20만 넘는 요청은 높은 단가",
              (u["input"], u["output"], u["thoughts"]) == (252785, 7522, 16387) and abs(u["usd"] - want) < 1e-9,
              f"{u}")
        check("단가를 모르는 모델은 비용을 적지 않는다", memoir.usage("gemini-x", steps)["usd"] is None)
    finally:
        mp.run = saved_run
        memoir_jobs._JOBS.clear()


def test_all_checks_passed():
    """pytest 안전판 — test_flow.py 의 같은 함수 주석 참조."""
    assert not FAIL, "실패: " + ", ".join(FAIL)


def main() -> int:
    print("기억의 조각 — 자서전 검증")
    test_seed()
    test_merge()
    test_check()
    test_routes()
    test_exclude()
    test_pipeline_engine()
    test_jobs()
    test_policy()
    print(f"\n{'=' * 52}\n통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("실패:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
