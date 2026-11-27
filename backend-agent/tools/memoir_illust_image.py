"""
삽화 그림 한 장을 만든다 — 로컬 실험. 서비스 · DB · API · UI 와 이어져 있지 않다.

    python tools/memoir_illust_image.py --prompt-file <지시문.txt> --model gemini-3.1-flash-image --size 1K --aspect 5:4 \
        --out eval/runs/illust-e01-image1-<날짜> --dry-run
    python tools/memoir_illust_image.py … --live --env-file <.env> --confirm <dry-run 의 live_confirm> \
        --approved-by <이름> --approval-note "<승인한 말>"

한 권을 목차별로 처리하는 흐름(tools/memoir_illust_book.py)도 이 파일의 run_once 로 그림을 만든다 — 그림 한 장마다 폴더 하나다.

**보내는 것은 지시문 파일의 글 그대로다.** 옮기거나 다듬지 않는다. 참고 사진 · 검색 · 다른 원문을 붙이지 않는다.

**한 번만 부른다.** SDK 의 재시도(기본 4번)와 HTTP 계층의 재시도를 끄고, 실패해도 다른 모델 · 크기 · 비율로 바꿔 다시 부르지 않는다.
- 부르기 전에 attempt.json 을 남긴다 — 그 폴더는 「이미 불렀다」.
- 이미 부른 폴더로 다시 돌리면 부르지 않는다. 응답은 받았는데 그림 파일 저장만 실패했으면, 보관된 응답에서 그림을 다시 꺼낸다.

**결과를 다섯 가지로 가른다** (run.json 의 outcome)

    image_saved   그림을 받아 파일로 저장했다
    refused       그림 없이 끝났고 거절로 보인다 (status 가 completed 가 아니거나 errors 가 있다)
    empty         그림도 오류도 없다 (글만 왔으면 그 글을 남긴다)
    error         호출이 실패했다 (예외 종류 · HTTP 상태만 남긴다)
    save_failed   그림은 받았는데 파일로 쓰지 못했다 — 응답은 response.json 에 있다

--live 의 조건: --confirm 이 dry-run 의 live_confirm 과 같다(모델 · 크기 · 비율 · 전송문이 그대로다) · --env-file 에 GEMINI_API_KEY 가 있다 ·
--approved-by 와 --approval-note 가 있다 · --out 이 eval/runs/ 아래다(git 제외) · 그 폴더로 부른 적이 없다.
키는 찍지 않고 어느 파일에도 쓰지 않는다.

종료 코드: 0 그림 저장(또는 복구) / 1 그림 없음 · 실패 / 2 조건 거부 / 3 이미 부른 폴더
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "eval" / "runs"
SIZES = ("512", "1K", "2K", "4K")
ASPECTS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
MIME = "image/jpeg"                  # 설치된 SDK(google-genai 2.33.0)가 아는 그림 형식은 이것 하나다
TIMEOUT_MS = 180_000
IMAGES_REQUESTED = 1
ALREADY = 3                          # 이미 부른 폴더 — 다시 부르지 않았다


class Refuse(RuntimeError):
    pass


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def confirm_token(model: str, size: str, aspect: str, prompt: str) -> str:
    """모델 · 크기 · 비율 · 전송문이 그대로일 때만 같은 값 — 승인한 것과 다른 것을 보내지 못하게."""
    raw = json.dumps([model, size, aspect, MIME, IMAGES_REQUESTED, sha256(prompt.encode("utf-8"))])
    return sha256(raw.encode("utf-8"))[:12]


def read_key(env_file: Path) -> str:
    from dotenv import dotenv_values

    key = (dotenv_values(env_file).get("GEMINI_API_KEY") or "").strip() if env_file.is_file() else ""
    if not key:
        raise Refuse(f"{env_file.name} 에 GEMINI_API_KEY 가 없다")
    return key


def make_client(key: str, base_url: str | None = None):
    """재시도를 끈 클라이언트. 끄지 못하면 부르지 않는다."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key, http_options=types.HttpOptions(
        timeout=TIMEOUT_MS, base_url=base_url, retry_options=types.HttpRetryOptions(attempts=1)))
    cfg = getattr(client.interactions, "sdk_configuration", None)
    if cfg is None or not hasattr(cfg, "retry_config"):
        raise Refuse("SDK 의 재시도 설정을 찾지 못했다 — 재시도를 끌 수 없으면 부르지 않는다")
    cfg.retry_config = None          # interactions 의 기본은 408 · 409 · 429 · 5XX 에 4번 다시 부른다 — 끈다
    return client


