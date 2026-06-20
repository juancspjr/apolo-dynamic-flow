/**
 * inspector.ts — CLI de inspección del plugin.
 *
 * Comando: apolo-inspect <subcommand> [args]
 * Subcomandos:
 *   state          — muestra estado del flow activo
 *   tools          — lista tools absorbidas y su status
 *   blocks         — lista bloqueos activos
 *   telemetry      — muestra stats de telemetría
 *   evidence       — lista items del evidence pack activo
 *   plan           — muestra plan dinámico actual
 *   conflicts      — muestra conflictos entre tools
 *   health         — verifica salud de todas las tools
 *   all            — resumen completo
 */

import * as fs from "fs";
import * as path from "path";
import type {
  FlowState,
  ToolRegistry,
  EvidencePack,
  Block,
} from "./types";
import { readYaml } from "./utils";
import { computeStats, readEvents } from "./telemetry";
import { spawnSync } from "child_process";

export interface InspectOptions {
  repoRoot: string;
  flowid?: string;
  json?: boolean;
}

export function inspectState(opts: InspectOptions): string {
  if (!opts.flowid) return error("flowid requerido", opts.json);
  const statePath = path.join(
    opts.repoRoot,
    "plan",
    "active",
    opts.flowid,
    "FLOW-STATE.yaml"
  );
  const state = readYaml<FlowState>(statePath);
  if (!state) return error(`no se encontró state en ${statePath}`, opts.json);

  if (opts.json) return JSON.stringify(state, null, 2);

  const lines: string[] = [
    `Flow: ${state.flowid}`,
    `Phase: ${state.phase} (entered: ${state.phase_entered_at})`,
    `Version: ${state.version}`,
    `Tokens consumidos: ${state.tokens_consumed_total}`,
    `Tools absorbidas: ${state.tools_absorbed.length}`,
    `Hints activos: ${state.operator_hints.filter((h) => !h.resolved).length}`,
    ``,
    `Loops por fase:`,
  ];
  for (const [phase, c] of Object.entries(state.loops)) {
    const counter = c as { current: number; max: number; last_decision: string };
    lines.push(
      `  ${phase.padEnd(22)} ${counter.current}/${counter.max} ${counter.last_decision}`
    );
  }
  lines.push(``, `Artifacts:`);
  for (const [k, v] of Object.entries(state.artifacts)) {
    if (Array.isArray(v)) {
      lines.push(`  ${k}: [${v.length} items]`);
    } else {
      lines.push(`  ${k}: ${v ?? "—"}`);
    }
  }
  lines.push(``, `History (${state.history.length} transiciones):`);
  for (const h of state.history.slice(-10)) {
    lines.push(`  ${h.at} ${h.from} → ${h.to} (${h.reason})`);
  }
  return lines.join("\n");
}

export function inspectTools(opts: InspectOptions): string {
  const registryPath = path.join(
    opts.repoRoot,
    ".opencode",
    "apolo-dynamic",
    "TOOL-REGISTRY.yaml"
  );
  const reg = readYaml<ToolRegistry>(registryPath);
  if (!reg) return error(`no se encontró registry en ${registryPath}`, opts.json);

  if (opts.json) return JSON.stringify(reg, null, 2);

  const lines: string[] = [
    `Tool Registry v${reg.version} (updated ${reg.updated_at})`,
    `${reg.tools.length} tools registradas, ${reg.conflicts.length} conflictos`,
    ``,
    `Tools:`,
  ];
  for (const t of reg.tools) {
    const caps = t.capabilities.join(",");
    const status = t.status.padEnd(10);
    lines.push(`  [${status}] ${t.id.padEnd(40)} ${t.kind.padEnd(12)} caps=${caps}`);
    if (t.fallback) lines.push(`           fallback: ${t.fallback}`);
  }
  if (reg.conflicts.length > 0) {
    lines.push(``, `Conflictos:`);
    for (const c of reg.conflicts) {
      lines.push(
        `  cap=${c.capability} res=${c.resolution} tools=${c.tools.join(", ")}`
      );
    }
  }
  return lines.join("\n");
}

export function inspectBlocks(opts: InspectOptions): string {
  if (!opts.flowid) return error("flowid requerido", opts.json);
  const blocksPath = path.join(
    opts.repoRoot,
    "plan",
    "active",
    opts.flowid,
    "BLOCK-LOG.yaml"
  );
  const data = readYaml<{ blocks: Block[] }>(blocksPath);
  if (!data) return error(`no se encontró block-log en ${blocksPath}`, opts.json);

  if (opts.json) return JSON.stringify(data, null, 2);

  const active = data.blocks.filter((b) => b.status === "active");
  const resolved = data.blocks.filter((b) => b.status === "resolved");

  const lines: string[] = [
    `Block Log — ${active.length} activos, ${resolved.length} resueltos`,
    ``,
    `Activos:`,
  ];
  for (const b of active) {
    lines.push(
      `  ${b.id} [${b.severity}] ${b.kind} @ ${b.phase}`
    );
    lines.push(`    ${b.description}`);
    if (b.suggested_resolution) {
      lines.push(`    → ${b.suggested_resolution}`);
    }
  }
  if (resolved.length > 0) {
    lines.push(``, `Resueltos (últimos 5):`);
    for (const b of resolved.slice(-5)) {
      lines.push(
        `  ${b.id} resuelto ${b.resolved_at} vía ${b.resolution_path ?? "n/a"}`
      );
    }
  }
  return lines.join("\n");
}

