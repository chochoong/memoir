-- 018 — 완성된 자서전의 사진 배치 (사용자가 직접 넣고 · 옮기고 · 뺀 것)
--
-- 자동 배치(memoir.illustrations, memoir_illust_service)는 재처리(--refresh-photos · 삽화 재처리) 때 통째로 다시
-- 적힌다. 사용자가 고른 자리를 거기 섞으면 재처리가 지운다. 그래서 따로 둔다 — 화면에 낼 때 자동 배치 위에 이 표를
-- 먼저 얹는다 (memoir_photos.merged_view). 원고(result)는 여기서도 고치지 않는다 (013 「한 번 만든 결과는 고치지 않는다」).
--
-- 행 두 가지
--   manual  사용자가 넣은 사진. 빼면 행을 지운다 (사진 파일은 지우지 않는다 — 다른 책 · 엽서가 쓸 수 있다).
--   auto    자동으로 놓인 회차 사진을 옮기거나 뺀 기록. placement_id 는 (사진, 회차)로 정해지는 고정값(a_…)이라
--           재처리 뒤에도 같은 사진을 가리킨다. 빼면 hidden = true 로 남긴다 — 지우면 재처리 때 다시 나타난다.

CREATE TABLE IF NOT EXISTS memoir_photo_placement (
    placement_id     TEXT PRIMARY KEY,
    memoir_id        TEXT        NOT NULL REFERENCES memoir (memoir_id) ON DELETE CASCADE,
    user_id          TEXT        NOT NULL REFERENCES app_user (user_id) ON DELETE CASCADE,
    photo_id         UUID        NOT NULL,
    origin           TEXT        NOT NULL CHECK (origin IN ('auto', 'manual')),
    chapter_no       INT,
    after_paragraph  INT,
    display_order    INT         NOT NULL DEFAULT 0,
    hidden           BOOLEAN     NOT NULL DEFAULT false,
    width            INT,
    height           INT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE memoir_photo_placement IS
  '완성된 자서전에서 사용자가 넣은 사진(manual)과 자동 사진을 옮기거나 뺀 기록(auto). 자동 배치보다 먼저 적용한다';
COMMENT ON COLUMN memoir_photo_placement.after_paragraph IS
  '그 장 안 문단 번호(0부터) — 사진이 그 문단 뒤에 온다. result.chapters[].paragraphs 의 순서';
COMMENT ON COLUMN memoir_photo_placement.hidden IS 'auto 행만 — 사용자가 책에서 뺀 자동 사진';

CREATE INDEX IF NOT EXISTS memoir_photo_placement_memoir_idx ON memoir_photo_placement (memoir_id, user_id);

ALTER TABLE memoir_photo_placement ENABLE ROW LEVEL SECURITY;
