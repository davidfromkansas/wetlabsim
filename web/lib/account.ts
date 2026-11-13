// General settings, per person: their run time limit and their own AI keys (OpenAI, Anthropic,
// Devin, Jev). Keys are encrypted here (AES-256-GCM) with API_KEYS_ENCRYPTION_KEY, a Vercel
// setting that is never stored in the database, so the database alone can't reveal a key. Only
// the lab asks for a whole key (with LAB_LINK_SECRET), for the run that needs it; everyone else
// only ever sees the last 4 letters. The lab checks each key with its company before saving it.
// OpenAI can instead hold a ChatGPT sign-in (kind "chatgpt"): the Codex CLI's own login file
// (auth.json, from Codex's device code sign-in on the lab), encrypted the same way. Only its
// email is ever shown.
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { neon } from "@neondatabase/serverless";

const sql = process.env.DATABASE_URL ? neon(process.env.DATABASE_URL) : null;

export const PROVIDERS = ["openai", "anthropic", "cognition", "typesafe"] as const;
export type Provider = (typeof PROVIDERS)[number];
export const MIN_MINUTES = 1, MAX_MINUTES = 30, DEFAULT_MINUTES = 5;

export function isProvider(p: unknown): p is Provider {
  return typeof p === "string" && (PROVIDERS as readonly string[]).includes(p);
}

/** The encryption key: 32 bytes, base64 (make one with `openssl rand -base64 32`). */
function masterKey(): Buffer {
  const raw = process.env.API_KEYS_ENCRYPTION_KEY ?? "";
  const k = Buffer.from(raw, "base64");
  if (k.length !== 32) throw new Error("API_KEYS_ENCRYPTION_KEY is not set (32 bytes, base64)");
  return k;
}

export function encrypt(plain: string, key: Buffer = masterKey()): string {
  const iv = randomBytes(12);
  const c = createCipheriv("aes-256-gcm", key, iv);
  const ct = Buffer.concat([c.update(plain, "utf8"), c.final()]);
  return [iv, c.getAuthTag(), ct].map((b) => b.toString("base64url")).join(".");
}

export function decrypt(box: string, key: Buffer = masterKey()): string {
  const [iv, tag, ct] = box.split(".").map((s) => Buffer.from(s, "base64url"));
  const d = createDecipheriv("aes-256-gcm", key, iv);
  d.setAuthTag(tag);
  return Buffer.concat([d.update(ct), d.final()]).toString("utf8");
}

// The tables this needs (also in db/schema.sql), made on first use so a deploy needs no extra step.
let ready: Promise<void> | null = null;
function ensureTables(): Promise<void> {
  if (!sql) throw new Error("the website has no database (DATABASE_URL)");
  ready ??= (async () => {
    await sql`alter table users add column if not exists run_minutes integer not null default 5`;
    await sql`create table if not exists user_api_keys (
      user_id text not null references users (user_id) on delete cascade,
      provider text not null check (provider in ('openai', 'anthropic', 'cognition', 'typesafe')),
      key_ciphertext text not null, key_last4 text not null,
      connected_at timestamptz not null default now(), primary key (user_id, provider))`;
    await sql`alter table user_api_keys add column if not exists kind text not null default 'key'`;
    await sql`alter table user_api_keys add column if not exists login_email text`;
  })().catch((e) => { ready = null; throw e; });
  return ready;
}

export type Kind = "key" | "chatgpt";
export type Connection = { kind: Kind; last4: string; email?: string; connected_at: string; spent_usd: number };
export type AccountSettings = { run_minutes: number; connections: Partial<Record<Provider, Connection>> };

