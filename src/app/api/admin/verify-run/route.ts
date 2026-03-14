import { NextRequest } from "next/server";
import { spawn, ChildProcess } from "child_process";
import { join } from "path";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const limit  = searchParams.get("limit");
  const dryRun = searchParams.get("dry-run") === "1";

  const args = ["verify_classification.py"];
  if (limit)  args.push("--limit", limit);
  if (dryRun) args.push("--dry-run");

  const cwd     = join(process.cwd());
  const encoder = new TextEncoder();
  let child: ChildProcess | null = null;

  const killChild = () => { try { child?.kill("SIGTERM"); } catch { /* ignore */ } };
  req.signal.addEventListener("abort", killChild);

  const stream = new ReadableStream({
    start(controller) {
      child = spawn("python3", args, { cwd });

      child.stdout!.on("data", (chunk: Buffer) => {
        const text  = chunk.toString();
        const lines = text.split("\n");
        for (const line of lines) {
          if (!line.trim()) continue;
          controller.enqueue(encoder.encode(`data: ${JSON.stringify({ log: line })}\n\n`));
        }
      });

      child.stderr!.on("data", (chunk: Buffer) => {
        const text = chunk.toString().trim();
        if (text) {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify({ err: text })}\n\n`));
        }
      });

      child.on("close", (code) => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ exit: code ?? 0 })}\n\n`));
        controller.close();
      });

      child.on("error", (err) => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ err: err.message, exit: 1 })}\n\n`));
        controller.close();
      });
    },
    cancel() { killChild(); },
  });

  return new Response(stream, {
    headers: {
      "Content-Type":  "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection":    "keep-alive",
    },
  });
}

