-- The site's database. Apply with `npm run db:migrate` (safe to run again: every step checks first).
-- Statements are separated by a line holding only ";".

-- One row per person who has signed in (user_id: Clerk's user id).
create table if not exists users (
  user_id      text primary key,
  email        text not null,
  display_name text not null default '',
  signed_up_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now()
)
;
-- (The first version of this table used id / name / created_at / last_seen.)
do $$ begin
  if exists (select 1 from information_schema.columns where table_schema = current_schema() and table_name = 'users' and column_name = 'id') then
    alter table users rename column id to user_id;
    alter table users rename column name to display_name;
    alter table users rename column created_at to signed_up_at;
    alter table users rename column last_seen to last_seen_at;
  end if;
end $$
;
-- A saved lab: its stations and objects, and each station's unsent task and model.
create table if not exists sessions (
  session_id     uuid primary key,
  owner_user_id  text not null references users (user_id),
  session_name   text not null default 'Untitled lab',
  scene_layout   jsonb not null default '{}',
  unsent_tasks   jsonb not null default '{}',
  save_version   integer not null default 1,
  created_at     timestamptz not null default now(),
  last_saved_at  timestamptz not null default now(),
  last_opened_at timestamptz not null default now(),
  deleted_at     timestamptz
)
;
create index if not exists sessions_owner on sessions (owner_user_id, last_saved_at desc)
;
-- One AI task on one robot. robot_type and robot_kit_version name the starter kit (3D model,
-- manuals) the AI was given; the kit lives in the code, never per run. A station's chat is its
-- runs in order.
create table if not exists runs (
  run_id             text primary key,
  session_id         uuid references sessions (session_id),
  robot_station_id   text,
  robot_type         text,
  robot_kit_version  text,
  started_by_user_id text references users (user_id),
  ai_provider        text,
  ai_model           text,
  task_prompt        text,
  run_outcome        text,
  started_at         timestamptz,
  ended_at           timestamptz,
  cost_usd           numeric,
  blob_folder_path   text
)
;
create index if not exists runs_session on runs (session_id, started_at)
;
create index if not exists runs_user on runs (started_by_user_id, started_at desc)
;
-- One row per file the AI wrote or changed, so code can be searched across runs.
create table if not exists run_files (
  file_id        bigserial primary key,
  run_id         text not null references runs (run_id) on delete cascade,
  file_path      text not null,
  language       text,
  size_bytes     integer,
  line_count     integer,
  code_text      text,
  blob_file_path text
)
;
create index if not exists run_files_run on run_files (run_id)
;
-- Share links the owner turns on (view only): a random token, empty when sharing is off.
alter table sessions add column if not exists share_token text unique
;
alter table runs add column if not exists share_token text unique
