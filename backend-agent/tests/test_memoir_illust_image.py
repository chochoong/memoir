"""
삽화 그림 실행기 (tools/memoir_illust_image.py · 로컬 실험)

    python -m pytest tests/test_memoir_illust_image.py -q

그림 모델을 부르지 않는다 — LIVE_CALL 을 갈아 끼우거나, 이 컴퓨터에 띄운 가짜 서버로 SDK 가 보내는 요청을 본다.
"""

from __future__ import annotations

import base64
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import memoir_illust_image as img     # noqa: E402

PIXELS = b"\xff\xd8\xff\xe0" + b"fake-jpeg-bytes" * 20 + b"\xff\xd9"
B64 = base64.b64encode(PIXELS).decode()
PROMPT = "[그림 양식]\r\n수채화 한 장.\r\n\r\n[그릴 장면]\r\n- 인물: 두 사람\r\n"
KEY = "test-key-not-real"


def ok_response() -> dict:
    return {"id": "int_1", "status": "completed", "output_image": {"type": "image", "data": B64, "mime_type": "image/jpeg"},
            "steps": [{"type": "thought", "signature": "s" * 5000},
                      {"type": "model_output", "content": [{"type": "image", "data": B64, "mime_type": "image/jpeg"}]}],
            "usage": {"total_input_tokens": 400, "total_output_tokens": 1120, "total_tokens": 1520}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(img, "RUNS", tmp_path / "runs")
    (tmp_path / "p.txt").write_bytes(PROMPT.encode("utf-8"))
    (tmp_path / "k.env").write_text(f"GEMINI_API_KEY={KEY}\n", encoding="utf-8")
    calls = []

    def base(out="o", extra=()):
        return ["--prompt-file", str(tmp_path / "p.txt"), "--model", "m-img", "--size", "1K", "--aspect", "5:4",
                "--out", str(tmp_path / "runs" / out), *extra]

    def live(out="o", confirm=None, extra=()):
        token = confirm or img.confirm_token("m-img", "1K", "5:4", PROMPT)
        return base(out, ["--live", "--env-file", str(tmp_path / "k.env"), "--confirm", token,
                          "--approved-by", "시험", "--approval-note", "시험용 승인", *extra])

    def fake(reply):
        def call(prompt, *, model, size, aspect, key):
            calls.append({"prompt": prompt, "model": model, "size": size, "aspect": aspect, "key": key})
            if isinstance(reply, Exception):
                raise reply
            return reply
        monkeypatch.setattr(img, "LIVE_CALL", call)

    return type("Env", (), {"tmp": tmp_path, "base": staticmethod(base), "live": staticmethod(live),
                            "fake": staticmethod(fake), "calls": calls, "out": tmp_path / "runs" / "o"})


def run_doc(env) -> dict:
    return json.loads((env.out / "run.json").read_text(encoding="utf-8"))


def test_dry_run_shows_scope_and_calls_nothing(env, capsys):
    env.fake(ok_response())
    assert img.main(env.base(extra=["--dry-run"])) == 0
    d = json.loads(capsys.readouterr().out)
    assert (d["model"], d["size"], d["aspect"], d["images_requested"], d["max_calls"]) == ("m-img", "1K", "5:4", 1, 1)
    assert d["prompt_sha256"] == img.sha256(PROMPT.encode("utf-8")) and d["prompt_line_endings"] == "CRLF"
    assert d["live_confirm"] == img.confirm_token("m-img", "1K", "5:4", PROMPT) and d["api_called"] is False
    assert d["attachments"] == [] and d["tools"] == [] and d["out"].endswith("o") and d["out_already_attempted"] is False
    assert env.calls == [] and not env.out.exists() and KEY not in json.dumps(d)


def test_image_is_saved_and_states_are_recorded(env, capsys):
    env.fake(ok_response())
    assert img.main(env.live()) == 0
    shown = capsys.readouterr().out
    assert len(env.calls) == 1 and env.calls[0] == {"prompt": PROMPT, "model": "m-img", "size": "1K", "aspect": "5:4", "key": KEY}
    assert (env.out / "image.jpg").read_bytes() == PIXELS
    assert (env.out / "prompt_sent.txt").read_bytes() == PROMPT.encode("utf-8")           # 보낸 글 그대로 — 줄바꿈까지
    r = run_doc(env)
    assert (r["outcome"], r["calls"], r["images_returned"], r["image_mime"], r["response_id"]) == ("image_saved", 1, 1, "image/jpeg", "int_1")
    assert r["image_sha256"] == img.sha256(PIXELS) and r["usage"]["total_output_tokens"] == 1120
    assert r["generation"] == {"user_selected": True, "user_selected_by": "시험", "automatic": False,
                               "image_status": "generated", "user_approved": False}
    assert r["approval"]["approved_by"] == "시험" and r["started_at"] <= r["call_finished_at"] <= r["finished_at"]
    assert json.loads((env.out / "attempt.json").read_text(encoding="utf-8"))["call"] == 1
    everything = shown + "".join(p.read_text(encoding="utf-8", errors="ignore") for p in env.out.iterdir())
    assert KEY not in everything and B64 not in json.dumps(r) and "sssss" not in json.dumps(r)   # 키도, 그림 바이트도, 긴 서명도 없다


@pytest.mark.parametrize("reply,outcome", [
    ({"id": "int_2", "status": "completed", "steps": [], "usage": {"total_tokens": 9}}, "empty"),
    ({"id": "int_3", "status": "completed", "output_text": "이 요청은 도와드릴 수 없습니다."}, "empty"),
    ({"id": "int_4", "status": "failed", "errors": [{"code": "SAFETY", "message": "blocked"}]}, "refused"),
    ({"id": "int_5", "status": "incomplete"}, "refused"),
])
def test_response_without_an_image_is_told_apart_and_not_retried(env, capsys, reply, outcome):
    env.fake(reply)
    assert img.main(env.live()) == 1
    capsys.readouterr()
    r = run_doc(env)
    assert (r["outcome"], r["calls"], r["images_returned"]) == (outcome, 1, 0) and len(env.calls) == 1
    assert r["generation"]["image_status"] == "failed" and r["generation"]["user_approved"] is False
    assert not (env.out / "image.jpg").exists() and (env.out / "response.json").exists()
    if reply.get("output_text"):
        assert r["output_text"] == reply["output_text"]


def test_call_error_is_recorded_and_not_retried(env, capsys):
    class Boom(RuntimeError):
        status_code = 503
    env.fake(Boom(f"upstream said no (key {KEY})"))
    assert img.main(env.live()) == 1
    capsys.readouterr()
    r = run_doc(env)
    assert (r["outcome"], r["calls"]) == ("error", 1) and len(env.calls) == 1
    assert r["failure"]["type"] == "Boom" and r["failure"]["http_status"] == 503 and KEY not in json.dumps(r)
    assert not (env.out / "response.json").exists()
    assert img.main(env.live()) == 3 and len(env.calls) == 1                              # 같은 폴더로 다시 돌려도 부르지 않는다


def test_save_failure_is_recovered_from_the_kept_response_without_calling_again(env, capsys, monkeypatch):
    env.fake(ok_response())
    real = img.save_image

    def broken(out, raw, run, write=None):
        def fail(path, data):
            raise OSError("disk full")
        return real(out, raw, run, write=fail)
    monkeypatch.setattr(img, "save_image", broken)
    assert img.main(env.live()) == 1
    r = run_doc(env)
    assert (r["outcome"], r["calls"], r["images_returned"]) == ("save_failed", 1, 1) and not (env.out / "image.jpg").exists()
    assert (env.out / "response.json").exists()
    monkeypatch.setattr(img, "save_image", real)
    assert img.main(env.live()) == 0                                                      # 다시 돌리면 보관된 응답에서 꺼낸다
    capsys.readouterr()
    r = run_doc(env)
    assert (r["outcome"], r["calls"]) == ("image_saved", 1) and "recovery" in r and len(env.calls) == 1
    assert (env.out / "image.jpg").read_bytes() == PIXELS


def test_folder_that_was_already_used_is_not_called_again(env, capsys):
    env.fake(ok_response())
    assert img.main(env.live()) == 0
    assert img.main(env.live()) == 3
    capsys.readouterr()
    assert len(env.calls) == 1


def test_image_given_as_uri_is_not_downloaded(env, capsys):
    env.fake({"id": "i", "status": "completed", "output_image": {"type": "image", "uri": "https://example.invalid/x.jpg"}})
    assert img.main(env.live()) == 1
    capsys.readouterr()
    r = run_doc(env)
    assert r["outcome"] == "save_failed" and r["image_uri"].endswith("x.jpg") and len(env.calls) == 1


def test_live_is_refused_unless_every_condition_holds(env, capsys):
    env.fake(ok_response())
    good = env.live()
    assert img.main(env.live(confirm="wrong")) == 2
    assert img.main([x if x != "1K" else "2K" for x in good]) == 2                        # 크기가 바뀌면 승인도 다시
    assert img.main([x if x != "5:4" else "1:1" for x in good]) == 2
    assert img.main([x if x != "m-img" else "m-other" for x in good]) == 2
    assert img.main(good[:good.index("--approved-by")]) == 2                              # 승인 기록 없음
    assert img.main([x if not x.endswith("k.env") else str(env.tmp / "none.env") for x in good]) == 2
    assert img.main(env.base()) == 2                                                      # --dry-run 도 --live 도 아님
    outside = [x if x != str(env.out) else str(env.tmp / "elsewhere") for x in good]
    assert img.main(outside) == 2                                                         # git 제외 경로 밖
    (env.tmp / "p.txt").write_bytes((PROMPT + "- 사물: 장화\r\n").encode("utf-8"))
    assert img.main(good) == 2                                                            # 전송문이 바뀌면 승인도 다시
    capsys.readouterr()
    assert env.calls == [] and not env.out.exists()


def test_prompt_must_match_the_candidate_it_came_from(env, capsys):
    env.fake(ok_response())
    res = env.tmp / "result.json"
    res.write_text(json.dumps({"scenes": [{"generation_prompt": {"text": PROMPT.replace("\r\n", "\n")}}, {"generation_prompt": None}]},
                              ensure_ascii=False), encoding="utf-8")
    assert img.main(env.base(extra=["--dry-run", "--candidate-result", str(res)])) == 0
    m = json.loads(capsys.readouterr().out)["candidate_match"]
    assert m["same_text"] is True and m["byte_identical"] is False                        # 줄바꿈만 다르다
    res.write_text(json.dumps({"scenes": [{"generation_prompt": {"text": "다른 글"}}]}, ensure_ascii=False), encoding="utf-8")
    assert img.main(env.base(extra=["--dry-run", "--candidate-result", str(res)])) == 2
    capsys.readouterr()


# ---------------------------------------------------------------- SDK 가 실제로 보내는 요청 — 이 컴퓨터의 가짜 서버로 본다

class _Server:
    def __init__(self, status: int, body: dict):
        self.hits, outer = [], self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):                      # noqa: N802
                n = int(self.headers.get("content-length") or 0)
                outer.hits.append({"path": self.path, "body": json.loads(self.rfile.read(n) or b"{}"),
                                   "has_key_header": bool(self.headers.get("x-goog-api-key"))})
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()


