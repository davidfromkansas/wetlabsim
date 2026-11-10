"use client";
// The Live now list: runs going on in any lab, refreshed every few seconds.
import { useEffect, useState } from "react";

type Run = { task: string; model: string; session?: string; session_name?: string; share?: string };
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
  // Labs are private: only runs in shared sessions show here, each opening its share link.
  const rows = labs.flatMap((lab) => lab.runs.filter((r) => r.share).map((r, i) => ({ lab, r, key: `${lab.lab}-${i}` })));
  if (!rows.length) return <ul><li className="small">Nothing shared is running right now.</li></ul>;
  return (
    <ul>
      {rows.map(({ lab, r, key }) => (
        <li key={key}>
          <span className="dot" />
          <span className="t"><b>{r.task}</b><span className="small">{r.model} · {r.session_name || `lab ${lab.lab}`}</span></span>
          <a href={r.share}>Watch</a>
        </li>
      ))}
    </ul>
  );
}
