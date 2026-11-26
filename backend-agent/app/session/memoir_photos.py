"""
완성된 자서전의 사진 — 사용자가 넣고 · 옮기고 · 뺀다 (2026-11-25 업무지시서 「자서전 사진 추가·이동·삭제」).

**사용자가 고른 자리가 자동 배치보다 언제나 먼저다.** 자동 배치(memoir_illust_service.place_session_photos 의 결과,
memoir.illustrations)는 재처리 때 통째로 다시 적히므로, 사용자의 선택은 따로 둔다 (018 memoir_photo_placement).
화면에 낼 때 자동 배치 위에 그 선택을 얹는다 — merged_view.

    manual  사용자가 넣은 사진. placement_id = p_…. 빼면 행을 지운다.
    auto    자동으로 놓인 회차 사진. placement_id = a_… — (사진, 회차)로 정해지는 고정값이라 재처리 뒤에도 같은 사진이다.
            옮기면 그 자리를, 빼면 hidden 을 남긴다 (행을 지우면 재처리 때 다시 나타난다).

지키는 것
  - 모델 · 그림 호출 없음. 넣은 사진도 분석(photo.analyze_later)하지 않는다 — 책에 넣는 사진은 질문에 쓰지 않는다.
  - 원고(result) · 자동 배치 문서(illustrations) · 엽서 · 사진 파일을 고치지 않는다.
  - 자리: chapter_no 는 원고에 있는 장, after_paragraph 는 그 장 문단 번호(0부터, 화면 srv-memoir.mapFigures 와 같은 기준).
  - 같은 문단 뒤 여러 장은 display_order → 만든 순서로 정렬한다 (같은 값이면 언제나 같은 순서).
"""

from __future__ import annotations

import hashlib
import uuid

from . import memoir_illust_service as svc
from .conf import env_int

MAX_PHOTOS_DEFAULT = 30


def max_photos() -> int:
    """책 한 권에 사용자가 넣을 수 있는 사진 수 (manual 만 센다 — 자동 사진은 회차 수만큼이라 따로 묶지 않는다)."""
    return max(1, env_int("MEMOIR_PHOTOS_MAX", MAX_PHOTOS_DEFAULT))


class PlacementError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def auto_id(memoir_id: str, photo_id: str, session_id: str) -> str:
    """
    자동 사진의 배치 id — **책마다 다르다** (같은 인터뷰로 만든 두 책이 서로의 기록을 건드리지 않게).
    처음 만들 때의 회차(anchor)로 정해지고, 그 뒤 회차 묶음이 바뀌어도 id 는 그대로다 (match_auto 참조).
    """
    return "a_" + hashlib.sha256(f"{memoir_id}|{photo_id}|{session_id}".encode()).hexdigest()[:24]


def legacy_auto_id(photo_id: str, session_id: str) -> str:
    """2026-11-25 첫 판의 id (책이 빠져 있었다) — 그때 저장된 기록을 계속 찾기 위해서만 쓴다."""
    return "a_" + hashlib.sha256(f"{photo_id}|{session_id}".encode()).hexdigest()[:24]


def manual_id(memoir_id: str, user_id: str, request_id: str | None = None) -> str:
    """request_id 를 주면 같은 요청을 두 번 보내도 같은 배치다 (중복 요청)."""
    if request_id:
        return "p_" + hashlib.sha256(f"{memoir_id}|{user_id}|{request_id}".encode()).hexdigest()[:24]
    return "p_" + uuid.uuid4().hex[:24]


# ---------------------------------------------------------------- 자리 검사

def paragraph_counts(result: dict | None) -> dict[int, int]:
    """{장 번호: 문단 수} — 원고 그대로."""
    out = {}
    for ch in (result or {}).get("chapters") or []:
        try:
            out[int(ch.get("no"))] = len(ch.get("paragraphs") or [])
        except (TypeError, ValueError):
            continue
    return out


def as_int(v, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, str)):
        raise PlacementError(422, "bad_position", f"{name} 는 숫자여야 해요")
    try:
        return int(v)
    except ValueError:
        raise PlacementError(422, "bad_position", f"{name} 는 숫자여야 해요") from None


def check_position(result: dict | None, chapter_no, after_paragraph) -> tuple[int, int]:
    counts = paragraph_counts(result)
    no, ap = as_int(chapter_no, "chapter_no"), as_int(after_paragraph, "after_paragraph")
    if no not in counts:
        raise PlacementError(422, "no_such_chapter", "그런 장이 없어요")
    if not 0 <= ap < counts[no]:
        raise PlacementError(422, "no_such_paragraph", f"{no}장에는 0~{counts[no] - 1}번 문단만 있어요" if counts[no]
                             else f"{no}장에는 사진을 놓을 문단이 없어요")
    return no, ap


