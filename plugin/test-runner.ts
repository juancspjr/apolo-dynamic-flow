/**
 * test-runner.ts — Wrapper TS que invoca scripts/python/run_tests.py.
 *
 * Filosofía: tras cada micro-cambio o sección de cambios, ejecutar tests
 * deterministas. Si fallan y el cambio fue micro → rollback automático.
 *
 * Trigger levels:
 *   - micro-change: tras 1 edición pequeña (1-3 líneas)
 *   - section-change: tras un MP completo
 *   - full-plan: tras todos los MPs
 *   - pre-merge: antes de cerrar el flow
 */

import { spawnSync } from "child_process";
import * as path from "path";
import type { PluginContext, TestRun, TestTrigger } from "./types";
import { readYaml, now, ensureDir } from "./utils";

export interface TestOptions {
  trigger: TestTrigger;
  scope: {
    kind: "unit" | "integration" | "mutation" | "e2e" | "contract" | "schema-validation";
    targets: string[]; // símbolos, archivos, endpoints
    mpId?: string;
    // v2.2.0 — si se pasa, invoca scaffold_impl.py antes de correr tests
    unit_id?: string;
    plan_path?: string; // DYNAMIC-PLAN.yaml
    code_index_path?: string; // CODE-INDEX.yaml
    impact_prediction_path?: string; // IMPACT-PREDICTION.yaml
  };
  rollbackOnFail?: boolean;
  rollbackStrategy?: "git-restore" | "git-stash-pop" | "custom-script";
  customRollbackScript?: string;
}

// v2.2.0 — Scaffold support
export interface RunScaffoldOptions {
  planPath: string;
  unitId: string;
  codeIndexPath?: string;
  impactPredictionPath?: string;
  outputPath?: string;
}

export interface RunScaffoldResult {
  success: boolean;
  verdict: string;
  total_files: number;
  total_checkpoints: number;
  has_circular_deps: boolean;
  duration_ms: number;
  outputPath: string;
  stdout: string;
  stderr: string;
}

export interface TestRunResult {
  run: TestRun | null;
  success: boolean;
  rollbackTriggered: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
  durationMs: number;
  // v2.2.0 — resultado del scaffold (si se invocó)
  scaffold?: RunScaffoldResult;
}

const TEST_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "run_tests.py"
);

const ROLLBACK_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "rollback.py"
);

const SCAFFOLD_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "scaffold_impl.py"
);

// ============================================================================
// v2.2.0 — Wrapper para scaffold_impl.py
// ============================================================================

/**
 * Invoca scripts/python/scaffold_impl.py para generar IMPL-SCAFFOLD-<U-XX>.yaml.
 * GAP 4: apoyo activo a la implementación.
 */
