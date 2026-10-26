# Domain Entities — 단위 8P 단계별 JSON 계약

필드 이름은 이 실험 안에서만 쓰는 제안이다. 현재 API · DB 에 없다 (지시서 §7.1).
**모델이 쓰는 것**(①~⑤ 출력)과 **코드가 붙이는 것**(run_ref · input_ref · 상태 · 시간)을 나눈다. 모델에게 상태 · 시간 · ID 를 쓰게 하지 않는다.

## 공통

### 턴 (Turn)
- `merge` 가 정한 **전역 턴** 정수 1..N. 모든 단계의 `turns` · `focus_turns` · `source_turns` 는 이 번호다.
- 유효 턴 집합 `T = {u.turn for u in input.utterances}`. 어느 단계도 새 번호를 만들거나 다시 매기지 않는다.

### 문장 항목 (Sentence)
```json
{"text": "가게 일을 하면서 회계책을 읽었어요.", "kind": "supported", "turns": [2]}
```
- `kind = "supported"` — 인생 사실을 담는다. `turns` 비면 안 되고, 모두 `T` 안.
- `kind = "editorial"` — 새 사실이 없는 제목 · 전환. `turns` 는 비워도 된다. 비어 있지 않으면 모두 `T` 안.
- 출처는 **문장 객체에 붙는다.** 인덱스 번호로 따로 잇지 않으므로 편집에서 합치거나 나눠도 옛 인덱스를 복사할 일이 없다.

### 제목 (Title)
문장 항목과 같은 모양 `{text, kind, turns}`.

## 0. 입력 (코드)
`memoir.merge` 출력 그대로.
```json
{"shared_state": {"confirmed_facts": [], "facts_found": [{"turn": 1, "facts": []}]},
 "sessions": [{"session_id": "s-a", "recorded_order": 1}],
 "utterances": [{"turn": 1, "session_id": "s-a", "asked": "", "elder": ""}]}
```
`turn_map` 은 기록에만 남기고 모델에 주지 않는다 (지금 서비스와 같음).
`input_ref` = 이 입력 JSON(정렬된 키, UTF-8)의 sha256 앞 12자.

## ① 분석 출력
```json
{"status": "ready",
 "events": [{"event_key": "e1", "summary": "", "turns": [1, 4],
             "people": ["어머니"],
             "time": {"text": "1979년", "certainty": "stated"},
             "said_feelings": [{"text": "", "turns": [4]}]}],
 "people": [{"name": "", "relation": "", "turns": [2]}],
 "themes": [{"theme": "", "supporting": [1, 4], "counter": [7], "note": ""}],
 "direction": {"theme": "", "reason": "", "neutral": false},
 "unclear": [{"issue": "", "turns": [3]}],
 "missing_context": []}
```
- `status`: `ready` / `insufficient_material` / `needs_context`
- `time.certainty`: `stated`(말씀에 있음) / `approx`(대략) / `unknown`
- `direction.neutral = true` — 주제가 선명하지 않아 중립 방향으로 둠

## ② 목차 출력
```json
{"status": "ready",
 "book": {"title": {"text": "", "kind": "editorial", "turns": []}, "direction": ""},
 "chapters": [{"chapter_key": "ch-1",
               "title": {"text": "", "kind": "editorial", "turns": []},
               "purpose": "", "events": ["e1"], "focus_turns": [1, 4],
               "context_turns": [5],
               "weight": "main", "transition_in": "", "transition_out": ""}],
 "missing_context": []}
```
- `status`: `ready` / `needs_context`
- `weight`: `main` / `minor`
- `chapter_key`: `ch-1` … `ch-5` (`^ch-\d{1,2}$`). 출력 안에서만 뜻이 있는 값이고 파일 이름에도 쓴다
- `context_turns`: 이 장 집필자가 이해에 꼭 필요한 다른 턴 — 정정한 턴, 대명사 · 주어의 대상, 같은 사건의 앞부분. 근거 턴이 아니라 문맥이다
- 장 수 1~5. 6 이상이면 `chapter_limit` 실패 (자르지 않는다)