# ---------------------------------------------------------------- 최종 배치

def auto_photos(doc: dict | None, memoir_id: str) -> list[dict]:
    """자동 배치가 화면에 내던 사진 (사진 장의 photos) — 지금까지의 view 와 같은 조건 · 같은 순서."""
    out = []
    for key, ch in sorted(((doc or {}).get("chapters") or {}).items(), key=lambda x: int(x[0])):
        if ch.get("state") != svc.PHOTO:
            continue
        for i, p in enumerate(ch.get("photos") or []):
            sessions = sorted(p.get("sessions") or ([p["session_id"]] if p.get("session_id") else []))
            out.append({"placement_id": auto_id(memoir_id, p["photo_id"], sessions[0] if sessions else ""), "origin": "auto",
                        "photo_id": p["photo_id"], "sessions": sessions, "anchor_session": sessions[0] if sessions else None,
                        "chapter_no": int(key), "after_paragraph": p.get("after_paragraph"),
                        "display_order": i, "width": p.get("width"), "height": p.get("height"), "_seq": (0, "", i)})
    return out


def match_auto(entries: list[dict], rows: list[dict]) -> tuple[dict[int, dict], list[dict]]:
    """
    저장된 자동 사진 기록(auto 행) ↔ 지금의 자동 사진. ({자동 사진 번호: 행}, 짝이 없는 행).

    같은 책 · 같은 사진이고 **회차가 이어지면** 같은 사진으로 본다 — 회차 묶음이 [A, B] → [B] 처럼 바뀌어도
    사용자가 옮긴 자리 · 뺀 상태가 남는다. 한 사진의 자동 사진들은 회차가 서로 겹치지 않으므로(회차 하나는 한 곳에만
    놓인다) 다른 장에 따로 놓인 같은 사진은 함께 숨겨지지 않는다. 짝을 찾는 순서:
        ① 행을 만들 때의 회차(anchor_session)가 들어 있는 자동 사진
        ② 첫 판의 id(legacy_auto_id — 책 없이 (사진, 회차))가 맞는 자동 사진 — 그때 저장된 기록
        ③ 행에 적힌 회차(sessions)와 가장 많이 겹치는 자동 사진
    자동 사진 하나에는 행 하나만 짝짓는다.
    """
    autos = [r for r in rows if r["origin"] == "auto"]
    got: dict[int, dict] = {}
    used: set[str] = set()

    def take(r, pick):
        for i, a in enumerate(entries):
            if i not in got and a["photo_id"] == r["photo_id"] and pick(a):
                got[i] = r
                used.add(r["placement_id"])
                return True
        return False

    for r in autos:
        if r.get("anchor_session"):
            take(r, lambda a, s=r["anchor_session"]: s in a["sessions"])
    for r in autos:
        if r["placement_id"] not in used and not r.get("anchor_session"):
            take(r, lambda a, pid=r["placement_id"]: any(legacy_auto_id(a["photo_id"], s) == pid for s in a["sessions"]))
    for r in autos:
        if r["placement_id"] in used or not r.get("sessions"):
            continue
        mine = set(r["sessions"])
        best = max(((len(mine & set(a["sessions"])), i) for i, a in enumerate(entries)
                    if i not in got and a["photo_id"] == r["photo_id"] and mine & set(a["sessions"])), default=None)
        if best is not None:
            got[best[1]] = r
            used.add(r["placement_id"])
    return got, [r for r in autos if r["placement_id"] not in used]