def gemini_image_call(prompt: str, *, model: str, size: str, aspect: str, key: str, base_url: str | None = None) -> dict:
    """한 번 부른다. 다시 부르지 않는다. 공식 이미지 생성 문서의 interactions.create 모양이다."""
    client = make_client(key, base_url)
    res = client.interactions.create(
        model=model, input=prompt,
        response_format={"type": "image", "mime_type": MIME, "aspect_ratio": aspect, "image_size": size})
    return res.model_dump(mode="json") if hasattr(res, "model_dump") else dict(res)


LIVE_CALL = gemini_image_call        # 시험이 갈아 끼운다


def images_in(raw: dict) -> list[dict]:
    """응답에 든 그림들 — 맨 위의 output_image 와 steps 안의 image 내용. 같은 그림은 한 번만 센다."""
    found, seen = [], set()
    items = [raw.get("output_image")] + [c for st in raw.get("steps") or [] if isinstance(st, dict)
                                         for c in (st.get("content") or []) if isinstance(c, dict)]
    for it in items:
        if isinstance(it, dict) and it.get("type", "image") == "image" and (it.get("data") or it.get("uri")):
            ident = it.get("data") or it.get("uri")
            if ident not in seen:
                seen.add(ident)
                found.append(it)
    return found


def slim(raw: dict) -> dict:
    """그림 바이트를 뺀 응답 — run.json 에 싣는다."""
    def cut(x):
        # 그림 바이트(data)만이 아니다 — 생각 단계의 signature 도 100만 자가 넘는다. 긴 글자열은 길이만 남긴다
        if isinstance(x, dict):
            return {k: (f"<base64 {len(v)} chars — response.json 에 있다>"
                        if k == "data" and isinstance(v, str) and len(v) > 200 else cut(v)) for k, v in x.items()}
        if isinstance(x, str) and len(x) > 2000:
            return f"<{len(x)} chars — response.json 에 있다>"
        return [cut(v) for v in x] if isinstance(x, list) else x
    return cut(raw)


def save_image(out: Path, raw: dict, run: dict, write=None) -> str:
    """보관된 응답에서 그림을 꺼내 파일로 쓴다. outcome 을 돌려준다."""
    imgs = images_in(raw)
    run["images_returned"] = len(imgs)
    run["status"] = raw.get("status")
    run["response_id"] = raw.get("id")
    run["usage"] = raw.get("usage")
    run["output_text"] = raw.get("output_text") or None
    if not imgs:
        refused = bool(raw.get("errors")) or raw.get("status") not in (None, "completed")
        run["errors"] = raw.get("errors")
        return "refused" if refused else "empty"
    first = imgs[0]
    run["image_mime"] = first.get("mime_type")
    run["image_resolution"] = first.get("resolution")
    if not first.get("data"):
        run["image_uri"] = first.get("uri")
        run["failure"] = "그림이 바이트가 아니라 주소(uri)로 왔다 — 내려받지 않았다"
        return "save_failed"
    try:
        data = base64.b64decode(first["data"])
        name = "image.png" if (first.get("mime_type") or "").endswith("png") else "image.jpg"
        (write or (lambda p, b: p.write_bytes(b)))(out / name, data)
    except Exception as e:                    # noqa: BLE001 — 저장 실패는 호출 실패와 다르다. 응답은 response.json 에 있다
        run["failure"] = f"그림 파일을 쓰지 못했다 ({type(e).__name__})"
        return "save_failed"
    run["image_file"] = name
    run["image_bytes"] = len(data)
    run["image_sha256"] = sha256(data)
    return "image_saved"


SHOWN = ("outcome", "calls", "model", "size", "aspect", "images_returned", "image_file", "image_mime", "image_resolution",
         "image_bytes", "status", "usage", "failure", "generation")


