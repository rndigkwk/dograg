-- The deployments' database role (2026-10-15): read and write what the app uses, nothing else.
-- The role itself is created by a person in the Supabase SQL editor with a password of their own:
--     create role ragdog_app login password '...';
-- then this file is applied with the admin connection. The app's tables have row level security on
-- (src/supabase_store.lock_from_data_api); these policies let ragdog_app through, only for what it is
-- granted. anon and authenticated stay without access (the public REST API).
begin;
grant usage on schema public to ragdog_app;

grant select on ragdog_health, ragdog_report to ragdog_app;
create policy ragdog_app_read on ragdog_health for select to ragdog_app using (true);
create policy ragdog_app_read on ragdog_report for select to ragdog_app using (true);

grant insert on ragdog_data_gaps, ragdog_feedback, ragdog_eval_history to ragdog_app;
create policy ragdog_app_insert on ragdog_data_gaps for insert to ragdog_app with check (true);
create policy ragdog_app_insert on ragdog_feedback for insert to ragdog_app with check (true);
create policy ragdog_app_insert on ragdog_eval_history for insert to ragdog_app with check (true);

grant select, insert, delete on ragdog_rate_limit to ragdog_app;
create policy ragdog_app_read on ragdog_rate_limit for select to ragdog_app using (true);
create policy ragdog_app_insert on ragdog_rate_limit for insert to ragdog_app with check (true);
create policy ragdog_app_delete on ragdog_rate_limit for delete to ragdog_app using (true);

grant usage on sequence ragdog_data_gaps_id_seq, ragdog_feedback_id_seq, ragdog_eval_history_id_seq,
    ragdog_rate_limit_id_seq to ragdog_app;
commit;
