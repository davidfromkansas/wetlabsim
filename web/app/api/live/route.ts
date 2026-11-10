// What is running in the labs right now (from the Modal front), for the front page's Live now list.
import { MODAL_FRONT_URL } from "@/lib/modal";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const r = await fetch(`${MODAL_FRONT_URL}/api/live`, { cache: "no-store", signal: AbortSignal.timeout(8000) });
    return Response.json(await r.json());
  } catch {
    return Response.json({ labs: [] });
  }
}