def finish(out: Path, run: dict, outcome: str, quiet: bool = False) -> int:
    run["outcome"] = outcome
    run["finished_at"] = now()
    ok = outcome == "image_saved"
    auto = run["approval"].get("mode") == "automatic"
    # 사람이 이 한 장을 만들기로 한 실행이면 user_selected 는 그 승인에서 온다. 자동 처리면 누구도 고른 것이 아니다 —
    # user_selected 를 true 로 적지 않고 automatic 으로 따로 적는다. 어느 쪽이든 그림을 승인한 것은 아니다.
    run["generation"] = {"user_selected": not auto, "user_selected_by": None if auto else run["approval"].get("approved_by"),
                         "automatic": auto, "image_status": "generated" if ok else "failed", "user_approved": False}
    (out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    if not quiet:
        print(json.dumps({k: run.get(k) for k in SHOWN}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def run_once(out: Path, raw_bytes: bytes, *, model: str, size: str, aspect: str, key: str, approval: dict,
             request: dict | None = None, quiet: bool = False, call=None) -> tuple[int, dict | None]:
    """
    그림 한 장 — 폴더 하나에 호출 한 번. (종료 코드, run.json 의 내용)을 돌려준다.

        0        그림을 저장했다 (이번에 불렀거나, 보관된 응답에서 꺼냈다)
        1        불렀지만 그림이 없다 · 실패했다
        ALREADY  이 폴더로 이미 불렀다 — 다시 부르지 않았다 (run 은 그때의 기록)
    이미 그림이 저장된 폴더도 ALREADY 다 — 부르는 쪽이 run["outcome"] 으로 가린다.
    """
    prompt = raw_bytes.decode("utf-8")
    if (out / "attempt.json").is_file():
        run = json.loads((out / "run.json").read_text(encoding="utf-8")) if (out / "run.json").is_file() else None
        if run and run.get("outcome") == "save_failed" and (out / "response.json").is_file():
            raw = json.loads((out / "response.json").read_text(encoding="utf-8"))
            run["recovered_at"] = now()
            run["recovery"] = "보관된 응답에서 그림을 다시 꺼냈다 — API 를 다시 부르지 않았다"
            run.pop("failure", None)
            return finish(out, run, save_image(out, raw, run), quiet), run
        return ALREADY, run
    out.mkdir(parents=True, exist_ok=True)
    request = {"provider": "Google Gemini API", "model": model, "size": size, "aspect": aspect, "mime_type": MIME,
               "images_requested": IMAGES_REQUESTED, "max_calls": 1, "retries": "off (SDK · HTTP)",
               "prompt_sha256": sha256(raw_bytes), "prompt_chars": len(prompt), "prompt_bytes": len(raw_bytes),
               "attachments": [], "tools": [], **(request or {})}
    (out / "prompt_sent.txt").write_bytes(raw_bytes)                 # 보낸 글 그대로 (바이트까지)
    (out / "request.json").write_text(json.dumps({**request, "approval": approval}, ensure_ascii=False, indent=1), encoding="utf-8")
    run = {**request, "approval": approval, "calls": 0, "started_at": now()}
    # 부르기 전에 남긴다 — 이 뒤로 이 폴더는 「이미 불렀다」
    (out / "attempt.json").write_text(json.dumps({"call": 1, "started_at": run["started_at"], "model": model,
                                                  "prompt_sha256": request["prompt_sha256"]}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    run["calls"] = 1
    try:
        raw = (call or LIVE_CALL)(prompt, model=model, size=size, aspect=aspect, key=key)   # call — 모의 그림(시험용)
    except Exception as e:                    # noqa: BLE001 — 다시 부르지 않는다. 까닭만 남긴다 (글에 키가 섞일 수 있어 종류와 상태만)
        run["call_finished_at"] = now()
        run["failure"] = {"type": type(e).__name__, "http_status": getattr(e, "status_code", None) or getattr(e, "code", None),
                          "message": str(getattr(e, "message", "") or e)[:500].replace(key, "<key>") if key else str(e)[:500]}
        return finish(out, run, "error", quiet), run
    run["call_finished_at"] = now()
    (out / "response.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")   # 그림 바이트까지 — 복구에 쓴다
    run["response"] = slim(raw)
    return finish(out, run, save_image(out, raw, run), quiet), run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="삽화 그림 한 장 만들기 (로컬 실험 · 한 번만 부른다)")
    ap.add_argument("--prompt-file", required=True, type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--size", required=True, choices=SIZES)
    ap.add_argument("--aspect", required=True, choices=ASPECTS)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--confirm")
    ap.add_argument("--approved-by")
    ap.add_argument("--approval-note")
    ap.add_argument("--candidate-result", type=Path, help="(선택) 이 지시문을 만든 판정 결과 result.json — 같은 글인지 대조한다")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    try:
        try:
            raw_bytes = a.prompt_file.read_bytes()
            prompt = raw_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise Refuse(f"지시문 파일을 읽지 못했다 ({type(e).__name__})") from e
        if not prompt.strip():
            raise Refuse("지시문이 비었다")
        if RUNS.resolve() not in a.out.resolve().parents:
            raise Refuse("--out 은 eval/runs/ 아래여야 한다 (git 제외 경로)")
        token = confirm_token(a.model, a.size, a.aspect, prompt)
        match = None
        if a.candidate_result:
            doc = json.loads(a.candidate_result.read_text(encoding="utf-8"))
            texts = [s["generation_prompt"]["text"] for s in doc["scenes"] if s.get("generation_prompt")]
            same = [t for t in texts if t.replace("\r\n", "\n") == prompt.replace("\r\n", "\n")]
            match = {"result": str(a.candidate_result), "generation_prompts": len(texts), "same_text": bool(same),
                     "byte_identical": prompt in texts,
                     "note": "줄바꿈(CRLF · LF)만 다르면 같은 글로 본다 — 보내는 것은 파일의 글 그대로다"}
            if not same:
                raise Refuse("지시문 파일이 그 판정 결과의 생성용 지시문과 다르다")
        extra = {"prompt_file": str(a.prompt_file), "prompt_line_endings": "CRLF" if "\r\n" in prompt else "LF",
                 "candidate_match": match}
        if a.dry_run:
            shown = {"provider": "Google Gemini API", "model": a.model, "size": a.size, "aspect": a.aspect, "mime_type": MIME,
                     "images_requested": IMAGES_REQUESTED, "max_calls": 1, "retries": "off (SDK · HTTP)",
                     "prompt_sha256": sha256(raw_bytes), "prompt_chars": len(prompt), "prompt_bytes": len(raw_bytes),
                     "attachments": [], "tools": [], **extra, "live_confirm": token}
            print(json.dumps({"dry_run": True, **shown, "out": str(a.out),
                              "out_already_attempted": (a.out / "attempt.json").is_file(), "api_called": False},
                             ensure_ascii=False, indent=1))
            return 0
        if not a.live:
            raise Refuse("--dry-run 또는 --live 를 쓴다")
        if (a.out / "attempt.json").is_file():        # 이미 부른 폴더 — 조건을 다시 묻지 않고 복구만 본다
            code, run = run_once(a.out, raw_bytes, model=a.model, size=a.size, aspect=a.aspect, key="", approval={})
            if code == ALREADY:
                print(f"이미 부른 폴더다 — 다시 부르지 않는다 ({a.out} · outcome {run and run.get('outcome')})", file=sys.stderr)
            return code
        if a.confirm != token:
            raise Refuse("--confirm 이 dry-run 의 live_confirm 과 다르다 — 승인한 모델 · 설정 · 전송문인지 확인한다")
        if not (a.approved_by or "").strip() or not (a.approval_note or "").strip():
            raise Refuse("--approved-by 와 --approval-note(승인한 사람과 승인한 말)가 있어야 한다")
        if not a.env_file:
            raise Refuse("--env-file 이 있어야 한다")
        key = read_key(a.env_file)
    except Refuse as e:
        print(f"거부 — {e}", file=sys.stderr)
        return 2

    approval = {"approved_by": a.approved_by, "note": a.approval_note, "recorded_at": now(),
                "covers": "이 모델 · 크기 · 비율 · 전송문으로 그림 한 장을 만드는 호출 한 번. 그림을 승인한 것이 아니다"}
    code, _ = run_once(a.out, raw_bytes, model=a.model, size=a.size, aspect=a.aspect, key=key, approval=approval, request=extra)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
