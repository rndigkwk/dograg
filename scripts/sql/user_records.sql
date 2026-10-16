-- Signed-in users' own records (ADR-0008 P4, 2026-10-16): their conversations and their dog's profile.
-- The browser reads and writes these with the user's Supabase JWT; row level security lets each user
-- reach only rows whose user_id is their own auth.uid(). The API (ragdog_app) is not granted them at
-- all: a bug in the app logic cannot leak one user's records to another.
--
-- Applied once with the admin connection (or the Supabase MCP). Checked by scripts/sql/user_records_test.sql.
begin;

-- The dog's profile ("우리 아이 정보"): the same JSON the browser keeps (src/storage/models.py PetProfile).
create table if not exists ragdog_user_profile (
    user_id uuid primary key default auth.uid() references auth.users (id) on delete cascade,
    profile jsonb not null check (jsonb_typeof(profile) = 'object' and pg_column_size(profile) <= 8192),
    updated_at timestamptz not null default now()
);

-- Conversations: one row per thread, its turns as the browser stores them (src/storage/models.py Thread).
create table if not exists ragdog_user_threads (
    user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
    thread_id text not null check (thread_id ~ '^[0-9a-f]{32}$'),
    title text not null check (char_length(title) between 1 and 30),
    turns jsonb not null check (jsonb_typeof(turns) = 'array' and jsonb_array_length(turns) <= 20
                                and pg_column_size(turns) <= 524288),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (user_id, thread_id)
);

-- At most 20 conversations a user, like the browser (MAX_THREADS): a signed-in account cannot fill the database.
create or replace function ragdog_user_threads_limit() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
    if (select count(*) from public.ragdog_user_threads where user_id = new.user_id) >= 20 then
        raise exception 'too many conversations' using errcode = 'check_violation';
    end if;
    return new;
end;
$$;
drop trigger if exists ragdog_user_threads_limit on ragdog_user_threads;
create trigger ragdog_user_threads_limit before insert on ragdog_user_threads
    for each row execute function ragdog_user_threads_limit();

alter table ragdog_user_profile enable row level security;
alter table ragdog_user_threads enable row level security;

-- Supabase grants new public tables to anon and authenticated by default: start from nothing.
revoke all on ragdog_user_profile, ragdog_user_threads from anon, authenticated, public;
grant select, insert, update, delete on ragdog_user_profile, ragdog_user_threads to authenticated;
revoke all on function ragdog_user_threads_limit() from anon, authenticated, public;

-- (select auth.uid()) is evaluated once per statement, not per row (Supabase RLS performance advice).
drop policy if exists own_profile on ragdog_user_profile;
create policy own_profile on ragdog_user_profile for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
drop policy if exists own_threads on ragdog_user_threads;
create policy own_threads on ragdog_user_threads for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

commit;
