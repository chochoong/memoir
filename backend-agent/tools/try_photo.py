"""
사진 한 장을 실제 Gemini 로 분석해 본다. DB·서버 없이 app.session.photo 만 부른다.

    python tools\\try_photo.py 사진경로.jpg
    python tools\\try_photo.py 사진경로.png image/png
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv                                    # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.session.photo import analyze_photo                       # noqa: E402

_MIME_BY_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp",
}


def main() -> int:
    if len(sys.argv) < 2:
        print("사용법: python tools/try_photo.py <사진 경로> [mime_type]")
        return 1

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"{path} 가 없다")
        return 1

    mime = sys.argv[2] if len(sys.argv) > 2 else _MIME_BY_EXT.get(path.suffix.lower(), "image/jpeg")
    print(f"분석 중 — {path.name} ({mime})")

    data = asyncio.run(analyze_photo(path.read_bytes(), mime))
    if data is None:
        print("분석 실패 — 로그를 확인한다 (키 없음 · 타임아웃 · 응답 오류 중 하나)")
        return 1

    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
