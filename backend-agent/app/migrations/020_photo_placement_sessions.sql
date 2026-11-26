-- 020 — 자동 사진 배치 기록에 회차를 적는다 (018 보완, 2026-11-26 검토)
--
-- 018 의 자동 사진 id 는 (사진, 회차 묶음의 첫 회차)였다. 두 가지가 틀렸다.
--   ① 책이 빠져 같은 인터뷰로 만든 두 책이 같은 id 를 써서, 두 번째 책의 이동 · 빼기가 404 로 거절됐다
--   ② 회차 묶음이 [A, B] → [B] 로 바뀌면 id 가 바뀌어 뺀 사진이 다시 나타났다
-- 이제 id 는 (책, 사진, 처음 회차)이고, 기록이 그 사진의 회차를 지닌다 — 묶음이 바뀌어도 회차가 이어지면 같은 사진으로 본다
-- (memoir_photos.match_auto). 첫 판 id 로 저장된 기록은 지우지 않는다 — 회차가 비어 있으면 첫 판 규칙으로 찾는다.

ALTER TABLE memoir_photo_placement ADD COLUMN IF NOT EXISTS sessions TEXT[];
ALTER TABLE memoir_photo_placement ADD COLUMN IF NOT EXISTS anchor_session TEXT;

COMMENT ON COLUMN memoir_photo_placement.sessions IS 'auto 행 — 그 자동 사진이 이어진 회차들 (마지막으로 저장할 때)';
COMMENT ON COLUMN memoir_photo_placement.anchor_session IS 'auto 행 — 기록을 처음 만들 때의 회차. 바뀌지 않는다';
