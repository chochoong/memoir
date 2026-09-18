# 메모아 API — 배포용 기동 스크립트
#
#   .\run.ps1            평소
#   .\run.ps1 -Dev       개발 (자동 리로드 · 127.0.0.1:8010 직접 접속)
#
# 개발용 `uvicorn app.main:app --reload` 와 다른 점이 셋이고, 셋 다 이유가 있다.
# docs/배포.md 「왜 이 세 옵션인가」 절과 짝이다.

param([switch]$Dev)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Write-Error ".env 가 없다. .env.example 을 복사해 채운다"
}

if ($Dev) {
    python -m uvicorn app.main:app --reload --port 8010
    exit $LASTEXITCODE
}

if (-not (Test-Path "web\index.html")) {
    Write-Warning "web\index.html 이 없다 — 화면이 안 나온다. frontend-client 에서 npm run build 한 뒤 dist 를 web\ 에 넣는다 (docs/배포.md 5단계)"
}

# --host 127.0.0.1
#   **0.0.0.0 으로 열지 않는다.** 이 포트가 공유기 밖으로 나가는 순간 터널을
#   거치지 않고 들어오는 길이 생기고, 그 길로 온 요청에는 CF-Connecting-IP 가
#   없다 — 생성 상한이 IP 를 못 세고 전부 127.0.0.1 한 칸에 들어간다.
#   인터넷에서 오는 길은 터널 하나뿐이어야 한다.
#
# --proxy-headers --forwarded-allow-ips 127.0.0.1
#   터널이 TLS 를 끝내고 평문으로 넘기므로 이 서버에는 http 로 보인다.
#   X-Forwarded-Proto 를 읽어 https 로 잡아 준다 — 쿠키의 Secure 가 여기 달렸다.
#   믿는 상대를 127.0.0.1 로 못 박는다. 비워 두면 아무나 보낸 헤더를 믿는다.
#
# --workers 1
#   회차는 프로세스 메모리에 있다. 둘로 띄우면 폴링이 다른 워커로 가서 회차를
#   못 찾고, 어르신 화면에서 회차가 무작위로 사라진다. 늘리려면 상태를 밖으로
#   빼야 한다 (controller.py 레지스트리 주석).
python -m uvicorn app.main:app `
    --host 127.0.0.1 --port 8010 `
    --proxy-headers --forwarded-allow-ips 127.0.0.1 `
    --workers 1 `
    --log-level info
