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
  };
  rollbackOnFail?: boolean;
  rollbackStrategy?: "git-restore" | "git-stash-pop" | "custom-script";
  customRollbackScript?: string;
}

export interface TestRunResult {
  run: TestRun | null;
  success: boolean;
  rollbackTriggered: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
  durationMs: number;
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

export function runTests(
  ctx: PluginContext,
  opts: TestOptions
): TestRunResult {
  const start = Date.now();
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
  };
}
