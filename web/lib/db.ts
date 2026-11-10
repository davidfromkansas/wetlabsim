// The site's database (Neon Postgres, from the Vercel Marketplace: DATABASE_URL). Without it the
// site still works; signed-in users just aren't recorded yet.
import { neon } from "@neondatabase/serverless";

const sql = process.env.DATABASE_URL ? neon(process.env.DATABASE_URL) : null;

export type SiteUser = { id: string; email: string; name: string };

/** Record a signed-in user (Clerk's user id), or refresh their details and last visit. */
export async function upsertUser(u: SiteUser): Promise<void> {
  if (!sql) return;
  await sql`
    insert into users (id, email, name) values (${u.id}, ${u.email}, ${u.name})
    on conflict (id) do update set email = excluded.email, name = excluded.name, last_seen = now()`;
}
