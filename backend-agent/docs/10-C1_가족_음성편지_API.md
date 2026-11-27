# 10-C1 — 가족 음성편지 (자서전당 1개 · 최대 5분) API 계약

- 작성: 2026-11-26 · 근거: 업무지시서 「가족 음성편지 1차 구현」 v1.0 (11/26)
- 코드: `app/session/voice_message.py` · `app/main.py` (가족 음성편지 절) · `app/migrations/019_voice_message.sql`
- 시험: `tests/test_voice_message.py` (API · 경합 · 공유 · 정리, 21건) · `tests/test_voice_message_db.py` (실제 Postgres 트랜잭션)

## 정한 값

| 항목 | 값 |
|---|---|
| 길이 | 최대 **300초**. 서버가 실제 길이를 잰다 (녹음 끝 여유 2초까지 받고, 기록은 300초로). 0.5초 미만은 거절 |
| 형식 | `audio/webm`(Opus — 크롬 · 안드로이드) · `audio/mp4`(AAC — 사파리 · 아이폰). 앞머리 바이트로 가린다 |
| 크기 | 최대 **8MB** (받는 중에 넘으면 끊는다 — 413) |
| 원본 | 그대로 보관. 받아 적기 · 무음 제거 · AI 변환 없음 |
| 재생 | 서버가 만든 **AAC(m4a) 재생용 사본** — 아이폰 · 안드로이드 모두 재생. `Range` 지원(206) |
| 임시 업로드 기한 | **24시간**. 지나면 410 `upload_expired` |
| 정리 | 서버가 1시간마다: 기한 지난 미연결 업로드 · 버린 것 · 교체 · 삭제된 파일. 연결된 파일은 지우지 않는다 |
| 공유 재생 주소 | 10분짜리 서명 주소. 만료되면 `/api/b` 를 다시 읽는다 |
| 유료 호출 | 없음 |

## 흐름

```
녹음(최대 5분, 자동 종료) → 미리듣기 → [저장]
  ② POST /api/voice-message-uploads           → upload_id (state=uploaded)  ← 아직 저장 완료 아님
  ③ 책이 아직 없으면(job 의 memoir_id 가 null) → 화면 「책에 연결 대기」
  ④ PUT /api/memoirs/saved/{memoir_id}/voice-message → message.state = "ready"  ← 이것만 저장 완료
```
- 책 생성(job)과 녹음 · 업로드는 서로 기다리지 않는다. **둘 다 끝난 뒤** ④를 부른다.
- 생성 실패 · 취소 · `done` 인데 `memoir_id = null` 이면 ④를 부르지 않는다. 업로드는 24시간 남아 있다 — **다른 책 · 최신 책에 자동으로 붙이지 않는다.**

## ② 임시 업로드 — `POST /api/voice-message-uploads`

```
POST /api/voice-message-uploads
X-Request-ID: <이 녹음에 한 번 만든 id — 재시도에 그대로, 새 녹음은 새 id>
Content-Type: audio/webm            (형식은 서버가 바이트로 가린다)
<녹음 바이트 그대로 — multipart 아님>
```
```jsonc
201 {"upload_id": "vu_…", "state": "uploaded", "duration_ms": 183400, "mime": "audio/webm",
     "size_bytes": 1830211, "expires_at": "2026-11-27T10:00:00+00:00", "memoir_id": null}
```
- 같은 `X-Request-ID` 로 다시 보내면 **200** 과 처음 업로드 (응답을 잃었을 때). 이미 책에 연결됐으면 `state: "attached"`.
- 버리기: `DELETE /api/voice-message-uploads/{upload_id}` → 204. 책에 연결된 파일이면 409 `upload_attached`.

## ④ 책 연결 · 조회 · 삭제 — `/api/memoirs/saved/{memoir_id}/voice-message`

**GET** → `{revision, message}`
```jsonc
{"revision": 0, "message": null}
{"revision": 1, "message": {"message_id": "vu_…", "state": "ready", "duration_ms": 183400, "mime": "audio/mp4",
                            "created_at": "…", "playback_url": "/api/memoirs/saved/m_…/voice-message/audio?v=…"}}
```
- `playback_url` 은 책 주인용 (로그인 쿠키로 열림) — `<audio src>` 에 그대로.

