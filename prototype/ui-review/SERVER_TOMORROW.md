# 서버 담당자와 바로 연결할 준비서

2026-11-09 · 로컬 `develop` / 작업 브랜치 `codex/frontend-ui-review`의 공통 기준 `7400e51`.

**2026-11-10 Git 공유:** 사용자 요청으로 `prototype/ui-review/` 전체를 `codex/frontend-ui-review`에 커밋·푸시합니다. 원격 `develop` HEAD는 `7400e51`로 확인했고 오프라인 검증을 다시 통과했습니다. 공유·검증 기준은 [README.md](README.md)를 따릅니다. 실제 배포 커밋·운영 설정은 확인 전입니다.

**먼저 할 일:** 아래 오프라인 검증 → 실제 배포 프론트 확인 → 로그인·화자·목록 연결 → 지원 문체로 생성 작업 연결 순서입니다. 서버를 새로 설계해야 시작할 수 있는 상태는 아닙니다. 준비 코드는 모두 `prototype/ui-review/`에 있습니다.

## 오늘 맞춰 둔 것

- [server-client.js](server-client.js): 기존 `/api` 경로에 맞춘 쿠키·JSON·204·오류·요청 취소 처리. `fetch`를 명시적으로 주입해야 요청할 수 있습니다. 모듈을 로드하는 것만으로 통신하지 않습니다.
- [memoir-controller.js](memoir-controller.js): 실제 메타·화자 소유 회차·선택 모드·문체 검증, 비동기 작업 시작/조회/취소, busy·만료·취소·부분 결과 구분. 화자 변경·401·reset 뒤 늦게 온 응답은 무시합니다.
- 기존 `memoir-policy.js`, `service-contract.js`, `interview-state.js`를 그대로 재사용합니다. 원본 장·문장 근거·검증 결과를 보존하고, 편집하면 기존 문장 근거는 만료합니다.
- 시안의 예시 자료도 서버의 merge 입력처럼 **회차 시작 시각 오름차순**으로 모읍니다. 선택 UUID의 클릭 순서는 유지합니다. 엽서 생성일·사건 발생 연도로 정렬하지 않습니다. 시작 시각이 없거나 같은 회차는 순서를 지어내지 않습니다. 실제 모델이 만든 장 순서는 응답 그대로 보존하며 회차 순서와 같다고 약속하지 않습니다.
- 기존 시안의 4문체 예시·6개 이상 선택·책장과 확정 디자인은 유지합니다. 실제 요청 경로에서는 지원하지 않는 동작을 차단합니다. 숨겨서 문체를 바꾸거나 선택 자료를 줄이지 않습니다.

## 오프라인 검증

이번 최종 결과는 **175/175 테스트 통과 · 31개 구문 통과 · 서버 소스 9개 지문 일치**입니다. 범위·독립 검토·브라우저 확인과 미검증 항목은 [검증 기록](SERVER_VERIFICATION.md)에 있습니다.

저장소 루트 `memoir-ui`에서 실행합니다. Node의 내장 `Response`를 쓴 오프라인 테스트가 있으므로 기존 개발 환경의 최신 Node LTS를 사용합니다.

```powershell
node prototype/ui-review/verify-server-ready.cjs
```

이 명령은 [기준 지문](server-baseline.json)의 서버 소스 9개와 작업 파일을 대조하고 시안 전체 테스트·JS/CJS 구문을 검사합니다. 서버 소스가 바뀌었으면 `REVIEW REQUIRED`로 멈춥니다. 해당 계약을 재검토한 후 지문을 갱신해야 합니다. 지문 일치는 실제 서버가 이 버전으로 배포됐거나 설정·DB가 정상이라는 뜻이 아닙니다.

실제 API·OAuth·마이크·DB를 호출하지 않습니다. 성공 문구 역시 **오프라인 준비 검증**만 뜻합니다. 기존 `serve.cjs`는 `connect-src 'none'; media-src 'none'`을 유지합니다. 아래 연결 예제를 이 검토 서버에서 실행하면 안 됩니다.

## 연결 순서와 바로 사용할 모듈