## ③ 장 집필 입력 (Q4 — 장마다 전체 원문을 주지 않는다)
```json
{"outline": {"book": {}, "chapters": []},
 "chapter": {"chapter_key": "ch-1", "...": "목차의 이 장 항목"},
 "people": [{"name": "", "relation": "", "turns": []}],
 "source": {"sessions": [], "utterances": [], "shared_state": {"facts_found": []}},
 "given_turns": [1, 2, 4, 5]}
```
- `given_turns` = `focus_turns` ∪ 이 장 events 의 turns ∪ `context_turns` ∪ 그 턴들의 **같은 회차 앞뒤 1턴**
- `source` 는 merge 출력에서 `given_turns` 만 남긴 것. 항목 내용 · 번호는 merge 그대로다. `confirmed_facts` 는 회차 전체 요약이라 싣지 않는다
- 장 출력의 모든 turns 는 `given_turns` 안이어야 한다 (받지 않은 원문을 인용하면 `reference` 실패)

## ③ 장 집필 출력 (장마다 하나)
```json
{"chapter_key": "ch-1",
 "title": {"text": "", "kind": "editorial", "turns": []},
 "paragraphs": [[{"text": "", "kind": "supported", "turns": [1]}]],
 "review_notes": [{"issue": "", "turns": [4]}]}
```
- `paragraphs` — 문단 배열, 문단은 문장 항목 배열
- `review_notes` — 본문에서 뺀 확인 전 해석 · 심리 후보. 본문과 섞지 않는다.

## ④ 편집 출력
```json
{"title": {"text": "", "kind": "editorial", "turns": []},
 "chapters": [{"chapter_key": "ch-1", "title": {}, "paragraphs": [[]]}],
 "review_notes": [{"issue": "", "turns": []}],
 "edit_notes": [{"location": "ch-2/p0/s1", "change": "", "reason": ""}]}
```
- 장 집필의 `review_notes` 를 이어받아 정리한다.
- `location` 형식: `title` · `ch-K/title` · `ch-K/pP/sS` (P · S 는 편집 **뒤** 위치, 0부터)

## ⑤ 검증 출력 (`검증_v4.md` 의 5키를 이어받음)
```json
{"review_status": "completed",
 "verdict": "pass",
 "issues": [{"location": "ch-1/p0/s2", "severity": "blocker",
             "code": "unsupported_claim", "resolution": "auto_fix",
             "explanation": "", "source_turns": [3], "fix_instruction": ""}],
 "reviewed_locations": ["artifact", "title", "ch-1/title", "ch-1/p0/s0"],
 "missing_context": []}
```
- `review_status`: `completed` / `needs_context` / `not_applicable`
- `verdict`: `pass` / `revise` / `ask_user` / `null`
- `code`: `unsupported_claim` / `source_mismatch` / `time_distortion` / `identity_inference` / `material_omission` / `style_mismatch` / `exclusion_violation` / `editorial_misuse`(새 — 사실을 담은 문장을 editorial 로 표시)
- 검증에 주는 입력에 `review_scope = {"turns": [T 전체], "complete": true}` 를 코드가 붙인다.
- `issues[].location` · `reviewed_locations` 는 실제 편집본에 있는 위치만: `artifact` · `title` · `ch-K` · `ch-K/title` · `ch-K/pP/sS` · `review_notes:i`
- 검사 범위 (`5_검증_v1.md`): 장 / 문단 / 문장 구조, supported / editorial, 책 · 장 제목, 중립 전환, 전체 사용 범위 누락, 편집 뒤 turns 연결

