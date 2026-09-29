-- 005 — 회차의 엽서
--
-- 회차가 끝난 뒤 AI 가 조각에서 문장을 뽑고 그림을 그려 한 장으로 구운 것이다.
-- 바이트는 사진과 같은 PhotoStore 에 들어가고 이 행은 그 키를 가리키는 표지다.
--
-- 001 의 「0번은 엽서」는 이 엽서가 아니다. 그쪽은 회차를 여는 한 줄이고 코드에서는
-- seed(씨앗)라 부른다. 001 은 봉인이라 주석을 고치지 않는다.

CREATE TABLE IF NOT EXISTS postcard (
    -- 회차당 한 장을 스키마가 지킨다. 다시 구우면 이 행을 덮어쓴다.
    session_id   UUID PRIMARY KEY REFERENCES session(session_id) ON DELETE CASCADE,
    user_id      TEXT        NOT NULL,
    text         TEXT        NOT NULL,
    storage_key  TEXT        NOT NULL,
    mime         TEXT        NOT NULL,
    bytes        BIGINT      NOT NULL,
    width        INT         NOT NULL,
    height       INT         NOT NULL,
    -- 그림을 그릴 때 참고로 준 사진. 없으면 글만 보고 그렸다.
    photo_id     UUID,
    -- 어떤 모델이 문장과 그림을 냈나. 결과가 매번 달라서 비교하려면 이게 있어야 한다.
    text_model   TEXT,
    image_model  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS postcard_user_idx ON postcard (user_id, created_at DESC);

COMMENT ON COLUMN postcard.text IS '엽서에 박힌 문장. 이미지 안의 글자와 같다';
COMMENT ON COLUMN postcard.storage_key IS
  '다시 구울 때마다 바뀐다. 같은 키를 덮어쓰면 브라우저 캐시에 옛 엽서가 남는다';
