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
    // v2.2.0 — controlan invocación automática de index_codebase.py y score_evidence.py
    run_code_index?: boolean; // default true
    run_score?: boolean; // default true (requiere verdad_path)
    verdad_path?: string; // path a 02-VERDAD.yaml para scoring
    code_index_path?: string; // override path CODE-INDEX.yaml
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

const INDEX_CODEBASE_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "index_codebase.py"
);

const SCORE_EVIDENCE_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "score_evidence.py"
);

// ============================================================================
// v2.2.0 — Wrappers para index_codebase.py y score_evidence.py
// ============================================================================

export interface RunCodeIndexOptions {
  outputPath?: string; // default: <repoRoot>/.opencode/apolo-dynamic/CODE-INDEX.yaml
  include?: string; // coma-separated globs (override defaults)
  exclude?: string; // coma-separated globs (override defaults)
}

export interface RunCodeIndexResult {
  success: boolean;
  files_indexed: number;
  index_hash: string;
  duration_ms: number;
  outputPath: string;
  stdout: string;
  stderr: string;
}

/**
 * Invoca scripts/python/index_codebase.py para generar CODE-INDEX.yaml.
 * GAP 1: comprensión rápida de código sin discrepancia.
 */
export function runCodeIndex(
  ctx: PluginContext,
  opts: RunCodeIndexOptions = {}
): RunCodeIndexResult {
  const start = Date.now();
  const outputPath =
    opts.outputPath ||
    path.join(ctx.repoRoot, ".opencode", "apolo-dynamic", "CODE-INDEX.yaml");
  ensureDir(path.dirname(outputPath));

  const args = [
    INDEX_CODEBASE_SCRIPT,
    "--repo-root",
    ctx.repoRoot,
    "--output",
    outputPath,
  ];
  if (opts.include) args.push("--include", opts.include);
  if (opts.exclude) args.push("--exclude", opts.exclude);

  const result = spawnSync("python3", args, {
    encoding: "utf8",
    timeout: 120000,
    maxBuffer: 10 * 1024 * 1024,
  });

  const durationMs = Date.now() - start;
  const success = result.status === 0;

  let files_indexed = 0;
  let index_hash = "";
  if (success && result.stdout) {
    try {
      const parsed = JSON.parse(result.stdout);
      files_indexed = parsed.files_indexed ?? 0;
      index_hash = parsed.index_hash ?? "";
    } catch {
      // El script puede emitir logs adicionales antes del JSON — intentar extraer la última línea JSON
      const lines = result.stdout.split("\n").filter((l) => l.trim().startsWith("{"));
      if (lines.length > 0) {
        try {
          const parsed = JSON.parse(lines[lines.length - 1]);
          files_indexed = parsed.files_indexed ?? 0;
          index_hash = parsed.index_hash ?? "";
        } catch {
          /* ignore */
        }
      }
    }
  }

  ctx.emit({
    kind: "evidence-captured",
    phase: "verdad",
    severity: success ? "info" : "error",
    message: success
      ? `code-index generado: ${files_indexed} archivos en ${durationMs}ms`
      : `fallo index_codebase: ${result.stderr?.slice(0, 200)}`,
    payload: {
      files_indexed,
      index_hash,
      duration_ms: durationMs,
      output: outputPath,
    },
    duration_ms: durationMs,
  });

  return {
    success,
    files_indexed,
    index_hash,
    duration_ms: durationMs,
    outputPath,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

export interface RunEvidenceScoreOptions {
  evidencePath: string; // EVIDENCE-PACK.yaml
  verdadPath: string; // 02-VERDAD.yaml
  codeIndexPath?: string; // CODE-INDEX.yaml (opcional)
  outputPath?: string; // default: junto al evidence pack, EVIDENCE-SCORE.yaml
}

export interface RunEvidenceScoreResult {
  success: boolean;
  overall_score: number;
  severity: string;
  should_block_agent: boolean;
  should_recollect: boolean;
  duration_ms: number;
  outputPath: string;
  stdout: string;
  stderr: string;
}

/**
 * Invoca scripts/python/score_evidence.py para puntuar el evidence pack.
 * GAP 2: calidad y suficiencia de evidencia.
 */
export function runEvidenceScore(
  ctx: PluginContext,
  opts: RunEvidenceScoreOptions
): RunEvidenceScoreResult {
  const start = Date.now();
  const outputPath =
    opts.outputPath ||
    path.join(path.dirname(opts.evidencePath), "EVIDENCE-SCORE.yaml");
  ensureDir(path.dirname(outputPath));

  const args = [
    SCORE_EVIDENCE_SCRIPT,
    "--evidence",
    opts.evidencePath,
    "--verdad",
    opts.verdadPath,
    "--output",
    outputPath,
    "--flowid",
    ctx.flowid,
  ];
  if (opts.codeIndexPath) {
    args.push("--code-index", opts.codeIndexPath);
  }

  const result = spawnSync("python3", args, {
    encoding: "utf8",
    timeout: 60000,
  });

  const durationMs = Date.now() - start;
  // score_evidence.py returns exit 1 when severity == "critical", but the JSON
  // is still valid. Tratar status != null como "el script corrió".
  const ran = result.status !== null;
  let overall_score = 0;
  let severity = "error";
  let should_block_agent = false;
  let should_recollect = false;

  if (ran && result.stdout) {
    try {
      const parsed = JSON.parse(result.stdout);
      overall_score = parsed.overall_score ?? 0;
      severity = parsed.severity ?? "info";
      should_block_agent = parsed.should_block_agent ?? false;
      should_recollect = parsed.should_recollect ?? false;
    } catch {
      const lines = result.stdout.split("\n").filter((l) => l.trim().startsWith("{"));
      if (lines.length > 0) {
        try {
          const parsed = JSON.parse(lines[lines.length - 1]);
          overall_score = parsed.overall_score ?? 0;
          severity = parsed.severity ?? "info";
          should_block_agent = parsed.should_block_agent ?? false;
          should_recollect = parsed.should_recollect ?? false;
        } catch {
          /* ignore */
        }
      }
    }
  }

  // success = el script se ejecutó y la severity no es crítica
  const success = ran && severity !== "error";

  ctx.emit({
    kind: "evidence-captured",
    phase: "verdad",
    severity: should_block_agent ? "critical" : severity === "warning" || severity === "warn" ? "warn" : "info",
    message: `evidence-score: overall=${overall_score.toFixed(3)} severity=${severity} (block=${should_block_agent} recollect=${should_recollect})`,
    payload: {
      overall_score,
      severity,
      should_block_agent,
      should_recollect,
      duration_ms: durationMs,
      output: outputPath,
    },
    duration_ms: durationMs,
  });

  return {
    success,
    overall_score,
    severity,
    should_block_agent,
    should_recollect,
    duration_ms: durationMs,
    outputPath,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

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

  // ============================================================================
  // v2.2.0 — Invocación automática de index_codebase.py y score_evidence.py
  // ============================================================================
  if (success) {
    // 1. runCodeIndex (si opts.scope.run_code_index !== false)
    if (opts.scope.run_code_index !== false) {
      try {
        const idxResult = runCodeIndex(ctx, {
          outputPath: opts.scope.code_index_path,
        });
        // Si hay verdad_path y run_score !== false, encadenar con score_evidence
        if (
          idxResult.success &&
          opts.scope.run_score !== false &&
          opts.scope.verdad_path
        ) {
          try {
            runEvidenceScore(ctx, {
              evidencePath: ctx.evidencePath,
              verdadPath: opts.scope.verdad_path,
              codeIndexPath: idxResult.outputPath,
            });
          } catch (e) {
            ctx.emit({
              kind: "evidence-captured",
              phase: "verdad",
              severity: "warn",
              message: `evidence-score invocación falló: ${(e as Error).message?.slice(0, 200)}`,
            });
          }
        }
      } catch (e) {
        ctx.emit({
          kind: "evidence-captured",
          phase: "verdad",
          severity: "warn",
          message: `code-index invocación falló: ${(e as Error).message?.slice(0, 200)}`,
        });
      }
    } else if (
      opts.scope.run_score !== false &&
      opts.scope.verdad_path
    ) {
      // Sin code-index pero con verdad_path → invocar score sin code-index
      try {
        runEvidenceScore(ctx, {
          evidencePath: ctx.evidencePath,
          verdadPath: opts.scope.verdad_path,
        });
      } catch (e) {
        ctx.emit({
          kind: "evidence-captured",
          phase: "verdad",
          severity: "warn",
          message: `evidence-score invocación falló: ${(e as Error).message?.slice(0, 200)}`,
        });
      }
    }
  }

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
