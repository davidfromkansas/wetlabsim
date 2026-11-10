"use client";
// Open your lab: ask the site for it (starting it if needed, about half a minute), then go in.
import { useState } from "react";

export function OpenLab({ session, label = "Open your lab", small = false }: { session?: string; label?: string; small?: boolean }) {
  const [state, setState] = useState<"idle" | "starting" | "full" | "error">("idle");
  const [msg, setMsg] = useState("");
  const open = async () => {
    setState("starting");
    for (let i = 0; i < 120; i++) {
      let r: { go?: string; pending?: boolean; full?: boolean; max?: number; error?: string } = {};
      try { r = await (await fetch("/api/lab", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session }) })).json(); } catch {}
      if (r.go) { location.href = r.go; return; }
      if (r.full) { setState("full"); setMsg(`All ${r.max} labs are in use right now. Please try again in a few minutes.`); return; }
      if (r.error) { setState("error"); setMsg(r.error); return; }
      await new Promise((res) => setTimeout(res, 2000));
    }
    setState("error"); setMsg("Your lab is taking longer than usual. Please try again.");
  };
  return (
    <>
      <button className={small ? "secondary" : "primary"} onClick={open} disabled={state === "starting"}>
        {state === "starting" ? "Starting your lab…" : label}
      </button>
      {msg && <p className="small" style={{ margin: "10px 0 0" }}>{msg}</p>}
    </>
  );
}
