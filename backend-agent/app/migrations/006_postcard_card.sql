-- 006 — 엽서가 카드 작성 에이전트(CardAgent v3)의 결과를 담는다
--
-- 005 의 엽서는 문장 한 줄과 AI 그림이었다. v3 는 제목 · 본문 · 사진 설명을 따로
-- 내고, 본문 문장마다 어느 턴의 말씀에서 왔는지(sources)를 붙인다. 그림은 그리지
-- 않고 회차 사진을 그대로 쓴다.
--
-- text 는 그대로 본문이다. 이미지 안의 본문과 글자까지 같다.

ALTER TABLE postcard ADD COLUMN IF NOT EXISTS title   TEXT;
ALTER TABLE postcard ADD COLUMN IF NOT EXISTS caption TEXT;
ALTER TABLE postcard ADD COLUMN IF NOT EXISTS sources JSONB;

COMMENT ON COLUMN postcard.sources IS
  '본문 문장별 근거 [{"sentence": 0, "turns": [2, 3]}]. turns 는 turn.idx 다';
COMMENT ON COLUMN postcard.image_model IS
  '005 의 AI 그림을 그린 모델. 006 부터는 그리지 않으므로 NULL 이다';
