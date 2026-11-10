# 기존 서버 연결 준비·팀 전달서

**추가 구현 · 2026-11-09:** [서버 담당자 준비서](SERVER_TOMORROW.md)에 실행할 검증 명령·기존 API 클라이언트·생성 제어기·연결 예시·남은 결정을 모았습니다. 아래 순수 변환기 외에 실제 transport를 주입할 수 있는 코드까지 준비했으나, 시안에서는 네트워크가 활성화되지 않았습니다. 예시 초안 순서는 이제 서버처럼 회차 시작 시각을 따릅니다. 아래 104개 검증 기록은 이전 준비 단계의 기록입니다.

2026-11-09 · 현재 디자인을 유지하는 정적 시안의 호환성 준비입니다. 사용자가 시안 디자인과 이번 폴더 안의 정리·인계를 승인했습니다. 팀의 운영 반영·배포 승인이나 실제 서비스 연결 완료를 뜻하지 않습니다.

## 기준과 범위

- 확인한 로컬 기준은 HEAD `7400e51c9b915d4de671b670e02857ab9e6d8cd5`입니다. 현재 브랜치는 `codex/frontend-ui-review`이며 로컬 `develop`도 같은 커밋입니다. **로컬 `main` ref는 없습니다.** 기존 전달서의 `main 088b23f…`는 과거 원본 조사·디자인 출처이며 현재 배포본으로 확인한 값이 아닙니다.
- 변경 범위는 `prototype/ui-review/`입니다. 실제 인증·네트워크·마이크·DB 호출을 추가하지 않았습니다. [serve.cjs](serve.cjs)의 `connect-src 'none'; media-src 'none'`을 유지합니다. 목업 계정·화자·UUID·작업 ID는 실제 사용자 정보나 권한이 아닙니다.
- 책 보관과 생성 작업은 탭 메모리입니다. 리더의 기존 localStorage는 보기 설정·내용 해시·숫자 위치·책갈피 용도이며 본문을 영구 저장하지 않습니다. `job_id`는 생성 작업 번호로, 책 ID나 서버 저장 성공을 나타내지 않습니다.
- 현재 네 메뉴·라디오·문체 선택·편집·책장·리더는 사용자가 선택한 검토 디자인입니다. 10/16 메뉴 지침 및 뒤의 FE 업무지시서에서 제한한 전체 UI 변경·책 보관 등과 차이가 있으므로 **팀에 제안할 변경**으로 인계합니다. 기존 팀 문서가 이 디자인의 운영 적용까지 승인했다고 해석하지 않습니다.

## 연결 판단표

