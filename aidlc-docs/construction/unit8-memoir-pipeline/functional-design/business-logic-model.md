# Business Logic Model — 단위 8P

## 1. 흐름과 중단 위치

```
[S0] 입력      seed 읽기 → rows → record → merge → T, input_ref
               실패: input  ─────────────────────────────────► failed (호출 0)
[S1] 분석      call(analysis)
               실패: call · timeout · format ────────────────► failed
               status=insufficient_material ──────────────────► insufficient_material (정상 종료)
               status=needs_context ──────────────────────────► needs_context
[S2] 분석검사  A-1~A-2, R-1  실패: reference/format ──────────► failed
[S3] 목차      call(outline)  실패 · needs_context ────────────► failed / needs_context
[S4] 목차검사  O-1~O-2, R-1  실패: reference ─────────────────► failed
[S4'] 장 수   0장 → format 실패 · 6장 이상 → chapter_limit 실패 (자르지 않음)
[S5] 장 1..N   for ch in chapters (순서대로):
                 given_turns 계산 → 원문을 그 턴만 남겨 call(chapter, ch) → C-1~C-4
                 실패(어느 종류든) ──────────────────────────► partial (남은 장 · 편집 · 검증 미호출)
[S6] 편집      call(edit)  실패: call · timeout · format ─────► failed
[S7] 최종검사  E-1~E-3, R-1~R-2  실패: reference ─────────────► failed (검증 미호출)
[S8] 검증      call(verify) → V-1~V-2
               실패 ─────────────────► generated · verification=failed · pipeline_complete=false
               성공 ─────────────────► generated · verification=completed · pipeline_complete=true
                                        (verdict 는 따로 기록, human_review=not_run)
```

호출 전마다 S-5(전체 시간) · P-4(호출 수)를 본다. 넘으면 `budget` 실패.

## 2. 함수 책임 — `app/session/memoir_pipeline.py`

| 함수 | 책임 | 모델 |
|---|---|---|
| `settings()` | `MEMOIR_PIPE_*` 를 읽어 단계별 모델 · 온도 · 시간 · 토큰 · 장 상한 · 전체 상한을 돌려준다. 키는 없다 | — |
| `prompt(stage)` | 파이프라인 안의 작은 로더로 `자서전_v2.md` 의 `## 2.` 절만 읽고, 그 뒤에 `파이프라인/<n>_<역할>_v1.md` 를 잇는다. 파일 없음 · 빈 절이면 실패 (`roledoc` 미사용) | — |
| `build_input(records)` | `memoir.merge` 를 부르고 `T` 와 `input_ref` 를 붙인다. 번호는 손대지 않는다 | — |
| `check_input(data, turn_map)` | `--input` 으로 받은 merge 출력의 모양 · 턴 1..N 연속 · turn_map 일치 | — |
| `chapter_source(data, analysis, chapter)` | Q4: focus · 사건 · context 턴과 같은 회차 앞뒤 1턴만 남긴 원자료와 `given_turns` | — |
| `call_model(spec)` | `question._client()` 로 한 번 부른다. 원응답 글자 · finish reason · token usage 를 돌려준다. 시간 제한은 `run` 이 건다 | 1회 |
| `analyze(data, call)` | ① 자료 메시지를 만들어 부르고 `check_analysis` | 1회 |
| `check_analysis(out, T)` | A-1~A-3 · R-1 | — |
| `outline(data, analysis, call)` | ② 분석 결과 + 같은 원자료로 부르고 `check_outline` | 1회 |
| `check_outline(out, analysis, T, max_ch)` | O-1~O-3 · R-1 | — |
| `write_chapter(data, outline_out, chapter, people, call)` | ③ 전체 목차 · 공통 인물 · 이 장의 `focus_turns` 표시 · 원자료로 부르고 `check_chapter` | 장마다 1회 |
| `check_chapter(out, chapter, T)` | C-1~C-4 · R-1~R-2 | — |
| `edit(data, outline_out, chapters, call)` | ④ 목차 · 모든 장 · 같은 원자료로 부른다 | 1회 |
| `check_final(out, outline_out, T)` | E-1~E-3 · R-1~R-2 (최종 근거검사) | — |
| `verify(data, edited, call)` | ⑤ 편집본 · 원자료 · `review_scope` 로 부르고 `check_verify` | 1회 |
| `check_verify(out, T)` | V-1~V-2 | — |
| `run(records, *, call=call_model, recorder)` | S0~S8 순서 실행. 첫 실패에서 멈추고 상태 · 실패를 정한다. 단계마다 `recorder` 로 파일을 남긴다. 재시도 없음 | 장 수 + 4 |

