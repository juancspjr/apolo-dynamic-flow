/**
 * tool-absorber.ts — Descubrimiento y registro de tools externas.
 *
 * El plugin puede absorber tools de:
 *   - MCPs registrados en opencode.json (opencode-fastedit, @playwright/mcp, etc.)
 *   - Skills externas en .opencode/skills/ (12 locales + koderspa/mcp-skills)
 *   - Otros plugins TS en .opencode/plugin/
 *   - Scripts Python en scripts/python/
 *
 * El absorber:
 *   1. Descubre candidates (escanea paths conocidos)
 *   2. Verifica salud (ejecuta health_check)
 *   3. Registra en TOOL-REGISTRY.yaml
 *   4. Detecta conflicts (mismas capabilities)
 *   5. Construye fallback chains
 */

import { spawnSync } from "child_process";
import * as fs from "fs";
import * as path from "path";
import type {
  PluginContext,
  RegisteredTool,
  ToolRegistry,
} from "./types";
import { readYaml, writeYaml, now, ensureDir, v4 } from "./utils";

const ABSORB_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "absorb_mcp.py"
);

const HEALTH_CHECK_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "health_check.py"
);

const REGISTRY_RECOMMEND_SCRIPT = path.join(
  __dirname,
  "..",
  "scripts",
  "python",
  "registry_recommend.py"
);

export interface AbsorbResult {
  registry: ToolRegistry;
  newTools: RegisteredTool[];
  conflicts: ToolRegistry["conflicts"];
  success: boolean;
  durationMs: number;
}

export function absorbTools(
  ctx: PluginContext,
  sources?: { mcps?: boolean; skills?: boolean; plugins?: boolean; scripts?: boolean }
): AbsorbResult {
  const start = Date.now();
  const opts = sources ?? { mcps: true, skills: true, plugins: true, scripts: true };

  // Leer registry existente
  const existing = readYaml<ToolRegistry>(ctx.toolRegistryPath) ?? {
    toolregistry: "V2",
    version: 1,
    updated_at: now(),
    tools: [],
    conflicts: [],
  };

  const newTools: RegisteredTool[] = [];
  const allTools: RegisteredTool[] = [...existing.tools];

  // 1. MCPs desde opencode.json
  if (opts.mcps) {
    const opencodePath = path.join(ctx.repoRoot, "opencode.json");
    if (fs.existsSync(opencodePath)) {
      const opencode = JSON.parse(fs.readFileSync(opencodePath, "utf8"));
      const mcpEntries = opencode.mcp ?? {};
      for (const [name, config] of Object.entries(mcpEntries)) {
        const tool = buildMcpTool(name, config as any);
        if (!allTools.find((t) => t.id === tool.id)) {
          allTools.push(tool);
          newTools.push(tool);
        }
      }
    }
  }

  // 2. Skills locales
  if (opts.skills) {
    const skillsDir = path.join(ctx.repoRoot, ".opencode", "skills");
    if (fs.existsSync(skillsDir)) {
      for (const entry of fs.readdirSync(skillsDir, { withFileTypes: true })) {
        if (entry.isDirectory()) {
          const skillMd = path.join(skillsDir, entry.name, "SKILL.md");
          if (fs.existsSync(skillMd)) {
            const tool = buildSkillTool(entry.name, skillMd);
            if (!allTools.find((t) => t.id === tool.id)) {
              allTools.push(tool);
              newTools.push(tool);
            }
          }
        }
      }
    }
  }

  // 3. Plugins TS locales
  if (opts.plugins) {
    const pluginDir = path.join(ctx.repoRoot, ".opencode", "plugin");
    if (fs.existsSync(pluginDir)) {
      for (const entry of fs.readdirSync(pluginDir, { withFileTypes: true })) {
        if (entry.isFile() && entry.name.endsWith(".ts")) {
          const tool = buildPluginTool(entry.name, path.join(pluginDir, entry.name));
          if (!allTools.find((t) => t.id === tool.id)) {
            allTools.push(tool);
            newTools.push(tool);
          }
        }
      }
    }
  }

  // 4. Scripts Python locales
  if (opts.scripts) {
    const scriptsDir = path.join(ctx.repoRoot, "scripts", "python");
    if (fs.existsSync(scriptsDir)) {
      for (const entry of fs.readdirSync(scriptsDir, { withFileTypes: true })) {
        if (entry.isFile() && entry.name.endsWith(".py")) {
          const tool = buildScriptTool(entry.name, path.join(scriptsDir, entry.name));
          if (!allTools.find((t) => t.id === tool.id)) {
            allTools.push(tool);
            newTools.push(tool);
          }
        }
      }
    }
  }

  // 5. Verificar salud de tools no verificadas
  for (const tool of newTools) {
    if (tool.health_check) {
      const ok = verifyHealth(tool, ctx.repoRoot);
      tool.status = ok ? "active" : "degraded";
      tool.last_verified_at = now();
    } else {
      tool.status = "unverified";
    }
  }

  // 6. Detectar conflicts (mismas capabilities)
  const conflicts = detectConflicts(allTools);

  // 7. Persistir registry actualizado
  const registry: ToolRegistry = {
    toolregistry: "V2",
    version: existing.version + 1,
    updated_at: now(),
    tools: allTools,
    conflicts,
  };
  ensureDir(path.dirname(ctx.toolRegistryPath));
  writeYaml(ctx.toolRegistryPath, registry);

  const durationMs = Date.now() - start;

  ctx.emit({
    kind: "tool-absorbed",
    phase: "reanclaje",
    severity: "info",
    message: `${newTools.length} tools nuevas absorbidas (${allTools.length} total, ${conflicts.length} conflictos)`,
    payload: {
      new_tool_ids: newTools.map((t) => t.id),
      total_tools: allTools.length,
      conflicts: conflicts.length,
      duration_ms: durationMs,
    },
    duration_ms: durationMs,
  });

  return {
    registry,
    newTools,
    conflicts,
    success: true,
    durationMs,
  };
}

