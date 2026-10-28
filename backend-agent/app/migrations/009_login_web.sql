-- 009 — 자녀 로그인은 화자 없이도 선다
--
-- 003 은 login_session 마다 elder_id 를 요구했다. 그런데 자녀의 첫 로그인은 화자를
-- 만들기 **전에** 일어난다 — 화자는 로그인한 자녀가 직접 만든다. 그대로 두면 첫
-- 로그인을 기록할 수 없다.
--
-- 화자가 꼭 있어야 하는 것은 어르신 기기에 물려 두는 device 세션뿐이다. 그 뜻은
-- CHECK 로 남긴다.

ALTER TABLE login_session ALTER COLUMN elder_id DROP NOT NULL;

ALTER TABLE login_session
    ADD CONSTRAINT login_session_device_needs_elder
    CHECK (kind <> 'device' OR elder_id IS NOT NULL);
