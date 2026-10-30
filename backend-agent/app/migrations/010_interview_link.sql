-- 010 — 인터뷰 링크와 회차의 화자
--
-- 자녀가 회차를 준비해 링크로 보내면, 받은 사람은 로그인 없이 그 회차 하나만
-- 진행한다. 링크는 「이 준비로 회차 하나를 열어도 된다」는 권한이다 — 링크를 연
-- 사람이 실제 어르신이라는 보증은 아니다.
--
-- 시작 전에는 준비만 있고 회차가 없다. 회차는 받은 사람이 「시작」을 누를 때 열린다
-- (session_id 가 그때 채워진다). 그래서 메신저 미리보기나 몇 번 열어 보는 것으로는
-- 아무것도 소모되지 않는다.

CREATE TABLE IF NOT EXISTS interview_link (
    link_id     TEXT PRIMARY KEY,
    token_hash  TEXT        NOT NULL UNIQUE,
    user_id     TEXT        NOT NULL REFERENCES app_user (user_id) ON DELETE CASCADE,
    elder_id    TEXT        NOT NULL REFERENCES elder (elder_id) ON DELETE CASCADE,
    title       TEXT        NOT NULL,
    seed        TEXT        NOT NULL DEFAULT '',
    theme       TEXT,
    topic       TEXT        NOT NULL DEFAULT '',
    photo_id    UUID,
    session_id  UUID UNIQUE,
    device_hash TEXT UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    started_at  TIMESTAMPTZ,
    ended_at    TIMESTAMPTZ
);

-- 토큰을 그대로 넣지 않는 이유는 login_session.sid 와 같다. 표가 새도 열쇠가 되지 않는다.
COMMENT ON COLUMN interview_link.token_hash IS '링크 토큰의 sha256. 원본은 발급 응답에 한 번만 나간다';
COMMENT ON COLUMN interview_link.device_hash IS
  '시작한 기기에 준 쿠키(mlink)의 sha256. 진행은 이 기기에서만 이어진다';
COMMENT ON COLUMN interview_link.expires_at IS
  '시작 전 유효 기한, 끝난 뒤 대화를 읽을 수 있는 기한. 진행 중에는 보지 않는다';

CREATE INDEX IF NOT EXISTS interview_link_user_idx ON interview_link (user_id, created_at DESC);

ALTER TABLE interview_link ENABLE ROW LEVEL SECURITY;

-- 회차의 화자. 링크로 연 회차부터 채운다. 그 전 회차는 화자를 모르므로 비워 둔다.
ALTER TABLE session ADD COLUMN IF NOT EXISTS elder_id TEXT;
