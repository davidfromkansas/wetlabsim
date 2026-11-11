"use client";
// Signed in: start (or find) your lab and go straight in. While it starts you see a faint outline
// of the Playground; if every lab is busy it keeps trying on its own.
import { useCallback, useEffect, useRef, useState } from "react";

type Reply = { go?: string; pending?: boolean; full?: boolean; max?: number; error?: string };

export function GoToLab() {
  const [state, setState] = useState<"starting" | "full" | "error">("starting");
  const [msg, setMsg] = useState("");
  const [wait, setWait] = useState(0);
  const run = useRef(0);

  const start = useCallback(async () => {
    const me = ++run.current;
    setState("starting"); setMsg("");
    for (let i = 0; i < 120 && me === run.current; i++) {
      let r: Reply = {};
      try { r = await (await fetch("/api/lab", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).json(); } catch {}
      if (me !== run.current) return;
      if (r.go) { location.replace(r.go); return; }
      if (r.full) { setState("full"); setMsg(`Every one of the ${r.max ?? 10} labs is in use. We'll keep trying and take you in as soon as one frees up.`); setWait(10); return; }
      if (r.error) { setState("error"); setMsg(r.error); return; }
      await new Promise((res) => setTimeout(res, 2000));
    }
    if (me === run.current) { setState("error"); setMsg("Your lab is taking longer than usual. Please try again."); }
  }, []);

  useEffect(() => { start(); }, [start]);
  // All labs busy: count down and try again by itself.
  useEffect(() => {
    if (state !== "full") return;
    if (wait <= 0) { start(); return; }
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [state, wait, start]);

  return (
    <div className="boot">
      <div className="boot-side"><b>Playground</b><i /><i style={{ width: "80%" }} /><i style={{ width: "65%" }} /></div>
      <div className="boot-scene" />
      <div className="boot-rail"><i /><i /></div>
      <div className="boot-panel"><i style={{ height: 44 }} /><i style={{ height: 28, width: "60%" }} /><i style={{ flex: 1 }} /><i style={{ height: 96, borderRadius: 14 }} /></div>
      <div className="boot-card" role="status">
        {state === "starting" ? (
          <>
            <span className="boot-dots" aria-hidden="true"><i /><i /><i /><i /><i /></span>
            <b>Starting your lab…</b>
            <p>About half a minute. Your sessions open right where you left them.</p>
            <span className="boot-bar"><span /></span>
          </>
        ) : state === "full" ? (
          <>
            <b>All labs are busy right now</b>
            <p>{msg}</p>
            <span className="boot-bar amber"><span /></span>
            <p className="boot-small">Trying again in {wait} second{wait === 1 ? "" : "s"}</p>
            <div className="boot-acts"><button className="land-cta solid" onClick={start}>Try now</button><a className="land-ghost" href="/runs">See your runs</a></div>
          </>
        ) : (
          <>
            <b>Your lab didn't start</b>
            <p>{msg}</p>
            <div className="boot-acts"><button className="land-cta solid" onClick={start}>Try again</button><a className="land-ghost" href="/runs">See your runs</a></div>
          </>
        )}
      </div>
    </div>
  );
}
