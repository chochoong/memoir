# Frontend Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 시안에 기존 서버 규격을 보존하는 데이터 경계를 적용한다.

**Architecture:** 순수 UMD 모듈로 응답 변환과 정책 검사를 분리한다. 목업이 서버 모양의 응답을 만들고 같은 변환을 통과하며, 화면과 로컬 책은 원래 응답을 함께 보존한다.

**Tech Stack:** 기존 HTML/CSS/JavaScript, Node 내장 test/VM. 새 의존성 없음.

**Spec:** [COMPATIBILITY_DESIGN.md](COMPATIBILITY_DESIGN.md) · 채팅에서 승인한 범위.

## Global Constraints

- 변경·생성은 `prototype/ui-review/` 안으로 한정한다. 기존 작업 브랜치를 유지하고 커밋·푸시하지 않는다.
- 실제 OAuth·마이크·API·DB 호출과 배포는 하지 않는다. `.txt`·`.env`를 읽지 않는다.
- 기존 화면·목업 범위와 최소 3·시안 상한 없음 정책을 유지한다. API 검사는 별도다.

## Review Focus

- 장이 여러 문단일 때 제목·문장별 근거가 손실되거나 잘못 연결되지 않는가.
- 편집·다른 책 열기·화자 변경 후 이전 문서와 검증 상태가 남지 않는가.
- pipeline의 `memoir_max:null`·메타 누락·비활성 상태를 무조건 생성 가능으로 보지 않는가.
- 지원하지 않는 문체·잘못된 UUID·부분 실패를 유효한 서버 요청/완성본으로 만들지 않는가.
- 목업 생성 대기 중 화자가 바뀌어도 원래 화자와 작업이 유지되는가.

## Task 1: 응답 변환과 문서 보존

Files: create `service-contract.js`, `service-contract.test.cjs`.

Interfaces: `postcardView(session,postcard,presentation)`, `memoirView(result,context)`, `editMemoir(document,{title,body})`, `jobView(response,context)` exported as `MemoirServiceContract` and CommonJS. 문서에는 body 배열·sections·sourceResult·sources·verification·elder_id·job_id·uiStyle·canRead·edited를 보존한다. malformed/partial 응답은 canRead=false 또는 명확한 오류로 거절한다.

- [x] 장/문단/출처 보존, legacy body, 잘못된 결과, 검증 상태, 편집 근거 만료에 대한 실패 테스트를 작성·실행한다.
- [x] 순수 변환을 구현하고 해당 테스트를 통과시킨다.

## Task 2: 서버 정책·인터뷰 명령

Files: extend `memoir-policy.js/.test.cjs`, `interview-state.js/.test.cjs`.

Interfaces: `serverPolicy(metadata)`, `styleBinding(uiStyle)`, `prepareRequest(input,metadata)`; input={mode,sessionIds,elderId,excludeSessionIds,uiStyle}. Returns {ok,body,code}. `fromSnapshot(snapshot)` maps server states to visual phase; `commandFor(action)` describes scope/endpoint or supported=false. 기존 함수는 유지한다.

- [x] null 상한의 모드 차이·메타 누락·비활성·UUID·중복·문체·명령 의미의 실패 테스트를 작성·실행한다.
- [x] 정책·명령 함수를 구현하고 기존/신규 테스트를 통과시킨다.

## Task 3: 목업과 실제 화면 연결

Files: create `preview-service.js/.test.cjs`, `compatibility-integration.test.cjs`; modify `index.html`, `app.js`, `library-view.js`, `ebook-reader.js`, `ebook-state.js` and affected existing VM fixtures.

Interfaces: `MemoirPreviewService.postcard(session,presentation)`, `createMemoirJob(records,context)` returns running job and `completeMemoirJob(job)` returns done/result. 입력·화자는 create 시점에 복사해 저장하므로 complete에 현재 화면 값을 다시 주지 않는다. 타이머와 화면 전환은 app이 소유한다. `state.document`에 변환 결과를 보존한다.

- [x] 목업→변환→편집→책 재열기와 장 제목·화자 귀속을 검증하는 실패 테스트를 작성·실행한다.
- [x] 실제 엽서 데이터·예시 생성·편집·보관·리더가 변환 경계를 사용하도록 연결한다.
- [x] 시안 전체 테스트·구문 검사와 브라우저 핵심 흐름을 확인한다.

## Task 4: 전달과 독립 검토

Files: create `COMPATIBILITY_HANDOFF.md`; add current links to `README.md`, `CONTINUATION_HANDOFF.md`, `FRONTEND_HANDOFF.md`.

- [x] 기존 API 연결 / 서버 보완 / 미결을 구분하고 로컬 기준 커밋·원본·배포 경로 의제를 기록한다.
- [x] 독립 검토자의 중요한 지적을 수정하고 필요한 테스트를 다시 실행한다.
- [x] 결과·검증·실제 연결의 한계를 기록한다. 사용자가 승인하지 않은 배포·커밋은 하지 않는다.

## Progress

- Baseline: 기존 테스트 56/56 통과. 구현 전 Git 상태는 `?? prototype/ui-review/`, HEAD `7400e51`.
- Ruling: 시안 파일이 현재 작업 폴더에 미추적으로 존재하므로 별도 worktree로 이동하지 않고 승인된 시안 폴더 안에서 작업한다.
- Task 1 complete: 변환 테스트 18/18. 제목 fallback·시각 우선순위·원문 공백·편집 근거 만료 포함.
- Task 2 complete: 정책/인터뷰 테스트 28/28. nullable 상한·미지원 문체·sparse UUID·비문자 명령 포함.
- Task 3 complete: 목업·문서·책장 연결 및 회귀 테스트. create 시점 입력 복사와 임시 job_id 분리.
- Final review: 독립 검토 수행. 단일 엔진 전체 제외 상한에 대한 지적은 실제 `select()` 호출 경로를 확인해 철회됨. 기존 정책을 유지한다.
- Final fixes: 이전 문서 보존, 장 제목 반복 방지, 다문단 장의 목차 현재 표시를 RED→GREEN으로 검증했다. 미룬 코드 지적은 없다.
- Final verification: `node --test prototype/ui-review/*.test.cjs`에 해당하는 전체 104/104 통과. JS/CJS 25개 `node --check` 통과. 브라우저 핵심 흐름·warn/error 0건 확인. 실제 연결 검증과 로컬 검증을 구분한다.
