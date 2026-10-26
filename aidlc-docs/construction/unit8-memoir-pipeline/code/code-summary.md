# Code Summary — 단위 8P: 자서전 5단계 독립 실행 파이프라인

**저장소**: `C:\work\memoir-team` · 브랜치 `feature/memoir-pipeline` (바탕 develop `f72d6df`) · 미커밋
**생성 위치**: 처음 `C:\work\memoir` 에서 생성 · 시험하고, 2026-10-26 사용자 지시로 같은 상대 경로에 복사했다(복사 때 8개 파일 SHA-256 일치). 그 뒤 이 저장소에서 서버 판 호환 수정으로 `tools/memoir_pipeline.py` · `tests/test_memoir_pipeline.py` 두 파일이 바뀌었다 — 원본과 이제 다르다.

## 파일
| 파일 | 종류 | 내용 |
|---|---|---|
| `backend-agent/app/session/memoir_pipeline.py` | 새 | 설정(`MEMOIR_PIPE_*`) · 지시문 로더 · 입력 검사 · 장 원자료 줄이기 · 단계별 검사 · 호출 · `run` · 기록 · R1 요약 |
| `backend-agent/tools/memoir_pipeline.py` | 새 | 실행기 — `--seed`+`--aliases` / `--input` · `--out-dir` · `--dry-run` |
| `backend-agent/첨부프롬프트_md/파이프라인/1_분석_v1.md` | 새 | 가치 · 사건 분석 |
| `backend-agent/첨부프롬프트_md/파이프라인/2_목차_v1.md` | 새 | 목차 · 장별 focus/context 턴 |
| `backend-agent/첨부프롬프트_md/파이프라인/3_장집필_v1.md` | 새 | 장 하나 집필 · supported/editorial |
| `backend-agent/첨부프롬프트_md/파이프라인/4_편집_v1.md` | 새 | 통합 편집 · edit_notes |
| `backend-agent/첨부프롬프트_md/파이프라인/5_검증_v1.md` | 새 | 장/문단/문장 위치 검증 · 출력 5키 |
| `backend-agent/tests/test_memoir_pipeline.py` | 새 | T01~T21 · T18b~e (36개, 가짜 호출) |
| `.gitignore` | +2줄 | `backend-agent/eval/runs/` |
| `backend-agent/.env.example` | +19줄 | `MEMOIR_PIPE_*` 이름 · 기본값 설명 |

## 함수 (`memoir_pipeline.py`)
- 설정 · 지시문: `settings` · `common_rules`(자서전_v2.md `## 2.` 만) · `role_text` · `prompt` · `prompt_hashes`
- 입력: `build_input`(memoir.merge) · `check_input` · `input_ref` · `chapter_source`(Q4)
- 검사: `check_analysis` · `check_outline` · `check_chapter` · `check_final` · `check_verify` · `locations`
- 호출: `CallSpec` · `Reply` · `call_model`(question._client, 한 번)
- 실행: `run` · `Recorder` · `r1_summary`
- 기존 모듈에서 쓰는 것: `memoir.merge` · `memoir.DEFAULT_TEXT_MODEL` · `memoir.MIN/MAX_SESSIONS` · `question._client` · `conf.env_*` · `seed_sessions.rows/check_seed/SET_IDS`. 밑줄 함수 `roledoc._sections` · `memoir._ints` 는 쓰지 않는다

## 서버 판 호환 (2026-10-26T05:45Z)
- `feature/theme-interview` 는 `memoir.MAX_SESSIONS` 상수를 없애고 `max_sessions()`(`MEMOIR_MAX_SESSIONS`, 기본 5)로 바꿨다. 실행기가 상수를 직접 읽어 그 판 위에서 테스트 29개가 깨졌다
- `tools/memoir_pipeline.py` 에 `session_range()` — 함수가 있으면 함수, 없으면 상수, 둘 다 없으면 지어내지 않고 입력 거부. 서버 파일은 고치지 않았다
- 회귀 방지 테스트 T18b(상수 판) · T18c(함수 판) · T18d(둘 다 없음) · T18e(두 판에 모두 있는 이름만 쓰는지 소스 검사)
- 실행기 요약 줄에 단계별 token usage 와 `human_review=not_run — 최종 완성본이 아니다` 를 찍는다

## 검증 (memoir-team, 2026-10-26T05:45Z)
- import · 지시문 5개 로드 · 지시문 해시가 원본에서 낸 값과 같음
- `pytest tests` — **105 passed**(기존 69 + 새 36) · 건너뜀 0. `GEMINI_API_KEY` 없이, Gemini 클라이언트 생성을 막은 상태로 실행 → 생성 시도 0
- 최신 `feature/theme-interview`(`460b855`) 코드에 8P 파일을 얹은 scratchpad 사본 — 새 테스트 36 passed · dry-run 같은 input_ref
- dry-run (seed A s-a,s-b,s-c) — 회차 3 · 말씀 6턴 · input_ref `2cb1cab7737f` · 호출 0
- 실행 환경: `backend-agent/.venv` (Python 3.13.15 · requirements.txt + pytest 9.1.1). git 제외

