# Functional Design Plan — 단위 8P: 자서전 5단계 독립 실행 파이프라인

**상태**: 승인 2026-10-26 (사용자: "설계 방향 승인합니다. 다만 아래 내용을 반영한 뒤 구현 단계로") — 변경 반영 완료, Code Generation 진행
**초기 분석**: [initial-analysis.md](../unit8-memoir-pipeline/initial-analysis.md)
**근거 지시서**: `02_김대원_자서전고도화_추가업무지시서_작성파이프라인_v1.0.docx` §3 · §4 · §5.1 · §7 · §8 (MEM-DW-01~07, MEM-T01~08)

## 1. Intent
기존 단일 자서전 생성 구조(`memoir.write` 1회 호출)를 **5단계 독립 실행 파이프라인**으로 바꿔 실제로 돌려 보고 검증한다.

## 2. Scope
- 독립 실행기 `tools/memoir_pipeline.py` — 합성 seed 에서 DB 없이 실행
- 단계 로직 `app/session/memoir_pipeline.py`
- 역할 프롬프트 5개 `첨부프롬프트_md/파이프라인/`
- 테스트 `tests/test_memoir_pipeline.py` (가짜 호출)
- 실제 모델 1차 실행 (seed A 3회차)

## 3. Out of Scope
`/api/memoirs/preview` 교체 · 새 라우트 · prototype 연결 · 자서전 DB 영구 저장 · GraphRAG · LangChain · 서비스 배포 · 실패 후 나머지 장 진단 생성 · 자동 재시도 · 실제 사용자 DB 자료 · 수정/제외 기능 반영(8d) · 문체 3종(10)

## 4. Existing Assets
| 자산 | 쓰임 |
|---|---|
| `memoir.merge` | 입력 계약의 핵심. 전역 턴 · turn_map 은 여기서 한 번만 정한다 |
| `memoir.DEFAULT_TEXT_MODEL` · `MIN_SESSIONS` · `MAX_SESSIONS` | 공개 상수 — 기본 모델 이름과 회차 수 범위 |
| `postcard.material` | merge 안에서 |
| `question._client` | Gemini 클라이언트 |
| `seed_sessions.rows` · `check_seed` · `SCHEMA` | seed → 기록 모양, seed 검사 |
| seed A / B | 합성 자료. 이번 단위의 실제 호출은 이 둘에서 만든 입력만 쓴다 |
| `자서전_v2.md` §2 | 공통 사실 규칙 7항. 파이프라인 안의 작은 로더로 이 절만 읽는다 (`roledoc` 미사용) |
| `검증_v4.md` | `5_검증_v1.md` 의 바탕 — 사실 · 출처 · 누락 규칙과 출력 5키를 이어받는다. 그대로 호출하지 않는다 |

**밑줄 함수에 기대지 않는다** (사용자 지시): `roledoc._sections` · `memoir._ints` 를 쓰지 않고 필요한 로더 · 정수 검사를 파이프라인 안에 둔다. 역할 프롬프트는 각자 독립 파일이라 `roledoc` 이 필요 없다. `question._client` 는 기존 자산으로 지정된 것이라 그대로 쓴다.

## 5. New Components
`app/session/memoir_pipeline.py` · `tools/memoir_pipeline.py` · `첨부프롬프트_md/파이프라인/1_분석_v1.md` ~ `5_검증_v1.md` · `tests/test_memoir_pipeline.py` · `.gitignore` 한 줄 · `.env.example` 의 `MEMOIR_PIPE_*`

## 6. Pipeline
```
seed → merge (전역 턴 고정)
  → ① 분석 → 코드 참조검사 → ② 목차 → 코드 참조검사
  → ③ 장별 집필 (장 수만큼, 순서대로) → ④ 전체 편집 → 최종 근거검사 → ⑤ 검증
```
성공 시 모델 호출 = 장 수 + 4 (장 1~5 → 5~9회).

## 7. 장 실패 정책
장 k 실패 → 그 즉시 이후 호출 중지 · 성공한 장은 진단용 파일로 보존 · `generation_state=partial` · `pipeline_complete=false` · 편집 · 검증 미호출 · 재시도 0.

## 8. 결정 사항 (Q1~Q6 답, 2026-10-26)
| | 결정 |
|---|---|
| Q1 장 수 | 1~5장 (독립 실험의 안전 상한, 서비스 정책 아님). 0장 → 분석이 자료 부족이면 `insufficient_material`, 아니면 `format` 실패. 6장 이상 → 자르지 않고 `chapter_limit` 실패. 한 회차 = 한 장으로 고정하지 않는다 |
| Q2 시간 · 토큰 | 분석 60초/5000 · 목차 60초/4000 · 장 90초/6000(장당) · 편집 120초/8000 · 검증 90초/5000 · 전체 600초 · 재시도 0. 첫 실측용 값. 단계별 소요시간과 token usage 를 기록하고, 잘림 · 시간 초과는 그 기록을 근거로 조정한다. 입력 · 출력을 몰래 잘라 맞추지 않는다 |
| Q3 입력 | 실제 호출 자료는 합성 seed A/B 만. `--input`(memoir_input.py 출력)은 받되, 모든 발언이 해당 seed 의 원문과 같을 때만 허용 |
| Q4 장 입력 | 장마다 전체 원문을 주지 않는다. 전체 목차 · 분석의 공통 인물 · 이 장의 `focus_turns` · 이 장 events 의 turns · 목차가 고른 `context_turns`(정정 · 대명사 대상 등) · 같은 회차 앞뒤 1턴만. 분석 · 목차 · 편집 · 검증은 전체 원자료 |
| Q5 결과 | `backend-agent/eval/runs/<run_ref>/`, git 제외. 실행마다 비밀값 · 본문 · 원문을 뺀 `r1_summary.md` 를 함께 만들어 팀 공유용 R1 요약의 틀로 쓴다 |
| Q6 순서 | A 3회차 → 고칠 것 수정 → B → 필요하면 A 5회차. 여러 자료를 처음부터 반복 호출하지 않는다 |

