"""
시험 중에는 외부 API 를 부르지 않는다 — 실제 키가 있어도 비용이 나지 않게 (단위 8P, 2026-10-26)

    .venv\\Scripts\\python -m pytest tests

**왜 필요한가.** 시험이 `app.main` 을 import 하면 `load_dotenv()` 가 backend-agent/.env 를
읽는다. 실제 GEMINI_API_KEY 가 들어 있으면 TestClient 가 앱을 띄울 때 lifespan 의
`question.warmup()` 이 Gemini 에 'ping' 을 실제로 보낸다(stt · tts 예열도 Azure 키가 있으면
같다). 시험마다 키를 비우는 `_Env` 는 그 시험 안에서만 돌고, 예열은 그 밖에서도 돈다.

**하는 일 (서버 코드는 고치지 않는다).**

    1. 키 이름에 빈 값을 먼저 둔다 — load_dotenv(override=False) 는 이미 있는 이름을
       덮지 않으므로 .env 의 실제 키가 프로세스에 들어오지 않는다. 클라이언트를 만드는
       함수(question · photo_analyze · stt · tts)는 키가 비면 None 을 돌려준다
    2. 그래도 google-genai 클라이언트를 만들려 하면 바로 실패시킨다
    3. 소켓 연결은 이 컴퓨터(127.0.0.1 · ::1 · localhost) 로만 허락한다 — 로컬 Postgres 시험은 된다

일부러 실제 서비스를 부르는 시험을 돌릴 때만 MEMOIR_TEST_ALLOW_NETWORK=1 로 끈다.
"""

from __future__ import annotations

import os
import socket

KEY_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AZURE_SPEECH_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")
ALLOW_NETWORK = os.environ.get("MEMOIR_TEST_ALLOW_NETWORK") == "1"


BLOCKED: list[str] = []     # 막은 시도 — 시험이 끝나면 개수를 찍는다


class ExternalCallBlocked(RuntimeError):
    """시험 중 외부 API · 외부 연결을 시도했다."""

    def __init__(self, what: str):
        BLOCKED.append(what)
        super().__init__(what)


def pytest_sessionfinish(session, exitstatus):
    state = "꺼짐 (MEMOIR_TEST_ALLOW_NETWORK=1)" if ALLOW_NETWORK else "켜짐"
    print(f"\n[conftest] 외부 호출 차단 {state} · 막은 시도 {len(BLOCKED)}회"
          + (f" — {BLOCKED[:3]}" if BLOCKED else ""))


def _local(address) -> bool:
    host = address[0] if isinstance(address, tuple) else address
    host = str(host)
    return host in LOCAL_HOSTS or host.startswith("127.")


# 모델 · 엔진 설정도 .env 에서 들이지 않는다. 운영 .env 가 모델을 바꾸면(gpt- · claude-)
# 시험이 가짜로 바꿔 둔 Gemini 자리를 지나쳐 다른 길로 가고, 시험 결과가 .env 에 따라
# 달라진다. 시험은 코드의 기본값으로 돈다 — 값이 필요한 시험은 제 안에서 넣는다.
SETTING_PREFIXES = ("MEMOIR_", "POSTCARD_", "GEMINI_", "TTS_", "OPENAI_", "ANTHROPIC_")


def _dotenv_settings() -> list[str]:
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return []
    names = (ln.split("=", 1)[0].strip() for ln in lines if "=" in ln and not ln.lstrip().startswith("#"))
    return [n for n in names if n.startswith(SETTING_PREFIXES) and n != "MEMOIR_TEST_ALLOW_NETWORK"]


for _name in _dotenv_settings():
    os.environ.setdefault(_name, "")

if not ALLOW_NETWORK:
    for _name in KEY_NAMES:
        os.environ[_name] = ""

    import google.genai as _genai

    def _no_client(self, *args, **kwargs):
        raise ExternalCallBlocked("시험 중 Gemini 클라이언트 생성 금지 (tests/conftest.py)")

    _genai.Client.__init__ = _no_client

    _connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex

    def _guarded_connect(self, address):
        if not _local(address):
            raise ExternalCallBlocked(f"시험 중 외부 연결 금지: {address!r}")
        return _connect(self, address)

    def _guarded_connect_ex(self, address):
        if not _local(address):
            raise ExternalCallBlocked(f"시험 중 외부 연결 금지: {address!r}")
        return _connect_ex(self, address)

    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
