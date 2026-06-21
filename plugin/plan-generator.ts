/**
 * plan-generator.ts — Wrapper TS que invoca scripts/python/generate_plan.py.
 *
 * El plan se genera deterministamente desde el evidence pack + verdad artifact.
 * El script Python:
 *   1. Lee EVIDENCE-PACK.yaml + 02-VERDAD.yaml
 *   2. Aplica heurísticas de partición (una unidad = un eje dominante)
 *   3. Genera topological_sort con Kahn's algorithm
 *   4. Configura adaptative_gates
 *   5. Escribe DYNAMIC-PLAN.yaml
 *
 * Si el orquestador detecta que el plan es insuficiente, incrementa versión
 * (parent_version = versión anterior) y re-genera con nuevos parámetros.
 */

import { spawnSync } from "child_process";
import * as path from "path";
import type { PluginContext } from "./types";
import { readYaml, writeYaml, now, ensureDir } from "./utils";

export interface GenerateOptions {
  evidencePackPath: string;
  verdadPath: string;
  parentVersion?: number; // si es rewrite, versión padre
  partitionHints?: string[]; // ej: "split U-02 by concern"
  derivationMethod?: "deterministic-python" | "hybrid" | "manual";
  // v2.2.0 — controlan invocación automática de predict_impact.py
  run_impact_prediction?: boolean; // default true (requiere code_index)
  codeIndexPath?: string; // .opencode/apolo-dynamic/CODE-INDEX.yaml
  telemetryPath?: string; // plan/active/<FLOW>/telemetry.jsonl
  testRunsDir?: string; // plan/active/<FLOW>/tests/
  deepImpact?: boolean; // --deep en predict_impact
}

export interface GenerateResult {
  planPath: string;
  version: number;
  success: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
  durationMs: number;
  units: number;
  topologicalOrder: string[];
  // v2.2.0 — resultado de predict_impact (si se invocó)
  impactPrediction?: RunImpactPredictionResult;
}

export interface RunImpactPredictionOptions {
  planPath: string;
  codeIndexPath?: string;
  telemetryPath?: string;
  testRunsDir?: string;
  outputPath?: string;
  deep?: boolean;
}

export interface RunImpactPredictionResult {
  success: boolean;
  global_risk: string;
  total_predictions: number;
  duration_ms: number;
  outputPath: string;
  risk_distribution?: Record<string, number>;
  stdout: string;
  stderr: string;
}

const GENERATE_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "generate_plan.py"
);

const PREDICT_IMPACT_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "predict_impact.py"
);

// ============================================================================
// v2.2.0 — Wrapper para predict_impact.py
// ============================================================================

/**
 * Invoca scripts/python/predict_impact.py para generar IMPACT-PREDICTION.yaml.
 * GAP 3: hologramas y predicción de soluciones.
 */
