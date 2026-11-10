// Replay one of your runs (the 3D replay viewer runs with the labs, on Modal): a pass for it.
import { auth } from "@clerk/nextjs/server";
import { myRun } from "@/lib/db";
import { MODAL_FRONT_URL } from "@/lib/modal";
import { signPass } from "@/lib/pass";

export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { userId } = await auth();
  if (!userId) return new Response("sign in first", { status: 401 });
  const { id } = await params;
  const run = await myRun(userId, id);
  const pass = run ? signPass({ k: "view", r: run.run_id }, 7200) : null;
  if (!pass) return new Response("not found", { status: 404 });
  return Response.redirect(`${MODAL_FRONT_URL}/view?pass=${pass}`, 303);
}
