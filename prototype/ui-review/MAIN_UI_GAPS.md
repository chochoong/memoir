# main에서 계승할 기능과 시안의 설계 공백

2026-11-09. 비교 기준은 main `088b23f40efce837909cdc54faa388fa2c2016fb`와 현재 `prototype/ui-review`입니다. main 원본을 읽어 확인했으며 배포 서버의 실행 결과를 뜻하지 않습니다. main·develop·백엔드는 수정하지 않았습니다.

조사 후 `main` 참조로 재조회한 `index.html` blob `0cf738b3a91b3b481fcb1e976a484d2a633c3cdb`와 `book.html` blob `6666df60a5ab273814d37d8dff626f8ba488c1b9`가 위 기준과 일치함을 확인했습니다.

후속 채팅의 현재 로컬 clone에는 `main` 참조와 위 고정 커밋 객체가 없습니다. 추가 완료 흐름 조사에서는 GitHub 연결 도구로 `main:prototype/index.html`의 4010~4139행·5075~5340행을 읽었고, 응답 blob이 위 `index.html`과 같음을 재확인했습니다. 오래된 로컬 `prototype/index.html`을 main 원문으로 간주하지 않습니다.

현재 시안은 화면 검토용입니다. 실제 데이터·음성·생성 작업은 연결하지 않았습니다. 아래의 기존 동작을 새 UI에 연결하는 설계가 필요합니다. main 전체를 병합하는 작업을 승인한 문서는 아닙니다.

## 먼저 맞출 항목

| 우선순위 | main에 있는 기능 | 현재 시안과 차이 · 다음 설계 |
|---|---|---|
| P0 | 보호자 관리 화면과 어르신 `/i#토큰` 진입 분리 | 시안은 모든 사용자에게 같은 네 메뉴를 보여줍니다. 어르신은 초대받은 인터뷰로 바로 들어가고 관리·생성 메뉴를 보지 않는 별도 구성이 필요합니다. |
| P0 | 실제 화자 등록·선택·추가, 화자 미지정 기록의 귀속 | 현재 `Google Login Mock Data`와 화자 `나`는 고정 예시입니다. 로그인 계정과 이야기 주인공을 구분하고 목록·인터뷰·자서전에 실제 화자 ID를 연결해야 합니다. |
| P0 | 초대 링크 발급·복사·취소·재발급·상태 목록 | 현재 없음. 보호자가 준비하고 다른 기기의 어르신이 참여하는 흐름을 배치해야 합니다. 발급 주소가 한 번만 표시되는 계약도 보존합니다. |
| P0 | 서버 상태에 따른 질문 낭독·수음·정리, 실제 일시정지·이어 듣기·글 전환 | 현재는 라디오 표시와 로컬 질문만 바뀝니다. 마이크 권한 실패의 글 입력 대안, 업로드 중 상태, 중복 전송 차단, 실패 시 입력 보존을 계승합니다. |
| P0 | 인터뷰 완료 → 저장 확인 → 나눈 이야기 조회 → 별도 엽서 생성 | 미리보기 UI는 완료 → 입력한 이야기 확인 → 명시적인 예시 엽서 만들기로 나눴습니다. 나중에 만들 이야기의 현재 탭 보관·재조회·빈 완료 차단·중복 방지를 반영했습니다. 실제 마지막 발화 확정·업로드·DB 저장 대기·저장 기록 재조회·서버 실패 처리는 아직 연결 전입니다. |
| P0 | 화자별 서버 제한·전체 선택 후 제외·목록 밖 기록 포함 안내 | 현재는 예시 엽서를 직접 선택합니다. main은 `memoir_max`에 따라 직접 선택과 `{elder_id, exclude_session_ids}`를 전환합니다. 오래된 목록 밖 기록이 포함되는 범위도 알려야 합니다. |
| P0 | 자서전 생성 작업 시작·진행·취소·복구 | 현재 850ms 뒤 예시 본문을 조합합니다. main의 비동기 작업·단계 표시·409 기존 작업 이어보기·작업 ID 복원·취소를 계승해야 합니다. |
| P1 | 실제 지원 문체·자료 부족·부분 실패·입력 과다 등 결과 판정 | 시안의 네 문체는 자체 예시입니다. main 문체 코드는 `spoken/novel/cyworld`, 기본 허용 목록은 `spoken`입니다. 실제 지원 목록과 UI 이름의 대응을 합의해야 합니다. 자료 부족을 완성본으로 표시하지 않습니다. |
| P1 | 인터뷰 소재 준비와 사진, 결과 엽서 이미지·문체 재생성·PNG 저장 | 현재 질문은 고정이며 엽서는 본문 조회만 합니다. 주제·낱말 카드·보조 사진을 쓰는 준비 흐름과 사용자가 보관하는 결과물을 연결해야 합니다. 원본에서 숨긴 테마 선택 등 기능 설정도 확인합니다. |
| P1 | 빈 목록·조회 실패·세션 만료·로그아웃 시 사용자 데이터 정리 | 현재 일부 로컬 예시만 있습니다. 원본 오류 코드와 재시도·복귀 동작, 인증 해제 시 목록·사진·본문 메모리 정리를 계승합니다. |

