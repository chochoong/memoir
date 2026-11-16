"""
자서전 삽화 장면 선정을 로컬에서 돌린다. DB 도 서버도 쓰지 않는다. 이미지는 만들지 않는다.

    python tools/memoir_illust.py --input eval/illust_seed_A.json --dry-run
    python tools/memoir_illust.py --input eval/illust_seed_A.json --mock eval/illust_mock_A.json
    python tools/memoir_illust.py --input eval/exp/<책>/input.json --chapter c01 --dry-run
    python tools/memoir_illust.py --input eval/exp/<책>/input.json --chapter c01 --mock <모의 후보>

--chapter  모델에 보낼 범위를 그 장(번호 또는 식별자)과 그 장이 근거로 쓰는 원문 턴으로 좁힌다. 여러 번 쓸 수 있다.
--dry-run  입력을 검사하고 보낼 범위와 크기만 보인다 (자료 내용은 찍지 않는다).
--mock     모델 응답 자리에 그 파일을 끼워 판정 · 그림 지시문까지 만든다.
--live     장면 선정 모델을 **한 번** 부른다. 실제 원문이 바깥으로 나가고 돈이 든다 — 아래 조건을 다 채워야 한다.

**--live 의 조건** (하나라도 빠지면 부르지 않는다)
- --chapter 로 범위를 좁혔다 (책 전체는 보내지 않는다) · 보내는 원문 턴이 LIVE_MAX_TURNS 이하다
- --model 로 모델을, --env-file 로 키가 든 파일을 줬다 (키는 GEMINI_API_KEY — 찍지 않는다)
- --confirm 에 dry-run 이 보여 준 live_confirm 값을 그대로 넣었다 (입력 · 범위 · 모델이 바뀌면 값도 바뀐다)
다시 부르지 않는다. 실패하면 받은 응답과 까닭을 남기고 끝난다.

**받는 자료.** `"synthetic": true` 인 합성 자료, 또는 eval/exp/ 아래(git 제외)에 둔 파일뿐이다.

결과는 eval/runs/<run_ref>/ 에 남는다 (git 제외 — 원문이 들어 있다).

    request.json        모델에 보낸(보낼) 지시와 자료, 범위
    response.raw.txt    모델이 낸 글 그대로 (모의 응답이면 그 파일의 내용)
    candidates.json     모델이 낸 후보 그대로 — 모듈의 판정이 섞이지 않은 것
    result.json         모듈의 최종 판정 (illust-result-v1)
    report.md           사람이 볼 요약
    human_review.json   사람이 원문과 대조해 채울 평가지 — 모든 칸이 not_reviewed 로 시작한다
    run.json            실행 기록 (모의/실제 · 호출 수 · 토큰 · 실패)

종료 코드: 0 끝남 / 1 모델 응답을 쓰지 못함 / 2 입력 · 조건 거부
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_illust as il     # noqa: E402

PRIVATE = ROOT / "eval" / "exp"
RUNS = ROOT / "eval" / "runs"
LIVE_MAX_TURNS = 5
LIVE_MAX_OUTPUT_TOKENS = 4096
LIVE_TIMEOUT_MS = 120_000

# 사람이 후보마다 원문과 대조해 적는 항목 (첨부프롬프트_md/삽화/3_평가기준_v1.md)
REVIEW_ITEMS = {
    "scene_fit": "독자가 이야기를 이해하는 데 도움이 되는 장면인가",
    "mode_fit": "SCENE · SYMBOLIC · SKIP 판정이 알맞은가",
    "quote_in_turn": "인용이 그 턴의 말씀과 맞는가",
    "sentence_cites_turn": "자서전의 그 문장이 그 턴을 실제로 근거로 쓰는가",
    "who_did_what": "① 제안된 사람이 실제로 중심 행동에 참여했는가 (relations 에 사람마다 적는다) "
                    "② 원문에서 함께 행동한 사람이 후보에서 빠지지 않았는가 (participants_review 에 장면마다 적는다) — 둘 다 본다",
    "time_place_object": "때 · 장소 · 사물이 원문과 같은가",
    "moments_not_merged": "서로 다른 때의 일을 한 순간으로 합치지 않았는가",
    "markers_not_missed": "부정 · 추정 · 전언 · 뒤의 정정을 빠뜨리지 않았는가",
    "nothing_added": "날씨 · 외모 · 시대 · 새 행동을 덧붙이지 않았는가",
    "review_state_ok": "사진 정보가 없거나 출처가 불완전한 후보가 검토 상태에 남았는가",
    "placement_ok": "가리킨 문단이 그 장면의 자리가 맞는가",
    "one_central_action": "그림에 담을 행동이 하나로 정해졌는가 (나르기와 쉬기를 한 그림에 섞지 않았는가)",
    "title_summary_wording": "제목 · 요약이 「쯤」 을 지우거나 배경을 행동의 자리로 바꿔 쓰지 않았는가",
}


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise il.IllustError("input", f"{path.name} 을 읽지 못했다 ({type(e).__name__})") from e


def allowed(path: Path, data) -> bool:
    if isinstance(data, dict) and data.get("synthetic") is True:
        return True
    return PRIVATE.resolve() in path.resolve().parents


def chapters_arg(values: list[str] | None) -> list | None:
    return None if not values else [int(v) if v.isdigit() else v for v in values]


def confirm_token(ref: str, only: list | None, model: str | None, user: str, system: str = "") -> str:
    """
    입력 · 범위 · 모델 · 보낼 자료 · 지시문이 그대로일 때만 같은 값 — 승인한 것과 다른 것을 보내지 못하게.
    지시문(system)을 고치면 값이 바뀐다 — 앞선 호출의 승인으로 새 지시문을 보낼 수 없다.
    """
    sent = hashlib.sha256((system + "\x00" + user).encode("utf-8")).hexdigest()
    raw = json.dumps([ref, only, model, sent], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def gemini_call(system: str, user: str, *, model: str, key: str, base_url: str | None = None) -> dict:
    """
    한 번 부른다. 다시 부르지 않는다 — 재시도를 명시적으로 끈다(attempts=1). 생성 설정은 팀 파이프라인
    (memoir_pipeline.call_model)과 같다. 응답 글과 함께 제공되는 실행 정보(실제 모델 판 · 응답 식별자 · 토큰)를 돌려준다.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key, http_options=types.HttpOptions(
        timeout=LIVE_TIMEOUT_MS, base_url=base_url, retry_options=types.HttpRetryOptions(attempts=1)))
    cfg = types.GenerateContentConfig(
        system_instruction=system, response_mime_type="application/json", temperature=0.2,
        max_output_tokens=LIVE_MAX_OUTPUT_TOKENS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    res = client.models.generate_content(model=model, contents=user, config=cfg)
    cands = getattr(res, "candidates", None) or []
    um = getattr(res, "usage_metadata", None)
    return {"text": res.text or "",
            "model_requested": model, "model_version": getattr(res, "model_version", None),
            "response_id": getattr(res, "response_id", None),
            "create_time": str(res.create_time) if getattr(res, "create_time", None) else None,
            "retries": "off (attempts=1)",
            "finish": str(cands[0].finish_reason) if cands and getattr(cands[0], "finish_reason", None) is not None else None,
            "usage": None if um is None else {"prompt": getattr(um, "prompt_token_count", None),
                                              "output": getattr(um, "candidates_token_count", None),
                                              "thoughts": getattr(um, "thoughts_token_count", None),
                                              "total": getattr(um, "total_token_count", None)}}


LIVE_CALL = gemini_call      # 시험이 갈아 끼운다


def read_key(env_file: Path) -> str:
    from dotenv import dotenv_values

    key = (dotenv_values(env_file).get("GEMINI_API_KEY") or "").strip() if env_file.is_file() else ""
    if not key:
        raise il.IllustError("not_approved", f"{env_file.name} 에 GEMINI_API_KEY 가 없다")
    return key


def apply_confirmations(sheet: dict, confirmations: dict | None) -> dict:
    """
    사람이 넘겨준 확인 기록이 평가지에서 덮는 범위만 채운다. 그 밖의 칸은 not_reviewed 그대로 둔다.

        reviewer             확인 기록의 검토자
        who_did_what         그 장면의 relations 가 전부 confirmed 이고 participants_review 가 complete 일 때만 ok
        confirmation_record  확인 기록에 사람이 함께 적은 말(관계 · 장면 식별값은 빼고) — 무엇을 확인한 것인지 읽게 한다
    관계 · 장면의 human 값은 판정(result)에서 이미 왔다 — 식별값이 맞는 것만 반영돼 있다.
    """
    if not confirmations:
        return sheet
    sheet["reviewer"] = confirmations.get("reviewer")
    sheet["reviewed_at"] = confirmations.get("reviewed_at")
    sheet["confirmation_record"] = {k: v for k, v in confirmations.items() if k not in ("relations", "scenes")}
    for sc in sheet["scenes"]:
        people = [r["human"] for r in sc["relations"]]
        if sc["participants_review"]["human"] == "complete" and all(h == "confirmed" for h in people):
            sc["items"]["who_did_what"].update(
                verdict="ok", note=f"확인 기록(검토자 {confirmations.get('reviewer')})에서 옴 — "
                                   f"인물 관계 {len(people)}건 confirmed · 빠진 참여자 없음 complete")
    return sheet


def review_sheet(result: dict) -> dict:
    """사람이 채울 평가지. 코드가 본 것(auto)과 사람이 볼 것(items)을 섞지 않는다."""
    return {
        "note": "사람이 원문과 대조해 채운다. verdict: not_reviewed · ok · problem · not_applicable. "
                "verified 는 원문 근거를 따라갈 수 있다는 뜻일 뿐이다 — 의미가 맞는지는 여기에 적는다.",
        "what_each_confirmation_means": {
            "relations": "사람 하나씩 — 제안된 그 사람이 그 행동에 그 역할로 참여했는가 (confirmed · rejected). "
                         "제안된 사람을 다 confirmed 해도 빠진 사람이 없다는 뜻이 아니다",
            "participants_review": "장면 하나씩 — 원문에서 함께 한 사람이 이 후보에서 빠지지 않았는가 (complete · incomplete). "
                                   "그 후보의 행동 · 사람들 · 원문에 묶인다. 사람을 넣거나 빼면 다시 본다",
            "generation_prompt_needs": "구체적 장면(SCENE)은 relations 가 전부 confirmed 이고 participants_review 가 complete 여야 "
                                       "생성용 지시문이 만들어진다. 그래도 user_selected · image_status · user_approved 는 따로다",
            "how_to_submit": "{\"reviewer\": \"이름\", \"relations\": {relation_id: 판정}, \"scenes\": {scene_review_id: 판정}} "
                             "파일을 --confirmations 로 넘긴다"},
        "input_ref": result["input_ref"], "reviewer": None, "reviewed_at": None,
        "book_level": {"no_suitable_scene_is_fine": "적합한 후보가 0개여도 정상이다", "missed_scenes": [], "note": ""},
        "scenes": [{"scene_id": s["scene_id"], "scene_title": s["scene_title"], "decision": s["decision"],
                    "visual_mode": s["visual_mode"],
                    "auto": {"verification": s["verification"], "verification_review": s["verification_review"],
                             "summary_persons_resolution": s["checks"]["summary_consistency"].get("persons_resolution"),
                             "memoir_link": s["memoir_link"],
                             "checks": {k: v["state"] for k, v in s["checks"].items()},
                             "placement": s["placement"] and {k: s["placement"][k] for k in ("paragraph_index", "basis")}},
                    # 인물마다 — 이 사람이 이 행동에 참여했는가. 사람이 confirmed · rejected 로 적어
                    # {"reviewer": "이름", "relations": {relation_id: 판정}} 파일로 --confirmations 에 넘긴다
                    "central_action": s["central_action"],
                    # 한 후보를 이 자리에서 다 읽을 수 있게 — 제목 · 요약 · 그릴 행동(턴 · 인용) · 검토용 초안
                    "scene_summary": s["scene_summary"],
                    "draft_scene_block": (s["generation_prompt"] or s["draft_prompt"] or {}).get("scene_block"),
                    "relations": [{"relation_id": r["relation_id"], "text": r["text"],
                                   "proposed": r["proposed"],                       # 모델이 낸 관계 그대로 (없으면 null)
                                   "evidence": (r["proposed"] or {}).get("evidence") or [r["element_quote"]],
                                   "element_quote": r["element_quote"],
                                   "code": r["code"]["state"],                       # 코드가 본 것 — 칸과 인용뿐
                                   "human": r["human"], "note": ""}                  # 사람이 본 것
                                  for r in s["people_review"]],
                    # 장면 단위 — 인물 목록 옆에서 원문 문맥을 읽고, 빠진 참여자가 없는지 적는다
                    "participants_review": {**s["participants_review"], "note": ""},
                    "items": {k: {"question": q, "verdict": "not_reviewed", "note": ""} for k, q in REVIEW_ITEMS.items()},
                    "human_semantic_check": "not_reviewed"}
                   for s in result["scenes"]],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="자서전 삽화 장면 선정 (로컬 실험)")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--chapter", action="append", help="범위로 삼을 장 번호 또는 식별자 (여러 번)")
    ap.add_argument("--mock", type=Path, help="모델 응답 자리에 끼울 모의 후보 JSON")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--live", action="store_true", help="장면 선정 모델을 한 번 부른다 (조건은 파일 머리말)")
    ap.add_argument("--model")
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--confirm")
    ap.add_argument("--confirmations", type=Path, help="사람이 확인한 인물 관계 JSON (reviewer · relations · scenes)")
    ap.add_argument("--compare-to", type=Path,
                    help="원본 후보(candidates.json) — --mock 이 그것을 고친 보완 초안일 때 차이를 changes.json 에 남긴다")
    ap.add_argument("--out", type=Path, help="결과 폴더 (기본 eval/runs/<run_ref>)")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    def refuse(kind: str, why: str):
        return il.IllustError(kind, why)

    try:
        data = load(a.input)
        if not allowed(a.input, data):
            raise refuse("input", "합성 자료(synthetic: true)가 아니면 eval/exp/ 아래에 두어야 한다")
        only = chapters_arg(a.chapter)
        confirmations = load(a.confirmations) if a.confirmations else None
        il.load_confirmations(confirmations)
        if a.compare_to and not a.mock:
            raise refuse("input", "--compare-to 는 --mock(보완 초안)과 함께 쓴다")
        sc = il.scope(data, only)
        ctx, ref = sc["ctx"], il.input_ref(data)
        system, user = il.select_prompt(), il.select_message(data, only)
        token = confirm_token(ref, only, a.model, user, system)
        if a.dry_run:
            print(json.dumps({
                "dry_run": True, "input_ref": ref, "whole_book": sc["whole_book"],
                "scope_chapters": [c["key"] or c["no"] for c in sc["chapters"]], "scope_turns": len(sc["turns"]),
                "sentences": sum(len(c["sentences"]) for c in sc["chapters"]),
                "sentences_with_turns": sum(1 for c in sc["chapters"] for s in c["sentences"] if s["turns"]),
                "utterances_total": len(ctx["utts"]), "photos": None if ctx["photos"] is None else len(ctx["photos"]),
                "system_chars": len(system), "user_chars": len(user),
                "elder_chars_sent": sum(len(ctx["utts"][t]["elder"]) for t in sc["turns"] if t in ctx["utts"]),
                "prompt_hashes": il.prompt_hashes(), "model": a.model, "live_confirm": token if a.model else None,
                "live_allowed_by_scope": bool(only) and len(sc["turns"]) <= LIVE_MAX_TURNS,
                "model_called": False}, ensure_ascii=False, indent=1))
            return 0
        if a.live and a.mock:
            raise refuse("input", "--live 와 --mock 을 함께 쓸 수 없다")
        meta = {"input_ref": ref, "source": "mock" if a.mock else "live", "model": None, "calls": 0,
                "usage": None, "finish": None, "failure": None, "image_api_called": False}
        if a.mock:
            mock = load(a.mock)
            raw = json.dumps(mock, ensure_ascii=False, indent=1)
        elif a.live:
            if not only or len(sc["turns"]) > LIVE_MAX_TURNS:
                raise refuse("not_approved", f"--live 는 --chapter 로 좁힌 범위(원문 {LIVE_MAX_TURNS}턴 이하)에서만 된다")
            if not a.model or not a.env_file:
                raise refuse("not_approved", "--live 에는 --model 과 --env-file 이 있어야 한다")
            if a.confirm != token:
                raise refuse("not_approved", "--confirm 이 dry-run 의 live_confirm 과 다르다 — 승인한 범위 · 모델인지 확인한다")
            key = read_key(a.env_file)
            raw = None
        else:
            raise refuse("not_approved", "--mock · --dry-run · --live 중 하나를 쓴다 (실제 호출은 승인된 범위에서만)")
    except il.IllustError as e:
        print(f"거부 — {e}", file=sys.stderr)
        return 2

    out = a.out or RUNS / f"illust-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{ref}"
    out.mkdir(parents=True, exist_ok=True)

    def save(name: str, obj) -> None:
        text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1)
        (out / name).write_text(text, encoding="utf-8")

    save("request.json", {"system": system, "user": user, "model": a.model if a.live else None,
                          "scope": {"chapters": [c["key"] or c["no"] for c in sc["chapters"]], "turns": sc["turns"]}})
    code = 0
    try:
        if a.live:
            meta.update(model=a.model, calls=1)       # 부르기 전에 센다 — 실패해도 한 번 부른 것이다
            try:
                reply = LIVE_CALL(system, user, model=a.model, key=key)
            except Exception as e:                    # noqa: BLE001 — 다시 부르지 않고 까닭만 남긴다
                raise il.IllustError("model_call", f"{type(e).__name__}") from e
            raw = reply["text"]
            meta.update(usage=reply.get("usage"), finish=reply.get("finish"))
        save("response.raw.txt", raw)
        save("candidates.json", {"note": "모델(모의)이 낸 후보 그대로 — 모듈의 판정 전", "source": meta["source"],
                                 "candidates": il.check_candidates(raw)})
        result = il.run(data, call=lambda s, u: raw, model_source=meta["source"], only=only,
                        confirmations=confirmations)
        save("result.json", result)
        save("report.md", il.report(result))
        sheet = apply_confirmations(review_sheet(result), confirmations)
        if a.confirmations:
            save("confirmations.json", confirmations)     # 이 판정에 쓴 확인 기록의 사본 — 사람이 쓴 그대로
        if a.compare_to:
            # 보완 초안 — 누가 무엇을 고쳤는지와 원본과의 차이를 평가지 맨 위에 둔다. 원본 기록은 건드리지 않는다
            amendment = mock.get("amendment") if isinstance(mock, dict) else None
            if not isinstance(amendment, dict) or not str(amendment.get("author") or "").strip():
                raise il.IllustError("input", "보완 초안에는 amendment.author(고친 주체)가 있어야 한다")
            changes = il.diff_candidates(load(a.compare_to)["candidates"], il.check_candidates(raw))
            meta["amendment"] = {**amendment, "compared_to": str(a.compare_to)}
            save("changes.json", {"amendment": meta["amendment"], "changes": changes,
                                  "note": "원본 후보와 보완 초안의 차이 — 판정이 아니다. 더한 요소 · 관계 · 인용을 사람이 확인한다"})
            adopted = (confirmations or {}).get("amendment_review")
            sheet = {"amendment": {**meta["amendment"], "changes": changes,
                                   # 보완 초안을 쓴 주체(author)는 그대로다. 사람이 채택했는지는 확인 기록에서만 온다
                                   "human_review_of_amendment": adopted if adopted in ("adopted", "rejected") else "not_reviewed",
                                   "human_reviewer": (confirmations or {}).get("reviewer") if adopted else None}, **sheet}
        save("human_review.json", sheet)
        print(json.dumps({"out": str(out), "source": meta["source"], "calls": meta["calls"], "usage": meta["usage"],
                          "summary": result["summary"],
                          "scenes": [{k: s[k] for k in ("scene_id", "scene_title", "visual_mode", "verification",
                                                        "decision", "decision_reasons")} for s in result["scenes"]]},
                         ensure_ascii=False, indent=1))
    except il.IllustError as e:
        meta["failure"] = {"kind": e.kind, "message": e.message}
        print(f"실패 — {e} (다시 부르지 않는다 · 기록 {out})", file=sys.stderr)
        code = 1
    save("run.json", meta)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
