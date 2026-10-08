# 메모아 API — 배포용 기동 스크립트
#
#   .\run.ps1            평소
#   .\run.ps1 -Dev       개발 (자동 리로드 · 프롬프트도 본다 · 127.0.0.1:8010 직접 접속)
#
# 개발용 `uvicorn app.main:app --reload` 와 다른 점이 셋이고, 셋 다 이유가 있다.
# docs/배포.md 「왜 이 세 옵션인가」 절과 짝이다.

param([switch]$Dev, [switch]$Supabase)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Write-Error ".env 가 없다. .env.example 을 복사해 채운다"
}

# -Supabase   DB 만 Supabase(memoir-dev)로 돌린다. 나머지 설정은 .env 그대로다.
if ($Supabase) {
    if (-not (Test-Path ".env.supabase")) {
        Write-Error ".env.supabase 가 없다. .env.supabase.example 을 복사해 비밀번호를 채운다"
    }
    $env:MEMOIR_DB = "supabase"
} else {
    Remove-Item Env:MEMOIR_DB -ErrorAction SilentlyContinue
}

# MEMOIR_DB 는 이 창(프로세스)에 남는다. 끝날 때 지우지 않으면 같은 창에서
# uvicorn 을 직접 띄웠을 때 -Supabase 없이도 공유 DB 에 붙는다. Ctrl+C 로
# 끊어도 finally 는 돈다.
$code = 0
try {

if ($Dev) {
    # --reload-dir app --reload-dir 첨부프롬프트_md --reload-include "*/첨부프롬프트_md/*.md"
    #   감시기는 기본이 *.py 뿐이다. 프롬프트(첨부프롬프트_md\*.md)를 고쳐도 서버는
    #   모른다 — prompt.load() 가 lru_cache 라 기동 때 읽은 것을 프로세스가
    #   죽을 때까지 쓴다. .py 를 같이 건드린 날만 곁다리로 적용돼서, 될 때도
    #   있고 안 될 때도 있는 것처럼 보였다.
    #
    #   캐시를 비우는 라우트(prompt.reload)를 두지 않고 재시작을 고른 까닭은
    #   **회차마다 규칙이 고정된다**는 보장을 깨지 않기 위해서다. 진행 중인
    #   회차 한가운데서 갈아끼우면 같은 회차의 앞 턴과 뒤 턴이 다른 프롬프트로
    #   움직인다. 같은 대본을 여러 판 돌려 재는 작업에서 그건 오염이고,
    #   기록에는 어느 판이 어느 규칙이었는지 남지 않는다.
    #
    #   **평소 자세에는 붙이지 않는다.** 배포 중에 프롬프트를 저장하면 서버가
    #   그 자리에서 재시작되고, 진행 중인 회차가 끊긴다 (docs/배포.md 「지금
    #   알고 있는 한계」). 거기서는 파일을 고친 뒤 사람이 다시 띄운다.
    #
    #   감시 폴더를 둘로 좁힌다. 폴더를 안 주면 backend-agent 전체를 보고,
    #   그러면 README·docs 의 .md 를 고칠 때도 재시작된다.
    #
    #   **패턴을 "*.md" 로 쓰지 않는다.** Windows 에서 uvicorn(click)은 인자의
    #   와일드카드를 넘기기 전에 현재 폴더에서 펼친다. "*.md" 는 README.md 한
    #   개가 되어 프롬프트를 고쳐도 아무 일도 없었다 (예전 "*.txt" 도
    #   requirements.txt 가 되어 같은 꼴이었다). "*/첨부프롬프트_md/*.md" 는
    #   현재 폴더에서 펼칠 것이 없어 그대로 넘어가고, 감시기는 경로를 오른쪽부터
    #   맞추므로 프롬프트 파일에 걸린다.
    python -m uvicorn app.main:app --reload `
        --reload-dir app --reload-dir 첨부프롬프트_md `
        --reload-include "*/첨부프롬프트_md/*.md" `
        --port 8010
    $code = $LASTEXITCODE

} else {

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
$code = $LASTEXITCODE

}

} finally {
    Remove-Item Env:MEMOIR_DB -ErrorAction SilentlyContinue
}
exit $code