// ============================================================================
// Builders
// ============================================================================

function buildMcpTool(name: string, config: any): RegisteredTool {
  return {
    id: `mcp:opencode.json:${name}`,
    source: `opencode.json#mcp.${name}`,
    kind: "mcp",
    name,
    status: "unverified",
    registered_at: now(),
    capabilities: inferMcpCapabilities(name),
    invoke: {
      method: "mcp-call",
      target: name,
    },
    fallback: config.fallback,
    health_check: {
      command: `opencode mcp list 2>&1 | grep -q ${name}`,
      expected_exit: 0,
      interval_seconds: 300,
    },
    notes: `MCP registrado en opencode.json: ${JSON.stringify(config).slice(0, 200)}`,
  };
}

function buildSkillTool(name: string, skillMdPath: string): RegisteredTool {
  return {
    id: `skill:.opencode/skills/${name}`,
    source: skillMdPath,
    kind: "skill",
    name,
    status: "unverified",
    registered_at: now(),
    capabilities: inferSkillCapabilities(name),
    invoke: {
      method: "ts-function",
      target: `loadSkill(${name})`,
    },
    health_check: {
      command: `test -f ${skillMdPath}`,
      expected_exit: 0,
      interval_seconds: 600,
    },
  };
}

function buildPluginTool(name: string, pluginPath: string): RegisteredTool {
  return {
    id: `plugin-tool:.opencode/plugin/${name}`,
    source: pluginPath,
    kind: "plugin-tool",
    name: name.replace(/\.ts$/, ""),
    status: "unverified",
    registered_at: now(),
    capabilities: ["orchestrate", "edit", "read"],
    invoke: {
      method: "ts-function",
      target: `import(${pluginPath})`,
    },
  };
}

function buildScriptTool(name: string, scriptPath: string): RegisteredTool {
  return {
    id: `external-script:scripts/python/${name}`,
    source: scriptPath,
    kind: "external-script",
    name: name.replace(/\.py$/, ""),
    status: "unverified",
    registered_at: now(),
    capabilities: inferScriptCapabilities(name),
    invoke: {
      method: "bash-script",
      target: `python3 ${scriptPath}`,
    },
    health_check: {
      command: `python3 ${scriptPath} --help 2>&1 | head -1`,
      expected_exit: 0,
      interval_seconds: 600,
    },
  };
}

// ============================================================================
// Heurísticas de capacidades
// ============================================================================

function inferMcpCapabilities(name: string): string[] {
  const lower = name.toLowerCase();
  const caps: string[] = [];
  if (lower.includes("fastedit") || lower.includes("edit")) caps.push("edit", "read");
  if (lower.includes("playwright")) caps.push("capture", "interact", "dom");
  if (lower.includes("triage")) caps.push("triage", "route");
  if (lower.includes("skillful") || lower.includes("skills")) caps.push("plan", "optimize");
  if (lower.includes("caveman")) caps.push("compress");
  if (lower.includes("dcp")) caps.push("discover", "scope");
  if (lower.includes("devtools")) caps.push("debug", "network", "console");
  return caps.length > 0 ? caps : ["unknown"];
}

function inferSkillCapabilities(name: string): string[] {
  const lower = name.toLowerCase();
  const caps: string[] = [];
  if (lower.includes("evidence") || lower.includes("capture")) caps.push("capture", "evidence");
  if (lower.includes("compare")) caps.push("compare", "evidence");
  if (lower.includes("plan")) caps.push("plan", "shape");
  if (lower.includes("test")) caps.push("test");
  if (lower.includes("audit") || lower.includes("truth")) caps.push("audit");
  if (lower.includes("frontend") || lower.includes("ui")) caps.push("frontend");
  if (lower.includes("backend")) caps.push("backend");
  if (lower.includes("security")) caps.push("security");
  return caps.length > 0 ? caps : ["unknown"];
}

