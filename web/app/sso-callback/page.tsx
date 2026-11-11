import { AuthenticateWithRedirectCallback } from "@clerk/nextjs";

// Google sends people back here; Clerk finishes sign-in (or sign-up for new people) and returns to "/".
export default function SsoCallback() {
  return (
    <main>
      <p className="sub">Signing you in…</p>
      <AuthenticateWithRedirectCallback signInFallbackRedirectUrl="/" signUpFallbackRedirectUrl="/" />
    </main>
  );
}
