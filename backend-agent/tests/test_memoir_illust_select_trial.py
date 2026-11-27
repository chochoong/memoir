"""
장면 선정 전용 시험 실행기 (tools/memoir_illust_select_trial.py) — 모의 호출로만 시험한다. 모델 · 그림 API 를 부르지 않는다.

    python -m pytest tests/test_memoir_illust_select_trial.py -q

그림 쪽 함수(그림 실행기의 LIVE_CALL · run_once · 모의 그림)는 모든 시험에서 불리면 바로 실패하게 바꿔 둔다 —
정상 · 오류 · 다시 돌리기 어느 길에서도 그림 호출이 0회임을 본다. 실제 선정 호출도 막아 둔다(실제 호출 배선 시험만 가짜로 바꾼다).
"""

from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_illust as il                     # noqa: E402
from app.session import memoir_illust_book as book              # noqa: E402
from tools import memoir_illust as seltool                      # noqa: E402
from tools import memoir_illust_select_trial as T               # noqa: E402

TRIAL, DATA, CASES = T.load_trial()
WHICH = {il.select_message(DATA, [k]): k for k in TRIAL["targets"]}
FIRST = T.mock_from_cases(CASES, TRIAL["targets"])


@pytest.fixture(autouse=True)
def no_image_or_real_calls(monkeypatch):
    from tools import memoir_illust_book as booktool
    from tools import memoir_illust_image as img

    def boom(*a, **k):
        raise AssertionError("그림 API 자리가 불렸다")

    def real(*a, **k):
        raise AssertionError("실제 선정 호출이 불렸다")
    monkeypatch.setattr(img, "LIVE_CALL", boom)
    monkeypatch.setattr(img, "run_once", boom)
    monkeypatch.setattr(booktool, "mock_image_call", boom)
    monkeypatch.setattr(seltool, "LIVE_CALL", real)


def caller(replies: dict, log: list):
    def call(system, user):
        k = WHICH[user]
        log.append(k)
        r = replies[k]
        if isinstance(r, BaseException):
            raise r
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)
    return call


def go(out: Path, replies: dict, log: list | None = None, *, mock: bool = True, trial: dict = TRIAL):
    return T.run(T.TRIAL, trial, DATA, CASES, out, call=caller(replies, [] if log is None else log), mock=mock)


def never(system, user):
    raise AssertionError("이미 시도한 항목을 다시 불렀다")


def case_reply(cid: str) -> tuple[str, dict]:
    key = cid.split("-")[0]
    c = next(x for x in CASES[key]["cases"] if x["id"] == cid)
    doc = {"candidates": [CASES[key]["candidates"][n] for n in c["candidates"]]}
    if c["focus"]:
        doc["focus"] = CASES[key]["focus"][c["focus"]]
    return key, doc