export function inspectTelemetry(opts: InspectOptions): string {
  if (!opts.flowid) return error("flowid requerido", opts.json);
  const telemetryPath = path.join(
    opts.repoRoot,
    "plan",
    "active",
    opts.flowid,
    "telemetry.jsonl"
  );
  if (!fs.existsSync(telemetryPath)) {
    return error(`no se encontró telemetría en ${telemetryPath}`, opts.json);
  }
  const stats = computeStats(telemetryPath);
  if (opts.json) return JSON.stringify(stats, null, 2);

  const lines: string[] = [
    `Telemetría — ${stats.total_events} eventos`,
    `Tokens: ${stats.total_tokens}`,
    `Duración total: ${stats.total_duration_ms}ms`,
    `Bloqueos: ${stats.blocks_detected} detectados, ${stats.blocks_resolved} resueltos`,
    `Tests: ${stats.tests_run} runs, ${stats.tests_failed} fails, ${stats.rollbacks} rollbacks`,
    `Tools absorbidas: ${stats.tools_absorbed}`,
    ``,
    `Eventos por kind:`,
  ];
  for (const [k, v] of Object.entries(stats.events_by_kind).sort((a, b) => b[1] - a[1])) {
    lines.push(`  ${k.padEnd(25)} ${v}`);
  }
  lines.push(``, `Duración por fase (ms):`);
  for (const [k, v] of Object.entries(stats.phase_durations_ms).sort((a, b) => b[1] - a[1])) {
    lines.push(`  ${k.padEnd(25)} ${v}`);
  }
  return lines.join("\n");
}

export function inspectEvidence(opts: InspectOptions): string {
  if (!opts.flowid) return error("flowid requerido", opts.json);
  const evidencePath = path.join(
    opts.repoRoot,
    "plan",
    "active",
    opts.flowid,
    "evidence",
    "EVIDENCE-PACK.yaml"
  );
  const pack = readYaml<EvidencePack>(evidencePath);
  if (!pack) return error(`no se encontró evidence pack`, opts.json);

  if (opts.json) return JSON.stringify(pack, null, 2);

  const lines: string[] = [
    `Evidence Pack v${pack.version} — ${pack.items.length} items`,
    `Capturado: ${pack.created_at} por ${pack.collector.script} (${pack.collector.duration_ms}ms)`,
    `Hash chain: ${pack.hash_chain.slice(0, 24)}...`,
    `Capabilities: ${JSON.stringify(pack.capabilities)}`,
    ``,
    `Items:`,
  ];
  for (const item of pack.items) {
    lines.push(
      `  ${item.id} [${item.kind.padEnd(18)}] ${item.source.slice(0, 60)}`
    );
    lines.push(`    ${item.summary}`);
    if (item.tags?.length) {
      lines.push(`    tags: ${item.tags.join(", ")}`);
    }
  }
  if (pack.degradation_log.length > 0) {
    lines.push(``, `Degradaciones:`);
    for (const d of pack.degradation_log) {
      lines.push(`  ${d.tool}: ${d.reason} → ${d.fallback_used}`);
    }
  }
  return lines.join("\n");
}

export function inspectHealth(opts: InspectOptions): string {
  const registryPath = path.join(
    opts.repoRoot,
    ".opencode",
    "apolo-dynamic",
    "TOOL-REGISTRY.yaml"
  );
  const reg = readYaml<ToolRegistry>(registryPath);
  if (!reg) return error(`no se encontró registry`, opts.json);

  const lines: string[] = [`Health check — ${reg.tools.length} tools`];
  let ok = 0, degraded = 0, unverified = 0;
  for (const t of reg.tools) {
    if (!t.health_check) {
      lines.push(`  [SKIP]     ${t.id} (sin health_check)`);
      continue;
    }
    const result = spawnSync("bash", ["-c", t.health_check.command], {
      encoding: "utf8",
      timeout: 10000,
      cwd: opts.repoRoot,
    });
    const healthy = result.status === t.health_check.expected_exit;
    if (healthy) {
      ok++;
      lines.push(`  [OK]       ${t.id}`);
    } else {
      degraded++;
      lines.push(`  [FAIL]     ${t.id} exit=${result.status} stderr=${result.stderr?.slice(0, 80)}`);
    }
  }
  unverified = reg.tools.filter((t) => t.status === "unverified").length;
  lines.push(``, `Resumen: ${ok} ok, ${degraded} fail, ${unverified} sin verificar`);
  return lines.join("\n");
}

export function inspectAll(opts: InspectOptions): string {
  const parts: string[] = [];
  parts.push("=== STATE ===");
  parts.push(inspectState(opts));
  parts.push("");
  parts.push("=== TOOLS ===");
  parts.push(inspectTools(opts));
  parts.push("");
  parts.push("=== BLOCKS ===");
  parts.push(inspectBlocks(opts));
  parts.push("");
  parts.push("=== TELEMETRY ===");
  parts.push(inspectTelemetry(opts));
  parts.push("");
  parts.push("=== EVIDENCE ===");
  parts.push(inspectEvidence(opts));
  parts.push("");
  parts.push("=== HEALTH ===");
  parts.push(inspectHealth(opts));
  return parts.join("\n");
}

function error(msg: string, json?: boolean): string {
  if (json) return JSON.stringify({ error: msg });
  return `ERROR: ${msg}`;
}
