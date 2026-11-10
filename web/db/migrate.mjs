// Apply db/schema.sql to DATABASE_URL:  npm run db:migrate  (after `vercel env pull .env.local`)
import { readFileSync } from "node:fs";
import { neon } from "@neondatabase/serverless";

process.loadEnvFile?.(".env.local");
if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL is not set");
const sql = neon(process.env.DATABASE_URL);
for (const stmt of readFileSync(new URL("./schema.sql", import.meta.url), "utf8").split(";").map((s) => s.trim()).filter(Boolean)) {
  await sql.query(stmt);
}
console.log("schema applied");