def one(out: Path, cid: str, doc: dict | None = None) -> dict:
    """한 항목만 대상으로 돌리고 그 항목의 평가를 돌려준다."""
    key, d = case_reply(cid)
    go(out, {key: doc if doc is not None else d}, trial=dict(TRIAL, targets=[key]))
    return json.loads((out / "items" / key / "evaluation.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 대상 고정 · 그림 모듈 없음

def test_trial_is_fixed_to_five_synthetic_items_with_hashes():
    assert TRIAL["targets"] == ["c01", "c04", "c05", "c07", "c08"]
    assert DATA["synthetic"] is True and TRIAL["max_select_calls"] == 5 and TRIAL["image_calls"] == 0
    p = T.plan(T.TRIAL, TRIAL, DATA)
    assert set(p["frozen"]) == {"select_prompt_v5", "picture_style", "judge_book", "judge_core", "select_call", "runner",
                                "trial", "cases", "input"}
    assert all(len(v["sha256"]) == 64 for v in p["frozen"].values())
    assert p["frozen"]["select_prompt_v5"]["path"].endswith("1_장면선정_v5_목차중심.md")
    assert all(r["photo_clues"] == 0 and len(r["source_turns"]) == 1 for r in p["items"])     # 그 항목의 원문 턴 하나 · 사진 단서 없음


def test_trial_refuses_changed_data_too_many_targets_and_photo_items(tmp_path):
    for change, kind in ((lambda t: t["input"].update(sha256="0" * 64), "frozen"),
                         (lambda t: t.update(targets=["c01", "c02", "c03", "c04", "c05", "c06"]), "cap"),
                         (lambda t: t.update(targets=["c01", "c09"]), "input")):
        t = copy.deepcopy(TRIAL)
        change(t)
        f = tmp_path / "trial.json"
        f.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(il.IllustError) as e:
            T.load_trial(f)
        assert e.value.kind == kind


def test_runner_never_loads_the_image_module():
    tree = ast.parse((ROOT / "tools" / "memoir_illust_select_trial.py").read_text(encoding="utf-8"))
    names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    names += [f"{n.module}.{a.name}" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names]
    assert not [x for x in names if "image" in x], names
    code = ("import sys; sys.path.insert(0, r'%s'); import tools.memoir_illust_select_trial; "
            "print(sorted(m for m in sys.modules if 'memoir_illust_image' in m or m.startswith('google')))" % ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True)
    assert out.stdout.strip() == "[]"                                  # 그림 실행기도, 모델 SDK 도 불러오지 않는다


# ---------------------------------------------------------------- 정상 · 오류 · 다시 돌리기 — 선정 최대 5회 · 그림 0회

def test_normal_path_calls_select_once_per_item_and_never_images(tmp_path):
    log = []
    items, calls = go(tmp_path, FIRST, log)
    assert calls == {"select": 5, "image": 0} and sorted(log) == TRIAL["targets"]
    for it in items:
        d = tmp_path / "items" / it["ident"]
        assert it["image"]["status"] == "not_requested_select_only" and it["run_mode"] == "select_only"
        assert it["select_call"] == "called" and it["user_selected"] is False and it["user_approved"] is False
        for f in ("select_request.json", "select_attempt.json", "select_response.txt", "select_run.json", "selection.json",
                  "evaluation.json"):
            assert (d / f).is_file(), (it["ident"], f)
        assert (d / "image_prompt.txt").is_file() == (it["status"] == "selected")
        if it["status"] == "selected":
            assert (d / "image_prompt.txt").read_text(encoding="utf-8").startswith("# 보내지 않은 그림 지시문")
    m = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert m["mock"] is True and m["image"]["calls"] == 0 and m["max_calls"]["select_total"] == 5
    run = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["runs"][-1]
    assert run["image_calls_total"] == 0 and run["select_attempted_total"] == 5
    assert "그림 API 호출: **0회**" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_errors_and_bad_replies_are_not_retried(tmp_path):
    log = []
    replies = {"c01": RuntimeError("503"), "c04": "JSON 이 아니다", "c05": {"candidates": []}, "c07": '{"candidates": "x"}',
               "c08": FIRST["c08"]}
    items, calls = go(tmp_path, replies, log)
    by = {it["ident"]: it for it in items}
    assert calls == {"select": 5, "image": 0} and sorted(log) == TRIAL["targets"]          # 항목마다 한 번 — 다시 부르지 않는다
    assert by["c01"]["select_call"] == "called_error" and by["c01"]["reasons"] == ["select_call_error"]
    assert by["c01"]["select_run"]["failure"]["type"] == "RuntimeError"
    assert by["c01"]["image"]["status"] == "not_requested_select_only"                      # 선정 실패는 그림 실패가 아니다
    assert by["c04"]["reasons"] == ["model_output"] and by["c07"]["reasons"] == ["model_output"]
    assert by["c05"]["reasons"] == ["no_candidate"] and by["c08"]["status"] == "selected"
    ev = json.loads((tmp_path / "items" / "c01" / "evaluation.json").read_text(encoding="utf-8"))
    assert ev["run_problems"] and not ev["model_problems"] and not ev["code_problems"]       # 호출 오류는 모델 탓도 코드 탓도 아니다
    ev4 = json.loads((tmp_path / "items" / "c04" / "evaluation.json").read_text(encoding="utf-8"))
    assert ev4["model"]["q1_center_proposed"]["verdict"] == "형식 오류"
    items2, calls2 = T.run(T.TRIAL, TRIAL, DATA, CASES, tmp_path, call=never, mock=True)
    assert calls2 == {"select": 0, "image": 0}
    assert {it["ident"]: it["select_call"] for it in items2}["c01"] == "not_called_previous_error"


def test_rerun_reuses_saved_replies_and_calls_nothing(tmp_path):
    go(tmp_path, FIRST)
    before = {k: (tmp_path / "items" / k / "selection.json").read_text(encoding="utf-8") for k in TRIAL["targets"]}
    items, calls = T.run(T.TRIAL, TRIAL, DATA, CASES, tmp_path, call=never, mock=True)
    assert calls == {"select": 0, "image": 0}
    assert all(it["select_call"] == "not_called_reused_saved_response" for it in items)
    assert before == {k: (tmp_path / "items" / k / "selection.json").read_text(encoding="utf-8") for k in TRIAL["targets"]}
    runs = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["runs"]
    assert [r["calls_this_run"]["select"] for r in runs] == [5, 0] and runs[-1]["select_attempted_total"] == 5


def test_an_interrupted_call_is_never_made_again(tmp_path):
    """c04 를 부르는 중에 멈췄다(시도 기록만 있고 응답이 없다) — 다시 돌리면 c04 는 부르지 않고, 아직 안 부른 항목만 부른다."""
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, {**FIRST, "c04": KeyboardInterrupt()})
    log = []
    items, calls = go(tmp_path, FIRST, log)
    by = {it["ident"]: it for it in items}
    assert sorted(log) == ["c05", "c07", "c08"] and calls == {"select": 3, "image": 0}
    assert by["c01"]["select_call"] == "not_called_reused_saved_response"
    assert by["c04"]["select_call"] == "not_called_attempted_without_result"
    assert by["c04"]["reasons"] == ["select_attempt_without_result"]
    assert json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["runs"][-1]["select_attempted_total"] == 5


def test_changed_prompt_code_or_criteria_cannot_rejudge_the_same_folder(tmp_path, monkeypatch):
    go(tmp_path, FIRST)
    real = T.frozen

    def changed(trial_path, trial):
        f = real(trial_path, trial)
        f["trial"] = dict(f["trial"], sha256="0" * 64)                 # 기대값을 고친 것처럼
        return f
    monkeypatch.setattr(T, "frozen", changed)
    with pytest.raises(il.IllustError) as e:
        T.run(T.TRIAL, TRIAL, DATA, CASES, tmp_path, call=never, mock=True)
    assert e.value.kind == "frozen" and "trial" in e.value.message


def test_mock_folder_cannot_be_used_for_a_live_run(tmp_path):
    go(tmp_path, FIRST)
    with pytest.raises(il.IllustError) as e:
        T.run(T.TRIAL, TRIAL, DATA, CASES, tmp_path, call=never, mock=False)
    assert e.value.kind == "mode"


# ---------------------------------------------------------------- 명령줄 — dry-run · 실제 호출 조건

def test_cli_dry_run_calls_nothing_and_reports_the_plan(capsys, tmp_path):
    assert T.main(["--dry-run"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["api_called"] is False and d["live_approved"] is False
    assert d["calls_if_live"] == {"select": 5, "image": 0} and d["max_calls"]["image"] == 0
    assert d["config"]["model"] == "gemini-3.5-flash-lite" and d["config"]["max_output_tokens"] == 4096
    assert d["config"]["retries"].startswith("off")
    est = d["estimate"]
    assert est["image_usd"] == 0 and "보장된 상한이 아니다" in est["not_a_cap"]
    assert est["typical"]["usd"] < est["if_every_reply_reaches_max_output_tokens"]["usd"]
    assert len(d["live_confirm"]) == 12 and [r["toc_item"] for r in d["items"]] == TRIAL["targets"]
    assert not list(tmp_path.iterdir())


def test_cli_live_needs_every_condition_and_then_calls_five_times_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(T, "RUNS", tmp_path)
    out = tmp_path / "live"
    env = tmp_path / "test.env"
    env.write_text("GEMINI_API_KEY=test-only-not-a-real-key\n", encoding="utf-8")
    sent = []

    def fake(system, user, *, model, key):
        sent.append((WHICH[user], model, key))
        return {"text": json.dumps(FIRST[WHICH[user]], ensure_ascii=False), "model_requested": model,
                "model_version": "gemini-3.5-flash-lite", "response_id": "r-" + WHICH[user], "retries": "off (attempts=1)",
                "finish": "FinishReason.STOP", "usage": {"prompt": 2400, "output": 1500, "thoughts": None, "total": 3900}}
    monkeypatch.setattr(seltool, "LIVE_CALL", fake)
    token = T.plan(T.TRIAL, TRIAL, DATA)["live_confirm"]
    base = ["--live", "--out", str(out)]
    full = base + ["--confirm", token, "--env-file", str(env), "--authorized-by", "test", "--authorization-note", "시험"]
    for argv in (base, base + ["--confirm", token], full[:-2], [x if x != token else "000000000000" for x in full]):
        assert T.main(argv) == 2 and not sent                           # 하나라도 빠지면 부르지 않는다
    assert T.main(full) == 0
    assert [s[0] for s in sent] == TRIAL["targets"] and {s[1] for s in sent} == {"gemini-3.5-flash-lite"}
    items = json.loads((out / "items.json").read_text(encoding="utf-8"))
    assert items["summary"]["image_calls_total"] == 0 and items["summary"]["calls_this_run"] == {"select": 5, "image": 0}
    first = items["items"][0]
    assert first["select_run"]["model_version"] == "gemini-3.5-flash-lite" and first["select_run"]["usage"]["prompt"] == 2400
    assert first["cost_usd_from_usage"] == round(2400 * 0.30 / 1e6 + 1500 * 2.50 / 1e6, 5)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["mock"] is False and m["authorization"]["authorized_by"] == "test" and m["live_confirm"] == token
    assert "test-only-not-a-real-key" not in json.dumps(m) + (out / "report.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert T.main(full) == 0 and len(sent) == 5                          # 같은 폴더로 다시 — 더 부르지 않는다


def test_cli_mock_from_cases_writes_a_mock_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(T, "RUNS", tmp_path)
    assert T.main(["--mock-from-cases", "--out", str(tmp_path / "m")]) == 0
    assert json.loads(capsys.readouterr().out)["calls"] == {"select": 5, "image": 0}
    assert T.main(["--mock-from-cases", "--out", str(ROOT / "eval" / "x")]) == 2          # eval/runs/ 밖에는 쓰지 않는다


# ---------------------------------------------------------------- 평가 — 모델 쪽과 코드 쪽을 섞지 않는다

def test_model_offering_only_peripheral_pictures_is_a_model_problem_not_a_code_one(tmp_path):
    ev = one(tmp_path, "c07-2")
    assert "중심을 담은 후보: 아니오" in ev["model_problems"] and not ev["code_problems"]
    assert ev["code"]["q4_chose_appropriate"].startswith("선택 없음 — 적절한 후보가 없었다")


def test_known_limit_is_tagged_not_counted_as_a_new_problem(tmp_path):
    ev = one(tmp_path, "c05-1")
    assert not ev["model_problems"] and ev["known_limit_hit"]["case"] == "c05-1"
    assert ev["code_problems"] and all(p.startswith("[알려진 한계 c05-1]") for p in ev["code_problems"])


def test_missing_co_worker_is_a_model_problem_and_the_code_keeps_the_center(tmp_path):
    ev = one(tmp_path, "c01-3")
    assert any(p.startswith("참여자") for p in ev["model_problems"])
    scene = ev["model"]["q3_participants_and_evidence"]["scenes"][0]
    assert any("아버지" in p and "빠졌다" in p for p in scene["problems"])
    assert ev["code"]["chosen"]["source"] == "derived_symbolic" and ev["code"]["q4_chose_appropriate"] == "예"
    assert not ev["code_problems"]


def test_short_evidence_with_source_support_is_counted_against_the_code(tmp_path):
    """
    어머니의 근거 인용을 「어머니랑 저랑 둘이서」 로만 잘랐다 — 원문 문장은 김장까지 받친다. 코드가 사람 장면을 막으면 코드 쪽으로 센다.
    [실제 호출 전에 찾은 것 · 기준은 고정 — 고치지 않았다] 이 항목은 사람 장면이 막히면 대신할 그림이 없다. 중심 근거가 있는 것은
    어머니(제목 + 본문)뿐이고, 사람을 뺀 그림에 남는 배추는 한 문장에만 나와 「딸린 것」 이다 — 항목 전체가 실패한다.
    """
    _, doc = case_reply("c08-1")
    doc = copy.deepcopy(doc)
    mother = next(e for e in doc["candidates"][0]["elements"] if e["text"] == "어머니")
    mother["relation"]["evidence"] = [{"turn": 8, "quote": "어머니랑 저랑 둘이서"}]
    ev = one(tmp_path, "c08-1", doc)
    assert ev["model"]["q3_participants_and_evidence"]["evidence_cut_short"] == ["후보 0: 어머니"]
    assert ev["code"]["status"] == "failed"
    wrong = {(w["source"], w["scene_title"]): w for w in ev["code"]["q5_wrongly_rejected"]}
    scene = wrong[("candidate", "어머니와 둘이 김장하기")]
    assert "person_relation_evidence_thin" in scene["why"] and scene["effect"] == "항목이 실패했다"
    assert wrong[("derived_symbolic", "배추")]["why"].startswith("중심 판정")
    assert wrong[("candidate", "마당에 묻은 김장독")]["known_limit"] == "c08-3"
    assert ev["known_limit_hit"]["case"] == "c08-3" and len(ev["code_problems"]) == 3


def test_code_passing_a_peripheral_picture_is_flagged(tmp_path):
    key, doc = case_reply("c07-1")
    sel = book.choose(copy.deepcopy(DATA), key, json.dumps(doc, ensure_ascii=False))
    fake = copy.deepcopy(sel)
    for r in fake["comparison"]:                                       # 찻잔 그림을 고른 것처럼 바꾼다 — 평가가 잡아내는지만 본다
        r["chosen"] = r["source"] == "candidate" and "찻잔" in r["scene_title"]
    assert any(r["chosen"] for r in fake["comparison"])
    ev = T.evaluate(DATA, TRIAL, CASES, key, json.dumps(doc, ensure_ascii=False), fake)
    assert ev["code"]["q6_wrongly_passed"] and any(p.startswith("잘못 통과") for p in ev["code_problems"])


def test_once_mentioned_co_actor_stays_in_the_scene(tmp_path):
    """동생은 본문에 한 번 나와 대표성 등급이 낮다(linked). 그래도 함께 탄 사람이라 사람 장면에서 빠지지 않는다."""
    act = {"key": "a1", "kind": "action", "text": "트럭 짐칸에 앉아 고개를 넘었다", "turn": 7, "quote": "트럭 짐칸에 앉아서 고개를 넘었어요"}
    ev_q = [{"turn": 7, "quote": "저는 동생이랑 트럭 짐칸에 앉아서 고개를 넘었어요"}]
    cand = {"chapter_no": 7, "scene_title": "동생과 트럭 짐칸에 앉아 고개를 넘다", "scene_summary": "동생과 트럭 짐칸에 앉아 고개를 넘었다.",
            "importance": "main", "reason": "이사 길", "central_action": "a1", "elements": [
                act,
                {"key": "p1", "kind": "person", "text": "저", "turn": 7, "quote": "저는 동생이랑",
                 "relation": {"action": "a1", "role": "actor", "evidence": ev_q}},
                {"key": "p2", "kind": "person", "text": "동생", "turn": 7, "quote": "동생이랑 트럭 짐칸에",
                 "relation": {"action": "a1", "role": "co_actor", "evidence": ev_q}},
                {"key": "o1", "kind": "object", "text": "트럭", "turn": 7, "quote": "트럭 짐칸에 앉아서",
                 "relation": {"action": "a1", "role": "used", "evidence": [{"turn": 7, "quote": "트럭 짐칸에 앉아서 고개를 넘었어요"}]}}]}
    reply = json.dumps({"candidates": [cand]}, ensure_ascii=False)
    sel = book.choose(copy.deepcopy(DATA), "c07", reply)
    assert sel["status"] == "selected" and sel["mode"] == "SCENE" and sel["source"] == "candidate"
    assert next(v for v in sel["focus"]["items"] if v["text"] == "동생")["tier"] == "linked"
    assert "동생" in [e["text"] for e in sel["scene"]["evidence"]] and "동생" in sel["prompt"]["text"]
    ev = T.evaluate(DATA, TRIAL, CASES, "c07", reply, sel)
    row = next(r for r in ev["people_tier_vs_participation"]["rows"] if r["text"] == "동생")
    assert row["tier"] == "linked" and row["acts_in_central_action"] is True
    assert ev["people_tier_vs_participation"]["scene_dropped_by_tier"] == [] and not ev["code_problems"]