1. 운영 프론트가 `prototype/index.html`인지 `frontend-client`인지, 시안에서 어떤 화면을 채택할지 확인합니다. 기존 진입점·서버를 이번 작업에서 덮어쓰지 않았습니다.
2. 채택한 프론트의 **같은 origin `/api`**에 연결합니다. 별도 개발 origin을 쓰면 기존 프록시·쿠키·Origin 허용 설정을 확인합니다. 이 클라이언트에는 임의 외부 baseURL 기능이 없습니다. `VITE_API_BASE`를 쓰는 기존 코드에 옮길 때도 실제 배포 경로를 확인합니다.
3. Google 제공 credential로 로그인한 뒤 `getMe()`의 실제 `user`와 `elders`를 사용합니다. 화면용 가상 계정·이름을 인증 정보나 ID로 보내지 않습니다. `createElder({name})`는 매번 새 화자를 만들므로 제출 중 중복 클릭을 막습니다. 같은 이름도 다른 화자일 수 있습니다.
4. 선택한 실제 `elder_id`로 `listSessions({elderId})`를 읽고, **응답 전체**를 제어기에 전달합니다. 직접 선택은 그 목록에 있는 현재 화자의 `closed_at` 있고 `has_words:true`인 회차만 허용합니다. 엽서 본문은 각 `getRecord()`의 `postcard.text`를 읽습니다.
5. UI의 생성 버튼을 `controller.start()`에 연결합니다. 진행 상태는 서버에서 받은 값만 표시하고 임의 타이머로 완료시키지 않습니다. 현재 시안의 목업 생성 핸들러를 동시에 실행하지 않습니다.
6. 화면이 활성이고 `phase==='running'`일 때만 호출자가 적절한 간격으로 `refresh()`합니다. 이 제어기에는 자동 폴링이 없습니다. 네트워크 오류에서는 명시적 재시도, 401/만료/완료/화자 변경/화면 종료에서는 반복 조회 중단을 구현합니다.
7. `view.canRead===true`인 `view.document`만 초안·리더에 전달합니다. 생성 작업 완료와 책의 서버 영구 저장은 서로 다른 상태입니다. 현재 `document.storage==='tab-memory'`입니다.

브라우저 전역 예시입니다. React로 옮기면 동일 모듈을 번들에 포함하고 화면 생명주기에서 이벤트 구독·정리를 담당합니다. `index.html`에는 모듈이 로드되지만 이 초기화는 자동 실행되지 않습니다.

```javascript
let speakerLoadVersion = 0;
const client = MemoirServerClient.create({
  fetch: window.fetch.bind(window),
  onUnauthorized() {
    speakerLoadVersion++;
    generation.setContext({elderId:null, metadata:null});
    // 실제 앱의 계정·화자·기록·초안·책장 메모리도 비우고 로그인으로 이동.
  },
});
const generation = MemoirGenerationController.create({
  client,
  onChange(view) {
    window.dispatchEvent(new CustomEvent('memoir:server-job', {detail:view}));
  },
});
async function loadSpeaker(elderId) {
  const version = ++speakerLoadVersion;
  const isCurrent = () => version === speakerLoadVersion;
  generation.setContext({elderId, metadata:null});
  try {
    const me = await client.getMe({isCurrent});
    if (!isCurrent()) return null;
    if (!me.elders.some(elder => elder.elder_id === elderId)) {
      throw new Error('등록된 이야기 주인공을 선택해 주세요.');
    }
    const metadata = await client.listSessions({elderId, limit:100}, {isCurrent});
    if (!isCurrent()) return null;
    generation.setContext({elderId, metadata});
    return metadata;
  } catch (error) {
    if (!isCurrent()) return null;
    throw error;
  }
}
// loadSpeaker 완료 후 UI가 선택한 실제 회차 UUID를 전달:
// await generation.start({mode:'explicit',sessionIds:selectedIds,uiStyle:'plain'});
// await generation.refresh();
// await generation.cancel(); // 생성 작업 취소이며 책 삭제가 아님.
```

계정 전환/로그아웃에는 대기 중 목록 조회의 버전도 무효화하고 `setContext({elderId:null,metadata:null})`로 컨텍스트를 없앱니다. `reset()`만 호출하면 현재 화자·메타는 유지되며, 화면 추적만 초기화합니다. 시작 응답 전에 `cancel()`하면 job ID가 없어 서버 취소를 확인할 수 없습니다(`submission_abandoned`). 나중에 계정의 현재 작업을 확인해야 하며 취소 성공으로 표시하지 않습니다.

## 기존 API 대응표

전 메서드 마지막 인자는 선택 `{signal,isCurrent}`입니다. `isCurrent`는 401의 전역 인증 콜백을 실행해도 되는지 직전에 동기 판정합니다. false/예외이면 콜백만 생략하고 원래 오류는 유지합니다. 생성 제어기는 이 판정을 자동으로 전달합니다. 그 밖의 계정·목록 화면도 위 예시처럼 화면 버전을 전달하고 늦은 응답을 버립니다. 인증 콜백의 상태 정리는 동기적으로 수행합니다. 중간 body가 선택이면 `undefined` 자리를 유지합니다. 성공은 원래 JSON, 204는 `null`입니다.

