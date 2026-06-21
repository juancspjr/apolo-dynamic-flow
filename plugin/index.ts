/**
 * index.ts — Entry point del plugin apolo-dynamic-flow.
 *
 * Reemplaza a apolo-flow-guardian.ts como plugin principal del sistema.
 *
 * Registro:
 *   - Plugin OpenCode con hooks de lifecycle
 *   - Tools expuestas al orquestador
 *   - Commands expuestos al CLI
 *
 * Carga:
 *   - En opencode.json: { "plugins": ["apolo-dynamic-flow/plugin/index.ts"] }
 *
 * Hooks:
 *   - tool:execute:before  → inyecta evidence pack y flow state al contexto
 *   - tool:execute:after   → captura telemetría, valida gate
 *   - message:after        → detecta bloqueos, sugiere resoluciones
 *   - session:start        → absorbe tools, inicializa flow state
 */

import * as path from "path";
import { spawnSync } from "child_process";
import type {
  FlowState,
  PluginContext,
  TelemetryEvent,
} from "./types";
import {
  readYaml,
  writeYaml,
  now,
  ensureDir,
  flowPath,
  statePath,
  evidencePath,
  blocksPath,
  telemetryPath,
  toolRegistryPath,
  v4,
} from "./utils";
import { runLoopIteration } from "./loop-engine";
import { detectBlocks } from "./block-detector";
import { collectEvidence } from "./evidence-collector";
import { generatePlan } from "./plan-generator";
import { runTests } from "./test-runner";
import { absorbTools } from "./tool-absorber";
import { appendEvent } from "./telemetry";
import {
  inspectState,
  inspectTools,
  inspectBlocks,
  inspectTelemetry,
  inspectEvidence,
  inspectHealth,
  inspectAll,
} from "./inspector";

// ============================================================================
// OpenCode Plugin Interface (compatible con opencode plugin API)
// ============================================================================

export interface OpenCodePlugin {
  name: string;
  version: string;
  init?: (ctx: PluginInitContext) => void;
  hooks?: Record<string, (ctx: HookContext) => HookResult | Promise<HookResult>>;
  tools?: Record<string, ToolHandler>;
  commands?: Record<string, CommandHandler>;
}

export interface PluginInitContext {
  repoRoot: string;
  config: Record<string, unknown>;
  log: (msg: string) => void;
}

export interface HookContext {
  tool?: string;
  args?: Record<string, unknown>;
  result?: unknown;
  error?: Error;
  repoRoot: string;
  flowid?: string;
}

export type HookResult =
  | { continue: true; patch?: Record<string, unknown> }
  | { continue: false; reason: string };

export interface ToolHandler {
  description: string;
  inputSchema: object;
  handler: (args: Record<string, unknown>, ctx: PluginContext) => Promise<unknown>;
}

export interface CommandHandler {
  description: string;
  args: Array<{ name: string; required?: boolean; description: string }>;
  run: (args: Record<string, string>, ctx: PluginContext) => Promise<string>;
}

// ============================================================================
// Plugin definition
// ============================================================================

