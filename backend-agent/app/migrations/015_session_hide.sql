-- 015 — 회차 숨기기 (엽서 지우기)
--
-- 자녀가 보관함에서 엽서를 지우면 그 회차를 통째로 숨긴다. 행 · 조각 · 사진 · 엽서는
-- 지우지 않는다 — 실수로 지웠을 때 deleted_at 을 비우면 그대로 돌아온다.
-- 숨긴 회차는 목록 · 자서전 고르기 · 자서전 「전부」 · 엽서 · 기록 보기에 나오지 않는다.

ALTER TABLE session ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

COMMENT ON COLUMN session.deleted_at IS '자녀가 지운 때. NULL 이 아니면 어디에도 보이지 않는다';