| 클라이언트 | 기존 서버 경로·계약 |
| --- | --- |
| `googleLogin(credential)`, `getMe()`, `logout()` | POST `/api/auth/google` `{credential}`; GET `/api/auth/me`; POST `/api/auth/logout` → 204. 앱 쿠키 `credentials:'include'`. |
| `createElder({name})` | POST `/api/elders` → 201 `{elder_id,name}`. 이름 trim 후 1~40자. 화자 목록은 `/auth/me`. |
| `createSession(preparation)` | POST `/api/sessions`; 필수 `title`, 선택 `elder_id/seed/theme/topic/pace/max_turn/photo_id`. UI 주제명과 서버 `family/self/hobby`의 의미 대응은 별도 확인. |
| `listSessions({elderId,limit,hasPostcard})` | GET `/api/sessions`; 클라이언트 기본 limit=100, 서버 기본=20·최대=100. cursor/offset/page 없음. 화자 지정 때만 생성 메타가 함께 옴. |
| `assignElder(sessionId,elderId)` | PUT `/api/sessions/{UUID}/elder` `{elder_id}`. 미지정 회차 연결. 같은 화자로 재요청하면 200, 이미 다른 화자라면 409를 그대로 처리. |
| `getSnapshot({sessionId})`, `getRecord(sessionId)` | GET `/api/sessions/{UUID}`는 메모리 FSM; GET `…/record`는 저장된 DB 기록. snapshot 404를 기록 삭제·완료로 해석하지 않음. |
| `createPostcard(sessionId,{style:'spoken'})` | POST `…/postcard` → 글·이미지 메타 JSON. 같은 경로 GET은 이미지 바이트이므로 JSON 클라이언트에 넣지 않음. 완료 후 사용자가 직접 생성. |
| `createMemoir(body)` | POST `/api/memoirs` → 202 running. 입력 예시는 아래 참고. |
| `getMemoir(jobId)`, `latestMemoir()` | GET `/api/memoirs/{job_id}`, `/latest`. **계정 단위**이며 현재 화자의 작업이라고 단정하지 않음. job ID는 32자리 hex. |
| `cancelMemoir(jobId)` | DELETE `/api/memoirs/{job_id}`. 취소 결과는 `status:'failed',code:'cancelled'`; 이미 끝났으면 기존 결과. |
| `interviewCommand({sessionId,action,text})` | `turn-done`→POST `/done`, `send-text`→POST `/speech` `{text}`, `tts-done`→POST `/tts-done`, `abort`→POST `/abort`. finish/pause/resume은 요청 전 거절. |
| `createLink(preparation)`, `listLinks`, `revokeLink`, `reissueLink` | POST/GET `/api/links`, POST `/api/links/{l_…}/revoke`, `/reissue`. 발급 시 받은 token 원문을 목록에서 재구성하지 않음. |
| `previewInvitation(token)`, `startInvitation(token,body?)` | GET `/api/i/preview`, POST `/api/i/start`: `x-interview-token` 헤더. 시작 body는 생략 가능, topic 생략 시 준비된 주제 사용. |
| `getSnapshot({guest:true})`, `interviewCommand({guest:true,…})` | `/api/i/session`+명령 suffix, 경로에 sessionId 없음. 수신자 기기 쿠키 사용. 시작 응답의 `state='in_progress'`는 링크 상태이므로 즉시 snapshot을 다시 조회하여 FSM 확인. |

API 오류는 `ApiError`의 `status/code/detail/body/kind/job_id?`로 전달합니다. FastAPI의 422 `detail` 배열, code 없는 409, JSON 아닌 응답도 별도로 보존합니다. `kind`는 `http/validation/network/abort/invalid_response`입니다. network 재시도를 자동으로 무한 반복하지 않습니다.

## 생성 요청 예시와 자동 처리 범위

아래 ID는 형식 예시입니다. 실제 응답에서 받은 ID로 바꿉니다.

```json
{"session_ids":["00000000-0000-4000-8000-000000000001","00000000-0000-4000-8000-000000000002","00000000-0000-4000-8000-000000000003"],"style":"spoken"}
```

```json
{"elder_id":"실제_화자_ID","exclude_session_ids":[],"style":"spoken"}
```

