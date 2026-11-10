// Passes the website signs for the labs and the replay viewer (LAB_LINK_SECRET, shared with Modal):
// base64url(json).base64url(hmac-sha256), each with an expiry and a one-time nonce.
import { createHmac, randomBytes } from "node:crypto";

export function signPass(payload: Record<string, unknown>, seconds = 60): string | null {
  const secret = process.env.LAB_LINK_SECRET;
  if (!secret) return null;
  const body = Buffer.from(JSON.stringify({ ...payload, exp: Date.now() / 1000 + seconds, n: randomBytes(12).toString("hex") })).toString("base64url");
  return `${body}.${createHmac("sha256", secret).update(body).digest("base64url")}`;
}

export function newShareToken(): string {
  return randomBytes(16).toString("base64url");
}
