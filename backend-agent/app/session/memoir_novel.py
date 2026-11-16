"""
자서전 소설체 (style=novel) — 태헌 전달 자료 3판 · 다애님 「소설체 최소 수정 v1」

    첨부프롬프트_md/문체/novel/prompt_소설체_최소수정v1.md
    aidlc-docs/construction/unit8-memoir-pipeline/style-handoff/backend_handoff.md

**장 하나 = 회차 하나.** 책장의 「장」 이 회차라서 그대로 맞춘다. 장마다 그 회차의 어르신
말씀을 `{{SOURCE_TEXT}}` 에 끼운 프롬프트 전체를 **사용자 메시지 하나로** 보낸다 (시스템 없음 ·
출력 형식 강제 없음 — 검증 실행이 그랬다). 장들은 동시에 쓴다 (MEMOIR_NOVEL_PARALLEL).

**프롬프트는 파일 그대로 읽는다** (handoff §2) — 공통 지침을 붙이지 않고, 울타리 줄을 지우지
않고, 다듬지 않는다. 바이트로 읽어 UTF-8 로 푼다. 실행 기록에 프롬프트 해시를 남긴다.

**제목은 모델이 내지 않는다.** 장 제목은 그 회차의 엽서 제목(없으면 회차 제목)이다.

**사실 표시가 없다** (handoff §6). 문장의 turns 는 빈 목록이고 검증은 not_run 이다. 따옴표
대사는 창작일 수 있다 — 화면은 초안이라고만 알린다.

같은 회차 · 같은 프롬프트 · 같은 모델이면 앞서 쓴 장을 다시 쓰지 않는다 (메모리 · 서버를 다시
켜면 사라진다). 책에 장이 하나 늘 때마다 책 전체를 다시 다듬기 때문이다.

로그에는 회차 앞 8자 · 토큰 · 시간 · 종료 사유만 남긴다. 원문 · 본문은 남기지 않는다.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

from . import postcard
from .conf import env_float, env_int, env_str

log = logging.getLogger("memoir")

PROMPT = (Path(__file__).resolve().parents[2] / "첨부프롬프트_md" / "문체" / "novel"
          / "prompt_소설체_최소수정v1.md")
PROMPT_SHA256 = "4b05811de3436f4b"          # style_manifest.json 앞 16자리 — 다르면 쓰지 않는다
SLOT = "{{SOURCE_TEXT}}"

# 검증된 조합 (style_manifest.json verified_runs — 한 장 71초 · $0.09)
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_TOKENS = 65536
DEFAULT_TIMEOUT = 300.0
DEFAULT_PARALLEL = 4
BOOK_TITLE = "소설로 엮은 나의 이야기"

# 100만 토큰당 USD (입력, 출력). 모르는 모델은 비용을 적지 않는다
PRICES = {"claude-sonnet-5-5": (2.0, 10.0)}

_CACHE: "OrderedDict[str, str]" = OrderedDict()
_CACHE_MAX = 256


def settings() -> dict:
    return {
        "MEMOIR_NOVEL_MODEL": env_str("MEMOIR_NOVEL_MODEL", DEFAULT_MODEL),
        "MEMOIR_NOVEL_EFFORT": env_str("MEMOIR_NOVEL_EFFORT", DEFAULT_EFFORT),
        "MEMOIR_NOVEL_MAX_TOKENS": env_int("MEMOIR_NOVEL_MAX_TOKENS", DEFAULT_MAX_TOKENS),
        "MEMOIR_NOVEL_TIMEOUT": env_float("MEMOIR_NOVEL_TIMEOUT", DEFAULT_TIMEOUT),
        "MEMOIR_NOVEL_PARALLEL": max(1, env_int("MEMOIR_NOVEL_PARALLEL", DEFAULT_PARALLEL)),
    }


@lru_cache(maxsize=1)
def template() -> tuple[str, str]:
    """(프롬프트 원문, sha256 전체). 파일이 전달본과 다르면 쓰지 않는다."""
    from .memoir import GenerationFailed

    try:
        raw = PROMPT.read_bytes()
    except OSError as e:
        raise GenerationFailed(f"소설체 프롬프트를 읽지 못했다: {PROMPT.name} ({e})") from e
    sha = hashlib.sha256(raw).hexdigest()
    if not sha.startswith(PROMPT_SHA256):
        # 줄바꿈이 CRLF 로 풀렸거나 고쳐졌다 — 검증한 프롬프트가 아니다 (문체/.gitattributes)
        raise GenerationFailed(f"소설체 프롬프트가 전달본과 다르다 (sha256 {sha[:16]})")
    text = raw.decode("utf-8")
    if text.count(SLOT) != 1:
        raise GenerationFailed(f"소설체 프롬프트의 {SLOT} 가 한 군데가 아니다")
    return text, sha


def elder_lines(rec: dict) -> list[str]:
    """그 회차의 어르신 말씀만, 말한 순서대로. 질문(AI)은 넣지 않는다 — 인물로 오해하지 않게."""
    m = postcard.material(rec["fragments"], None, rec.get("closing_decision"))
    return [u["elder"].strip() for u in m["utterances"] if (u.get("elder") or "").strip()]


def source_text(rec: dict) -> str:
    """그 회차의 어르신 말씀만, 말씀 사이는 빈 줄."""
    return "\n\n".join(elder_lines(rec))


def user_message(src: str) -> str:
    text, _ = template()
    return text.replace(SLOT, src)


def chapter_title(rec: dict, no: int) -> str:
    card = rec.get("postcard") or {}
    for t in (card.get("title"), rec.get("title")):
        if isinstance(t, str) and t.strip():
            return t.strip()
    return f"{no}장"


def paragraphs(body: str) -> list[dict]:
    """
    본문 → 응답의 문단. **줄 하나가 문단 하나다** — 대사마다 줄이 바뀌고 장면은 빈 줄로 나뉘는
    소설체의 줄을 합치지 않는다 (input_output_contract §6). 문장으로 쪼개지 않는다.
    """
    return [{"sentences": [{"text": ln.strip(), "turns": []}]} for ln in body.splitlines() if ln.strip()]


async def _call(client, msg: str, s: dict) -> tuple[str, dict]:
    """한 장. (본문, 기록). 정상 완료(end_turn)가 아니면 쓰지 않는다 (handoff §8)."""
    async with client.beta.messages.stream(
        model=s["MEMOIR_NOVEL_MODEL"],
        max_tokens=s["MEMOIR_NOVEL_MAX_TOKENS"],
        output_config={"effort": s["MEMOIR_NOVEL_EFFORT"]},
        # 안전 분류기가 거절하면 같은 요청을 다른 모델이 잇는다 (Sonnet 5.5 권장 — 「default」)
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": msg}],
    ) as stream:
        final = await stream.get_final_message()
    text = "".join(b.text for b in final.content if getattr(b, "type", "") == "text")
    u = final.usage
    rec = {"stop": final.stop_reason, "model": final.model,
           "input": getattr(u, "input_tokens", 0) or 0, "output": getattr(u, "output_tokens", 0) or 0}
    return text, rec


async def run(recs: list[dict], ids: list[str], style: str, progress=None) -> dict:
    """collect 를 지난 회차로 소설체 책 한 권. 응답은 pipeline_result 와 같은 7-C1 장 모양이다."""
    from .memoir import (READY, GenerationFailed, GenerationTimeout, Incomplete, SourceUnavailable,
                         inject, INJECT_FAILED, INJECT_TIMEOUT)

    hook = inject()
    if hook == INJECT_FAILED:
        raise GenerationFailed("MEMOIR_FAIL_INJECT=generation_failed")
    if hook == INJECT_TIMEOUT:
        raise GenerationTimeout("MEMOIR_FAIL_INJECT=generation_timeout")

    order = sorted(recs, key=lambda r: r["created_at"])
    if len({r["created_at"] for r in order}) != len(order):
        raise SourceUnavailable("시작 시각이 같은 회차가 있어 기록 순서를 정할 수 없다")
    _, sha = template()
    s = settings()
    key_api = env_str("ANTHROPIC_API_KEY", "")
    if not key_api:
        raise GenerationFailed("ANTHROPIC_API_KEY 가 없다 — 소설체는 Claude 로 쓴다")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=key_api, max_retries=1)
    n = len(order)
    gate = asyncio.Semaphore(s["MEMOIR_NOVEL_PARALLEL"])
    done = 0
    t0 = time.monotonic()
    log.info("자서전 소설체 요청 — 회차 %d개 %s · 모델 %s · 프롬프트 %s",
             n, ",".join(r["session_id"][:8] for r in order), s["MEMOIR_NOVEL_MODEL"], sha[:16])
    if progress is not None:
        progress("chapter", 1, n)

    async def one(no: int, rec: dict) -> dict:
        nonlocal done
        sid = rec["session_id"]
        msg = user_message(source_text(rec))
        key = hashlib.sha256(f"{s['MEMOIR_NOVEL_MODEL']}|{s['MEMOIR_NOVEL_EFFORT']}|{msg}".encode()).hexdigest()
        out: dict = {"no": no, "title": chapter_title(rec, no), "sid": sid}
        if key in _CACHE:
            _CACHE.move_to_end(key)
            out.update(body=_CACHE[key], cached=True)
        else:
            async with gate:
                t = time.monotonic()
                try:
                    body, r = await asyncio.wait_for(_call(client, msg, s), s["MEMOIR_NOVEL_TIMEOUT"])
                except asyncio.TimeoutError:
                    out["fail"] = "generation_timeout"
                    log.warning("소설체 %d장 %s — %.0f초 안에 오지 않았다", no, sid[:8], s["MEMOIR_NOVEL_TIMEOUT"])
                except Exception as e:                       # noqa: BLE001
                    out["fail"] = "generation_failed"
                    log.warning("소설체 %d장 %s — 호출 실패 %s: %s", no, sid[:8], type(e).__name__, str(e)[:160])
                else:
                    log.info("소설체 %d장 %s — %s · %.1f초 · 입력 %d · 출력 %d · %s",
                             no, sid[:8], r["stop"], time.monotonic() - t, r["input"], r["output"], r["model"])
                    out["usage"] = r
                    if r["stop"] != "end_turn" or not body.strip():
                        out["fail"] = "generation_failed"
                    else:
                        out["body"] = body
                        _CACHE[key] = body
                        while len(_CACHE) > _CACHE_MAX:
                            _CACHE.popitem(last=False)
        done += 1
        if progress is not None and done < n:
            progress("chapter", done + 1, n)
        return out

    try:
        res = await asyncio.gather(*(one(i, r) for i, r in enumerate(order, start=1)))
    finally:
        await client.close()

    tin = sum(x.get("usage", {}).get("input", 0) for x in res)
    tout = sum(x.get("usage", {}).get("output", 0) for x in res)
    price = PRICES.get(s["MEMOIR_NOVEL_MODEL"])
    log.info("자서전 소설체 응답 — %.1f초 · 장 %d (다시 씀 %d · 앞서 쓴 것 %d · 실패 %d) · 입력 %d · 출력 %d · 비용 %s",
             time.monotonic() - t0, n, sum(1 for x in res if "usage" in x), sum(1 for x in res if x.get("cached")),
             sum(1 for x in res if "fail" in x), tin, tout,
             f"약 ${(tin * price[0] + tout * price[1]) / 1e6:.3f}" if price else "단가 모름")

    failed = [x for x in res if "fail" in x]
    if failed:
        why = " · ".join(f"{x['no']}장 {x['fail']}" for x in failed)
        if len(failed) < n:
            raise Incomplete(f"partial — 소설체 {why}")
        if all(x["fail"] == "generation_timeout" for x in failed):
            raise GenerationTimeout(f"소설체 {why}")
        raise GenerationFailed(f"소설체 {why}")

    chapters = [{"no": x["no"], "title": x["title"], "status": "ready", "paragraphs": paragraphs(x["body"])}
                for x in res]
    if not all(c["paragraphs"] for c in chapters):
        raise GenerationFailed("소설체 결과에 빈 장이 있다")
    flat = [p["sentences"][0] for c in chapters for p in c["paragraphs"]]
    title = chapters[0]["title"] if n == 1 else BOOK_TITLE
    return {"status": READY, "style": style, "title": title, "chapters": chapters, "to_confirm": [],
            "body": "\n\n".join(x["body"].strip() for x in res),
            "sources": [{"sentence": i, "turns": []} for i in range(len(flat))],
            "verification": {"state": "not_run"},
            "run": {"session_ids": ids, "chapters_requested": n,
                    "model": s["MEMOIR_NOVEL_MODEL"], "prompt_sha256": sha[:16]}}
