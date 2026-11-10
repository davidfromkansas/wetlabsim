-- One row per person who has signed in (id: Clerk's user id).
create table if not exists users (
  id         text primary key,
  email      text not null,
  name       text not null default '',
  created_at timestamptz not null default now(),
  last_seen  timestamptz not null default now()
);
