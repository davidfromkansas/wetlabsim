// Your runs: every AI task you've run, newest first (only yours).
import Link from "next/link";
import { UserButton } from "@clerk/nextjs";
import { currentUser } from "@clerk/nextjs/server";
import { myRuns } from "@/lib/db";

export const dynamic = "force-dynamic";

export default async function Runs() {
  const user = await currentUser();
  if (!user) return <main><h1>Your runs</h1><p className="sub">Sign in on the <Link href="/">front page</Link> to see your runs.</p></main>;
  const runs = await myRuns(user.id).catch(() => []);
  return (
    <main>
      <div className="top"><p className="small"><Link href="/">← Back to the Playground</Link></p><UserButton /></div>
      <h1>Your runs</h1>
      <p className="sub">Every task you've given an AI, with the code it wrote. Only you can see these.</p>
      <div className="card">
        {runs.length ? (
          <ul>
            {runs.map((r) => (
              <li key={r.run_id}>
                <span className="t">
                  <b><Link href={`/runs/${encodeURIComponent(r.run_id)}`}>{r.task_prompt || r.run_id}</Link>{r.share_token && <span className="tag">Shared</span>}</b>
                  <span className="small">{r.ai_model} · {r.robot_type} · {r.run_outcome}{r.cost_usd ? ` · $${Number(r.cost_usd).toFixed(2)}` : ""} · {r.files} file{r.files === 1 ? "" : "s"} · {r.started_at ? new Date(r.started_at).toLocaleString() : ""}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : <ul><li className="small">No runs yet.</li></ul>}
      </div>
    </main>
  );
}
