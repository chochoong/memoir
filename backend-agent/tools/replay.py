"""
녹음 파일을 실제 회차처럼 흘려보낸다 — 마이크 없이 오디오 경로를 돌려보는 도구

    python tools/replay.py                      tools/recordings/turn*.wav 로 3턴
    python tools/replay.py --base https://...   터널 너머의 서버로
    python tools/replay.py --no-realtime        기다리지 않고 몰아서 (빠른 확인용)

**녹음 파일은 저장소에 올리지 않는다** (.gitignore). 사람 목소리라 그렇고,
저마다 자기 목소리로 받아 두는 편이 시험으로도 낫다. 16kHz 모노 wav 면 된다.

--------------------------------------------------------------------------
무음을 걸러내는 게 이 도구의 핵심이다

그냥 파일 전체를 밀어 넣으면 시험이 헐거워진다. 실제 화면은 **소리가 있는
청크만** 올려야 하고, 무음까지 올리면 T1 이 영원히 리셋되어 발화가 확정되지
않는다. 그 판정을 여기서 똑같이 해 본다 — 이 파일의 _voiced() 가 프론트에
들어갈 무음 판정의 초안이다.

wav 는 헤더에 데이터 길이가 박혀 있어서, 무음을 빼고 보내려면 헤더를 다시
써야 한다. 브라우저가 쓸 webm/opus 는 패킷을 이어 붙여도 그대로 유효해서
이 손질이 필요 없다. wav 라서 생기는 일이다.
"""

from __future__ import annotations

import argparse
import array
import json
import math
import ssl
import struct
import sys
import time
import urllib.request
import wave
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

POSTCARD = "1968년 여름, 순애랑 서울 가는 완행열차를 탔다."
CHUNK_SEC = 1.0          # MediaRecorder 의 timeslice 와 같은 자리
SILENCE_RATIO = 0.08     # 최대 음량 대비 이 아래면 무음으로 본다
CTX = ssl.create_default_context()


def _call(base: str, path: str, data: bytes | None = None,
          ctype: str = "application/json") -> dict:
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": ctype, "X-User-Id": "replay"},
        method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=40, context=CTX) as r:
        return json.loads(r.read().decode())


def _voiced(path: Path, chunk_sec: float) -> tuple[bytes, int, int]:
    """
    소리가 있는 구간만 남겨 wav 로 다시 만든다.

    돌려주는 것: (wav 바이트, 보낸 청크 수, 버린 청크 수)

    판정은 청크별 RMS 를 파일 최대치와 견주는 것뿐이다. 실제 화면에서는
    절대 임계값과 이력(hysteresis)이 필요하다 — 조용한 방과 시끄러운 방에서
    최대치가 다르기 때문이다. 여기서는 시험에 필요한 만큼만 한다.
    """
    with wave.open(str(path)) as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise SystemExit(f"{path.name}: 16bit wav 만 받는다 (지금 {sw*8}bit)")

    samples = array.array("h")
    samples.frombytes(raw)
    per = int(sr * chunk_sec) * ch

    blocks = [samples[i:i + per] for i in range(0, len(samples), per)]
    rms = [math.sqrt(sum(int(x) * int(x) for x in b) / len(b)) if len(b) else 0.0
           for b in blocks]
    floor = (max(rms) or 1.0) * SILENCE_RATIO

    kept = array.array("h")
    sent = dropped = 0
    for b, r in zip(blocks, rms):
        if r > floor:
            kept.extend(b)
            sent += 1
        else:
            dropped += 1

    data = kept.tobytes()
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
              struct.pack("<IHHIIHH", 16, 1, ch, sr, sr * ch * 2, ch * 2, 16) +
              b"data" + struct.pack("<I", len(data)))
    return header + data, sent, dropped


