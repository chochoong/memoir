-- 013 — 만든 자서전
--
-- 자서전은 만들 때마다 모델이 새로 쓰고, 예전에는 서버 메모리에만 30분 두었다
-- (7-C1 §4). 그러면 책은 만든 기기(브라우저)에만 남아 다른 기기에서 보이지 않고,
-- 서버를 다시 켜면 만들던 결과도 사라진다. 이제 다 쓴 자서전은 이 표에 남는다.
--
-- 한 번 만든 결과는 고치지 않는다. 다시 만들면 새 행이다 — 같은 회차로 만들어도
-- 결과가 매번 달라서, 어느 것을 골랐는지 화면이 고를 수 있어야 한다.
-- 지우면 deleted_at 만 적는다 (목록 · 읽기에서 빠진다).

CREATE TABLE IF NOT EXISTS memoir (
    memoir_id    TEXT PRIMARY KEY,
    user_id      TEXT        NOT NULL REFERENCES app_user (user_id) ON DELETE CASCADE,
    elder_id     TEXT,
    session_ids  UUID[]      NOT NULL,
    style        TEXT        NOT NULL DEFAULT '',
    engine       TEXT        NOT NULL DEFAULT '',
    status       TEXT        NOT NULL DEFAULT '',
    title        TEXT        NOT NULL DEFAULT '',
    result       JSONB       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);

COMMENT ON COLUMN memoir.elder_id IS '쓴 회차들의 화자. 회차에 화자가 없으면 NULL';
COMMENT ON COLUMN memoir.result IS
  '자서전 응답 그대로 (GET /api/memoirs/{job_id} 의 result · 7-C1 §3)';
COMMENT ON COLUMN memoir.status IS 'result.status (ready · needs_confirmation · insufficient_material …)';

CREATE INDEX IF NOT EXISTS memoir_user_idx ON memoir (user_id, created_at DESC);

ALTER TABLE memoir ENABLE ROW LEVEL SECURITY;
