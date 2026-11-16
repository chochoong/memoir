"""
자서전 수필체 · 문학체 (style=essay · literary) — 태헌 전달 자료 3판

    첨부프롬프트_md/문체/essay/7c_고픽션문학수필_리듬v1.md        수필체 (시스템 프롬프트)
    첨부프롬프트_md/문체/literary/prompt_극서정문학체_v2.md       문학체 (시스템 프롬프트)
    첨부프롬프트_md/문체/analysis/0_원문분석_목차통합_안전사본.md  분석 (시스템 프롬프트)
    첨부프롬프트_md/문체/reference/bundle_reference.py           장 자료 묶음 조립
    aidlc-docs/construction/unit8-memoir-pipeline/style-handoff/backend_handoff.md §3

두 문체는 원문만으로 쓰지 않는다. **두 번 부른다.**

1. **분석** — 회차마다 한 번. 그 회차의 어르신 말씀 하나하나가 「이야기」 다. 번호는 책 전체에서
   기록 순서대로 1부터 잇는다 (뒤에 회차가 붙어도 앞 번호는 그대로다). 「장 하나(c1)」 로 설계하라고
   맺는다 — 실험의 한 장 맺음 문장 그대로, 이야기 개수만 바꿨다. 출력은 분석 스키마로 강제한다.
2. **집필** — 장(= 회차)마다 한 번. 분석들을 책 하나로 합쳐 (장 id 는 c1 · c2 … 책 순서) 참조
   구현으로 묶음을 만들고, 문체 프롬프트를 시스템으로 보낸다. 출력은 문체 스키마로 강제한다.

**정한 것** (style-handoff/remaining_decisions.md 의 번호)
- 8 확정 제목 — 장 제목은 그 회차의 엽서 제목(없으면 회차 제목)이다. 수필체 묶음의 확정 제목도 이것.
  모델이 낸 title 은 쓰지 않는다 (문학체는 임시값 「제목 미확정」 을 낸다).
- 13 민감한 기억 — 그 장의 어르신 말씀에 죽음 · 사고 · 질병 · 전쟁의 낱말(SENSITIVE_WORDS)이 있으면 true.
  true 일 때만 수필체의 「임종 장면을 만들지 않는다」 규칙 · 문학체의 「경위와 결과는 원문 그대로」 문구가 켜진다.
  놓치는 것보다 잘못 켜는 쪽이 낫다 — 낱말은 넉넉하게 잡는다. 실험의 사람이 고른 목록은 없다.
- 7 essay_id 가 요청한 장 id 와 다르면 실패시키지 않고 요청한 id 로 본다 (로그에 남긴다).
- 4 응답 — 출력 문단의 줄 하나를 응답의 문단 하나로, 문단 안은 문장으로 나눈다 (책 넘김 화면이
  문장 단위로 쪽을 나눈다). 사실 표시(facts.where)가 든 문장에는 그 사실의 이야기 번호를 turns 로 단다.
- 10 각색 기록(fiction) — 응답의 adaptations 에 장 번호와 함께 싣는다. 화면에는 나가지 않는다.
- 문학체 참고 분량 — 검증된 한 조합(원문 1,234자 → 4,500~7,000자)의 비율로 늘이고 줄인다.

**같은 회차는 다시 쓰지 않는다** (메모리 · 서버를 다시 켜면 사라진다). 분석은 그 회차의 분석 요청이
같으면, 집필은 문체 · 모델 · 그 회차의 분석 요청 · 장 제목 · 장 번호가 같으면 앞의 것을 쓴다. 묶음의
차례(다른 장들)는 열쇠에 넣지 않는다 — 넣으면 책에 장이 하나 늘 때마다 모든 장을 다시 쓴다.

로그에는 회차 앞 8자 · 토큰 · 시간 · 종료 사유만 남긴다. 원문 · 분석 · 본문은 남기지 않는다.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import re
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

from .conf import env_float, env_int, env_str
from .memoir_novel import chapter_title, elder_lines

log = logging.getLogger("memoir")

ROOT = Path(__file__).resolve().parents[2] / "첨부프롬프트_md" / "문체"

# sha256 앞 16자리 — style_manifest.json. 다르면 쓰지 않는다 (줄바꿈이 CRLF 로 풀렸거나 고쳐졌다)
ANALYSIS = {"prompt": ROOT / "analysis" / "0_원문분석_목차통합_안전사본.md", "sha": "6c2f1afea07e982e",
            "schema": ROOT / "schemas" / "analysis_output.schema.json"}
STYLES = {
    "essay": {"name": "수필체", "prompt": ROOT / "essay" / "7c_고픽션문학수필_리듬v1.md", "sha": "4a9c43e3b163e70d",
              "schema": ROOT / "schemas" / "essay_output.schema.json",
              "model": "claude-sonnet-5-5", "max_tokens": 65536, "book": "수필로 엮은 나의 이야기"},
    "literary": {"name": "문학체", "prompt": ROOT / "literary" / "prompt_극서정문학체_v2.md", "sha": "fd70d60bb8ad4e14",
                 "schema": ROOT / "schemas" / "literary_output.schema.json",
                 "model": "claude-sonnet-5-5", "max_tokens": 128000, "book": "문학으로 엮은 나의 이야기"},
}
BUNDLE = ROOT / "reference" / "bundle_reference.py"

# 검증된 조합 (style_manifest.json) — 분석 Fable 5.1 · 출력 32,000 / 문학체 Sonnet 5.5 · 128,000 · 320초
DEFAULT_ANALYSIS_MODEL = "claude-fable-5-1"
DEFAULT_ANALYSIS_MAX_TOKENS = 32000
DEFAULT_EFFORT = "high"
DEFAULT_TIMEOUT = 600.0
DEFAULT_PARALLEL = 4
# 13 — 민감한 기억의 낱말. 하나라도 있으면 그 장은 민감하다 (넉넉하게 — 잘못 켜도 사실을 지키라는 규칙일 뿐이다)
SENSITIVE_WORDS = re.compile(
    r"죽었|죽은|죽고|죽음|숨지|숨을 거|돌아가셨|돌아가시|세상을 떠|별세|장례|상여|빈소|임종|묘소|산소에|제사"
    r"|사고|다쳤|다치|부상|병원|병환|병이 |병으로|병에 |투병|앓|수술|입원|암이|암으로|암에|암 진단|치매|중풍"
    r"|전쟁|피난|난리|폭격|6\.25|육이오")
LIT_RATIO = (4500 / 1234, 7000 / 1234)  # 문학체 참고 분량 — 검증된 한 조합의 비율
LIT_MIN = (1200, 2000)

# 100만 토큰당 USD (입력, 출력). 모르는 모델은 비용을 적지 않는다
PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "claude-fable-5-1": (10.0, 50.0), "claude-fable-5-2": (8.0, 40.0),
          "claude-opus-5-5": (5.0, 25.0)}

_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_CACHE_MAX = 512


def settings(style: str) -> dict:
    up = style.upper()
    return {
        "analysis_model": env_str("MEMOIR_STYLE_ANALYSIS_MODEL", DEFAULT_ANALYSIS_MODEL),
        "analysis_max_tokens": env_int("MEMOIR_STYLE_ANALYSIS_MAX_TOKENS", DEFAULT_ANALYSIS_MAX_TOKENS),
        "model": env_str(f"MEMOIR_{up}_MODEL", STYLES[style]["model"]),
        "max_tokens": env_int(f"MEMOIR_{up}_MAX_TOKENS", STYLES[style]["max_tokens"]),
        "effort": env_str("MEMOIR_STYLE_EFFORT", DEFAULT_EFFORT),
        "timeout": env_float("MEMOIR_STYLE_TIMEOUT", DEFAULT_TIMEOUT),
        "parallel": max(1, env_int("MEMOIR_STYLE_PARALLEL", DEFAULT_PARALLEL)),
    }


@lru_cache(maxsize=8)
def _file(path: Path, sha16: str) -> tuple[str, str]:
    """(파일 글, sha256 전체). 바이트로 읽어 UTF-8 로 푼다 — 공통 지침을 붙이지 않고 다듬지 않는다."""
    from .memoir import GenerationFailed

    try:
        raw = path.read_bytes()
    except OSError as e:
        raise GenerationFailed(f"문체 프롬프트를 읽지 못했다: {path.name} ({e})") from e
    sha = hashlib.sha256(raw).hexdigest()
    if not sha.startswith(sha16):
        raise GenerationFailed(f"{path.name} 이 전달본과 다르다 (sha256 {sha[:16]})")
    return raw.decode("utf-8"), sha


def prompt(style: str) -> tuple[str, str]:
    return _file(STYLES[style]["prompt"], STYLES[style]["sha"])


def analysis_prompt() -> tuple[str, str]:
    return _file(ANALYSIS["prompt"], ANALYSIS["sha"])


@lru_cache(maxsize=4)
def schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def bundle():
    """참조 구현을 그대로 읽어 쓴다 — 실제로 보낸 입력과 글자까지 같다고 확인된 조립이다 (표준 라이브러리만)."""
    spec = importlib.util.spec_from_file_location("memoir_style_bundle", BUNDLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 입력

def stories_of(order: list[dict]) -> list[dict[int, str]]:
    """회차마다 {이야기 번호: 말씀}. 번호는 책 전체에서 기록 순서대로 1부터 잇는다."""
    out, n = [], 0
    for rec in order:
        st = {}
        for line in elder_lines(rec):
            n += 1
            st[n] = line
        out.append(st)
    return out


def analysis_message(stories: dict[int, str]) -> str:
    """handoff §3 — 이야기마다 「## 이야기 N」 · 빈 줄 · 원문. 이야기 사이 빈 줄. 끝에 한 장 맺음 문장."""
    k = len(stories)
    parts = [f"## 이야기 {n}\n\n{t}" for n, t in stories.items()]
    close = (f"위 이야기 {k}개를 지시대로 분석하고, 이번에는 **장 하나(c1)** 로 설계해 JSON 하나만 출력하세요. "
             f"이야기 {k}개 모두 그 한 장에 들어갑니다(장 수 1).")
    return "\n\n".join(parts) + "\n\n" + close