SDK_SCRIPT = """
import json, sys
sys.path.insert(0, sys.argv[1])
from tools import memoir_illust_image as img
try:
    raw = img.gemini_image_call(sys.argv[3], model="m-img", size="1K", aspect="5:4", key="test-key-not-real", base_url=sys.argv[2])
    print(json.dumps({"ok": True, "images": len(img.images_in(raw)), "data": img.images_in(raw)[0]["data"], "id": raw.get("id")}))
except Exception as e:
    print(json.dumps({"ok": False, "type": type(e).__name__}))
"""


def _sdk_call(server) -> dict:
    """
    실제 SDK 로 가짜 서버를 한 번 부른다 — 다른 파이썬 프로세스에서. 이 시험 프로세스는 conftest 가 Gemini 클라이언트 생성을 막고 있다.
    가는 곳은 이 컴퓨터(127.0.0.1)의 가짜 서버뿐이다.
    """
    import os
    import subprocess
    try:
        done = subprocess.run([sys.executable, "-c", SDK_SCRIPT, str(ROOT), server.url, PROMPT], capture_output=True,
                              text=True, encoding="utf-8", timeout=60, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    finally:
        server.close()
    assert done.returncode == 0, done.stderr[-400:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_sdk_sends_one_request_with_only_the_prompt_and_image_format():
    server = _Server(200, ok_response())
    got = _sdk_call(server)
    assert got == {"ok": True, "images": 1, "data": B64, "id": "int_1"}
    assert len(server.hits) == 1 and server.hits[0]["path"].endswith("/interactions") and server.hits[0]["has_key_header"]
    body = server.hits[0]["body"]
    assert body["model"] == "m-img" and body["input"] == PROMPT                          # 글 그대로 — 줄바꿈까지
    assert body["response_format"] == {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "5:4", "image_size": "1K"}
    assert set(body) <= {"model", "input", "response_format", "stream"}                   # 도구 · 참고 그림 · 다른 글을 붙이지 않았다


@pytest.mark.parametrize("status", [503, 429, 500, 408])
def test_sdk_does_not_retry_on_retryable_errors(status):
    """interactions 의 기본은 408 · 409 · 429 · 5XX 에 4번 다시 부른다 — 꺼져 있어야 한다."""
    server = _Server(status, {"error": {"code": status, "message": "try later", "status": "UNAVAILABLE"}})
    got = _sdk_call(server)
    assert got["ok"] is False and len(server.hits) == 1
