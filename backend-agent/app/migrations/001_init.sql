-- 001 — 처음 세 테이블 (session / turn / photo)
--
-- **이 파일은 이미 적용되었다. 고치지 않는다.**
--
-- 예전에는 app/schema.sql 한 장이었고, 바꿀 때는 「DROP 후 다시 만든다」였다.
-- 실사용자가 한 명이라도 들어오면 그게 불가능해진다 — 그 뒤 첫 스키마 변경을
-- 운영 DB 에서 수작업 SQL 로 하게 되고, 그게 사고가 나는 자리다.
--
-- 그래서 이 파일을 001 로 봉인하고, 앞으로의 변경은 002, 003 … 을 **새로** 더한다.
-- migrate.py 가 적용된 파일의 체크섬을 들고 있어서, 여기를 고치면 다음 기동이
-- 조용히 지나가는 대신 소리를 내며 멈춘다 (migrate.MigrationError).
--
-- 전부 CREATE ... IF NOT EXISTS 다. schema.sql 로 이미 만들어 둔 개발 DB 에도
-- 그대로 걸리고, 001 이 적용됨으로 기록되기만 한다.

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
    closed_reason TEXT,                         -- finish | abort | max_turn | turn_cap | expired
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
