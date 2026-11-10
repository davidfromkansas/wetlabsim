// A shared run's link: its replay, view only, no sign-in (while its owner has sharing on).
import { sharedRun } from "@/lib/db";
import { MODAL_FRONT_URL } from "@/lib/modal";
import { signPass } from "@/lib/pass";

export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const run = /^[\w-]{10,64}$/.test(token) ? await sharedRun(token) : null;
  const pass = run ? signPass({ k: "view", r: run.run_id, t: token }, 7200) : null;
  if (!pass) return new Response("This link is off: its owner has turned sharing off, or the link is wrong.", { status: 404 });
  return Response.redirect(`${MODAL_FRONT_URL}/view?pass=${pass}`, 303);
}
