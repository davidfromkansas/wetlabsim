// One of your runs as a video (owner only). The lab makes it after the run (playground/runvideo.py)
// and hands it over in parts of at most 3.5 MB (a request to this site takes at most 4.5 MB):
// runs/<id>/video/manifest.json lists them. This joins them back into one MP4, with byte
// ranges so the player can seek.
import { auth } from "@clerk/nextjs/server";
import { get } from "@vercel/blob";
import { myRun } from "@/lib/db";

export const dynamic = "force-dynamic";

type Manifest = { type: string; size: number; parts: number[] };

async function text(path: string): Promise<string | null> {
  const got = await get(path, { access: "private" });
  return got ? await new Response(got.stream).text() : null;
}

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { userId } = await auth();
  if (!userId) return new Response("sign in first", { status: 401 });
  const { id } = await params;
  const run = await myRun(userId, id);
  if (!run?.blob_folder_path) return new Response("not found", { status: 404 });
  const base = `${run.blob_folder_path}video/`;
  let man: Manifest;
  try {
    const t = await text(`${base}manifest.json`);
    if (!t) return new Response("this run has no video", { status: 404 });
    man = JSON.parse(t);
  } catch {
    return new Response("this run has no video", { status: 404 });
  }
  const size = man.size;
  // The bytes asked for (all of them without a Range header).
  let start = 0, end = size - 1, partial = false;
  const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.get("range") ?? "");
  if (m) {
    if (m[1] === "" && m[2] !== "") { start = Math.max(0, size - Number(m[2])); }
    else { start = Number(m[1] || 0); if (m[2] !== "") end = Math.min(size - 1, Number(m[2])); }
    if (start > end || start >= size) return new Response(null, { status: 416, headers: { "Content-Range": `bytes */${size}` } });
    partial = true;
  }
  // Which parts hold those bytes.
  const pieces: { i: number; from: number; to: number }[] = [];
  let off = 0;
  man.parts.forEach((n, i) => {
    const a = off, b = off + n - 1;
    if (b >= start && a <= end) pieces.push({ i, from: Math.max(start, a) - a, to: Math.min(end, b) - a });
    off += n;
  });
  const body = new ReadableStream<Uint8Array>({
    async start(ctrl) {
      try {
        for (const p of pieces) {
          const got = await get(`${base}part-${String(p.i).padStart(3, "0")}`, { access: "private" });
          if (!got) throw new Error("missing part");
          const buf = new Uint8Array(await new Response(got.stream).arrayBuffer());
          ctrl.enqueue(buf.subarray(p.from, p.to + 1));
        }
        ctrl.close();
      } catch (e) { ctrl.error(e); }
    },
  });
  return new Response(body, {
    status: partial ? 206 : 200,
    headers: {
      "Content-Type": man.type || "video/mp4",
      "Content-Length": String(end - start + 1),
      "Accept-Ranges": "bytes",
      ...(partial ? { "Content-Range": `bytes ${start}-${end}/${size}` } : {}),
      "Cache-Control": "private, max-age=3600",
    },
  });
}
