"use client";
// Share (as in the lab's header): one switch, "Anyone with the link can watch", off by default.
// On shows the link and Copy; off stops the link at once; on again makes a new link.
import { useState } from "react";

export function ShareSwitch({ endpoint, initialLink, what = "run" }: { endpoint: string; initialLink: string; what?: string }) {
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState(initialLink && typeof window !== "undefined" ? new URL(initialLink, location.origin).href : initialLink);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const toggle = async () => {
    setBusy(true);
    try {
      const r = await (await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ on: !link }) })).json();
      if (!r.error) { setLink(r.link || ""); setCopied(false); }
    } finally { setBusy(false); }
  };
  return (
    <span className="sharewrap">
      <button className="sharebtn" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}>
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7" /><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7" /></svg>
        Share
      </button>
      {open && (
        <span className="sharepop" role="dialog" aria-label={`Share this ${what}`}>
          <span className="sharetitle">Share this {what}</span>
          <span className="sharerow">
            <span style={{ flex: 1 }}>
              <label htmlFor="shareSwitch" className="sharelabel">Anyone with the link can watch</label>
              <span className="sharedesc">They can watch the replay and see the code, but can&apos;t change anything. No sign-in needed.</span>
            </span>
            <button id="shareSwitch" className="switch" type="button" aria-pressed={!!link} disabled={busy} onClick={toggle}><span /></button>
          </span>
          {link ? (
            <span>
              <span className="sharelink">
                <input readOnly value={link.replace(/^https?:\/\//, "")} aria-label="Share link" />
                <button type="button" onClick={async () => { await navigator.clipboard.writeText(link); setCopied(true); }}>{copied ? "Copied" : "Copy"}</button>
              </span>
              <span className="sharenote">Turning this off stops the link working right away.</span>
            </span>
          ) : <span className="sharenote" style={{ marginTop: 0 }}>Only you can see this {what}.</span>}
        </span>
      )}
    </span>
  );
}
