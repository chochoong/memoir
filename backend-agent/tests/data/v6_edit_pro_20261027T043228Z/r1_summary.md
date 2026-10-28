# R1 — 자서전 파이프라인 실행 20261027T043228Z-C5-b9f8-focus-fixture-outline-edit6-31propreview

## 실행 식별
- input_ref: `b9f8e2daea65` · seed: `memoir_seed_C.json` · alias: c1, c2, c3, c4, c5 · focus: 있음(한 장)
- 시각: 2026-10-27T04:32:28+00:00 ~ 2026-10-27T04:34:25+00:00

## 설정
- 모델 `gemini-3.1-pro-preview` · 온도 1.0 · 전체 상한 600.0초 · 재시도 0 · 장 [1, 5] · **편집 단독 시험(edit_only) — 초안 20261027T023603Z-C5-b9f8-focus-fixture-outline-chapter-31propreview (gemini-3.1-pro-preview)을 편집만, 검증을 부르지 않았다** · **편집 계약 v6 — 문단 산문 + 근거 표현(claims), 지시문 4_편집_v6.md**
- 단계 상한: analysis 90.0초/8000 · outline 60.0초/6000 · chapter 90.0초/6000 · edit 300.0초/32768 · verify 90.0초/6000
- 지시문 판: v5 · 분석 출처: **reviewed_fixture** · 목차 출처: **reviewed_fixture** — 사람이 검토한 시험용 목차(자동 목차 생성 결과 아님) — 시험용 스냅샷(모델 원본 아님), 분석 단계를 부르지 않았다

## 상태
- generation_state: **edit_only** · pipeline_complete: **false** · 호출 1회
- 사실 대조: not_run · verdict: None
- 구성 채점(코드 보정 뒤): None · 기준 충족 None · 보정 0건
- code_gate: **attention** · model_verdict: None · human_review: not_run → **overall: needs_revision**
- approved 는 사람 검수로만 된다 — 모델 pass · 구성 채점 · 코드 pass 는 출판 품질 승인이 아니다

## 단계

| 단계 | 장 | 성공 | ms | 입력 글자 | 출력 글자 | 토큰(입력/출력/생각) | finish | 경고 |
|---|---|---|---|---|---|---|---|---|
| edit |  | O | 116350 | 30866 | 9599 | 18262/3572/16510 | FinishReason.STOP | 0 |

## 비교 지표 (판정 아님)

- 사실 66 · 기억 단위 11 · 목차 장 1 · 목차가 뺀 사실 36 → 편집본 장 1
- 문장 24 · editorial 0 · 여러 턴을 묶은 문장 4 · 원문 그대로 0.0
- 계획 사실 사용(draft): 전체 30/30 · 핵심 18/18 · 보조 12/12 · 빠진 핵심 []
- 계획 사실 사용(final): 전체 25/30 · 핵심 18/18 · 보조 7/12 · 빠진 핵심 []
- ch-1 나열 신호: 1:1 0.33 · 턴 순서 유지 0.83 · 잇는 문장 3 · 여러 회차 문단 3/7 · listing=False

## 편집 추적 (코드가 잰 것)

- 장 1 → 1 · 합친 장 [] · 나눈 장 [] · 문단 합침 0 · 나눔 0
- 문장 24 → 24 · 그대로 7 · 다듬음 13 · 다시 씀 3 · 새 문장 1 · 덜어 냄 3 · 옮김 0 · 구조 변화 False

## 코드 판정 (편집본) — {'must_keep_omitted(info)': 4, 'spoken_carryover(review)': 3, 'time_reversal_undeclared(fix)': 1, 'edit_claim_mismatch(fix)': 1}

- review 는 사람 확인 항목(문학적 판단 · 오탐 가능한 표면 검사)이다 — code_gate 에 넣지 않는다

| 위치 | 규칙 | severity |
|---|---|---|
| artifact | must_keep_omitted | info |
| artifact | must_keep_omitted | info |
| artifact | must_keep_omitted | info |
| artifact | must_keep_omitted | info |
| ch-1/p3/s2 | spoken_carryover | review |
| ch-1/p6/s1 | spoken_carryover | review |
| ch-1/p6/s4 | spoken_carryover | review |
| ch-1/p5 | time_reversal_undeclared | fix |
| artifact | edit_claim_mismatch | fix |

## 사람 검수 (직접 적는다 — 위 지표보다 먼저 본다)

- human_review: not_run / passed / failed
- Q7 사실 충실 (필수 — 문장마다 원문 대조, 들은 말 · 불확실성 포함):
- Q8 블라인드 독자 시험 (평가자 · 선호 · 질문/답 흔적 위치):
- Q1~Q6 사람 채점:
- 문제 위치와 이유:
- 검수자 · 시각:
