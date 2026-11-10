// A shared session's link: watch it in its owner's lab, view only, no sign-in. Works while the
// owner has sharing on and their lab is open (a share link never starts anyone's lab).
import { redirect } from "next/navigation";
import { sharedSession } from "@/lib/db";
import { MODAL_FRONT_URL } from "@/lib/modal";
import { signPass } from "@/lib/pass";

export const dynamic = "force-dynamic";

function Note({ title, text }: { title: string; text: string }) {
  return <main><h1>{title}</h1><p className="sub">{text}</p><p className="small"><a href="/">MuJoCo Playground</a></p></main>;
}

export default async function Shared({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const s = /^[\w-]{10,64}$/.test(token) ? await sharedSession(token) : null;
  if (!s) return <Note title="This link is off" text="Its owner has turned sharing off, or the link is wrong." />;
  let lab: { url?: string; lab?: string } = {};
  try {
    const r = await fetch(`${MODAL_FRONT_URL}/api/lab-for-user`, {
      method: "POST", cache: "no-store", signal: AbortSignal.timeout(15000),
      headers: { "Content-Type": "application/json", "X-Link-Secret": process.env.LAB_LINK_SECRET ?? "" },
      body: JSON.stringify({ user: s.owner_user_id, find_only: true }),
    });
    lab = await r.json();
  } catch {}
  const pass = lab.url && lab.lab ? signPass({ k: "watch", w: s.session_id, t: token, l: lab.lab }) : null;
  if (!pass) return <Note title={s.session_name} text="This lab isn't open right now. You can watch it while its owner has it open." />;
  redirect(`${lab.url}/watch?pass=${pass}`);
}
