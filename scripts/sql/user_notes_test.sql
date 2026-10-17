-- Row level security check for scripts/sql/user_notes.sql (same pattern as user_records_test.sql):
-- two fake users in one rolled-back transaction, each acting as `authenticated` with its own claims.
begin;

insert into auth.users (id, aud, role, email) values
    ('00000000-0000-4000-8000-00000000000a', 'authenticated', 'authenticated', 'notes-a@example.test'),
    ('00000000-0000-4000-8000-00000000000b', 'authenticated', 'authenticated', 'notes-b@example.test');

create temporary table results (name text, ok boolean) on commit drop;
grant insert on results to authenticated, anon;

set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-8000-00000000000a","role":"authenticated"}', true);
insert into ragdog_user_notes (note, thread_id) values ('10/10 설사 이틀째, 이틀 넘으면 병원 안내', repeat('a', 32));
insert into results select 'A sees its own note', (select count(*) from ragdog_user_notes) = 1;

do $$ begin
    insert into ragdog_user_notes (user_id, note) values ('00000000-0000-4000-8000-00000000000b', 'x');
    insert into results values ('A cannot write as B', false);
exception when insufficient_privilege then
    insert into results values ('A cannot write as B', true);
end $$;

select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-8000-00000000000b","role":"authenticated"}', true);
insert into results select 'B sees none of A''s notes', (select count(*) from ragdog_user_notes) = 0;
with changed as (update ragdog_user_notes set note = 'hacked' returning 1) insert into results select 'B updates nothing', count(*) = 0 from changed;
with gone as (delete from ragdog_user_notes returning 1) insert into results select 'B deletes nothing', count(*) = 0 from gone;

select set_config('request.jwt.claims', '{"sub":"00000000-0000-4000-8000-00000000000a","role":"authenticated"}', true);
do $$ begin
    update ragdog_user_notes set user_id = '00000000-0000-4000-8000-00000000000b';
    insert into results values ('A cannot hand a note to B', false);
exception when insufficient_privilege then
    insert into results values ('A cannot hand a note to B', true);
end $$;

-- Limits: length, blank, thread id shape, 30 notes.
do $$ begin
    insert into ragdog_user_notes (note) values (repeat('가', 301));
    insert into results values ('a note over 300 characters refused', false);
exception when check_violation then
    insert into results values ('a note over 300 characters refused', true);
end $$;
do $$ begin
    insert into ragdog_user_notes (note) values ('   ');
    insert into results values ('a blank note refused', false);
exception when check_violation then
    insert into results values ('a blank note refused', true);
end $$;
do $$ begin
    insert into ragdog_user_notes (note, thread_id) values ('x', '../etc');
    insert into results values ('bad thread id refused', false);
exception when check_violation then
    insert into results values ('bad thread id refused', true);
end $$;
do $$ begin
    insert into ragdog_user_notes (note) select 'n' || n from generate_series(1, 30) as n;
    insert into results values ('31st note refused', false);
exception when check_violation then
    insert into results values ('31st note refused', true);
end $$;

-- Deleting the account deletes the notes (on delete cascade).
reset role;
delete from auth.users where id = '00000000-0000-4000-8000-00000000000a';
insert into results select 'notes go with the account',
    not exists (select 1 from ragdog_user_notes where user_id = '00000000-0000-4000-8000-00000000000a');

set local role anon;
do $$ begin
    perform count(*) from ragdog_user_notes;
    insert into results values ('anon cannot read', false);
exception when insufficient_privilege then
    insert into results values ('anon cannot read', true);
end $$;
reset role;

do $$ begin
    if exists (select 1 from pg_roles where rolname = 'ragdog_app') then
        insert into results select 'ragdog_app has no grant', not has_table_privilege('ragdog_app', 'ragdog_user_notes', 'select');
    end if;
end $$;

select case when bool_and(ok) then 'all passed' else 'FAILED: ' || string_agg(name, ', ') filter (where not ok) end as result,
       count(*) as checks
from results;

rollback;
