"""
낭독 — Azure Neural TTS

전사(stt.py)와 같은 키·같은 지역을 쓴다. 호스트만 다르다.
    전사  {region}.api.cognitive.microsoft.com
    낭독  {region}.tts.speech.microsoft.com

**합성은 T2 안에 숨는다.** 이 설계의 핵심이 여기서 한 번 더 쓰인다.

    T1 만료 ──▶ T2 카운트다운 ────────────────────────┐
            └▶ 전사 → 질문 생성 → 낭독 합성 (비동기) ┘
                                                    셋 다 끝나야 다음 질문이 나간다

질문은 실측 1.3초쯤에 준비되는데 T2 최솟값은 3.0초다. 남는 1.7초가 합성 예산이다.
그래서 어르신 귀에는 침묵이 끝나는 순간 곧바로 목소리가 나온다. 질문이 준비된
**뒤에** 합성을 시작하면 그 시간이 그대로 기다림이 된다 — 순서가 전부다.

**목소리를 왜 이 값으로 골랐나.**

    ko-KR-SunHiNeural   표준 여성. 또렷하고 높낮이가 과하지 않다
    rate -8%            어르신 대상이다. 기본 속도는 빠르다
    24kHz 48kbps mp3    폰에서 받는 시간이 짧다. 말소리에 이 이상은 들리지 않는다

`AZURE_TTS_VOICE` · `AZURE_TTS_RATE` 로 바꿀 수 있게 두었다. 실제 어르신께
들려 드리고 고르는 게 맞지, 여기서 정할 일이 아니다.

**실패는 회차를 끝내지 않는다.** 빈 바이트를 돌려주면 화면은 글자만 띄우고
「낭독 끝」 버튼으로 넘어간다. 어르신은 소리 없이 글을 읽게 되지만 회차는 산다.

환경변수는 **함수 안에서** 읽는다. main.py 가 load_dotenv() 를 import 뒤에
호출하기 때문에, 모듈 수준에서 읽으면 .env 가 아직 로드되기 전이라 빈 값을 잡는다.
"""

from __future__ import annotations

import asyncio
import logging
import os
from xml.sax.saxutils import escape

log = logging.getLogger("tts")

DEFAULT_VOICE = "ko-KR-SunHiNeural"
DEFAULT_RATE = "-8%"
DEFAULT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"

# 예산은 T2 최솟값(3.0초)에서 질문 생성이 쓰고 남은 자리다. 실측 질문 p90 이
# 1.1초쯤이라 1.9초가 남는데, 거기서 폰이 받아 가는 시간까지 빼야 한다.
# 넘기면 소리 없이 글자만 나가고, 그건 회차가 끊기는 것보다는 훨씬 낫다.
DEFAULT_TIMEOUT = 1.6

# 한 문장 질문이다. 이보다 길면 프롬프트가 무너진 것이라 합성할 일이 아니다.
MAX_CHARS = 300

_CLIENT = None
_WARNED = False


def _endpoint(region: str) -> str:
    return f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"


def _client():
    """stt.py 와 따로 둔다. 호스트가 달라 연결 풀을 나눠 쓸 수 없다."""
    global _CLIENT
    if _CLIENT is None:
        import httpx
        _CLIENT = httpx.AsyncClient(timeout=10)
    return _CLIENT


def _creds() -> tuple[str, str] | None:
    key = (os.environ.get("AZURE_SPEECH_KEY") or "").strip()
    region = (os.environ.get("AZURE_SPEECH_REGION") or "").strip()
    if key and region:
        return key, region
    global _WARNED
    if not _WARNED:
        _WARNED = True
        log.warning("AZURE_SPEECH_KEY/REGION 이 없다 — 질문은 글자로만 나간다")
    return None


