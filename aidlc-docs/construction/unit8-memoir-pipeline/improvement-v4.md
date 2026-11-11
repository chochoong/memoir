# 단위 8P v4 — 1인칭 회고 수필체 · 사건과 끈 · 장 입력 · 코드 판정

**작성**: 2026-10-26 · 근거: `redesign-v4-analysis.md`(원인 · 최소 변경안 1~8), 사용자 승인("v4 개선 작업을 승인 … 기본 문체는 담백한 1인칭 회고 수필체")
**범위**: 같은 5단계 · 같은 호출 수(장 수 + 4). 여섯 번째 호출 · 감독 에이전트 · GraphRAG 없음. 서버 API · DB · 배포 무수정. 실제 모델 호출 없음.
**보존**: v1(`fe94baf`) · v2(`9231a70`) · v3(`5ae6c1c` · `d3deb2b`) 커밋과 `*_v1~v3.md` 지시문, 실행 폴더 4개. v3 의 해요체 전제는 v4 에 가져오지 않았다.

## 1. 수필체 계약 (자서전 본문 — 인터뷰 · 엽서 문체는 그대로)
| 항목 | 규칙 | 어디서 |
|---|---|---|
| 서술 | 화자 본인의 담백한 1인칭 회고 수필. 화자는 **"나"** | 장 집필 · 편집 지시문 |
| 종결 | **"~다" · "~했다" · "~었다"**. 해요체 · 합니다체 서술 금지 | 지시문 + 코드 `style_mix`(fix) |
| 인용 | 직접 인용은 원문 말투 그대로 따옴표 안에 — 문체 검사에서 뺀다 | 지시문 + 코드(`_QUOTE`) |
| 재구성 | 원문 한 턴을 한 문장으로 옮기지 않는다. 같은 일을 다룬 여러 턴(다른 회차 포함)을 한 문단으로. 한 문장이 여러 턴을 근거로 가질 수 있다(계약은 v1 부터 `turns: [..]` 목록 — 제한 없음) | 지시문 · 장 입력의 사건 묶음 |
| 보존 | 사실 · 인물 · 시간 · 장소 · 부정 · 불확실성 · 직접 말한 감정과 세기. 들은 이야기는 "…했다고 들었다" | 지시문 · 검증(fact) |
| 금지 | 새 사건 · 대사 · 감정 · 심리 · 동기 · 인과 · 교훈 · 감각 · 장면 · 정확한 시점. 감탄 · 과장된 수사 | 지시문 · 검증(fact) |
| 인터뷰 중단 표현 | "오늘은 그만할게요" · "나중에 할게요" 등은 본문에 쓰지 않는다. 같은 발언의 사실은 쓴다. 멈춘 이유 · 마음을 짐작하지 않는다 | 지시문 + 코드 `stop_phrase`(**block**) |
| 답 흔적 | "아니요" · "가끔요" 등은 뜻만 살려 서술로. 답이 질문에 **내용으로** 답한 경우에만 질문 내용을 이어 쓴다("네"만 한 답은 사실 아님) | 지시문 + 코드 `answer_trace`(fix) |

지시문 예시는 Seed C 원문과 겹치지 않게 일반 문장으로 썼다(시험 정답 유출 방지 — 테스트로 8자 조각 일치 0 확인).

## 2. 계약 · 코드 변경 (최소 변경안 1~8)
| # | 변경 | 계약 / 코드 |
|---|---|---|
| 1 | 다른 장의 턴을 앞뒤 1턴으로 끌어오지 않는다 | `chapter_source(…, outline_out)` — 다른 장의 focus · 사건 턴은 이웃에서 뺀다. 일부러 쓰려면 목차의 `context_turns` |
| 2 | 장 입력을 사건 묶음 순서로 | `source.utterances` 를 목차의 사건 순서로 재배열(번호 · 글 무변경) + `event_packets` · `threads` |
| 3 | 사건 식별과 주제별 묶음 분리 | 분석 `threads: [{thread_key, name, kind: person/object/place/theme, events, turns}]`. 사건 time 에 연도 둘 이상이면 경고 |
| 4 | 중심 소재를 목차 · 장 목적에 | 목차 `book.theme_use · opening_turns · closing_turns(필수)`, 장 `role(필수) · threads`. 뚜렷한 주제인데 theme_use 없음 · 끈을 어느 장도 안 씀 · 끈 없이 사건 4개 이상 모은 장 → 경고 |
| 5 | 코드 경고를 편집에 | 장 초안 뒤 `code_findings` → `03_checks.json` → 편집 입력 `checks`(id · rule · severity · location · detail) |
| 6 | 편집 결과에 처리 상태 | 편집 출력 `checks_resolution: [{check_id, status: resolved/kept, reason}]`(kept 는 이유 필수). 빠진 항목은 경고 — 최종 본문을 코드가 다시 본다 |
| 7 | 판정 분리 | 결과 `code_gate` · `model_verdict` · `human_review` · `overall` (3절) · `04_code_gate.json` · R1 요약 |
| 8 | 지시문 v4 | 5개 새로 씀 — 수필체 · 사건 단위 · 끈 · 장 역할 · 처음/끝 · checks 처리 · 검증은 뜻에 집중 |

