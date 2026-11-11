"use client";
import { useClerk } from "@clerk/nextjs";
import { useState } from "react";

// One "Start" button: goes straight to Google's sign-in (new and returning users alike).
export function StartButton() {
  const { client, loaded } = useClerk();
  const [busy, setBusy] = useState(false);
  async function start() {
    if (!loaded || !client || busy) return;
    setBusy(true);
    try {
      await client.signIn.authenticateWithRedirect({
        strategy: "oauth_google",
        redirectUrl: "/sso-callback",
        redirectUrlComplete: "/",
      });
    } catch {
      setBusy(false);
    }
  }
  return (
    <button className="land-start" onClick={start} disabled={busy} aria-busy={busy}>
      <span className="land-play" aria-hidden="true">
        <svg width="12" height="12" viewBox="0 0 12 12"><path d="M3 1.8v8.4L10 6z" fill="currentColor" /></svg>
      </span>
      Start
    </button>
  );
}
