// A lab reads and changes its signed-in owner's General settings (with LAB_LINK_SECRET):
// POST {user, action: get | set_minutes | save_key | save_login | update_login | remove_key | key, ...}.
// Only "key" returns a whole API key (or ChatGPT sign-in), for the run the lab is starting;
// nothing here is reachable from a browser.
import { timingSafeEqual } from "node:crypto";
import { getKey, getSettings, isProvider, removeKey, saveKey, saveLogin, setMinutes, updateLogin } from "@/lib/account";

export const dynamic = "force-dynamic";

function linkOk(given: string | null): boolean {
  const secret = process.env.LAB_LINK_SECRET ?? "";
  if (!secret || !given) return false;
  const a = Buffer.from(given), b = Buffer.from(secret);
  return a.length === b.length && timingSafeEqual(a, b);
}

const noStore = { "Cache-Control": "no-store" };

export async function POST(req: Request) {
  if (!linkOk(req.headers.get("x-link-secret"))) return Response.json({ error: "not found" }, { status: 404 });
  let b: Record<string, unknown>;
  try {
    b = await req.json();
  } catch {
    return Response.json({ error: "bad request" }, { status: 400 });
  }
  const user = typeof b.user === "string" ? b.user : "";
  if (!/^[\w-]{1,100}$/.test(user)) return Response.json({ error: "bad user" }, { status: 400 });
  try {
    switch (b.action) {
      case "get":
        return Response.json(await getSettings(user), { headers: noStore });
      case "set_minutes":
        await setMinutes(user, Number(b.minutes));
        return Response.json({ ok: true });
      case "save_key":
        if (!isProvider(b.provider) || typeof b.key !== "string") return Response.json({ error: "bad request" }, { status: 400 });
        await saveKey(user, b.provider, b.key);
        return Response.json({ ok: true });
      case "save_login":
        if (!isProvider(b.provider) || typeof b.login !== "string") return Response.json({ error: "bad request" }, { status: 400 });
        await saveLogin(user, b.provider, b.login, typeof b.email === "string" ? b.email : "");
        return Response.json({ ok: true });
      case "update_login":
        if (!isProvider(b.provider) || typeof b.login !== "string") return Response.json({ error: "bad request" }, { status: 400 });
        await updateLogin(user, b.provider, b.login);
        return Response.json({ ok: true });
      case "remove_key":
        if (!isProvider(b.provider)) return Response.json({ error: "bad request" }, { status: 400 });
        await removeKey(user, b.provider);
        return Response.json({ ok: true });
      case "key":
        if (!isProvider(b.provider)) return Response.json({ error: "bad request" }, { status: 400 });
        return Response.json(await getKey(user, b.provider), { headers: noStore });
      default:
        return Response.json({ error: "unknown action" }, { status: 400 });
    }
  } catch (e) {
    // Never echo a key: only our own error messages come back.
    const msg = e instanceof Error ? e.message : "failed";
    return Response.json({ error: msg.includes("API_KEYS_ENCRYPTION_KEY") || msg.startsWith("the ") || msg.startsWith("that ") || msg === "no such user" ? msg : "the website couldn't do that" }, { status: 500 });
  }
}
