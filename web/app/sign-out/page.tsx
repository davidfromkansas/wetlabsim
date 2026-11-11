"use client";
// The Playground's account menu links here: sign out of the website, then back to the front page.
import { useClerk } from "@clerk/nextjs";
import { useEffect } from "react";

export default function SignOut() {
  const { signOut, loaded } = useClerk();
  useEffect(() => { if (loaded) signOut({ redirectUrl: "/" }); }, [loaded, signOut]);
  return <main><p className="sub">Signing you out…</p></main>;
}
