# 로그인 원본 조사와 정적 시안 인계

이 문서는 코드에서 확인한 동작을 정리합니다. 배포 서비스에서 OAuth·쿠키·DB가 실제로 동작하는지는 시험하지 않았습니다. 원본 `main`·`develop`은 읽기만 했으며 수정·checkout·커밋·푸시하지 않았습니다.

## 확인한 소스

- 원본 main: `chochoong/memoir`, 커밋 `088b23f40efce837909cdc54faa388fa2c2016fb`
- [main `prototype/index.html`](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html): blob `0cf738b3a91b3b481fcb1e976a484d2a633c3cdb`. 로그인 마크업 823~842행, 모드 1669~1687행, 요청 1805~1825행, 인증 5707~5864행.
- [main `frontend-client/src/api.ts`](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/frontend-client/src/api.ts): blob `7d3963bca9a5d95ea7ee13dc5072b77d90d38529`. React 호출부는 `X-User-Id: dev-user` 개발 헤더를 사용합니다.
- 로컬 `origin/develop`: `7400e51c9b915d4de671b670e02857ab9e6d8cd5`. `prototype/index.html:642`, `frontend-client/src/api.ts:125`도 개발 헤더를 사용하며 로그인 화면이 없습니다.
- 같은 develop의 `backend-agent/app/session/auth.py`, `backend-agent/app/main.py:324`에는 Google 검증과 앱 세션 인증이 이미 구현되어 있습니다. main 프론트의 오래된 “서버 코드가 아직 없다” 주석을 현재 백엔드 구현 상태로 해석하면 안 됩니다.
- 저장소에서 `AGENTS.md`는 발견되지 않았습니다. 이미 읽은 `prototype/CLAUDE.md`의 원본 프론트·백엔드 분리와 명시 요청 전 커밋·푸시 금지 지침을 지켰습니다.

## 원본에서 확인한 동작

1. main 정적 프론트는 Google Identity Services의 `ux_mode: 'popup'`과 콜백을 사용합니다. 콜백의 ID credential을 `POST /api/auth/google`의 `{credential}`로 보냅니다. OTP·비밀번호·별도 회원가입 폼은 없습니다.
2. 로그인 응답은 `{user:{user_id,name,email}, elders:[{elder_id,name}]}`입니다. 백엔드는 검증된 Google 계정을 upsert하고 앱 세션을 만듭니다. 프론트가 사용자 ID를 임의 헤더로 정하지 않습니다.
3. 백엔드가 `msid` 쿠키를 설정합니다. 코드상 `HttpOnly`, `SameSite=Lax`, `path=/`이며 `Secure`는 HTTPS·`PUBLIC_ORIGIN`·`COOKIE_SECURE` 조건으로 결정됩니다. 세션 최대·유휴 시간은 환경 설정 값이며 제품 정책으로 확정된 숫자로 단정하지 않습니다.
4. main 프론트의 공통 호출은 `credentials:'include'`를 사용합니다. 앱 진입 시 `GET /api/auth/me`로 계정·화자를 확인합니다. 일반 자녀 API의 401은 인증 해제로 처리하며 `/auth/*`, `/i/*`는 별도 경로입니다.
5. 화자가 이미 있으면 성공 후 `ready`로 이동합니다. 없으면 `elder` 화면에서 부르는 이름 하나를 받아 `POST /api/elders {name}`로 등록합니다. 이메일을 따로 입력하거나 상세 프로필을 받지 않습니다. 중복 등록을 막는 busy/success 상태가 있습니다.
6. Google popup 취소는 로그인 전 화면에 머뭅니다. `invalid_token`, `expired_token`, `session_expired` 등은 코드별 안내를 표시합니다.
7. 로그아웃은 `POST /api/auth/logout` 뒤 reload합니다. 인증 해제도 reload하여 목록·사진·본문 등 화면 메모리를 비웁니다. 원래 요청한 화면을 보존하는 `returnTo` redirect는 확인하지 못했습니다. 성공 이동은 `ready` 또는 첫 화자 등록입니다.
8. 어르신 링크 `/i#토큰`은 자녀 Google 로그인과 다른 경로입니다. 이 시안에서는 링크 인증을 새로 구현하지 않습니다.

