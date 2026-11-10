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

export type SavedSession = { session_id: string; session_name: string; last_saved_at: string; stations: number; runs: number };

/** A signed-in user's saved sessions, most recently saved first. */
export async function mySessions(userId: string): Promise<SavedSession[]> {
  if (!sql) return [];
  return (await sql`
    select s.session_id::text, s.session_name, s.last_saved_at,
           coalesce(jsonb_array_length(s.scene_layout->'stations'), 0) as stations,
           (select count(*)::int from runs r where r.session_id = s.session_id) as runs
    from sessions s where s.owner_user_id = ${userId} and s.deleted_at is null
    order by s.last_saved_at desc limit 50`) as SavedSession[];
}

/** Hide a session (deleted_at); it can be brought back by clearing it. */
export async function deleteSession(userId: string, sessionId: string): Promise<void> {
  if (!sql) return;
  await sql`update sessions set deleted_at = now() where session_id = ${sessionId}::uuid and owner_user_id = ${userId}`;
}
