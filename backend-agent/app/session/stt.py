"""
전사 — Azure Fast Transcription (배치)

`controller.SttFn` 자리에 그대로 들어간다. question.py 와 같은 모양이고,
FSM 도 타이머도 이 파일의 존재를 모른다.

**왜 Azure 인가.** whisper-1 과 같은 조건으로 각 10회씩 재고 골랐다.

    음성 14.6초   중앙값    p90
    whisper-1     1927ms   2236ms   편차 819~2331 (2.8배)
    Azure          897ms    921ms   편차 868~1046 (1.2배)

중앙값이 두 배 빠른 것보다 **편차가 붙어 있는 게 더 중요했다.** 타이머 예산으로
도는 설계에서는 p90 이 설계를 정한다. whisper-1 은 p90 2236 + 질문 875 = 3.1초라
T2 최솟값 3.0초를 넘겨서, 침묵이 시작되는 순간 전사를 미리 쏘고 어르신이 말을
이으면 취소하는 투기적 호출을 만들어야 했다. Azure 는 921 + 875 = 1.8초라 그게
통째로 필요 없다. 지금 구조에 한 줄 넣으면 끝난다.

정확도는 120자 기준 글자 오류율로 whisper 4.2% · whisper+씨앗 0.8% · Azure 1.7%
였다. Azure 가 지명·인명을 맞히고 조사·어미에서 틀리는 쪽이라, 회고록에는 이쪽이
덜 아프다고 봤다. **다만 이 수치는 TTS 로 만든 깨끗한 음성 기준이다.** 실제 어르신
말씀은 사투리·떨림·잡음이 섞여 순위가 뒤집힐 수 있다. 그래서 이 함수는 갈아 끼울
수 있게 두었다 — controller.stt_fn 을 바꾸면 된다.

**실패는 회차를 끝내지 않는다.** 전사에 실패하면 빈 문자열을 돌려주고, controller 는
그걸 빈 발화로 보아 턴을 소모하지 않는다 (FR-AD-312). 어르신에게는 다시 여쭙는
것으로 보인다. 회차가 끊기는 것보다 낫다.

환경변수는 **함수 안에서** 읽는다. main.py 가 load_dotenv() 를 import 뒤에
호출하기 때문에, 모듈 수준에서 읽으면 .env 가 아직 로드되기 전이라 빈 값을 잡는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

log = logging.getLogger("stt")

API_VERSION = "2024-11-15"
DEFAULT_LOCALE = "ko-KR"

# 실측 p90 이 15초 음성에 921ms, 34초 음성에 1656ms 다. 6초는 「느린 것」이 아니라
# 「무언가 잘못된 것」을 가르는 선이다.
#
# 예산(T2 3초)보다 길게 잡은 것은 일부러다. 전사가 실패하면 **어르신이 방금 하신
# 말씀이 사라진다.** 그건 다음 질문이 몇 초 늦는 것과 비교할 일이 아니다.
# 늦더라도 받아 오는 쪽을 고른다.
DEFAULT_TIMEOUT = 6.0

# 포기한 뒤에도 응답을 이만큼 더 기다려 본다. 늦게 온 응답만이 「왜 늦었나」를
# 말해 준다 — 쓰로틀인지 정말 느린 것인지 끊긴 것인지는 응답에만 적혀 있다.
# 무한히 두지는 않는다.
LATE_GRACE = 10.0

_CLIENT = None
_WARNED = False

# 요청 일련번호. 뒤늦게 도착한 줄이 어느 요청 것인지 로그에서 가리려면 필요하다 —
# 그 줄은 이미 다음 턴이 시작된 뒤에 끼어든다.
_SEQ = 0
# 포기한 뒤에도 도는 태스크를 붙들어 둔다. 이벤트 루프는 태스크를 약한 참조로만
# 잡아서, 아무도 안 잡고 있으면 실행 중에 사라질 수 있다.
_LATE: set = set()


def _endpoint(region: str) -> str:
    return (f"https://{region}.api.cognitive.microsoft.com"
            f"/speechtotext/transcriptions:transcribe?api-version={API_VERSION}")


def _client():
    """httpx 클라이언트는 한 번만 만들어 재사용한다. 연결을 재사용해야 빠르다."""
    global _CLIENT
    if _CLIENT is None:
        import httpx
        _CLIENT = httpx.AsyncClient(timeout=30)
    return _CLIENT


def _creds() -> tuple[str, str] | None:
    key = (os.environ.get("AZURE_SPEECH_KEY") or "").strip()
    region = (os.environ.get("AZURE_SPEECH_REGION") or "").strip()
    if key and region:
        return key, region
    global _WARNED
    if not _WARNED:
        _WARNED = True
        log.warning("AZURE_SPEECH_KEY/REGION 이 없다 — 오디오는 전사되지 않는다")
    return None


def _definition(hint: str | None) -> dict:
    """
    hint 는 씨앗·직전 답변에서 온다. 인명·지명을 phraseLists 로 흘려 넣는다.

    **효과는 확인하지 못했다.** 시험 음성에서는 Azure 가 이미 「서울」을 맞혀서
    차이가 나타나지 않았다. 비용이 없고 실제 녹음에서 지명·인명이 틀릴 때
    기댈 자리라 넣어 두었다. 도움이 안 된다고 판명되면 이 줄만 지우면 된다.
    """
    d: dict = {"locales": [os.environ.get("AZURE_STT_LOCALE", DEFAULT_LOCALE)]}
    if hint:
        phrases = [w for w in (hint.replace("\n", " ").split()) if len(w) > 1][:40]
        if phrases:
            d["phraseLists"] = phrases
    return d


async def azure_transcribe(audio: bytes, mime: str = "audio/wav",
                           hint: str | None = None) -> str:
    """
    오디오 한 덩어리를 글로. **실패하면 빈 문자열이다. 예외를 올리지 않는다.**

    429 는 한 번만 다시 시도한다. 측정 중 연속 호출에서 실제로 걸렸다 —
    무료 티어면 실사용에서도 걸린다. 재시도는 예산을 먹으므로 한 번까지다.

    **시간이 넘어도 요청을 취소하지 않는다.** 취소하면 응답이 이 프로세스에
    도달하지 못하고, 그러면 로그에 남는 것은 「시간 초과」뿐이다. 그건 증상이지
    원인이 아니다 — 쓰로틀(429)인지 정말 느린 것인지 끊긴 것인지가 구분되지 않고,
    아래 _post 의 429 처리도 응답보다 먼저 취소되면 닿지 못한다.

    어르신을 기다리게 하지 않는 것과 원인을 아는 것은 양립한다. **기다리는 쪽만
    그만두고(shield) 응답은 뒤에서 받아 적는다.** 예산은 그대로 지킨다.
    """
    cred = _creds()
    if not cred or not audio:
        return ""
    key, region = cred
    timeout = float(os.environ.get("AZURE_STT_TIMEOUT", DEFAULT_TIMEOUT))
    deadline = time.perf_counter() + timeout

    global _SEQ
    _SEQ += 1
    seq = _SEQ

    task = asyncio.create_task(_post(key, region, audio, mime, hint, deadline))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except asyncio.TimeoutError:
        log.error("전사 #%d 를 %.1f초 안에 못 받았다 — 이 턴의 말씀을 받지 못했다",
                  seq, timeout)
        _report_late(task, seq)
    except asyncio.CancelledError:
        # 회차가 닫히는 길이다. 기다리는 사람도, 그 답을 적어 둘 회차도 없다.
        task.cancel()
        raise
    except Exception as e:                                   # noqa: BLE001
        log.error("전사 #%d 실패 (%s: %s)", seq, type(e).__name__, str(e)[:140])
    return ""


def _report_late(task: "asyncio.Task", seq: int) -> None:
    """
    포기한 요청을 살려 둔 채 결과만 받아 적는다.

    완료 콜백에서 exception() 을 반드시 읽는다. 안 읽으면 이벤트 루프가
    「retrieved 되지 않은 예외」를 따로 뱉어 같은 실패가 두 겹으로 남는다.

    **늦게 도착한 성공 결과는 버린다.** 회차는 이미 다음으로 갔고, 뒤늦은 글을
    끼워 넣으면 조각 순서가 어긋난다. 어르신 말씀을 잃는 것도 아니다 —
    controller._after_empty 가 버퍼를 비우지 않아 같은 오디오가 다시 올라간다.
    """
    started = time.perf_counter()
    _LATE.add(task)

    def done(t: "asyncio.Task") -> None:
        _LATE.discard(t)
        late = (time.perf_counter() - started) * 1000
        if t.cancelled():
            log.warning("전사 #%d — 유예 %.0f초가 지나 요청을 접었다", seq, LATE_GRACE)
            return
        e = t.exception()
        if e is not None:
            log.error("전사 #%d 뒤늦은 실패 (%s: %s) — 포기 후 %.0fms",
                      seq, type(e).__name__, str(e)[:140], late)
        else:
            text = t.result()
            log.warning("전사 #%d 뒤늦게 도착 — %s (포기 후 %.0fms)",
                        seq, f"{len(text)}자" if text else "빈 결과", late)

    task.add_done_callback(done)
    asyncio.get_running_loop().call_later(
        LATE_GRACE, lambda: None if task.done() else task.cancel())


async def _post(key: str, region: str, audio: bytes, mime: str,
                hint: str | None, deadline: float) -> str:
    client = _client()
    files = {
        "audio": ("utterance", audio, mime or "application/octet-stream"),
        "definition": (None, json.dumps(_definition(hint)), "application/json"),
    }
    for attempt in (1, 2):
        sent = time.perf_counter()
        r = await client.post(_endpoint(region),
                              headers={"Ocp-Apim-Subscription-Key": key}, files=files)
        took = (time.perf_counter() - sent) * 1000
        if r.status_code == 429 and attempt == 1:
            # 응답에 걸린 시간과 Retry-After 유무를 같이 남긴다. 429 는 한 모양이
            # 아니다 — 곧바로 오며 Retry-After 를 주는 것과, 한참 뒤에 오며 아무
            # 것도 주지 않는 것이 있고, 뒤쪽은 예산을 이미 넘긴 채로 도착한다.
            after = r.headers.get("Retry-After")
            wait = float(after or 1)
            if time.perf_counter() + wait >= deadline:
                log.error("429 — 재시도할 예산이 없다 (응답 %.0fms · Retry-After %s)",
                          took, after or "없음")
                return ""
            log.warning("429 — %.1f초 뒤 한 번 다시 시도한다 (응답 %.0fms)", wait, took)
            await asyncio.sleep(wait)
            continue
        if r.status_code != 200:
            log.error("전사 HTTP %s (%.0fms) — %s", r.status_code, took, r.text[:140])
            return ""
        body = r.json()
        return " ".join(p.get("text", "") for p in body.get("combinedPhrases", [])).strip()
    return ""


async def warmup() -> None:
    """
    TLS 연결을 미리 맺는다. 실측 첫 호출 1655ms, 이후 200~900ms 였다.

    전사를 한 번 돌리는 대신 호스트에 그냥 붙기만 한다 — 예열하자고 유료 호출을
    쓰거나 429 예산을 깎을 이유가 없다. 404 가 와도 목적은 달성된다.
    """
    cred = _creds()
    if not cred:
        return
    _, region = cred
    try:
        await asyncio.wait_for(
            _client().get(f"https://{region}.api.cognitive.microsoft.com/"), timeout=5)
        log.info("Azure STT 예열 완료")
    except Exception as e:                                   # noqa: BLE001
        log.warning("Azure STT 예열 실패 (%s) — 첫 전사가 조금 느릴 뿐이다",
                    type(e).__name__)


async def aclose() -> None:
    global _CLIENT
    if _CLIENT is not None:
        await _CLIENT.aclose()
        _CLIENT = None