def check_analysis(a: dict, nums: list[int]) -> dict:
    """분석이 받은 이야기를 다 다뤘는지. 장은 하나로 본다 — 모델이 여럿으로 나눴으면 첫 장의 설계를 쓴다."""
    got = [s.get("turn") for s in a.get("stories") or []]
    if sorted(got) != sorted(nums):
        raise ValueError(f"분석의 이야기 번호가 다르다 ({len(got)}개 / 요청 {len(nums)}개)")
    chs = a.get("chapters") or []
    if not chs:
        raise ValueError("분석에 장 설계가 없다")
    ch = dict(chs[0])
    ch["stories"] = list(nums)
    ch["fact_ids"] = [f["id"] for s in a["stories"] for f in s.get("facts") or []]
    return {"book_title": a.get("book_title", ""), "stories": a["stories"], "chapter": ch}


def book_analysis(parts: list[dict], titles: list[str]) -> dict:
    """회차별 분석을 책 하나로 — 장 id 는 책 순서대로 c1 · c2 …, 제목은 확정 제목(엽서 제목)."""
    return {"book_title": "",
            "stories": [s for p in parts for s in p["stories"]],
            "chapters": [{**p["chapter"], "id": f"c{no}", "title": titles[no - 1]}
                         for no, p in enumerate(parts, start=1)]}