function inferScriptCapabilities(name: string): string[] {
  const lower = name.toLowerCase();
  const caps: string[] = [];
  if (lower.includes("collect")) caps.push("collect", "evidence");
  if (lower.includes("generate_plan")) caps.push("plan", "generate");
  if (lower.includes("run_tests")) caps.push("test", "run");
  if (lower.includes("absorb")) caps.push("absorb", "register");
  if (lower.includes("inspect")) caps.push("inspect");
  if (lower.includes("rollback")) caps.push("rollback");
  if (lower.includes("validate")) caps.push("validate");
  if (lower.includes("telemetry")) caps.push("telemetry", "aggregate");
  return caps.length > 0 ? caps : ["unknown"];
}

// ============================================================================
// Health check
// ============================================================================

function verifyHealth(tool: RegisteredTool, repoRoot: string): boolean {
  if (!tool.health_check) return true; // Sin health_check = asumir ok
  try {
    const result = spawnSync("bash", ["-c", tool.health_check.command], {
      encoding: "utf8",
      timeout: 10000,
      cwd: repoRoot,
    });
    return result.status === tool.health_check.expected_exit;
  } catch {
    return false;
  }
}

// ============================================================================
// Conflict detection
// ============================================================================

function detectConflicts(tools: RegisteredTool[]): ToolRegistry["conflicts"] {
  const byCap = new Map<string, RegisteredTool[]>();
  for (const t of tools) {
    for (const c of t.capabilities) {
      if (!byCap.has(c)) byCap.set(c, []);
      byCap.get(c)!.push(t);
    }
  }
  const conflicts: ToolRegistry["conflicts"] = [];
  for (const [cap, ts] of byCap.entries()) {
    if (ts.length > 1) {
      conflicts.push({
        tools: ts.map((t) => t.id),
        capability: cap,
        resolution: "priority-first", // primera registrada gana
      });
    }
  }
  return conflicts;
}

// ============================================================================
// Lookup
// ============================================================================

export function findToolByCapability(
  registry: ToolRegistry,
  capability: string,
  preferActive = true
): RegisteredTool | null {
  const matches = registry.tools.filter((t) => t.capabilities.includes(capability));
  if (matches.length === 0) return null;
  if (preferActive) {
    const active = matches.filter((t) => t.status === "active");
    if (active.length > 0) return active[0];
  }
  return matches[0];
}

export function getFallbackChain(
  registry: ToolRegistry,
  toolId: string
): RegisteredTool[] {
  const chain: RegisteredTool[] = [];
  let current = registry.tools.find((t) => t.id === toolId);
  while (current) {
    chain.push(current);
    if (!current.fallback) break;
    const next = registry.tools.find((t) => t.id === current!.fallback);
    if (!next || chain.find((c) => c.id === next.id)) break; // evita loop
    current = next;
  }
  return chain;
}

// ============================================================================
// v2.2.0 — Hot reload + active recommendation
// ============================================================================

export interface HotReloadResult {
  registry: ToolRegistry;
  new_tools: RegisteredTool[];
  status_changes: Array<{
    tool_id: string;
    old_status: string;
    new_status: string;
    reason: string;
  }>;
  missing_tools: string[];
  success: boolean;
  durationMs: number;
  rawSummary?: {
    total_tools: number;
    healthy: number;
    unhealthy: number;
  };
}

/**
 * Invoca scripts/python/health_check.py --fix true --json para re-absorber
 * en caliente: actualiza estados (active/degraded) del ToolRegistry en memoria
 * y persiste el archivo YAML.
 *
 * Emite eventos `tool-absorbed` (cuando hay nuevas tools) o `tool-failed`
 * (cuando una tool cambió a degraded/disabled).
 */
