-- 003 — 로그인하는 사람과, 기록의 주인
--
-- 둘은 다른 사람이다. 계정을 만들고 복구하는 쪽은 가족이고, 이야기를 남기는
-- 쪽은 어르신이다. 한 표에 합치면 형제가 둘인 집에서 깨진다 — 어머니는 한
-- 분인데 계정은 둘이고, 기록은 먼저 만든 쪽에만 보인다.
--
--   app_user (가족)  ──┐
--                      ├── user_elder ── elder (어르신)
--   app_user (가족)  ──┘                    │
--                                           ├── session
--                                           └── photo
--
-- session·photo 는 건드리지 않는다. 지금은 아무 문자열이나 user_id 로 들어올 수
-- 있어서, 여기서 외래 키를 걸면 위조된 헤더 하나가 500 을 낸다. 쓰기 경로가
-- 전부 로그인을 거치게 된 뒤에 004 에서 elder 로 묶는다.
--
-- user 는 Postgres 예약어라 app_user 다.

CREATE TABLE IF NOT EXISTS app_user (
    user_id    TEXT PRIMARY KEY,
    provider   TEXT        NOT NULL,
    subject    TEXT        NOT NULL,
    email      TEXT,
    name       TEXT,
    picture    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login TIMESTAMPTZ
);

-- 제공자가 준 id 를 기본 키로 쓰지 않는다. 한 사람이 구글로 한 번 카카오로 한
-- 번 들어오면 우리 눈에는 두 사람이 되는데, 우리 id 가 따로 있어야 그때 두 줄을
-- 한 계정으로 붙일 수 있다.
CREATE UNIQUE INDEX IF NOT EXISTS app_user_provider_idx
    ON app_user (provider, subject);

COMMENT ON COLUMN app_user.subject IS
  '제공자가 준 고유 id (구글 sub · 카카오 id). 이메일이 아니다 — 이메일은 바뀐다';

CREATE TABLE IF NOT EXISTS elder (
    elder_id     TEXT PRIMARY KEY,
    display_name TEXT        NOT NULL,
    born_year    INT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN elder.born_year IS '태어난 해. 인터뷰가 시대 배경을 잡는 데 쓴다';

CREATE TABLE IF NOT EXISTS user_elder (
    user_id    TEXT        NOT NULL REFERENCES app_user (user_id) ON DELETE CASCADE,
    elder_id   TEXT        NOT NULL REFERENCES elder    (elder_id) ON DELETE CASCADE,
    role       TEXT        NOT NULL DEFAULT 'family',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, elder_id)
);

-- 「이 어르신을 볼 수 있는 가족」 방향. 기본 키는 반대 방향만 빠르다.
CREATE INDEX IF NOT EXISTS user_elder_elder_idx ON user_elder (elder_id);

-- 서명한 쿠키로 끝내지 않고 표를 두는 이유는 끊을 수 있어야 해서다. 어르신
-- 기기는 오래 살아 있어야 하는데, 오래 사는 것은 잃어버릴 수도 있다.
CREATE TABLE IF NOT EXISTS login_session (
    sid          TEXT PRIMARY KEY,
    user_id      TEXT        REFERENCES app_user (user_id) ON DELETE CASCADE,
    elder_id     TEXT        NOT NULL REFERENCES elder (elder_id) ON DELETE CASCADE,
    kind         TEXT        NOT NULL,
    label        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ
);

-- 쿠키 값을 그대로 넣지 않고 해시를 넣는다. 원본을 넣으면 이 표가 새는 순간
-- 그 값들이 전부 지금 쓸 수 있는 열쇠가 된다.
COMMENT ON COLUMN login_session.sid IS '쿠키 값의 sha256. 원본은 저장하지 않는다';
COMMENT ON COLUMN login_session.kind IS
  'web = 가족이 로그인했다 (짧다) · device = 어르신 기기에 물려 둔 것 (길다)';

CREATE INDEX IF NOT EXISTS login_session_elder_idx
    ON login_session (elder_id) WHERE revoked_at IS NULL;

-- 만료된 줄을 걷어내는 쓸기용. 지우지 않으면 표가 영원히 자란다.
CREATE INDEX IF NOT EXISTS login_session_expiry_idx ON login_session (expires_at);
