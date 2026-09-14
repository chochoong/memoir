# memoir

어르신 구술 회고록 수집 시스템.

- `backend-agent/` — 세션 서버 (FastAPI). 설계·측정은 [backend-agent/README.md](backend-agent/README.md)
- `frontend-client/` — 웹 클라이언트 (Vite + TypeScript)

## 받아서 실행하기

```bash
git clone https://github.com/chochoong/memoir.git
cd memoir
```

### 백엔드

```bash
cd backend-agent
python -m venv .venv
source .venv/Scripts/activate      # mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # 키 채우기
uvicorn app.main:app --reload
```

### 프런트엔드

```bash
cd frontend-client
npm install
cp .env.example .env
npm run dev
```

`.env` 는 저장소에 없습니다. `.env.example` 을 복사해 각자 키를 채우세요.
