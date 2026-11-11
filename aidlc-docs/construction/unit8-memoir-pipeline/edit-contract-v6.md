# 단위 8P — 편집 계약 v6 (문단 산문 + 근거 표현) 준비

- 날짜: 2026-10-27
- 바탕 분석: `edit-contract-review-v5.md`. 조건부 승인 범위는 **전체 편집 단계만**입니다.
- 실제 Gemini 호출은 하지 않았습니다.
- 그대로 둔 것:
  - 분석 스냅샷, 목차 r2, Pro 장 초안(`tests/data/v5_chapter_pro_20261027T023603Z`)
  - 다섯 단계 역할, 장 집필 계약 · 검증 계약(v5)
  - v1~v5 지시문과 실행 기록
  - 기본 모델 Flash-Lite, `PROMPT_VERSION = "v5"`, `ROLE_FILES["edit"] = 4_편집_v5.md`
- v6은 `--from-draft`(편집 단독 시험)에 `--edit-contract v6`을 줄 때만 쓰입니다. v5 실행은 지시문, 자료, 검사가 모두 전과 같습니다(테스트로 고정).

## 1. 바뀐 파일

| 파일 | 내용 |
|---|---|
| `backend-agent/첨부프롬프트_md/파이프라인/4_편집_v6.md` | 새 편집 지시문 |
| `backend-agent/app/session/memoir_pipeline.py` | v6 계약 검사 · 변환, 새 검사, 편집 자료, 실행 연결, R1 줄 |
| `backend-agent/tools/memoir_pipeline.py` | `--edit-contract {v5,v6}`, v6 dry-run 추정 |
| `backend-agent/tools/memoir_blind.py` | 편집 비교 평가 항목(`--criteria edit`), v6 산문 그대로 출력, 사실대조표에 표현(span) 표시 |
| `backend-agent/tests/test_memoir_pipeline.py` | v6 회귀 테스트 40개 |
| `backend-agent/tests/data/v5_edit_pro_20261027T024949Z/` | 기준선 Pro 편집 결과 사본(이전 턴에 만듦) |

## 2. 새 계약

### 편집 출력

```json
{"diagnosis": [{"issue": "", "where": ["ch-1/p1"], "change": "rewrite|move|merge|split|cut|compress|link|fact_fix",
                "action": "", "result": ["ch-1/p1"]}],
 "title": {"text": "", "kind": "editorial", "facts": []},
 "chapters": [{"chapter_key": "ch-1", "center": "", "title": {...},
   "composition": [{"paragraph": 0, "role": "", "from": ["ch-1/p0"], "after_previous": "",
                    "reorder": null | {"facts": ["f42"], "reason": ""}}],
   "paragraphs": [{"text": "문단 산문 전체",
                   "claims": [{"span": "본문 그대로의 표현", "kind": "claim", "facts": ["f16"]},
                              {"span": "새 사실 없는 잇는 말", "kind": "link", "facts": []}]}]}],
 "omitted": [...], "checks_resolution": [...], "notes": [...]}
```

### 편집 입력 (`edit_message_v6`)
- 초안: 문단 위치, 문단 산문, 그 문단의 사실 id만 줍니다. 문장 객체는 주지 않습니다.
- 목차: 장의 중심 · 핵심 경험과 문단의 역할 · 시기 · core만 줍니다. 문단별 facts 배열은 뺍니다.
- `core_facts`(18개)와 `must_keep`(core를 뺀 나머지)을 나눠 줍니다.
- checks: block · fix만 주고, 초안 문장 위치에는 그 문장을 `quote`로 붙입니다. 검토 지적에도 같은 `quote`를 붙입니다.

### 코드 처리 (`check_final_v6`)
1. 모양이 틀리면 멈춥니다(PipelineError). 해당하는 경우:
   - `change`가 목록 밖
   - link인데 facts가 있음, 또는 claim인데 facts가 없음
   - 원장에 없는 id
   - 옛 문장 목록 모양
   - composition 없음
2. 문단을 코드가 문장으로 나누고(`split_sentences`, 따옴표 안 마침표에서는 끊지 않음), span을 claims 순서대로 본문 앞에서부터 찾습니다.
3. 문장의 facts는 그 문장 안 claim들의 사실을 합친 것입니다. 이렇게 v5와 같은 문장 목록으로 바꿉니다(`04_edited_sentences.json`).
   - 그래서 기존 검사를 그대로 씁니다: fact_token, 들은 말 · 흐림 · 생각, 핵심 사실, 정정, edit_trace, 검증 위치(`ch-1/pN/sM`).
   - **검사 단위는 문단이 아니라 문장 이하입니다.** span이 문장 경계를 넘으면 block이라, 넓은 span으로 여러 문장의 근거를 섞을 수 없습니다.
