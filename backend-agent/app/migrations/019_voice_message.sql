-- 019 — 가족 음성편지 (자서전당 1개 · 최대 5분)
--
-- 업무지시서 「가족 음성편지 1차 구현」 (11/26). 흐름은 voice_message.py 머리 참조.
--   ① 녹음 → 화면에서 미리듣기 → 「저장」 → ② 임시 업로드(voice_upload, state=uploaded, 기한 24시간)
--   → ③ 책이 저장되면(memoir_id) ④ 책에 연결(memoir_voice). 연결이 성공해야 저장 완료다.
-- 생성 작업(job_id)은 메모리에만 있어 사라질 수 있다 — 임시 업로드는 job_id 가 아니라 사용자 · 요청 id 로 남긴다.
-- 바이트는 사진과 같은 저장소(photo_blob · photostore)에 voice/… 키로 든다. 원본은 고치지 않고, 재생용 AAC 사본을 따로 둔다.

CREATE TABLE IF NOT EXISTS voice_upload (
    upload_id     TEXT PRIMARY KEY,
    user_id       TEXT        NOT NULL REFERENCES app_user (user_id) ON DELETE CASCADE,
    request_id    TEXT        NOT NULL,
    state         TEXT        NOT NULL DEFAULT 'uploaded'
                  CHECK (state IN ('uploaded', 'attached', 'released', 'discarded', 'purged')),
    mime          TEXT        NOT NULL,
    size_bytes    INT         NOT NULL,
    duration_ms   INT         NOT NULL,
    sha256        TEXT        NOT NULL,
    storage_key   TEXT        NOT NULL,
    play_key      TEXT        NOT NULL,
    play_mime     TEXT        NOT NULL,
    play_bytes    INT         NOT NULL,
    memoir_id     TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL,
    attached_at   TIMESTAMPTZ,
    released_at   TIMESTAMPTZ,
    UNIQUE (user_id, request_id)
);

COMMENT ON TABLE voice_upload IS '가족 음성편지의 파일. uploaded(책 연결 전 · 기한 있음) → attached(책에 연결) → released(교체 · 삭제로 참조 끊김) → purged(바이트 정리됨). discarded 는 사용자가 버린 임시 업로드';
COMMENT ON COLUMN voice_upload.storage_key IS '받은 원본 그대로 (webm/opus · mp4/aac)';
COMMENT ON COLUMN voice_upload.play_key IS '재생용 사본 (AAC m4a, ffmpeg 변환 — AI 변환 아님). 아이폰 · 안드로이드 모두 재생되게';
COMMENT ON COLUMN voice_upload.memoir_id IS 'attached 이후 연결된 책';

CREATE INDEX IF NOT EXISTS voice_upload_cleanup_idx ON voice_upload (state, expires_at);

-- 책 한 권의 음성편지 상태 — 한 줄. upload_id 가 NULL 이면 메시지 없음. 상태가 바뀔 때마다 revision 이 오른다.
CREATE TABLE IF NOT EXISTS memoir_voice (
    memoir_id        TEXT PRIMARY KEY REFERENCES memoir (memoir_id) ON DELETE CASCADE,
    user_id          TEXT        NOT NULL REFERENCES app_user (user_id) ON DELETE CASCADE,
    revision         INT         NOT NULL DEFAULT 0,
    upload_id        TEXT        REFERENCES voice_upload (upload_id),
    last_request_id  TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN memoir_voice.last_request_id IS '마지막으로 상태를 바꾼 연결 요청 id — 응답을 잃은 같은 요청의 재시도는 같은 결과를 받는다';

-- 공유 링크가 어느 책에서 나왔는지 — 받은 사람이 그 책의 지금 음성편지를 듣게 한다 (교체 · 삭제가 링크에 반영).
ALTER TABLE memoir_share ADD COLUMN IF NOT EXISTS source_memoir_id TEXT;
COMMENT ON COLUMN memoir_share.source_memoir_id IS '소유권을 확인한 원본 자서전. 없으면 글만 공유한 예전 링크';

-- 예전 링크 — 화면의 책 id(book_id)가 같은 사람의 저장된 자서전 id 와 같으면 그 책이다 (srv-memoir: 책 id = memoir_id).
UPDATE memoir_share s
   SET source_memoir_id = m.memoir_id
  FROM memoir m
 WHERE s.source_memoir_id IS NULL
   AND m.memoir_id = s.book_id
   AND m.user_id = s.user_id;

ALTER TABLE voice_upload ENABLE ROW LEVEL SECURITY;
ALTER TABLE memoir_voice ENABLE ROW LEVEL SECURITY;
