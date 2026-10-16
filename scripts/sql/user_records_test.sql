-- Row level security check for scripts/sql/user_records.sql. Runs in one transaction and rolls back:
-- two fake users are made in auth.users, then each acts as the `authenticated` role with its own JWT
-- claims (as PostgREST does). Every check raises on failure; the last line returns 'all passed'.
begin;

insert into auth.users (id, aud, role, email) values
    ('00000000-0000-4000-8000-00000000000a', 'authenticated', 'authenticated', 'rls-a@example.test'),
    ('00000000-0000-4000-8000-00000000000b', 'authenticated', 'authenticated', 'rls-b@example.test');

create temporary table results (name text, ok boolean) on commit drop;
grant insert on results to authenticated, anon;

-- User A writes a profile and a conversation.
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-8000-00000000000a","role":"authenticated"}', true);
insert into ragdog_user_profile (profile) values ('{"name":"두부"}');
insert into ragdog_user_threads (thread_id, title, turns) values (repeat('a', 32), '구토', '[{"question":"q","answer":"a"}]');
insert into results select 'A sees its own rows', (select count(*) from ragdog_user_threads) = 1 and (select count(*) from ragdog_user_profile) = 1;

-- A cannot write a row in B's name.
do $$ begin
    insert into ragdog_user_threads (user_id, thread_id, title, turns)
        values ('00000000-0000-4000-8000-00000000000b', repeat('b', 32), 'x', '[]');
    insert into results values ('A cannot write as B', false);
exception when insufficient_privilege then
    insert into results values ('A cannot write as B', true);
end $$;

-- User B sees, changes and deletes nothing of A's.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-8000-00000000000b","role":"authenticated"}', true);
insert into results select 'B sees none of A''s threads', (select count(*) from ragdog_user_threads) = 0;
insert into results select 'B sees none of A''s profile', (select count(*) from ragdog_user_profile) = 0;
with changed as (update ragdog_user_threads set title = 'hacked' returning 1) insert into results select 'B updates nothing', count(*) = 0 from changed;
with gone as (delete from ragdog_user_profile returning 1) insert into results select 'B deletes nothing', count(*) = 0 from gone;

-- A cannot move a row to B (with check on update).
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-8000-00000000000a","role":"authenticated"}', true);
do $$ begin
    update ragdog_user_threads set user_id = '00000000-0000-4000-8000-00000000000b';
    insert into results values ('A cannot hand a row to B', false);
exception when insufficient_privilege then
    insert into results values ('A cannot hand a row to B', true);
end $$;

-- Limits: thread id shape, size, 20 conversations.
do $$ begin
    insert into ragdog_user_threads (thread_id, title, turns) values ('../etc', 'x', '[]');
    insert into results values ('bad thread id refused', false);
exception when check_violation then
    insert into results values ('bad thread id refused', true);
end $$;
do $$ begin
    insert into ragdog_user_threads (thread_id, title, turns)
        select lpad(to_hex(n), 32, 'c'), 't', '[]' from generate_series(1, 20) as n;
    insert into results values ('21st conversation refused', false);
exception when check_violation then
    insert into results values ('21st conversation refused', true);
end $$;

-- anon (no sign-in) can neither read nor write.
reset role;
set local role anon;
do $$ begin
    perform count(*) from ragdog_user_threads;
    insert into results values ('anon cannot read', false);
exception when insufficient_privilege then
    insert into results values ('anon cannot read', true);
end $$;
reset role;

-- The app's own role (the API) has no access either.
do $$ begin
    if exists (select 1 from pg_roles where rolname = 'ragdog_app') then
        insert into results select 'ragdog_app has no grant',
            not has_table_privilege('ragdog_app', 'ragdog_user_threads', 'select')
            and not has_table_privilege('ragdog_app', 'ragdog_user_profile', 'select');
    end if;
end $$;

select case when bool_and(ok) then 'all passed' else 'FAILED: ' || string_agg(name, ', ') filter (where not ok) end as result,
       count(*) as checks
from results;

rollback;
