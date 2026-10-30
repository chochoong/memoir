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

**Gemini 로 읽는 갈래가 있다 (실험).** 기본은 위 그대로 Azure 다.

    TTS_PROVIDER=gemini              한 번에 받는다 (synthesize → wav). 들어 보기용 —
                                     2~3초라 예산을 넘기므로 GEMINI_TTS_TIMEOUT 만큼
                                     기다린다. 그만큼 질문이 늦게 나간다
    TTS_PROVIDER=gemini TTS_STREAM=1 조각으로 받아 흘려보낸다 (Speech). 첫 소리 1초 안팎

Gemini 가 실패하면(429 · 시간 초과 · 오류) **Azure 가 대신 읽는다.** 스트리밍에서는
Azure 에도 같은 날 PCM(24kHz 16비트)을 달라고 해서, 화면은 누가 읽었는지 몰라도
같은 길로 튼다. 왜 실험인지는 tts_gemini.py 머리말에 숫자로 적었다.

환경변수는 **함수 안에서** 읽는다. main.py 가 load_dotenv() 를 import 뒤에
호출하기 때문에, 모듈 수준에서 읽으면 .env 가 아직 로드되기 전이라 빈 값을 잡는다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import AsyncIterator
from xml.sax.saxutils import escape

from . import tts_gemini
from .audio import pcm16_to_wav
from .conf import env_flag, env_float, env_str

log = logging.getLogger("tts")

DEFAULT_VOICE = "ko-KR-SunHiNeural"
DEFAULT_RATE = "-8%"
DEFAULT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
# 스트리밍에서 Azure 가 대신 읽을 때. Gemini 조각과 같은 꼴이어야 화면이 한 길로 튼다.
PCM_FORMAT = "raw-24khz-16bit-mono-pcm"
PCM_RATE = 24000
TAIL_SILENCE_MS = 150              # 마지막 음절 뒤에 남기는 무음 (_ssml 참조)

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


def provider() -> str:
    return "gemini" if env_str("TTS_PROVIDER").lower() == "gemini" else "azure"


def streaming() -> bool:
    """조각으로 흘려보내는가. Gemini 일 때만 뜻이 있다 — Azure 는 0.2초면 다 온다."""
    return provider() == "gemini" and env_flag("TTS_STREAM")


def _ssml(text: str) -> str:
    """
    **escape 를 거른다.** 질문은 Gemini 가 지은 문장이라 `&` 나 `<` 가 섞일 수
    있고, 그대로 넣으면 SSML 이 깨져 400 이 온다. 소리가 안 나는 것으로 끝나지만
    원인을 찾기는 어려운 자리다.

    **끝의 무음을 깎는다.** Azure 는 기본으로 마지막 음절 뒤에 1초쯤 무음을
    붙인다. 화면은 파일이 끝나야 수음을 여는데, 어르신은 목소리가 그친 순간
    답을 시작하신다 — 그 1초 동안 말씀의 앞머리가 녹음기에 들어오지 못한다.
    0 으로 자르지 않고 조금 남기는 것은 마지막 음절의 울림까지 잘라 말끝이
    뚝 끊기게 들리지 않게 하려는 것이다.
    """
    voice = os.environ.get("AZURE_TTS_VOICE") or DEFAULT_VOICE
    rate = os.environ.get("AZURE_TTS_RATE") or DEFAULT_RATE
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
        "xmlns:mstts='https://www.w3.org/2001/mstts' xml:lang='ko-KR'>"
        f"<voice name='{escape(voice)}'>"
        f"<mstts:silence type='Tailing-exact' value='{TAIL_SILENCE_MS}ms'/>"
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

    if provider() == "gemini" and tts_gemini.available():
        # 한 번에 받는 갈래다. 예산(1.6초)을 지키면 늘 빈손이라 따로 기다린다.
        wait = env_float("GEMINI_TTS_TIMEOUT", 3.0)
        try:
            pcm, rate = await asyncio.wait_for(tts_gemini.synth(text), timeout=wait)
            trim = Trim(rate)
            pcm = trim.feed(pcm) + trim.end()
            if pcm:
                return pcm16_to_wav(pcm, rate)
            log.warning("Gemini 낭독이 무음뿐이다 — Azure 로 읽는다")
        except asyncio.TimeoutError:
            log.warning("Gemini 낭독 %.1f초 초과 — Azure 로 읽는다", wait)
        except Exception as e:                               # noqa: BLE001
            tts_gemini.note_failure(e)
            log.error("Gemini 낭독 실패 (%s: %s) — Azure 로 읽는다",
                      type(e).__name__, str(e)[:140])

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


