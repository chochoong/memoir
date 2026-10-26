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
- **v3 보완 (2026-10-26T07:01Z, 미커밋)**: N-1 편집 메모 action/before/after · N-2 분할 원칙(지시문) · N-3 메모 혼입 방지 · N-4 장면 추가 금지(지시문, 코드 한계 기록). 테스트 72 / 전체 141, 실제 호출 0. 다음: 승인 뒤 v3 A3 한 번 → seed C 계획(팀 결정 필요, `improvement-v3.md`)
- **시험 격리**: `tests/conftest.py` 가 키를 비우고 클라이언트 · 외부 연결을 막는다 — `.env` 에 실제 키가 있어도 `pytest tests` 로 비용이 나지 않는다(서버의 `question.warmup` 'ping' 포함)
- **Status**: 독립 파이프라인 구현 · 모의 시험 완료, 실제 모델 시험 전. 서버 판 호환 수정 뒤 105 passed · theme-interview 사본 36 passed · 실제 호출 0. 로컬 커밋(push 없음). `backend-agent/.env` 없음 — 실제 호출 전 사용자가 키를 로컬에만 넣는다
