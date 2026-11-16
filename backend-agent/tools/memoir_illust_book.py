"""
자서전 한 권 — 목차별로 사진이 없는 항목에 삽화를 한 장씩 넣는다. 로컬 실험이다 (서비스 · DB · API · UI 와 이어져 있지 않다).

    python tools/memoir_illust_book.py --input eval/illust_book_seed_B.json --out eval/runs/illust-book-B-mock --dry-run
    python tools/memoir_illust_book.py --input eval/illust_book_seed_B.json --out eval/runs/illust-book-B-mock \
        --mock-select eval/illust_book_mock_B.json --mock-images

흐름: 한 권 입력 → 목차별 사진 확인 → 사진 없는 항목의 대표 그림 정하기 → 그림 만들기 → 그 본문에 넣기 → 결과와 미리보기.
사람이 장면을 고르거나 항목마다 승인하는 단계가 없다 (자동). 책 전체에서 몇 개까지라는 한도도 없다.
**장면 선정 지시문 v4 와 이 자동 흐름은 아직 실제 모델로 돌려 본 적이 없다.**

--dry-run          목차 · 사진 상태 · 대상 수 · 부를 횟수만 보인다. 아무것도 부르지 않는다.
--mock-select      장면 선정 모델 자리에 끼울 모의 후보 {"by_chapter": {"<식별자 또는 번호>": {"candidates": [...]}}}.
--mock-images      그림 모델 자리에 시험용 그림(「MOCK」 이라고 적힌 자리 표시)을 끼운다. 결과에 모의라고 적힌다.
--live             실제 모델을 부른다 — 이 실험에서 **아직 승인되지 않았다**. 항목마다 장면 선정 1회 + 그림 1회이고 돈이 든다.
                   --confirm(dry-run 의 live_confirm) · --env-file · --authorized-by · --authorization-note 가 모두 있어야 한다.
--reprocess-stale  「다시 처리 필요」 로 남은 항목만 새로 처리한다 — 앞선 파일은 items/_stale/ 로 옮겨 둔다(지우지 않는다).
                   실제 실행에서는 그 항목 수만큼 호출이 는다 — 스스로 켜지지 않는다.

**다시 돌릴 때** (같은 --out)
- 모의 실행의 폴더를 실제 실행에 넘기거나 그 반대면 부르기 전에 멈춘다. 모의 그림은 실제 결과로 쳐 주지 않는다.
- 앞선 선정 결과와 그림은 **그것이 기대던 것이 그대로일 때만** 다시 쓴다 — 책 · 그 장면이 인용한 원문과 출처 · 그 장면의 본문 문단 ·
  지시문 · 그림 양식 · 그림 설정. 문단이 자리만 옮겼으면 그 문단을 따라간다. 하나라도 달라졌으면 앞선 그림을 넣지 않고
  「다시 처리 필요」 와 까닭을 남긴다(파일은 그대로 둔다). 책의 다른 곳이 바뀐 것은 이 항목과 상관없다.
- 그림 파일이 정말 있고 기록(해시 · 지시문)과 같은지 본다. 파일이 없으면 보관된 응답에서 꺼내고, 그것도 없으면 실패다 — 다시 부르지 않는다.
- 그림은 만들었는데 넣는 데 실패한 항목은 저장된 그림으로 넣기만 다시 한다.
- 결과 책은 매번 원고와 상태에서 새로 조립한다 — 삽화가 두 번 들어가지 않는다.
- 실패 · 보류로 끝난 항목은 스스로 다시 시도하지 않는다 (돈이 든다).

**기존 사진은 빼지 않는다.** 자리를 쓸 수 없으면 같은 항목 안의 기본 자리로 옮기고 까닭을 적는다. 사진 파일을 읽지 못하면
오류로 남기고 책을 complete 로 치지 않는다. 사진의 path 는 입력 파일이 있는 폴더를 기준으로 읽는다.

결과 (--out 아래 · git 제외)

    state.json               항목별 처리 상태 — 다시 돌릴 때 읽는다
    items.json               목차별 처리 결과표
    book_illustrated.json    문단 · 기존 사진 · 삽화가 차례로 든 책 (원고는 건드리지 않는다)
    book_illustrated.md      같은 내용의 글
    preview.html             파일 하나로 열리는 미리보기 (사진과 그림이 안에 들어 있다)
    items/<항목>/…           항목마다의 요청 · 응답 · 그림      items/_stale/…  다시 처리하며 옮겨 둔 앞선 파일

종료 코드: 0 책이 complete / 1 incomplete / 2 조건 거부
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_illust as il            # noqa: E402
from app.session import memoir_illust_book as book     # noqa: E402
from tools import memoir_illust as seltool             # noqa: E402
from tools import memoir_illust_image as img           # noqa: E402

PRIVATE = ROOT / "eval" / "exp"
RUNS = ROOT / "eval" / "runs"
IMAGE_MODEL, IMAGE_SIZE, IMAGE_ASPECT = "gemini-3.1-flash-image", "1K", "5:4"
SELECT_MODEL = "gemini-3.5-flash-lite"
IMAGE_USD = 0.067                    # 1K 그림 한 장 — 2026-11-14 첫 호출의 그림 토큰 1,120 × 문서 가격. 호출 전 다시 확인한다
INSERT = book.insert_position        # 시험이 갈아 끼운다 (넣기 실패)
MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise il.IllustError("input", f"{path.name} 을 읽지 못했다 ({type(e).__name__})") from e


def mock_image_call(prompt: str, *, model: str, size: str, aspect: str, key: str) -> dict:
    """시험용 그림 — 실제 그림이 아니다. 지시문의 사물 · 방식 줄을 적어 둔 자리 표시다."""
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (1152, 928), (243, 236, 224))
    d = ImageDraw.Draw(im)
    try:
        big, small = ImageFont.truetype("malgun.ttf", 54), ImageFont.truetype("malgun.ttf", 30)
    except OSError:
        big = small = ImageFont.load_default()
    d.rectangle([40, 40, 1112, 888], outline=(170, 150, 125), width=6)
    d.text((90, 110), "MOCK — 모의 삽화", fill=(120, 60, 40), font=big)
    d.text((90, 200), "실제 그림이 아닙니다 (시험용 자리 표시)", fill=(90, 80, 70), font=small)
    y = 300
    for line in [ln for ln in prompt.splitlines() if ln.startswith(("- 방식", "- 배경", "- 인물", "- 행동", "- 사물"))][:6]:
        d.text((90, y), line[:44], fill=(60, 55, 50), font=small)
        y += 62
    d.text((90, 800), "sha " + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16], fill=(140, 130, 120), font=small)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return {"id": "mock", "status": "completed", "model": "mock",
            "output_image": {"type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()},
            "usage": None}


def plan_token(ref: str, targets: list, select_model: str, image_model: str, size: str, aspect: str) -> str:
    raw = json.dumps([ref, targets, select_model, image_model, size, aspect, book.prompt_hash(), il.prompt_hashes()],
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def new_item(it: dict, photo: dict) -> dict:
    return {"ident": it["ident"], "key": it["key"], "no": it["no"], "title": it["title"], "chapter_hash": it["chapter_hash"],
            "photo": photo, "target": False, "target_reason": None, "status": None, "failure": None,
            "selection": None, "basis": None, "image": {"status": "not_requested", "path": None},
            "insertion": {"status": "not_applicable"},
            # 자동 처리다 — 사람이 고르거나 승인한 것이 아니다. 이 둘을 true 로 바꾸는 코드는 이 흐름에 없다
            "automatic": True, "user_selected": False, "user_approved": False}


def check_photos(photo: dict, base_dir: Path | None) -> None:
    """사진 파일을 읽을 수 있는가 — path 가 있는 사진만 본다(주소 url 은 가 보지 않는다). 못 읽으면 그 사진에 오류를 적는다."""
    for p in photo["photos"]:
        if not p.get("path"):
            p["file"] = "url_not_checked" if p.get("url") else "no_file_info"
            continue
        f = (base_dir / p["path"]) if base_dir is not None and not Path(p["path"]).is_absolute() else Path(p["path"])
        try:
            ok = f.is_file() and len(f.read_bytes()) > 0 and f.suffix.lower() in MIMES
        except OSError:
            ok = False
        p["file"] = "readable" if ok else "unreadable"
        if not ok:
            p["error"] = "photo_file_unreadable"


def verify_image(image_dir: Path, run: dict | None, prompt_text: str, mock: bool) -> tuple[bool, str | None]:
    """
    저장된 그림을 이번 결과로 써도 되는가 — 기록만 믿지 않고 파일을 본다. (됨, 안 되는 까닭)
    모의 그림을 실제 실행에서, 실제 그림을 모의 실행에서 쓰지 않는다. 안 된다고 해서 API 를 다시 부르지 않는다.
    """
    if not run or run.get("outcome") != "image_saved":
        return False, (run or {}).get("outcome") or "no_record"
    if bool(run.get("mock")) != mock:
        return False, "mode_mismatch"
    if run.get("prompt_sha256") != img.sha256(prompt_text.encode("utf-8")):
        return False, "prompt_mismatch"
    f = image_dir / run["image_file"]
    if not f.is_file() and (image_dir / "response.json").is_file():       # 파일만 없어졌다 — 보관된 응답에서 꺼낸다
        try:
            img.save_image(image_dir, json.loads((image_dir / "response.json").read_text(encoding="utf-8")), dict(run))
        except Exception:                             # noqa: BLE001
            pass
    if not f.is_file():
        return False, "file_missing"
    if img.sha256(f.read_bytes()) != run.get("image_sha256"):
        return False, "file_mismatch"
    return True, None


def process(data: dict, out: Path, *, select_for=None, image_call=None, mock: bool, key: str = "",
            image_model: str = IMAGE_MODEL, authorization: dict | None = None, base_dir: Path | None = None,
            reprocess_stale: bool = False) -> tuple[list[dict], dict]:
    """
    한 권을 항목마다 처리한다. select_for(항목) → (system, user) 를 받아 응답 글을 돌려주는 함수(없으면 장면을 정하지 않는다).
    image_call 은 그림 모델 자리(없으면 그림을 만들지 않는다). 한 항목의 실패가 다른 항목을 건드리지 않는다.
    """
    state_path = out / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else None
    if state is not None and bool(state.get("mock")) != mock:             # 부르기 전에 멈춘다
        raise il.IllustError("mode", f"이 폴더는 {'모의' if state.get('mock') else '실제'} 실행의 것이다 — "
                                     f"{'실제' if state.get('mock') else '모의'} 실행에 다시 쓸 수 없다. 새 --out 을 쓴다")
    out.mkdir(parents=True, exist_ok=True)
    state = state or {"items": {}}
    ref = il.input_ref(data)
    photos = book.photo_states(data)
    image_cfg = {"model": image_model, "size": IMAGE_SIZE, "aspect": IMAGE_ASPECT}
    items, calls = [], {"select": 0, "image": 0}

    def save():
        state_path.write_text(json.dumps({"input_ref": ref, "mock": mock, "items": {str(x["ident"]): x for x in items}},
                                         ensure_ascii=False, indent=1), encoding="utf-8")

    for t in book.toc(data):
        prev = state["items"].get(str(t["ident"]))
        it = new_item(t, photos[t["ident"]])
        items.append(it)
        folder = out / "items" / str(t["ident"])
        try:
            check_photos(it["photo"], base_dir)
            st = it["photo"]["state"]
            if t["raw"].get("illustrations"):
                it.update(status="already_illustrated", already_illustrated=True,
                          target_reason="이 항목에는 이미 삽화가 들어 있다 — 다시 만들지 않는다")
                continue
            if st == "has_photo":
                bad = [p["photo_id"] for p in it["photo"]["photos"] if p.get("error")]
                it.update(status="kept_photo", target_reason=f"사진이 있다({len(it['photo']['photos'])}장) — 삽화를 넣지 않는다",
                          failure=["photo_file_unreadable"] if bad else None)
                continue
            if st == "unknown":
                it.update(status="photo_unknown", failure=["photo_info_missing"],
                          target_reason="사진이 있는지 모른다 — 없다고 보지 않는다. 삽화를 만들지 않는다 (자료 부족)")
                continue
            it.update(target=True, target_reason="사진이 없는 것이 확인됐다 — 삽화 한 장을 넣는다", status="pending")
            it["insertion"] = {"status": "pending"}

            # ① 앞선 결과를 다시 써도 되는가 — 그것이 기대던 원문 · 본문 문단 · 지시문 · 설정이 그대로일 때만
            if prev and prev.get("selection"):
                why = book.reuse_check(data, t, prev, image_cfg)
                if why and reprocess_stale:
                    n = 1
                    while (out / "items" / "_stale" / f"{t['ident']}-{n}").exists():
                        n += 1
                    if folder.exists():               # 앞선 파일은 지우지 않고 옮겨 둔다
                        (out / "items" / "_stale").mkdir(parents=True, exist_ok=True)
                        folder.rename(out / "items" / "_stale" / f"{t['ident']}-{n}")
                    it["reprocessed"] = {"reasons": why, "previous_files": f"items/_stale/{t['ident']}-{n}"}
                    prev = None
                elif why:
                    it.update(status="needs_reprocess", failure=[w["reason"] for w in why])
                    it["stale"] = {"reasons": why, "previous_selection": (prev["selection"].get("scene") or {}).get("scene_title"),
                                   "previous_status": prev.get("status"), "previous_image": (prev.get("image") or {}).get("path"),
                                   "kept_files": f"items/{t['ident']}",
                                   "note": "앞선 선정 결과와 그림을 넣지 않았다. 파일은 그대로 있다. --reprocess-stale 로 이 항목만 새로 처리한다"}
                    it["selection"], it["basis"] = prev["selection"], prev.get("basis")
                    it["insertion"] = {"status": "not_applicable"}
                    continue
            if prev and prev.get("selection"):
                it["selection"], it["basis"] = prev["selection"], prev["basis"]
                it["selection_reused"] = True
                if prev.get("chapter_hash") != t["chapter_hash"]:
                    it["body_changed"] = True         # 항목의 다른 곳이 바뀌었다 — 이 장면이 기대던 것은 그대로다
            elif select_for is not None:
                folder.mkdir(parents=True, exist_ok=True)
                system, user = book.select_prompt(), il.select_message(data, [t["ident"]])
                (folder / "select_request.json").write_text(json.dumps(
                    {"system": system, "user": user, "prompt_file": book.SELECT_FILE, "prompt_hash": book.prompt_hash()},
                    ensure_ascii=False, indent=1), encoding="utf-8")
                if (folder / "select_attempt.json").is_file():
                    # 앞선 실행이 이 항목의 장면 선정을 불렀는데 결과를 남기지 못하고 멈췄다 — 다시 부르지 않는다
                    it["selection"] = {"status": "failed", "reasons": ["select_attempt_without_result"], "tried": [],
                                       "detail": "장면 선정을 부른 기록만 있고 결과가 없다 — 스스로 다시 부르지 않는다"}
                else:
                    meta = {"mock": mock, "started_at": img.now(), "call": 1, "prompt_file": book.SELECT_FILE,
                            "prompt_hash": book.prompt_hash()}
                    (folder / "select_attempt.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
                    calls["select"] += 1
                    try:
                        reply = select_for(t)(system, user)
                    except Exception as e:            # noqa: BLE001 — 다시 부르지 않는다
                        meta.update(finished_at=img.now(), failure={"type": type(e).__name__,
                                                                   "http_status": getattr(e, "status_code", None) or getattr(e, "code", None)})
                        it["selection"] = {"status": "failed", "reasons": ["select_call_error"], "detail": type(e).__name__, "tried": []}
                    else:
                        if isinstance(reply, dict):   # 실제 호출 — 글과 함께 실행 정보(실제 모델 판 · 응답 식별자 · 토큰)가 온다
                            meta.update({k: v for k, v in reply.items() if k != "text"})
                            reply = reply["text"]
                        meta["finished_at"] = img.now()
                        (folder / "select_response.txt").write_text(reply, encoding="utf-8")
                        it["selection"] = book.choose(data, t["ident"], reply)
                    (folder / "select_run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
                    it["select_run"] = {k: meta.get(k) for k in ("model_requested", "model_version", "response_id", "usage",
                                                                 "finish", "retries", "started_at", "finished_at", "failure")}
                it["basis"] = book.reuse_basis(data, t, it["selection"], image_cfg)
            sel = it["selection"]
            if sel is None:
                continue
            if sel["status"] != "selected":
                it.update(status=sel["status"], failure=sel["reasons"])
                it["insertion"] = {"status": "not_applicable"}
                continue

            # ② 그림 — 폴더마다 호출은 한 번. 이미 있으면 파일을 확인하고 쓴다
            image_dir = folder / "image"
            attempted = (image_dir / "attempt.json").is_file()
            run = json.loads((image_dir / "run.json").read_text(encoding="utf-8")) if (image_dir / "run.json").is_file() else None
            if not attempted:
                if image_call is None:
                    it["image"] = {"status": "not_requested", "path": None}
                    continue
                approval = {"mode": "automatic", "approved_by": None, "batch_authorization": authorization,
                            "covers": "목차별 자동 처리 — 항목마다 사람이 고르거나 승인하지 않는다. 그림을 승인한 것이 아니다"}
                _, run = img.run_once(image_dir, sel["prompt"]["text"].encode("utf-8"), model=image_model, size=IMAGE_SIZE,
                                      aspect=IMAGE_ASPECT, key=key, approval=approval, quiet=True, call=image_call,
                                      request={"toc_item": str(t["ident"]), "mock": mock})
                calls["image"] += 1
            elif run and run.get("outcome") == "save_failed":             # 응답은 있다 — 다시 부르지 않고 꺼내기만 한다
                _, run = img.run_once(image_dir, sel["prompt"]["text"].encode("utf-8"), model=image_model, size=IMAGE_SIZE,
                                      aspect=IMAGE_ASPECT, key="", approval={}, quiet=True)
            ok, why = verify_image(image_dir, run, sel["prompt"]["text"], mock)
            if not ok:
                it["image"] = {"status": "failed", "path": None, "outcome": why, "reused": attempted}
                it.update(status="failed", failure=[f"image_{why}"])
                it["insertion"] = {"status": "not_applicable"}
                continue
            rel = (image_dir / run["image_file"]).relative_to(out).as_posix()
            it["image"] = {"status": "mock_generated" if run.get("mock") else "generated", "path": rel, "mock": bool(run.get("mock")),
                           "sha256": run.get("image_sha256"), "model": run.get("model"), "reused": attempted, "file_verified": True}

            # ③ 넣기 — 저장된 그림으로 한다. 실패해도 그림을 다시 만들지 않는다
            try:
                it["insertion"] = INSERT(data, it, sel["placement"])
            except Exception as e:                    # noqa: BLE001
                it["insertion"] = {"status": "failed", "reason": "insert_error", "detail": type(e).__name__}
            if it["insertion"]["status"] == "inserted":
                it["status"] = "inserted"
            else:
                it.update(status="failed", failure=[f"insert_{it['insertion'].get('reason')}"])
        except il.IllustError as e:                   # 이 항목만 실패로 남기고 다음 항목으로 간다
            it.update(status="failed", failure=[f"error_{e.kind}"])
        finally:
            save()
    return items, calls


def write_outputs(data: dict, out: Path, items: list[dict], mock: bool, base_dir: Path | None = None) -> dict:
    doc = book.build_book(data, items, mock)
    summary = book.summarize(items, mock, doc)

    def uri(rel: str):
        """결과 폴더의 그림, 또는 입력 폴더 기준의 사진 → 미리보기에 박아 넣을 data: 주소."""
        for p in (out / rel, (base_dir / rel) if base_dir is not None else None, Path(rel)):
            try:
                if p is not None and p.is_file() and p.suffix.lower() in MIMES:
                    return f"data:{MIMES[p.suffix.lower()]};base64," + base64.b64encode(p.read_bytes()).decode()
            except OSError:
                pass
        return None

    table = [{k: it.get(k) for k in ("ident", "no", "title", "status", "target", "target_reason", "failure", "automatic",
                                     "user_selected", "user_approved", "stale", "reprocessed")}
             | {"photo_state": it["photo"]["state"], "photo_basis": it["photo"]["basis"], "photos": len(it["photo"]["photos"]),
                "photo_files": [{k: p.get(k) for k in ("photo_id", "path", "url", "file", "error", "after_paragraph")}
                                for p in it["photo"]["photos"]],
                "mode": (it["selection"] or {}).get("mode"), "selection_source": (it["selection"] or {}).get("source"),
                "scene_title": ((it["selection"] or {}).get("scene") or {}).get("scene_title"),
                "evidence": ((it["selection"] or {}).get("scene") or {}).get("evidence"),
                "auto_checks": (it["selection"] or {}).get("auto_checks"), "basis": it.get("basis"),
                "image_status": it["image"]["status"], "image_path": it["image"].get("path"),
                "insertion": it["insertion"]} for it in items]
    (out / "items.json").write_text(json.dumps({"mock": mock, "summary": summary, "items": table}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    (out / "book_illustrated.json").write_text(json.dumps({**doc, "summary": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "book_illustrated.md").write_text(book.render_markdown(doc), encoding="utf-8")
    (out / "preview.html").write_text(book.render_html(doc, items, summary, uri), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="자서전 한 권 — 사진 없는 목차마다 삽화 한 장 (로컬 실험)")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mock-select", type=Path)
    ap.add_argument("--mock-images", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--confirm")
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--authorized-by")
    ap.add_argument("--authorization-note")
    ap.add_argument("--reprocess-stale", action="store_true")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    try:
        data = load(a.input)
        if not ((isinstance(data, dict) and data.get("synthetic") is True) or PRIVATE.resolve() in a.input.resolve().parents):
            raise il.IllustError("input", "합성 자료(synthetic: true)가 아니면 eval/exp/ 아래에 두어야 한다")
        if RUNS.resolve() not in a.out.resolve().parents:
            raise il.IllustError("input", "--out 은 eval/runs/ 아래여야 한다 (git 제외 경로)")
        photos = book.photo_states(data)
        toc = book.toc(data)
        targets = [t["ident"] for t in toc if photos[t["ident"]]["state"] == "no_photo_confirmed" and not t["raw"].get("illustrations")]
        token = plan_token(il.input_ref(data), targets, SELECT_MODEL, IMAGE_MODEL, IMAGE_SIZE, IMAGE_ASPECT)
        if a.dry_run:
            saved = load(a.out / "state.json") if (a.out / "state.json").is_file() else {"items": {}}
            state = saved["items"]
            cfg = {"model": IMAGE_MODEL, "size": IMAGE_SIZE, "aspect": IMAGE_ASPECT}
            stale = [t["ident"] for t in toc if t["ident"] in targets and (state.get(str(t["ident"])) or {}).get("selection")
                     and book.reuse_check(data, t, state[str(t["ident"])], cfg)]
            need_sel = [t for t in targets if not (state.get(str(t)) or {}).get("selection")]
            need_img = [t for t in targets if not ((state.get(str(t)) or {}).get("image") or {}).get("path")
                        and ((state.get(str(t)) or {}).get("selection") or {"status": "selected"})["status"] == "selected"]
            print(json.dumps({
                "dry_run": True, "input_ref": il.input_ref(data), "toc_items": len(toc),
                "photo_states": {s: sum(1 for p in photos.values() if p["state"] == s)
                                 for s in ("has_photo", "no_photo_confirmed", "unknown")},
                "targets": targets, "limit": None,
                "existing_state": None if not (a.out / "state.json").is_file() else ("mock" if saved.get("mock") else "live"),
                "needs_reprocess_if_live": stale,
                "calls_if_live": {"select": len(need_sel), "image_at_most": len(need_img)},
                "sent_if_live": [{"toc_item": t["ident"], "title": t["title"], "sentences": sum(
                                      len(p["sentences"]) if isinstance(p, dict) else len(p) for p in t["raw"]["paragraphs"]),
                                  "source_turns": t["source_turns"],
                                  "elder_chars": sum(len(u["elder"]) for u in (data.get("source") or {}).get("utterances", [])
                                                     if u["turn"] in t["source_turns"]),
                                  "select_system_chars": len(book.select_prompt()),
                                  "select_user_chars": len(il.select_message(data, [t["ident"]]))}
                                 for t in toc if t["ident"] in targets],
                "retries": {"select": "off (attempts=1)", "image": "off (SDK · HTTP)"},
                "models": {"select": SELECT_MODEL, "image": IMAGE_MODEL, "size": IMAGE_SIZE, "aspect": IMAGE_ASPECT},
                "estimated_image_cost_usd": round(len(need_img) * IMAGE_USD, 3),
                "select_prompt": {book.SELECT_FILE: book.prompt_hash()}, "live_confirm": token,
                "verified_with_real_model": False, "live_approved": False, "api_called": False}, ensure_ascii=False, indent=1))
            return 0
        if a.live:
            if a.mock_select or a.mock_images:
                raise il.IllustError("input", "--live 와 --mock-… 을 함께 쓸 수 없다")
            if a.confirm != token or not a.env_file or not (a.authorized_by or "").strip() or not (a.authorization_note or "").strip():
                raise il.IllustError("not_approved", "--live 에는 --confirm(dry-run 의 live_confirm) · --env-file · --authorized-by · "
                                                     "--authorization-note 가 모두 있어야 한다. 이 실험에서 실제 호출은 아직 승인되지 않았다")
            if (a.out / "state.json").is_file() and load(a.out / "state.json").get("mock"):
                raise il.IllustError("mode", "이 폴더는 모의 실행의 것이다 — 실제 실행에 다시 쓸 수 없다. 새 --out 을 쓴다")
            key = img.read_key(a.env_file)
            authorization = {"authorized_by": a.authorized_by, "note": a.authorization_note, "recorded_at": img.now(),
                             "targets": targets}

            def select_for(t):
                return lambda system, user: seltool.LIVE_CALL(system, user, model=SELECT_MODEL, key=key)
            image_call, mock = img.LIVE_CALL, False
        else:
            if not a.mock_select and not a.mock_images:
                raise il.IllustError("not_approved", "--dry-run · --mock-select/--mock-images · --live 중 하나를 쓴다")
            key, authorization, mock = "", None, True
            by = load(a.mock_select).get("by_chapter", {}) if a.mock_select else None

            def select_for(t):
                reply = by.get(str(t["ident"]), {"candidates": []})
                return lambda system, user: json.dumps(reply, ensure_ascii=False)
            if by is None:
                select_for = None
            image_call = mock_image_call if a.mock_images else None
        base_dir = a.input.resolve().parent
        items, calls = process(data, a.out, select_for=select_for, image_call=image_call, mock=mock, key=key,
                               image_model="mock" if mock else IMAGE_MODEL, authorization=authorization, base_dir=base_dir,
                               reprocess_stale=a.reprocess_stale)
    except (il.IllustError, img.Refuse) as e:
        print(f"거부 — {e}", file=sys.stderr)
        return 2

    summary = write_outputs(data, a.out, items, mock, base_dir)
    print(json.dumps({"out": str(a.out), "mock": mock, "calls": calls, "summary": summary,
                      "items": [{"ident": it["ident"], "title": it["title"], "photo": it["photo"]["state"], "status": it["status"],
                                 "mode": (it["selection"] or {}).get("mode"), "failure": it["failure"]} for it in items]},
                     ensure_ascii=False, indent=1))
    return 0 if summary["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
