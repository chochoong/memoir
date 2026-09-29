-- 007 — 마지막 말씀을 듣고 낸 판단
--
-- turn.decision 은 그 턴의 질문을 만든 판단, 곧 **앞 턴의** 말씀을 듣고 낸 판단이다.
-- 그래서 마지막 말씀의 판단은 들어갈 턴 행이 없다. 회차가 닫힐 때 여기 남긴다.
-- 엽서는 이것을 마지막 말씀에서 찾은 사실로 쓴다.

ALTER TABLE session ADD COLUMN IF NOT EXISTS closing_decision JSONB;

COMMENT ON COLUMN session.closing_decision IS
  '마지막 턴의 말씀을 듣고 낸 판단 (turn.decision 과 같은 모양). 말씀이 없던 회차는 NULL';