- 직접 선택은 최소3·최대 환경값(기본5). `pipeline`의 `memoir_max:null`은 직접 선택 상한을 알려주지 않으므로 `explicit_limit_unknown`으로 차단합니다. 최대5로 추정해서 보내지 않습니다.
- 전체 제외 모드는 해당 화자의 닫힌·말씀 있는 **전체 회차**가 대상입니다. 엽서가 없는 회차·화면 밖 오래된 회차도 들어갈 수 있습니다. 이 모드도 `single` 엔진에서는 환경 상한이 적용되며 `pipeline`일 때만 상한이 없습니다. 직접 선택을 이 모드로 몰래 바꾸지 않습니다.
- 202에서 받은 job ID·실제 `run.session_ids`를 시작 시점 화자와 함께 고정합니다. 이후 같은 job과 회차 범위의 결과만 채택합니다.
- `409 {code:'busy',job_id:…}`는 `phase:'busy',scope:'unverified'`로 표시하며 자동으로 `/latest`를 조회하거나 현재 화자에게 귀속시키지 않습니다. 기존 작업 복귀 화면에는 화자·선택 범위 확인이 먼저 필요합니다.
- `404 {code:'job_not_found'}`는 `expired`, failed+cancelled는 `cancelled`, 부분 결과는 `incomplete`로 다룹니다. 검증되지 않은 결과를 완성책으로 열지 않습니다. 네트워크 오류는 서버의 생성 실패와 구별합니다.

## 내일 서버 담당자에게 확인할 최소 항목

| 우선순위 | 확인·결정 | 그대로 두면 생기는 영향 |
| --- | --- | --- |
| P0 | 실제 운영 프론트·배포 커밋과 반영 담당, origin·cookie 설정 | 준비 코드가 기존 서비스에 자동 적용되지 않음. `GOOGLE_CLIENT_ID/ALLOWED_ORIGINS/PUBLIC_ORIGIN/COOKIE_SECURE` 설정 이름만 조사했으며 값은 미조회. |
| P0 | 직접 선택 상한을 응답 메타에 별도로 제공할지 | pipeline 계정의 직접 선택 생성은 안전하게 차단됨. 기존 전체 제외 모드는 명시적으로 선택하면 사용 가능. |
| P0 | 우선 문체를 spoken으로 연결하고 수필체 계약은 언제 적용할지 | 현재 4종은 디자인 예시. PM의 수필체 기본 방향을 API enum·모델·응답에 함께 반영해야 함. |
| P0 | 마지막 발화를 보존하는 정상 종료, 일시정지·재개의 의미 | `/done`을 인터뷰 종료, `/abort`를 정상 완료로 연결하면 안 됨. 마이크만 끄는 것과 서버 일시정지도 다름. |
| P1 | 완성책 ID·영구 저장·수정·삭제·권한·복원 | 생성 job은 프로세스 메모리이며 만료/재시작으로 사라질 수 있음. 현재 책장 보관을 서버 저장 성공으로 표시하면 안 됨. |
| P1 | 작업 응답의 화자 식별과 100개 밖 회차 탐색 | 현재 계정 busy/latest를 화자별 복귀에 바로 쓸 수 없고, 기존 목록 API는 전체 페이지 탐색을 제공하지 않음. |

위 항목은 제안·미결입니다. 새 endpoint/필드를 이미 구현됐다고 가정하지 않습니다. 기존 네 메뉴·표지·개인화 제목·리더 디자인을 다시 결정할 필요는 없습니다.

## 실제 환경에서 함께 확인할 순서

1. 진짜 로그인·me·로그아웃과 401 뒤 메모리 정리, 다른 계정/화자의 데이터 분리.
2. 화자 등록 중 중복 클릭, 미지정 회차 연결, 다른 화자 409·권한 오류 처리.
3. 2/3/상한개 직접 선택, pipeline 전체 제외, 엽서 없는/목록 밖 회차의 포함 안내.
4. 비동기 running→done/failed, busy·명시 취소·네트워크 단절·job 만료·서버 재시작.
5. 마지막 발화 저장→DB record→사용자 직접 엽서 생성. 실제 음성은 별도로 STT/TTS·무음204·기기 권한을 검증.
6. 실제 결과의 장·문장 출처·검증 표시, 편집 뒤 근거 만료, 실제 휴대폰 읽기·가로/세로 전환.

백업: 상위 작업 폴더 `_backups/memoir-ui-review/20261109-191141-before-develop-alignment.zip` 및 파일별 SHA256 manifest. 백업은 소스·디자인 파일이며, 브라우저 탭 메모리의 사용자 이야기 저장본은 아닙니다.
