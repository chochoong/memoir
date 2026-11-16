"""
자서전 삽화 — 서비스 연결부 (자서전이 저장되면 저절로 돈다)

    자서전 저장 (memoir_jobs.keep)  →  schedule(memoir_id, user_id)  →  뒤에서 run()

    ① 입력 만들기   build_input   원고(memoir.result) · 원문(회차 기록 → memoir.merge) · 목차별 사진
    ② 목차별 사진   photo_states  사진이 놓인 장은 그 사진을 보이고 삽화를 만들지 않는다 (memoir_illust_book)
    ③ 사진 없는 장  장면 선정 1회 → choose(자동 검사 · 대표 고르기) → 그림 1회 → 저장 → 넣을 자리
    ④ 상태 · 그림   memoir.illustrations (017) · 그림 바이트는 사진과 같은 저장소(photostore)

**삽화는 자서전 작업과 따로 돈다.** 자서전 작업은 저장까지 끝나면 done 이고, 삽화가 실패해도 본문은
그대로 열린다. 상태는 memoir.illustrations 에만 적는다 — memoir.result(원고)는 건드리지 않는다.

**사진은 회차에 붙은 사진(session.photo_id)이다.** 한 회차의 말씀이 한 장에만 쓰였을 때만 그 회차의 사진을 그 장에 놓는다
(그 회차 말씀이 처음 나오는 문단 뒤). 여러 장에 걸친 회차 · 장에 쓰이지 않은 회차의 사진은 어느 장의 사진으로도 치지 않는다
— 올라와 있다는 것만으로 표시된 사진이 아니다 (unplaced_photos 에 까닭과 함께 남긴다). 그래서 모든 장의 사진 상태가 정해진다
(photo_placement.complete) — 사진이 놓이지 않은 장은 「사진 없음 확인」 이다.

**다시 부르지 않는다.** 장면 선정과 그림은 장마다 한 번이다. 부르기 **전에** 「불렀다」 를 DB 에 적고, 결과를 적지 못한 채
멈췄으면(서버 재시작) 다음에 그 장을 실패로 남긴다 — 다시 부르지 않는다. 실패 · 보류도 저절로 다시 하지 않는다.
그림이 이미 저장된 장은 넣을 자리만 다시 정한다. 같은 책을 두 번 돌려도 그림은 장마다 한 장이다.

**사람이 확인한 것이 아니다.** automatic: true · human_reviewed: false 로 적는다. 화면에는 「AI 가 그린 그림」 으로 보인다.

설정 (환경변수 — 함수 안에서 읽는다)

    MEMOIR_ILLUST                auto(기본) · off.  auto 는 GEMINI_API_KEY 가 있을 때만 돈다
    MEMOIR_ILLUST_SELECT_MODEL   장면 선정 모델 (기본 gemini-3.5-flash-lite)
    MEMOIR_ILLUST_IMAGE_MODEL    그림 모델 (기본 gemini-3.1-flash-image · 1K · 5:4)

로그에는 장 번호 · 상태 · 토큰만 남긴다. 원문 · 본문 · 지시문은 남기지 않는다.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import io
import json
import logging
import os
from datetime import datetime, timezone

from . import memoir, memoir_illust as il, memoir_illust_book as book, photostore, store
from .conf import env_str

log = logging.getLogger("memoir.illust")

SCHEMA = "memoir-illust-service-v1"
DEFAULT_SELECT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"
IMAGE_SIZE, IMAGE_ASPECT, IMAGE_MIME = "1K", "5:4", "image/jpeg"
SELECT_TIMEOUT_MS, IMAGE_TIMEOUT_MS = 120_000, 180_000
SELECT_MAX_OUTPUT_TOKENS, SELECT_TEMPERATURE = 4096, 0.2

# 장 상태
PHOTO, ILLUSTRATED, FAILED, HELD, UNKNOWN, PENDING = "photo", "illustrated", "failed", "held", "photo_unknown", "pending"
DONE_STATES = (PHOTO, ILLUSTRATED, FAILED, HELD, UNKNOWN)
# 책 상태
RUNNING, COMPLETE, PARTIAL, BROKEN = "running", "done", "partial", "failed"


def enabled() -> bool:
    mode = env_str("MEMOIR_ILLUST", "auto").strip().lower()
    return mode != "off" and bool((os.environ.get("GEMINI_API_KEY") or "").strip())


def settings() -> dict:
    return {"select_model": env_str("MEMOIR_ILLUST_SELECT_MODEL", DEFAULT_SELECT_MODEL),
            "image_model": env_str("MEMOIR_ILLUST_IMAGE_MODEL", DEFAULT_IMAGE_MODEL),
            "size": IMAGE_SIZE, "aspect": IMAGE_ASPECT,
            "select_prompt": book.SELECT_FILE, "select_prompt_hash": book.prompt_hash(),
            "style_hash": il.prompt_hashes().get(il.STYLE_FILE)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- 모델 호출 (재시도 없음 — 한 번)

def gemini_select(system: str, user: str, *, model: str) -> dict:
    """장면 선정 한 번. 선정 전용 시험(2026-11-16)과 같은 설정 — JSON · 온도 0.2 · 출력 4,096 · 120초 · 재시도 끔."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"].strip(), http_options=types.HttpOptions(
        timeout=SELECT_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)))
    cfg = types.GenerateContentConfig(
        system_instruction=system, response_mime_type="application/json", temperature=SELECT_TEMPERATURE,
        max_output_tokens=SELECT_MAX_OUTPUT_TOKENS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    res = client.models.generate_content(model=model, contents=user, config=cfg)
    um = getattr(res, "usage_metadata", None)
    return {"text": res.text or "", "model_version": getattr(res, "model_version", None),
            "usage": None if um is None else {"prompt": getattr(um, "prompt_token_count", None),
                                              "output": getattr(um, "candidates_token_count", None),
                                              "thoughts": getattr(um, "thoughts_token_count", None)}}


def gemini_image(prompt: str, *, model: str) -> dict:
    """그림 한 번. tools/memoir_illust_image 와 같은 interactions.create 모양 · 재시도 끔."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"].strip(), http_options=types.HttpOptions(
        timeout=IMAGE_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)))
    cfg = getattr(client.interactions, "sdk_configuration", None)
    if cfg is None or not hasattr(cfg, "retry_config"):
        raise RuntimeError("SDK 의 재시도 설정을 찾지 못했다 — 끌 수 없으면 부르지 않는다")
    cfg.retry_config = None
    res = client.interactions.create(
        model=model, input=prompt,
        response_format={"type": "image", "mime_type": IMAGE_MIME, "aspect_ratio": IMAGE_ASPECT, "image_size": IMAGE_SIZE})
    return res.model_dump(mode="json") if hasattr(res, "model_dump") else dict(res)


# 시험이 갈아 끼운다
SELECT_CALL = gemini_select
IMAGE_CALL = gemini_image


def image_bytes(raw: dict) -> tuple[bytes, str] | None:
    """응답의 첫 그림 (output_image 또는 steps 안의 image). 바이트가 없으면 None."""
    items = [raw.get("output_image")] + [c for st in raw.get("steps") or [] if isinstance(st, dict)
                                         for c in (st.get("content") or []) if isinstance(c, dict)]
    for it in items:
        if isinstance(it, dict) and it.get("type", "image") == "image" and it.get("data"):
            return base64.b64decode(it["data"]), it.get("mime_type") or IMAGE_MIME
    return None


def _size(data: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:                                         # noqa: BLE001 — 크기는 화면의 자리 잡기용일 뿐이다
        return None, None


# ---------------------------------------------------------------- 입력

def place_session_photos(chapters: list[dict], turn_map: list[dict], photos: dict[str, dict]) -> tuple[dict, list[dict]]:
    """
    회차 사진 → 장. {장 번호: [사진]} 과 놓지 않은 사진 목록.

    photos 는 {session_id: 사진 행}. 한 회차의 말씀이 **한 장에만** 쓰였을 때 그 장에 놓고, 자리는 그 회차 말씀이 처음
    나오는 문단 뒤다. 여러 장에 걸쳤거나 어느 장에도 쓰이지 않았으면 놓지 않는다.
    """
    sid_of = {m["global_turn"]: m["session_id"] for m in turn_map}
    used: dict[str, list[tuple[int, int]]] = {}
    for ch in chapters:
        for pi, para in enumerate(ch["paragraphs"]):
            for x in para["sentences"]:
                for t in x.get("turns") or []:
                    if t in sid_of:
                        used.setdefault(sid_of[t], []).append((ch["no"], pi))
    placed: dict[int, list[dict]] = {}
    unplaced = []
    for sid, p in photos.items():
        spots = used.get(sid, [])
        nos = sorted({no for no, _ in spots})
        base = {"photo_id": p["photo_id"], "session_id": sid}
        if len(nos) == 1:
            first = min(pi for no, pi in spots if no == nos[0])
            placed.setdefault(nos[0], []).append({**base, "after_paragraph": first, "width": p.get("width"),
                                                  "height": p.get("height"), "url": f"/api/photos/{p['photo_id']}"})
        else:
            unplaced.append({**base, "reason": "session_in_many_chapters" if nos else "session_not_cited", "chapters": nos})
    return placed, unplaced


async def build_input(rec: dict, user_id: str) -> tuple[dict, list[dict]]:
    """저장된 자서전 하나 → 삽화 모듈 입력 (illust-input-v1) 과 놓지 않은 사진. 원고는 복사본만 쓴다."""
    result = rec["result"]
    ids = list((result.get("run") or {}).get("session_ids") or rec.get("session_ids") or [])
    recs = []
    for sid in ids:
        r = await store.load_session(sid)
        if r is None or r["user_id"] != user_id:
            raise il.IllustError("source", "자서전에 쓴 회차를 읽지 못했다")
        recs.append(r)
    src, turn_map = memoir.merge(recs)
    photos: dict[str, dict] = {}
    for r in recs:
        if not r.get("photo_id"):
            continue
        p = await store.load_photo(r["photo_id"])
        if p is not None and p["user_id"] == user_id and p["status"] == "stored":
            photos[r["session_id"]] = p
    chapters = copy.deepcopy(result.get("chapters") or [])
    placed, unplaced = place_session_photos(chapters, turn_map, photos)
    for ch in chapters:
        ch["photos"] = placed.get(ch["no"], [])
    data = {"schema_version": il.INPUT_SCHEMA,
            "memoir": {"memoir_id": rec["memoir_id"], "style": result.get("style"), "title": result.get("title"),
                       "chapters": chapters},
            "source": {"utterances": src["utterances"], "turn_map": turn_map},
            "photos": [{"photo_id": p["photo_id"], "session_id": sid, "turns": [], "clues": None} for sid, p in photos.items()],
            "photo_placement": {"complete": True, "basis": "회차 사진(session.photo_id)을 장에 놓는 규칙이 모든 장에 적용됐다"}}
    return data, unplaced


# ---------------------------------------------------------------- 상태 문서

def new_doc() -> dict:
    return {"schema": SCHEMA, "status": RUNNING, "automatic": True, "ai_generated_images": True,
            "human_reviewed": False, "user_selected": False, "user_approved": False,
            "started_at": _now(), "finished_at": None, "settings": settings(),
            "calls": {"select": 0, "image": 0}, "chapters": {}, "unplaced_photos": [], "error": None}


def finish_status(doc: dict) -> str:
    chs = list(doc["chapters"].values())
    if not chs:
        return BROKEN
    if any(c["state"] not in DONE_STATES for c in chs):
        return RUNNING
    return COMPLETE if all(c["state"] in (PHOTO, ILLUSTRATED) for c in chs) else PARTIAL


_RUNNING: dict[str, asyncio.Task] = {}


def running(memoir_id: str) -> bool:
    t = _RUNNING.get(memoir_id)
    return t is not None and not t.done()


def schedule(memoir_id: str | None, user_id: str) -> asyncio.Task | None:
    """자서전이 저장된 자리(memoir_jobs.keep)에서 부른다. 꺼져 있거나 이미 돌고 있으면 아무것도 하지 않는다."""
    if not memoir_id or not enabled() or running(memoir_id):
        return None
    task = asyncio.create_task(_guarded(memoir_id, user_id))
    _RUNNING[memoir_id] = task
    task.add_done_callback(lambda t: _RUNNING.pop(memoir_id, None) if _RUNNING.get(memoir_id) is t else None)
    return task


def resume_if_stalled(memoir_id: str, user_id: str, doc: dict | None) -> None:
    """상태가 running 인데 이 서버에서 돌고 있지 않다(재시작) — 남은 장만 이어서 한다. 부른 장은 다시 부르지 않는다."""
    if doc and doc.get("status") == RUNNING and not running(memoir_id):
        schedule(memoir_id, user_id)


async def _guarded(memoir_id: str, user_id: str) -> None:
    try:
        await run(memoir_id, user_id)
    except Exception as e:                                    # noqa: BLE001 — 삽화가 서버를 넘어뜨리지 않는다
        log.exception("삽화 %s 예상 못 한 오류 (%s)", memoir_id[:10], type(e).__name__)


async def _save(memoir_id: str, user_id: str, doc: dict) -> None:
    await store.save_memoir_illustrations(memoir_id, user_id, doc)


async def run(memoir_id: str, user_id: str, *, select_call=None, image_call=None) -> dict | None:
    """
    한 권을 장마다 처리한다. 장 하나의 실패가 다른 장을 막지 않는다. 상태는 단계마다 DB 에 적는다.
    돌려주는 것은 마지막 상태 문서 (자서전이 없으면 None).
    """
    select_call = select_call or SELECT_CALL
    image_call = image_call or IMAGE_CALL
    rec = await store.load_memoir(memoir_id, user_id)
    if rec is None:
        return None
    result = rec["result"] or {}
    doc = rec.get("illustrations") or new_doc()
    doc.setdefault("calls", {"select": 0, "image": 0})
    if result.get("status") != memoir.READY or not result.get("chapters"):
        doc.update(status=BROKEN, error="memoir_not_ready", finished_at=_now())
        await _save(memoir_id, user_id, doc)
        return doc
    try:
        data, unplaced = await build_input(rec, user_id)
        items = book.toc(data)
        photos = book.photo_states(data)
    except (il.IllustError, memoir.MemoirError, store.StoreUnavailable) as e:
        doc.update(status=BROKEN, error=f"input_{getattr(e, 'kind', type(e).__name__)}", finished_at=_now())
        await _save(memoir_id, user_id, doc)
        log.warning("삽화 %s 입력을 만들지 못했다 — %s", memoir_id[:10], doc["error"])
        return doc
    doc["status"], doc["error"], doc["unplaced_photos"] = RUNNING, None, unplaced
    cfg = doc.get("settings") or settings()
    doc["settings"] = cfg
    for it in items:
        key = str(it["no"])
        ch = doc["chapters"].get(key) or {"no": it["no"], "title": it["title"], "state": PENDING}
        doc["chapters"][key] = ch
        ph = photos[it["ident"]]
        ch["photo_state"], ch["photo_basis"] = ph["state"], ph["basis"]
        ch["photos"] = [{k: p.get(k) for k in ("photo_id", "after_paragraph", "width", "height")} for p in ph["photos"]]
        if ph["state"] == "has_photo":
            ch["state"], ch["reason"] = PHOTO, "이 장에 사진이 있다 — 삽화를 넣지 않는다"
        elif ph["state"] == "unknown":
            ch["state"], ch["failure"] = UNKNOWN, ["photo_info_missing"]
    await _save(memoir_id, user_id, doc)

    for it in items:
        ch = doc["chapters"][str(it["no"])]
        if ch["state"] in (PHOTO, UNKNOWN, FAILED, HELD):
            continue
        try:
            await _chapter(data, it, ch, doc, memoir_id, user_id, cfg, select_call, image_call)
        except il.IllustError as e:
            ch.update(state=FAILED, failure=[f"error_{e.kind}"])
        except Exception as e:                                # noqa: BLE001 — 이 장만 실패로 남긴다
            log.exception("삽화 %s %s장 오류", memoir_id[:10], it["no"])
            ch.update(state=FAILED, failure=[f"error_{type(e).__name__}"])
        await _save(memoir_id, user_id, doc)

    doc["status"] = finish_status(doc)
    doc["finished_at"] = _now()
    await _save(memoir_id, user_id, doc)
    log.info("삽화 %s — %s · 장 %s · 호출 선정 %d · 그림 %d", memoir_id[:10], doc["status"],
             " ".join(f"{k}={c['state']}" for k, c in sorted(doc["chapters"].items(), key=lambda x: int(x[0]))),
             doc["calls"]["select"], doc["calls"]["image"])
    return doc


async def _chapter(data, it, ch, doc, memoir_id, user_id, cfg, select_call, image_call) -> None:
    """사진 없는 장 하나 — 이미 한 것은 다시 하지 않는다."""
    sel_rec = ch.get("select") or {}
    img_rec = ch.get("image") or {}

    # ① 그림이 이미 저장돼 있다 — 넣을 자리만 (다시) 정한다
    if img_rec.get("storage_key"):
        if not await photostore.current().exists(img_rec["storage_key"]):
            ch.update(state=FAILED, failure=["image_file_missing"])
            return
        _insert(data, it, ch)
        return

    # ② 장면 선정 — 한 번만
    selection = sel_rec.get("selection")
    if selection is None:
        if sel_rec.get("attempted_at"):
            ch.update(state=FAILED, failure=["select_attempt_without_result"])
            return
        system, user = book.select_prompt(), il.select_message(data, [it["ident"]])
        ch["select"] = sel_rec = {"attempted_at": _now(), "model": cfg["select_model"], "prompt_hash": cfg["select_prompt_hash"]}
        ch["state"] = "selecting"
        doc["calls"]["select"] += 1
        await _save(memoir_id, user_id, doc)                 # 부르기 전에 적는다 — 멈춰도 다시 부르지 않는다
        try:
            reply = await asyncio.to_thread(select_call, system, user, model=cfg["select_model"])
        except Exception as e:                                # noqa: BLE001 — 다시 부르지 않는다
            sel_rec.update(finished_at=_now(), error=type(e).__name__)
            ch.update(state=FAILED, failure=["select_call_error"])
            log.warning("삽화 %s %s장 장면 선정 호출 실패 (%s)", memoir_id[:10], it["no"], type(e).__name__)
            return
        text = reply["text"] if isinstance(reply, dict) else str(reply)
        sel_rec.update(finished_at=_now(), usage=(reply or {}).get("usage") if isinstance(reply, dict) else None,
                       model_version=(reply or {}).get("model_version") if isinstance(reply, dict) else None)
        selection = await asyncio.to_thread(book.choose, data, it["ident"], text)
        sel_rec["selection"] = selection
    sel_rec["status"] = selection["status"]
    if selection["status"] != "selected":
        ch.update(state=HELD if selection["status"] == "held" else FAILED, failure=selection.get("reasons"))
        return
    sel_rec["scene_title"] = selection["scene"]["scene_title"]
    sel_rec["mode"] = selection["mode"]

    # ③ 그림 — 한 번만
    if img_rec.get("attempted_at"):
        ch.update(state=FAILED, failure=["image_attempt_without_result"])
        return
    prompt = selection["prompt"]["text"]
    ch["image"] = img_rec = {"attempted_at": _now(), "model": cfg["image_model"], "size": cfg["size"], "aspect": cfg["aspect"],
                             "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
    ch["state"] = "drawing"
    doc["calls"]["image"] += 1
    await _save(memoir_id, user_id, doc)
    try:
        raw = await asyncio.to_thread(image_call, prompt, model=cfg["image_model"])
    except Exception as e:                                    # noqa: BLE001
        img_rec.update(finished_at=_now(), error=type(e).__name__)
        ch.update(state=FAILED, failure=["image_call_error"])
        log.warning("삽화 %s %s장 그림 호출 실패 (%s)", memoir_id[:10], it["no"], type(e).__name__)
        return
    img_rec.update(finished_at=_now(), usage=raw.get("usage"), status=raw.get("status"))
    got = image_bytes(raw)
    if got is None:
        img_rec["outcome"] = "refused" if raw.get("errors") or raw.get("status") not in (None, "completed") else "empty"
        ch.update(state=FAILED, failure=[f"image_{img_rec['outcome']}"])
        return
    blob, mime = got
    sha = hashlib.sha256(blob).hexdigest()
    ext = photostore.EXT.get(mime, "jpg")
    now = datetime.now(timezone.utc)
    skey = f"illusts/{now.year:04d}/{now.month:02d}/{memoir_id}/c{it['no']}-{sha[:16]}.{ext}"
    try:
        await photostore.current().put(skey, blob, mime)
    except photostore.PhotoStoreError as e:
        img_rec.update(outcome="save_failed", error=type(e).__name__)
        ch.update(state=FAILED, failure=["image_save_failed"])
        return
    w, h = _size(blob)
    img_rec.update(outcome="image_saved", storage_key=skey, sha256=sha, mime=mime, bytes=len(blob), width=w, height=h)
    _insert(data, it, ch)


def _insert(data, it, ch) -> None:
    ins = book.insert_position(data, {"key": it["key"], "no": it["no"], "title": it["title"]},
                               (ch["select"]["selection"] or {}).get("placement"))
    ch["insertion"] = ins
    if ins.get("status") == "inserted":
        ch.update(state=ILLUSTRATED, failure=None)
    else:
        ch.update(state=FAILED, failure=[f"insert_{ins.get('reason')}"])


# ---------------------------------------------------------------- 화면에 내보내는 모양

def view(memoir_id: str, doc: dict | None) -> dict:
    """
    화면용 — 저장 키 · 지시문 · 원문은 싣지 않는다. 그림은 이 서버의 주소로만 나간다 (photostore 머리와 같은 까닭).

        status    off(꺼짐) · not_started · running · done · partial · failed
        chapters  [{no, state, figures: [{kind: photo|illustration, url, after_paragraph, width, height, ai_generated, caption}]}]
    """
    if not doc:
        return {"status": "not_started" if enabled() else "off", "automatic": True, "chapters": []}
    chapters = []
    for key, ch in sorted(doc.get("chapters", {}).items(), key=lambda x: int(x[0])):
        figs = [{"kind": "photo", "url": f"/api/photos/{p['photo_id']}", "after_paragraph": p.get("after_paragraph"),
                 "width": p.get("width"), "height": p.get("height"), "ai_generated": False, "caption": None}
                for p in ch.get("photos") or []] if ch.get("state") == PHOTO else []
        img = ch.get("image") or {}
        if ch.get("state") == ILLUSTRATED and img.get("storage_key"):
            figs.append({"kind": "illustration",
                         "url": f"/api/memoirs/saved/{memoir_id}/illustrations/{key}?v={img['sha256'][:12]}",
                         "after_paragraph": (ch.get("insertion") or {}).get("after_paragraph"),
                         "width": img.get("width"), "height": img.get("height"), "ai_generated": True,
                         "caption": "AI가 그린 그림", "scene_title": (ch.get("select") or {}).get("scene_title")})
        chapters.append({"no": int(key), "state": ch.get("state"), "figures": figs, "failure": ch.get("failure")})
    return {"status": doc.get("status"), "automatic": True, "human_reviewed": False, "chapters": chapters}


def image_record(doc: dict | None, no: str) -> dict | None:
    """그림을 내보낼 때 — 넣은 장의 저장 정보. 없으면 None."""
    ch = (doc or {}).get("chapters", {}).get(str(no)) or {}
    img = ch.get("image") or {}
    return img if ch.get("state") == ILLUSTRATED and img.get("storage_key") else None


def dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, default=str)
