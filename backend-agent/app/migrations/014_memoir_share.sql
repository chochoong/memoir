-- 014 — 자서전 공유 링크
--
-- 자서전은 저장하지 않는다 (7-C1 §4). 책은 자녀 기기(브라우저)에만 있다. 이 표는
-- 자녀가 「링크로 공유」 를 누른 그 순간의 책 한 권만 담는다 — 누르지 않은 자서전은
-- 여전히 어디에도 남지 않는다.
--
-- 링크를 받은 사람은 로그인 없이 읽기만 한다. 기한은 없고, 자녀가 끄면 그때 닫힌다.
-- 본문은 화면이 보여 주던 모양 그대로다 (제목 · 장 · 문단 · 문장). 서버가 다시
-- 만들지 않는다 — 장 일부는 서버가 다듬지 않은 엽서 글(초고)이기 때문이다.

CREATE TABLE IF NOT EXISTS memoir_share (
    share_id    TEXT PRIMARY KEY,
    token_hash  TEXT        NOT NULL UNIQUE,
    user_id     TEXT        NOT NULL REFERENCES app_user (user_id) ON DELETE CASCADE,
    book_id     TEXT        NOT NULL DEFAULT '',
    title       TEXT        NOT NULL,
    book        JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ
);

COMMENT ON COLUMN memoir_share.token_hash IS '공유 토큰의 sha256. 원본은 발급 응답에 한 번만 나간다';
COMMENT ON COLUMN memoir_share.book_id IS '자녀 기기의 책 id. 같은 책의 공유를 화면이 찾는 데만 쓴다';
COMMENT ON COLUMN memoir_share.book IS
  '공유한 순간의 책 {title, subtitle, draft, made, chapters:[{no, title, paras:[[문장]], draft}]}';

CREATE INDEX IF NOT EXISTS memoir_share_user_idx ON memoir_share (user_id, created_at DESC);

ALTER TABLE memoir_share ENABLE ROW LEVEL SECURITY;
