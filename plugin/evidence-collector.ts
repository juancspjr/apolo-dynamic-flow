/**
 * evidence-collector.ts — Wrapper TS que invoca scripts/python/collect_evidence.py.
 *
 * La recolección es 100% determinista: el script Python hace todo el trabajo
 * (snapshot archivos, git diff, símbolos, curl, screenshots si playwright,
 * etc.) y retorna un EVIDENCE-PACK.yaml conforme al schema.
 *
 * El orquestador TS no piensa — solo invoca y consume.
 */

import { spawnSync } from "child_process";
import * as path from "path";
import type { EvidencePack, PluginContext } from "./types";
import { readYaml, now, ensureDir, hashFile } from "./utils";

export interface CollectOptions {
  scope: {
    paths?: string[]; // archivos a snapshot
    symbols?: string[]; // símbolos a inspeccionar con LSP
    endpoints?: string[]; // endpoints a probe con curl
    git_diff?: boolean; // incluir git diff
    git_log?: boolean; // incluir git log reciente
    db_queries?: string[]; // queries SQL para psql
    screenshots?: string[]; // URLs para screenshot si playwright
  };
  invokedBy: string; // agente que pide la recolección
}

export interface CollectResult {
  pack: EvidencePack | null;
  success: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
  durationMs: number;
}

const COLLECT_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "collect_evidence.py"
);

export function collectEvidence(
  ctx: PluginContext,
  opts: CollectOptions
): CollectResult {
  const start = Date.now();
  ensureDir(path.dirname(ctx.evidencePath));

  const args = [
    COLLECT_SCRIPT,
    "--flowid",
    ctx.flowid,
    "--repo-root",
    ctx.repoRoot,
    "--output",
    ctx.evidencePath,
    "--invoked-by",
    opts.invokedBy,
    "--scope-json",
    JSON.stringify(opts.scope),
  ];

  const result = spawnSync("python3", args, {
    encoding: "utf8",
    timeout: 120000, // 2 min máximo
    maxBuffer: 10 * 1024 * 1024,
  });

  const durationMs = Date.now() - start;
  const success = result.status === 0;

  let pack: EvidencePack | null = null;
  if (success) {
    pack = readYaml<EvidencePack>(ctx.evidencePath);
  }

  ctx.emit({
    kind: "evidence-captured",
    phase: "verdad",
    severity: success ? "info" : "error",
    message: success
      ? `evidence pack generado: ${pack?.items.length ?? 0} items en ${durationMs}ms`
      : `fallo recolección: ${result.stderr?.slice(0, 200)}`,
    payload: {
      items: pack?.items.length ?? 0,
      hash_chain: pack?.hash_chain,
      capabilities: pack?.capabilities,
      duration_ms: durationMs,
    },
    duration_ms: durationMs,
  });

  return {
    pack,
    success,
    exitCode: result.status ?? -1,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    durationMs,
  };
}

/**
 * Verifica si el evidence pack actual sigue siendo válido
 * (no ha habido cambios en el repo desde su captura).
 */
export function isEvidenceStale(
  ctx: PluginContext,
  pack: EvidencePack
): boolean {
  const fileSnapshots = pack.items.filter((i) => i.kind === "file-snapshot");
  for (const snap of fileSnapshots) {
    try {
      const fullPath = path.join(ctx.repoRoot, snap.source);
      const currentHash = hashFile(fullPath);
      if (currentHash !== snap.hash) {
        return true; // cambió → stale
      }
    } catch {
      return true; // archivo desapareció → stale
    }
  }
  return false;
}
