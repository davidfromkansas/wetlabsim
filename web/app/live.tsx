"use client";
// The Live now list: runs going on in any lab, refreshed every few seconds.
import { useEffect, useState } from "react";

type Run = { task: string; model: string; session?: string; session_name?: string };
type Lab = { lab: string; url: string; runs: Run[] };

export function LiveNow() {
  const [labs, setLabs] = useState<Lab[]>([]);
  useEffect(() => {
    let stop = false, timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try { const d = await (await fetch("/api/live")).json(); if (!stop) setLabs(d.labs ?? []); } catch {}
      if (!stop) timer = setTimeout(load, 4000);
    };
    load();
    return () => { stop = true; clearTimeout(timer); };
  }, []);
  const rows = labs.flatMap((lab) => lab.runs.map((r, i) => ({ lab, r, key: `${lab.lab}-${i}` })));
  if (!rows.length) return <ul><li className="small">Nothing is running right now.</li></ul>;
  return (
    <ul>
      {rows.map(({ lab, r, key }) => (
        <li key={key}>
          <span className="dot" />
          <span className="t"><b>{r.task}</b><span className="small">{r.model} · {r.session_name || `lab ${lab.lab}`}</span></span>
          <a href={`${lab.url}/?watch=1${r.session ? `&s=${encodeURIComponent(r.session)}` : ""}`}>Watch</a>
        </li>
      ))}
    </ul>
  );
}