## 3. 자동 차단 정책
| 규칙 | 판정 | 비고 |
|---|---|---|
| 출처 · 참조 오류(없는 턴 · 범위 밖 · 장 키 · 위치) | **실패로 멈춤** (final_check) | 기존 그대로 |
| 제외 턴 재사용(whole · 요청 턴) | **실패로 멈춤** | 기존 그대로. partial 의 문장 안 재등장은 검증 · 사람 |
| 목차 메모 혼입 (`memo_leak`) | **block** | v3 의 파이프라인 실패 → v4 는 code_gate 로 (검증은 계속 돈다) |
| 인터뷰 중단 표현 (`stop_phrase`) | **block** | |
| 문체 혼합 (`style_mix`, 인용 제외) | fix — 편집 대상 | 남으면 attention. kept 로 넘어가지 않는다 |
| 답 흔적 (`answer_trace`) · 안내문 (`meta_text`) | fix | |
| 같은 턴을 여러 장이 근거 (`repeat_turn`) | fix — **이것만으로 막지 않는다** | 편집이 kept + 이유(의도한 회상)면 남은 것으로 치지 않는다 |
| 원문 나열 (`verbatim_run`) · 주제 완성도 · 문학적 자연스러움 | info / 사람 검수 | |

```
overall = not_generated     생성이 끝나지 않음
        | blocked_by_code   code_gate=blocked  (모델이 pass 여도)
        | needs_revision    code_gate=attention · 모델 revise/ask_user · 검증 미완료
        | awaiting_human    코드 pass · 모델 pass — 사람 검수 대기
        | approved          human_review=passed 일 때만 (코드는 쓰지 않는다)
```
"사용자 제공 가능" 은 approved 뿐이다.

## 4. 한 장 시험 (수필 집필 성능)
Seed C 전체를 다시 돌리기 전에 **장 집필 v4 하나만** 실제로 시험한다.
- 계획 파일 `backend-agent/eval/trial_C_sewing.json` — 장 역할 · 사건 묶음 7개 · 끈 2개(발틀 재봉틀 · 큰언니) · focus/context 턴만. **예상 정답 수필은 없다** — `trial_plan` 이 정답성 키(expected · answer · 정답 …)와 160자 넘는 글을 거부한다
- 받는 원문: 24턴 · 회차 c1 · c2 · c4 · c5 (사건 묶음 순서로)
- 모델 호출 **1회**(장 집필). 분석 · 목차는 계획이 대신, 편집 · 검증은 부르지 않는다
- 기록: `eval/runs/<run_ref>-trial/` — `00_trial_plan.json` · `00_input.json` · `03_ch-1.json` · 원응답 · `result.json`(코드 판정 · 지표 · 문단별 회차) · `run.json`

```bash
cd backend-agent
.venv\Scripts\python tools\memoir_pipeline.py --seed eval\memoir_seed_C.json --aliases c1,c2,c3,c4,c5 --chapter-trial eval\trial_C_sewing.json --dry-run
.venv\Scripts\python tools\memoir_pipeline.py --seed eval\memoir_seed_C.json --aliases c1,c2,c3,c4,c5 --chapter-trial eval\trial_C_sewing.json
```

### 성공 기준 (사람이 읽고 판정 — 코드 지표는 참고)
| # | 기준 | 참고로 볼 것 |
|---|---|---|
| 1 | 여러 회차의 발언이 하나의 흐름으로 통합 | `paragraph_sessions`(문단마다 쓰인 회차), 여러 턴 묶은 문장 수 |
| 2 | 1인칭 수필체가 자연스럽게 유지 | `style_mix` 0 |
| 3 | 원문 한 턴을 한 문장으로 옮기는 패턴 감소 | 원문 그대로 비율 · `verbatim_run` (v3 C: 55/57 · 0.51) |
| 4 | 사실 · 감정을 만들지 않음 | 문장별 근거 턴과 원문 대조 (사람) |
| 5 | 중복 · 인터뷰 진행 문구 없음 | `stop_phrase` · `answer_trace` · `repeat_turn` 0 |
| 6 | 하나의 수필로 읽힘 | 사람 |

## 5. 테스트
8P 93개(v3 까지 76 유지 · fixture 를 v4 계약과 수필체 문장으로 + 신규 17) · 전체 162 passed · 실제 `.env` 를 둔 채 막은 시도 0 · theme-interview `460b855` 사본 93 · dry-run A3 · B · C · 한 장 시험 호출 0.

