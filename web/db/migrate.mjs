// Apply db/schema.sql to DATABASE_URL:  npm run db:migrate  (after `vercel env pull .env.local`).
// DB_SCHEMA=<name> applies it to that schema instead (tests; the live tables stay as they are).
import { readFileSync } from "node:fs";
import { neon } from "@neondatabase/serverless";

process.loadEnvFile?.(".env.local");
if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL is not set");
const sql = neon(process.env.DATABASE_URL);
const schema = process.env.DB_SCHEMA ?? "";
if (schema && !/^\w+$/.test(schema)) throw new Error("bad DB_SCHEMA");
if (schema) await sql.query(`create schema if not exists "${schema}"`);
const text = readFileSync(new URL("./schema.sql", import.meta.url), "utf8");
for (const stmt of text.split(/^;\s*$/m).map((s) => s.trim()).filter((s) => s.replace(/^--.*$/gm, "").trim())) {
  if (schema) await sql.transaction([sql.query(`set local search_path to "${schema}"`), sql.query(stmt)]);
  else await sql.query(stmt);
}
console.log(`schema applied${schema ? ` (to ${schema})` : ""}`);