**PUT** (연결 · 교체)
```jsonc
{"upload_id": "vu_…", "request_id": "<연결 요청 id>", "expected_revision": 0}
```
- 성공 응답은 GET 과 같다. 있던 메시지는 **이 응답이 성공한 순간에만** 바뀐다 — 그전까지 예전 메시지가 계속 재생된다.
- 같은 `request_id` 재시도는 같은 결과(200). `expected_revision` 이 지금과 다르면 **409 `revision_conflict` `{revision}`** — GET 으로 다시 읽고 사용자에게 고르게 한다. 늦게 온 저장이 삭제 · 교체를 되돌리지 못한다.

**DELETE** `?expected_revision=값` → 204. 그 뒤 GET 은 `message: null`. revision 이 다르면 409.

## 공유받은 사람 (로그인 없음)

- 저장된 자서전에서 새로 낸 공유(`POST /api/shares` 의 `book_id` = `memoir_id`)는 서버가 원본 자서전을 단다 (내 책 · 지우지 않은 책만).
- **예전 링크도** `book_id` 가 같은 사람의 `memoir_id` 이면 마이그레이션이 이어 붙였다. 기기에만 있던 책의 링크는 글만 — `voice_message: null`.
- `GET /api/b` (X-Share-Token) 응답에 칸이 하나 더해진다:
```jsonc
{"book": {…}, "shared_at": "…",
 "voice_message": {"message_id": "vu_…", "duration_ms": 183400, "mime": "audio/mp4",
                   "playback_url": "/api/b/voice?s=…&m=…&e=…&k=…", "url_expires_at": "…"}}   // 없으면 null
```
- `playback_url` 은 **10분짜리 서명 주소**다 (`<audio>` 는 헤더를 못 붙여서). 재생할 때마다 서버가 다시 본다:
  만료 · 서명 틀림 → 410 `url_expired` (→ `/api/b` 다시) · 공유 꺼짐 → 410 `share_revoked` · 메시지가 교체 · 삭제됨 → 410 `message_gone` (→ `/api/b` 다시 읽으면 지금 메시지).
- 교체 · 삭제는 이미 보낸 링크에도 바로 반영된다 (링크가 책의 **지금** 음성편지를 가리킨다).

## 실패 — `{"detail": "<화면에 보일 말>", "code": "<갈래>"}`

| 상태 | code | 언제 · 화면이 할 일 |
|---|---|---|
| 400 | `request_id_required` · `bad_revision` | 요청을 고쳐 보낸다 |
| 401 | | 로그인 |
| 404 | `memoir_not_found` | 없는 책 · **남의 책** · 지운 책 |
| 404 | `upload_not_found` | 없는 업로드 · 남의 업로드 |
| 404 | `message_not_found` | 지울 메시지가 없다 |
| 409 | `revision_conflict` (+`revision`) | 다른 곳에서 바뀌었다 → GET 후 다시 |
| 409 | `upload_in_use` | 이미 다른 책에 연결된 업로드 |
| 409 | `upload_attached` | 연결된 파일을 업로드 쪽에서 버리려 함 → 책에서 DELETE |
| 410 | `upload_expired` | 24시간 지남 · 버림 · 교체됨 → 탭에 원본이 있으면 **새 X-Request-ID** 로 다시 업로드, 없으면 재녹음 안내 |
| 413 | | 8MB 초과 |
| 415 | `unsupported_audio` | webm · mp4 음성이 아니다 · 영상이 섞였다 · 읽을 수 없다 |
| 422 | `too_long` · `too_short` | 300초 초과 · 0.5초 미만 |
| 503 | `voice_unavailable` · `voice_busy` · (code 없음) | 서버 처리 · 저장 실패 → **저장 완료 표시 금지**, 같은 id 로 재시도 |

## 남은 제한

- 실제 기기 확인(아이폰 · 안드로이드 녹음 → 저장 → 공유 재생)은 화면이 붙은 뒤 함께 한다.
- 서버 재시작 때 공유 재생 주소가 풀릴 수 있다 (`VOICE_URL_SECRET` 이 없으면 프로세스마다 새 열쇠) — 화면은 410 `url_expired` 에서 `/api/b` 를 다시 읽으면 된다.
- 브라우저를 닫은 뒤 녹음 복구 · 영구 보관은 하지 않는다 (업로드는 24시간만).
