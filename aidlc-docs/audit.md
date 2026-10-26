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

## Build and Test 단위 8P - 첫 실제 호출 (실패 · 키)
**Timestamp**: 2026-10-26T05:51:42Z
**User Input**: "첫 번째 실제 Gemini 모델 실행을 승인합니다. … Seed A s-a, s-b, s-c · gemini-3.5-flash-lite · 재시도 0 · 장 수 1~5 자율 · 실제 호출은 이번에 한 차례만, 실패하면 무단 재실행 · 모델 변경 금지 · 키 비공개 · memoir.py · main.py · DB · 서비스 API 무수정 · 무호출 · human_review=not_run 유지" / "C:\work\memoir-team\backend-agent\.env 에 GEMINI_API_KEY 를 넣었다. 승인한 조건대로 Seed A 3회차 실제 호출을 한 번 진행해 줘."
**AI Response**: "커밋 fe94baf 에서 한 번 실행(run_ref 20261026T055142Z-A3-2cb1). 분석 단계 첫 호출이 1327ms 만에 400 INVALID_ARGUMENT 'API key not valid' 로 실패 → failed(analysis, call), 호출 1회, 이후 단계 미호출, 토큰 사용 없음. 재실행하지 않았다. run 폴더 4개 파일에 키 값 · 앞 8자가 없음을 확인. .env 값을 예/아니오로만 점검: 한 줄 · BOM 없음 · 공백 · 따옴표 없음, 그러나 39자 · AIza 시작이 아니고 자리표시 문자('<' · 'your' · 'xxx' · '키' 중 하나)가 들어 있다 — 실제 키가 아니라 자리표시 값으로 보인다고 보고했다."
**Context**: CONSTRUCTION - 단위 8P Build and Test, 키 교체 · 재실행 승인 대기

---

## Build and Test 단위 8P - 재실행 승인 · 실행 전 보류
**Timestamp**: 2026-10-26T05:59:20Z
**User Input**: ".env 의 GEMINI_API_KEY 를 실제 키로 바꿨다. 같은 조건으로 Seed A 3회차 실제 호출을 한 번 더 진행해 줘."
**AI Response**: "실행 전 값을 예/아니오로만 점검: .env 는 14:58:28(+0900) 에 다시 저장됐지만 값이 '<' 로 시작해 '>' 로 끝나고(55자), 괄호 안쪽도 영숫자 · - · _ 밖의 문자를 담아 API 키 형식이 아니다. 실행하면 같은 400 이 확실해 승인된 한 번을 쓰지 않고 멈췄다. 모델 호출 0."
**Context**: CONSTRUCTION - 단위 8P Build and Test, 키 수정 대기

---

## Build and Test 단위 8P - 키 설정 출처 점검
**Timestamp**: 2026-10-26T06:05Z
**User Input**: "새로 발급한 Google AI Studio API 키를 사용 중입니다. … 실제 실행기가 어떤 설정을 읽고 있는지 확인 … memoir-team .env 인지 · memoir .env 혼동 · .env.txt/.env.example · GOOGLE_API_KEY 덮어쓰기 · 꺾쇠/안내 문구 · AIza·39자 조건으로 새 Auth Key 를 거부하지 말 것. 키 값 · 일부 · 해시 출력 금지, 실제 호출 금지."
**AI Response**: "실행기는 C:\work\memoir-team\backend-agent\.env 를 절대경로로 읽는다(load_dotenv, override=False). 프로세스 · Windows 사용자 · 시스템 환경에 GEMINI_API_KEY · GOOGLE_API_KEY 가 없어 .env 값이 그대로 쓰인다. memoir 의 .env · .env.example 과는 다른 값, .env.txt 없음. question._client 가 api_key 를 직접 넘겨 google-genai 의 GOOGLE_API_KEY 우선 규칙은 적용되지 않는다. 설정 오류는 하나 — 값이 '<' … '>' 로 감싸여 있다. 꺾쇠 안쪽(53자)은 영문 · 숫자 · -_ 와 기호 1개로, 공백 · 한글 · 안내 문구는 없다. 앞으로 형식(AIza · 39자)으로 거부하지 않고 꺾쇠 · 공백 · 따옴표만 본다. 호출 0."
**Context**: CONSTRUCTION - 단위 8P Build and Test, .env 꺾쇠 제거 대기

---

## Build and Test 단위 8P - 첫 실제 실행 완료
**Timestamp**: 2026-10-26T06:07:37Z
**User Input**: ".env 의 GEMINI_API_KEY 값에서 앞뒤 꺾쇠를 지웠다. 같은 조건으로 Seed A 3회차 실제 호출을 한 번 진행해 줘."
**AI Response**: "꺾쇠 · 따옴표 · 공백 없음 확인 뒤 fe94baf 로 한 번 실행(run_ref 20261026T060737Z-A3-2cb1). 7회 호출(분석 · 목차 · 장 3 · 편집 · 검증) 모두 STOP, 14,033ms, 토큰 입력 21,270 · 출력 2,941. generated · pipeline_complete=true · 검증 completed/pass · human_review=not_run. 사실 오류 없음, 그러나 본문이 원문 6문장 나열 수준 · 전환 없음 · 편집이 분리 1건뿐 · 검증이 구성 문제를 잡지 못함 — R1 문서(aidlc-docs/construction/unit8-memoir-pipeline/build-and-test/R1-20261026T060737Z-A3.md)에 Q-1~Q-8 로 정리. run 폴더에 키 없음. 재실행 · push 없음."
**Context**: CONSTRUCTION - 단위 8P Build and Test 1차 완료, 사람 검수 대기

