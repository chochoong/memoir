"""
자서전 삽화 — 서비스 연결부 (자서전이 저장되면 저절로 돈다)

    자서전 저장 (memoir_jobs.keep)  →  schedule(memoir_id, user_id)  →  뒤에서 run()

    ① 입력 만들기   build_input   원고(memoir.result) · 원문(회차 기록 → memoir.merge) · 목차별 사진
    ② 목차별 사진   photo_states  사진이 놓인 장은 그 사진을 보이고 삽화를 만들지 않는다 (memoir_illust_book)
    ③ 사진 없는 장  선정 1회 → choose_by(방식) → 그림 1회 → 저장 → 넣을 자리
                    방식 theme(기본 · 목차 주제 삽화 chapter_theme_v2): 장 전체의 주제와 분위기 → 소재 · 구도 → 장의 첫 문단 뒤.
                    뜻은 모델이 판단하고 코드는 응답 모양 · 주제와 소재의 존재만 본다 (낱말 검사로 막지 않는다)
                    방식 scene(앞선 방식 · scene_v5): 한 장면을 원문 그대로 재현 → 그 장면의 문단 뒤
    ④ 상태 · 그림   memoir.illustrations (017) · 그림 바이트는 사진과 같은 저장소(photostore)

**삽화는 자서전 작업과 따로 돈다.** 자서전 작업은 저장까지 끝나면 done 이고, 삽화가 실패해도 본문은
그대로 열린다. 상태는 memoir.illustrations 에만 적는다 — memoir.result(원고)는 건드리지 않는다.

**사진은 회차에 붙은 사진(session.photo_id)이다** (2026-11-24 고침). 그 회차 말씀이 쓰인 장이 하나면 그 장, 여럿이면 **그 회차의
서로 다른 원문 턴을 가장 많이 쓴 장**(같으면 그 회차의 가장 앞선 턴을 쓴 장, 그래도 같으면 앞 장) 한 곳에 놓는다 — 그 장에서 그 회차
말씀이 처음 나오는 문단 뒤. 원문 출처(turns)만 쓰고 AI 로 관련성을 짐작하지 않는다. 같은 사진을 서로 다른 회차가 썼으면 회차마다
따로 놓는다(같은 장이면 한 번만 보인다). 어느 장에도 쓰이지 않은 회차의 사진 · 찾을 수 없는 사진은 놓지 않고 까닭을 남긴다
(unplaced_photos · 화면 응답에도). 그때 그 사진이 갈 수 있었던 장(못 쓰는 사진의 대표 장 · 출처가 없는 장)은 사진이 없다고 단정하지
않는다 — 「모름」 이라 AI 삽화를 만들지 않는다. 그 밖의 장은 「사진 없음 확인」 이다 (책에 사진이 있다고 다른 장의 삽화를 끄지 않는다).
앞서(2026-11-16 ~ 11-23) 규칙은 「한 장에만 쓰였을 때만」 놓아, 여러 장에 걸친 회차의 사진이 빠지고 그 장들에 AI 삽화가 들어갔다.

**다시 부르지 않는다.** 장면 선정과 그림은 장마다 한 번이다. 부르기 **전에** 「불렀다」 를 DB 에 적고, 결과를 적지 못한 채
멈췄으면(서버 재시작) 다음에 그 장을 실패로 남긴다 — 다시 부르지 않는다. 실패 · 보류도 저절로 다시 하지 않는다.
그림이 이미 저장된 장은 넣을 자리만 다시 정한다. 같은 책을 두 번 돌려도 그림은 장마다 한 장이다.

**방식이 바뀌면.** 장마다 그 장을 처리한 방식(policy_id) · 지시문 해시를 적는다 — 앞선 방식의 결과를 새 방식의 결과처럼 보이지 않는다.
앞선 판으로 실패한 장은 저절로 다시 하지 않는다. 운영자가 장을 이름 대서(tools/memoir_illust_reprocess.py --chapter N)
prepare_reprocess 가 그 장만 「지금 판으로 다시」 로 표시하고(앞선 기록은 그 장의 history 에 남긴다), 서버가 그 책을 다음에
열 때 그 장들만 처리한다. 지금 판으로 이미 부른 장은 다시 부르지 않는다. 사진 장 · 이미 넣은 삽화는 건드리지 않는다.

**사람이 확인한 것이 아니다.** automatic: true · human_reviewed: false 로 적는다. 화면에는 「AI 가 그린 그림」 으로 보인다.

**삽화 그림체는 책마다 하나다 (2026-11-25).** 자서전을 만들 때 화면이 보낸 illust_style(watercolor 수채화 · anime
애니풍 · oil_painting 유화, 없으면 수채화)을 schedule → run 이 책 기록(doc.art_style)에 적고, 그 책의 모든 AI 삽화를 그
그림체로 그린다. **다시 처리해도 책에 적힌 그림체를 쓴다** — 그림체 칸이 없는 책(그림체를 고르기 전에 만든 책)은 수채화다.
장마다 선정 기록(select.art_style · art_style_hash)과 그림 기록(image.art_style · style_id)에도 남는다. 이미 저장한 그림은
그림체가 무엇이든 다시 그리지 않는다. 사진 장은 그림체와 상관없이 원본 사진이다. 문체(memoir.style)와는 따로다.
연필담채화(pencil_wash)는 11-25 에 선택지에서 뺐다 — 새 책은 고를 수 없고(400), 이미 그 그림체로 만든 책은 그대로 보이고
저장된 그림을 다시 쓰며 남은 장도 같은 그림체로 이어서 그린다. 애니풍으로 이름을 바꾸거나 다시 그리지 않는다.

설정 (환경변수 — 함수 안에서 읽는다)

    MEMOIR_ILLUST                auto(기본) · off.  auto 는 GEMINI_API_KEY 가 있을 때만 돈다
    MEMOIR_ILLUST_POLICY         theme(기본 · 목차 주제 삽화) · scene(장면 재현)
    MEMOIR_ILLUST_SELECT_MODEL   선정 모델 (기본 gemini-3.5-flash-lite)
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

from . import memoir, memoir_illust as il, memoir_illust_book as book, memoir_illust_theme as th, photostore, store
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


def policy() -> str:
    """삽화를 고르는 방식 — theme(기본 · 목차 주제 삽화) · scene(장면 재현, 앞선 방식). 모르는 값이면 멈춘다."""
    return book.check_policy(env_str("MEMOIR_ILLUST_POLICY", book.DEFAULT_POLICY).strip().lower() or book.DEFAULT_POLICY)


def settings(pol: str | None = None, art_style: str | None = None) -> dict:
    """지금 쓰는 모델 · 그림 설정과 방식(지시문 · 양식 · 그림체 파일과 해시). 결과에 남겨 어느 방식의 결과인지 가린다."""
    return {"select_model": env_str("MEMOIR_ILLUST_SELECT_MODEL", DEFAULT_SELECT_MODEL),
            "image_model": env_str("MEMOIR_ILLUST_IMAGE_MODEL", DEFAULT_IMAGE_MODEL),
            "size": IMAGE_SIZE, "aspect": IMAGE_ASPECT, **book.policy_files(pol or policy(), art_style)}


# 삽화 그림체 (memoir_illust_theme) — 라우트 · 작업은 이 이름으로 부른다
ART_STYLES, DEFAULT_ART_STYLE = th.ART_STYLES, th.DEFAULT_ART_STYLE
UnsupportedArtStyle, pick_art_style = th.UnsupportedArtStyle, th.pick_art_style
ART_STYLE_CODE, ART_STYLE_SAYS = th.ART_STYLE_CODE, th.ART_STYLE_SAYS


def book_art_style(doc: dict | None, requested: str | None = None) -> str:
    """
    그 책의 그림체. **기록이 있는 책은 기록이 정한다** — 다시 처리 · 이어서 처리해도 같은 그림체이고, 그림체 칸이 없는 앞선 책
    (그림체를 고르기 전에 만든 책)은 수채화다. requested(화면이 고른 값)는 기록이 없는 새 책에만 쓴다 — 없으면 수채화.
    모르는 값은 UnsupportedArtStyle — 다른 그림체로 바꿔 그리지 않는다. 기록의 그림체가 지금은 고를 수 없는 것(연필담채화)이어도
    그 책은 그 그림체 그대로다 — requested 로 덮지 않는다.
    """
    if doc:
        return th.stored_art_style(doc.get("art_style"))
    return th.pick_art_style(requested)


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

# 사진을 놓지 못한 까닭 — 화면 응답(unplaced_photos)에도 나간다
UNPLACED_DETAIL = {
    "session_not_cited": "이 회차의 말씀이 자서전 어느 장에도 출처로 쓰이지 않았다 — 어느 장에 놓을지 근거가 없어 놓지 않았다",
    "photo_missing": "회차에 적힌 사진을 찾을 수 없다 — 사진이 지워졌거나 잘못된 사진 번호다",
    "photo_not_owned": "회차에 적힌 사진이 이 계정의 사진이 아니다",
    "photo_not_stored": "사진이 아직 저장되지 않았다 (올리는 중이었거나 실패했다)",
}
UNAVAILABLE = ("photo_missing", "photo_not_owned", "photo_not_stored")
NOT_CITED_WHY = {
    "memoir_has_no_sources": "자서전 문장에 출처(원문 턴)가 하나도 없다 — 집필 · 편집 과정에서 출처가 빠졌을 수 있다",
    "session_turns_not_cited": "자서전은 다른 회차의 말씀을 출처로 쓰지만 이 회차의 말씀은 쓰지 않았다 — 이 회차 내용이 빠졌다",
    "session_has_no_utterances": "이 회차에 자서전 재료가 된 말씀이 없다",
}


def session_usage(chapters: list[dict], turn_map: list[dict]) -> dict[str, dict[int, dict]]:
    """
    회차마다 장별로 쓰인 **서로 다른** 원문 턴과 그 회차 말씀이 처음 나오는 문단. 같은 턴을 여러 문장이 인용해도 한 번만 센다.
        {session_id: {장 번호: {"turns": {전역 턴, …}, "first_para": 문단 번호 | None}}}
    장 단위 출처(source_turns — 문장마다 출처가 없는 원고)도 그 장의 턴으로 센다 (문단은 모른다).
    """
    sid_of = {m["global_turn"]: m["session_id"] for m in turn_map}
    out: dict[str, dict[int, dict]] = {}
    for ch in chapters:
        for pi, para in enumerate(ch.get("paragraphs") or []):
            for x in para.get("sentences") or []:
                for g in x.get("turns") or []:
                    if g in sid_of:
                        u = out.setdefault(sid_of[g], {}).setdefault(ch["no"], {"turns": set(), "first_para": None})
                        u["turns"].add(g)
                        u["first_para"] = pi if u["first_para"] is None else min(u["first_para"], pi)
        for g in ch.get("source_turns") or []:
            if g in sid_of:
                out.setdefault(sid_of[g], {}).setdefault(ch["no"], {"turns": set(), "first_para": None})["turns"].add(g)
    return out


def representative_chapter(usage: dict[int, dict]) -> tuple[int, dict]:
    """
    회차 사진을 놓을 대표 장 — 원문 출처만으로 정한다 (AI 로 관련성을 짐작하지 않는다).
        ① 그 회차의 서로 다른 원문 턴을 가장 많이 쓴 장
        ② 같으면 그 회차의 가장 앞선 원문 턴을 쓴 장 (회차의 첫 이야기가 나오는 장)
        ③ 그래도 같으면 장 번호가 작은 장
    """
    no = min(usage, key=lambda n: (-len(usage[n]["turns"]), min(usage[n]["turns"]), n))
    rule = "single_chapter" if len(usage) == 1 else "most_distinct_turns"
    return no, {"rule": rule, "chapters": {str(n): len(u["turns"]) for n, u in sorted(usage.items())}}


def place_session_photos(chapters: list[dict], turn_map: list[dict], photos: dict[str, dict],
                         unavailable: dict[str, dict] | None = None, utterances: list[dict] | None = None) -> tuple[dict, list[dict]]:
    """
    회차 사진 → 장. {장 번호: [사진]} 과 놓지 않은 사진 목록.

    photos 는 {session_id: 사진 행}(쓸 수 있는 사진), unavailable 은 {session_id: {photo_id, reason}}(회차에 적혔지만 못 쓰는 사진).
    - 그 회차 말씀이 쓰인 장이 하나면 그 장, 여럿이면 대표 장(representative_chapter) 한 곳에 놓는다. 자리는 그 장에서 그 회차 말씀이
      처음 나오는 문단 뒤다 (모르면 장 머리).
    - **같은 사진을 서로 다른 회차가 썼으면 회차마다 따로 놓는다** — 파일이 같다고 빼지 않는다. 같은 장에 같은 사진이 두 번 놓이면
      한 번만 보이고, 두 회차의 연결은 sessions 에 함께 남긴다.
    - 어느 장에도 쓰이지 않은 회차의 사진은 놓지 않는다(session_not_cited) — 첫 장 같은 데 억지로 놓지 않고 까닭을 남긴다.
    - 못 쓰는 사진도 대표 장을 적어 둔다 — 그 장은 사진이 없다고 단정하지 않는다(build_input 의 「모름」).
    """
    usage = session_usage(chapters, turn_map)
    any_cited = any(usage.values())
    said = {}
    for u in utterances or []:
        said[u["session_id"]] = said.get(u["session_id"], 0) + 1
    placed: dict[int, list[dict]] = {}
    unplaced = []
    for sid, p in photos.items():
        base = {"photo_id": p["photo_id"], "session_id": sid}
        if not usage.get(sid):
            why = ("session_has_no_utterances" if utterances is not None and not said.get(sid)
                   else "session_turns_not_cited" if any_cited else "memoir_has_no_sources")
            unplaced.append({**base, "reason": "session_not_cited", "diagnosis": why, "chapters": []})
            continue
        no, basis = representative_chapter(usage[sid])
        first = usage[sid][no]["first_para"]
        row = next((x for x in placed.get(no, []) if x["photo_id"] == p["photo_id"]), None)
        if row is not None:                                   # 같은 장 · 같은 사진 — 한 번만 보이고 두 회차의 연결은 남긴다
            row["sessions"].append(sid)
            if first is not None and (row["after_paragraph"] is None or first < row["after_paragraph"]):
                row["after_paragraph"] = first
            continue
        placed.setdefault(no, []).append({**base, "sessions": [sid], "after_paragraph": first, "width": p.get("width"),
                                          "height": p.get("height"), "url": f"/api/photos/{p['photo_id']}", "placement": basis})
    for sid, miss in (unavailable or {}).items():
        no = representative_chapter(usage[sid])[0] if usage.get(sid) else None
        unplaced.append({"photo_id": miss["photo_id"], "session_id": sid, "reason": miss["reason"],
                         "chapters": sorted(usage.get(sid, {})), "chapter": no})
    for rows in placed.values():                              # 한 장 안에서는 문단 순서대로 (같은 문단이면 회차 순서)
        rows.sort(key=lambda x: (x["after_paragraph"] if x["after_paragraph"] is not None else -1))
    return placed, unplaced


def uncertain_chapters(chapters: list[dict], placed: dict, unplaced: list[dict]) -> dict[int, str]:
    """
    사진이 없다고 단정할 수 없는 장 — 그 장에는 AI 삽화를 만들지 않는다 (사진 상태 「모름」). {장 번호: 까닭}
        못 쓰는 사진(photo_missing · photo_not_owned · photo_not_stored)의 대표 장 — 사용자가 사진을 붙인 이야기의 장이다
        어느 장에도 쓰이지 않은 회차 사진이 있을 때, 문장에 출처가 하나도 없는 장 — 그 사진이 갈 장일 수 있다
    사진이 실제로 놓인 장은 「사진 있음」 이 먼저다. 출처가 있는 다른 장은 그대로 — 책에 사진이 있다고 다른 장의 삽화를 끄지 않는다.
    """
    out: dict[int, str] = {}
    for u in unplaced:
        if u["reason"] in UNAVAILABLE and u.get("chapter") is not None and u["chapter"] not in placed:
            out[u["chapter"]] = u["reason"]
    if any(u["reason"] == "session_not_cited" for u in unplaced):
        for ch in chapters:
            cites = any(x.get("turns") for para in ch.get("paragraphs") or [] for x in para.get("sentences") or []) \
                or bool(ch.get("source_turns"))
            if not cites and ch["no"] not in placed:
                out.setdefault(ch["no"], "chapter_without_sources")
    return out


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
    unavailable: dict[str, dict] = {}
    for r in recs:
        if not r.get("photo_id"):
            continue
        p = await store.load_photo(r["photo_id"])
        why = ("photo_missing" if p is None else "photo_not_owned" if p["user_id"] != user_id
               else "photo_not_stored" if p["status"] != "stored" else None)
        if why:                                               # 회차에 사진이 적혔는데 못 쓴다 — 조용히 빼지 않고 까닭을 남긴다
            unavailable[r["session_id"]] = {"photo_id": str(r["photo_id"]), "reason": why}
        else:
            photos[r["session_id"]] = p
    chapters = copy.deepcopy(result.get("chapters") or [])
    placed, unplaced = place_session_photos(chapters, turn_map, photos, unavailable, src["utterances"])
    unsure = uncertain_chapters(chapters, placed, unplaced)
    for ch in chapters:
        if ch["no"] in placed:
            ch["photos"] = placed[ch["no"]]
        elif ch["no"] not in unsure:
            ch["photos"] = []                                 # 사진이 없는 것이 확인된 장
        # unsure 인 장은 photos 칸을 두지 않는다 → photo_states 가 「모름」 으로 본다 (AI 삽화를 만들지 않는다)
    data = {"schema_version": il.INPUT_SCHEMA,
            "memoir": {"memoir_id": rec["memoir_id"], "style": result.get("style"), "title": result.get("title"),
                       "chapters": chapters},
            "source": {"utterances": src["utterances"], "turn_map": turn_map},
            "photos": [{"photo_id": p["photo_id"], "session_id": sid, "turns": [], "clues": None} for sid, p in photos.items()],
            "photo_placement": {"complete": not unsure,
                                "basis": "회차 사진(session.photo_id)을 그 회차 말씀이 가장 많이 쓰인 장에 놓는 규칙",
                                "uncertain_chapters": {str(k): v for k, v in sorted(unsure.items())}}}
    return data, unplaced


# ---------------------------------------------------------------- 상태 문서

def new_doc(art_style: str | None = None) -> dict:
    art = th.pick_art_style(art_style)
    return {"schema": SCHEMA, "status": RUNNING, "automatic": True, "ai_generated_images": True,
            "human_reviewed": False, "user_selected": False, "user_approved": False, "art_style": art,
            "started_at": _now(), "finished_at": None, "settings": settings(art_style=art),
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


def schedule(memoir_id: str | None, user_id: str, art_style: str | None = None) -> asyncio.Task | None:
    """
    자서전이 저장된 자리(memoir_jobs.keep)에서 부른다. 꺼져 있거나 이미 돌고 있으면 아무것도 하지 않는다.
    art_style 은 새 책의 그림체(화면이 고른 값). 이미 기록이 있는 책은 기록의 그림체를 쓴다 (book_art_style).
    """
    if not memoir_id or not enabled() or running(memoir_id):
        return None
    task = asyncio.create_task(_guarded(memoir_id, user_id, art_style))
    _RUNNING[memoir_id] = task
    task.add_done_callback(lambda t: _RUNNING.pop(memoir_id, None) if _RUNNING.get(memoir_id) is t else None)
    return task


def resume_if_stalled(memoir_id: str, user_id: str, doc: dict | None) -> None:
    """상태가 running 인데 이 서버에서 돌고 있지 않다(재시작) — 남은 장만 이어서 한다. 부른 장은 다시 부르지 않는다."""
    if doc and doc.get("status") == RUNNING and not running(memoir_id):
        schedule(memoir_id, user_id)


# ---------------------------------------------------------------- 방식이 바뀐 뒤 실패한 장만 다시 (기록은 지우지 않는다)

REPROCESS_STATES = (FAILED,)


def _policy_id_of(rec: dict) -> str:
    """그 기록이 쓴 방식. 방식 칸이 없는 기록은 이 변경 전 — 장면 방식(scene_v5)이다."""
    return (rec.get("select") or {}).get("policy_id") or book.POLICY_IDS["scene"]


def reprocess_targets(doc: dict | None, pol: str | None = None, chapters: list[int] | None = None) -> list[dict]:
    """
    다시 처리할 수 있는 장 — **실패한 장 가운데, 지금 판(policy_id)으로는 한 번도 부르지 않은 장**만.
    chapters 를 주면 그 장들 가운데서만 고른다 (운영자가 이름을 댄 장만 — 실패한 장을 모두 저절로 다시 부르지 않는다).
    사진 장 · 이미 넣은 삽화 · 보류 · 사진 정보를 모르는 장은 이름을 대도 건드리지 않는다. 지금 판으로 이미 부른 장도 다시 부르지
    않는다 (실패 기록을 지우거나 옮겨서 「한 번만」 을 비켜 가지 않는다 — 앞선 기록은 history 에 그대로 남는다).
    판이 바뀌면(chapter_theme_v1 → v2) 앞선 판으로 실패한 장은 새 판으로 한 번 다시 할 수 있다.
    """
    pid = book.POLICY_IDS[book.check_policy(pol or policy())]
    want = None if chapters is None else {int(c) for c in chapters}
    out = []
    for key, ch in sorted(((doc or {}).get("chapters") or {}).items(), key=lambda x: int(x[0])):
        if want is not None and int(key) not in want:
            continue
        if ch.get("state") not in REPROCESS_STATES:
            continue
        tried = [_policy_id_of(r) for r in [ch, *(ch.get("history") or [])] if r.get("select") or r.get("image")]
        if pid in tried:
            continue
        out.append({"no": int(key), "title": ch.get("title"), "state": ch.get("state"), "failure": ch.get("failure"),
                    "from_policy": _policy_id_of(ch), "to_policy": pid})
    return out


def refused_chapters(doc: dict | None, chapters: list[int], pol: str | None = None) -> list[dict]:
    """이름을 댔지만 다시 처리하지 않는 장과 그 까닭 — 운영자 도구가 보여 준다."""
    pid = book.POLICY_IDS[book.check_policy(pol or policy())]
    out = []
    for c in chapters:
        ch = ((doc or {}).get("chapters") or {}).get(str(c))
        if ch is None:
            why = "그 장의 기록이 없다"
        elif ch.get("state") not in REPROCESS_STATES:
            why = f"실패한 장이 아니다 (state={ch.get('state')}) — 건드리지 않는다"
        elif pid in [_policy_id_of(r) for r in [ch, *(ch.get("history") or [])] if r.get("select") or r.get("image")]:
            why = f"지금 판({pid})으로 이미 불렀다 — 다시 부르지 않는다"
        else:
            continue
        out.append({"no": int(c), "why": why})
    return out


async def prepare_reprocess(memoir_id: str, user_id: str, pol: str | None = None, chapters: list[int] | None = None) -> dict:
    """
    이름을 댄 실패 장을 지금 판으로 다시 처리하도록 표시만 한다 — 모델 · 그림을 부르지 않는다. 앞선 기록은 그 장의 history 에 옮겨 둔다.
    chapters 가 없으면 아무것도 하지 않는다 (모든 실패 장을 저절로 다시 부르지 않는다).
    책 상태를 running 으로 두므로, 서버가 그 책을 다음에 열 때(resume_if_stalled) 그 장들만 이어서 처리한다 — 장마다 선정 1회 · 그림 1회.
    """
    pol = book.check_policy(pol or policy())
    if not chapters:
        return {"memoir_id": memoir_id, "found": None, "targets": [], "changed": False, "refused": "chapters_required"}
    rec = await store.load_memoir(memoir_id, user_id)
    if rec is None:
        return {"memoir_id": memoir_id, "found": False, "targets": [], "changed": False}
    doc = rec.get("illustrations")
    targets = reprocess_targets(doc, pol, chapters)
    refused = refused_chapters(doc, chapters, pol)
    if not targets:
        return {"memoir_id": memoir_id, "found": True, "targets": [], "changed": False, "refused_chapters": refused}
    for t in targets:
        ch = doc["chapters"][str(t["no"])]
        archived = {**{k: ch.get(k) for k in ("state", "failure", "policy", "select", "image", "insertion", "reason")},
                    "policy_id": t["from_policy"], "archived_at": _now(), "why": "policy_change"}
        doc["chapters"][str(t["no"])] = {"no": ch.get("no", t["no"]), "title": ch.get("title"), "state": PENDING, "policy": pol,
                                         "history": [*(ch.get("history") or []), archived],
                                         "reprocess": {"from_policy": t["from_policy"], "to_policy": t["to_policy"],
                                                       "prepared_at": _now(), "requested_chapters": sorted(int(c) for c in chapters)}}
    doc["status"], doc["finished_at"] = RUNNING, None
    doc.setdefault("reprocess_log", []).append({"at": _now(), "policy_id": book.POLICY_IDS[pol],
                                                "requested": sorted(int(c) for c in chapters), "chapters": [t["no"] for t in targets]})
    await _save(memoir_id, user_id, doc)
    log.info("삽화 %s — %s 로 다시 처리할 장 %s (표시만 · 부르지 않았다)", memoir_id[:10], book.POLICY_IDS[pol],
             [t["no"] for t in targets])
    return {"memoir_id": memoir_id, "found": True, "targets": targets, "changed": True, "refused_chapters": refused,
            "calls_expected": {"select": len(targets), "image": len(targets)}}


async def _guarded(memoir_id: str, user_id: str, art_style: str | None = None) -> None:
    try:
        await run(memoir_id, user_id, art_style=art_style)
    except Exception as e:                                    # noqa: BLE001 — 삽화가 서버를 넘어뜨리지 않는다
        log.exception("삽화 %s 예상 못 한 오류 (%s)", memoir_id[:10], type(e).__name__)


async def _save(memoir_id: str, user_id: str, doc: dict) -> None:
    await store.save_memoir_illustrations(memoir_id, user_id, doc)


def apply_photo_state(ch: dict, ph: dict) -> str | None:
    """
    장 하나에 사진 상태를 얹는다. 바뀐 것을 돌려준다 (없으면 None). **모델 · 그림을 부르지 않는다.**
        사진 있음    → photo. 앞서 AI 삽화를 넣은 장이면 그 그림 기록은 지우지 않고 남긴다 — 화면에는 사진이 먼저다
        모름         → 아직 처리하지 않은 장 · 사진 장이었던 장은 photo_unknown (AI 삽화를 만들지 않는다).
                       이미 넣은 AI 삽화 · 실패 · 보류 기록은 그대로 둔다 — 다시 계산했다고 있던 결과를 지우지 않는다
        사진 없음    → 사진 장이었는데 이제 사진이 없으면 photo_unknown(사진이 사라졌다 · 다시 부르지 않는다). 그 밖에는 그대로
    """
    before = ch.get("state")
    ch["photo_state"], ch["photo_basis"] = ph["state"], ph["basis"]
    ch["photos"] = [{k: p.get(k) for k in ("photo_id", "after_paragraph", "width", "height", "sessions")} for p in ph["photos"]]
    if ph["state"] == "has_photo":
        if before == ILLUSTRATED:
            ch["photo_over_illustration"] = {"at": _now(), "image_kept": True}
        ch["state"], ch["reason"], ch["failure"] = PHOTO, "이 장에 사진이 있다 — 삽화를 넣지 않는다", None
    elif ph["state"] == "unknown":
        if before in (None, PENDING, PHOTO, UNKNOWN):
            ch["state"], ch["failure"] = UNKNOWN, ["photo_info_missing"]
    elif before == PHOTO:
        ch["state"], ch["failure"] = UNKNOWN, ["photo_missing"]
    return None if ch.get("state") == before else f"{before} → {ch.get('state')}"


async def refresh_photos(memoir_id: str, user_id: str, apply: bool = False) -> dict:
    """
    이미 만든 자서전의 사진 배치만 지금 규칙으로 다시 계산한다 — **모델 · 그림을 부르지 않고**, 책 상태를 running 으로 두지 않는다.
    사진이 새로 놓이는 장은 photo 로 바뀐다(앞서 넣은 AI 삽화 기록은 지우지 않는다). 새로 그림을 만들 장은 생기지 않는다.
    apply=False 면 바뀔 것만 보여 준다.
    """
    rec = await store.load_memoir(memoir_id, user_id)
    if rec is None:
        return {"memoir_id": memoir_id, "found": False}
    doc = copy.deepcopy(rec.get("illustrations"))
    if not doc or not doc.get("chapters"):
        return {"memoir_id": memoir_id, "found": True, "changes": [], "note": "삽화 처리 기록이 없다 — 다시 계산할 것이 없다"}
    data, unplaced = await build_input(rec, user_id)
    states = book.photo_states(data)
    changes = []
    for it in book.toc(data):
        ch = doc["chapters"].get(str(it["no"]))
        if ch is None:
            continue
        old_photos = [x.get("photo_id") for x in ch.get("photos") or []]
        moved = apply_photo_state(ch, states[it["ident"]])
        new_photos = [x.get("photo_id") for x in ch.get("photos") or []]
        if moved or old_photos != new_photos:
            changes.append({"no": it["no"], "state": moved or ch.get("state"), "photos": new_photos,
                            "image_kept": bool((ch.get("image") or {}).get("storage_key")) and ch.get("state") == PHOTO})
    doc["unplaced_photos"] = unplaced
    if apply and (changes or unplaced != (rec.get("illustrations") or {}).get("unplaced_photos")):
        doc.setdefault("photo_refresh_log", []).append({"at": _now(), "changes": changes, "unplaced": len(unplaced)})
        await _save(memoir_id, user_id, doc)
    return {"memoir_id": memoir_id, "found": True, "applied": apply, "changes": changes, "unplaced_photos": unplaced,
            "uncertain_chapters": data["photo_placement"]["uncertain_chapters"], "calls": 0}


async def run(memoir_id: str, user_id: str, *, select_call=None, image_call=None, art_style: str | None = None) -> dict | None:
    """
    한 권을 장마다 처리한다. 장 하나의 실패가 다른 장을 막지 않는다. 상태는 단계마다 DB 에 적는다.
    돌려주는 것은 마지막 상태 문서 (자서전이 없으면 None). art_style 은 새 책의 그림체 — 기록이 있는 책은 기록의 것을 쓴다.
    """
    select_call = select_call or SELECT_CALL
    image_call = image_call or IMAGE_CALL
    rec = await store.load_memoir(memoir_id, user_id)
    if rec is None:
        return None
    result = rec["result"] or {}
    before = rec.get("illustrations")
    doc = before or new_doc()
    doc.setdefault("calls", {"select": 0, "image": 0})
    try:
        art = book_art_style(before, art_style)
    except th.UnsupportedArtStyle:
        doc.update(status=BROKEN, error="art_style_unsupported", finished_at=_now())
        await _save(memoir_id, user_id, doc)
        log.warning("삽화 %s 모르는 그림체 — 처리하지 않는다", memoir_id[:10])
        return doc
    if before is not None and before.get("art_style") in (None, ""):
        doc["art_style_note"] = "그림체를 고르기 전에 만든 책 — 수채화로 본다"
    doc["art_style"] = art
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
    # 새로 부르는 장은 지금 설정(방식 · 지시문)으로 한다. 앞선 설정은 지우지 않고 settings_history 에 남긴다 — 장마다 쓴 방식은
    # 그 장의 select 기록(policy · prompt_hash)에 따로 있다
    cfg = settings(art_style=art)
    if doc.get("settings") and doc["settings"] != cfg:
        doc.setdefault("settings_history", []).append({**doc["settings"], "replaced_at": _now()})
    doc["settings"] = cfg
    for it in items:
        key = str(it["no"])
        ch = doc["chapters"].get(key) or {"no": it["no"], "title": it["title"], "state": PENDING}
        doc["chapters"][key] = ch
        apply_photo_state(ch, photos[it["ident"]])
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
        pol = ch.get("policy") or cfg["policy"]
        art = book_art_style(doc)            # 책에 적힌 그림체 (cfg 의 art_style 은 그 방식이 그리는 것 — 장면 방식은 늘 수채화)
        if book.check_policy(pol) == "scene" and art != book.SCENE_ART_STYLE:
            # 장면 방식은 수채화(그림 양식 v1)만 그린다 — 고른 그림체와 다른 그림을 넣지 않는다. 부르기 전에 멈춘다
            ch.update(state=FAILED, failure=["art_style_not_in_policy"])
            return
        files = book.policy_files(pol, art)
        system, user = book.select_system(pol), book.select_user(data, it["ident"], pol)
        ch["policy"] = pol
        ch["select"] = sel_rec = {"attempted_at": _now(), "model": cfg["select_model"], "policy": pol,
                                  "policy_id": files["policy_id"], "prompt_file": files["select_prompt"],
                                  "prompt_hash": files["select_prompt_hash"], "style_hash": files["style_hash"],
                                  "art_style": files["art_style"], "art_style_hash": files["art_style_hash"],
                                  "checks_version": files["checks_version"]}
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
        selection = await asyncio.to_thread(book.choose_by, pol, data, it["ident"], text, art)
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
    # 그 지시문에 실제로 들어간 그림체 — 그림체를 고르기 전의 선정(주제 v2 양식 · 장면 v1 양식)은 수채화다
    ch["image"] = img_rec = {"attempted_at": _now(), "model": cfg["image_model"], "size": cfg["size"], "aspect": cfg["aspect"],
                             "art_style": selection["prompt"].get("art_style") or th.DEFAULT_ART_STYLE,
                             "style_id": selection["prompt"].get("style_id"),
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

        status     off(꺼짐) · not_started · running · done · partial · failed
        chapters   [{no, state, art_style, figures: [{kind: photo|illustration, url, after_paragraph, width, height, ai_generated,
                     caption, art_style(삽화만)}]}]
        art_style  {id: watercolor | anime | oil_painting, label: 수채화 | 애니풍 | 유화} — 그 책의 그림체
    """
    if not doc:
        return {"status": "not_started" if enabled() else "off", "automatic": True, "chapters": []}
    chapters = []
    for key, ch in sorted(doc.get("chapters", {}).items(), key=lambda x: int(x[0])):
        figs = [{"kind": "photo", "url": f"/api/photos/{p['photo_id']}", "after_paragraph": p.get("after_paragraph"),
                 "width": p.get("width"), "height": p.get("height"), "ai_generated": False, "caption": None}
                for p in ch.get("photos") or []] if ch.get("state") == PHOTO else []
        img = ch.get("image") or {}
        # 그 장 그림의 그림체 — 그림 기록에 없으면(그림체를 고르기 전의 그림) 수채화. 그림을 부르지 않은 장은 None
        drawn_style = (img.get("art_style") or th.DEFAULT_ART_STYLE) if img.get("storage_key") else None
        if ch.get("state") == ILLUSTRATED and img.get("storage_key"):
            figs.append({"kind": "illustration",
                         "url": f"/api/memoirs/saved/{memoir_id}/illustrations/{key}?v={img['sha256'][:12]}",
                         "after_paragraph": (ch.get("insertion") or {}).get("after_paragraph"),
                         "width": img.get("width"), "height": img.get("height"), "ai_generated": True,
                         "caption": "AI가 그린 그림", "scene_title": (ch.get("select") or {}).get("scene_title"),
                         "art_style": drawn_style})
        chapters.append({"no": int(key), "state": ch.get("state"), "figures": figs, "failure": ch.get("failure"),
                         "photo_state": ch.get("photo_state"), "art_style": drawn_style,
                         # 그 장의 그림을 고른 방식 — 앞선 방식의 결과를 새 방식의 결과처럼 보이지 않게 함께 낸다
                         "policy": _policy_id_of(ch) if ch.get("select") else None})
    # 회차에 붙였지만 어느 장에도 놓지 못한 사진 — 조용히 사라지지 않게 까닭과 함께 낸다 (화면이 따로 보여 줄 수 있다)
    unplaced = [{"photo_id": u.get("photo_id"), "session_id": u.get("session_id"), "reason": u.get("reason"),
                 "diagnosis": u.get("diagnosis"), "chapters": u.get("chapters") or [],
                 "detail": UNPLACED_DETAIL.get(u.get("reason"), u.get("reason")),
                 "url": f"/api/photos/{u['photo_id']}" if u.get("reason") not in UNAVAILABLE and u.get("photo_id") else None}
                for u in doc.get("unplaced_photos") or []]
    art = doc.get("art_style") or th.DEFAULT_ART_STYLE                # 그림체 칸이 없는 책은 수채화
    return {"status": doc.get("status"), "automatic": True, "human_reviewed": False,
            "policy": (doc.get("settings") or {}).get("policy_id") or book.POLICY_IDS["scene"], "chapters": chapters,
            "unplaced_photos": unplaced,
            "art_style": {"id": art, "label": (th.KNOWN_ART_STYLES.get(art) or {}).get("label")}}


def image_record(doc: dict | None, no: str) -> dict | None:
    """그림을 내보낼 때 — 넣은 장의 저장 정보. 없으면 None."""
    ch = (doc or {}).get("chapters", {}).get(str(no)) or {}
    img = ch.get("image") or {}
    return img if ch.get("state") == ILLUSTRATED and img.get("storage_key") else None


def dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, default=str)
