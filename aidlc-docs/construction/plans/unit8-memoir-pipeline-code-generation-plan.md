# Code Generation Plan — 단위 8P: 자서전 5단계 독립 실행 파이프라인

**상태**: 확정 2026-10-26T05:14Z · Step 1~9 완료 (생성은 `C:\work\memoir`, 2026-10-26T05:33Z 에 `C:\work\memoir-team` 으로 복사 · 재검증). **Step 10(실제 모델 호출)은 사용자 확인 대기.**
**이 계획이 단위 8P Code Generation 의 유일한 기준이다.** 적힌 단계만, 적힌 순서대로.

## Unit Context
- **설계**: `aidlc-docs/construction/unit8-memoir-pipeline/functional-design/` (승인 2026-10-26T05:10Z, 변경 반영)
- **요구사항**: FR-MEM-1~8 (독립 실행 범위) · NFR-5 · NFR-7 · C-5 · C-6 · C-7
- **선행**: 없음. 이 저장소(develop `f72d6df` 바탕)에는 단위 1 · 4 산출물이 없고, 8P 는 그것에 기대지 않는다 (seed · DB 미사용)
- **Workspace Root**: `C:\work\memoir-team` (처음 생성은 `C:\work\memoir`, 사용자 지시로 같은 상대 경로에 복사 · SHA-256 일치)
- **고치지 않는 파일**: `memoir.py` · `main.py` · `roledoc.py` · `postcard.py` · `question.py` · `store.py` · `자서전_v2.md` · `검증_v4.md` · 기존 테스트 전부

## 생성 · 수정 파일
| 파일 | 종류 |
|---|---|
| `backend-agent/app/session/memoir_pipeline.py` | 새 |
| `backend-agent/tools/memoir_pipeline.py` | 새 |
| `backend-agent/첨부프롬프트_md/파이프라인/1_분석_v1.md` ~ `5_검증_v1.md` | 새 5개 |
| `backend-agent/tests/test_memoir_pipeline.py` | 새 |
| `.gitignore` | 수정 — `backend-agent/eval/runs/` |
| `backend-agent/.env.example` | 수정 — `MEMOIR_PIPE_*` 이름 · 기본값 |
| `aidlc-docs/construction/unit8-memoir-pipeline/code/code-summary.md` | 새 (문서) |

## Steps

### Step 1: 설정 · 오류 · 로더 · 작은 검사 함수
- [x] `settings()` — `MEMOIR_PIPE_TEXT_MODEL`(기본 = `memoir.DEFAULT_TEXT_MODEL` 값) · `MEMOIR_PIPE_TEMPERATURE` 0.3 · 단계별 `MEMOIR_PIPE_<STAGE>_TIMEOUT` / `_MAX_OUTPUT_TOKENS` (60/5000 · 60/4000 · 90/6000 · 120/8000 · 90/5000) · `MEMOIR_PIPE_TOTAL_TIMEOUT` 600 · 장 1~5 · 재시도 0(고정)
- [x] `PipelineError(stage, kind, message, chapter_key)`
- [x] `prompt(stage)` — `자서전_v2.md` `## 2.` 절만 읽는 작은 로더 + 역할 파일. `roledoc` 미사용
- [x] `_int_list` · 턴 · 문장 항목 · 제목 · 위치 검사 (밑줄 함수 의존 없음)

### Step 2: 입력 · 호출
- [x] `build_input(records)` — `memoir.merge` · `T` · `input_ref`
- [x] `check_input(data, turn_map)` — `--input` 용 모양 검사
- [x] `chapter_source(...)` — Q4 의 `given_turns` 와 줄인 원자료
- [x] `call_model(spec)` — `question._client`, JSON mime · 온도 · 토큰 · 자동 함수호출 끔, 원응답 · finish · usage 반환

### Step 3: 단계 함수와 검사
- [x] `analyze` · `check_analysis` · `outline` · `check_outline`(0장 format · 6장+ chapter_limit) · `write_chapter` · `check_chapter`(given_turns) · `edit` · `check_final` · `verify` · `check_verify`(위치)