## 개선 v2 (2026-10-26T06:25Z, 미커밋)
- 지시문 `*_v2.md` 다섯 개를 쓰고 `ROLE_FILES` 를 v2 로 바꿨다. v1 은 기준선 기록으로 남는다 (`PROMPT_VERSION`)
- 새 함수: `excluded_turns` · `text_metrics` · `verify_plan`. 바뀐 검사: `check_analysis`(턴 덮기 · 제외 · strength) · `check_outline`(사건 배치 · 이유 · 제외) · `chapter_source`(제외 턴 빼기) · `check_final`(장 합치기 · structure_notes · 제외) · `check_verify`(category · 구성 code · accept_limit · blocker+pass)
- 테스트 47 (기존 36 + T22~T32) · 전체 116 passed · theme-interview 사본 47 passed
- 보완(06:39Z): `exclusion_notices` · `stage_source` 추가, exclusions 에 mode(whole · partial). 테스트 56 · 전체 125
- 시험 격리: `tests/conftest.py` (새 파일) — `.env` 에 실제 키가 있어도 `pytest tests` 는 외부를 부르지 않는다. 기존 서버의 `question.warmup` 이 'ping' 을 보내던 원인을 막는다

## 개선 v3 (2026-10-26T07:01Z, 미커밋)
- 지시문 `*_v3.md` 다섯 개 · `PROMPT_VERSION = "v3"` (v1 · v2 파일은 남김)
- 새 함수: `draft_locations` · `check_edit_notes` · `outline_memos` · `memo_leaks` · `meta_sentences`. `check_final` 이 장 초안(drafts)을 받아 edit_notes 의 before 를 검사, 목차 메모 혼입은 memo_leak
- `verify_plan` 이 앞 단계 경고를 `checks` 로 넘긴다. metrics 에 `edit_actions`
- 테스트 72 (T39~T43 추가) · 전체 141 passed

## Seed C (2026-10-26, 07:22Z 확정)
- `eval/memoir_seed_C.json` — 가상 화자 · 5회차 · 39턴 · `synthetic: true` · input_ref `b9f8e2daea65` (턴 34 주어 수정 뒤)
- `tools/memoir_pipeline.check_pipeline_seed` — A · B 는 팀 `check_seed` 그대로, C 는 같은 함수에 set_id 만 바꿔 끼운 사본을 넘긴다(`PIPELINE_SET_IDS = ("C",)`). `seed_sessions.py` 는 고치지 않았고 C 는 DB 에 넣지 않는다
- 테스트 T44~T47 · 76 passed · 전체 145

## v4 (2026-10-26T08:05Z, 미커밋) — `../improvement-v4.md`
- 지시문 `*_v4.md` 다섯 개 · `PROMPT_VERSION = "v4"` (v1~v3 남김)
- 새 함수: `chapter_owned_turns` · `event_packets` · `chapter_threads` · `code_findings` · `verbatim_runs` · `check_resolutions` · `code_gate` · `overall_state` · `trial_plan` · `run_chapter_trial` · `_years` · `_essay_ending` · `_narration`
- 바뀐 것: `check_analysis`(threads · 다중 시점 경고) · `check_outline`(role · threads · opening/closing · theme_use · 모음 장 경고) · `chapter_source`(다른 장 턴 이웃 제외 · 사건 묶음 순서) · `chapter_message`/`edit_message`(packets · threads · checks) · `check_final`(checks_resolution 필수, memo_leak 은 code_gate 로) · `_result`(code_gate · model_verdict · overall · code_findings) · R1 요약
- 실행기: `--chapter-trial PLAN` (호출 1회)
- 테스트 93 · 전체 162
- 실행 전 확인(08:13Z): `context_findings`(context_only, fix) · 장 입력에 `core_turns` · `context_only_turns` · `00_input.json` 에도 기록. 테스트 100 · 전체 169
- 보완: `fact_findings`(fact_token, fix · kept+이유면 code_gate 통과 — `accepted_facts`) · `_fact_tokens` · `_num_supported` · `_FACT_NUM` · `_PLACE`. 장 초안 · 편집본 · 한 장 시험 모두 검사. 테스트 107 · 전체 176

## 실행
```
cd backend-agent
.venv\Scripts\python tools/memoir_pipeline.py --seed eval/memoir_seed_A.json --aliases s-a,s-b,s-c --dry-run
.venv\Scripts\python -m pytest tests/test_memoir_pipeline.py -v
```

## 아직 하지 않은 것
- 실제 모델 호출 (Step 10) — 사용자 확인 대기. `backend-agent/.env` 가 이 저장소에 없다 (키를 사용자가 넣어야 함)
- 커밋 · push
- 서비스 연결 (단위 8S)
