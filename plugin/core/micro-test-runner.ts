/**
 * micro-test-runner.ts — Runner de micro-tests.
 *
 * Extrae el comando de test de un MP (criteriodeadmision.testdeverdad.comando)
 * y lo ejecuta vía shell. Soporta camelCase y snake_case.
 */

import { spawnSync } from "child_process";
import * as fs from "fs";
import { log } from "./runtime-logger";

// ============================================================================
// Types
// ============================================================================

export interface TestResult {
  passed: boolean;
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_ms: number;
}

// ============================================================================
// YAML parser minimalista (solo para extraer comando de test)
// ============================================================================

function parseSimpleYaml(text: string): Record<string, any> {
  const result: Record<string, any> = {};
  const stack: Array<{ indent: number; node: Record<string, any> }> = [
    { indent: -1, node: result },
  ];

  for (const rawLine of text.split("\n")) {
    const line = rawLine.replace(/\s+$/, "");
    if (!line || line.trim().startsWith("#")) continue;
    const indent = line.length - line.trimStart().length;
    const trimmed = line.trim();

    while (stack.length > 1 && stack[stack.length - 1].indent >= indent) {
      stack.pop();
    }
    const parent = stack[stack.length - 1].node;

    if (trimmed.startsWith("- ")) {
      // List item — skip for our purposes
      continue;
    }

    if (trimmed.includes(": ")) {
      const idx = trimmed.indexOf(": ");
      const key = trimmed.slice(0, idx).trim();
      const value = trimmed.slice(idx + 2).trim();
      if (value === "") {
        const child: Record<string, any> = {};
        parent[key] = child;
        stack.push({ indent: indent + 2, node: child });
      } else {
        // Strip quotes
        let v: any = value;
        if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
          v = v.slice(1, -1);
        }
        parent[key] = v;
      }
    } else if (trimmed.endsWith(":")) {
      const key = trimmed.slice(0, -1).trim();
      const child: Record<string, any> = {};
      parent[key] = child;
      stack.push({ indent: indent + 2, node: child });
    }
  }

  return result;
}

// ============================================================================
// Public API
// ============================================================================

/**
 * Extrae el comando de test de un MP YAML.
 * Soporta camelCase (criteriodeadmision.testdeverdad.comando)
 * y snake_case (criterio_de_admision.test_de_verdad.comando).
 */
export function extractTestCommand(mpPath: string): string | null {
  if (!fs.existsSync(mpPath)) return null;

  try {
    const content = fs.readFileSync(mpPath, "utf8");
    const parsed = parseSimpleYaml(content);

    // camelCase
    const camelCmd =
      parsed?.criteriodeadmision?.testdeverdad?.comando ??
      parsed?.criteriodeadmision?.testdeverdad?.command;
    if (camelCmd) return camelCmd;

    // snake_case
    const snakeCmd =
      parsed?.criterio_de_admision?.test_de_verdad?.comando ??
      parsed?.criterio_de_admision?.test_de_verdad?.command;
    if (snakeCmd) return snakeCmd;

    // Cualquier combinación: buscar recursivamente "comando" o "command"
    return findDeep(parsed, ["comando", "command"]);
  } catch {
    return null;
  }
}

function findDeep(obj: any, keys: string[]): string | null {
  if (!obj || typeof obj !== "object") return null;
  for (const k of keys) {
    if (typeof obj[k] === "string") return obj[k];
  }
  for (const k of Object.keys(obj)) {
    const found = findDeep(obj[k], keys);
    if (found) return found;
  }
  return null;
}

/**
 * Ejecuta un comando de test y retorna el resultado.
 */
export function runTest(
  flowId: string,
  mpId: string,
  command: string
): TestResult {
  const start = Date.now();

  const result = spawnSync("bash", ["-c", command], {
    encoding: "utf8",
    timeout: 60000, // 1 min máximo
  });

  const duration_ms = Date.now() - start;
  const exit_code = result.status ?? -1;
  const passed = exit_code === 0;

  // Loguear al audit log
  log({
    flow_id: flowId,
    actor: "agent:mutation-guardian",
    action: passed ? "test_passed" : "test_failed",
    outcome: passed ? "success" : "failure",
    target: mpId,
    duration_ms,
    context: {
      command,
      exit_code,
      stdout_preview: (result.stdout ?? "").slice(0, 200),
      stderr_preview: (result.stderr ?? "").slice(0, 200),
    },
  });

  return {
    passed,
    exit_code,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    duration_ms,
  };
}