### Step 4: 실행 · 기록
- [x] `run(data, turn_map, *, call, recorder)` — S0~S8, 첫 실패에서 멈춤, 재시도 없음, 호출 수 · 전체 시간 상한, 호출마다 `min(단계 시간, 남은 시간)`
- [x] 상태: `generation_state` · `pipeline_complete` · `verification{state, verdict}` · `human_review="not_run"`
- [x] `Recorder` — 단계 JSON · 원응답 · `run.json` · `result.json` · `r1_summary.md`(본문 · 원문 · 설명문 · 비밀값 없음)

### Step 5: 실행기 `tools/memoir_pipeline.py`
- [x] `--seed` + `--aliases` / `--input` · `--out-dir` · `--dry-run`
- [x] `records_from_seed` — `check_seed` · alias 3~5 · `rows` · 시각
- [x] `load_input` — memoir_input 출력 모양 · set_id · 모든 발언이 seed 원문과 같은지 (K-1)
- [x] 요약 출력 · 종료 코드 0 / 1 / 2

### Step 6: 역할 지시문 5개
- [x] `1_분석_v1.md` · `2_목차_v1.md` · `3_장집필_v1.md` · `4_편집_v1.md` · `5_검증_v1.md` (각 파일 끝에 출력 계약)

### Step 7: 테스트 `tests/test_memoir_pipeline.py` (pytest, 모델 · DB 없음)
- [x] T01 정상 — A 3회차 · 장 2개 · 호출 순서 `analysis, outline, chapter×2, edit, verify` (= 장 수 + 4) · `generated` · `pipeline_complete=true` · `human_review=not_run`
- [x] T02 호출마다 시스템 지시가 다르고 한 역할 지시문만 들어 있다 · 공통 §2 가 앞에 붙는다
- [x] T03 원문이 시스템 지시에 없고 사용자 메시지에 있다
- [x] T04 전역 턴 유지 — 분석 · 목차 · 편집 · 검증 입력의 utterances 가 merge 출력과 같고, 결과의 모든 turns ⊂ T
- [x] T05 장 입력 제한 (Q4) — 장 호출에는 given_turns 원문만 있고 다른 장 원문은 없다 · 같은 회차 앞뒤 1턴 · context_turns 가 들어간다
- [x] T06 분석에 없는 턴 → `failed(analysis, reference)` · 목차 미호출
- [x] T07 목차 0장 → `format` · 6장 → `chapter_limit` (자르지 않음) · 없는 event_key → `reference` · 장 미호출
- [x] T08 장 2 시간 초과 → `partial` · `pipeline_complete=false` · ch-1 파일 남음 · ch-3 · 편집 · 검증 미호출 · `chapters` 비어 있음
- [x] T09 장 출력 잘림(`MAX_TOKENS`) → `partial(truncated)` · 깨진 JSON → `partial(format)`
- [x] T10 supported 빈 turns → 실패 · editorial 빈 turns → 통과 · given_turns 밖 인용 → `reference`
- [x] T11 편집에서 장 누락 · 순서 바뀜 · 없는 위치의 edit_note → `failed(final_check)` · 검증 미호출
- [x] T12 검증 `revise` → `generated` · `pipeline_complete=true` · `verdict=revise` · 추가 호출 없음
- [x] T13 검증 출력 모양 오류 · 없는 위치 → `verification.state=failed` · `pipeline_complete=false`
- [x] T14 분석 `insufficient_material` → 호출 1회로 정상 종료
- [x] T15 재시도 0 — 실패한 단계가 정확히 한 번 불렸다
- [x] T16 키 없음 → 네트워크 없이 `failed(analysis, call)`
- [x] T17 `MEMOIR_PIPE_*` 와 `MEMOIR_*` 가 서로 영향을 주지 않는다
- [x] T18 잘못된 input 스키마 또는 허용되지 않은 입력 거부 — seed 검사 실패 · alias 개수 · memoir_input 모양 · seed 에 없는 발언 · run() 에 깨진 입력 → 호출 0
- [x] T19 run 폴더 파일이 있고 `run.json` · `r1_summary.md` 에 키 값 · 본문 · 원문이 없다
- [x] T20 역할 지시문 5개가 모두 읽힌다 · 밑줄 함수(`roledoc._sections` · `memoir._ints`)를 쓰지 않는다
- [x] T21 전체 시간 상한 — 남은 시간이 없으면 다음 호출 전에 `budget`