export function hotReloadRegistry(
  ctx: PluginContext,
  opts: { fix?: boolean } = {}
): HotReloadResult {
  const start = Date.now();
  const fix = opts.fix !== false; // default true

  const args = [
    HEALTH_CHECK_SCRIPT,
    "--repo-root",
    ctx.repoRoot,
    "--json",
    "true",
  ];
  if (fix) {
    args.push("--fix", "true");
  }

  const result = spawnSync("python3", args, {
    encoding: "utf8",
    timeout: 30000,
    maxBuffer: 10 * 1024 * 1024,
  });

  const durationMs = Date.now() - start;
  const ran = result.status !== null;

  // health_check.py returns exit 1 if there are unhealthy tools, but JSON is valid.
  let parsed: any = null;
  if (ran && result.stdout) {
    try {
      parsed = JSON.parse(result.stdout);
    } catch {
      const lines = result.stdout
        .split("\n")
        .filter((l) => l.trim().startsWith("{"));
      if (lines.length > 0) {
        try {
          parsed = JSON.parse(lines[lines.length - 1]);
        } catch {
          /* ignore */
        }
      }
    }
  }

  // Leer el registry actualizado (el script Python lo persistió si fix=true)
  const registry = readYaml<ToolRegistry>(ctx.toolRegistryPath) ?? {
    toolregistry: "V2",
    version: 1,
    updated_at: now(),
    tools: [],
    conflicts: [],
  };

  const newTools: RegisteredTool[] = (parsed?.new_scripts ?? []).map((s: any) => ({
    id: s.id,
    source: s.source,
    kind: s.kind ?? "external-script",
    name: s.name,
    status: s.status ?? "unverified",
    registered_at: s.registered_at ?? now(),
    capabilities: s.capabilities ?? [],
    invoke: s.invoke ?? { method: "bash-script", target: "" },
  }));

  const statusChanges: HotReloadResult["status_changes"] =
    parsed?.status_changes ?? [];
  const missingTools: string[] = parsed?.missing_tools ?? [];

  // Emitir telemetría
  if (newTools.length > 0) {
    ctx.emit({
      kind: "tool-absorbed",
      phase: "reanclaje",
      severity: "info",
      message: `hot-reload: ${newTools.length} tools nuevas absorbidas`,
      payload: {
        new_tool_ids: newTools.map((t) => t.id),
        duration_ms: durationMs,
      },
      duration_ms: durationMs,
    });
  }
  for (const sc of statusChanges) {
    if (sc.new_status === "degraded" || sc.new_status === "disabled") {
      ctx.emit({
        kind: "tool-failed",
        phase: "reanclaje",
        severity: sc.new_status === "disabled" ? "error" : "warn",
        message: `hot-reload: ${sc.tool_id} ${sc.old_status} -> ${sc.new_status} (${sc.reason})`,
        payload: sc,
      });
    }
  }

  const rawSummary = parsed?.summary
    ? {
        total_tools: parsed.summary.total_tools ?? 0,
        healthy: parsed.summary.healthy ?? 0,
        unhealthy: parsed.summary.unhealthy ?? 0,
      }
    : undefined;

  return {
    registry,
    new_tools: newTools,
    status_changes: statusChanges,
    missing_tools: missingTools,
    success: ran && parsed !== null,
    durationMs,
    rawSummary,
  };
}

export interface RecommendToolResult {
  task: string;
  total_tools_evaluated: number;
  tools_with_score: number;
  top_recommendations: Array<{
    tool_id: string;
    tool_name: string;
    tool_kind: string;
    score: number;
    matched_capabilities: string[];
    reasons: string[];
    status: string;
    fallback?: string;
    invoke?: any;
  }>;
  conflicts: any[];
  recommended_action: string;
  _meta?: any;
}

/**
 * Invoca scripts/python/registry_recommend.py --task <task> --repo-root <repo>
 * --top <top> --json. Es la implementación ACTIVA (vs la pasiva de
 * findToolByCapability que solo filtra el registry en memoria).
 */
export function recommendTool(
  ctx: PluginContext,
  task: string,
  top: number = 3
): RecommendToolResult {
  const args = [
    REGISTRY_RECOMMEND_SCRIPT,
    "--task",
    task,
    "--repo-root",
    ctx.repoRoot,
    "--top",
    String(top),
  ];

  const result = spawnSync("python3", args, {
    encoding: "utf8",
    timeout: 10000,
    maxBuffer: 5 * 1024 * 1024,
  });

  const ran = result.status !== null;
  let parsed: any = null;
  if (ran && result.stdout) {
    try {
      parsed = JSON.parse(result.stdout);
    } catch {
      const lines = result.stdout
        .split("\n")
        .filter((l) => l.trim().startsWith("{"));
      if (lines.length > 0) {
        try {
          parsed = JSON.parse(lines[lines.length - 1]);
        } catch {
          /* ignore */
        }
      }
    }
  }

  if (!parsed) {
    return {
      task,
      total_tools_evaluated: 0,
      tools_with_score: 0,
      top_recommendations: [],
      conflicts: [],
      recommended_action: "no tool matches the task — registry_recommend.py failed",
    };
  }

  return {
    task: parsed.task ?? task,
    total_tools_evaluated: parsed.total_tools_evaluated ?? 0,
    tools_with_score: parsed.tools_with_score ?? 0,
    top_recommendations: parsed.top_recommendations ?? [],
    conflicts: parsed.conflicts ?? [],
    recommended_action: parsed.recommended_action ?? "",
    _meta: parsed._meta,
  };
}
