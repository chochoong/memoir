-- 017 — 자서전 삽화의 처리 상태
--
-- 자서전이 저장되면 사진이 없는 장마다 삽화를 한 장씩 저절로 만든다 (memoir_illust_service.py).
-- 그 장별 상태(사진 · 삽입 · 실패 · 보류)와 그림의 저장 키를 여기에 둔다.
--
-- result(원고)와 따로 둔다. 원고는 「한 번 만든 결과는 고치지 않는다」(013) 그대로이고, 삽화가 실패하거나
-- 다시 처리돼도 원고는 바뀌지 않는다. 그림 바이트는 사진과 같은 저장소(photo_blob · photostore)에 든다.
-- NULL 은 「아직 처리하지 않았다」(이 열이 생기기 전의 책 · 삽화가 꺼진 서버에서 만든 책)다.

ALTER TABLE memoir ADD COLUMN IF NOT EXISTS illustrations JSONB;

COMMENT ON COLUMN memoir.illustrations IS
  '삽화 처리 상태 (memoir-illust-service-v1) — 장별 사진 · 삽화 · 실패, 그림 저장 키. 자동 처리이며 사람이 확인한 것이 아니다';