## 9. 결과 상태 (사용자 지시 — `is_final` 대신)
`generation_state` · `pipeline_complete` · `verification.state` · `verification.verdict` · `human_review` 로 나눈다. 모델 검증 pass 는 사람의 품질 검수가 아니다.
- 5단계 정상 + 검증 pass → `generated` · `true` · `completed` · `pass` · `not_run`. 이 상태를 "최종 품질 승인"이라 부르지 않는다.
- `pipeline_complete` = 다섯 단계가 모두 호출 · 검사를 통과하고 검증이 `completed` 로 끝났다는 **실행** 사실. 판정(`verdict`)과 따로 읽는다.
- `human_review` 는 코드가 늘 `not_run` 으로 둔다. 사람이 R1 요약에 적는다.
- `is_final` 은 두지 않는다.

## 10. Completion Criteria
- [ ] 다섯 역할이 실제 별도 모델 호출로 실행된다
- [ ] 같은 모델을 써도 된다
- [ ] 장별 집필은 장 수만큼 실제로 호출된다
- [ ] 단계별 JSON 산출물이 run 폴더에 있다
- [ ] 모든 source turn 이 최초 merge 의 전역 턴을 유지한다
- [ ] 한 장이라도 실패하면 완성본 생성을 멈춘다
- [ ] 최종 검증이 실제 모델 호출로 실행된다
- [ ] DB 와 기존 서비스 API 를 고치지 않고 seed 로 재현된다
- [ ] 실제 모델 실행 결과와 소요시간(가능하면 token usage)이 남는다
- [ ] 기존 테스트 전체가 그대로 통과한다

## 11. 구현 원칙
- 기존 `memoir.py` · `main.py` · 서비스 프롬프트는 고치지 않는다.
- 원문은 시스템 지시에 넣지 않고 사용자 메시지(자료)로만 넘긴다.
- 분석 · 목차 · 편집 결과는 인생 사실의 근거가 아니다.
- 말하지 않은 사건 · 심리 · 동기 · 후회 · 화해 · 대사 · 감각 · 정확한 시점 · 인과를 넣지 않는다.
- 편집적 제목 · 중립 전환은 새 사실이 없을 때만 `editorial`.
- 전역 턴을 다시 매기지 않는다.
- `MEMOIR_PIPE_*` 와 `MEMOIR_*` 분리.
- 결과 · 원응답에 비밀키를 남기지 않는다.

## 12. 실행 계획과의 관계 — Workflow Change
처음 설계한 곳(`C:\work\memoir` 의 실행 계획)에서는 8a · 8b · 8c 를 8P 로 묶고, 8c 의 `main.py` · prototype 연결을 새 단위 8S 로 떼었다. 8c 의 재시도 1회 → 0회, FR-MEM-8 의 `검증_v4.md` 재사용 → 새 판 `5_검증_v1.md`.
이 저장소(`C:\work\memoir-team`)에는 그 실행 계획이 없다. 여기서는 **8P(지금) → 8S(나중)** 두 단위만 다룬다.

## 13. 작업 폴더 이전 (2026-10-26)
- 이 설계는 `C:\work\memoir`(개인 저장소 memoir-aidlc, `feature/aidlc-solo`)에서 승인됐다. 그 폴더의 다른 세션이 단위 4 를 커밋하고 이 문서들을 `archive/unit8-premature/` 로 옮겼다. 사용자가 작업 폴더를 `C:\work\memoir-team`(팀 저장소 클론, `feature/memoir-pipeline`, 바탕 develop `f72d6df`)으로 옮기고 승인된 8P 결과물을 재사용하라고 지시했다.
- 문서 · 코드 · 지시문 · 테스트를 원본에서 같은 상대 경로로 복사했다. 코드 · 지시문 · 테스트의 SHA-256 은 원본과 같다. `.gitignore` · `.env.example` 은 필요한 줄만 더했다.
- **이 저장소에는 단위 4(화자 · 테마) · 단위 8a 가 없다.** 원본 폴더에서 했던 단위 4 의 stash · 커밋, 다른 세션의 8a 기록은 이 저장소의 상태가 아니므로 옮기지 않았다. 8P 는 단위 4 의 코드 · 마이그레이션에 기대지 않는다(DB 미사용, seed 만).
- 기록(`aidlc-state.md` · `audit.md`)은 이 저장소에서 새로 시작했다. 원본에서의 승인 이력은 audit 의 「이전 작업 폴더에서 승인된 것」에 요지로 남겼다.

## 14. Functional Design 단계
- [x] 초기 분석 — `initial-analysis.md`
- [x] JSON 계약 — `functional-design/domain-entities.md`
- [x] 규칙 — `functional-design/business-rules.md`
- [x] 흐름 · 함수 책임 — `functional-design/business-logic-model.md`
- [x] Q1~Q6 답 반영
- [x] 사용자 승인 (변경 반영 조건)