def literary_target(stories: dict[int, str]) -> tuple[int, int]:
    chars = bundle().nchars("\n".join(stories.values()))
    lo = max(LIT_MIN[0], int(round(chars * LIT_RATIO[0], -2)))
    hi = max(LIT_MIN[1], int(round(chars * LIT_RATIO[1], -2)))
    return lo, max(hi, lo + 500)


def sensitive(stories: dict[int, str]) -> bool:
    """그 장의 말씀에 죽음 · 사고 · 질병 · 전쟁의 낱말이 있는가."""
    return any(SENSITIVE_WORDS.search(t) for t in stories.values())


def style_message(style: str, book: dict, stories: dict[int, str], cid: str) -> str:
    b = bundle()
    if style == "essay":
        return b.essay_user_message(book, stories, cid, sensitive(stories))
    return b.literary_user_message(book, stories, cid, sensitive(stories), literary_target(stories))


# ---------------------------------------------------------------- 출력 → 응답

_SENT = re.compile(r"\S.*?(?:[.!?…]+[\"”’」』')]*(?=\s|$)|$)")


def norm(s: str) -> str:
    return re.sub(r"\s", "", s)


def split_sentences(line: str) -> list[str]:
    return [m.group(0).strip() for m in _SENT.finditer(line) if m.group(0).strip()]


