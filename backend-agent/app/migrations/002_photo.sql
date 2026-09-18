-- 002 — 사진의 소유자와 바이트
--
-- 두 가지를 더한다.
--
-- 1. photo.user_id
--    photo 에는 주인이 없었다. session_id 는 NULL 을 허용하고(회차를 열기 전에
--    사진을 고를 수 있다) 그런 행은 조인으로도 주인을 찾을 수 없다. 사진은
--    얼굴이다. 주인을 모르는 채로는 내보낼 수 없어서, 소유자 검사가 성립하려면
--    이 열이 먼저 있어야 한다.
--
-- 2. photo_blob
--    바이트를 Postgres 에 넣는다. 001 의 photo 주석은 「바이트는 여기 넣지
--    않는다」였고 **그건 지금도 맞다** — 바이트는 photo 가 아니라 photo_blob 에
--    들어간다. photo 행이 커지면 목록을 훑는 모든 쿼리가 같이 느려진다.
--
--    photo_blob 은 photo 를 **참조하지 않는다.** 일부러다. 이 표는 오브젝트
--    스토리지를 흉내 낸 것이고 (키 → 바이트), 오브젝트 스토리지에는 외래 키가
--    없다. FK 를 걸면 PgStore 만 진짜 스토리지와 다르게 행동하게 되어, 나중에
--    Blob 으로 옮길 때 그 차이가 전부 버그로 나타난다. 대신 지우는 쪽에서
--    두 번 지운다 — 실제 스토리지에서도 그렇게 해야 한다.

ALTER TABLE photo ADD COLUMN IF NOT EXISTS user_id TEXT;

-- 기존 행은 회차의 주인을 물려받는다. 회차조차 없으면 지운다 —
-- 주인 없는 사진은 소유자 검사를 통과할 길이 없어 영원히 읽히지 않는다.
-- 남겨 두는 것은 「용량을 쓰면서 아무 쓸모도 없는 얼굴 사진」을 남기는 일이다.
UPDATE photo p
   SET user_id = s.user_id
  FROM session s
 WHERE p.session_id = s.session_id
   AND p.user_id IS NULL;

DELETE FROM photo WHERE user_id IS NULL;

ALTER TABLE photo ALTER COLUMN user_id SET NOT NULL;

-- 내 사진 목록 · 회차에 붙은 사진.
CREATE INDEX IF NOT EXISTS photo_user_idx    ON photo (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS photo_session_idx ON photo (session_id);

COMMENT ON COLUMN photo.storage_key IS
  '화면용(view) 변형이 저장된 키. 오브젝트 스토리지 규칙으로 항상 / 구분이다';
COMMENT ON COLUMN photo.bytes IS '저장한 화면용 바이트 수 (원본 크기가 아니다)';
COMMENT ON COLUMN photo.sha256 IS
  '올려받은 원본의 해시. 같은 사진을 두 번 올리면 같은 값이 된다';

-- 키 → 바이트. 이것이 PhotoStore 의 pg 구현이 쓰는 표다.
CREATE TABLE IF NOT EXISTS photo_blob (
    storage_key TEXT PRIMARY KEY,
    mime        TEXT        NOT NULL,
    bytes       BYTEA       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- **압축을 끈다.** JPEG 은 이미 압축돼 있어서 TOAST 가 한 번 더 압축해도 거의
-- 줄지 않는데, 넣고 꺼낼 때마다 그 CPU 를 쓴다. 이벤트 루프 하나로 모든 회차의
-- T1·T2 를 도는 서버에서 그건 지연이 된다.
ALTER TABLE photo_blob ALTER COLUMN bytes SET STORAGE EXTERNAL;
