"""
삽화 그림체 — 수채화 watercolor · 애니풍 anime · 유화 oil_painting (2026-11-25. 연필담채화 pencil_wash 는 견본을 본 뒤 뺐다). 합성 자료 · 가짜 호출로만

    python -m pytest tests/test_memoir_illust_art_style.py -q

유료 모델 · 이미지 API 를 부르지 않는다. 그래서 **그림이 실제로 그 그림체로 보이는지는 이 시험이 확인하지 않는다.**
화면이 보낸 값이 API → 작업 → 삽화 처리 → 그림 지시문 → 책 · 장 기록까지 그대로 가는지, 같은 계획에서 그림체 블록만
다른지, 다른 그림체의 지시가 섞이지 않는지, 앞선 책 · 다시 처리가 그대로인지를 본다.

    A1 고르지 않으면 수채화
    A2 세 값이 API → 작업 → keep → schedule → run → 책 · 장 기록 · 화면 응답까지 (문체 style 은 그대로)
    A3 같은 주제 · 같은 계획에서 그림체별 지시문이 다르고, 주제 · 그릴 것 블록과 공통 양식은 같다
    A4 애니풍 · 유화 지시문에 수채화 전용 지시가 없다 (「수채」 낱말도 없다) · 애니풍은 특정 작품 · 제작사를 가리키지 않는다
    A5 한 책의 모든 AI 삽화가 같은 그림체
    A6 사진 있는 장은 그림체와 상관없이 부르지 않는다
    A7 앞선 책(그림체 칸 없음)은 수채화 · 저장된 그림은 다시 그리지 않는다 · 이어서 · 다시 처리해도 책에 적힌 그림체
    A8 모르는 값은 거절 — API 400 · 지시문에 넣지 않는다 · 장면 방식은 수채화만
    A9 계획 지시문(v8)은 그림체를 모른다 — 그림체가 달라도 선정 호출이 같다. v7 과는 재료 문구만 다르다
    B1 연필담채화는 새 책에서 고를 수 없지만(400) 저장된 책의 그림체로는 안다
    B2 연필담채화로 저장된 책 — 조회 · 그림 주소 · 저장된 그림 다시 쓰기가 그대로다. 애니풍으로 이름을 바꾸지 않고 다시 그리지 않는다
    B3 연필담채화 책의 남은 장은 연필담채화로 이어서 그린다 (애니풍으로 바뀌지 않는다)
    C1 화면의 선택지(원본 · 묶은 파일 · 예시 모드)와 서버의 선택 목록이 같다
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_illust as il, memoir_illust_book as book, memoir_illust_service as svc   # noqa: E402
from app.session import memoir_illust_theme as th, store                                               # noqa: E402
from tests._auth import AsHeader                                                                       # noqa: E402
from tests._nodb import NoDb                                                                           # noqa: E402
from tests.test_memoir_illust_photos import ME, MID, P1, Calls, world                                  # noqa: E402

ARTS = list(th.ART_STYLES)
SEED_D = json.loads((ROOT / "eval" / "illust_theme_seed_D.json").read_text(encoding="utf-8"))
MOCK_D = json.loads((ROOT / "eval" / "illust_theme_mock_D.json").read_text(encoding="utf-8"))["D"]
# 앞선 그림 양식 v2 의 수채화 문구 — 수채화에만 있어야 한다
WATERCOLOR_ONLY = ("수채화 일러스트", "수채 질감", "물이 번진 부드러운", "종이결이 보인다", "가장자리가 옅게 풀린다")


def run_art(calls, art=None):
    return asyncio.run(svc.run(MID, ME, select_call=calls.select_call, image_call=calls.image_call, art_style=art))


def same_plan_prompts(chapter: str = "3") -> dict:
    """같은 장 · 같은 모델 계획(모의)으로 세 그림체의 선정 결과를 낸다 — 부르지 않는다."""
    reply = json.dumps(MOCK_D[chapter], ensure_ascii=False)
    return {a: th.choose_theme(SEED_D, int(chapter), reply, a) for a in ARTS}


class RecordingCalls(Calls):
    """선정에 보낸 system · user 를 남긴다."""

    def __init__(self):
        super().__init__()
        self.sent = []

    def select_call(self, system, user, *, model):
        self.sent.append((system, user))
        return super().select_call(system, user, model=model)


# ---------------------------------------------------------------- A1 · A2 · A5 · A6 서비스

def test_A1_not_choosing_gives_watercolor(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (2, None), "B": (2, None)}, [[[1]], [[3]]])
    calls = Calls()
    doc = run_art(calls)                                       # 그림체를 넘기지 않는다
    assert th.pick_art_style(None) == "watercolor" and svc.new_doc()["art_style"] == "watercolor"
    assert doc["art_style"] == "watercolor" and doc["settings"]["art_style"] == "watercolor"
    assert len(calls.image) == 2 and all(th.art_style_blocks("watercolor")["medium"] in p for p in calls.image)
    assert {c["image"]["art_style"] for c in doc["chapters"].values()} == {"watercolor"}
    assert svc.view(MID, db.row["illustrations"])["art_style"] == {"id": "watercolor", "label": "수채화"}


@pytest.mark.parametrize("art", ARTS)
def test_A2_A5_the_book_and_every_chapter_record_and_use_the_chosen_style(monkeypatch, tmp_path, art):
    db = world(monkeypatch, tmp_path, {"A": (2, None), "B": (2, None), "C": (2, None)}, [[[1]], [[3]], [[5]]])
    calls = Calls()
    doc = run_art(calls, art)
    h = th.art_style_hash(art)
    assert db.row["illustrations"]["art_style"] == art == doc["art_style"]                        # 책 기록 (DB)
    assert doc["settings"]["art_style"] == art and doc["settings"]["art_style_hash"] == h
    for ch in doc["chapters"].values():                                                          # 장 기록
        assert ch["state"] == svc.ILLUSTRATED
        assert ch["select"]["art_style"] == art and ch["select"]["art_style_hash"] == h
        assert ch["select"]["selection"]["prompt"]["art_style"] == art
        assert ch["image"]["art_style"] == art and ch["image"]["style_id"] == f"{art}-recall-v3"
    # A5 — 세 장의 그림 지시문이 모두 그 그림체 하나 (다른 그림체 블록이 없다)
    assert len(calls.image) == 3 and all(th.art_style_blocks(art)["medium"] in p for p in calls.image)
    assert not any(th.art_style_blocks(o)["medium"] in p for p in calls.image for o in ARTS if o != art)
    v = svc.view(MID, db.row["illustrations"])                                                   # 화면 응답
    assert v["art_style"] == {"id": art, "label": th.ART_STYLES[art]["label"]}
    assert all(c["art_style"] == art and all(f["art_style"] == art for f in c["figures"]) for c in v["chapters"])


def test_A6_a_photo_chapter_is_not_drawn_whatever_the_style(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (2, P1), "B": (2, None)}, [[[1, 2]], [[3, 4]]])
    calls = Calls()
    doc = run_art(calls, "oil_painting")
    assert calls.select == [2] and len(calls.image) == 1                     # 1장(사진)은 부르지 않았다
    one, two = doc["chapters"]["1"], doc["chapters"]["2"]
    assert one["state"] == svc.PHOTO and "select" not in one and "image" not in one
    assert two["state"] == svc.ILLUSTRATED and two["image"]["art_style"] == "oil_painting"
    v = {c["no"]: c for c in svc.view(MID, db.row["illustrations"])["chapters"]}
    assert [f["kind"] for f in v[1]["figures"]] == ["photo"] and v[1]["art_style"] is None
    assert [f["kind"] for f in v[2]["figures"]] == ["illustration"] and v[2]["art_style"] == "oil_painting"


# ---------------------------------------------------------------- A2 API → 작업 → keep → schedule

def _route_world(monkeypatch, scheduled: list, saved: list):
    from app.session import memoir

    async def select(body, who):
        return ["s1", "s2", "s3"]

    async def collect(ids, who):
        return [{"session_id": s} for s in ids]

    async def generate(recs, ids, user_id, style, progress=None):
        return {"status": "ready", "style": style, "title": "합성 책", "run": {"session_ids": ids}, "chapters": []}

    async def save_memoir(rec):
        saved.append(rec)

    for name, f in dict(check_open=lambda who: None, select=select, collect=collect, generate=generate).items():
        monkeypatch.setattr(memoir, name, f)
    monkeypatch.setattr(store, "enabled", lambda: True)
    monkeypatch.setattr(store, "save_memoir", save_memoir)
    monkeypatch.setattr(svc, "schedule", lambda mid, uid, art=None: scheduled.append((mid, uid, art)))


@pytest.mark.parametrize("art", [None, *ARTS])
def test_A2_the_api_job_keep_and_schedule_carry_the_choice(monkeypatch, art):
    from fastapi.testclient import TestClient
    from app.main import app
    scheduled, saved = [], []
    want = art or "watercolor"
    body = {"session_ids": ["s1", "s2", "s3"], "style": "essay"} | ({} if art is None else {"illust_style": art})
    with NoDb(), AsHeader(), TestClient(app) as c:
        _route_world(monkeypatch, scheduled, saved)
        r = c.post("/api/memoirs", json=body, headers={"X-User-Id": ME})
        assert r.status_code == 202, r.text
        assert r.json()["illust_style"] == want and r.json()["style"] == "essay"          # 문체는 따로 · 그대로
        job = r.json()
        for _ in range(300):
            job = c.get(f"/api/memoirs/{job['job_id']}", headers={"X-User-Id": ME}).json()
            if job["status"] != "running":
                break
            time.sleep(0.01)
    assert job["status"] == "done" and job["illust_style"] == want and job["style"] == "essay"
    assert len(saved) == 1 and saved[0]["style"] == "essay" and "illust_style" not in saved[0]["result"]   # 원고 · 문체를 덮지 않는다
    assert scheduled == [(saved[0]["memoir_id"], ME, want)]


def test_A2_preview_route_also_carries_the_choice(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.session import memoir
    scheduled, saved = [], []

    async def preview(ids, who, style):
        return {"status": "ready", "style": style, "title": "합성 책", "run": {"session_ids": ids}, "chapters": []}
    with NoDb(), AsHeader(), TestClient(app) as c:
        _route_world(monkeypatch, scheduled, saved)
        monkeypatch.setattr(memoir, "preview", preview)
        r = c.post("/api/memoirs/preview", json={"session_ids": ["s1", "s2", "s3"], "style": "literary",
                                                 "illust_style": "anime"}, headers={"X-User-Id": ME})
    assert r.status_code == 200 and r.json()["style"] == "literary"
    assert "illust_style" not in r.json()                      # preview 응답 모양은 그대로 (test_memoir 의 계약)
    assert scheduled == [(saved[0]["memoir_id"], ME, "anime")]


# ---------------------------------------------------------------- A3 · A4 지시문

def test_A3_same_plan_gives_three_prompts_that_differ_only_in_the_style_blocks():
    sels = same_plan_prompts()
    assert all(s["status"] == "selected" for s in sels.values())
    prompts = {a: s["prompt"] for a, s in sels.items()}
    assert len({p["text"] for p in prompts.values()}) == 3                          # 그림체마다 다르다
    assert len({p["scene_block"] for p in prompts.values()}) == 1                   # 주제 · 그릴 것은 같다
    assert len({json.dumps(s["scene"], ensure_ascii=False) for s in sels.values()}) == 1   # 고른 주제 · 소재도 같다
    common = th.style_blocks()
    stripped = set()
    for a, p in prompts.items():
        blocks = th.art_style_blocks(a)
        t = p["text"]
        assert p["art_style"] == a and p["style_id"] == f"{a}-recall-v3" and len(t) <= il.PROMPT_MAX
        assert p["art_style_hash"] == th.art_style_hash(a) and p["art_style_file"] == th.ART_STYLES[a]["file"]
        # 순서 — 공통 양식 → 그림체 → 주제 · 그릴 것 → 인물 → 넣지 않는 것 → 이 그림체에서 피할 것
        order = [common["style"], blocks["medium"], p["scene_block"], common["people"], common["negative"], blocks["avoid"]]
        assert [t.index(x) for x in order] == sorted(t.index(x) for x in order)
        assert not any(th.art_style_blocks(o)["medium"] in t for o in ARTS if o != a)
        stripped.add(t.replace(blocks["medium"], "").replace(blocks["avoid"], ""))
    assert len(stripped) == 1                                                       # 그림체 두 블록을 빼면 글자까지 같다


def test_A4_anime_and_oil_carry_no_watercolor_only_wording():
    texts = {a: s["prompt"]["text"] for a, s in same_plan_prompts().items()}
    assert all(w in texts["watercolor"] for w in ("따뜻한 회상 수채화 일러스트", "종이결이 보인다", "가장자리가 옅게 풀린다"))
    for a in ("anime", "oil_painting"):
        assert not any(w in texts[a] for w in WATERCOLOR_ONLY), a
        assert "수채" not in texts[a], a
    assert "붓 자국과 겹겹이 쌓인 물감" in texts["oil_painting"]
    anime = texts["anime"]                                       # 특정 작품 · 캐릭터 · 제작사를 가리키지 않는다
    assert "애니메이션 영화의 배경 그림 같은 일러스트" in anime and "만화 캐릭터로 그리지 않는다" in anime
    assert "특정 제작사의 그림을 흉내 내지 않는다" in anime
    assert not any(w in anime for w in ("지브리", "Ghibli", "신카이", "디즈니", "Disney", "픽사", "Pixar"))
    assert set(th.ART_STYLES) == {"watercolor", "anime", "oil_painting"}        # 연필담채화는 뺐다
    # 공통 양식 · 기본 구도에는 재료 표현이 없다 (v2 의 「옅게 풀어 준다」 는 수채화 그림체로 옮겼다)
    common = "\n".join(th.style_blocks().values())
    assert not any(w in common for w in ("수채", "연필", "유화", "애니", "번진", "종이결", "옅게 풀"))
    assert not any(w in th.DEFAULT_COMPOSITION for w in ("수채", "번지", "옅게 풀"))
    # 인물 표현 · 넣지 않는 것은 앞선 그림 양식 v2 와 글자까지 같다
    v2 = il._blocks(il.PROMPTS / "2_그림양식_v2.md")
    assert th.style_blocks()["people"] == v2["2"] and th.style_blocks()["negative"] == v2["3"]


# ---------------------------------------------------------------- A7 앞선 책 · 이어서 · 다시 처리

def _strip_art_style(row: dict) -> None:
    """그림체를 고르기 전의 기록처럼 — 책 · 장의 그림체 칸을 없앤다."""
    doc = row["illustrations"]
    doc.pop("art_style", None)
    for k in ("art_style", "art_style_file", "art_style_hash"):
        doc["settings"].pop(k, None)
    for ch in doc["chapters"].values():
        for rec in (ch.get("select") or {}, ch.get("image") or {}):
            rec.pop("art_style", None)
            rec.pop("art_style_hash", None)


def test_A7_an_old_book_without_a_style_is_watercolor_and_keeps_its_images(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (2, None), "B": (2, None)}, [[[1]], [[3]]])
    run_art(Calls())
    _strip_art_style(db.row)
    keys = {k: c["image"]["storage_key"] for k, c in db.row["illustrations"]["chapters"].items()}
    assert svc.view(MID, db.row["illustrations"])["art_style"] == {"id": "watercolor", "label": "수채화"}   # 다시 돌리기 전에도
    calls = Calls()
    doc = run_art(calls, "oil_painting")                       # 앞선 책에 다른 값이 와도 — 기록이 정한다
    assert calls.select == [] and calls.image == []            # 저장된 그림을 다시 쓴다 (유료 호출 0)
    assert doc["art_style"] == "watercolor" and "고르기 전" in doc["art_style_note"]
    assert {k: c["image"]["storage_key"] for k, c in doc["chapters"].items()} == keys
    v = svc.view(MID, db.row["illustrations"])
    assert v["art_style"]["id"] == "watercolor" and {c["art_style"] for c in v["chapters"]} == {"watercolor"}


def test_A7_resuming_a_book_uses_the_style_written_in_the_book(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (2, None), "B": (2, None)}, [[[1]], [[3]]])
    run_art(Calls(), "anime")
    doc = db.row["illustrations"]                              # 2장을 부르기 전에 멈춘 책처럼
    doc["status"] = svc.RUNNING
    doc["chapters"]["2"] = {"no": 2, "title": "2장", "state": svc.PENDING}
    calls = Calls()
    out = run_art(calls, "oil_painting")                       # 다른 값이 와도 책의 그림체로 이어서
    assert calls.select == [2] and len(calls.image) == 1       # 1장 그림은 다시 그리지 않는다
    assert th.art_style_blocks("anime")["medium"] in calls.image[0]
    assert out["art_style"] == "anime" and out["chapters"]["2"]["image"]["art_style"] == "anime"


def test_A7_reprocessing_a_failed_chapter_uses_the_books_style(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (2, None), "B": (2, None)}, [[[1]], [[3]]])
    run_art(Calls(), "oil_painting")
    ch = db.row["illustrations"]["chapters"]["2"]              # 2장이 앞선 판에서 실패한 책처럼
    ch.update(state=svc.FAILED, failure=["image_refused"])
    ch["select"]["policy_id"] = "chapter_theme_v1"
    ch.pop("image")
    done = asyncio.run(svc.prepare_reprocess(MID, ME, "theme", [2]))
    assert done["changed"] and [t["no"] for t in done["targets"]] == [2]
    calls = Calls()
    out = run_art(calls)
    assert calls.select == [2] and len(calls.image) == 1
    assert th.art_style_blocks("oil_painting")["medium"] in calls.image[0]
    assert out["chapters"]["2"]["image"]["art_style"] == "oil_painting" and out["chapters"]["1"]["state"] == svc.ILLUSTRATED


# ---------------------------------------------------------------- A8 모르는 값

@pytest.mark.parametrize("bad", ["", "Watercolor", "crayon", "pencil_wash", 3, ["oil_painting"], {"id": "watercolor"}])
def test_A8_the_api_refuses_unknown_styles_without_opening_a_job(monkeypatch, bad):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.session import memoir_jobs
    scheduled, saved = [], []
    with NoDb(), AsHeader(), TestClient(app) as c:
        _route_world(monkeypatch, scheduled, saved)
        n = len(memoir_jobs._JOBS)
        r = c.post("/api/memoirs", json={"session_ids": ["s1", "s2", "s3"], "illust_style": bad}, headers={"X-User-Id": ME})
        p = c.post("/api/memoirs/preview", json={"session_ids": ["s1", "s2", "s3"], "illust_style": bad},
                   headers={"X-User-Id": ME})
    for res in (r, p):
        assert res.status_code == 400 and res.json() == {"detail": th.ART_STYLE_SAYS, "code": "unsupported_illust_style"}
    assert len(memoir_jobs._JOBS) == n and saved == [] and scheduled == []


def test_A8_unknown_styles_never_reach_a_prompt():
    for bad in ("", "Watercolor", "crayon", "pencil_wash", 3, ["watercolor"]):
        with pytest.raises(th.UnsupportedArtStyle):
            th.pick_art_style(bad)
    assert th.stored_art_style(None) == th.stored_art_style("") == "watercolor"
    reply = json.dumps(MOCK_D["3"], ensure_ascii=False)
    sel = th.choose_theme(SEED_D, 3, reply, "crayon; 사진처럼")
    assert sel["status"] == "failed" and sel["reasons"] == ["art_style"] and "prompt" not in sel
    assert book.choose_by("theme", SEED_D, 3, reply, "crayon")["status"] == "failed"
    with pytest.raises(il.IllustError):
        book.choose_by("scene", SEED_D, 3, reply, "oil_painting")      # 장면 방식은 수채화만


def test_A8_a_stored_unknown_style_stops_the_book_without_calls(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (2, None)}, [[[1]]])
    db.row["illustrations"] = svc.new_doc() | {"art_style": "crayon"}
    calls = Calls()
    doc = run_art(calls)
    assert doc["status"] == svc.BROKEN and doc["error"] == "art_style_unsupported" and calls.select == calls.image == []


def test_A8_the_scene_policy_draws_watercolor_only(monkeypatch, tmp_path):
    world(monkeypatch, tmp_path, {"A": (2, None)}, [[[1]]])
    monkeypatch.setenv("MEMOIR_ILLUST_POLICY", "scene")
    calls = Calls()
    doc = run_art(calls, "anime")
    assert calls.select == [] and calls.image == []            # 부르기 전에 멈춘다
    assert doc["chapters"]["1"]["state"] == svc.FAILED and doc["chapters"]["1"]["failure"] == ["art_style_not_in_policy"]
    assert book.policy_files("scene", "anime")["art_style"] == "watercolor"


# ---------------------------------------------------------------- A9 계획 지시문은 그림체를 모른다

def test_A9_the_selection_call_is_the_same_whatever_the_style(monkeypatch, tmp_path):
    sent = {}
    for art in ARTS:
        world(monkeypatch, tmp_path / art, {"A": (2, None), "B": (2, None)}, [[[1]], [[3]]])
        calls = RecordingCalls()
        run_art(calls, art)
        sent[art] = calls.sent
    assert sent["watercolor"] == sent["anime"] == sent["oil_painting"] and len(sent["watercolor"]) == 2
    system = sent["watercolor"][0][0]                          # v8 은 재료를 정하지 않는다 (적지 말라는 줄만 있다)
    assert "수채화 한 장" not in system and "그림 재료와 붓질(그림체)은 따로 정해진다" in system


def test_A9_v8_differs_from_v7_only_in_the_material_wording():
    v7 = il._blocks(il.PROMPTS / "1_목차주제_v7.md")["1"]
    v8 = th.select_prompt()
    assert book.policy_files("theme")["select_prompt"] == "1_목차주제_v8.md" and book.POLICY_IDS["theme"] == "chapter_theme_v2"
    want = v7.replace("따뜻한 회상 수채화 한 장이다.", "따뜻한 회상 삽화 한 장이다. 그림 재료와 붓질(그림체)은 따로 정해진다.").replace(
        "- 글자 · 간판 · 숫자는 그림에 넣지 않는다.\n",
        "- 글자 · 간판 · 숫자는 그림에 넣지 않는다.\n"
        "- composition 과 subjects 에 그림 재료 · 화풍 · 붓질(수채 · 연필 · 유화 · 번짐 같은 것)을 적지 않는다. 그림체는 따로 정해진다.\n")
    assert v8 == want


# ---------------------------------------------------------------- B 선택지에서 뺀 그림체(연필담채화)로 이미 만든 책

def _as_pencil_book(row: dict) -> None:
    """연필담채화가 선택지에 있던 때(2026-11-25) 만든 책의 기록처럼 — 책 · 장의 그림체 칸이 pencil_wash 다."""
    doc = row["illustrations"]
    h = th.art_style_hash("pencil_wash")
    doc["art_style"] = "pencil_wash"
    doc["settings"].update(art_style="pencil_wash", art_style_file="2_그림체_연필담채화_v1.md", art_style_hash=h)
    for ch in doc["chapters"].values():
        if ch.get("select"):
            ch["select"].update(art_style="pencil_wash", art_style_hash=h)
            ch["select"]["selection"]["prompt"].update(art_style="pencil_wash", style_id="pencil_wash-recall-v3")
        if ch.get("image"):
            ch["image"].update(art_style="pencil_wash", style_id="pencil_wash-recall-v3")


def test_B1_pencil_wash_is_not_selectable_for_new_books_but_is_still_known():
    assert list(th.ART_STYLES) == ["watercolor", "anime", "oil_painting"] and list(th.RETIRED_ART_STYLES) == ["pencil_wash"]
    with pytest.raises(th.UnsupportedArtStyle):
        th.pick_art_style("pencil_wash")                       # 새 책 — 화면 · API
    with pytest.raises(th.UnsupportedArtStyle):
        svc.new_doc("pencil_wash")
    assert th.stored_art_style("pencil_wash") == "pencil_wash"  # 저장된 책
    assert th.art_style_info("pencil_wash")["selectable"] is False and th.art_style_info("anime")["selectable"] is True
    assert (il.PROMPTS / "2_그림체_연필담채화_v1.md").is_file()   # 그 책의 근거 · 이어서 그릴 때 쓰는 파일
    with pytest.raises(th.UnsupportedArtStyle):
        th.stored_art_style("crayon")                          # 어느 목록에도 없는 값은 저장돼 있어도 모른다


def test_B2_a_stored_pencil_wash_book_still_shows_and_reuses_its_images(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (2, P1), "B": (2, None), "C": (2, None)}, [[[1, 2]], [[3, 4]], [[5, 6]]])
    run_art(Calls())
    _as_pencil_book(db.row)
    before = json.loads(json.dumps(db.row["illustrations"]))
    v = svc.view(MID, db.row["illustrations"])
    assert v["art_style"] == {"id": "pencil_wash", "label": "연필담채화"}       # 애니풍으로 이름을 바꾸지 않는다
    by = {c["no"]: c for c in v["chapters"]}
    assert [f["kind"] for f in by[1]["figures"]] == ["photo"]                   # 사진 장은 그대로 사진
    assert by[2]["art_style"] == by[3]["art_style"] == "pencil_wash" and by[2]["figures"][0]["kind"] == "illustration"
    calls = Calls()
    doc = run_art(calls, "anime")                               # 다시 돌려도 (다른 값이 와도)
    assert calls.select == [] and calls.image == []             # 다시 그리지 않는다 — 저장된 그림을 그대로 쓴다
    assert doc["art_style"] == "pencil_wash" and doc["status"] == svc.COMPLETE
    for k in ("2", "3"):
        assert doc["chapters"][k]["image"] == before["chapters"][k]["image"] and doc["chapters"][k]["state"] == svc.ILLUSTRATED
    assert svc.view(MID, db.row["illustrations"])["chapters"] == v["chapters"]   # 그림 주소도 그대로


def test_B2_routes_still_serve_a_stored_pencil_wash_book(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    db = world(monkeypatch, tmp_path, {"A": (2, None), "B": (2, None)}, [[[1]], [[3]]])
    run_art(Calls())
    _as_pencil_book(db.row)
    with NoDb(), AsHeader(), TestClient(app) as c:
        r = c.get(f"/api/memoirs/saved/{MID}/illustrations", headers={"X-User-Id": ME})
        assert r.status_code == 200 and r.json()["art_style"] == {"id": "pencil_wash", "label": "연필담채화"}
        assert r.json()["status"] == "done" and len(r.json()["chapters"]) == 2
        img = c.get(r.json()["chapters"][0]["figures"][0]["url"], headers={"X-User-Id": ME})
        assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
        full = c.get(f"/api/memoirs/saved/{MID}", headers={"X-User-Id": ME})
        assert full.status_code == 200 and full.json()["illustrations"]["art_style"]["id"] == "pencil_wash"


def test_B3_a_stored_pencil_wash_book_continues_in_pencil_wash_not_anime(monkeypatch, tmp_path):
    db = world(monkeypatch, tmp_path, {"A": (2, None), "B": (2, None)}, [[[1]], [[3]]])
    run_art(Calls())
    _as_pencil_book(db.row)
    doc = db.row["illustrations"]                              # 2장을 부르기 전에 멈춘 책처럼
    doc["status"] = svc.RUNNING
    doc["chapters"]["2"] = {"no": 2, "title": "2장", "state": svc.PENDING}
    calls = Calls()
    out = run_art(calls, "anime")
    assert calls.select == [2] and len(calls.image) == 1        # 1장 그림은 다시 그리지 않는다
    assert th.art_style_blocks("pencil_wash")["medium"] in calls.image[0]
    assert th.art_style_blocks("anime")["medium"] not in calls.image[0]
    assert out["art_style"] == "pencil_wash" and out["chapters"]["2"]["image"]["art_style"] == "pencil_wash"
    assert out["chapters"]["2"]["image"]["style_id"] == "pencil_wash-recall-v3"


# ---------------------------------------------------------------- C 화면과 서버의 선택지

PROTO = ROOT.parent / "prototype"


@pytest.mark.skipif(not (PROTO / "app" / "illust-style.js").is_file(), reason="화면 원본(prototype/)이 없는 곳에서는 건너뛴다")
def test_C1_the_screen_offers_exactly_the_styles_the_server_accepts():
    import re
    want = [(k, v["label"]) for k, v in th.ART_STYLES.items()]
    assert want == [("watercolor", "수채화"), ("anime", "애니풍"), ("oil_painting", "유화")]
    card = re.compile(r"\{id: '(\w+)', title: '([^']+)', note:")
    src = (PROTO / "app" / "illust-style.js").read_text(encoding="utf-8")
    assert card.findall(src) == want and "const DEFAULT = 'watercolor';" in src        # 화면 원본 · 기본 수채화
    built = (PROTO / "index.html").read_text(encoding="utf-8")                          # 서버가 내보내는 묶은 파일
    assert card.findall(built) == want and "pencil_wash" not in built and "연필담채화" not in built
    demo = (PROTO / "app" / "srv-demo.js").read_text(encoding="utf-8")                  # 예시 모드도 같은 규칙
    assert "['watercolor', 'anime', 'oil_painting'].includes(illust)" in demo
    assert "illust_style: illustStyle" in (PROTO / "app" / "srv-core.js").read_text(encoding="utf-8")   # 요청 본문의 칸 이름