def _ssml(text: str) -> str:
    """
    **escape 를 거른다.** 질문은 Gemini 가 지은 문장이라 `&` 나 `<` 가 섞일 수
    있고, 그대로 넣으면 SSML 이 깨져 400 이 온다. 소리가 안 나는 것으로 끝나지만
    원인을 찾기는 어려운 자리다.
    """
    voice = os.environ.get("AZURE_TTS_VOICE") or DEFAULT_VOICE
    rate = os.environ.get("AZURE_TTS_RATE") or DEFAULT_RATE
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
        "xml:lang='ko-KR'>"
        f"<voice name='{escape(voice)}'>"
        f"<prosody rate='{escape(rate)}'>{escape(text)}</prosody>"
        "</voice></speak>"
    )


async def synthesize(text: str) -> bytes:
    """
    질문 한 문장을 mp3 로. **실패하면 빈 바이트다. 예외를 올리지 않는다.**

    전사(stt.py)와 정반대의 실패 정책이다. 전사가 실패하면 어르신의 말씀이
    사라지니 예산을 넘겨서라도 받아 왔지만, 낭독이 실패하면 글자는 그대로 남는다.
    그래서 여기서는 **예산을 지키는 쪽**을 고른다 — 늦게 나오는 목소리보다
    제때 나오는 글자가 낫다.
    """
    text = (text or "").strip()
    cred = _creds()
    if not cred or not text:
        return b""
    if len(text) > MAX_CHARS:
        log.error("질문이 %d자다 — 합성하지 않는다 (한 문장이어야 한다)", len(text))
        return b""

    key, region = cred
    try:
        timeout = float(os.environ.get("AZURE_TTS_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        timeout = DEFAULT_TIMEOUT

    try:
        return await asyncio.wait_for(_post(key, region, text), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("낭독 합성 %.1f초 초과 — 글자만 내보낸다 (회차는 계속)", timeout)
    except Exception as e:                                   # noqa: BLE001
        log.error("낭독 합성 실패 (%s: %s)", type(e).__name__, str(e)[:140])
    return b""


async def _post(key: str, region: str, text: str) -> bytes:
    r = await _client().post(
        _endpoint(region),
        headers={
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": os.environ.get("AZURE_TTS_FORMAT") or DEFAULT_FORMAT,
            # 이 헤더가 없으면 400 이 온다. Azure TTS 의 요구사항이다.
            "User-Agent": "memoir-agent",
        },
        content=_ssml(text).encode("utf-8"))
    if r.status_code != 200:
        log.error("낭독 HTTP %s — %s", r.status_code, r.text[:140])
        return b""
    return r.content


async def warmup() -> None:
    """
    TLS 연결을 미리 맺는다. 첫 합성이 느려지는 이유의 대부분이 여기다.

    전사 예열과 달리 **실제로 한 문장을 합성한다.** 낭독은 음성 모델을 지역에서
    처음 깨우는 비용이 따로 있어서, 붙기만 해서는 그게 안 사라진다. 글자 수가
    적어 비용은 무시할 만하다.
    """
    cred = _creds()
    if not cred:
        return
    try:
        # **synthesize() 를 거치지 않는다.** 그쪽은 1.6초 예산을 지키는 게 일이라,
        # 모델을 처음 깨우는 호출이 그 안에 들어올 리가 없다. 실제로 예열이
        # 「1.6초 초과 → 0바이트」로 끝나 예열이 아무것도 안 하고 있었다.
        # 여기서는 어르신이 기다리는 게 아니라 기동이 기다리는 것이므로 넉넉히 준다.
        n = len(await asyncio.wait_for(_post(*cred, "안녕하세요"), timeout=10))
        log.info("Azure TTS 예열 완료 (%d바이트)", n)
    except Exception as e:                                   # noqa: BLE001
        log.warning("Azure TTS 예열 실패 (%s) — 첫 낭독이 느릴 수 있다",
                    type(e).__name__)


async def aclose() -> None:
    global _CLIENT
    if _CLIENT is not None:
        await _CLIENT.aclose()
        _CLIENT = None
