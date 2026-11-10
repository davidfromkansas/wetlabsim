// One of your runs: what it was, and every file the AI wrote or changed (code shown inline).
import Link from "next/link";
import { notFound } from "next/navigation";
import { currentUser } from "@clerk/nextjs/server";
import { myRun, runFiles } from "@/lib/db";
import { ShareSwitch } from "../../share-switch";

export const dynamic = "force-dynamic";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const user = await currentUser();
  if (!user) return <main><p className="sub">Sign in on the <Link href="/">front page</Link> to see this run.</p></main>;
  const { id } = await params;
  const run = await myRun(user.id, id);
  if (!run) notFound();
  const files = await runFiles(run.run_id);
  const file = (p: string, dl = false) => `/api/runs/${encodeURIComponent(run.run_id)}/file?path=${encodeURIComponent(p)}${dl ? "&download=1" : ""}`;
  return (
    <main>
      <p className="small"><Link href="/runs">← Your runs</Link></p>
      <div className="top" style={{ alignItems: "flex-start" }}>
        <h1>{run.task_prompt || run.run_id}</h1>
        <span style={{ display: "flex", gap: 8, flex: "none" }}>
          <a className="secondary" href={`/api/runs/${encodeURIComponent(run.run_id)}/replay`} target="_blank" rel="noopener">Watch replay</a>
          <ShareSwitch endpoint={`/api/runs/${encodeURIComponent(run.run_id)}/share`} initialLink={run.share_token ? `/r/${run.share_token}` : ""} />
        </span>
      </div>
      <p className="sub">
        {run.ai_model} ({run.ai_provider}) on {run.robot_type} · station {run.robot_station_id} in {run.session_name || "a session"} · {run.run_outcome}
        {run.cost_usd ? ` · $${Number(run.cost_usd).toFixed(2)}` : ""} · starter kit {run.robot_kit_version}
      </p>
      {run.blob_folder_path && (
        <div className="links small" style={{ marginBottom: 16 }}>
          <a href={file("transcript.jsonl.gz", true)}>Download transcript</a>
          <a href={file("replay.npz", true)}>Download replay</a>
        </div>
      )}
      <div className="card">
        <h2>Files the AI wrote or changed</h2>
        {files.length ? files.map((f) => (
          <details key={f.file_path} style={{ borderTop: "1px solid #EEF0F3", padding: "10px 0" }}>
            <summary><b>{f.file_path}</b> <span className="small">{f.language} · {f.line_count != null ? `${f.line_count} lines` : `${f.size_bytes} bytes`}</span>
              {run.blob_folder_path && <> · <a className="small" href={file(`workspace/${f.file_path}`, true)}>download</a></>}</summary>
            {f.code_text != null
              ? <pre style={{ overflowX: "auto", background: "#F9FAFB", padding: 12, borderRadius: 8, fontSize: 12.5 }}>{f.code_text}</pre>
              : f.language === "image" && run.blob_folder_path
                ? <img src={file(`workspace/${f.file_path}`)} alt={f.file_path} style={{ maxWidth: "100%", borderRadius: 8 }} />
                : null}
          </details>
        )) : <p className="small">The AI didn't write any files in this run.</p>}
      </div>
    </main>
  );
}