- `call` 을 인자로 받는 이유: 테스트가 가짜 호출을 끼운다 (`memoir.write` 를 갈아 끼우는 기존 방식과 같은 뜻).
- 오류 종류: `PipelineError(stage, kind, message, chapter_key)` 하나로, `kind` 가 S-4 의 값.
- `memoir.py` 에서는 `merge` 와 공개 상수만 쓴다. `write` · `check` · `preview` · `_ints` 는 쓰지 않는다.

## 3. 실행기 — `tools/memoir_pipeline.py`
1. 인자: `--seed` + `--aliases` (3~5개, 쉼표) **또는** `--input` (memoir_input.py 출력) · `--out-dir` (기본 `eval/runs`) · `--dry-run` (입력만 만들고 호출하지 않음)
2. `.env` 를 읽는다 (`GEMINI_API_KEY` · `MEMOIR_PIPE_*`). `.env.supabase` 는 읽지 않는다. 키 값은 출력하지 않는다.
3. 입력 확인(K-1) → seed 는 고른 alias 를 `seed_sessions.rows` 로 기록 모양으로 (`session_id` = alias, `created_at` = recorded_order 로 만든 시각 — `test_memoir.record` 와 같은 방식) → `memoir.merge`
4. `run_ref` = `UTC시각-<set_id><회차수>-<input_ref 앞 4자>` 로 폴더를 만들고 `memoir_pipeline.run` 실행
5. 끝나면 요약: 상태 · 장 수 · 호출 수 · 단계별 ms · 검증 판정 · 폴더 경로. 종료 코드 `0` = generated · insufficient_material, `1` = 그 밖, `2` = 입력 거부

## 4. 단계별 자료 메시지 (사용자 메시지 내용)
모두 `[자료]` 머리말 + 이 단계가 받는 JSON. 머리말에는 모양 설명만 쓰고 규칙은 지시문에만 둔다 (지금 `memoir._input` 과 같은 원칙).

| 단계 | 싣는 것 |
|---|---|
| ① | merge 출력 |
| ② | `analysis` + merge 출력 |
| ③ | `outline`(전체) · `people` · `chapter`(이번 장) · `given_turns` · **이 장 원문만 남긴** merge 출력 (Q4) |
| ④ | `outline` · `chapters`(모든 장 초안) · merge 출력 |
| ⑤ | `candidate`(편집본) · `review_scope` · merge 출력 |

## 5. 역할 지시문 5개 — `첨부프롬프트_md/파이프라인/`
| 파일 | 바탕 | 새로 쓰는 것 |
|---|---|---|
| `1_분석_v1.md` | 지시서 §5.1 ① | 사건 묶기 · 주제 후보 지지/반대 · 불명확 항목 · 출력 계약 |
| `2_목차_v1.md` | §5.1 ② | 장 목적 · 배치 · 전환 · 반복 사건 처리 · 출력 계약 |
| `3_장집필_v1.md` | §5.1 ③ · §4 | 문장 항목 · supported/editorial · review_notes · 문체 F-4 |
| `4_편집_v1.md` | §5.1 ④ | 통합 본문 · edit_notes · 위치 다시 계산 |
| `5_검증_v1.md` | `검증_v4.md` 의 사실 · 출처 · 누락 · 정정/제외 규칙과 판정 · 출력 5키 | chapter / paragraph / sentence 위치, supported / editorial, 책 · 장 제목, 중립 전환, 전체 사용 범위 누락, 편집 뒤 turns 연결, `editorial_misuse`. 회차별 분량 · 줄 단위 · 엽서 · 연대기 기준은 뺀다 |

각 파일은 시스템 지시 본문만 담는다. 공통 §2 는 로더가 앞에 붙인다(파일에 다시 쓰지 않음).

## 6. 테스트 시나리오 (지시서 MEM-T 대응)
| 시나리오 | 대응 |
|---|---|
| 정상 · 장 N개 · 호출 N+4 | MEM-T06 |
| 분석 · 목차 · 장 · 편집 · 검증 각각의 없는 턴 | MEM-T07 |
| 잘린 JSON · 시간 초과 · 호출 오류 | MEM-T07 |
| 장 하나 실패 → partial · 이후 미호출 | MEM-T07 · FR-MEM-5 |
| 편집에서 장 누락 | MEM-T06 |
| 자료 부족 정상 종료 | MEM-T07 |
| 검증 revise → 완성본 아님 · 재작성 없음 | MEM-T05 · T07 |
| 실제 모델 A 3회차 | MEM-T01~T06 (사람이 읽고 판정) |
| 실제 모델 B 3회차 | MEM-T04 · T08 |
