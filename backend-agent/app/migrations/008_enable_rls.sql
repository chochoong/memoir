-- 008 — 모든 표에 RLS 를 켠다
--
-- Supabase 는 public 스키마를 Data API(REST)로 내놓는다. RLS 가 꺼진 표는 공개
-- 키(anon)만 있으면 누구나 읽고 쓴다 — app_user, login_session 까지. Data API 는
-- 대시보드에서 꺼 두었지만, 누가 다시 켜는 날을 위해 표 쪽에서도 닫는다.
--
-- 정책은 하나도 두지 않는다. 그러면 anon / authenticated 는 아무것도 못 본다.
-- 백엔드는 표의 소유자(postgres, 로컬은 memoir)로 붙고 소유자는 RLS 를 지나치니
-- 앱은 그대로 돈다. FORCE 를 붙이면 그 길까지 막히므로 붙이지 않는다.
--
-- **이 파일은 지금 있는 표만 닫는다.** 앞으로 CREATE TABLE 하는 마이그레이션은
-- 같은 파일 안에서 ENABLE ROW LEVEL SECURITY 를 함께 건다.

DO $$
DECLARE
    t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    END LOOP;
END
$$;
