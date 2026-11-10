// Delete one of your saved sessions (it is hidden: deleted_at, so it can be brought back).
import { auth } from "@clerk/nextjs/server";
import { deleteSession } from "@/lib/db";

export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { userId } = await auth();
  if (!userId) return Response.json({ error: "sign in first" }, { status: 401 });
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) return Response.json({ error: "bad session" }, { status: 400 });
  await deleteSession(userId, id);
  return Response.json({ ok: true });
}
