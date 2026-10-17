-- Retention (2026-10-17, owner's decision): consented 👎 conversations (ragdog_feedback) and "자료에 없던
-- 내용" sentences (ragdog_data_gaps) are kept for 3 years, then deleted. Both are masked text from
-- consultations (docs/security/README.md).
--
-- The app's role (ragdog_app) may only insert into these tables. Instead of granting it delete, this
-- function deletes rows older than 3 years and nothing else: it takes no input, so a caller cannot
-- point it at newer rows or other tables. The app calls it at most once a day per instance
-- (src/supabase_store.expire_old_rows). Applied once with the admin connection; checked by
-- scripts/sql/retention_test.sql (uv run python scripts/check_user_records.py).
begin;

create or replace function public.ragdog_expire_old_rows() returns integer
language plpgsql security definer set search_path = '' as $$
declare
    gone integer := 0;
    n integer;
begin
    delete from public.ragdog_feedback where created_at < now() - interval '3 years';
    get diagnostics n = row_count;
    gone := gone + n;
    delete from public.ragdog_data_gaps where created_at < now() - interval '3 years';
    get diagnostics n = row_count;
    return gone + n;
end;
$$;

revoke all on function public.ragdog_expire_old_rows() from public, anon, authenticated;
grant execute on function public.ragdog_expire_old_rows() to ragdog_app;

commit;