---

## Build and Test 단위 8P - 1차 판정 · 개선 v2 (모의)
**Timestamp**: 2026-10-26T06:25:31Z
**User Input**: "Unit 8P 첫 실제 실행 결과를 확인했습니다. 5단계 파이프라인의 기술 실행은 성공했지만, 자서전의 콘텐츠 품질은 아직 승인하지 않습니다. 현재 결과를 기준선(Baseline)으로 보존하고 다음 개선 작업을 진행해주세요. … 사건 1개=장 1개 · 회차 내용 재기록 · 장 사이 연결 · 편집이 교정에 머묾 · 약하거나 모순된 주제 · 검증이 구성 문제를 못 잡음 … 프롬프트 중심, 필요할 때만 계약 · 코드 … A3 · A5 · B 구분 … B 제외가 입력에 적용되지 않았다면 제외 기능 검증 주장 금지 … 더 풍부한 합성 사례 검토 … 실제 Gemini 추가 호출 금지 · push · PR · 서버 연결 금지"
**AI Response**: "기준선(fe94baf · v1 · run 20261026T060737Z) 보존. 기준선 지표: 사건 3 → 장 3, 원문 그대로 7/7, editorial 0, edit_notes 1. 원인 분석 — 목차의 묶음 기준 부재, 장 집필의 재구성 지시 부재, 편집 v1 과 코드가 장 합치기를 금지, 주제 강도 기준 부재, 검증 code 가 사실뿐. 추가로 장 입력의 앞뒤 1턴 규칙이 seed B 의 제외 턴을 끌어오는 위험과 사건 누락이 그냥 지나가는 점을 찾음. 지시문 v2 다섯 개, 최소 계약 · 코드(분석 턴 덮기 · 제외 턴 차단 · 목차 사건 배치 · 편집 장 합치기 · 검증 fact/composition · text_metrics). 테스트 47(기존 36 유지 + 11) · 전체 116 · theme-interview 사본 47 · dry-run A3 · A5 · B. 전체 회귀 중 기존 서버의 question.warmup 이 .env 키로 'ping' 호출을 시도함을 감시로 잡음(차단, 호출 0) — 회귀는 GEMINI_API_KEY= 로 비워 돌린다. seed C 는 제안만(check_seed 가 A · B 만 받음). 실제 호출 · 커밋 · push 없음."
**Context**: CONSTRUCTION - 단위 8P 개선 v2 모의 완료, 실제 실행 승인 대기

---

## Code Generation 단위 8P - v2 보완 (제외 · 시험 격리 · 지표)
**Timestamp**: 2026-10-26T06:39:29Z
**User Input**: "Unit 8P v2 개선 방향을 확인했습니다. … 1. 제외 처리의 정확성 확인 — 턴 전체 단위인지, seed B 에서 꽃집과 빌린 돈 · 금액이 동일 턴인지, 일부 제외 시 턴 전체를 무조건 제거하지 않음, 턴 번호 · 출처 유지, 제외 내용 재사용 금지, 최종 삭제 기능은 만들지 말고 보장 범위 구분 2. 테스트의 외부 API 호출 차단 — GEMINI_API_KEY · GOOGLE_API_KEY 영향, 예열 격리, 실제 키가 있어도 비용 없게, 운영 서버 무수정 3. 지표는 비교용, 맞추려고 강제하지 않음, 품질 우선 6항목 4. 신규 · 전체 · theme-interview · A3/A5/B dry-run, 실제 호출 없음 5. 보고 … 수정이 끝나면 v2 A3 실제 실행을 한 번 진행."
**AI Response**: "seed B 턴 4 한 문장에 꽃집 준비와 빌린 돈 · 금액이 함께 있음, 메모(facts_found 턴 4 · confirmed_facts)에도 그 내용이 있음을 확인. exclusions 에 mode(whole · partial) — whole · 요청 턴은 턴째로 막고, partial 은 턴을 남긴 채 scope 알림 · 메모 제외. 목차 · 편집 원자료는 stage_source 로 거르고, 분석 · 검증은 전부. 지시문 v2 를 mode 에 맞추고 '필요할 때만' 으로 완화. tests/conftest.py — 키 이름을 빈 값으로 먼저 두어 load_dotenv 가 .env 를 덮지 못하게, genai 클라이언트 생성 · 외부 소켓 연결 차단, 막은 수 출력. R1 사람 검수 칸을 6항목으로. 테스트 56(신규 9 더함) · 전체 125 passed · 실제 .env 를 둔 채 막은 시도 0 · theme-interview 사본 56 · dry-run A3 · A5 · B 호출 0. 서버 · DB 무수정, 커밋 · push 없음."
**Context**: CONSTRUCTION - 단위 8P v2 보완 완료, A3 실제 실행 대기

---
