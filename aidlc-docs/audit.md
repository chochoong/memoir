# AI-DLC Audit Log — memoir-team

## 이전 작업 폴더에서 승인된 것 (요지)
단위 8P 의 계획 · 설계 · 코드 생성은 `C:\work\memoir`(feature/aidlc-solo)에서 진행됐다. 그 폴더의 audit.md 에는 이 기록이 들어가지 않았다(단위 4 와 섞지 말라는 지시). 아래는 같은 세션의 사용자 입력 요지다.

| 시각 (UTC) | 단계 | 사용자 입력 요지 | 처리 |
|---|---|---|---|
| 2026-10-26T05:02Z | Workflow Change · FD Plan | "Using AI-DLC로 진행 … 자서전 고도화 작업 단위를 새로 … 장 실패 정책 수정(장 하나 실패 시 이후 호출 중지 · partial · 편집/검증 미실행 · 재시도 0)" | 단위 8P 계획 · 설계 문서, 질문 Q1~Q6 |
| 2026-10-26T05:10Z | FD Approval | "설계 방향 승인합니다. 다만 아래 내용을 반영한 뒤 구현 단계로 … Q1 1~5장 · Q2 단계별 시간/토큰 · Q3 합성 seed 만 · Q4 장마다 해당 원문만 · Q5 eval/runs · Q6 A3→B→A5 · is_final 대신 상태 분리 · private 함수 의존 줄이기 · 새 검증 지시문" | 설계 확정, Code Generation Step 1~9 실행 (원본 폴더 189 passed) |

---

## Workflow Change - 작업 폴더 이전
**Timestamp**: 2026-10-26T05:33Z
**User Input**: "작업 폴더를 C:\work\memoir-team 으로 옮긴다. 지금까지 만든 memoir_pipeline.py 두 파일을 그쪽 같은 경로로 복사하고, 이 폴더(C:\work\memoir)에는 더 쓰지 마라. 지시서 02 기준으로 그쪽에서 계속."
**AI Response**: "두 파일을 같은 경로로 복사(바이트 동일). 의존 모듈 · 프롬프트 · seed 가 두 폴더에서 같음을 확인. dry-run 통과. 지시문 5개 · 테스트는 아직 복사하지 않았다고 보고."
**Context**: CONSTRUCTION - 단위 8P, 작업 폴더 이전

---

## Code Generation 단위 8P - 결과물 이전 · 재검증
**Timestamp**: 2026-10-26T05:33Z
**User Input**: "기존에 작성한 Unit 8P 결과물을 재사용하겠습니다. 새로 만들지 말고 검증된 파일을 C:\work\memoir-team으로 옮겨주세요. (지시문 5개 · test_memoir_pipeline.py · .gitignore 의 eval/runs 규칙 · .env.example 의 MEMOIR_PIPE_* — 필요한 항목만) … 해시 비교 … 독립 .venv … import · 프롬프트 · 신규 32 · 기존 회귀 · dry-run · 실제 호출 0 확인 … Unit 8P 기준 AI-DLC 기록, Unit 4 · 8a 를 완료로 기록하지 말 것 … 커밋 · push 는 별도 지시 후. 아직 Gemini 실제 호출은 하지 않습니다."
**AI Response**: "지시문 5개 · 테스트 복사, .gitignore(+2) · .env.example(+19) 에 해당 항목만 추가(CRLF 유지). 코드 · 지시문 · 테스트 8개 SHA-256 원본과 일치. backend-agent/.venv 새로 구성(Python 3.13.15, requirements.txt + pytest). pytest 101 passed(기존 69 + 새 32), 건너뜀 0 — GEMINI_API_KEY 없이 · Gemini 클라이언트 생성을 막은 상태에서 생성 시도 0. dry-run A 3회차 회차 3 · 6턴 · input_ref 2cb1cab7737f · 호출 0. 원본 폴더는 이번 작업 중 바뀐 파일 없음. 승인된 8P 설계 문서를 원본 archive/unit8-premature/ 에서 가져와 이 저장소 상태에 맞게 §12 · §13 · 계획 머리를 고쳤다. aidlc-state.md · audit.md 는 이 저장소에서 새로 시작(단위 4 · 8a 기록 미반영). 결과 확인을 요청했다."
**Context**: CONSTRUCTION - 단위 8P Code Generation, 결과 확인 대기

---

## Code Generation 단위 8P - 서버 판 호환 · 로컬 커밋
**Timestamp**: 2026-10-26T05:45:07Z
**User Input**: "Unit 8P 이전 및 검증 결과를 확인했습니다. 현재 단계는 독립 파이프라인 구현 및 모의 테스트 완료, 실제 모델 시험 전으로 판단합니다. … 1. tools/memoir_pipeline.py 에서 memoir.MAX_SESSIONS 의존 수정 — develop 과 최신 feature/theme-interview 모두 대응, 회귀 테스트 추가, 서버 파일 무수정 2. 재검증(신규 · 전체 · theme-interview scratchpad · dry-run · 호출 0) 3. 통과하면 feature/memoir-pipeline 에 8P 변경만 로컬 커밋, .env · 키 · .venv · eval/runs 제외, push · 병합 없음 4. 첫 실제 Gemini 시험 준비(seed A 3회차 · gemini-3.5-flash-lite · 재시도 0 · 장 수 강제 없음 · 단계별 원본 · 호출 수 · 시간 · 토큰 기록 · DB · 서비스 API 연결 금지 · 품질 승인 전 완성본 표시 금지). 아직 실제 Gemini 호출은 진행하지 마세요."
**AI Response**: "tools/memoir_pipeline.py 에 session_range() — max_sessions() 가 있으면 그것, 없으면 MAX_SESSIONS, 둘 다 없으면 입력 거부. 테스트 T18b~e 4개 추가. 실행기 요약에 token usage · human_review=not_run 안내 추가. pytest 105 passed(기존 69 + 새 36) · theme-interview 460b855 사본 새 테스트 36 passed · dry-run 두 판 모두 input_ref 2cb1cab7737f · Gemini 클라이언트 생성 0. 8P 변경만 로컬 커밋, push 없음. 실제 호출 승인을 기다린다."
**Context**: CONSTRUCTION - 단위 8P Code Generation 완료, Build and Test(실제 모델 1회) 승인 대기

---