## 결과 (코드가 조립) — `result.json`
```json
{"run_ref": "20261026T0530Z-A3-1a2b",
 "input_ref": "9f8e7d6c5b4a",
 "generation_state": "generated",
 "pipeline_complete": true,
 "human_review": "not_run",
 "failure": null,
 "title": {}, "chapters": [], "review_notes": [],
 "verification": {"state": "completed", "verdict": "pass", "issues": [],
                  "reviewed_locations": [], "missing_context": []},
 "calls": 6}
```
- `generation_state`: `generated` / `partial` / `failed` / `insufficient_material` / `needs_context`
- `pipeline_complete`: 다섯 단계 호출 · 검사가 모두 통과하고 `verification.state == "completed"` 일 때만 `true`. 판정(`verdict`)과는 따로 읽는다
- `human_review`: `not_run` / `passed` / `failed`. 코드는 늘 `not_run` 으로 쓴다. 모델 검증 pass 를 사람 검수로 쓰지 않는다
- `is_final` 은 두지 않는다
- `failure`: `{"stage": "input|analysis|outline|chapter|edit|final_check|verify", "chapter_key": null, "kind": "input|call|timeout|truncated|format|reference|context|chapter_limit|budget", "message": ""}`
  - `truncated` = 모델이 출력 토큰 상한(`MAX_TOKENS`)에서 멈춤. JSON 이 맞아 보여도 실패로 둔다
- `verification.state`: `not_run` / `failed` / `completed` / `needs_context` / `not_applicable`
- `partial` · `failed` 일 때 `title` · `chapters` 는 비운다. 성공한 장은 run 폴더의 단계 파일에만 있다.

## 실행 기록 (코드) — `run.json`
```json
{"run_ref": "", "input_ref": "", "seed": "memoir_seed_A.json", "aliases": ["s-a","s-b","s-c"],
 "started_at": "", "finished_at": "",
 "settings": {"MEMOIR_PIPE_TEXT_MODEL": "", "MEMOIR_PIPE_TEMPERATURE": 0.3, "...": "..."},
 "prompts": {"analysis": "sha256:…", "outline": "…", "chapter": "…", "edit": "…", "verify": "…"},
 "steps": [{"stage": "analysis", "chapter_key": null, "ok": true, "ms": 0,
            "timeout": 60.0, "max_output_tokens": 5000,
            "in_chars": 0, "out_chars": 0, "finish": "STOP",
            "usage": {"prompt": 0, "output": 0, "thoughts": 0, "total": 0},
            "file": "01_analysis.json", "raw_file": "01_analysis.raw.txt",
            "warnings": [], "error": null}],
 "generation_state": "", "pipeline_complete": false, "failure": null}
```
`settings` 에 키 값은 없다. 비밀값을 읽는 이름(`GEMINI_API_KEY`)은 기록하지 않는다. `usage` 는 모델이 돌려준 경우에만 채운다.

## run 폴더 파일
`00_input.json`(merge 출력 · turn_map) · `01_analysis.json` · `02_outline.json` · `03_ch-1.json` … · `04_edited.json` · `05_verify.json` · 단계마다 `*.raw.txt`(모델 원응답 글자 그대로) · `result.json` · `run.json` · `r1_summary.md`

## R1 요약 (`r1_summary.md`) — 팀 공유용 틀
run 폴더 전체는 git 에 올리지 않는다. 대신 실행마다 아래만 담은 요약을 만든다. **본문 · 원문 · 검증 설명문 · 비밀값은 넣지 않는다.**
- 실행 식별: `run_ref` · `input_ref` · seed · alias · 시각
- 설정: 모델 · 온도 · 단계별 시간 / 토큰 상한 · 재시도 0
- 상태: `generation_state` · `pipeline_complete` · `verification.state` · `verdict` · 실패 단계 · 종류
- 단계 표: 단계 · 장 · 성공 · ms · 입력 / 출력 글자 수 · token usage · finish · 경고 수
- 결과 모양: 장 수 · 장별 문단 / 문장 수 · supported / editorial 수 · review_notes 수
- 검증 issues: 위치 · severity · code · resolution (설명문 없이)
- 사람 검수 칸: `human_review` · 판정 · 메모 · 검수자 (비워 둠)