신규: 수필체 종결과 인용 제외 · 중단 표현 block / 답 흔적 fix · repeat_turn 은 kept 로 통과, 문체는 kept 로 통과 못 함 · overall 5갈래(사람 없이 approved 없음) · run 결과 4상태와 중단 표현 차단 · 편집에 checks 전달과 처리 기록 · **장 경계의 이웃 턴 제외(Seed C 26 · 27 · 28 로 v3 중복 재현)** · 사건 묶음 순서 · threads 계약과 다중 시점 경고 · 목차 role · threads · closing · 모음 장 경고 · 시험 계획이 정답 글을 거부 · 한 장 시험 1회 호출 · 키 없으면 네트워크 없이 실패 · 지시문 · 시험 계획에 Seed C 원문 조각 없음.

## 6. 정해야 할 것
- 1인칭 대명사를 "나"로 두었다(~다 체에 맞춤). 다르게 정했다면 알려 주면 지시문만 바꾼다
- 한 장 시험의 이웃 턴: 다른 장이 없어 같은 회차 앞뒤 턴(1 · 5 · 10 · 13 · 14 · 16 · 25 · 28 · 30 · 37)이 문맥으로 함께 간다 — 실제 파이프라인과 같은 조건. 이 턴을 근거로 쓰면 장 단계 경고로 남는다

## 7. 실행 전 확인 (2026-10-26T08:13Z)
- **핵심 · 문맥 턴**: 장 입력에 `core_turns`(장이 소유한 사건 턴 ∪ context_turns)와 `context_only_turns`(같은 회차 이웃으로만 온 턴)를 따로 싣는다. 한 장 시험은 core 14개(focus 13 + 29), 문맥만 10개(1 · 5 · 10 · 13 · 14 · 16 · 25 · 28 · 30 · 37). 장 지시문: 본문은 core 로, 문맥에만 있는 사건 · 인물을 들이지 않는다. 코드 검사 `context_only`(fix): 근거가 문맥 턴뿐인 supported 문장 — 편집 checks 로 간다. 문맥 턴과 core 턴을 함께 단 문장은 허용
- **kept**: 이유가 있어도 repeat_turn 말고는 code_gate 에서 남은 문제(attention)로 센다 → overall needs_revision. block 규칙은 kept 여도 blocked. repeat_turn kept 는 그 턴의 중복만 인정. 편집 지시문에 명시
- 테스트 8P 100(+7) · 전체 169 · theme-interview 사본 100 · 막은 시도 0

## 8. 한 장 시험 뒤 보완 (v4 유지, 작은 수정)
- **시험 계획**: 턴 14 를 core 로(e-factory [14, 15]) — 공장 사건의 출발(나이 · 서울 · 동대문)이라 문맥으로 둘 이유가 없다. 턴 29 도 e-sister-death [29, 34] 로 — 별세와 이어지는 '병원 다녀온 그다음 해'의 근거. 순서: 바느질 배움 → 공장 → 발틀이 옴 → 가게 시절 → 언니의 병과 별세 → 2010 가게 정리 → 지금. 받는 턴 24 그대로, 문맥만 9개. 새 사건 · 감정 · 본문 글 없음
- **보조 검사 fact_token (fix, 경고)**: 문장의 숫자 · 연도 · 나이 · 시각 · 인원과 원문에서 장소 조사 앞에 오는 드문 낱말(3턴 이하)이 그 문장의 근거 턴(질문+답)에 있는가. 없으면 그 말이 있는 턴을 detail 에. 편집이 kept + 이유로 두면 code_gate 가 남은 것으로 치지 않는다 — 말을 바꿔 쓴 경우 막지 않기 위해
  - 한계: 뜻이 근거와 맞는지, 감정 · 인과가 근거에 있는지는 보지 않는다. 낱말 대조라 원문과 다른 말로 쓴 장소는 놓치고, 흔한 말은 일부러 뺐다 — **의미상의 출처 오류를 다 잡지 못한다** (검증 · 사람 몫)
  - 실측: v4 한 장 출력 9문장 → p1 만 3건(열일곱 살 · 서울 · 동대문, 모두 턴 14). v3 C 편집본 57문장 → 1건(ch-3 '대전으로' 근거 19, 실제 18 — 진짜 누락)
- **장 지시문**: 사건 묶음은 문단 단위가 아니다 · 한 턴 한 묶음을 한 문단으로 세우지 않는다 · 문단 · 문장 수 정해지지 않음 · 지나친 감성 · 원문에 없는 인생 교훈 금지 · 문맥 턴의 말을 쓰면 그 턴을 turns 에 · 문장 항목 하나에 문장 하나 · 숫자 · 연도 · 나이 · 지명 턴을 빠뜨리지 않음. 편집 지시문: fact_token 처리
- 테스트 8P 107 (+7: 14 · 15 회귀 · 자연스러운 바꿔 쓰기 비차단 · editorial 사실 · kept 대우 · 시험 기록 · 편집 전달 · 계획 순서 · 지시문) · 전체 176 · theme-interview 사본 107 · 막은 시도 0