async def _post(key: str, region: str, text: str, fmt: str | None = None) -> bytes:
    r = await _client().post(
        _endpoint(region),
        headers={
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": fmt or os.environ.get("AZURE_TTS_FORMAT") or DEFAULT_FORMAT,
            # 이 헤더가 없으면 400 이 온다. Azure TTS 의 요구사항이다.
            "User-Agent": "memoir-agent",
        },
        content=_ssml(text).encode("utf-8"))
    if r.status_code != 200:
        log.error("낭독 HTTP %s — %s", r.status_code, r.text[:140])
        return b""
    return r.content


# ---------------------------------------------------------------- 무음 깎기

FRAME_MS = 10
LOUD = 600                 # 프레임 최댓값이 이보다 크면 소리다 (16비트 기준 -35dBFS 쯤)
LEAD_KEEP_MS = 40          # 첫 소리 앞에 남기는 무음 — 첫 자음이 잘리지 않게


class Trim:
    """
    앞 무음을 걷고 끝 무음을 TAIL_SILENCE_MS 로 맞춘다. **조각을 받는 대로**
    내보낸다 — 끝을 모르는 채로 끝을 깎아야 해서, 조용한 구간은 다음 소리가
    올 때까지 붙잡아 둔다. 문장 사이 쉼은 그렇게 늦게 나가지만 조각이 재생보다
    빨리 오므로 귀에는 차이가 없다.

    **앞을 깎는 것이 곧 첫 소리를 당기는 것이다.** Gemini 는 앞에 260ms 쯤
    무음을 붙이고 (bench_tts.py), 그건 고스란히 어르신이 기다리는 시간이다.
    끝을 깎는 까닭은 Azure 와 같다 — 파일이 끝나야 수음이 열린다 (_ssml 참조).
    Gemini 는 끝에 300ms 쯤을 붙인다.
    """

    def __init__(self, rate: int):
        self.frame = rate * FRAME_MS // 1000 * 2           # 프레임 바이트
        self.lead = rate * LEAD_KEEP_MS // 1000 * 2
        self.tail = rate * TAIL_SILENCE_MS // 1000 * 2
        self.started = False
        self.held = bytearray()

    def _loud(self, buf: bytes | bytearray, i: int) -> bool:
        f = memoryview(buf)[i:i + self.frame].cast("h")
        return max(f, default=0) > LOUD or -min(f, default=0) > LOUD

    def feed(self, pcm: bytes) -> bytes:
        self.held += pcm
        whole = len(self.held) - len(self.held) % self.frame
        loud = [i for i in range(0, whole, self.frame) if self._loud(self.held, i)]
        if not self.started:
            if not loud:
                # 아직 무음뿐이다. 앞에 남길 만큼만 들고 나머지는 버린다.
                keep = len(self.held) - len(self.held) % 2
                del self.held[: max(0, keep - self.lead - self.frame)]
                return b""
            self.started = True
            cut = max(0, loud[0] - self.lead)
            del self.held[:cut]
            loud = [i - cut for i in loud]
        if not loud:
            return b""
        end = loud[-1] + self.frame                        # 마지막 소리 프레임의 끝
        out = bytes(self.held[:end])
        del self.held[:end]
        return out

    def end(self) -> bytes:
        """남은 무음에서 TAIL_SILENCE_MS 만큼만 내보낸다."""
        if not self.started:
            return b""
        out = bytes(self.held[: self.tail])
        self.held.clear()
        return out[: len(out) - len(out) % 2]


