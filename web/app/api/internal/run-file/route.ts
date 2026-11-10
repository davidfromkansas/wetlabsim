// A lab hands over one file of a finished run (with LAB_LINK_SECRET): stored privately in Blob at
// runs/<run id>/<path>. The website reaches Blob by itself (OIDC), so labs never hold a Blob key.
import { timingSafeEqual } from "node:crypto";
import { put } from "@vercel/blob";

export const dynamic = "force-dynamic";

function linkOk(given: string | null): boolean {
  const secret = process.env.LAB_LINK_SECRET ?? "";
  if (!secret || !given) return false;
  const a = Buffer.from(given), b = Buffer.from(secret);
  return a.length === b.length && timingSafeEqual(a, b);
}

export async function POST(req: Request) {
  if (!linkOk(req.headers.get("x-link-secret"))) return Response.json({ error: "not found" }, { status: 404 });
  const q = new URL(req.url).searchParams;
  const run = q.get("run") ?? "", path = q.get("path") ?? "";
  if (!/^[\w.-]{1,80}$/.test(run) || !path || path.length > 400 || path.split("/").some((p) => !p || p === "." || p === ".."))
    return Response.json({ error: "bad run or path" }, { status: 400 });
  const blob = await put(`runs/${run}/${path}`, Buffer.from(await req.arrayBuffer()), {
    access: "private", addRandomSuffix: false, allowOverwrite: true,
    contentType: req.headers.get("content-type") ?? "application/octet-stream",
  });
  return Response.json({ pathname: blob.pathname });
}
