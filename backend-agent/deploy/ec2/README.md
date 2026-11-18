# EC2 로 서버 옮기기

지금: 이 PC(Windows) 의 uvicorn + Cloudflare 터널 → AWS RDS
옮긴 뒤: EC2(Ubuntu) 의 uvicorn + **같은** Cloudflare 터널 → **같은** AWS RDS

주소(naemalssami.com) · 구글 로그인 · 보낸 초대 링크 · DB 는 그대로다. 바뀌는 것은 서버가 도는 컴퓨터뿐이다.

| 파일 | 하는 일 |
|---|---|
| `setup.sh` | 패키지 · 코드 · 가상환경 · 서비스 등록 (여러 번 돌려도 된다) |
| `memoir.service` | 서버를 늘 켜 둔다 — 죽거나 재부팅해도 다시 뜬다 |
| `cloudflared.service` | 터널을 늘 켜 둔다 — **옮기는 순간에만 켠다** |
| `cloudflared.config.example.yml` | 터널 설정 본 |

---

## 1. EC2 만들기 (AWS 콘솔)

- 리전 **서울 ap-northeast-2** (RDS 와 같게)
- AMI **Ubuntu Server 24.04 LTS**, 유형 **t3.small** (메모리 2GB)
- 키 페어: 새로 만들어 `.pem` 을 안전한 곳에 둔다
- 보안 그룹(인바운드): **SSH 22 — 내 IP 만**. 80 · 443 · 8010 은 **열지 않는다** (터널이 밖으로 나가서 맺는다)
- 저장소 20GB

## 2. RDS 가 EC2 를 받게

RDS → 보안 그룹 → 인바운드에 **PostgreSQL 5432, 소스 = EC2 의 보안 그룹** 을 더한다.
(이 PC 의 IP 허용은 옮기기가 끝나고 며칠 뒤에 지운다 — 되돌릴 길이다.)

## 3. 세팅 스크립트

```bash
ssh -i <키.pem> ubuntu@<EC2 공인 IP>
curl -fsSL https://raw.githubusercontent.com/chochoong/memoir/develop/backend-agent/deploy/ec2/setup.sh -o setup.sh
bash setup.sh
```

처음에는 `.env` 가 없어 서버는 등록만 된다. 정상이다.

## 4. .env 옮기기 (PC → EC2)

비밀이 들어 있다. **메신저 · 메일 · Git 에 올리지 않는다.** PC 의 PowerShell 에서:

```powershell
scp -i <키.pem> C:\workspace\memoir\backend-agent\.env ubuntu@<EC2 IP>:/home/ubuntu/memoir/backend-agent/.env
```

EC2 에서:

```bash
chmod 600 ~/memoir/backend-agent/.env
sudo systemctl restart memoir
journalctl -u memoir -n 30 --no-pager | grep -E "화면 파일|DB 연결|DB 없이"
curl -s http://127.0.0.1:8010/api/health
```

`DB 연결 · 스키마 확인 완료` 가 보여야 한다. `DB 없이 간다` 면 2번(RDS 보안 그룹)을 다시 본다.

## 5. 터널 키 옮기기 (PC → EC2)

PC 의 `%USERPROFILE%\.cloudflared\` 에 있는 `<터널-ID>.json` 하나만 옮긴다 (`cert.pem` 은 필요 없다).

```powershell
scp -i <키.pem> $env:USERPROFILE\.cloudflared\<터널-ID>.json ubuntu@<EC2 IP>:/home/ubuntu/
```

EC2 에서:

```bash
sudo mv ~/<터널-ID>.json /etc/cloudflared/
sudo chmod 600 /etc/cloudflared/<터널-ID>.json
sudo cp ~/memoir/backend-agent/deploy/ec2/cloudflared.config.example.yml /etc/cloudflared/config.yml
sudo nano /etc/cloudflared/config.yml      # <터널-ID> 두 군데를 채운다
```

**아직 cloudflared 를 켜지 않는다.**

## 6. 옮기기 (몇십 초)

같은 터널을 PC 와 EC2 가 **동시에** 잡으면 Cloudflare 가 요청을 둘로 나눈다 — 인터뷰 도중
다른 서버로 가면 회차를 잃는다. 그래서 **PC 쪽을 먼저 끄고** EC2 를 켠다.

1. 진행 중인 인터뷰 · 자서전 작업이 없는지 본다 (PC 서버 `/api/health` 의 live 0, 로그에 끝나지 않은 「자서전 작업」 없음)
2. PC: 터널 끄기 — 관리자 PowerShell `Stop-Service cloudflared` , 그리고 서버(8010) 끄기
3. EC2: `sudo systemctl enable --now cloudflared`
4. 확인: 브라우저로 https://naemalssami.com — 구글 로그인 · 책 보기 · 인터뷰 한 턴
   EC2 에서 `journalctl -u memoir -f` 로 요청이 들어오는지 본다
5. PC: 터널이 재부팅 때 다시 켜지지 않게 — 관리자 PowerShell `Set-Service cloudflared -StartupType Disabled`

## 되돌리기

EC2: `sudo systemctl disable --now cloudflared` → PC: `Start-Service cloudflared` , 서버 다시 켜기.
DB 는 같은 RDS 라 되돌려도 자료가 갈라지지 않는다.

## 옮긴 뒤 평소 일

| 할 일 | 명령 (EC2) |
|---|---|
| 새 코드 받기 | `cd ~/memoir && git pull --ff-only` |
| 화면만 바뀌었을 때 | 받기만 하면 끝 (`WEB_INDEX=../prototype/index.html`) |
| 서버 코드가 바뀌었을 때 | 받은 뒤 `sudo systemctl restart memoir` (진행 중 작업 확인 먼저) |
| requirements 가 바뀌었을 때 | `~/memoir/backend-agent/.venv/bin/pip install -r ~/memoir/backend-agent/requirements.txt` 후 재시작 |
| 로그 | `journalctl -u memoir -f` · 오늘 것 `journalctl -u memoir --since today` |
| 서버 상태 | `systemctl status memoir cloudflared` |
