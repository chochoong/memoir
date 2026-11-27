# 9-C1 — 완성된 자서전의 사진 넣기 · 옮기기 · 빼기 (API 계약)

- 작성: 2026-11-25 · 근거: 업무지시서 「자서전 사진 추가·이동·삭제」 (11/25)
- 코드: `app/session/memoir_photos.py` · `app/main.py` (자서전 사진 절) · `app/migrations/018_memoir_photo_placement.sql` · `020_photo_placement_sessions.sql` (11/26 보완)
- 시험: `tests/test_memoir_photos.py` (업무지시서 7절 완료 기준 C1~C7 · 배치 id 회귀) · `tests/test_memoir_photos_db.py` (실제 Postgres)

## 정한 것

| 항목 | 결정 |
|---|---|
| 사용자 선택 vs 자동 배치 | **사용자 선택이 언제나 먼저.** 따로 저장(018 표)해서 재처리(`--refresh-photos` · 삽화 재처리)가 덮지 않는다 |
| 자리 기준 | `chapter_no` = 원고의 장 번호, `after_paragraph` = 그 장 문단 번호 **0부터** (화면 `srv-memoir.mapFigures` 와 같다). 그 문단 **뒤**에 놓인다 |
| 같은 문단 여러 장 | `display_order` 작은 것 먼저 → 같으면 넣은 순서. 같은 문단의 AI 삽화는 사진들 **뒤** |
| AI 삽화가 있는 장에 사진을 넣으면 | **둘 다 보인다** (삽화를 숨기지 않는다) |
| AI 삽화 옮기기 · 빼기 | 이번 범위 아님 (`origin: "ai"`, `placement_id: null`) |
| 책 한 권에 넣는 사진 | 최대 **30장** (`MEMOIR_PHOTOS_MAX`, 넣은 사진만 센다) |
| 넣은 사진의 분석 | **하지 않는다** — 모델 · 그림 호출 0 |
| 빼기 | 이 책에서만. 사진 파일 · 엽서 · 다른 책은 그대로 |
| 사진 교체 · 본문 편집 · 위치 추천 | 범위 밖 |

## 읽기 — 기존 응답에 칸만 더해짐

`GET /api/memoirs/saved/{id}` 의 `illustrations`, `GET /api/memoirs/saved/{id}/illustrations` 둘 다 같다.

```jsonc
{"status": "done", "chapters": [
  {"no": 1, "state": "photo", "figures": [
    {"kind": "photo", "url": "/api/photos/1111…", "after_paragraph": 0, "width": 800, "height": 600,
     "ai_generated": false, "caption": null,
     "placement_id": "a_006b7a61…", "origin": "auto", "display_order": 0, "photo_id": "1111…"}   // ← 새 칸 4개
  ]},
  {"no": 2, "state": "illustrated", "figures": [
    {"kind": "photo", "url": "/api/photos/2222…", "after_paragraph": 1, …, "placement_id": "p_9f…", "origin": "manual", "display_order": 0},
    {"kind": "illustration", "url": "/api/memoirs/saved/…/illustrations/2?v=…", "after_paragraph": 1, …,
     "placement_id": null, "origin": "ai", "display_order": null}
  ]}
], "unplaced_photos": [ … ]}
```

- `origin`: `auto` 자동으로 놓인 회차 사진 · `manual` 사용자가 넣은 사진 · `ai` AI 삽화.
- `placement_id` 는 **책마다 다르다** — 같은 인터뷰로 만든 두 책의 같은 사진도 id 가 달라 서로 영향이 없다. 자동 사진의 id 는
  재처리로 회차 묶음이 바뀌어도 그대로다 (11/26 보완, 020). 화면은 늘 응답에 온 id 를 그대로 쓰면 된다.
- 한 장 안의 figures 는 **이미 정렬돼 있다** — 같은 문단이면 배열 순서대로 쌓으면 된다. 화면과 PDF(`window.print`)가 같은 배열을 쓰면 순서가 같다.
- 사진을 손대지 않은 책은 예전과 같은 figures 에 칸 4개만 더해진다.
- 사용자가 다시 넣은 사진은 `unplaced_photos` 에서 빠진다.