- 보조 사실은 이유 없이 빼도 됩니다(지시문 9, `dropped_facts`는 기록만). core는 빠지면 core_missing(fix), must_keep은 이유 없이 빠지면 fix입니다.

## 3. 판정 구분 — 명확한 오류와 사람 판단

| 등급 | 규칙 | 뜻 |
|---|---|---|
| block | span_missing · span_misplaced · span_crosses_sentence · memo_leak(편집 구성 메모 포함) · 기존 block | 계약 위반 · 사실 위치를 확인할 수 없음 |
| fix (code_gate attention) | negation_lost · causal_unsupported · link_content · uncovered_text · time_reversal_undeclared · edit_claim_mismatch(진단 항목별) · composition_missing · 기존 fix | 명확한 사실 · 계약 오류 |
| review (code_gate에 넣지 않음) | spoken_carryover · meta_suspect · repeat_phrase · causal_suspect · claim_weak · time_reversal_declared · composition_mismatch | 문학적 판단이거나 오탐이 있는 표면 검사 — 사람이 확인 |

- 오탐이 알려진 것:
  - `causal_suspect`: "~아서/~어서"가 시간 순서일 수도 있습니다(예: "부산에 처음 가서").
  - `negation_lost`: 부정어 없이 같은 뜻으로 바꿔 쓴 경우도 걸립니다.
  - `claim_weak`: 글자 겹침만 봅니다. 기준선 문장의 최저 겹침은 0.19라서, 문턱을 0.15로 잡았습니다.
- **출처 id가 붙었다고 뜻이 맞다고 보지 않습니다.** 뜻의 대조는 검증 단계와 사람(사실대조표)의 몫입니다.
- 진단과 결과 대조(`claim_findings`): change마다 edit_trace로 봅니다.
  - rewrite: 결과 문장의 절반 이상이 새 문장이거나, 초안과 0.7 미만으로 닮음
  - merge: 초안 두 문단 이상에서 옴
  - cut: 초안 문장이나 사실이 빠짐
  - 나머지 change도 같은 방식으로 봅니다.
  - 바꾼 양이 적어도 사실대로 적었으면 걸리지 않고, 많이 바꿨다고 통과시키지도 않습니다.

## 4. 기준선 회귀 결과 (모델 호출 없음)

### 4-1. 02:49Z Pro 편집본
- 본문을 한 글자도 바꾸지 않고 v6 모양으로 옮겨 실행했습니다(문장마다 span 하나, 진단 5개를 change · result로 옮김).
- v5에서는 code_gate가 **pass**(info 4)였는데, v6에서는 **attention → needs_revision**(fix 3 · review 10 · info 4)입니다.

| 등급 | 규칙 | 위치 | 내용 |
|---|---|---|---|
| fix | negation_lost | ch-1/p1/s0 | f16, 턴 10 "저는 기억은 안 나요"가 사라짐 |
| fix | time_reversal_undeclared | ch-1/p4 | 1985~2010년 가게 이야기 뒤 1977년으로 돌아감, 이유 없음 |
| fix | edit_claim_mismatch | 진단 0 | "문단을 다시 구성" — 27문장 중 4개만 초안과 달라짐 |
| review | spoken_carryover | p0/s2 · p3/s2 · p5/s0 · p5/s3 | 말이다 · 그거 · ~겠어서 · 걔 |
| review | meta_suspect | p0/s3 | "기억을 따라가다 보면 … 거슬러 올라가게 된다" |
| review | causal_suspect | p4/s0 | "가서" — 시간 순서라 오탐 |
| review | composition_mismatch ×4 | p0 · p3 · p4 · p5 | 옮겨 쓸 때 from을 같은 번호로 넣은 탓 — 기준선 자체의 문제는 아닙니다 |

### 4-2. Pro 초안 (v6 검사만)
- causal_suspect p1/s2("손이 빨라서")
- repeat_phrase p6/s1("2010년" 반복)
- spoken_carryover p6/s4("걔")
- negation_lost 없음 — 초안은 "기억하지는 못하지만"을 지켰습니다.