# ---------------------------------------------------------------- 스트리밍


class Speech:
    """
    한 질문의 낭독. 조각을 모아 두고, 받으러 온 쪽에 처음부터 흘려준다.

    **합성은 질문이 준비되는 순간 시작한다** (controller._speak) — 화면이 받으러
    오는 때가 아니다. 그 사이에 온 조각은 여기 쌓여 있다가 한꺼번에 나가고,
    그 뒤로는 오는 대로 나간다. Azure 갈래가 T2 안에 숨는 것과 같은 이치다.

    조각은 늘 날 PCM 16비트 모노, rate 는 self.rate 다. 누가 읽었는지는
    self.source 에 남는다 ("gemini" · "azure" · "" = 못 읽었다).
    """

    def __init__(self, text: str):
        self.text = text
        self.rate = PCM_RATE
        self.chunks: list[bytes] = []
        self.done = False
        self.source = ""
        self.first_at: float | None = None             # 첫 소리 조각이 온 시각 (perf_counter)
        self._cond = asyncio.Condition()
        self._task: asyncio.Task | None = None

    @classmethod
    def start(cls, text: str) -> "Speech":
        sp = cls(text)
        sp._task = asyncio.create_task(sp._run())
        return sp

    # -------------------------------------------- 받는 쪽

    @property
    def pending(self) -> bool:
        """소리가 있거나, 아직 만드는 중이다."""
        return bool(self.chunks) or not self.done

    def pcm(self) -> bytes:
        return b"".join(self.chunks)

    async def wait_first(self, timeout: float | None = None) -> bool:
        """첫 소리가 왔으면 True. 소리 없이 끝났거나 시간이 지나면 False."""
        try:
            async with self._cond:
                await asyncio.wait_for(
                    self._cond.wait_for(lambda: bool(self.chunks) or self.done), timeout)
        except asyncio.TimeoutError:
            pass
        return bool(self.chunks)

    async def wait_done(self, timeout: float | None = None) -> None:
        try:
            async with self._cond:
                await asyncio.wait_for(self._cond.wait_for(lambda: self.done), timeout)
        except asyncio.TimeoutError:
            pass

    async def iter_chunks(self) -> AsyncIterator[bytes]:
        """처음부터 끝까지. 받는 쪽이 여럿이어도 각자 처음부터 받는다."""
        i = 0
        while True:
            async with self._cond:
                await self._cond.wait_for(lambda: len(self.chunks) > i or self.done)
                new, finished = self.chunks[i:], self.done
            i += len(new)
            for c in new:
                yield c
            if finished and i >= len(self.chunks):
                return

    def cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    # -------------------------------------------- 만드는 쪽

    async def _push(self, pcm: bytes) -> None:
        if not pcm:
            return
        async with self._cond:
            if self.first_at is None:
                self.first_at = time.perf_counter()
            self.chunks.append(pcm)
            self._cond.notify_all()

    async def _finish(self) -> None:
        async with self._cond:
            self.done = True
            self._cond.notify_all()

    async def _run(self) -> None:
        try:
            if not await self._gemini():
                await self._azure()
        except asyncio.CancelledError:
            raise
        except Exception as e:                               # noqa: BLE001
            log.error("낭독 스트림 실패 (%s: %s)", type(e).__name__, str(e)[:140])
        finally:
            # 취소돼도 받는 쪽을 풀어 준다. 안 그러면 화면의 요청이 영영 매달린다.
            self.done = True
            try:
                async with self._cond:
                    self._cond.notify_all()
            except RuntimeError:
                pass

    async def _gemini(self) -> bool:
        """
        Gemini 로 읽었으면 True. **첫 조각 전에** 실패하면 False — Azure 가 대신한다.
        읽는 도중에 끊기면 True 다. 이미 들려 드린 말을 다른 목소리로 처음부터
        다시 읽는 것보다, 받은 데까지만 읽고 「낭독 끝」으로 넘어가는 게 낫다.
        """
        if not tts_gemini.available():
            return False
        first_wait = env_float("GEMINI_TTS_FIRST_TIMEOUT", 1.3)
        gap_wait = env_float("GEMINI_TTS_GAP_TIMEOUT", 2.0)
        agen = tts_gemini.stream(self.text)
        trim: Trim | None = None
        heard = False
        try:
            wait = first_wait
            while True:
                try:
                    pcm, rate = await asyncio.wait_for(agen.__anext__(), timeout=wait)
                except StopAsyncIteration:
                    break
                if trim is None:
                    self.rate, trim = rate, Trim(rate)
                out = trim.feed(pcm)
                if out:
                    heard = True
                    self.source = "gemini"
                    await self._push(out)
                # 첫 **소리** 전까지는 첫 조각 예산으로 잰다. 앞 무음 조각만 오고
                # 말이 안 나오는 것도 「첫 소리를 못 받았다」이다.
                wait = gap_wait if heard else first_wait
            if trim is not None:
                await self._push(trim.end())
            return heard
        except asyncio.TimeoutError:
            log.warning("Gemini 스트림이 %.1f초 동안 조용하다 — %s",
                        wait, "받은 데까지 읽는다" if heard else "Azure 로 읽는다")
            return heard
        except asyncio.CancelledError:
            raise
        except Exception as e:                               # noqa: BLE001
            tts_gemini.note_failure(e)
            log.error("Gemini 스트림 실패 (%s: %s) — %s", type(e).__name__, str(e)[:140],
                      "받은 데까지 읽는다" if heard else "Azure 로 읽는다")
            return heard
        finally:
            await agen.aclose()

    async def _azure(self) -> None:
        cred = _creds()
        if not cred:
            return
        try:
            pcm = await asyncio.wait_for(
                _post(*cred, self.text, fmt=PCM_FORMAT),
                timeout=env_float("AZURE_TTS_TIMEOUT", DEFAULT_TIMEOUT))
        except asyncio.TimeoutError:
            log.warning("Azure 대신 읽기도 시간 초과 — 글자만 내보낸다")
            return
        self.rate = PCM_RATE
        trim = Trim(PCM_RATE)
        out = trim.feed(pcm) + trim.end()
        if out:
            self.source = "azure"
            await self._push(out)


