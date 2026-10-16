-- Checks for scripts/sql/delete_my_account.sql, in one transaction that is rolled back: two fake
-- users with records; A deletes their account; B and B's records must be untouched.
begin;

insert into auth.users (id, aud, role, email) values
    ('00000000-0000-4000-8000-0000000000d1', 'authenticated', 'authenticated', 'del-a@example.test'),
    ('00000000-0000-4000-8000-0000000000d2', 'authenticated', 'authenticated', 'del-b@example.test');
insert into auth.identities (provider_id, user_id, identity_data, provider, created_at, updated_at) values
    ('del-a', '00000000-0000-4000-8000-0000000000d1', '{}', 'google', now(), now());
insert into ragdog_user_threads (user_id, thread_id, title, turns) values
    ('00000000-0000-4000-8000-0000000000d1', repeat('1', 32), 'A의 대화', '[]'),
    ('00000000-0000-4000-8000-0000000000d2', repeat('2', 32), 'B의 대화', '[]');
insert into ragdog_user_profile (user_id, profile) values
    ('00000000-0000-4000-8000-0000000000d1', '{"name":"A"}'),
    ('00000000-0000-4000-8000-0000000000d2', '{"name":"B"}');

create temporary table results (name text, ok boolean) on commit drop;
grant insert on results to authenticated, anon;

-- anon (signed out) cannot call it.
set local role anon;
do $$ begin
    perform public.delete_my_account();
    insert into results values ('anon cannot call', false);
exception when insufficient_privilege then
    insert into results values ('anon cannot call', true);
end $$;
reset role;

-- A deletes their own account.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-8000-0000000000d1","role":"authenticated"}', true);
insert into results select 'A deleted', public.delete_my_account();
reset role;

insert into results select 'A account gone', not exists (select 1 from auth.users where id = '00000000-0000-4000-8000-0000000000d1');
insert into results select 'A identity gone', not exists (select 1 from auth.identities where user_id = '00000000-0000-4000-8000-0000000000d1');
insert into results select 'A records gone', not exists (select 1 from ragdog_user_threads where user_id = '00000000-0000-4000-8000-0000000000d1')
                                       and not exists (select 1 from ragdog_user_profile where user_id = '00000000-0000-4000-8000-0000000000d1');
insert into results select 'B untouched', exists (select 1 from auth.users where id = '00000000-0000-4000-8000-0000000000d2')
                                    and exists (select 1 from ragdog_user_threads where user_id = '00000000-0000-4000-8000-0000000000d2')
                                    and exists (select 1 from ragdog_user_profile where user_id = '00000000-0000-4000-8000-0000000000d2');

-- A token without a user (no sub) deletes nothing.
set local role authenticated;
select set_config('request.jwt.claims', '{"role":"authenticated"}', true);
do $$ begin
    perform public.delete_my_account();
    insert into results values ('no user id refused', false);
exception when insufficient_privilege then
    insert into results values ('no user id refused', true);
end $$;
reset role;

-- The app's own role (the API) cannot call it.
do $$ begin
    if exists (select 1 from pg_roles where rolname = 'ragdog_app') then
        insert into results select 'ragdog_app cannot call', not has_function_privilege('ragdog_app', 'public.delete_my_account()', 'execute');
    end if;
end $$;

select case when bool_and(ok) then 'all passed' else 'FAILED: ' || string_agg(name, ', ') filter (where not ok) end as result,
       count(*) as checks
from results;

rollback;
