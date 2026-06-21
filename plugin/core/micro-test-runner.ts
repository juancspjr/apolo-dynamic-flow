/**
 * micro-test-runner.ts — Ejecutor determinista de micro-tests por MP.
 *
 * Extrae el `comando` del microplan YAML y lo ejecuta vía `spawnSync("bash", ...)`
 * con timeout de 60s. Devuelve resultado estructurado + loguea al runtime-logger.
 *
 * Soporta dos notaciones en el YAML del MP:
 *   - camelCase: `criteriodeadmision.testdeverdad.comando`
 *   - snake_case: `criterio_de_admision.test_de_verdad.comando`
 *
 * Fallback recursivo: busca cualquier key `comando` o `command` en el árbol.
 *
 * Conforme al schema: schemas/json/runtime-audit-log.json (action: test_executed)
 */

import * as fs from "fs";
import { spawnSync } from "child_process";
import { log as auditLog } from "./runtime-logger";

// ============================================================================
// Types
// ============================================================================

export interface TestRunResult {
  passed: boolean;
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_ms: number;
}

// ============================================================================
// Minimalist YAML parser (sin dependencia externa)
// ============================================================================

interface YamlNode {
  [key: string]: unknown;
}

function parseYaml(text: string): unknown {
  const lines = text.split("\n");
  const root: YamlNode = {};
  const stack: Array<{ indent: number; node: any }> = [
    { indent: -1, node: root },
  ];

  for (const rawLine of lines) {
    const line = rawLine.replace(/\s+$/, "");
    if (!line || line.trim().startsWith("#")) continue;
    const indent = line.length - line.trimStart().length;
    const trimmed = line.trim();

    while (stack.length > 1 && stack[stack.length - 1].indent >= indent) {
      stack.pop();
    }
    const parent = stack[stack.length - 1].node;

    if (trimmed.startsWith("- ")) {
      const value = trimmed.slice(2).trim();
      if (!Array.isArray(parent)) continue;
      if (value.includes(": ")) {
        const obj: YamlNode = {};
        const idx = value.indexOf(": ");
        const k = value.slice(0, idx).trim();
        obj[k] = parseScalar(value.slice(idx + 2).trim());
        parent.push(obj);
        stack.push({ indent: indent + 2, node: obj });
      } else {
        parent.push(parseScalar(value));
      }
      continue;
    }

    if (trimmed.includes(": ")) {
      const idx = trimmed.indexOf(": ");
      const key = trimmed.slice(0, idx).trim();
      const value = trimmed.slice(idx + 2).trim();
      if (value === "") {
        const child: YamlNode = {};
        parent[key] = child;
        stack.push({ indent: indent + 2, node: child });
      } else if (value === "[]") {
        parent[key] = [];
      } else if (value === "{}") {
        parent[key] = {};
      } else {
        parent[key] = parseScalar(value);
      }
    } else if (trimmed.endsWith(":")) {
      const key = trimmed.slice(0, -1).trim();
      const child: YamlNode = {};
      parent[key] = child;
      stack.push({ indent: indent + 2, node: child });
    }
  }
  return root;
}

function parseScalar(raw: string): unknown {
  if (raw === "null" || raw === "~") return null;
  if (raw === "true") return true;
  if (raw === "false") return false;
  if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
  if (/^-?\d+\.\d+$/.test(raw)) return parseFloat(raw);
  if (
    (raw.startsWith('"') && raw.endsWith('"')) ||
    (raw.startsWith("'") && raw.endsWith("'"))
  ) {
    return raw.slice(1, -1);
  }
  return raw;
}

// ============================================================================
// Command extraction
// ============================================================================

function findKeyRecursive(obj: unknown, keys: string[]): string | null {
  if (obj === null || obj === undefined) return null;
  if (typeof obj === "string") return null;
  if (typeof obj !== "object") return null;

  if (Array.isArray(obj)) {
    for (const item of obj) {
      const found = findKeyRecursive(item, keys);
      if (found) return found;
    }
    return null;
  }

  const record = obj as Record<string, unknown>;
  for (const k of Object.keys(record)) {
    const lower = k.toLowerCase();
    if (keys.includes(lower)) {
      const v = record[k];
      if (typeof v === "string" && v.trim().length > 0) return v;
    }
  }
  // Recurse
  for (const k of Object.keys(record)) {
    const found = findKeyRecursive(record[k], keys);
    if (found) return found;
  }
  return null;
}

/**
 * Extrae el comando de admisión de un microplan YAML.
 *
 * Busca primero las rutas canónicas (camelCase y snake_case), luego
 * fallback recursivo por cualquier key `comando` o `command`.
 */
export function extractTestCommand(mpPath: string): string | null {
  if (!fs.existsSync(mpPath)) return null;
  let parsed: unknown;
  try {
    const raw = fs.readFileSync(mpPath, "utf8");
    parsed = parseYaml(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;

  const root = parsed as Record<string, unknown>;

  // camelCase: criteriodeadmision.testdeverdad.comando
  const cca = root["criteriodeadmision"];
  if (cca && typeof cca === "object") {
    const tdv = (cca as Record<string, unknown>)["testdeverdad"];
    if (tdv && typeof tdv === "object") {
      const cmd = (tdv as Record<string, unknown>)["comando"];
      if (typeof cmd === "string" && cmd.trim().length > 0) return cmd;
    }
  }

  // snake_case: criterio_de_admision.test_de_verdad.comando
  const cda = root["criterio_de_admision"];
  if (cda && typeof cda === "object") {
    const tdv = (cda as Record<string, unknown>)["test_de_verdad"];
    if (tdv && typeof tdv === "object") {
      const cmd = (tdv as Record<string, unknown>)["comando"];
      if (typeof cmd === "string" && cmd.trim().length > 0) return cmd;
    }
  }

  // Fallback recursivo: buscar cualquier key "comando" o "command"
  return findKeyRecursive(root, ["comando", "command"]);
}

// ============================================================================
// Test execution
// ============================================================================

const TEST_TIMEOUT_MS = 60_000;

export function runTest(
  flowId: string,
  mpId: string,
  command: string,
  repoRoot: string = process.cwd()
): TestRunResult {
  const startedAt = Date.now();
  let passed = false;
  let exitCode = 1;
  let stdout = "";
  let stderr = "";

  try {
    const result = spawnSync("bash", ["-c", command], {
      cwd: repoRoot,
      timeout: TEST_TIMEOUT_MS,
      encoding: "utf8",
      maxBuffer: 10 * 1024 * 1024,
    });
    exitCode = result.status ?? 1;
    stdout = (result.stdout ?? "").toString();
    stderr = (result.stderr ?? "").toString();
    passed = exitCode === 0;
    if (result.error && result.error.message.includes("ETIMEDOUT")) {
      stderr = `[timeout ${TEST_TIMEOUT_MS}ms] ${stderr}`;
    }
  } catch (err) {
    exitCode = 1;
    stderr = `error ejecutando test: ${(err as Error).message}`;
    passed = false;
  }

  const duration_ms = Date.now() - startedAt;

  auditLog(
    {
      flow_id: flowId,
      actor: "plugin:apolo-dynamic-flow",
      action: passed ? "test_passed" : "test_failed",
      outcome: passed ? "success" : "failure",
      target: mpId,
      duration_ms,
      context: {
        mp_id: mpId,
        command,
        exit_code: exitCode,
      },
      evidence: { produced: passed ? [mpId] : [] },
    },
    repoRoot
  );

  return { passed, exit_code: exitCode, stdout, stderr, duration_ms };
}