| 구분 | 화면·기능 | 담당자가 이어 할 일 |
| --- | --- | --- |
| 기존 API로 연결 | Google 로그인·계정 확인·로그아웃 | `POST /api/auth/google {credential}`, `GET /api/auth/me`, `POST /api/auth/logout`의 앱 세션 쿠키 계약을 사용합니다. 가상 로그인 이벤트나 개발용 사용자 헤더를 실제 인증으로 쓰지 않습니다. 401과 로그아웃에서 사용자별 화면 메모리를 비웁니다. |
| 기존 API로 연결 | 화자 등록·선택 | `/auth/me`의 `elders[{elder_id,name}]`, `POST /api/elders {name}`를 사용합니다. 예시 이름을 ID로 바꾸지 않습니다. 화자 미지정 회차는 `PUT /api/sessions/{id}/elder`의 확인 절차를 따릅니다. |
| 기존 API로 연결 | 인터뷰 초대·회수 | `POST/GET /api/links`, `POST /api/links/{id}/revoke`, `/reissue`가 있습니다. 발급 때만 토큰 원문을 받습니다. 받은 사람의 `/api/i/*`는 자녀 쿠키 인증 화면과 구분합니다. 회수는 진행 회차도 중단합니다. |
| 기존 API로 연결 | 인터뷰 진행·기록 읽기 | 진행 중 `GET /api/sessions/{id}`는 메모리 snapshot, 종료 뒤 `GET /api/sessions/{id}/record`는 DB 기록입니다. snapshot 소멸·404를 기록 소멸이나 정상 완료로 대체하지 않습니다. |
| 기존 API로 연결 | 엽서 목록·직접 생성 | `GET /api/sessions?elder_id=…`의 회차 메타와 저장 기록의 `postcard`를 사용합니다. `POST /api/sessions/{id}/postcard`는 글·이미지 메타 JSON, `GET …/postcard`는 이미지입니다. 인터뷰 완료와 엽서 생성을 자동으로 묶지 않습니다. |
| 기존 API로 연결 | 자서전 비동기 생성 | `POST /api/memoirs` → `202 running`, `GET /api/memoirs/{job_id}`, `/latest`, `DELETE /api/memoirs/{job_id}`가 이미 있습니다. `409 busy`는 기존 작업 이어보기로 연결합니다. 동기 `/api/memoirs/preview`도 남아 있습니다. 새 비동기 API가 필요하다고 인계하지 않습니다. |
| 기존 API로 연결 | 생성 정책·오류 | 화자별 목록의 `memoir_engine`, `memoir_max`, `memoir_max_chars`, `memoir_enabled`, `memoir_total`을 읽고 요청 모드를 구분합니다. 자료 부족·조회 실패·부분 실패·timeout·취소를 status/code대로 표시합니다. 생성 완료·모델 검증·사람 확인·저장 완료는 각각 다른 상태입니다. |
| 서버 보완 또는 제품결정 | 직접 선택의 정확한 상한 | `pipeline`의 `memoir_max:null`은 전체 제외 모드의 상한 없음입니다. 직접 `session_ids`는 여전히 서버 `MEMOIR_MAX_SESSIONS` 검사 대상이며 현재 메타에 그 별도 상한이 없습니다. 상한 전달 방식을 합의하기 전 어댑터는 `explicit_limit_unknown`으로 막습니다. |
| 서버 보완 또는 제품결정 | 문체·각색 표시 | 현재 서버 지원값은 `spoken`뿐입니다. 시안 `plain → spoken`만 연결 가능하고 `essay/story/letter`는 미지원입니다. 10/28 PM의 **수필체를 별도 문체·자서전 기본값으로 삼는 결정은 존재**하나 API 값·기본값 연결은 미결입니다. 문장별 사실·각색 표시 계약도 합의해야 합니다. |
| 서버 보완 또는 제품결정 | 인터뷰 마치기·잠시 쉬기·재개 | `/done`은 현재 턴 확정이며 전체 인터뷰 마치기가 아닙니다. `/abort`는 회차 중단입니다. 마지막 소리·전사·저장을 처리하는 정상 마치기 및 pause/resume 계약은 별도이며, 시안 버튼을 기존 API와 임의 대응시키지 않습니다. |
| 서버 보완 또는 제품결정 | 책장 영구 보관·편집 저장 | 조사한 라우트에는 영구 책 CRUD·편집 저장 API가 없습니다. 보관 단위·책 ID·수정 이력·삭제·권한·기기 간 읽기 위치 정책부터 정합니다. 아직 없는 `/api/books` 등을 구현된 경로로 쓰지 않습니다. |
| 미결 | 원본·반영 경로·운영 설정 | 정적 `prototype/index.html`과 React `frontend-client` 중 운영 원본, 시안 채택 범위, develop/main 반영 주체, 실제 배포 커밋을 팀이 확인합니다. 계정별 개방·엔진·상한·쿠키·출처 설정은 배포 환경에서 별도 검증합니다. |
| 미결 | 전체 대상 탐색·선택 순서 | 목록은 기본 20·최대 100이고 `memoir_total`은 전체 대상 수입니다. 화면에 없는 회차의 포함·제외 방법과 추가 조회 방식을 정합니다. 클릭 순서를 원자료의 사건 연도순·서버 생성 순서로 약속하지 않습니다. |

## 모듈 연결점

모듈은 브라우저 전역과 CommonJS로 같은 순수 함수를 제공합니다. 이 함수들은 요청을 보내지 않습니다. 실제 transport는 추후 기존 API 클라이언트에 붙이고, 화면·리더가 서버 응답을 직접 재해석하지 않게 합니다.

