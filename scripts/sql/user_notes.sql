-- "지난 상담 기억" (ADR-0009, 2026-10-17): a signed-in guardian's consultation notes. A note is made
-- only when the guardian clicks "이 상담 기억하기" and saves it; with the setting on, the browser sends
-- the latest five with a question. Same rules as ragdog_user_threads (scripts/sql/user_records.sql):
-- the browser reads and writes them with the user's JWT, row level security allows only the user's own
-- rows, and the API role (ragdog_app) has no grant. Deleting the account deletes the notes (cascade).
--
-- Applied once with the admin connection. Checked by scripts/sql/user_notes_test.sql
-- (uv run python scripts/check_user_records.py).
begin;

create table if not exists ragdog_user_notes (
    user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
    note_id uuid not null default gen_random_uuid(),
    note text not null check (char_length(btrim(note)) between 1 and 300),
    thread_id text check (thread_id is null or thread_id ~ '^[0-9a-f]{32}$'),
    created_at timestamptz not null default now(),
    primary key (user_id, note_id)
);
create index if not exists ragdog_user_notes_recent on ragdog_user_notes (user_id, created_at desc);

-- At most 30 notes a user (ADR-0009): an account cannot fill the database.
create or replace function ragdog_user_notes_limit() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
    if (select count(*) from public.ragdog_user_notes where user_id = new.user_id) >= 30 then
        raise exception 'too many notes' using errcode = 'check_violation';
    end if;
    return new;
end;
$$;
drop trigger if exists ragdog_user_notes_limit on ragdog_user_notes;
create trigger ragdog_user_notes_limit before insert on ragdog_user_notes
    for each row execute function ragdog_user_notes_limit();

alter table ragdog_user_notes enable row level security;
revoke all on ragdog_user_notes from anon, authenticated, public;
grant select, insert, update, delete on ragdog_user_notes to authenticated;
revoke all on function ragdog_user_notes_limit() from anon, authenticated, public;

drop policy if exists own_notes on ragdog_user_notes;
create policy own_notes on ragdog_user_notes for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

commit;