def paragraphs(out: dict, where_turns: list[tuple[str, int]]) -> list[dict]:
    """
    문체 출력의 paragraphs → 응답의 문단. 문단 안 줄바꿈(문학체)은 문단을 나눠 지킨다. 문단은 문장으로
    나누고, 사실 표시(where)가 든 문장에 그 사실의 이야기 번호를 단다.
    """
    res = []
    for para in out.get("paragraphs") or []:
        for line in str(para).splitlines():
            ss = split_sentences(line)
            if not ss:
                continue
            res.append({"sentences": [
                {"text": s, "turns": sorted({t for w, t in where_turns if w and w[:20] in norm(s)})} for s in ss]})
    return res


def where_turns(out: dict, book: dict) -> list[tuple[str, int]]:
    turn = {f["id"]: s["turn"] for s in book["stories"] for f in s.get("facts") or []}
    return [(norm(str(x.get("where") or "")), turn[x.get("id")]) for x in out.get("facts") or []
            if x.get("id") in turn]


# ---------------------------------------------------------------- 호출

async def _call(client, system: str, msg: str, fmt: dict, model: str, max_tokens: int, effort: str) -> tuple[str, dict]:
    """(글, 기록). 정상 완료(end_turn)가 아니면 쓰지 않는다 (handoff §8)."""
    async with client.beta.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": fmt}},
        # 안전 분류기가 거절하면 같은 요청을 다른 모델이 잇는다 — 소설체와 같다
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": msg}],
    ) as stream:
        final = await stream.get_final_message()
    text = "".join(b.text for b in final.content if getattr(b, "type", "") == "text")
    u = final.usage
    return text, {"stop": final.stop_reason, "model": final.model,
                  "input": getattr(u, "input_tokens", 0) or 0, "output": getattr(u, "output_tokens", 0) or 0}


def _remember(key: str, val: dict) -> None:
    _CACHE[key] = val
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