def _wait(base: str, sid: str, limit: float = 25.0) -> tuple[dict, float]:
    """PROCESSING 을 빠져나올 때까지. 여기가 어르신이 기다리는 시간이다."""
    t0 = time.perf_counter()
    snap = _call(base, f"/api/sessions/{sid}")
    while time.perf_counter() - t0 < limit:
        snap = _call(base, f"/api/sessions/{sid}")
        if snap["state"] in ("SPEAKING", "CLOSED"):
            break
        time.sleep(0.1)
    return snap, time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--dir", default="tools/recordings")
    ap.add_argument("--glob", default="turn*.wav")
    ap.add_argument("--pace", default="fast", choices=("fast", "normal", "slow"))
    ap.add_argument("--chunk", type=float, default=CHUNK_SEC)
    ap.add_argument("--wav", action="store_true",
                    help="머리 없는 PCM 대신 wav 로 올린다 (통과 경로 확인용)")
    ap.add_argument("--no-realtime", action="store_true",
                    help="청크 사이를 기다리지 않는다. T1 리셋은 시험되지 않는다")
    a = ap.parse_args()

    files = sorted(Path(a.dir).glob(a.glob))
    if not files:
        print(f"{a.dir}/{a.glob} 에 녹음이 없다. 16kHz 모노 wav 를 넣어 두면 된다.")
        return 1

    snap = _call(a.base, "/api/sessions", json.dumps({
        "title": "녹음 재생", "postcard": POSTCARD,
        "pace": a.pace, "max_turn": len(files)}).encode())
    sid = snap["session_id"]
    print(f"회차 {sid[:8]} · {a.pace} · {len(files)}턴")
    print(f"  첫 질문  {snap['next_question']}\n")

    for i, path in enumerate(files, 1):
        audio, sent, dropped = _voiced(path, a.chunk)
        sec = (len(audio) - 44) / 32000
        _call(a.base, f"/api/sessions/{sid}/tts-done", b"{}")

        # 기본은 머리 없는 PCM 이다 — 브라우저(src/recorder.ts)가 보내는 것과
        # 같은 모양이라야 여기서 잰 숫자가 실제 화면으로 옮겨 간다. wav 머리는
        # 발화가 확정될 때 서버가 한 번 씌운다 (app/session/audio.py).
        per = int(16000 * a.chunk) * 2
        body = audio[44:]
        offsets = list(range(0, len(body), per))
        for j, k in enumerate(offsets):
            if a.wav:
                piece = (audio[:44] + body[k:k + per]) if k == 0 else body[k:k + per]
                ctype = "audio/wav"
            else:
                piece, ctype = body[k:k + per], "audio/pcm;rate=16000"
            _call(a.base, f"/api/sessions/{sid}/speech/audio", piece, ctype)
            # 마지막 청크 뒤에는 자지 않는다. 여기서 자면 T1 이 그만큼 일찍 시작한
            # 셈이 되어 아래 「말씀이 끝나고 N초」가 실제보다 짧게 찍힌다.
            if not a.no_realtime and j < len(offsets) - 1:
                time.sleep(a.chunk)

        snap, waited = _wait(a.base, sid)
        frag = snap["fragments"][-1]
        print(f"[턴 {i}] {path.name}  소리 {sent}청크({sec:.1f}초) · 무음 {dropped}청크 버림")
        print(f"  말씀이 끝나고 {waited:.1f}초 뒤 {snap['state']}")
        print(f"  전사  {frag['answer']}")
        if snap["state"] != "CLOSED":
            print(f"  다음  {snap['next_question']}")
        print()
        if snap["state"] == "CLOSED":
            break

    lat = _call(a.base, f"/api/sessions/{sid}/latency")
    print("구간별 지연 (FR-AD-314)")
    for i, t in enumerate(lat["turns"], 1):
        print(f"  턴{i}  전사 {t['stt']:6.0f} · 저장 {t['save']:4.0f} · "
              f"질문 {t['question']:6.0f} · 전달 {t['deliver']:6.0f}   합계 {t['total']:6.0f}ms")
    d = lat["timer_drift"]
    if d:
        print(f"  타이머 격발 오차 최대 {d['max_ms']:.0f}ms · 평균 {d['avg_ms']:.0f}ms (허용 200ms)")
    print(f"\n  마지막 턴은 지연 칸이 없다 — 최대 턴에서는 질문을 만들지 않는다 (FR-IV-006)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