def final_photos(doc: dict | None, rows: list[dict], memoir_id: str) -> list[dict]:
    """자동 사진 + 사용자 선택 → 지금 책에 보이는 사진 (빠진 것 · 자리 없는 것 제외)."""
    entries = auto_photos(doc, memoir_id)
    got, orphans = match_auto(entries, rows)
    out = []
    for i, a in enumerate(entries):
        r = got.get(i)
        if r is None:                                           # 손대지 않은 자동 사진
            out.append(a)
            continue
        if r.get("hidden"):
            continue
        a = {**a, "placement_id": r["placement_id"], "anchor_session": r.get("anchor_session") or a["anchor_session"]}
        if r.get("chapter_no") is not None:
            a.update(chapter_no=r["chapter_no"], after_paragraph=r.get("after_paragraph"),
                     display_order=r.get("display_order") or 0, edited=True)
        out.append(a)
    shown = {a["photo_id"] for a in entries}
    for r in orphans:
        # 재처리로 자동 배치에서 사라졌어도 사용자가 옮겨 둔 자리는 지킨다 — 같은 사진이 다른 자동 자리로 이미 보이면 겹쳐 내지 않는다
        if not r.get("hidden") and r.get("chapter_no") is not None and r["photo_id"] not in shown:
            out.append({"placement_id": r["placement_id"], "origin": "auto", "photo_id": r["photo_id"],
                        "sessions": r.get("sessions") or [], "anchor_session": r.get("anchor_session"),
                        "chapter_no": r["chapter_no"], "after_paragraph": r.get("after_paragraph"),
                        "display_order": r.get("display_order") or 0, "width": r.get("width"), "height": r.get("height"),
                        "edited": True, "_seq": (1, str(r.get("created_at") or ""), r["placement_id"])})
    for r in rows:
        if r["origin"] != "manual":
            continue
        seq = (1, str(r.get("created_at") or ""), r["placement_id"])
        if not r.get("hidden") and r.get("chapter_no") is not None:
            out.append({"placement_id": r["placement_id"], "origin": "manual", "photo_id": r["photo_id"],
                        "chapter_no": r["chapter_no"], "after_paragraph": r.get("after_paragraph"),
                        "display_order": r.get("display_order") or 0, "width": r.get("width"), "height": r.get("height"),
                        "_seq": seq})
    return sorted(out, key=_order)


def _order(p: dict):
    ap = p.get("after_paragraph")
    return (p["chapter_no"], ap is None, ap if ap is not None else 0, p.get("display_order") or 0, p.get("_seq") or (2, "", 0))


def next_order(photos: list[dict], chapter_no: int, after_paragraph: int, skip: str | None = None) -> int:
    """그 문단 뒤 맨 끝 순서."""
    at = [p.get("display_order") or 0 for p in photos
          if p["chapter_no"] == chapter_no and p.get("after_paragraph") == after_paragraph and p["placement_id"] != skip]
    return max(at) + 1 if at else 0


def _figure(p: dict) -> dict:
    return {"kind": "photo", "url": f"/api/photos/{p['photo_id']}", "after_paragraph": p.get("after_paragraph"),
            "width": p.get("width"), "height": p.get("height"), "ai_generated": False, "caption": None,
            "placement_id": p["placement_id"], "origin": p["origin"], "display_order": p.get("display_order") or 0,
            "photo_id": p["photo_id"]}


def merged_view(memoir_id: str, doc: dict | None, result: dict | None, rows: list[dict]) -> dict:
    """
    memoir_illust_service.view 에 사용자 선택을 얹은 것. 사진이 아닌 그림(AI 삽화)은 그대로 둔다.
    사진 figure 에 placement_id · origin(auto | manual) · display_order · photo_id 가 더해진다 (앞선 칸은 그대로).
    AI 삽화 figure 는 origin = "ai", placement_id = None (이번 범위에서 옮기거나 빼지 않는다).
    """
    v = svc.view(memoir_id, doc)
    photos = final_photos(doc, rows, memoir_id)
    if not rows and not photos:
        return v
    by_no = {c["no"]: c for c in v["chapters"]}
    for c in v["chapters"]:
        c["figures"] = [f for f in c["figures"] if f.get("kind") != "photo"]
        for f in c["figures"]:
            f.setdefault("placement_id", None)
            f.setdefault("origin", "ai")
            f.setdefault("display_order", None)
    known = set(paragraph_counts(result))
    for p in photos:
        no = p["chapter_no"]
        if known and no not in known:                       # 원고에 없는 장 — 낼 자리가 없다
            continue
        c = by_no.get(no)
        if c is None:                                       # 삽화 처리 전 · 삽화가 꺼진 책에도 사용자가 넣은 사진은 보인다
            c = by_no[no] = {"no": no, "state": None, "figures": [], "failure": None, "photo_state": None,
                             "art_style": None, "policy": None}
            v["chapters"].append(c)
        c["figures"].append(_figure(p))
    for c in v["chapters"]:
        # 사진은 정해진 순서로 앞에, 같은 문단의 AI 삽화는 그 뒤에. 화면은 같은 문단의 그림을 배열 순서대로 쌓는다
        photo = [f for f in c["figures"] if f["kind"] == "photo"]
        rest = [f for f in c["figures"] if f["kind"] != "photo"]
        c["figures"] = photo + rest
    v["chapters"].sort(key=lambda c: c["no"])
    placed = {p["photo_id"] for p in photos}
    if v.get("unplaced_photos"):
        v["unplaced_photos"] = [u for u in v["unplaced_photos"] if u.get("photo_id") not in placed]
    return v
