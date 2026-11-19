// Wake the Modal front ahead of time: the landing page calls this as it opens, so by the time
// Google sign-in is done the front is already up and can start the visitor's container at once.
// Public and harmless: it only asks the front's public live list (what anyone can see).
import { MODAL_FRONT_URL } from "@/lib/modal";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    await fetch(`${MODAL_FRONT_URL}/api/live`, { cache: "no-store", signal: AbortSignal.timeout(4000) });
  } catch {
    // still waking: the request alone is enough to start it
  }
  return new Response(null, { status: 204 });
}
