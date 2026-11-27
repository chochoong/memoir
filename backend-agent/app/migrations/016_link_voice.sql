-- 016 — 링크로 여는 회차의 낭독 목소리
--
-- 자녀가 링크를 만들 때 목소리를 고르고, 어르신이 「시작」을 누를 때 그 목소리로 회차가 열린다.
-- 링크와 회차 사이에 시간이 있어서 표에 적어 둔다. 값은 app/session/tts.py 의 VOICES 키다.
-- 예전 링크는 default (지금까지의 목소리) 로 읽는다.

ALTER TABLE interview_link ADD COLUMN IF NOT EXISTS voice TEXT NOT NULL DEFAULT 'default';

COMMENT ON COLUMN interview_link.voice IS '질문을 읽는 목소리 (tts.VOICES 의 키 · default 또는 young)';
