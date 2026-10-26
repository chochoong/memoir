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
- **v4 보완 (미커밋)**: 시험 계획 턴 14 · 29 core · 사건 순서, fact_token 보조 검사(경고), 장 · 편집 지시문 v4 소폭. 8P 107 / 전체 176, 호출 0. 다음: 한 장 시험 재실행 여부 결정
- **시험 격리**: `tests/conftest.py` 가 키를 비우고 클라이언트 · 외부 연결을 막는다 — `.env` 에 실제 키가 있어도 `pytest tests` 로 비용이 나지 않는다(서버의 `question.warmup` 'ping' 포함)
- **Status**: 독립 파이프라인 구현 · 모의 시험 완료, 실제 모델 시험 전. 서버 판 호환 수정 뒤 105 passed · theme-interview 사본 36 passed · 실제 호출 0. 로컬 커밋(push 없음). `backend-agent/.env` 없음 — 실제 호출 전 사용자가 키를 로컬에만 넣는다
