#!/usr/bin/env bash
# 내말싸미 서버 — EC2(Ubuntu 24.04) 세팅. 여러 번 돌려도 된다 (이미 된 것은 건너뛴다).
#
#   curl -fsSL https://raw.githubusercontent.com/chochoong/memoir/develop/backend-agent/deploy/ec2/setup.sh -o setup.sh
#   bash setup.sh
#
# 하는 것
#   1. 시간대 Asia/Seoul · 패키지(git · python3 venv) 설치
#   2. 코드 받기 (/home/ubuntu/memoir, develop 브랜치)
#   3. 가상환경 · requirements 설치
#   4. memoir 서비스 등록 — .env 가 있을 때만 켠다
#   5. cloudflared 설치 · 서비스 파일만 둔다 — **켜지 않는다** (README 「옮기기」 단계에서 켠다)
#
# 하지 않는 것: .env · 터널 키 복사 (비밀이 들어 있어 손으로 옮긴다), DB 변경 (RDS 그대로 쓴다)

set -euo pipefail

REPO=https://github.com/chochoong/memoir.git
BRANCH=develop
HOME_DIR=/home/ubuntu
APP=$HOME_DIR/memoir
BE=$APP/backend-agent
HERE=$BE/deploy/ec2

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

if [ "$(id -un)" != "ubuntu" ]; then
  echo "ubuntu 사용자로 돌린다 (sudo 없이 bash setup.sh). 지금: $(id -un)"; exit 1
fi

say "1. 시간대 · 패키지"
sudo timedatectl set-timezone Asia/Seoul
sudo apt-get update -y
sudo apt-get install -y git python3 python3-venv python3-pip curl
python3 --version

say "2. 코드 ($BRANCH)"
if [ -d "$APP/.git" ]; then
  git -C "$APP" fetch origin
  git -C "$APP" checkout "$BRANCH"
  git -C "$APP" merge --ff-only "origin/$BRANCH"
else
  git clone -b "$BRANCH" "$REPO" "$APP"
fi
git -C "$APP" log --oneline -1

say "3. 가상환경 · 패키지"
[ -d "$BE/.venv" ] || python3 -m venv "$BE/.venv"
"$BE/.venv/bin/pip" install -q --upgrade pip
"$BE/.venv/bin/pip" install -q -r "$BE/requirements.txt"
"$BE/.venv/bin/python" -c "import fastapi, asyncpg, google.genai, anthropic, pillow_heif; print('패키지 확인 완료')"

say "4. memoir 서비스"
sudo cp "$HERE/memoir.service" /etc/systemd/system/memoir.service
sudo systemctl daemon-reload
sudo systemctl enable memoir >/dev/null
if [ -f "$BE/.env" ]; then
  sudo systemctl restart memoir
  echo "서버를 켰다 — 10초 뒤 상태를 본다"
  sleep 10
  if curl -fsS http://127.0.0.1:8010/api/health >/dev/null; then echo "health OK"; else echo "health 실패 — journalctl -u memoir -n 50"; fi
  journalctl -u memoir --since "1 min ago" --no-pager | grep -E "화면 파일|DB 연결|DB 없이|Error|오류" || true
else
  echo "⚠ $BE/.env 가 없다 — 서비스는 등록만 했다. .env 를 옮긴 뒤: sudo systemctl restart memoir"
fi

say "5. cloudflared (설치만 · 켜지 않는다)"
if ! command -v cloudflared >/dev/null; then
  sudo mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
    | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y cloudflared
fi
cloudflared --version
sudo mkdir -p /etc/cloudflared
sudo cp "$HERE/cloudflared.service" /etc/systemd/system/cloudflared.service
sudo systemctl daemon-reload
if [ -f /etc/cloudflared/config.yml ]; then
  echo "터널 설정 있음 — 옮길 때: sudo systemctl enable --now cloudflared"
else
  echo "⚠ /etc/cloudflared/config.yml 이 없다 — README 「터널 키 옮기기」"
fi

say "끝"
echo "다음: README.md 의 남은 단계 (.env · 터널 키 · 옮기기)"
