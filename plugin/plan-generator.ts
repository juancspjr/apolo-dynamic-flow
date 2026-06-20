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
}

const GENERATE_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "generate_plan.py"
);

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
  };
}