async def run(recs: list[dict], ids: list[str], style: str, progress=None) -> dict:
    """collect 를 지난 회차로 수필체 · 문학체 책 한 권. 응답은 소설체와 같은 7-C1 장 모양이다."""
    from .memoir import (READY, GenerationFailed, GenerationTimeout, Incomplete, SourceUnavailable,
                         inject, INJECT_FAILED, INJECT_TIMEOUT)

    hook = inject()
    if hook == INJECT_FAILED:
        raise GenerationFailed("MEMOIR_FAIL_INJECT=generation_failed")
    if hook == INJECT_TIMEOUT:
        raise GenerationTimeout("MEMOIR_FAIL_INJECT=generation_timeout")

    cfg = STYLES[style]
    order = sorted(recs, key=lambda r: r["created_at"])
    if len({r["created_at"] for r in order}) != len(order):
        raise SourceUnavailable("시작 시각이 같은 회차가 있어 기록 순서를 정할 수 없다")
    system, sha = prompt(style)
    a_system, a_sha = analysis_prompt()
    bundle()
    s = settings(style)
    key_api = env_str("ANTHROPIC_API_KEY", "")
    if not key_api:
        raise GenerationFailed(f"ANTHROPIC_API_KEY 가 없다 — {cfg['name']}는 Claude 로 쓴다")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=key_api, max_retries=1)
    n = len(order)
    gate = asyncio.Semaphore(s["parallel"])
    usage: list[dict] = []
    t0 = time.monotonic()
    stories = stories_of(order)
    titles = [chapter_title(r, no) for no, r in enumerate(order, start=1)]
    log.info("자서전 %s 요청 — 회차 %d개 %s · 분석 %s · 집필 %s · 프롬프트 %s",
             cfg["name"], n, ",".join(r["session_id"][:8] for r in order), s["analysis_model"], s["model"], sha[:16])
    if progress is not None:
        progress("analysis", 0, n)

    async def call(what: str, no: int, sid: str, sysm: str, msg: str, fmt: dict, model: str, mt: int) -> dict:
        """한 번 부르고 JSON 을 푼다. 실패는 {"fail": ...} 로 돌려준다 — 다른 장은 계속 쓴다."""
        async with gate:
            t = time.monotonic()
            try:
                text, r = await asyncio.wait_for(_call(client, sysm, msg, fmt, model, mt, s["effort"]), s["timeout"])
            except asyncio.TimeoutError:
                log.warning("%s %s %d장 %s — %.0f초 안에 오지 않았다", cfg["name"], what, no, sid[:8], s["timeout"])
                return {"fail": "generation_timeout"}
            except Exception as e:                           # noqa: BLE001
                log.warning("%s %s %d장 %s — 호출 실패 %s: %s", cfg["name"], what, no, sid[:8], type(e).__name__, str(e)[:160])
                return {"fail": "generation_failed"}
        usage.append(r)
        log.info("%s %s %d장 %s — %s · %.1f초 · 입력 %d · 출력 %d · %s", cfg["name"], what, no, sid[:8], r["stop"],
                 time.monotonic() - t, r["input"], r["output"], r["model"])
        if r["stop"] != "end_turn":
            return {"fail": "generation_failed"}
        try:
            return {"json": json.loads(text)}
        except ValueError:
            log.warning("%s %s %d장 %s — JSON 이 아니다", cfg["name"], what, no, sid[:8])
            return {"fail": "generation_failed"}

    # 1. 분석 — 회차마다
    async def analyse(no: int, rec: dict, st: dict[int, str]) -> dict:
        sid = rec["session_id"]
        if not st:
            return {"fail": "generation_failed"}
        msg = analysis_message(st)
        key = hashlib.sha256(f"A|{s['analysis_model']}|{s['effort']}|{a_sha}|{msg}".encode()).hexdigest()
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return {**_CACHE[key], "akey": key, "cached": True}
        got = await call("분석", no, sid, a_system, msg, schema(ANALYSIS["schema"]),
                         s["analysis_model"], s["analysis_max_tokens"])
        if "fail" in got:
            return got
        try:
            part = check_analysis(got["json"], list(st))
        except (ValueError, KeyError, TypeError) as e:
            log.warning("%s 분석 %d장 %s — %s", cfg["name"], no, sid[:8], e)
            return {"fail": "generation_failed"}
        _remember(key, part)
        return {**part, "akey": key}

    try:
        parts = await asyncio.gather(*(analyse(no, r, st) for no, (r, st) in enumerate(zip(order, stories), start=1)))
        ok = [p for p in parts if "fail" not in p]
        res: list[dict] = [{"no": no, "title": titles[no - 1], "sid": r["session_id"]}
                           for no, r in enumerate(order, start=1)]
        for x, p in zip(res, parts):
            if "fail" in p:
                x["fail"] = p["fail"]
        # 분석이 안 된 장도 차례의 자리는 지킨다 (장 번호가 밀리지 않게) — 그 장은 쓰지 않는다
        book = book_analysis([p if "fail" not in p else {"stories": [], "chapter": {"stories": []}} for p in parts],
                             titles) if ok else None

        # 2. 집필 — 장마다 (분석이 된 장만)
        done = 0
        if progress is not None:
            progress("chapter", 1, n)

        async def write(x: dict, p: dict, st: dict[int, str]) -> None:
            nonlocal done
            no, sid, cid = x["no"], x["sid"], f"c{x['no']}"
            key = hashlib.sha256(f"W|{style}|{s['model']}|{s['effort']}|{sha}|{p['akey']}|{x['title']}|{no}"
                                 .encode()).hexdigest()
            if key in _CACHE:
                _CACHE.move_to_end(key)
                x.update(out=_CACHE[key], cached=True)
            else:
                msg = style_message(style, book, st, cid)
                got = await call("집필", no, sid, system, msg, schema(cfg["schema"]), s["model"], s["max_tokens"])
                if "fail" in got:
                    x["fail"] = got["fail"]
                else:
                    out = got["json"]
                    if out.get("essay_id") != cid:
                        log.info("%s %d장 %s — essay_id %r 를 %s 로 본다", cfg["name"], no, sid[:8],
                                 str(out.get("essay_id"))[:12], cid)
                    if not any(str(q).strip() for q in out.get("paragraphs") or []):
                        x["fail"] = "generation_failed"
                    else:
                        x["out"] = out
                        _remember(key, out)
            done += 1
            if progress is not None and done < n:
                progress("chapter", done + 1, n)

        await asyncio.gather(*(write(x, p, st) for x, p, st in zip(res, parts, stories) if "fail" not in p))
    finally:
        await client.close()

    tin = sum(r["input"] for r in usage)
    cost = 0.0
    for r in usage:
        price = PRICES.get(r["model"]) or PRICES.get(s["model"])
        cost += (r["input"] * price[0] + r["output"] * price[1]) / 1e6 if price else 0.0
    log.info("자서전 %s 응답 — %.1f초 · 장 %d (실패 %d) · 호출 %d · 입력 %d · 출력 %d · 비용 약 $%.3f",
             cfg["name"], time.monotonic() - t0, n, sum(1 for x in res if "fail" in x), len(usage), tin,
             sum(r["output"] for r in usage), cost)

    failed = [x for x in res if "fail" in x]
    if failed:
        why = " · ".join(f"{x['no']}장 {x['fail']}" for x in failed)
        if len(failed) < n:
            raise Incomplete(f"partial — {cfg['name']} {why}")
        if all(x["fail"] == "generation_timeout" for x in failed):
            raise GenerationTimeout(f"{cfg['name']} {why}")
        raise GenerationFailed(f"{cfg['name']} {why}")

    chapters, adaptations = [], []
    for x in res:
        ps = paragraphs(x["out"], where_turns(x["out"], book))
        if not ps:
            raise GenerationFailed(f"{cfg['name']} {x['no']}장이 비었다")
        chapters.append({"no": x["no"], "title": x["title"], "status": "ready", "paragraphs": ps})
        adaptations += [{"chapter": x["no"], **f} for f in x["out"].get("fiction") or [] if isinstance(f, dict)]
    flat = [t for c in chapters for p in c["paragraphs"] for t in p["sentences"]]
    title = chapters[0]["title"] if n == 1 else cfg["book"]
    return {"status": READY, "style": style, "title": title, "chapters": chapters, "to_confirm": [],
            "body": "\n\n".join("\n".join(str(q) for q in x["out"]["paragraphs"]) for x in res),
            "sources": [{"sentence": i, "turns": t["turns"]} for i, t in enumerate(flat)],
            "verification": {"state": "not_run"},
            "adaptations": adaptations,
            "run": {"session_ids": ids, "chapters_requested": n, "model": s["model"],
                    "analysis_model": s["analysis_model"], "prompt_sha256": sha[:16],
                    "analysis_sha256": a_sha[:16]}}
