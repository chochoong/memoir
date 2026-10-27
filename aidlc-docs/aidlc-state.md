# AI-DLC State Tracking

## Project Information
- **Project**: 내말싸미 — 자서전 고도화 (지시서 02 「작성 파이프라인」 v1.0)
- **Project Type**: Brownfield
- **Repository**: `C:\work\memoir-team` — 팀 저장소 `chochoong/memoir` 클론
- **Branch**: `feature/memoir-pipeline` (바탕 develop `f72d6df`). `develop` · `main` · `feature/theme-interview` 는 고치지 않는다
- **Start Date (이 저장소)**: 2026-10-26T05:33Z
- **Current Stage**: CONSTRUCTION — 단위 8P Code Generation 완료, 결과 확인 대기

## Workspace State
- **Existing Code**: Yes (Python FastAPI `backend-agent/` · 단일 HTML `prototype/` · React/Vite `frontend-client/`)
- **AI-DLC 규칙 위치**: 이 저장소에는 없다. `C:\work\memoir\aws-aidlc-rules\core-workflow.md` · `.aidlc-rule-details\` 를 읽기 전용으로 참고한다
- **Documentation**: `aidlc-docs/`

## 이 저장소에서 다루는 단위
| 단위 | 내용 | Functional Design | Code Generation | Build and Test |
|---|---|---|---|---|
| 8P | 자서전 5단계 독립 실행 파이프라인 | [x] 승인 (이전 작업 폴더) | [x] 생성 · 이 저장소에서 재검증 — 결과 확인 대기 | [~] A 3회차 실제 1회 완료 (R1) — 사람 검수 · 지시문 수정 · B 남음 |
| 8S | 서비스 연결 (`/api/memoirs/preview` 또는 새 라우트 · prototype) | [ ] | [ ] | [ ] |

**이 저장소에 없는 것**: 단위 1(실행 환경 · 계약 테스트) · 단위 4(화자 · 테마 · 메뉴 · 마이그레이션 009) · 단위 8a. 이들은 `C:\work\memoir`(개인 저장소) 쪽 기록이며 여기서 완료로 기록하지 않는다. 8P 는 이들에 기대지 않는다 (DB 미사용, 합성 seed 만).

## Extension Configuration
| Extension | Enabled | Decided At |
|---|---|---|
| Resiliency Baseline | No | 이전 작업 폴더 Requirements Analysis |
| Security Baseline | No | 이전 작업 폴더 Requirements Analysis |
| Property-Based Testing | No | 이전 작업 폴더 Requirements Analysis |

## Current Status
- **Lifecycle Phase**: CONSTRUCTION
- **Current Stage**: 단위 8P — Code Generation 결과 확인 대기
- **Next Stage**: 단위 8P — Build and Test (seed A 3회차 실제 모델 1회 → 수정 → B → 필요 시 A 5회차)
- **실제 시험 1차 (2026-10-26T05:51:42Z, fe94baf)**: 분석 단계에서 400 'API key not valid' — `.env` 값의 꺾쇠. 호출 1회 · 토큰 0
- **실제 시험 2차 (2026-10-26T06:07:37Z, fe94baf)**: 7회 호출 완주 · generated · pipeline_complete=true · 검증 pass · human_review=not_run · 14초 · 토큰 24,211. 사실 오류 없음, 글은 원문 나열 수준 — R1 문서 Q-1~Q-8. **사용자 판정: 기술 실행 성공 · 콘텐츠 품질 미승인 → 기준선**
- **개선 v2 (2026-10-26T06:25Z, 미커밋)**: 지시문 v2 · 최소 계약 · 코드 · 테스트 47 / 전체 116. 모의만, 실제 호출 0. 다음: 승인 뒤 A3 → B → A5 각 한 번 (`unit8-memoir-pipeline/improvement-v2.md`)
- **v2 보완 (2026-10-26T06:39Z, 미커밋)**: 제외 mode(whole · partial) · 목차/편집 원자료 거르기 · 지시문 완화 · R1 검수 6항목. 테스트 56 / 전체 125, 실제 호출 0. 다음: v2 A3 실제 1회
- **v2 커밋 · 실제 실행 (2026-10-26T06:44:53Z, 9231a70)**: 6회 호출 뒤 final_check 실패(edit_notes 가 지운 문장의 옛 위치) · 검증 미호출 · 12.8초 · 토큰 23,699. 주제 판단은 개선, 장 구성 · 나열은 그대로. 보완 후보 N-1~N-5 (R1-20261026T064453Z-A3-v2.md). B 실제 실행 미승인
- **v3 (5ae6c1c)**: N-1 편집 메모 action/before/after · N-2 분할 원칙(지시문) · N-3 메모 혼입 방지 · N-4 장면 추가 금지. v3 A3 실제 실행은 사용자 판단으로 생략(자료가 너무 적음)
- **Seed C (2026-10-26T07:22Z 확정 · 로컬 커밋)**: 가상 화자 5회차 39턴 `eval/memoir_seed_C.json`(input_ref `b9f8e2daea65`) · 파이프라인 전용 검사(`check_pipeline_seed`, 팀 도구 무수정) · 평가 기준 `build-and-test/seed-C-evaluation.md`(모델 입력 아님). 34 주어 최소 수정 · 출생 연도 미기재(원문상 1950~53년생 무렵). 테스트 76 / 전체 145, 실제 호출 0. 다음: 승인 뒤 v3 · C 실제 1회
- **v3 · Seed C 실제 실행 (2026-10-26T07:30:58Z, d3deb2b, Free 티어)**: 8회 완주 · 33초 · 토큰 79,547 · generated · pipeline_complete true · 검증 pass · human_review not_run. 정정 · 사실 · 감정 · 인물 · 장 분할은 양호, 원문 나열 · 장 사이 중복 · 편집/검증 무력은 남음 — R1-20261026T073058Z-C5-v3.md. 사람 검수 대기
- **판정 (2026-10-26)**: v3 · C 기술 실행 성공 · 콘텐츠 품질 미승인 → 기준선. 구조 재점검 `redesign-v4-analysis.md` (원인 · 검증 3갈래 · code_gate · 최소 변경안 8단계). 코드 · 지시문 무변경, 다음: 변경안 승인
- **v4 (2026-10-26T08:05Z, 미커밋)**: 1인칭 회고 수필체 · 사건과 끈 · 장 입력(다른 장 턴 제외 · 사건 묶음) · code_findings → 편집 · checks_resolution · code_gate/model_verdict/human_review/overall · 한 장 시험 모드. 8P 93 / 전체 162, 실제 호출 0. 다음: 한 장 시험 실제 1회 승인 (`improvement-v4.md`)
- **v4 실행 전 확인 (08:13Z)**: core_turns · context_only_turns 분리와 context_only 검사, kept 는 repeat_turn 말고 남은 문제로 집계(테스트). 8P 100 / 전체 169. 커밋 86c7029 → 한 장 시험 실제 1회 완료(08:14Z, 1호출 · 경고 0 · 제안 판정 통과 2 · 부분 4) — 사람 검수 대기
- **v4 보완 (미커밋)**: 시험 계획 턴 14 · 29 core · 사건 순서, fact_token 보조 검사(경고), 장 · 편집 지시문 v4 소폭. 8P 107 / 전체 176, 호출 0. 커밋 84c2f11 → 한 장 시험 재실행 1회 완료(08:30Z, 1호출 · 경고 0 · 출처 정확 · 나열은 부분) — 사람 검수 · 전체 5단계 여부 결정 대기
- **v4 Seed C 전체 (08:35Z)**: 6호출 · code_gate attention · model_verdict pass · overall needs_revision. 별개 사건 분리 · 장 경계 중복 해소, 나열 · 편집 · 검증은 남음. 다음: 사람 검수 · Draft PR 인계 여부 결정 (`R1-20261026T083510Z-C5-v4.md`)
- **판정 (2026-10-26)**: v4 품질 미승인 · 인계 보류. 목표를 '책의 한 장으로 읽히는 1인칭 회고 수필'로. 구조 재설계안 `redesign-v5-book-quality.md` (계약 원인 · 5단계 재정의 · 품질 기준 Q1~Q8 · 모델 비교 시험안). 코드 · 지시문 · 호출 없음. 다음: 재설계안 승인
- **v5 (모의, 미커밋)**: 사실 원장 · 기억 단위 · 책 설계도 · 문단 서사 · 구성 편집(edit_trace) · 사실 + 구성 채점 · --focus 한 장 시험 · 블라인드 도구. 8P 85 / 전체 154, 호출 0. 다음: 한 장 시험(5호출) 승인 (`improvement-v5.md`)
- **v5 한 장 시험 (09:34Z, a03f5c2)**: 분석 1호출에서 실패 — 정정 전 값을 별개 사실로 · 정정 기록 오지정(코드가 막음). 수필 없음. 다음: 조치 결정
- **분석 안정화 (미커밋)**: 정정 = 유효 사실 하나 + before 이력, 진단 모음, 주 단위 · keep · 전언 · 주제 검사, --analysis-only(1호출 · 기억 지도). 8P 104 / 전체 173, 호출 0. 다음: 분석만 실제 1회 승인
- **분석만 실제 1회 (2026-10-27T00:20Z, 1f1c909)**: 계약 실패 — 정정 둘로 나눔 · 턴 13 전언, 사실 39 = 턴 39, 단위 4. 다음 단계로 넘기지 않음. 다음: 조치 결정
- **보완 2차 (02b423d)**: 정정 정규화 · 전언/직접 들은 말/평가 · 감정 보존 · 사실과 기억 단위 지시문. 8P 115 / 전체 184. gemini-3.8-flash 는 쓰지 않기로(사용자 결정)
- **flash-lite 분석만 1회 (01:02Z, 02b423d)**: 계약 실패 — source='reported' 모양 1건(참고 뜻 위반 턴 13 · 16). 사실 60 · 단위 7, 정정 바르게, 38 · 32 보존. 다음: 조치 결정
- **보완 3차 (041354c) → flash-lite 분석만 (01:19Z)**: 실패 8(턴 13 · 35 세 번째 반복, 2 · 27 은 검사 오탐), 코드 정규화가 정정을 실제로 고침, 단위 5(수십 년 단위 · 무관 묶음 재발). 미세 수정 중단, 계약 단순화 / 상위 모델 결정 대기
- **A안 (미커밋)**: 분석 계약 단순화(보호 항목만 실패) · 시험용 분석 스냅샷(reviewed_fixture, 33항목 고침) · --from-analysis 후속 단계 시험(focus 4호출). 8P 137 / 전체 206. 다음: 후속 단계 실제 1회 승인
- **후속 단계 실제 1회 (01:44Z, e26ed25, reviewed_fixture)**: 4호출. 목차가 핵심 기억을 빼고 무관한 사실을 모음, 편집 무변경(edit_trace), 검증 만점 → 코드 보정으로 needs_revision. 창작은 없음. v4 한 장보다 나쁨. 다음: 구성 단계 모델 적합성 시험 결정
- **집필 시험 준비 (미커밋)**: 원인별 보완(일괄 생략 · 혼입 · 편집 허위 보고 · result.json 출처), 사람 검토 목차(outline_source=reviewed_fixture), --from-outline 3호출. 8P 152 / 전체 221. 다음: 3호출 시험 승인
- **집필 시험 (02:06Z, c276109)**: 사람 목차를 받고도 집필이 계획 사실 30 중 12만 쓰고 나열형, 편집 부분 개선 · 반복, 검증 형식 실패 · 만점. 창작 없음. 다음: 집필 · 편집 모델 재검토
- **핵심 사실 · 장 집필 비교 준비 (미커밋)**: 740토큰은 정상 종료(상한 6,000), 핵심 사실 core · core_missing → needs_revision, 검증 위치 정규화, --chapter-only --model. 8P 166 / 전체 235. 다음: 3.1 Pro preview 장 집필 1회 승인
- **Pro 장 집필 비교 (02:36Z, 0919cf9)**: 핵심 18/18 · 24문장, 원문에 없는 인과 1건 · 연결 약함. 모델 · 목차 r2 · 온도 1.0 이 함께 바뀜. 다음: 원인 가르기 · 편집 모델 결정
- **Pro 편집 단독 (02:49Z, df24863)**: 핵심 18 보존, 인과 · 과장 · 맥락 고침, 대비 첫 문단으로. 나열 신호 그대로 · 원문 말투 되돌림 · 부정 1건 누락. 책 한 장 수준 아님. 다음: 결정 대기
- **편집 계약 v6 준비**: 문단 산문 + 근거 표현(claims), 사실 오류(fix) · 사람 판단(review) 구분, 기준선 Pro 편집본 v6 검사 attention. 호출 없음 · 미커밋. (완료) v6 Pro 편집 1회 승인 대기
- **v6 Pro 편집 (04:32Z, 740674d)**: 핵심 18 보존, 구조 변화 없음, 보조 5개 생략(f16 포함), 인과 흐림 1, 구어 3. v5 편집보다 낫지 않음. 다음: 결정 대기
- **시험 격리**: `tests/conftest.py` 가 키를 비우고 클라이언트 · 외부 연결을 막는다 — `.env` 에 실제 키가 있어도 `pytest tests` 로 비용이 나지 않는다(서버의 `question.warmup` 'ping' 포함)
- **Status**: 독립 파이프라인 구현 · 모의 시험 완료, 실제 모델 시험 전. 서버 판 호환 수정 뒤 105 passed · theme-interview 사본 36 passed · 실제 호출 0. 로컬 커밋(push 없음). `backend-agent/.env` 없음 — 실제 호출 전 사용자가 키를 로컬에만 넣는다
- **자유 산문 진단 (04:51Z, fd94328)**: 사실 · 전언 · 부정 지킴, 시간 왜곡 1, 원문 문장 유사도 0.79 · 구어 다수 — 책 수준 아님. 다음: 결정 대기
- **자유 산문 2차 v2 (05:05Z, 5823f2c)**: 유사도 0.70 · 구어 · 시간 왜곡 해소, '손이 빨라서' 인과 창작 1 — 사실성 실패, 시간순 나열. 다음: 사람 편집 기준 비교
- **사람 편집 검토 자료 (05:40Z)**: 21턴 주석 · 분류 제안 · 문맥 주의 · v1/v2 원고 · 검토 질문 5. Gemini 호출 없음. 다음: 다애님 · 태헌님 검토

## 2026-10-27 기술 인계 갱신
- 사용자 요청으로 develop 대상 Draft PR 업로드 준비. 콘텐츠 미승인, 서비스 연결(8S) 미구현 유지.
- 원본 5823f2c와 미커밋 검토 자료를 사본에서 보존. 최종 299 passed, 외부 호출 시도 0. 상세: construction/unit8-memoir-pipeline/handoff-20261027.md