## 이번 정적 시안

- 새 파일: `login-view.js`, `login-view.css`. 기존 아이보리·버건디 스타일과 로컬 `book-illustration.svg`를 사용합니다.
- 사용자 정정에 따라 native dialog의 `Google Login Mock Data` 버튼 한 번으로 동일 이름의 고정 예시 계정에 진입합니다. 중간 화자 선택은 생략하고 예시 화자는 `나`로 둡니다. 실제 첫 화자 등록은 원본에서 계승할 별도 설계 항목으로 남깁니다. 이름·이메일·비밀번호 입력란이 없습니다.
- Google SDK·popup·credential·쿠키·API 요청은 사용하지 않습니다. 로그인 상태와 선택은 이 모듈의 탭 메모리에만 있습니다. localStorage·sessionStorage·문서 쿠키에 쓰지 않습니다.
- 네 메뉴와 기존 작업 화면은 유지합니다. 닫기·Esc는 로그인 패널을 열기 전 화면으로 돌아갑니다. 이는 원본의 전체 화면 로그인 gate와 다른 검토용 표현입니다. 실제 접근 통제나 세션을 뜻하지 않습니다.
- 가상 로그아웃은 모듈의 계정 표시만 초기화합니다. 기존 엽서·자서전 예시와 리더 설정을 삭제하지 않습니다. 실서비스 로그아웃 시에는 원본의 사용자별 화면 메모리 초기화를 통합해야 합니다.

연결 방법:

```html
<link rel="stylesheet" href="login-view.css">
<!-- app.js 다음에 로드: icons(), escapeText() 사용 -->
<script src="login-view.js" defer></script>
```

루트 화면이 avatar 클릭을 `window.MemoirLogin.open()`에 연결합니다. 공개 API는 `open()`, `close()`, `logout()`입니다. 실제 인증 상태와 혼동하지 않도록 `memoir:preview-auth` 이벤트의 `detail`은 항상 `preview:true`이며 `{authenticated,displayName,speaker}`에는 고정 가상 값만 담습니다. `authenticated`는 이 시안 표시 상태일 뿐 API 권한을 의미하지 않습니다.

## 실제 연동 시 맞출 계약

main의 Google 버튼·`credentials:'include'`·`/auth/me`·`/auth/logout`·첫 화자 등록 흐름을 기준으로, develop 프론트의 `dev-user` 헤더를 백엔드의 HttpOnly 앱 세션 계약과 맞춰야 합니다. Google 클라이언트 설정, 서버 환경·DB·쿠키·허용 출처, 계정별 목록 분리·401·로그아웃 초기화는 해당 환경에서 별도로 검증해야 합니다. 이 시안의 가상 계정 상태를 실제 신원으로 보내거나 인증 성공으로 재사용하지 않습니다.

이 인계는 UI 연결 준비까지이며 실제 OAuth·서버 배포 변경을 승인하거나 완료한 기록이 아닙니다.

## 확인 결과

- `node --check prototype/ui-review/login-view.js` 통과.
- `tinycss2`로 CSS 53개 규칙과 선언을 파싱했고 오류가 없었습니다. 스타일 범위가 `.memoir-login-dialog` 안으로 한정됨을 확인했습니다.
- 최초 버전에서는 가상 DOM으로 화자 선택 포함 흐름을 확인했습니다. 최신 간소화 버전은 브라우저에서 `Google Login Mock Data` 한 번 클릭 → 고정 계정 → 가상 로그아웃 → 원래 책장 복귀를 확인했고 오류·경고 로그가 없었습니다.
- 입력 폼·SDK·외부 주소·네트워크 함수·쿠키·브라우저 저장소 접근이 없는지 검사했습니다.
- 실제 OAuth·배포 서버·브라우저/CUA 조작은 이 모듈 작업에서 수행하지 않았습니다.
