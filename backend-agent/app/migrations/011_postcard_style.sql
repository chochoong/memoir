-- 011 — 엽서가 어느 문체로 쓰였는지
--
-- 같은 회차를 다른 문체로 다시 구우면 행을 덮어쓴다 (회차당 한 장). 화면은 지금
-- 보이는 엽서의 문체를 이 값으로만 표시한다 — 요청한 문체로 표시하면, 다시 굽다
-- 실패했을 때 옛 엽서에 새 문체 이름이 붙는다.
--
-- 기본값을 두지 않는다. NULL 은 문체를 고르기 전에 구운 엽서이고, 그때는 구어체
-- 하나뿐이었으므로 읽는 쪽이 spoken 으로 읽는다.

ALTER TABLE postcard ADD COLUMN IF NOT EXISTS style TEXT;

COMMENT ON COLUMN postcard.style IS
  '문체 (spoken · novel · cyworld). NULL 은 011 전에 구운 엽서 = spoken';