export function runImpactPrediction(
  ctx: PluginContext,
  opts: RunImpactPredictionOptions
): RunImpactPredictionResult {
  const start = Date.now();
  const outputPath =
    opts.outputPath ||
    path.join(path.dirname(opts.planPath), "IMPACT-PREDICTION.yaml");
  ensureDir(path.dirname(outputPath));

  const args = [
    PREDICT_IMPACT_SCRIPT,
    "--plan",
    opts.planPath,
    "--repo-root",
    ctx.repoRoot,
    "--output",
    outputPath,
    "--flowid",
    ctx.flowid,
  ];
  if (opts.codeIndexPath) args.push("--code-index", opts.codeIndexPath);
  if (opts.telemetryPath) args.push("--telemetry", opts.telemetryPath);
  if (opts.testRunsDir) args.push("--test-runs-dir", opts.testRunsDir);
  if (opts.deep) args.push("--deep", "true");

  const result = spawnSync("python3", args, {
    encoding: "utf8",
    timeout: 120000,
    maxBuffer: 10 * 1024 * 1024,
  });

  const durationMs = Date.now() - start;
  // predict_impact.py returns exit 1 when global_risk == "high" but JSON is valid.
  const ran = result.status !== null;
  let global_risk = "unknown";
  let total_predictions = 0;
  let risk_distribution: Record<string, number> | undefined;

  if (ran && result.stdout) {
    try {
      const parsed = JSON.parse(result.stdout);
      global_risk = parsed.global_risk ?? "unknown";
      total_predictions = parsed.total_predictions ?? 0;
      risk_distribution = parsed.risk_distribution;
    } catch {
      const lines = result.stdout
        .split("\n")
        .filter((l) => l.trim().startsWith("{"));
      if (lines.length > 0) {
        try {
          const parsed = JSON.parse(lines[lines.length - 1]);
          global_risk = parsed.global_risk ?? "unknown";
          total_predictions = parsed.total_predictions ?? 0;
          risk_distribution = parsed.risk_distribution;
        } catch {
          /* ignore */
        }
      }
    }
  }

  const success = ran && global_risk !== "unknown";

  ctx.emit({
    kind: "plan-version-bump",
    phase: "plan-indice",
    severity: success ? (global_risk === "high" ? "warn" : "info") : "error",
    message: success
      ? `impact-prediction: ${total_predictions} MPs, global_risk=${global_risk} en ${durationMs}ms`
      : `fallo predict_impact: ${result.stderr?.slice(0, 200)}`,
    payload: {
      global_risk,
      total_predictions,
      risk_distribution,
      duration_ms: durationMs,
      output: outputPath,
    },
    duration_ms: durationMs,
  });

  return {
    success,
    global_risk,
    total_predictions,
    duration_ms: durationMs,
    outputPath,
    risk_distribution,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

export function generatePlan(
  ctx: PluginContext,
  opts: GenerateOptions
): GenerateResult {
  const start = Date.now();
  const planPath = path.join(
    path.dirname(ctx.evidencePath),
    "..",
    "03-PLAN-INDICE-DYNAMIC.yaml"
  );
  ensureDir(path.dirname(planPath));

  const args = [
    GENERATE_SCRIPT,
    "--flowid",
    ctx.flowid,
    "--evidence",
    opts.evidencePackPath,
    "--verdad",
    opts.verdadPath,
    "--output",
    planPath,
    "--method",
    opts.derivationMethod ?? "deterministic-python",
  ];
  if (opts.parentVersion) {
    args.push("--parent-version", String(opts.parentVersion));
  }
  if (opts.partitionHints && opts.partitionHints.length > 0) {
    args.push("--partition-hints", JSON.stringify(opts.partitionHints));
  }

  const result = spawnSync("python3", args, {
    encoding: "utf8",
    timeout: 60000,
  });

  const durationMs = Date.now() - start;
  const success = result.status === 0;

  let version = 1;
  let units = 0;
  let topologicalOrder: string[] = [];
  if (success) {
    const plan = readYaml<{
      version: number;
      unidades: Array<{ id: string }>;
      topological_sort: Array<{ order: number; unit_id: string }>;
    }>(planPath);
    if (plan) {
      version = plan.version;
      units = plan.unidades.length;
      topologicalOrder = plan.topological_sort
        .sort((a, b) => a.order - b.order)
        .map((t) => t.unit_id);
    }
  }

  ctx.emit({
    kind: "plan-version-bump",
    phase: "plan-indice",
    severity: success ? "info" : "error",
    message: success
      ? `plan v${version} generado: ${units} unidades`
      : `fallo generación: ${result.stderr?.slice(0, 200)}`,
    payload: {
      plan_path: planPath,
      version,
      units,
      topological_order: topologicalOrder,
      duration_ms: durationMs,
      parent_version: opts.parentVersion ?? null,
    },
    duration_ms: durationMs,
  });

  // ============================================================================
  // v2.2.0 — Invocación automática de predict_impact.py
  // ============================================================================
  let impactPrediction: RunImpactPredictionResult | undefined;
  if (success && opts.run_impact_prediction !== false && opts.codeIndexPath) {
    try {
      impactPrediction = runImpactPrediction(ctx, {
        planPath,
        codeIndexPath: opts.codeIndexPath,
        telemetryPath: opts.telemetryPath,
        testRunsDir: opts.testRunsDir,
        deep: opts.deepImpact,
      });
    } catch (e) {
      ctx.emit({
        kind: "plan-version-bump",
        phase: "plan-indice",
        severity: "warn",
        message: `predict_impact invocación falló: ${(e as Error).message?.slice(0, 200)}`,
      });
    }
  }

  return {
    planPath,
    version,
    success,
    exitCode: result.status ?? -1,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    durationMs,
    units,
    topologicalOrder,
    impactPrediction,
  };
}
