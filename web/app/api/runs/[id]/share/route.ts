// One of your runs' share link: on (a new link) or off (the old link stops at once).
import { auth } from "@clerk/nextjs/server";
import { setRunShare } from "@/lib/db";
import { newShareToken } from "@/lib/pass";

export const dynamic = "force-dynamic";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { userId } = await auth();
  if (!userId) return Response.json({ error: "sign in first" }, { status: 401 });
  const { id } = await params;
  const on = !!(await req.json().catch(() => ({}))).on;
  const token = on ? newShareToken() : null;
  if (!(await setRunShare(userId, id, token))) return Response.json({ error: "not found" }, { status: 404 });
  return Response.json({ on, link: token ? `${new URL(req.url).origin}/r/${token}` : "" });
}