| 파일·전역 | 입력 → 출력·책임 |
| --- | --- |
| [service-contract.js](service-contract.js) · `MemoirServiceContract` | `postcardView(session, postcard, presentation)` → 엽서 화면 데이터. `memoirView(result, context)` → 보존 원본과 읽기 문단. `editMemoir(document,{title,body})` → 편집본. `jobView(response,context)` → 작업 상태와 완료 문서. 잘못된 형식은 거절하고 부분본을 읽기 완료로 만들지 않습니다. |
| [memoir-policy.js](memoir-policy.js) · `MemoirSelectionPolicy` | `serverPolicy(metadata)` → 메타 조회 가능·기능 개방·모드별 제한. `styleBinding(uiStyle)` → 지원 여부·API 문체. `prepareRequest({mode,sessionIds,elderId,excludeSessionIds,uiStyle},metadata)` → `{ok,body,code}`. 모드는 `explicit` / `all-except`입니다. |
| [interview-state.js](interview-state.js) · `InterviewVisualState` | `fromSnapshot(snapshot)` → `{phase,serverState,closed}` 또는 미지 상태 `null`. `SPEAKING/LISTENING/PROCESSING/CLOSED`를 화면 상태로 대응합니다. `commandFor(action)`은 `turn-done/send-text/tts-done/abort`의 상대 경로·method·scope를 반환하며 `finish/pause/resume`는 `supported:false`입니다. 실제 세션 또는 `/api/i/session` prefix는 연결부가 결정합니다. |
| [preview-service.js](preview-service.js) · `MemoirPreviewService` | `postcard(session,presentation)`, `createMemoirJob(records,context)`, `completeMemoirJob(job)`는 탭 안의 고정 예시 transport입니다. 생성 때 자료·화자를 복사하여 대기 중 화자 변경과 분리합니다. 타이머·화면 전환은 app이 맡습니다. 서버 형태 `spoken`은 문체 변환 성과를 뜻하지 않습니다. |

`reviewPolicy={min:3,max:null}`은 시안의 최소 3·선택 상한 없음 정책입니다. `serverPolicy`와 분리되어 있으므로 UI 예시를 6개 이상 선택할 수 있다는 사실이 실제 직접 선택 요청 허용을 뜻하지 않습니다. 메타 없음은 `metadata_unavailable`, 기능 비활성은 `memoir_disabled`, 미지원 문체는 `unsupported_style`로 구분합니다.

## 데이터 필드 대응

| 서버 원자료 또는 별도 입력 | 화면 데이터 | 보존·표시 원칙 |
| --- | --- | --- |
| 회차 `session_id`, `elder_id` | 엽서·문서의 식별/화자 귀속 | 표시용 `id`·화자 이름과 별개입니다. 자서전 요청에는 실제 회차 UUID를 사용합니다. |
| 엽서 `title`, `text`, `created_at` | `title`, `body`, `created_at` | `sourceSession`, `sourcePostcard`에 원본을 복사합니다. `postcard_title`만 있는 목록은 본문이 아니므로 기록을 조회해야 합니다. |
| `presentation`의 분류·아이콘·화면 날짜·설명 | `category/icon/date/description`, `presentation` | 서버 응답에서 추정하지 않는 시안 표시값입니다. 서버 본문·사실·식별자와 섞어 역저장하지 않습니다. |
| 결과 `title`, `chapters[].paragraphs[].sentences[]` | `title`, 문단 배열 `body`, `sections` | `chapterNo/chapterTitle/paragraphIndex`와 문장별 `text/turns`를 유지합니다. 장 제목을 근거가 있는 본문 문장으로 끼우지 않습니다. |
| 구형 결과의 문자열 `body` | 빈 줄을 제외한 `body`·제목 없는 `sections` | 구형 응답을 새 장별 생성 결과로 꾸미지 않습니다. 원 문자열은 `sourceResult`에 남습니다. |
| `sources`, `verification`, `run`, `to_confirm`, `style` 등 결과 전체 | `sourceResult`, 현재 `sources/verification/style` | 알 수 없는 추가 필드도 원본에 남깁니다. 검증 누락은 `not_run`이며 pass로 승격하지 않습니다. `run.session_ids`는 실제 생성에 사용한 범위입니다. |
| context `elder_id/job_id/uiStyle/preview` | 문서의 같은 필드 | 요청 시작 시점에 고정합니다. `uiStyle`은 화면 선택, `style`은 응답 값이므로 둘의 의미를 구분합니다. |
| 작업 `job_id/status/stage/chapter/chapters/elapsed/code/detail` | 작업 view, 완료 시 `document`·`canRead` | `done`이어도 결과 형식과 완료 범위를 확인합니다. 프로세스 재시작·보관 만료 후 작업을 영구 책처럼 복원하지 않습니다. |

