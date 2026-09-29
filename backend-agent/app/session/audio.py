"""
오디오 담기 — 브라우저가 보낸 조각들을 전사기에 넘길 한 덩어리로 만든다

**왜 브라우저에서 raw PCM 을 보내는가.**

MediaRecorder 가 주는 webm/mp4 는 한 녹음 세션이 통째로 하나의 파일이다.
그런데 우리는 소리가 있는 구간만 올린다(무음까지 올리면 T1 이 영원히 리셋되어
발화가 확정되지 않는다). 잘라낸 webm 조각들을 이어 붙이면 헤더가 둘, 셋이 되어
어떤 디코더도 첫 조각까지만 읽는다. 어르신의 뒷말이 통째로 사라지는 셈이다.

머리 없는 PCM 은 이어 붙이는 것이 곧 이어 붙이는 것이다. 무음을 들어낸 자리는
그냥 없던 시간이 되고, 마지막에 WAV 머리 하나만 씌우면 온전한 파일이 된다.
tools/replay.py 가 녹음 파일에 하던 일과 정확히 같고, 그래서 그때 잰 숫자가
그대로 옮겨 온다.

값은 16kHz 모노 16비트다. 전화 음성보다 넉넉하고 Azure 가 그 이상을 쓰지 않는다.
초당 32KB 라 10초 발화가 320KB — 압축하지 않는 대신 인코딩이 없다.
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path

from .conf import env_str

log = logging.getLogger("audio")

# 브라우저가 붙여 보내는 mime. rate 는 파라미터로 따라온다.
PCM_MIME = "audio/pcm"
DEFAULT_RATE = 16000


def is_pcm(mime: str) -> bool:
    return mime.split(";")[0].strip().lower() in (PCM_MIME, "audio/l16", "audio/x-pcm")


def pcm_rate(mime: str, default: int = DEFAULT_RATE) -> int:
    """`audio/pcm;rate=16000` 에서 16000 을 꺼낸다. 없거나 이상하면 기본값."""
    for part in mime.split(";")[1:]:
        k, _, v = part.partition("=")
        if k.strip().lower() == "rate":
            try:
                rate = int(v.strip())
            except ValueError:
                break
            if 8000 <= rate <= 48000:
                return rate
            break
    return default


def pcm16_to_wav(pcm: bytes, rate: int = DEFAULT_RATE, channels: int = 1) -> bytes:
    """머리 없는 16비트 PCM 에 WAV 머리를 씌운다. 표본은 건드리지 않는다."""
    pcm = pcm[: len(pcm) - len(pcm) % 2]        # 반 토막 난 표본은 버린다
    byte_rate = rate * channels * 2
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate, byte_rate, channels * 2, 16)
        + b"data" + struct.pack("<I", len(pcm)) + pcm
    )


def for_stt(audio: bytes, mime: str) -> tuple[bytes, str]:
    """
    전사기에 넘길 (바이트, mime). PCM 이면 WAV 로 싸고, 아니면 그대로 통과시킨다.

    그대로 통과시키는 길을 남겨 둔 것은 tools/replay.py 때문이다. 이미 wav 인
    녹음 파일은 다시 쌀 이유가 없다.
    """
    if not is_pcm(mime):
        return audio, mime or "application/octet-stream"
    return pcm16_to_wav(audio, pcm_rate(mime)), "audio/wav"


def dump(audio: bytes, mime: str, stem: str) -> Path | None:
    """
    전사기에 넘기는 바로 그 바이트를 파일로 남긴다. **개발 중에만.**

    잘못 받아 적힌 턴을 가르려면 들어 봐야 한다. 글자만으로는 소리가 잘려서
    올라온 것인지, 온전히 올라왔는데 전사기가 틀린 것인지 구분되지 않고,
    둘은 고칠 자리가 다르다 (앞은 recorder.ts, 뒤는 전사기·힌트).

    STT_DUMP_DIR 을 적어야만 켜지고, PUBLIC_ORIGIN 이 있으면 적어 두어도
    꺼진다. 어르신 목소리를 디스크에 쌓는 일은 동의 없이 서비스에서 할 수
    없다 — 끄는 것을 잊어도 배포에서는 돌지 않게 한다.

    실패해도 전사는 계속된다. 들어 보려고 남기는 파일이 회차를 막으면 안 된다.
    """
    root = env_str("STT_DUMP_DIR")
    if not root or env_str("PUBLIC_ORIGIN"):
        return None
    ext = ".wav" if mime == "audio/wav" else ".bin"
    try:
        d = Path(root)
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{stem}{ext}"
        f.write_bytes(audio)
        return f
    except OSError as e:
        log.warning("전사 오디오를 남기지 못했다 (%s: %s)", type(e).__name__, e)
        return None