export function runScaffold(
  ctx: PluginContext,
  opts: RunScaffoldOptions
): RunScaffoldResult {
  const start = Date.now();
  const safeUnit = opts.unitId.replace(/[^A-Za-z0-9-]/g, "");
  const outputPath =
    opts.outputPath ||
    path.join(
      path.dirname(opts.planPath),
      `IMPL-SCAFFOLD-${safeUnit}.yaml`
    );
  ensureDir(path.dirname(outputPath));

  const args = [
    SCAFFOLD_SCRIPT,
    "--plan",
    opts.planPath,
    "--unit-id",
    opts.unitId,
    "--output",
    outputPath,
    "--flowid",
    ctx.flowid,
  ];
  if (opts.codeIndexPath) args.push("--code-index", opts.codeIndexPath);
  if (opts.impactPredictionPath)
    args.push("--impact-prediction", opts.impactPredictionPath);

  const result = spawnSync("python3", args, {
    encoding: "utf8",
    timeout: 60000,
    maxBuffer: 10 * 1024 * 1024,
  });

  const durationMs = Date.now() - start;
  // scaffold_impl.py returns exit 1 when verdict != "proceed" but JSON is valid.
  const ran = result.status !== null;
  let verdict = "error";
  let total_files = 0;
  let total_checkpoints = 0;
  let has_circular_deps = false;

  if (ran && result.stdout) {
    try {
      const parsed = JSON.parse(result.stdout);
      verdict = parsed.verdict ?? "error";
      total_files = parsed.total_files ?? 0;
      total_checkpoints = parsed.total_checkpoints ?? 0;
      has_circular_deps = parsed.has_circular_deps ?? false;
    } catch {
      const lines = result.stdout
        .split("\n")
        .filter((l) => l.trim().startsWith("{"));
      if (lines.length > 0) {
        try {
          const parsed = JSON.parse(lines[lines.length - 1]);
          verdict = parsed.verdict ?? "error";
          total_files = parsed.total_files ?? 0;
          total_checkpoints = parsed.total_checkpoints ?? 0;
          has_circular_deps = parsed.has_circular_deps ?? false;
        } catch {
          /* ignore */
        }
      }
    }
  }

  const success = ran && verdict !== "error";

  ctx.emit({
    kind: success ? "test-run" : "test-fail",
    phase: "implementation",
    severity: success
      ? verdict === "proceed"
        ? "info"
        : "warn"
      : "error",
    message: success
      ? `scaffold ${opts.unitId}: verdict=${verdict}, ${total_files} archivos, ${total_checkpoints} checkpoints (circular=${has_circular_deps})`
      : `fallo scaffold_impl: ${result.stderr?.slice(0, 200)}`,
    payload: {
      unit_id: opts.unitId,
      verdict,
      total_files,
      total_checkpoints,
      has_circular_deps,
      duration_ms: durationMs,
      output: outputPath,
    },
    duration_ms: durationMs,
  });

  return {
    success,
    verdict,
    total_files,
    total_checkpoints,
    has_circular_deps,
    duration_ms: durationMs,
    outputPath,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

export function runTests(
  ctx: PluginContext,
  opts: TestOptions
): TestRunResult {
  const start = Date.now();

  // ============================================================================
  // v2.2.0 — Si se pasa unit_id + plan_path, invocar scaffold_impl.py primero
  // ============================================================================
  let scaffold: RunScaffoldResult | undefined;
  if (opts.scope.unit_id && opts.scope.plan_path) {
    try {
      scaffold = runScaffold(ctx, {
        planPath: opts.scope.plan_path,
        unitId: opts.scope.unit_id,
        codeIndexPath: opts.scope.code_index_path,
        impactPredictionPath: opts.scope.impact_prediction_path,
      });
      // Si el scaffold detecta dependencias circulares, no correr tests
      if (scaffold.has_circular_deps) {
        ctx.emit({
          kind: "test-fail",
          phase: "implementation",
          severity: "critical",
          message: `scaffold ${opts.scope.unit_id}: block-circular-deps — tests no ejecutados`,
          payload: {
            unit_id: opts.scope.unit_id,
            verdict: scaffold.verdict,
            has_circular_deps: true,
          },
        });
        return {
          run: null,
          success: false,
          rollbackTriggered: false,
          exitCode: -1,
          stdout: "",
          stderr: `scaffold ${opts.scope.unit_id} bloqueado: dependencias circulares`,
          durationMs: Date.now() - start,
          scaffold,
        };
      }
    } catch (e) {
      ctx.emit({
        kind: "test-fail",
        phase: "implementation",
        severity: "warn",
        message: `scaffold invocación falló (continuando con tests): ${(e as Error).message?.slice(0, 200)}`,
      });
    }
  }

  const runId = `run-${Date.now()}`;
  const outPath = path.join(
    path.dirname(ctx.evidencePath),
    "..",
    "tests",
    `${runId}.yaml`
  );
  ensureDir(path.dirname(outPath));

  const args = [
    TEST_SCRIPT,
    "--flowid",
    ctx.flowid,
    "--repo-root",
    ctx.repoRoot,
    "--output",
    outPath,
    "--trigger",
    opts.trigger,
    "--kind",
    opts.scope.kind,
    "--targets-json",
    JSON.stringify(opts.scope.targets),
  ];
  if (opts.scope.mpId) {
    args.push("--mp-id", opts.scope.mpId);
  }

  const result = spawnSync("python3", args, {
    encoding: "utf8",
    timeout: 300000, // 5 min máximo
    maxBuffer: 50 * 1024 * 1024,
  });

  const durationMs = Date.now() - start;
  const success = result.status === 0;

  let run: TestRun | null = null;
  if (success || result.status === 1) {
    // status 1 = tests corrieron pero algunos fallaron; aún escribimos el YAML
    run = readYaml<TestRun>(outPath);
  }

  let rollbackTriggered = false;
  if (
    !success &&
    opts.rollbackOnFail &&
    run &&
    run.summary.failed > 0 &&
    (opts.trigger === "micro-change" || opts.trigger === "section-change")
  ) {
    // Disparar rollback
    const rbArgs = [
      ROLLBACK_SCRIPT,
      "--repo-root",
      ctx.repoRoot,
      "--strategy",
      opts.rollbackStrategy ?? "git-restore",
    ];
    if (opts.customRollbackScript) {
      rbArgs.push("--custom-script", opts.customRollbackScript);
    }
    if (opts.scope.mpId) {
      rbArgs.push("--mp-id", opts.scope.mpId);
    }
    const rbResult = spawnSync("python3", rbArgs, {
      encoding: "utf8",
      timeout: 60000,
    });
    rollbackTriggered = rbResult.status === 0;
    if (run) {
      run.rollback_triggered = rollbackTriggered;
      run.rollback_log = rbResult.stdout;
    }
  }

  ctx.emit({
    kind: success ? "test-run" : "test-fail",
    phase: "implementation",
    severity: success ? "info" : "error",
    message: success
      ? `tests pass: ${run?.summary.passed}/${run?.summary.total}`
      : `tests fail: ${run?.summary.failed} failed de ${run?.summary.total}`,
    payload: {
      run_id: runId,
      trigger: opts.trigger,
      kind: opts.scope.kind,
      targets: opts.scope.targets,
      summary: run?.summary,
      rollback_triggered: rollbackTriggered,
      duration_ms: durationMs,
    },
    duration_ms: durationMs,
  });

  if (rollbackTriggered) {
    ctx.emit({
      kind: "rollback",
      phase: "implementation",
      severity: "warn",
      message: `rollback aplicado tras test fail (mp=${opts.scope.mpId ?? "n/a"})`,
    });
  }

  return {
    run,
    success,
    rollbackTriggered,
    exitCode: result.status ?? -1,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    durationMs,
    scaffold,
  };
}