## 넣기 — `POST /api/memoirs/saved/{id}/photos` → 201

두 모양이 있다.

**① 새 사진** — 본문 = 사진 바이트 그대로 (`POST /api/photos` 와 같다, multipart 아님). 자리는 주소에.
```
POST /api/memoirs/saved/{id}/photos?chapter_no=2&after_paragraph=1[&display_order=0][&request_id=…]
Content-Type: image/jpeg   (형식은 앞머리 바이트로 가린다 — JPEG · PNG · HEIC 등 /api/photos 와 같다)
<바이트>
```

**② 이미 올린 내 사진** (예: 책에서 뺀 회차 사진을 다시 넣기)
```jsonc
POST /api/memoirs/saved/{id}/photos
Content-Type: application/json
{"photo_id": "2222…", "chapter_no": 2, "after_paragraph": 1, "display_order": 0, "request_id": "…"}   // 뒤 두 칸은 선택
```

응답
```jsonc
201 {"placement": {"placement_id": "p_9f…", "origin": "manual", "photo_id": "…", "url": "/api/photos/…",
                   "chapter_no": 2, "after_paragraph": 1, "display_order": 0, "width": 1280, "height": 960}}
```
- `display_order` 를 안 주면 그 문단 뒤 **맨 끝**.
- `request_id`(화면이 만든 아무 문자열)를 주면 같은 요청을 다시 보내도 한 장만 들어간다 — 두 번째는 **200** 과 같은 placement.

## 옮기기 — `PATCH /api/memoirs/saved/{id}/photos/{placement_id}` → 200

```jsonc
{"chapter_no": 3, "after_paragraph": 0}        // 다른 장 · 문단으로 (한쪽만 주면 다른 쪽은 지금 값)
{"display_order": 2}                          // 같은 자리에서 순서만
```
- `auto`(a_…) · `manual`(p_…) 둘 다 된다. 자동 사진을 옮긴 자리는 재처리 뒤에도 그대로.
- 자리를 바꾸고 `display_order` 를 안 주면 새 자리의 맨 끝. 응답은 넣기와 같은 `{"placement": …}`.

## 빼기 — `DELETE /api/memoirs/saved/{id}/photos/{placement_id}` → 204

- 이 책에서만 빠진다. 자동 사진을 빼면 다시 열어도 · 재처리해도 나타나지 않는다.
- 뺀 사진을 다시 넣으려면 넣기 ② (`photo_id`).

## 실패 — `{"detail": "<화면에 보일 말>", "code": "<갈래>"}`

| 상태 | code | 언제 |
|---|---|---|
| 400 | (detail 만) | 사진 형식이 아니다 · 너무 크다(413) · JSON 이 틀렸다 |
| 401 | | 로그인 안 됨 |
| 404 | `memoir_not_found` | 없는 책 · **남의 책** · 지운 책 |
| 404 | `placement_not_found` | 없는 배치 · 남의 배치 · 이미 뺀 사진 |
| 404 | `photo_not_found` | 없는 사진 · **남의 사진** (있는지 자체를 알려 주지 않는다) |
| 422 | `bad_position` | `chapter_no` · `after_paragraph` · `display_order` 가 숫자가 아니다 / 빠졌다 |
| 422 | `no_such_chapter` | 원고에 없는 장 |
| 422 | `no_such_paragraph` | 음수 · 그 장 문단 수 이상 |
| 422 | `too_many_photos` | 넣은 사진이 이미 30장 |
| 422 | `photo_not_stored` | 아직 저장되지 않은 사진 |
| 503 | | 저장 실패 — 새 사진이면 올린 사진도 되돌린다. 다시 시도하면 된다 (`request_id` 권장) |

## 남은 제한

- **공유 링크(`/b/…`)에는 아직 사진이 실리지 않는다** (11/19 · 11/25 요청서의 공유 그림 — 별도 작업). 그때 이 최종 배치를 그대로 쓴다.
- 화면에서 글을 고친 책(`doc.edited`)은 지금처럼 그림을 넣지 않는다 — 문단 번호가 원고와 달라졌을 수 있어서다.
- 회차에서 뗀 · 책에서 뺀 사진 파일을 지우는 정리 규칙은 아직 없다 (파일은 남는다).
