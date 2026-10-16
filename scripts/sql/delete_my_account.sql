-- "계정 삭제" (2026-10-16): a signed-in user deletes their own account, with no admin key anywhere.
-- The function runs as its owner (security definer) but can only ever touch the caller: the row of
-- auth.users whose id is the caller's auth.uid(). Deleting it cascades to their sessions, sign-in
-- identities and refresh tokens (auth schema) and to ragdog_user_threads / ragdog_user_profile
-- (scripts/sql/user_records.sql, on delete cascade). Only `authenticated` may call it.
-- Applied once with the admin connection; checked by scripts/sql/delete_my_account_test.sql.
begin;

create or replace function public.delete_my_account() returns boolean
language plpgsql security definer set search_path = '' as $$
declare
    me uuid := auth.uid();
begin
    if me is null then
        raise exception 'not signed in' using errcode = 'insufficient_privilege';
    end if;
    delete from auth.users where id = me;
    return found;
end;
$$;

revoke all on function public.delete_my_account() from public, anon, authenticated;
grant execute on function public.delete_my_account() to authenticated;

commit;
