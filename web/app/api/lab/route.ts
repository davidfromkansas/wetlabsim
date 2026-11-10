// "Open your lab" for a signed-in account: ask the Modal front (privately, with LAB_LINK_SECRET)
// for this account's lab, and once it is up hand back a one-time pass into it. The pass is
// signed with the same secret and good for one use, one minute, this lab and this account.
import { createHmac, randomBytes } from "node:crypto";
import { auth } from "@clerk/nextjs/server";
import { MODAL_FRONT_URL } from "@/lib/modal";

export const dynamic = "force-dynamic";

function pass(secret: string, user: string, lab: string): string {
  const body = Buffer.from(JSON.stringify({ u: user, l: lab, exp: Date.now() / 1000 + 60, n: randomBytes(12).toString("hex") })).toString("base64url");
  return `${body}.${createHmac("sha256", secret).update(body).digest("base64url")}`;
}

export async function POST(req: Request) {
  const { userId } = await auth();
  if (!userId) return Response.json({ error: "sign in first" }, { status: 401 });
  const secret = process.env.LAB_LINK_SECRET;
  if (!secret) return Response.json({ error: "this site isn't connected to the labs yet" }, { status: 503 });
  let r: { url?: string; lab?: string; pending?: boolean; full?: boolean; max?: number; error?: string };
  try {
    const res = await fetch(`${MODAL_FRONT_URL}/api/lab-for-user`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Link-Secret": secret },
      body: JSON.stringify({ user: userId }),
      cache: "no-store",
      signal: AbortSignal.timeout(20000),
    });
    r = await res.json();
  } catch {
    return Response.json({ pending: true });     // the Modal front is waking up: ask again
  }
  // A saved session to open in the lab (it loads it from the database if it isn't open yet).
  const body = await req.json().catch(() => ({}));
  const open = typeof body.session === "string" && /^[0-9a-f-]{36}$/.test(body.session) ? `&open=${body.session}` : "";
  if (r.url && r.lab) return Response.json({ go: `${r.url}/auth?pass=${pass(secret, userId, r.lab)}${open}` });
  return Response.json({ pending: r.pending, full: r.full, max: r.max, error: r.error });
}