### 4-3. 같은 원고를 문제만 적게 고친 경우
- 고친 것:
  - 부정 표현 되살림
  - 1977년 재배치 이유 적기
  - 진단을 fact_fix 하나로 사실대로 적기
- 결과: **code_gate pass** — 변경량이 적어도 실패시키지 않습니다. 구어 · 안내문은 review로 남아 사람이 봅니다.

### 4-4. 요구 사항별 고정 테스트

| 요구 사항 | 테스트 |
|---|---|
| 부정 표현 누락 | `test_v6_checks_catch_what_the_pro_edit_got_past` · `test_negation_kept_when_rephrased_with_a_negative` |
| 구어체 | 같은 테스트(4곳) |
| 근거 없는 인과 | `test_causal_findings`("때문에" → fix, "빨라서" → review, "아파서"는 원문에 있어 통과, "~면서"는 통과) |
| 시간 역행 | undeclared → fix, declared → review(`test_declared_reorder_…`) |
| 메타 안내문 | 위 기준선 테스트 · `test_composition_memo_copied_into_a_link_is_blocked` |
| 반복 | 초안 "2010년에" (`test_v6_checks_on_the_pro_draft_…`) |
| 설명과 결과 불일치 | `test_claimed_rewrite_…` · `test_each_change_is_checked_against_the_trace`(8가지 change) |

## 5. 테스트 · dry-run
- 테스트: 8P 182 → **222개**, 전체 251 → **291개**, 모두 통과. conftest가 외부 호출을 막고, 재시도는 0회입니다.
- dry-run 명령:

```bash
python tools/memoir_pipeline.py --seed eval/memoir_seed_C.json --aliases c1,c2,c3,c4,c5 --from-analysis eval/analysis_fixture_C_v5_reviewed.json --from-outline eval/outline_fixture_C_v5_reviewed_r2.json --from-draft tests/data/v5_chapter_pro_20261027T023603Z --review-notes eval/review_notes_C_v5_pro_draft.json --model gemini-3.1-pro-preview --edit-contract v6 --dry-run
```

- 결과:
  - 예상 호출 1회(편집만) · 편집 계약 v6
  - 입력 약 18,242 토큰(지시문 5,253자 + 자료 30,866자). v5 편집의 실제 입력은 20,358이었습니다.
  - 초안 판정에서 편집에 넘길 block · fix는 없습니다. 검토 지적은 9개(quote 포함)입니다.
  - 출력 상한 32,768, 300초
  - 예상 비용: 출력 3,000이면 $0.072, 12,000이면 $0.180, 상한까지 다 쓰면 $0.430
  - v5 편집은 출력과 생각을 합쳐 16,566을 썼습니다. v6은 span이 본문을 한 번 더 적는 만큼 출력이 늘어 **약 $0.25~0.32로 예상**합니다.
- 실제 실행 때는 기준선과 같게 `MEMOIR_PIPE_TEMPERATURE=1.0`을 주어야 합니다. dry-run 표시는 기본값 0.3이었습니다.

## 6. 비교 준비
- v6 실행 뒤 아래 명령으로 블라인드 비교 자료를 만듭니다.

```bash
python tools/memoir_blind.py --seed eval/memoir_seed_C.json --aliases c1,c2,c3,c4,c5 --criteria edit --result tests/data/v5_edit_pro_20261027T024949Z/result.json --result eval/runs/<v6 실행>/result.json
```

- 평가자용(버전 표시 없음), 여섯 항목:
  1. 하나의 이야기
  2. 도입과 마무리
  3. 문단 전환
  4. 나열감
  5. 문체 · 호흡
  6. 책 수록
- 검수자용:
  - 사실대조표: 문장, 표현(span) · 사실, 근거 턴 원문. 사실 · 전언 · 감정 · 불확실성 보존은 여기서 따로 판정합니다.
  - 비교조건: 같은 초안, 계약 v5/v6, 검토 지적 9개, 모델
- 수치(edit_trace, 나열 신호)는 검수자 참고일 뿐 성공 판정이 아닙니다.

## 7. 남은 것
- v6 Pro 편집 1회 실행 여부는 태헌님이 결정합니다. 같은 Pro 초안, 같은 검토 지적, 온도 1.0, 재시도 0으로 돌립니다.
- 커밋은 하지 않았습니다. push · PR · 충님 서버 연결도 하지 않았습니다.
