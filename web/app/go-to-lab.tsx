"use client";
// Signed in: start (or find) your Modal container and go straight in. While it starts you see an
// outline of the Playground with a card over the 3D area: the steps so far, the seconds waited and
// a bar that fills toward the usual start time. If every container is busy it keeps trying.
import { useCallback, useEffect, useRef, useState } from "react";

type Reply = { go?: string; pending?: boolean; stage?: string; waited?: number; full?: boolean; max?: number; error?: string };

// The steps, in order, by what the website and the Modal front report.
const STEPS = [
  { key: "waking", label: "Connecting" },
  { key: "starting", label: "Starting your computer in the cloud" },
  { key: "sessions", label: "Opening your sessions" },
  { key: "go", label: "Loading the Playground" },
];
const USUAL = 25;          // s: a usual cold start, for the bar (it slows down past this, never fills)

function stepOf(r: Reply): number {
  if (r.go) return 3;
  if (r.stage === "Opening your sessions") return 2;
  if (r.stage === "starting" || r.pending && r.stage !== "waking") return 1;
  return 0;
}

export function GoToLab() {
  const [state, setState] = useState<"starting" | "full" | "error">("starting");
  const [msg, setMsg] = useState("");
  const [wait, setWait] = useState(0);
  const [step, setStep] = useState(0);
  const [secs, setSecs] = useState(0);
  const t0 = useRef(Date.now());
  const run = useRef(0);

  const start = useCallback(async () => {
    const me = ++run.current;
    setState("starting"); setMsg(""); setStep(0); t0.current = Date.now(); setSecs(0);
    for (let i = 0; i < 240 && me === run.current; i++) {
      let r: Reply = {};
      try { r = await (await fetch("/api/lab", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).json(); } catch {}
      if (me !== run.current) return;
      setStep((s) => Math.max(s, stepOf(r)));
      // Already started a while ago (another tab, or a reload): count from then.
      if (r.waited) t0.current = Math.min(t0.current, Date.now() - r.waited * 1000);
      if (r.go) { location.replace(r.go); return; }
      if (r.full) { setState("full"); setMsg(`Every one of the ${r.max ?? 10} computers is in use. We'll keep trying and take you in as soon as one frees up.`); setWait(10); return; }
      if (r.error) { setState("error"); setMsg(r.error); return; }
      await new Promise((res) => setTimeout(res, 1000));
    }
    if (me === run.current) { setState("error"); setMsg("This is taking longer than usual. Please try again."); }
  }, []);

  useEffect(() => { start(); }, [start]);
  useEffect(() => {
    if (state !== "starting") return;
    const t = setInterval(() => setSecs(Math.floor((Date.now() - t0.current) / 1000)), 250);
    return () => clearInterval(t);
  }, [state]);
  // All busy: count down and try again by itself.
  useEffect(() => {
    if (state !== "full") return;
    if (wait <= 0) { start(); return; }
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [state, wait, start]);

  // Fills to ~85% at the usual time, then creeps (never claims to be done before it is).
  const pct = step >= 3 ? 100 : Math.min(96, secs <= USUAL ? (secs / USUAL) * 85 : 85 + (1 - Math.exp(-(secs - USUAL) / 30)) * 11);

  return (
    <div className="boot">
      <div className="boot-side">
        <b>Playground</b>
        <span className="boot-lbl">Your sessions</span>
        <i /><i style={{ width: "80%" }} /><i style={{ width: "65%" }} />
      </div>
      <div className="boot-scene">
        <div className="boot-grid" aria-hidden="true" />
        <div className="boot-card" role="status" aria-live="polite">
          {state === "starting" ? (
            <>
              <b>Getting your Playground ready</b>
              <ol className="boot-steps">
                {STEPS.map((s, i) => (
                  <li key={s.key} className={i < step ? "done" : i === step ? "now" : ""}>
                    <span className="boot-tick" aria-hidden="true">
                      {i < step ? (
                        <svg width="12" height="12" viewBox="0 0 12 12"><path d="M2.5 6.2l2.3 2.3 4.7-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      ) : null}
                    </span>
                    {s.label}
                  </li>
                ))}
              </ol>
              <span className="boot-bar fill"><span style={{ width: `${pct}%` }} /></span>
              <p className="boot-small">{secs} s · usually about {USUAL} s. Your sessions open right where you left them.</p>
            </>
          ) : state === "full" ? (
            <>
              <b>Everything is busy right now</b>
              <p>{msg}</p>
              <span className="boot-bar amber"><span /></span>
              <p className="boot-small">Trying again in {wait} second{wait === 1 ? "" : "s"}</p>
              <div className="boot-acts"><button className="land-cta solid" onClick={start}>Try now</button><a className="land-ghost" href="/runs">See your runs</a></div>
            </>
          ) : (
            <>
              <b>Your Playground didn't start</b>
              <p>{msg}</p>
              <div className="boot-acts"><button className="land-cta solid" onClick={start}>Try again</button><a className="land-ghost" href="/runs">See your runs</a></div>
            </>
          )}
        </div>
      </div>
      <div className="boot-rail"><i /><i /></div>
      <div className="boot-panel">
        <div className="boot-tabs"><span>Chat</span><span>Files</span><span>Data</span></div>
        <i style={{ height: 28, width: "60%" }} /><i style={{ flex: 1 }} /><i style={{ height: 96, borderRadius: 14 }} />
      </div>
    </div>
  );
}