### Step 8: 설정 · 문서
- [x] `.gitignore` · `.env.example`
- [x] `code-summary.md`

### Step 9: 회귀
- [x] `.venv\Scripts\python -m pytest tests -v` — 기존 + 새 테스트 전부, 건너뜀 수 기록 → memoir-team: 101 passed (기존 69 + 새 32), 건너뜀 0, Gemini 클라이언트 생성 0
- [x] 서버 판 호환 (사용자 지시 2026-10-26T05:45Z) — `session_range()` (상수 · `max_sessions()` 둘 다) · 테스트 T18b~e → 105 passed · theme-interview 사본 36 passed
- [x] `--dry-run` 으로 A 3회차 입력이 만들어지는지 (호출 0)

### Step 10: 실제 모델 1회 — **사용자 확인 뒤**
- [x] 확인 받을 것: 변경 파일 · 테스트 결과 · 예상 호출 수 · 모델 · 설정 · 명령
- [x] seed A 3회차 1회 실행, run 폴더 · R1 요약 확인 (MEM-T01~T06 은 사람이 읽고 판정) → 2026-10-26T06:07:37Z run 20261026T060737Z-A3-2cb1, 7회 완주, R1 문서 build-and-test/R1-20261026T060737Z-A3.md. 사람 판정: 기술 실행 성공 · 콘텐츠 품질 미승인 → 기준선

### Step 11: 개선 v2 — 사용자 지시 2026-10-26 (`unit8-memoir-pipeline/improvement-v2.md`)
- [x] 원인 분석 (지시문 · 계약 · 코드, 제외 턴 유입 · 사건 누락 발견)
- [x] 지시문 v2 다섯 개 (`*_v2.md`, v1 은 기준선으로 남김) · `PROMPT_VERSION`
- [x] 계약 · 코드: 분석 exclusions · not_in_events · strength · 턴 덮기 / 목차 structure_reason · grouping_reason · left_out · 사건 배치 / 장 입력에서 제외 턴 빼기 / 편집 from_chapters(합치기) · structure_notes / 검증 category · 구성 code · accept_limit · plan / text_metrics
- [x] 테스트: 기존 36 유지(fixture 만 v2 계약으로) + T22~T32 11개 → 47 passed · 전체 116 passed · theme-interview 사본 47 passed · dry-run A3 · A5 · B · 호출 0
- [x] 보완 (2026-10-26T06:39Z): 제외 mode(whole · partial) · `stage_source` · `exclusion_notices` · 지시문 완화 · `tests/conftest.py`(외부 호출 차단) · R1 검수 6항목 → 56 passed · 전체 125 · theme-interview 사본 56 · 막은 시도 0
- [x] 커밋 9231a70 · A3 실제 1회 (2026-10-26T06:44:53Z) → failed(final_check, edit_notes 삭제 위치) · R1-20261026T064453Z-A3-v2.md
- [x] 보완 N-1~N-4 (2026-10-26T07:01Z, `unit8-memoir-pipeline/improvement-v3.md`) — 지시문 v3 · 편집 메모 계약 · 메모 혼입 검사 · 테스트 T39~T43 → 72 passed · 전체 141 · theme-interview 사본 72 · A3 dry-run 호출 0
- [x] v3 커밋 5ae6c1c · v3 A3 실제 실행은 생략 (사용자 판단 — A3 는 자료가 너무 적다)
- [x] seed C (2026-10-26T07:12Z) — `eval/memoir_seed_C.json` 39턴 · `check_pipeline_seed`(팀 도구 무수정) · 평가 기준 문서 · T44~T46 → 75 passed · 전체 144 · dry-run 호출 0
- [x] seed C 재검토 (2026-10-26T07:22Z) — 34 주어 최소 수정 · 연대기 기준 · 정정 판정 분리 · T47 → 76 passed · 전체 145 · input_ref b9f8e2daea65 · 로컬 커밋
- [ ] v3 · seed C 실제 1회 — 사용자 승인 뒤
- [ ] N-5 일부 제외 범위 지정 방식 → B (B 실제 실행 미승인)
