# 초기 분석 — 자서전 5단계 파이프라인 (단위 8P)

**작성**: 2026-10-26 · 「자서전 5단계 파이프라인 사전 분석」(대화 보고)을 옮겨 적었다. 코드를 고치지 않고 읽기만 해서 쓴 분석이다.
**바뀐 점**: 처음 분석의 "장 하나가 실패해도 나머지 장은 진단용으로 계속 쓴다"는 사용자 지시(2026-10-26)로 **"실패한 그 자리에서 새 호출을 멈춘다"**로 바꿨다.

## 1. 현재 자서전 생성 흐름
`POST /api/memoirs/preview` 한 요청에 모델 호출은 한 번이다.

```
main.memoir_preview → memoir.preview
  check_selection  3~5개 · 중복 · UUID                    → 400
  collect          store.load_session (DB)                 → 404 / 422
  merge            기록 순서 정렬 · 전역 턴 1..N · turn_map
                   (회차 안 자료는 postcard.material)
  write            _client() 로 Gemini 1회
                   시스템 지시 = roledoc.assemble(자서전_v2.md, "5-2")
  check            7키 · 한 줄 한 문장 · 줄마다 출처 · 빈 줄/# 거부  → 502 / 503
  → 5키 응답, 저장 없음
```

- `검증_v4.md` 는 코드 어디에서도 부르지 않는다. 지금은 검증 단계가 없다.
- `자서전_v2.md` §5-2 · §7-4 의 "회차당 3~8문장 · 장 제목 금지 · 의미 해석 금지"와, §5 의 "body 는 한 줄에 한 문장"이 장 구조와 충돌한다.
- `memoir.check` 는 장 구조를 거부한다. 파이프라인 결과에는 쓰지 않는다.

## 2. 재사용
| 무엇 | 위치 | 쓰는 법 |
|---|---|---|
| 회차 합치기 | `memoir.merge()` | 1단계 입력 그대로. 전역 턴 · turn_map 의 유일한 출처 |
| 회차 자료 | `postcard.material()` | merge 안에서 |
| seed → 기록 | `tools/seed_sessions.rows()` | DB 없이 `load_session` 모양으로 (`test_memoir.record()` 와 같은 방식) |
| 클라이언트 | `question._client()` | 그대로 |
| 호출 방식 | `memoir.write()` 몸통 | config · `wait_for` · JSON 파싱 실패 처리를 옮겨 쓴다 (원 함수는 그대로) |
| 설정 | `conf.env_*` | `MEMOIR_PIPE_*` 를 같은 방식으로 |
| 공통 규칙 | `자서전_v2.md` §2 | 파이프라인 안의 작은 로더로 §2 만 읽어 다섯 지시문 앞에 (설계 승인 때 `roledoc._sections` 대신으로 바뀜) |
| 검증 바탕 | `검증_v4.md` | 출력 5키 · issue 모양을 이어받고 장 구조 기준으로 새로 씀 |
| 시험 자료 | seed A(5회차) · B(정정 · 제외 요청) | 대표 · 대조 |

## 3. 새 파일
`app/session/memoir_pipeline.py` · `tools/memoir_pipeline.py` · `첨부프롬프트_md/파이프라인/` 5개 · `tests/test_memoir_pipeline.py` · 결과 `eval/runs/` (git 제외)

## 4~5. 입출력 · 실행기
→ `functional-design/domain-entities.md` · `business-logic-model.md`

## 6. 기존 코드에 영향 없이 실험
- 새 파일만. `memoir.py` · `main.py` · `roledoc.py` · 기존 프롬프트 무수정 → 기존 테스트 그대로
- DB 없음 (seed → rows → merge). `main.py` 를 import 하지 않아 warmup 없음. `.env.supabase` 분기 없음
- 설정 이름 분리 (`MEMOIR_PIPE_*`)
- 가짜 호출을 끼워 모델 없이 흐름 · 실패 시험
- 결과 폴더 git 제외
- 미커밋 단위 4 와 섞지 않는다 (설계 계획 §11)

## 7. 구현 순서
→ `../plans/unit8-memoir-pipeline-code-generation-plan.md`
