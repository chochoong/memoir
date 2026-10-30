-- 012 — 어르신이 링크에서 고른 낱말
--
-- 링크를 열고 「시작」 을 누르면 화면이 낱말 카드를 보여 주고, 어르신이 고른 낱말로
-- 회차를 연다 (app/session/words.py 의 허용 목록 · 링크의 구체 주제). topic 은 자녀가
-- 적은 그대로 두고 고른 낱말은 따로 남긴다 — 자녀 화면이 「무엇을 보냈고 무엇을
-- 고르셨는지」 둘 다 보여 줄 수 있게.
--
-- NULL 은 고르지 않고 시작한 링크다 (012 전 링크 · 낱말 화면을 끈 화면). 그때 회차의
-- 주제는 topic 이다.

ALTER TABLE interview_link ADD COLUMN IF NOT EXISTS picked_topic TEXT;

COMMENT ON COLUMN interview_link.picked_topic IS
  '어르신이 시작할 때 고른 낱말. NULL 이면 topic 으로 열었다';
