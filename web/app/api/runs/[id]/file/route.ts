// One file of one of your runs, from Blob (owner only).
import { auth } from "@clerk/nextjs/server";
import { get } from "@vercel/blob";
import { myRun } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { userId } = await auth();
  if (!userId) return new Response("sign in first", { status: 401 });
  const { id } = await params;
  const run = await myRun(userId, id);
  if (!run?.blob_folder_path) return new Response("not found", { status: 404 });
  const path = new URL(req.url).searchParams.get("path") ?? "";
  if (!path || path.split("/").some((p) => !p || p === "..")) return new Response("bad path", { status: 400 });
  const got = await get(`${run.blob_folder_path}${path}`, { access: "private" });
  if (!got) return new Response("not found", { status: 404 });
  const name = path.split("/").pop() ?? "file";
  return new Response(got.stream, {
    headers: {
      "Content-Type": got.blob.contentType ?? "application/octet-stream",
      "Content-Disposition": `${new URL(req.url).searchParams.has("download") ? "attachment" : "inline"}; filename="${name.replace(/"/g, "")}"`,
      "Cache-Control": "private, no-store",
    },
  });
}