const PLUGIN: OpenCodePlugin = {
  name: "apolo-dynamic-flow",
  version: "2.0.0",
  init(ctx) {
    ctx.log(`[apolo-dynamic-flow] init en ${ctx.repoRoot}`);
    ensureDir(path.join(ctx.repoRoot, ".opencode", "apolo-dynamic"));
    // Absorber tools al iniciar
    const pc = buildContext(ctx.repoRoot, ctx.config.flowid as string ?? "APOLO-INIT");
    absorbTools(pc);
    ctx.log(`[apolo-dynamic-flow] tools absorbidas y registradas`);
  },

  hooks: {
    "tool:execute:before": (ctx) => {
      // Si el flow activo tiene un bloqueo crítico, detener tools de mutación
      if (!ctx.flowid) return { continue: true };
      const state = loadState(ctx.repoRoot, ctx.flowid);
      if (!state) return { continue: true };
      if (state.phase === "blocked") {
        if (["write_to_file", "apply_diff", "fastedit"].includes(ctx.tool ?? "")) {
          return {
            continue: false,
            reason: `flow ${ctx.flowid} bloqueado — resolver BLOQUEO antes de mutar`,
          };
        }
      }
      return { continue: true };
    },

    "tool:execute:after": (ctx) => {
      if (!ctx.flowid) return { continue: true };
      const pc = buildContext(ctx.repoRoot, ctx.flowid);
      appendEvent(pc, {
        kind: "tool-invoked",
        phase: "implementation",
        severity: ctx.error ? "error" : "info",
        message: `${ctx.tool} ${ctx.error ? "FAIL" : "OK"}`,
        payload: { args: ctx.args, error: ctx.error?.message },
      });
      return { continue: true };
    },

    "session:start": (ctx) => {
      const pc = buildContext(
        ctx.repoRoot,
        ctx.flowid ?? `APOLO-${new Date().toISOString().slice(0, 10).replace(/-/g, "")}-${v4().slice(0, 8)}`
      );
      absorbTools(pc);
      return { continue: true };
    },
  },

  tools: {
    "apolo.flow.init": {
      description: "Inicializa un nuevo flow con state vacío y tools absorbidas.",
      inputSchema: {
        type: "object",
        required: ["flowid"],
        properties: {
          flowid: { type: "string", pattern: "^APOLO-[0-9]{8}-[A-Z0-9-]+$" },
        },
      },
      handler: async (args, ctx) => {
        const state = initFlowState(args.flowid as string);
        saveState(ctx.repoRoot, state);
        absorbTools(ctx);
        return { flowid: state.flowid, phase: state.phase };
      },
    },

    "apolo.flow.tick": {
      description:
        "Ejecuta UNA iteración del loop dinámico. Evalúa gate, transita o bloquea. El orquestador externo llama tick() repetidamente.",
      inputSchema: {
        type: "object",
        properties: {
          evidence_pack: { type: "boolean", description: "Cargar evidence pack desde path en state" },
        },
      },
      handler: async (args, ctx) => {
        const state = loadState(ctx.repoRoot, ctx.flowid);
        if (!state) throw new Error(`flow ${ctx.flowid} no inicializado`);

        // Cargar evidence si existe
        let evidence;
        if (args.evidence_pack && state.artifacts.evidence_pack) {
          evidence = readYaml(ctx.evidencePath) as any;
        }

        const result = runLoopIteration(state, ctx, { evidence });

        // Persistir estado actualizado
        saveState(ctx.repoRoot, result.state);

        // Emitir telemetría
        for (const evt of result.telemetry) {
          appendEvent(ctx, {
            kind: evt.kind,
            phase: evt.phase,
            severity: evt.severity,
            message: evt.message,
            payload: evt.payload,
          });
        }

        // Si se creó un bloqueo, persistirlo
        if (result.blockCreated) {
          appendBlock(ctx.repoRoot, ctx.flowid, result.blockCreated);
        }

        // Detección activa de bloqueos
        const detection = detectBlocks(result.state, ctx);
        for (const b of detection.blocks) {
          appendBlock(ctx.repoRoot, ctx.flowid, b);
        }
        for (const evt of detection.telemetry) {
          appendEvent(ctx, {
            kind: evt.kind,
            phase: evt.phase,
            severity: evt.severity,
            message: evt.message,
            payload: evt.payload,
          });
        }

        return {
          transitioned: result.transitioned,
          from: result.fromPhase,
          to: result.toPhase,
          decision: result.gateResult.decision,
          reason: result.gateResult.reason,
          signals: result.gateResult.signals,
          block_created: result.blockCreated?.id,
        };
      },
    },

    "apolo.evidence.collect": {
      description:
        "Dispara recolección determinista de evidencia via script Python.",
      inputSchema: {
        type: "object",
        required: ["scope"],
        properties: {
          scope: {
            type: "object",
            properties: {
              paths: { type: "array", items: { type: "string" } },
              symbols: { type: "array", items: { type: "string" } },
              endpoints: { type: "array", items: { type: "string" } },
              git_diff: { type: "boolean" },
              git_log: { type: "boolean" },
              db_queries: { type: "array", items: { type: "string" } },
              screenshots: { type: "array", items: { type: "string" } },
            },
          },
          invoked_by: { type: "string" },
        },
      },
      handler: async (args, ctx) => {
        const result = collectEvidence(ctx, {
          scope: args.scope as any,
          invokedBy: (args.invoked_by as string) ?? "orchestrator",
        });
        if (result.pack) {
          const state = loadState(ctx.repoRoot, ctx.flowid);
          if (state) {
            state.artifacts.evidence_pack = ctx.evidencePath;
            saveState(ctx.repoRoot, state);
          }
        }
        return {
          success: result.success,
          items: result.pack?.items.length ?? 0,
          hash_chain: result.pack?.hash_chain,
          capabilities: result.pack?.capabilities,
          duration_ms: result.durationMs,
          stderr: result.success ? undefined : result.stderr,
        };
      },
    },

    "apolo.plan.generate": {
      description:
        "Genera un plan dinámico desde evidence pack + verdad via script Python.",
      inputSchema: {
        type: "object",
        required: ["verdad_path"],
        properties: {
          verdad_path: { type: "string" },
          parent_version: { type: "integer" },
          partition_hints: { type: "array", items: { type: "string" } },
          derivation_method: {
            type: "string",
            enum: ["deterministic-python", "hybrid", "manual"],
          },
        },
      },
      handler: async (args, ctx) => {
        const state = loadState(ctx.repoRoot, ctx.flowid);
        if (!state?.artifacts.evidence_pack) {
          throw new Error("evidence_pack no inicializado — ejecutar apolo.evidence.collect primero");
        }
        const result = generatePlan(ctx, {
          evidencePackPath: state.artifacts.evidence_pack,
          verdadPath: args.verdad_path as string,
          parentVersion: args.parent_version as number | undefined,
          partitionHints: args.partition_hints as string[] | undefined,
          derivationMethod: args.derivation_method as any,
        });
        if (result.success) {
          state.artifacts.plan_indice = result.planPath;
          saveState(ctx.repoRoot, state);
        }
        return {
          success: result.success,
          plan_path: result.planPath,
          version: result.version,
          units: result.units,
          topological_order: result.topologicalOrder,
          stderr: result.success ? undefined : result.stderr,
        };
      },
    },

    "apolo.tests.run": {
      description:
        "Ejecuta tests deterministas tras un cambio. Soporta rollback automático.",
      inputSchema: {
        type: "object",
        required: ["trigger", "scope"],
        properties: {
          trigger: {
            type: "string",
            enum: ["micro-change", "section-change", "full-plan", "manual", "pre-merge"],
          },
          scope: {
            type: "object",
            required: ["kind", "targets"],
            properties: {
              kind: {
                type: "string",
                enum: ["unit", "integration", "mutation", "e2e", "contract", "schema-validation"],
              },
              targets: { type: "array", items: { type: "string" } },
              mp_id: { type: "string" },
            },
          },
          rollback_on_fail: { type: "boolean" },
          rollback_strategy: {
            type: "string",
            enum: ["git-restore", "git-stash-pop", "custom-script"],
          },
          custom_rollback_script: { type: "string" },
        },
      },
      handler: async (args, ctx) => {
        const result = runTests(ctx, {
          trigger: args.trigger as any,
          scope: args.scope as any,
          rollbackOnFail: (args.rollback_on_fail as boolean) ?? true,
          rollbackStrategy: args.rollback_strategy as any,
          customRollbackScript: args.custom_rollback_script as string | undefined,
        });
        if (result.run) {
          const state = loadState(ctx.repoRoot, ctx.flowid);
          if (state) {
            if (!state.artifacts.test_runs) state.artifacts.test_runs = [];
            state.artifacts.test_runs.push(
              path.join("tests", path.basename(result.run.run_id ?? `run-${Date.now()}.yaml`)) + ".yaml"
            );
            saveState(ctx.repoRoot, state);
          }
        }
        return {
          success: result.success,
          summary: result.run?.summary,
          rollback_triggered: result.rollbackTriggered,
          exit_code: result.exitCode,
          stderr: result.success ? undefined : result.stderr,
        };
      },
    },

    "apolo.tools.absorb": {
      description: "Descubre y registra tools externas (MCPs, skills, plugins, scripts).",
      inputSchema: {
        type: "object",
        properties: {
          sources: {
            type: "object",
            properties: {
              mcps: { type: "boolean" },
              skills: { type: "boolean" },
              plugins: { type: "boolean" },
              scripts: { type: "boolean" },
            },
          },
        },
      },
      handler: async (args, ctx) => {
        const result = absorbTools(ctx, args.sources as any);
        return {
          total: result.registry.tools.length,
          new_tools: result.newTools.length,
          conflicts: result.conflicts.length,
          new_tool_ids: result.newTools.map((t) => t.id),
        };
      },
    },

    // ==========================================================================
    // v2.2.0 — 3 tools nuevas (cerrando los 4 gaps)
    // ==========================================================================

    "apolo.context.query": {
      description:
        "Consulta activa al sistema: responde preguntas del agente usando telemetría + flow state + code index + evidence + plan + impact + scaffold.",
      inputSchema: {
        type: "object",
        required: ["question"],
        properties: {
          question: {
            type: "string",
            description:
              "Pregunta en lenguaje natural. Ej: 'qué fase sigue', 'qué falta para avanzar', 'qué código debo tocar para U-01', 'qué predicciones de impacto hay'",
          },
          phase: {
            type: "string",
            description: "Fase actual del flow (opcional, se infiere del state)",
          },
        },
      },
      handler: async (args, ctx) => {
        const result = spawnSync(
          "python3",
          [
            path.join(__dirname, "..", "scripts", "python", "context_query.py"),
            "--flowid",
            ctx.flowid,
            "--repo-root",
            ctx.repoRoot,
            "--phase",
            (args.phase as string) || "",
            "--question",
            args.question as string,
          ],
          { encoding: "utf8", timeout: 30000 }
        );
        try {
          return JSON.parse(result.stdout);
        } catch {
          return {
            error: "context_query.py output no es JSON válido",
            stdout: result.stdout?.slice(0, 500),
            stderr: result.stderr?.slice(0, 500),
            exit_code: result.status,
          };
        }
      },
    },

    "apolo.registry.recommend": {
      description:
        "Recomienda qué tool del registry usar para una tarea, con scoring y reasoning.",
      inputSchema: {
        type: "object",
        required: ["task"],
        properties: {
          task: {
            type: "string",
            description:
              "Descripción de la tarea. Ej: 'editar archivo TS y correr tests'",
          },
          top: { type: "integer", minimum: 1, maximum: 10, default: 3 },
        },
      },
      handler: async (args, ctx) => {
        const result = spawnSync(
          "python3",
          [
            path.join(
              __dirname,
              "..",
              "scripts",
              "python",
              "registry_recommend.py"
            ),
            "--task",
            args.task as string,
            "--repo-root",
            ctx.repoRoot,
            "--top",
            String(args.top ?? 3),
          ],
          { encoding: "utf8", timeout: 10000 }
        );
        try {
          return JSON.parse(result.stdout);
        } catch {
          return {
            error: "registry_recommend.py output no es JSON válido",
            stdout: result.stdout?.slice(0, 500),
            stderr: result.stderr?.slice(0, 500),
            exit_code: result.status,
          };
        }
      },
    },

    "apolo.health.check": {
      description:
        "Health check en tiempo real de todas las tools del registry. Con fix=true, re-absorbe en caliente.",
      inputSchema: {
        type: "object",
        properties: {
          fix: {
            type: "boolean",
            default: false,
            description: "Si true, actualiza estados y absorbe scripts nuevos",
          },
        },
      },
      handler: async (args, ctx) => {
        const result = spawnSync(
          "python3",
          [
            path.join(__dirname, "..", "scripts", "python", "health_check.py"),
            "--repo-root",
            ctx.repoRoot,
            "--fix",
            args.fix ? "true" : "false",
            "--json",
            "true",
          ],
          { encoding: "utf8", timeout: 30000 }
        );
        try {
          return JSON.parse(result.stdout);
        } catch {
          return {
            error: "health_check.py output no es JSON válido",
            stdout: result.stdout?.slice(0, 500),
            stderr: result.stderr?.slice(0, 500),
            exit_code: result.status,
          };
        }
      },
    },
  },

  commands: {
    "apolo-inspect": {
      description: "Inspecciona estado del plugin (subcomando: state|tools|blocks|telemetry|evidence|health|all)",
      args: [
        { name: "subcommand", required: true, description: "state|tools|blocks|telemetry|evidence|health|all" },
        { name: "flowid", required: false, description: "Flow ID (default: del state activo)" },
        { name: "json", required: false, description: "Output JSON si se pasa 'json'" },
      ],
      run: async (args, ctx) => {
        const opts = {
          repoRoot: ctx.repoRoot,
          flowid: args.flowid ?? ctx.flowid,
          json: args.json === "json",
        };
        switch (args.subcommand) {
          case "state": return inspectState(opts);
          case "tools": return inspectTools(opts);
          case "blocks": return inspectBlocks(opts);
          case "telemetry": return inspectTelemetry(opts);
          case "evidence": return inspectEvidence(opts);
          case "health": return inspectHealth(opts);
          case "all": return inspectAll(opts);
          default: return `subcomando desconocido: ${args.subcommand}`;
        }
      },
    },
  },
};

