"""
실제 원문 · 원고를 삽화 장면 선정의 입력(illust-input-v1)으로 바꾼다. 모델을 부르지 않는다.

    python tools/memoir_illust_prepare.py --stories "eval/exp/<책>/stories.txt" \
        --book eval/exp/<책>/book.json --manuscript eval/exp/<책>/manuscript.md \
        --out eval/exp/<책>/illust_input.json

**받는 자료** (실험 원고 exp/memoir-integrated 의 모양 — 서비스 DB 의 자료가 아니다)

    --stories       번호 붙은 이야기 글. 「N.」 한 줄 뒤에 그 이야기 본문 (1부터 빈틈없이)
    --stories-json  또는 합친 입력 파일 — data.utterances · turn_map 이 든 JSON (그대로 옮긴다)
    --book          book.json — essays[{key, no, title, stories[이야기 번호], paragraphs[...]}]
    --manuscript    (선택) manuscript.md — book.json 의 문단이 이 원고에 그대로 있는지 대조만 한다

**지어내지 않는다.**
- 턴 번호는 이야기 번호 그대로다 (실험 입력이 「이야기 번호 = 전역 턴」 으로 정했다). 새 번호를 매기지 않는다.
- 문장의 출처(turns)는 book.json 에 있을 때만 그대로 옮긴다 (수필체 v3 에는 있고 문학체 v4 에는 없다).
  없으면 비우고, 수필이 아는 이야기 번호만 장의 source_turns 로 싣는다.
- 문단을 문장으로 쪼개지 않는다 (문단이 글 하나면 문장 하나). 장 식별자는 book.json 의 key 그대로다.
- --stories 에는 회차가 없다 → session_id 는 「file:<파일 이름>」 이고 turn_map 을 만들지 않는다.
- 사진 자료가 없다 → photos 는 null(받지 못함)이다. 사진이 정말 없는 책이면 --no-photos 로 빈 목록을 싣는다.
- 원문에 없는 이야기를 쓰는 수필은 뺀다 (몇 편을 뺐는지 알린다) — 원문 일부만 받았을 때다.

**실제 원문이다.** --out 은 eval/exp/ 아래(git 제외)여야 한다. 화면에는 개수만 찍고 본문은 찍지 않는다.

종료 코드: 0 만들었다 / 2 거부
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.session import memoir_illust as il     # noqa: E402

PRIVATE = ROOT / "eval" / "exp"
_HEAD = re.compile(r"(?m)^[ \t]*(\d+)\.?[ \t]*\r?$")


def bad(why: str) -> il.IllustError:
    return il.IllustError("input", why)


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise bad(f"{path.name} 을 읽지 못했다 ({type(e).__name__})") from e


def stories_from_text(text: str, name: str) -> dict:
    """「N.」 머리 줄로 나눈다. 번호가 1부터 차례가 아니면 거부한다 — 맞춰 주지 않는다."""
    parts = _HEAD.split(text)
    nums = [int(n) for n in parts[1::2]]
    bodies = [b.strip() for b in parts[2::2]]
    if not nums or nums != list(range(1, len(nums) + 1)) or not all(bodies):
        raise bad(f"{name} 의 이야기 번호가 1부터 차례가 아니거나 빈 이야기가 있다 (읽은 번호 {nums[:6]}…)")
    return {"utterances": [{"turn": n, "session_id": f"file:{name}", "asked": "", "elder": b}
                           for n, b in zip(nums, bodies)]}


def stories_from_json(doc) -> dict:
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("utterances"), list):
        raise bad("--stories-json 에 data.utterances 가 없다")
    out = {"utterances": [{k: u.get(k) for k in ("turn", "session_id", "asked", "elder")} for u in data["utterances"]]}
    if isinstance(doc.get("turn_map"), list):
        out["turn_map"] = [{k: m.get(k) for k in ("global_turn", "session_id", "turn")} for m in doc["turn_map"]]
    return out


def chapters_from_book(book, known: set[int]) -> tuple[list[dict], list[str]]:
    """수필 → 장. 원문에 없는 이야기를 쓰는 수필은 빼고 그 key 를 돌려준다."""
    essays = book.get("essays") if isinstance(book, dict) else None
    if essays is None and isinstance(book, dict) and isinstance(book.get("parts"), list):
        essays = [e for part in book["parts"] for e in part.get("essays", [])]
    if not isinstance(essays, list) or not essays:
        raise bad("book.json 에 essays 가 없다")
    chapters, dropped = [], []
    for i, e in enumerate(essays, start=1):
        if (not isinstance(e, dict) or not isinstance(e.get("key"), str) or not isinstance(e.get("title"), str)
                or not isinstance(e.get("stories"), list) or not all(isinstance(n, int) for n in e["stories"])
                or not isinstance(e.get("paragraphs"), list) or not e["paragraphs"]):
            raise bad(f"{i}번째 수필 모양이 다르다 (key · title · stories · paragraphs)")
        if not e["stories"] or not set(e["stories"]) <= known:
            dropped.append(e["key"])
            continue
        paras = []
        for para in e["paragraphs"]:
            items = [para] if isinstance(para, str) else para
            if not isinstance(items, list):
                raise bad(f"수필 {e['key']} 의 문단 모양이 다르다")
            sents = []
            for x in items:
                text = x if isinstance(x, str) else x.get("text") if isinstance(x, dict) else None
                turns = x.get("turns", []) if isinstance(x, dict) else []
                if not isinstance(text, str) or not isinstance(turns, list) or not all(isinstance(t, int) for t in turns):
                    raise bad(f"수필 {e['key']} 의 문장 모양이 다르다")
                if not set(turns) <= known:
                    raise bad(f"수필 {e['key']} 의 문장이 원문에 없는 이야기 {sorted(set(turns) - known)} 를 근거로 든다")
                if text.strip():                      # 편집에서 지워져 빈 글이 된 문장은 본문이 아니다
                    sents.append({"text": text.strip(), "turns": sorted(set(turns))})
            if sents:
                paras.append({"sentences": sents})
        if not paras:
            raise bad(f"수필 {e['key']} 에 본문이 없다")
        chapters.append({"no": e.get("no", i), "chapter_key": e["key"], "title": e["title"],
                         "source_turns": sorted(set(e["stories"])), "paragraphs": paras})
    return chapters, dropped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="실제 원문 · 원고 → illust-input-v1 (모델 호출 없음)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--stories", type=Path)
    src.add_argument("--stories-json", type=Path)
    ap.add_argument("--book", required=True, type=Path)
    ap.add_argument("--manuscript", type=Path)
    ap.add_argument("--no-photos", action="store_true", help="사진이 없는 책이다 (photos: [])")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    try:
        if PRIVATE.resolve() not in a.out.resolve().parents:
            raise bad("--out 은 eval/exp/ 아래여야 한다 (실제 원문은 git 제외 경로에만 둔다)")
        try:
            source = (stories_from_text(read(a.stories), a.stories.name) if a.stories
                      else stories_from_json(json.loads(read(a.stories_json))))
            book = json.loads(read(a.book))
        except json.JSONDecodeError as e:
            raise bad(f"JSON 이 아니다 ({e.msg})") from e
        known = {u["turn"] for u in source["utterances"]}
        chapters, dropped = chapters_from_book(book, known)
        if not chapters:
            raise bad("원문으로 덮이는 수필이 하나도 없다 — 원문과 원고가 같은 자료인지 확인한다")
        data = {"schema_version": il.INPUT_SCHEMA, "synthetic": False,
                "note": "실제 원문에서 만든 입력 — git 에 올리지 않는다.",
                "memoir": {"memoir_id": None, "style": None, "title": book.get("title"), "chapters": chapters},
                "source": source, "photos": [] if a.no_photos else None}
        il.check_input(data)

        seen = None
        if a.manuscript:
            flat = re.sub(r"\s+", "", read(a.manuscript))
            paras = [x["text"] for c in chapters for p in c["paragraphs"] for x in p["sentences"]]
            seen = {"paragraphs": len(paras), "found_in_manuscript": sum(1 for t in paras if re.sub(r"\s+", "", t) in flat)}
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except il.IllustError as e:
        print(f"거부 — {e}", file=sys.stderr)
        return 2

    used = {t for c in chapters for t in c["source_turns"]}
    sents_all = [x for c in chapters for p in c["paragraphs"] for x in p["sentences"]]
    print(json.dumps({
        "out": str(a.out), "input_ref": il.input_ref(data), "stories": len(known),
        "chapters": len(chapters), "chapters_dropped_no_source": len(dropped),
        "stories_used_by_chapters": len(used), "stories_unused": len(known - used),
        "sentences": len(sents_all), "sentences_with_turns": sum(1 for x in sents_all if x["turns"]),
        "chapter_level_sources": True,
        "turn_map": "turn_map" in source, "photos": "none([])" if a.no_photos else "not_provided(null)",
        "manuscript_check": seen, "model_called": False}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
