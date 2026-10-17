-- Check for scripts/sql/retention.sql in one rolled-back transaction: old rows go, recent ones stay,
-- and only the app's role may call the function.
begin;

create temporary table results (name text, ok boolean) on commit drop;

insert into ragdog_feedback (created_at, route, question, answer) values
    (now() - interval '3 years 1 day', 'rag', 'retention-test old', 'a'),
    (now() - interval '2 years 364 days', 'rag', 'retention-test recent', 'a');
insert into ragdog_data_gaps (created_at, route, kind, sentence) values
    (now() - interval '3 years 1 day', 'rag', 'missing', 'retention-test old'),
    (now() - interval '1 day', 'rag', 'missing', 'retention-test recent');

insert into results select 'two old rows deleted', public.ragdog_expire_old_rows() >= 2;
insert into results select 'old feedback gone', not exists (select 1 from ragdog_feedback where question = 'retention-test old');
insert into results select 'recent feedback kept', exists (select 1 from ragdog_feedback where question = 'retention-test recent');
insert into results select 'old gap gone', not exists (select 1 from ragdog_data_gaps where sentence = 'retention-test old');
insert into results select 'recent gap kept', exists (select 1 from ragdog_data_gaps where sentence = 'retention-test recent');

insert into results select 'anon cannot call', not has_function_privilege('anon', 'public.ragdog_expire_old_rows()', 'execute');
insert into results select 'authenticated cannot call', not has_function_privilege('authenticated', 'public.ragdog_expire_old_rows()', 'execute');
do $$ begin
    if exists (select 1 from pg_roles where rolname = 'ragdog_app') then
        insert into results select 'ragdog_app may call', has_function_privilege('ragdog_app', 'public.ragdog_expire_old_rows()', 'execute');
        insert into results select 'ragdog_app still cannot delete directly',
            not has_table_privilege('ragdog_app', 'ragdog_feedback', 'delete')
            and not has_table_privilege('ragdog_app', 'ragdog_data_gaps', 'delete');
    end if;
end $$;

select case when bool_and(ok) then 'all passed' else 'FAILED: ' || string_agg(name, ', ') filter (where not ok) end as result,
       count(*) as checks
from results;

rollback;
