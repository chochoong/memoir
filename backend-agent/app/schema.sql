-- 기억의 조각 — Phase 1 스키마
-- psql -h localhost -U memoir -d memoir -f app/schema.sql
--
-- 마이그레이션 도구를 쓰지 않는다. 4주 프로젝트에는 이 파일 하나가 낫다.
-- 스키마를 바꿀 때는 이 파일을 고치고 DROP 후 다시 만든다 (Phase 1 한정).

CREATE TABLE IF NOT EXISTS session (
    session_id   UUID PRIMARY KEY,
    user_id      TEXT        NOT NULL,
    title        TEXT        NOT NULL,
    photo_id     UUID,                          -- 사진 없이 시작할 수 있다
    photo_clues  JSONB,                         -- 회차당 1회 추출해 재사용 (FR-AD-315)
    state        TEXT        NOT NULL DEFAULT 'SPEAKING',
    turn         INT         NOT NULL DEFAULT 0,
    max_turn     INT         NOT NULL DEFAULT 0,   -- 0 = 제한 없음
    t2_seconds   NUMERIC(3,1) NOT NULL DEFAULT 5.0,   -- 3 / 5 / 7
    closed_reason TEXT,                         -- max_turn | finish | abort
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS session_user_idx ON session (user_id, created_at DESC);

-- 조각. idx 가 곧 서사의 시간 순서다 (FR-AD-401).
-- 0번은 엽서, 1번부터가 인터뷰 답변.
CREATE TABLE IF NOT EXISTS turn (
    turn_id      BIGSERIAL PRIMARY KEY,
    session_id   UUID        NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,
    idx          INT         NOT NULL,
    question     TEXT,                          -- 0번 조각에는 질문이 없다
    answer       TEXT        NOT NULL,
    decision     JSONB,                         -- action / reason (FR-IV-006 근거 기록)
    latency      JSONB,                         -- 구간별 지연 (FR-AD-314)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, idx)
);

-- 오브젝트 스토리지의 사진. 바이트는 여기 넣지 않는다.
CREATE TABLE IF NOT EXISTS photo (
    photo_id      UUID PRIMARY KEY,
    session_id    UUID,
    storage_key   TEXT        NOT NULL,
    mime          TEXT        NOT NULL,
    status        TEXT        NOT NULL DEFAULT 'pending',   -- pending | stored
    bytes         BIGINT      NOT NULL DEFAULT 0,
    sha256        TEXT,
    width         INT,
    height        INT,
    exif_taken_at TIMESTAMPTZ,      -- 스캔·촬영 시각. memory_year 가 아니다
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