export default PLUGIN;

// ============================================================================
// Helpers
// ============================================================================

function buildContext(repoRoot: string, flowid: string): PluginContext {
  return {
    flowid,
    repoRoot,
    statePath: statePath(repoRoot, flowid),
    evidencePath: evidencePath(repoRoot, flowid),
    blocksPath: blocksPath(repoRoot, flowid),
    telemetryPath: telemetryPath(repoRoot, flowid),
    toolRegistryPath: toolRegistryPath(repoRoot),
    log: (msg) => console.error(`[apolo-dynamic-flow] ${msg}`),
    emit: (event) => {
      // Re-bound en runtime real al telemetry.appendEvent
      const ctx: PluginContext = {
        flowid,
        repoRoot,
        statePath: statePath(repoRoot, flowid),
        evidencePath: evidencePath(repoRoot, flowid),
        blocksPath: blocksPath(repoRoot, flowid),
        telemetryPath: telemetryPath(repoRoot, flowid),
        toolRegistryPath: toolRegistryPath(repoRoot),
        log: () => {},
        emit: () => {},
      };
      appendEvent(ctx, event);
    },
  };
}

function initFlowState(flowid: string): FlowState {
  const nowIso = now();
  return {
    flowid,
    version: 1,
    schema_version: "V2",
    created_at: nowIso,
    updated_at: nowIso,
    phase: "reanclaje",
    phase_entered_at: nowIso,
    history: [],
    loops: {
      reanclaje: { current: 0, max: 2, last_decision: "" },
      "planning-bootstrap": { current: 0, max: 2, last_decision: "" },
      asr: { current: 0, max: 2, last_decision: "" },
      verdad: { current: 0, max: 2, last_decision: "" },
      shaping: { current: 0, max: 2, last_decision: "" },
      "plan-indice": { current: 0, max: 2, last_decision: "" },
      "mp-validation": { current: 0, max: 2, last_decision: "" },
      implementation: { current: 0, max: 4, last_decision: "" },
      "critical-validation": { current: 0, max: 2, last_decision: "" },
    },
    circuit_breaker: {
      policy: "fail-closed",
      escalation_path: [],
    },
    artifacts: {
      objetivo: "",
      asr: "",
      verdad: "",
      shaping: "",
      plan_indice: "",
      current_mps: [],
      evidence_pack: "",
      test_runs: [],
      blocks_log: "",
    },
    tools_absorbed: [],
    tokens_consumed_total: 0,
    operator_hints: [],
  };
}

function loadState(repoRoot: string, flowid: string): FlowState | null {
  return readYaml<FlowState>(statePath(repoRoot, flowid));
}

function saveState(repoRoot: string, state: FlowState): void {
  state.updated_at = now();
  ensureDir(path.dirname(statePath(repoRoot, state.flowid)));
  writeYaml(statePath(repoRoot, state.flowid), state);
}

function appendBlock(repoRoot: string, flowid: string, block: any): void {
  const blocksFile = blocksPath(repoRoot, flowid);
  ensureDir(path.dirname(blocksFile));
  interface BlocksFile { blocklog?: string; version?: number; flowid?: string; updated_at?: string; blocks: any[]; }
  const existing: BlocksFile = readYaml<BlocksFile>(blocksFile) ?? {
    blocklog: "V2",
    version: 1,
    flowid,
    updated_at: now(),
    blocks: [],
  };
  if (!existing.blocks.find((b) => b.id === block.id)) {
    existing.blocks.push(block);
    existing.updated_at = now();
    writeYaml(blocksFile, existing);
  }
}
