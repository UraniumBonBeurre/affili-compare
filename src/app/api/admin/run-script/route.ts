import { NextRequest } from "next/server";
import { spawn, type ChildProcess } from "child_process";

export const dynamic = "force-dynamic";

// ── Validation ────────────────────────────────────────────────────────────────
const SAFE_ID  = /^[a-z0-9_-]{1,60}$/i;
const SAFE_INT = /^\d{1,7}$/;

type ScriptDef = {
  cmd:       string[];
  env?:      Record<string, string>;
  buildArgs: (p: URLSearchParams) => string[];
};

// ── Whitelist des scripts autorisés ──────────────────────────────────────────
const SCRIPTS: Record<string, ScriptDef> = {
  import: {
    cmd: ["python3", "recup_flux_awin.py"],
    env: { PYTHONUNBUFFERED: "1" },
    buildArgs: (p) => {
      const args: string[] = ["--mode", p.get("mode") === "reset_and_fill" ? "reset_and_fill" : "update"];
      const count = p.get("count");     if (count    && SAFE_INT.test(count))    args.push("--count",    count);
      const limit = p.get("limit");     if (limit    && SAFE_INT.test(limit))    args.push("--limit",    limit);
      const m     = p.get("merchant");  if (m        && SAFE_ID.test(m))         args.push("--merchant", m);
      if (p.get("force_download") === "1") args.push("--force-download");
      return args;
    },
  },

  classify: {
    cmd: ["python3", "classification.py"],
    env: { PYTHONUNBUFFERED: "1" },
    buildArgs: (p) => {
      const args: string[] = [];
      if (p.get("force") === "1") args.push("--force");
      const bs = p.get("batch_size"); if (bs && SAFE_INT.test(bs)) args.push("--batch-size", bs);
      const m  = p.get("merchant");   if (m  && SAFE_ID.test(m))   args.push("--merchant",   m);
      const lim = p.get("limit");     if (lim && SAFE_INT.test(lim)) args.push("--limit",    lim);
      return args;
    },
  },

  embeddings: {
    cmd: ["python3", "create_embeddings.py"],
    env: { PYTHONUNBUFFERED: "1", OMP_NUM_THREADS: "1", TOKENIZERS_PARALLELISM: "false" },
    buildArgs: (p) => {
      const args: string[] = [];
      if (p.get("force") === "1") args.push("--force");
      const lim = p.get("limit"); if (lim && SAFE_INT.test(lim)) args.push("--limit", lim);
      return args;
    },
  },

  "check-links": {
    cmd: ["python3", "check_links.py"],
    env: { PYTHONUNBUFFERED: "1" },
    buildArgs: (p) => {
      const args: string[] = [];
      if (p.get("dry_run") === "1") args.push("--dry-run");
      const w = p.get("workers");  if (w && SAFE_INT.test(w)) args.push("--workers", w);
      const m = p.get("merchant"); if (m && SAFE_ID.test(m))  args.push("--merchant", m);
      return args;
    },
  },

  "generate-articles": {
    cmd: ["python3", "generate_articles.py"],
    env: { PYTHONUNBUFFERED: "1" },
    buildArgs: (p) => {
      const args: string[] = [];
      const count = p.get("count");            if (count && SAFE_INT.test(count)) args.push("--count", count);
      const nb    = p.get("nb_produits");      if (nb    && SAFE_INT.test(nb))    args.push("--nb_produits", nb);
      const pins  = p.get("nb_variantes_pins"); if (pins  && SAFE_INT.test(pins))  args.push("--nb_variantes_pins", pins);
      const niche = p.get("niche");            if (niche && SAFE_ID.test(niche))  args.push("--niche", niche);
      const angle = p.get("angle");            if (angle && SAFE_ID.test(angle))  args.push("--angle", angle);
      const month = p.get("month");            if (month && SAFE_ID.test(month))  args.push("--month", month);
      const pub   = p.get("publish");
      if (pub === "local" || pub === "pinterest") args.push("--publish", pub);
      return args;
    },
  },
};

// ── Handler ───────────────────────────────────────────────────────────────────
export async function GET(req: NextRequest) {
  const params   = req.nextUrl.searchParams;
  const scriptId = params.get("script") ?? "";
  const def      = SCRIPTS[scriptId];
  if (!def) return new Response(`Script inconnu: ${scriptId}`, { status: 400 });

  const extraArgs = def.buildArgs(params);
  const cmd       = def.cmd[0];
  const args      = [...def.cmd.slice(1), ...extraArgs];
  const env       = { ...process.env, ...(def.env ?? {}) } as Record<string, string>;
  const cwd       = process.cwd();

  let child: ChildProcess | null = null;
  const killChild = () => { try { child?.kill("SIGTERM"); } catch { /* ignore */ } };
  req.signal.addEventListener("abort", killChild);

  const enc = (data: unknown, ctrl: ReadableStreamDefaultController) =>
    ctrl.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(data)}\n\n`));

  const stream = new ReadableStream({
    start(controller) {
      // Echo back the exact command being run
      enc({ log: `$ ${cmd} ${args.join(" ")}` }, controller);
      enc({ log: "" }, controller);

      child = spawn(cmd, args, { cwd, env });

      child.stdout?.on("data", (d: Buffer) => {
        for (const line of d.toString().split("\n"))
          enc({ log: line }, controller);
      });

      child.stderr?.on("data", (d: Buffer) => {
        for (const line of d.toString().split("\n"))
          enc({ err: line }, controller);
      });

      child.on("close", (code) => {
        enc({ exit: code ?? 1 }, controller);
        controller.close();
      });

      child.on("error", (e) => {
        enc({ err: String(e) }, controller);
        enc({ exit: 1 }, controller);
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
