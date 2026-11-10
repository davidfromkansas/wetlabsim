"use client";
// Your saved sessions: open one in your lab (it starts if needed), or delete it.
import { useState } from "react";
import type { SavedSession } from "@/lib/db";
import { OpenLab } from "./open-lab";

function ago(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export function MySessions({ initial }: { initial: SavedSession[] }) {
  const [list, setList] = useState(initial);
  const remove = async (id: string) => {
    if (!confirm("Delete this session?")) return;
    const r = await fetch(`/api/sessions/${id}`, { method: "DELETE" });
    if (r.ok) setList((l) => l.filter((x) => x.session_id !== id));
  };
  if (!list.length) return <ul><li className="small">No saved sessions yet. Open your lab and build something: it saves as you go.</li></ul>;
  return (
    <ul>
      {list.map((s) => (
        <li key={s.session_id}>
          <span className="t"><b>{s.session_name}{s.shared && <span className="tag">Shared</span>}</b><span className="small">{s.stations} station{s.stations === 1 ? "" : "s"} · {s.runs} run{s.runs === 1 ? "" : "s"} · saved {ago(s.last_saved_at)}</span></span>
          <OpenLab session={s.session_id} label="Open" small />
          <button className="link" onClick={() => remove(s.session_id)} aria-label={`Delete ${s.session_name}`}>Delete</button>
        </li>
      ))}
    </ul>
  );
}