def stream_factory():
    """
    컨트롤러가 회차를 열 때 부른다. 스트리밍이 켜져 있으면 Speech.start, 아니면
    None — 그러면 컨트롤러는 예전처럼 tts_fn(synthesize) 으로 한 덩어리를 받는다.
    """
    return Speech.start if streaming() else None


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

    # Gemini 도 같은 이유로 깨운다. 안 깨우면 첫 질문의 첫 소리가 2초를 넘겼다
    # (예열한 측정은 0.9초). **한도를 한 번 쓴다** — 하루 100번 중 하나다.
    if provider() != "gemini" or not tts_gemini.available():
        return
    try:
        t0 = time.perf_counter()
        pcm, _ = await asyncio.wait_for(tts_gemini.synth("안녕하세요"), timeout=15)
        log.info("Gemini TTS 예열 완료 (%s · %.1f초 · %d바이트)", tts_gemini._model(),
                 time.perf_counter() - t0, len(pcm))
    except Exception as e:                                   # noqa: BLE001
        tts_gemini.note_failure(e)
        log.warning("Gemini TTS 예열 실패 (%s: %s) — 첫 낭독이 느리거나 Azure 로 읽는다",
                    type(e).__name__, str(e)[:140])


async def aclose() -> None:
    global _CLIENT
    if _CLIENT is not None:
        await _CLIENT.aclose()
        _CLIENT = None