export async function getSettings(userId: string): Promise<AccountSettings> {
  await ensureTables();
  const u = (await sql!`select run_minutes from users where user_id = ${userId}`) as { run_minutes: number }[];
  const rows = (await sql!`
    select k.provider, k.kind, k.login_email, k.key_last4, k.connected_at,
           coalesce((select sum(r.cost_usd) from runs r
                     where r.started_by_user_id = k.user_id and r.started_at >= k.connected_at
                       and r.ai_provider = case k.provider when 'openai' then 'codex' when 'anthropic' then 'claude'
                                                          when 'cognition' then 'devin' else 'jev' end), 0)::float as spent
    from user_api_keys k where k.user_id = ${userId}`) as { provider: Provider; kind: Kind; login_email: string | null; key_last4: string; connected_at: string; spent: number }[];
  const connections: AccountSettings["connections"] = {};
  for (const r of rows)
    connections[r.provider] = { kind: r.kind, last4: r.key_last4, ...(r.login_email ? { email: r.login_email } : {}),
                                connected_at: r.connected_at, spent_usd: Number(r.spent) || 0 };
  return { run_minutes: u[0]?.run_minutes ?? DEFAULT_MINUTES, connections };
}

export async function setMinutes(userId: string, minutes: number): Promise<void> {
  if (!Number.isInteger(minutes) || minutes < MIN_MINUTES || minutes > MAX_MINUTES)
    throw new Error(`the time limit is ${MIN_MINUTES} to ${MAX_MINUTES} minutes`);
  await ensureTables();
  const rows = await sql!`update users set run_minutes = ${minutes} where user_id = ${userId} returning user_id`;
  if (!rows.length) throw new Error("no such user");
}

export async function saveKey(userId: string, provider: Provider, key: string): Promise<void> {
  key = key.trim();
  if (key.length < 12 || key.length > 400 || /\s/.test(key)) throw new Error("that doesn't look like an API key");
  await ensureTables();
  const box = encrypt(key);
  await sql!`
    insert into user_api_keys (user_id, provider, key_ciphertext, key_last4) values (${userId}, ${provider}, ${box}, ${key.slice(-4)})
    on conflict (user_id, provider) do update set key_ciphertext = excluded.key_ciphertext,
      key_last4 = excluded.key_last4, kind = 'key', login_email = null, connected_at = now()`;
}

/** Codex's ChatGPT login file (auth.json), as text: a JSON object holding its tokens. */
function checkLogin(login: string): string {
  if (login.length > 20000) throw new Error("that sign-in is too big");
  let o: unknown;
  try {
    o = JSON.parse(login);
  } catch {
    throw new Error("that isn't a ChatGPT sign-in");
  }
  if (!o || typeof o !== "object" || !("tokens" in o)) throw new Error("that isn't a ChatGPT sign-in");
  return login;
}

/** A ChatGPT sign-in replaces any OpenAI key (one OpenAI connection per person). */
export async function saveLogin(userId: string, provider: Provider, login: string, email: string): Promise<void> {
  if (provider !== "openai") throw new Error("the ChatGPT sign-in is for OpenAI only");
  const box = encrypt(checkLogin(login));
  await ensureTables();
  await sql!`
    insert into user_api_keys (user_id, provider, key_ciphertext, key_last4, kind, login_email)
    values (${userId}, ${provider}, ${box}, '', 'chatgpt', ${email.slice(0, 200) || null})
    on conflict (user_id, provider) do update set key_ciphertext = excluded.key_ciphertext, key_last4 = '',
      kind = 'chatgpt', login_email = excluded.login_email, connected_at = now()`;
}

/** Codex refreshed its tokens during a run: keep the new ones (only while still signed in). */
export async function updateLogin(userId: string, provider: Provider, login: string): Promise<void> {
  const box = encrypt(checkLogin(login));
  await ensureTables();
  await sql!`update user_api_keys set key_ciphertext = ${box}
             where user_id = ${userId} and provider = ${provider} and kind = 'chatgpt'`;
}

export async function removeKey(userId: string, provider: Provider): Promise<void> {
  await ensureTables();
  await sql!`delete from user_api_keys where user_id = ${userId} and provider = ${provider}`;
}

/** The whole key (or ChatGPT sign-in), for the lab starting this person's run ("" if none is saved). */
export async function getKey(userId: string, provider: Provider): Promise<{ key: string; kind: Kind }> {
  await ensureTables();
  const rows = (await sql!`select key_ciphertext, kind from user_api_keys where user_id = ${userId} and provider = ${provider}`) as { key_ciphertext: string; kind: Kind }[];
  return rows[0] ? { key: decrypt(rows[0].key_ciphertext), kind: rows[0].kind } : { key: "", kind: "key" };
}
