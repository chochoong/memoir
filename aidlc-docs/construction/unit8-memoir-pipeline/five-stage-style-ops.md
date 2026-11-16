# 문체 3종 5단계 — 운영 설정과 화면 반영 (2026-11-15)

세 문체(수필체 · 문학체 · 소설체)는 `memoir_pipeline.run(style=…)` 로 분석 → 목차 → 집필(문체) → 편집 → 검증을 거친다.
아래는 실모델 시험(합성 자료 C · 소설체 · 5회차 39문답 → 6장 12,000자)에서 **성공한 설정**과, 지금 값이 어디에 있는지다.

## 1. 설정 — 지금 값과 시험에서 성공한 값

| 환경 변수 | 코드 기본값 | 문체 실행 때 코드가 올리는 값 | 시험에서 쓴 값 | 실측 |
|---|---|---|---|---|
| `MEMOIR_PIPE_TEXT_MODEL` | `gemini-3.5-flash-lite` | — | `gemini-3.1-pro-preview` | 분석 · 목차 · 편집 · 검증 모두 정상 종료 |
| `MEMOIR_PIPE_ANALYSIS_TIMEOUT` / `_MAX_OUTPUT_TOKENS` | 90초 / 8,000 | — | 300초 / 32,768 | 139 ~ 144초 · 출력 7,210 ~ 9,243 + 생각 18,333 ~ 20,988 토큰 |
| `MEMOIR_PIPE_OUTLINE_TIMEOUT` / `_MAX_OUTPUT_TOKENS` | 60초 / 6,000 | — | 300초 / 32,768 | 61초 · 출력 3,059 + 생각 7,687 |
| `MEMOIR_PIPE_EDIT_TIMEOUT` / `_MAX_OUTPUT_TOKENS` | 150초 / 10,000 | 300초 / 32,768 | 600초 / 65,536 | 175초 · 출력 25,320 + 생각 11,779 = **37,099** |
| `MEMOIR_PIPE_VERIFY_TIMEOUT` / `_MAX_OUTPUT_TOKENS` | 90초 / 6,000 | — | 300초 / 32,768 | 60초 · 출력 1,229 + 생각 7,216 |
| `MEMOIR_PIPE_TOTAL_TIMEOUT` | 600초 | + 문체 집필 상한(소설체 300 · 수필체 · 문학체 600) | 1,800초 (+300) | 한 권 약 8분 (분석 139 + 목차 61 + 집필 60 + 편집 175 + 검증 60) |
| `MEMOIR_NOVEL_MODEL` 등 문체 집필 | `claude-sonnet-5-5` · 65,536 · 300초 (문학체 128,000 · 600초) | — | 기본값 그대로 | 소설체 장당 48 ~ 60초 · 출력 4,879 ~ 6,070 토큰 |

- **코드 기본값만으로는 실패한다.** 분석은 90초를 넘기고(139초), 생각 토큰이 출력 상한에 들어가 8,000 · 6,000 으로는 잘린다. 편집은 문체 실행의 상한 32,768 을 넘는다(37,099).
- 긴 책은 편집 출력이 65,536(이 모델의 상한)도 넘을 수 있다 — 12,000자에 37,099 토큰이었다. 편집은 책 전체를 한 번에 낸다.

### 운영에 넣을 값 (backend-agent 의 `.env` — 서버에서 직접)

```
MEMOIR_PIPE_TEXT_MODEL=gemini-3.1-pro-preview
MEMOIR_PIPE_ANALYSIS_TIMEOUT=300
MEMOIR_PIPE_ANALYSIS_MAX_OUTPUT_TOKENS=32768
MEMOIR_PIPE_OUTLINE_TIMEOUT=300
MEMOIR_PIPE_OUTLINE_MAX_OUTPUT_TOKENS=32768
MEMOIR_PIPE_EDIT_TIMEOUT=600
MEMOIR_PIPE_EDIT_MAX_OUTPUT_TOKENS=65536
MEMOIR_PIPE_VERIFY_TIMEOUT=300
MEMOIR_PIPE_VERIFY_MAX_OUTPUT_TOKENS=32768
MEMOIR_PIPE_TOTAL_TIMEOUT=1800
```

`GEMINI_API_KEY`(분석 · 목차 · 편집 · 검증)와 `ANTHROPIC_API_KEY`(문체 집필)가 **둘 다** 있어야 한다. 문체는 `MEMOIR_ENGINE` 값과 상관없이 다섯 단계로 간다.
이 값들은 구어체 다섯 단계(`MEMOIR_ENGINE=pipeline`)에도 같이 적용된다 — 구어체의 장 집필 상한(`MEMOIR_PIPE_CHAPTER_*`)은 건드리지 않았다.

### 적용 대상

| 환경 | 지금 | 할 일 |
|---|---|---|
| 저장소 `backend-agent/.env.example` | `MEMOIR_PIPE_*` 가 모두 비어 있다(코드 기본값) | 바꾸지 않았다 — 위 값을 참고로 적을지는 팀이 정한다 |
| 로컬 개발 `.env` | `MEMOIR_PIPE_*` 없음 | 문체를 로컬에서 돌리려면 위 값을 넣는다 |
| 운영 서버의 `.env` | **확인하지 못했다** (저장소에 없다 · 서버에서만 볼 수 있다) | 위 값이 들어 있는지 확인하고 없으면 넣는다. 배포 · 재시작은 담당자가 |
| 시험 실행 | 프로세스 환경 변수로만 주었다 | — |

## 2. 화면 — 검증 알림

- `prototype/app/draft-verify.js` 를 추가하고 `python prototype/build.py` 로 `prototype/index.html` 을 다시 묶었다. 묶음 파일의 차이는 **이 스크립트 블록 87줄 추가뿐**이다.
  (이 PC 에서 그냥 묶으면 SVG 그림 5개의 줄바꿈이 달라져 base64 가 바뀐다 — 그 5줄은 기존 묶음 그대로 두었다.)
- 서버가 내보내는 것은 `backend-agent/web/index.html` 이다 — 배포 때 `prototype/index.html` 을 복사한다 (하지 않았다).
- 알림은 응답의 `verification.outcome` 이 있을 때만 그린다 (다섯 단계의 결과). 예전 한 번 호출의 초안에는 아무것도 더하지 않는다.

## 3. 응답의 검증 칸 읽는 법

| 칸 | 뜻 |
|---|---|
| `verification.state` | 검증 단계가 적은 값. **`completed` 는 끝까지 돌았다는 뜻일 뿐 — 문제가 없다는 뜻이 아니다** |
| `verification.outcome` | `passed`(사실 문제 없음 · 코드 판정도 막지 않음) · `issues_found` · `needs_confirmation` · `incomplete` · `failed` · `not_run` |
| `verification.issues` | 검증 모델이 원문과 대조해 낸 문제 — 위치 · 문장 · 종류 · 설명 · 원문 턴 |
| `to_confirm` | 그 가운데 **사람이 확인해야 풀리는 것만** (`ask_user` · `provide_context`) |
| `verification.code_gate` · `code` | 코드 판정 — `pass` · `attention`(참고 신호 · outcome 을 바꾸지 않는다) · `blocked`(정정 전 값 · 멈추는 말 등 — outcome 이 `issues_found` 가 된다) |
| `verification.style` | 편집 전후의 분량 · 대화 수 비교와 경고 |

검증 모델은 모든 문장을 보지 않는다 — 시험에서 248문장 가운데 12곳만 검토했다고 적었다. `passed` 여도 화면은 「AI 의 검토라 놓친 곳이 있을 수 있다」 고 알린다.
