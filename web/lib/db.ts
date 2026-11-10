// The site's database (Neon Postgres, from the Vercel Marketplace: DATABASE_URL). Without it the
// site still works; signed-in users just aren't recorded yet.
import { neon } from "@neondatabase/serverless";

const sql = process.env.DATABASE_URL ? neon(process.env.DATABASE_URL) : null;

export type SiteUser = { id: string; email: string; name: string };

/** Record a signed-in user (Clerk's user id), or refresh their details and last visit. */
export async function upsertUser(u: SiteUser): Promise<void> {
  if (!sql) return;
  await sql`
    insert into users (user_id, email, display_name) values (${u.id}, ${u.email}, ${u.name})
    on conflict (user_id) do update set email = excluded.email, display_name = excluded.display_name, last_seen_at = now()`;
}

export type SavedSession = { session_id: string; session_name: string; last_saved_at: string; stations: number; runs: number; shared: boolean };

/** A signed-in user's saved sessions, most recently saved first. */
export async function mySessions(userId: string): Promise<SavedSession[]> {
  if (!sql) return [];
  return (await sql`
    select s.session_id::text, s.session_name, s.last_saved_at,
           coalesce(jsonb_array_length(s.scene_layout->'stations'), 0) as stations,
           (select count(*)::int from runs r where r.session_id = s.session_id) as runs,
           s.share_token is not null as shared
    from sessions s where s.owner_user_id = ${userId} and s.deleted_at is null
    order by s.last_saved_at desc limit 50`) as SavedSession[];
}

/** Hide a session (deleted_at); it can be brought back by clearing it. */
export async function deleteSession(userId: string, sessionId: string): Promise<void> {
  if (!sql) return;
  await sql`update sessions set deleted_at = now() where session_id = ${sessionId}::uuid and owner_user_id = ${userId}`;
}

export type RunRow = {
  run_id: string; session_id: string | null; session_name: string | null; robot_station_id: string | null;
  robot_type: string | null; robot_kit_version: string | null; ai_provider: string | null; ai_model: string | null;
  task_prompt: string | null; run_outcome: string | null; started_at: string | null; ended_at: string | null;
  cost_usd: string | null; blob_folder_path: string | null; files: number; share_token: string | null;
};

/** Your runs, newest first. */
export async function myRuns(userId: string): Promise<RunRow[]> {
  if (!sql) return [];
  return (await sql`
    select r.*, s.session_name, (select count(*)::int from run_files f where f.run_id = r.run_id) as files
    from runs r left join sessions s on s.session_id = r.session_id
    where r.started_by_user_id = ${userId} order by r.started_at desc nulls last limit 200`) as RunRow[];
}

/** One of your runs (null if it isn't yours). */
export async function myRun(userId: string, runId: string): Promise<RunRow | null> {
  if (!sql) return null;
  const rows = (await sql`
    select r.*, s.session_name, (select count(*)::int from run_files f where f.run_id = r.run_id) as files
    from runs r left join sessions s on s.session_id = r.session_id
    where r.run_id = ${runId} and r.started_by_user_id = ${userId}`) as RunRow[];
  return rows[0] ?? null;
}

export type RunFile = { file_path: string; language: string | null; size_bytes: number | null; line_count: number | null; code_text: string | null };

export async function runFiles(runId: string): Promise<RunFile[]> {
  if (!sql) return [];
  return (await sql`select file_path, language, size_bytes, line_count, code_text from run_files where run_id = ${runId} order by file_path`) as RunFile[];
}

/** A shared session, by its share link's token. */
export async function sharedSession(token: string): Promise<{ session_id: string; owner_user_id: string; session_name: string } | null> {
  if (!sql) return null;
  const rows = await sql`select session_id::text, owner_user_id, session_name from sessions where share_token = ${token} and deleted_at is null`;
  return (rows[0] as { session_id: string; owner_user_id: string; session_name: string }) ?? null;
}

/** A shared run, by its share link's token. */
export async function sharedRun(token: string): Promise<{ run_id: string } | null> {
  if (!sql) return null;
  const rows = await sql`select run_id from runs where share_token = ${token}`;
  return (rows[0] as { run_id: string }) ?? null;
}

/** Turn one of your runs' share link on (a new token) or off (null). */
export async function setRunShare(userId: string, runId: string, token: string | null): Promise<boolean> {
  if (!sql) return false;
  const rows = await sql`update runs set share_token = ${token} where run_id = ${runId} and started_by_user_id = ${userId} returning run_id`;
  return rows.length > 0;
}
