/**
 * mcp-loader.ts — Absorbedor declarativo de MCPs desde opencode.json.
 *
 * Reemplaza el descubrimiento "manual" de MCPs por una carga declarativa:
 * lee `opencode.json#mcp` y registra cada MCP con su estado (enabled/available).
 *
 * API:
 *   - detectAvailableMcps(repoRoot)    → McpRegistry
 *   - isMcpAvailable(registry, name)   → boolean
 *   - suggestMcpForTask(registry, taskDescription) → {mcp, reason} | null
 *   - invokeMcp(flowId, registry, mcpName, tool, inputs, fallback?) → InvokeResult
 *
 * Conforme al schema: schemas/json/runtime-audit-log.json (action: mcp_invoked)
 */

import * as fs from "fs";
import * as path from "path";
import { log as auditLog } from "../core/runtime-logger";

// ============================================================================
// Types
// ============================================================================

export interface McpDescriptor {
  name: string;
  command: string[] | string;
  enabled: boolean;
  available: boolean;
  description?: string;
}

export interface McpRegistry {
  repoRoot: string;
  descriptors: McpDescriptor[];
  loaded_at: string;
}

export interface InvokeResult {
  success: boolean;
  result?: unknown;
  fallback_used?: boolean;
  error?: string;
  mcp: string;
  tool: string;
}

// ============================================================================
// Cache
// ============================================================================

let mcpCache: McpRegistry | null = null;
let cachedRepoRoot: string | null = null;

export function _resetMcpCache(): void {
  mcpCache = null;
  cachedRepoRoot = null;
}

// ============================================================================
// detectAvailableMcps
// ============================================================================

export function detectAvailableMcps(repoRoot: string = process.cwd()): McpRegistry {
  if (mcpCache && cachedRepoRoot === repoRoot) {
    return mcpCache;
  }

  const opencodePath = path.join(repoRoot, "opencode.json");
  const descriptors: McpDescriptor[] = [];

  if (fs.existsSync(opencodePath)) {
    try {
      const raw = fs.readFileSync(opencodePath, "utf8");
      const parsed = JSON.parse(raw) as { mcp?: Record<string, unknown> };
      const mcpSection = parsed.mcp;
      if (mcpSection && typeof mcpSection === "object") {
        for (const name of Object.keys(mcpSection)) {
          const entry = (mcpSection as Record<string, any>)[name];
          if (!entry || typeof entry !== "object") continue;
          const enabled = entry.enabled !== false; // default true
          descriptors.push({
            name,
            command: entry.command ?? [],
            enabled,
            available: enabled, // available = enabled (modo declarativo)
            description: entry.description,
          });
        }
      }
    } catch {
      // opencode.json inválido → registry vacío
    }
  }

  // Si no hay MCPs, incluir un descriptor "builtin"
  if (descriptors.length === 0) {
    descriptors.push({
      name: "builtin",
      command: ["builtin"],
      enabled: true,
      available: true,
      description: "MCP builtin de fallback cuando no hay MCPs externos",
    });
  }

  const registry: McpRegistry = {
    repoRoot,
    descriptors,
    loaded_at: new Date().toISOString(),
  };
  mcpCache = registry;
  cachedRepoRoot = repoRoot;
  return registry;
}

// ============================================================================
// isMcpAvailable
// ============================================================================

export function isMcpAvailable(registry: McpRegistry, name: string): boolean {
  const desc = registry.descriptors.find((d) => d.name === name);
  if (!desc) return false;
  return desc.available && desc.enabled;
}

// ============================================================================
// suggestMcpForTask
// ============================================================================

export function suggestMcpForTask(
  registry: McpRegistry,
  taskDescription: string
): { mcp: string; reason: string } | null {
  const lower = (taskDescription ?? "").toLowerCase();

  // Heurística: edición rápida
  if (/\b(editar|edit|edición|modificar archivo|cambiar línea)\b/.test(lower)) {
    const candidate =
      registry.descriptors.find((d) => /fastedit/.test(d.name)) ??
      registry.descriptors.find((d) => /edit/.test(d.name));
    if (candidate && isMcpAvailable(registry, candidate.name)) {
      return { mcp: candidate.name, reason: "tarea de edición → fastedit" };
    }
  }

  // Heurística: captura visual / browser
  if (/\b(captur|screenshot|browser|navegador|pantalla|dom)\b/.test(lower)) {
    const candidate =
      registry.descriptors.find((d) => /playwright/.test(d.name)) ??
      registry.descriptors.find((d) => /browser/.test(d.name));
    if (candidate && isMcpAvailable(registry, candidate.name)) {
      return { mcp: candidate.name, reason: "tarea visual/browser → playwright" };
    }
  }

  // Heurística: planificación / optimización
  if (/\b(plan|optimize|optimiza|planificar|skill)\b/.test(lower)) {
    const candidate =
      registry.descriptors.find((d) => /skill/.test(d.name)) ??
      registry.descriptors.find((d) => /plan/.test(d.name));
    if (candidate && isMcpAvailable(registry, candidate.name)) {
      return { mcp: candidate.name, reason: "tarea de planificación/skill → skills MCP" };
    }
  }

  return null;
}

// ============================================================================
// invokeMcp
// ============================================================================

export type FallbackFn = (inputs: Record<string, unknown>) => unknown;

export function invokeMcp(
  flowId: string,
  registry: McpRegistry,
  mcpName: string,
  tool: string,
  inputs: Record<string, unknown>,
  fallback?: FallbackFn,
  repoRoot: string = process.cwd()
): InvokeResult {
  const available = isMcpAvailable(registry, mcpName);

  if (!available) {
    if (fallback) {
      try {
        const result = fallback(inputs);
        auditLog(
          {
            flow_id: flowId,
            actor: "plugin:apolo-dynamic-flow",
            action: "mcp_fallback",
            outcome: "success",
            target: mcpName,
            context: { tool, mcp: mcpName, fallback_used: true },
          },
          repoRoot
        );
        return {
          success: true,
          result,
          fallback_used: true,
          mcp: mcpName,
          tool,
        };
      } catch (err) {
        auditLog(
          {
            flow_id: flowId,
            actor: "plugin:apolo-dynamic-flow",
            action: "mcp_invoked",
            outcome: "failure",
            target: mcpName,
            context: { tool, error: (err as Error).message },
          },
          repoRoot
        );
        return {
          success: false,
          error: `fallback falló: ${(err as Error).message}`,
          mcp: mcpName,
          tool,
        };
      }
    }
    auditLog(
      {
        flow_id: flowId,
        actor: "plugin:apolo-dynamic-flow",
        action: "mcp_invoked",
        outcome: "failure",
        target: mcpName,
        context: { tool, reason: "mcp no disponible y sin fallback" },
      },
      repoRoot
    );
    return {
      success: false,
      error: `mcp ${mcpName} no disponible y sin fallback`,
      mcp: mcpName,
      tool,
    };
  }

  // MCP disponible — en modo declarativo no ejecutamos el MCP real (es
  // responsabilidad del runtime de OpenCode). Sólo logueamos y devolvemos
  // un stub de éxito.
  auditLog(
    {
      flow_id: flowId,
      actor: "plugin:apolo-dynamic-flow",
      action: "mcp_invoked",
      outcome: "success",
      target: mcpName,
      context: { tool, inputs_keys: Object.keys(inputs) },
    },
    repoRoot
  );
  return {
    success: true,
    result: { delegated: true, mcp: mcpName, tool },
    fallback_used: false,
    mcp: mcpName,
    tool,
  };
}