P0는 핵심 흐름을 연결하기 전에 정할 항목, P1은 실제 사용과 실패 처리를 위해 이어서 연결할 항목입니다. 사용자가 모두 새로 구현하라고 승인한 목록은 아닙니다.

## main 원문 근거

모두 같은 고정 커밋의 `prototype/index.html`입니다.

- [역할별 진입 845행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L845), [어르신 링크 진입 5620행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L5620)
- [첫 화자 등록 835행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L835), [화자 탭·추가 5724행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L5724), [미지정 기록 귀속 4140행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L4140)
- [초대 링크 발급·취소 5890행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L5890), [링크 목록 5953행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L5953)
- [글 전송·오디오 대기 3006행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L3006), [일시정지·이어 듣기 3370행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L3370), [전송·입력 보존 3458행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L3458)
- [완료·마지막 저장 대기 5242행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L5242), [저장 기록 조회·엽서 생성 4010행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L4010)
- [서버 제한과 요청 모드 4582행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L4582), [화자별 목록·전체 제외 4684행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L4684)
- [생성 시작·조회·취소·복구 5032행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L5032), [결과 판정 4881행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L4881), [지원 문체 1699행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L1699)
- [소재·사진 준비 897행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L897), [마이크 실패 대안 3068행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L3068), [엽서 결과·PNG 저장 1028행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L1028)
- [401 처리 1805행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L1805), [인증 해제 시 정리 5818행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L5818)

## 자동으로 가져오면 안 되는 것

- `book.html`에는 책에 이어 쓰기·다른 책으로 장 이동·책에서 빼기·미수록 이야기 보관함이 있습니다. 브라우저 저장 기반입니다. 현재 요청한 **얇은 책 여러 권 → 나중에 합본** 모델과 관계를 먼저 정해야 하므로 그대로 복사하지 않습니다. [책 관리 7459행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/book.html#L7459), [이어 쓰기 8256행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/book.html#L8256)
- 엽서 부분 수정·삭제·취소는 main의 **FE-01 lab 모의**입니다. 일반 엽서의 저장 가능한 편집 기능으로 확정하지 않습니다. [lab 1276행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L1276)
- 인터뷰의 일시정지·이어 듣기를 새로고침 후 일반 회차 자동 재개와 혼동하지 않습니다. main은 새 시작 전에 이 기기에 남은 이전 회차를 조회해 닫습니다. [2959행](https://github.com/chochoong/memoir/blob/088b23f40efce837909cdc54faa388fa2c2016fb/prototype/index.html#L2959)
- `GET /api/memoirs/latest`는 백엔드에 있지만 main 프론트는 저장된 작업 ID로 복원합니다. 제안·목업으로 표시된 `chapters` 처리도 서비스 완료 기능으로 단정하지 않습니다.
- backend의 `memoir_enabled` 메타는 main 목록 처리부에서 아직 읽지 않습니다. 계정별 생성 가능 여부 UI는 추가 연결이 필요한 설계 항목입니다.
- 목록 초기 조회는 main 100개, 현재 기준 develop은 20개입니다. 둘 다 전체 기록 조회와 같지 않으며 전체 제외 요청은 서버가 집계합니다. 실제 생성 순서는 서버 `created_at` 기준이므로 클릭 순서와 구분합니다.

## 권장 후속 순서

역할·화자·초대 진입부터 정하고, 인터뷰 완료와 기록·엽서 생성 단계를 맞춘 뒤, 자서전 선택·진행·실패·복구를 연결하는 순서를 권합니다. 기존 API 계약과 상태 처리를 재사용하며 새 UI에 배치합니다. 실제 연결 전에는 [서버 전달서](FRONTEND_HANDOFF.md)와 [로그인 전달서](LOGIN_HANDOFF.md)를 함께 확인합니다.
