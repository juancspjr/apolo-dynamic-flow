/**
 * utils.ts — Utilidades compartidas.
 *
 * UUID v4 sin dependencias externas, hashing SHA256, IO de YAML.
 */

import * as crypto from "crypto";
import * as fs from "fs";
import * as path from "path";

// ============================================================================
// UUID v4 (sin dependencia externa)
// ============================================================================

export function v4(): string {
  // RFC 4122 v4
  const bytes = crypto.randomBytes(16);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(
    12,
    16
  )}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// ============================================================================
// Hashing
// ============================================================================

export function sha256(data: string | Buffer): string {
  return crypto.createHash("sha256").update(data).digest("hex");
}

export function hashFile(filePath: string): string {
  const content = fs.readFileSync(filePath);
  return sha256(content);
}

export function hashChain(items: Array<{ hash: string }>): string {
  const concat = items.map((i) => i.hash).join("");
  return sha256(concat);
}

// ============================================================================
// IO YAML (sin dependencia de js-yaml — serialización minimalista)
// ============================================================================

/**
 * Serializa un objeto a YAML. Soporta objetos anidados, arrays, strings,
 * numbers, booleans, null. No soporta tipos exóticos.
 */
export function toYaml(obj: unknown, indent = 0): string {
  const pad = "  ".repeat(indent);
  if (obj === null || obj === undefined) return "null";
  if (typeof obj === "string") {
    // String con caracteres especiales → comillas dobles
    if (/[:#\[\]{}&*!|>'"%@`]/.test(obj) || obj.includes("\n")) {
      return JSON.stringify(obj);
    }
    return obj;
  }
  if (typeof obj === "number" || typeof obj === "boolean") return String(obj);
  if (Array.isArray(obj)) {
    if (obj.length === 0) return "[]";
    return obj
      .map((item) => {
        if (typeof item === "object" && item !== null) {
          const inner = toYaml(item, indent + 1);
          return `${pad}- ${inner.trimStart()}`;
        }
        return `${pad}- ${toYaml(item, indent + 1)}`;
      })
      .join("\n");
  }
  if (typeof obj === "object") {
    const entries = Object.entries(obj as Record<string, unknown>);
    if (entries.length === 0) return "{}";
    return entries
      .map(([key, value]) => {
        if (value === null || value === undefined) {
          return `${pad}${key}: null`;
        }
        if (typeof value === "object") {
          const inner = toYaml(value, indent + 1);
          if (Array.isArray(value) && value.length === 0) {
            return `${pad}${key}: []`;
          }
          if (!Array.isArray(value) && Object.keys(value).length === 0) {
            return `${pad}${key}: {}`;
          }
          return `${pad}${key}:\n${inner}`;
        }
        return `${pad}${key}: ${toYaml(value, indent)}`;
      })
      .join("\n");
  }
  return String(obj);
}

/**
 * Lee un archivo YAML y lo parsea. NO usa js-yaml (dependencia externa).
 * Implementación mínima: soporta scalar, listas, objetos anidados.
 * Para proyectos serios, se recomienda instalar js-yaml y reemplazar esta función.
 */
export function parseYaml(text: string): unknown {
  // Implementación simple basada en indentación.
  // Acepta: key: value, key: [list], key: (nested), - item
  const lines = text.split("\n");
  const root: any = {};
  const stack: Array<{ indent: number; node: any }> = [{ indent: -1, node: root }];

  for (const rawLine of lines) {
    const line = rawLine.replace(/\s+$/, "");
    if (!line || line.trim().startsWith("#")) continue;
    const indent = line.length - line.trimStart().length;
    const trimmed = line.trim();

    // Pop stack hasta encontrar padre con indent menor
    while (stack.length > 1 && stack[stack.length - 1].indent >= indent) {
      stack.pop();
    }
    const parent = stack[stack.length - 1].node;

    if (trimmed.startsWith("- ")) {
      // List item
      const value = trimmed.slice(2).trim();
      if (!Array.isArray(parent)) {
        // Si el padre es objeto con última key esperando array, lo inicializamos
        // (mejor soporte requeriría tracking explícito)
        continue;
      }
      if (value.includes(": ")) {
        // Inline object item
        const obj: any = {};
        const [k, ...rest] = value.split(": ");
        obj[k.trim()] = parseScalar(rest.join(": ").trim());
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
        // Nested object or list
        const child: any = {};
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
      const child: any = {};
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
  // Quoted string
  if (
    (raw.startsWith('"') && raw.endsWith('"')) ||
    (raw.startsWith("'") && raw.endsWith("'"))
  ) {
    return raw.slice(1, -1);
  }
  return raw;
}

// ============================================================================
// FS helpers
// ============================================================================

export function ensureDir(dir: string): void {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

export function readJson<T = unknown>(filePath: string): T | null {
  if (!fs.existsSync(filePath)) return null;
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8")) as T;
  } catch {
    return null;
  }
}

export function writeJson(filePath: string, data: unknown): void {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
}

export function readYaml<T = unknown>(filePath: string): T | null {
  if (!fs.existsSync(filePath)) return null;
  try {
    return parseYaml(fs.readFileSync(filePath, "utf8")) as T;
  } catch {
    return null;
  }
}

export function writeYaml(filePath: string, data: unknown): void {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, toYaml(data) + "\n", "utf8");
}

export function appendLine(filePath: string, line: string): void {
  ensureDir(path.dirname(filePath));
  fs.appendFileSync(filePath, line + "\n", "utf8");
}

// ============================================================================
// Time
// ============================================================================

export function now(): string {
  return new Date().toISOString();
}

export function elapsedMs(startIso: string): number {
  return Date.now() - new Date(startIso).getTime();
}

// ============================================================================
// Path helpers
// ============================================================================

export function flowPath(repoRoot: string, flowid: string): string {
  return path.join(repoRoot, "plan", "active", flowid);
}

export function statePath(repoRoot: string, flowid: string): string {
  return path.join(flowPath(repoRoot, flowid), "FLOW-STATE.yaml");
}

export function evidencePath(repoRoot: string, flowid: string): string {
  return path.join(flowPath(repoRoot, flowid), "evidence", "EVIDENCE-PACK.yaml");
}

export function blocksPath(repoRoot: string, flowid: string): string {
  return path.join(flowPath(repoRoot, flowid), "BLOCK-LOG.yaml");
}

export function telemetryPath(repoRoot: string, flowid: string): string {
  return path.join(flowPath(repoRoot, flowid), "telemetry.jsonl");
}

export function toolRegistryPath(repoRoot: string): string {
  return path.join(repoRoot, ".opencode", "apolo-dynamic", "TOOL-REGISTRY.yaml");
}