편집으로 제목 또는 본문이 바뀌면 `sourceResult`의 원래 글·출처·검증·실행 정보는 그대로 남습니다. 현재 글은 `edited:true`, `sourceAlignment:'stale'`, `sources:[]`, `verification:{state:'not_run'}`로 바뀝니다. 장 구분도 현재 편집 문단으로 다시 만들며, 옛 문장 번호의 근거를 수정 글에 재사용하지 않습니다. 바뀌지 않은 편집 저장은 기존 상태를 유지합니다.

## 팀 자료와 다음 확인

- [COMPATIBILITY_DESIGN.md](COMPATIBILITY_DESIGN.md)·[COMPATIBILITY_PLAN.md](COMPATIBILITY_PLAN.md)는 이번 사용자가 승인한 작업 범위입니다. 상세 기존 API 근거는 [FRONTEND_HANDOFF.md](FRONTEND_HANDOFF.md)·[LOGIN_HANDOFF.md](LOGIN_HANDOFF.md), 현재 서버 근거는 [main.py](../../backend-agent/app/main.py)·[memoir.py](../../backend-agent/app/session/memoir.py)·[memoir_jobs.py](../../backend-agent/app/session/memoir_jobs.py)·[style.py](../../backend-agent/app/session/style.py)입니다.
- 로컬 팀 자료: [D1 각색 기준 v1.2](C:/Users/nda01/Downloads/자서전고도화_D1_각색기준_v1.2.md)와 [대표 대조 묶음 v1.2](C:/Users/nda01/Downloads/자서전고도화_D1_대표대조묶음_v1.2.md), `Downloads/03_강승우_자서전고도화_추가업무지시서_결과화면_v1.0.docx`의 MEM-FE-03·05·06을 대조했습니다. 합성 표시·실제 독립 결과 표시·실제 서비스 연결은 서로 다른 완료 기준입니다. 옛 FE 지시서의 저장 제외·3~5장·동기 호출 제한을 현재 서버 구현 상태로 단정하지 않습니다.
- `.txt`·`.env`·비밀정보는 읽지 않았습니다. D1이 인용한 PM 답 원문 `.txt`도 직접 열지 않았으며, 위 PM 결정은 D1 v1.2가 기록한 내용을 근거로 했습니다.
- 2026-11-09 최종 로컬 검증: 시안 테스트 **104/104 통과**, 모든 JavaScript/CJS 25개 구문 검사 통과. 인앱 브라우저에서 6개 기록 선택→예시 생성→장별 목차(9문단·6장)→제목 편집→목록에서 새 선택 후 뒤로 가기→수정 초안 보존→책장 보관→다시 열기를 확인했습니다. 브라우저 warn/error는 0건입니다. 기존 테스트 56개와 이번 신규·회귀 테스트를 함께 실행했으며 실제 API를 호출한 결과가 아닙니다.
- 독립 검토에서 찾은 「새 선택 시작 시 기존 문서 원본 소실」은 다음 결과 성공 전까지 이전 문서를 보존하도록 고쳤습니다. 다문단 장 제목 반복 및 목차의 현재 장 표시도 고쳤습니다. 이 세 동작은 실패 재현 후 통과한 회귀 테스트로 확인했습니다.
- 실제 연결 때는 인증·계정/화자 격리, 마지막 발화와 DB 기록, 두 선택 모드·오류, busy/취소/복구, 장·근거 보존, 편집 뒤 재검증을 실제 환경에서 확인해야 합니다. 실제 스마트폰·전체 반응형 조합·OAuth·음성·운영 저장 검증은 이번 확인 범위가 아닙니다.
