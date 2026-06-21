/**
 * telemetry.ts — Emisor de telemetría append-only.
 *
 * Cada evento se appendea a telemetry.jsonl (1 evento por línea).
 * Consumido por panel/index.html para visualización.
 */

import * as fs from "fs";
import * as path from "path";
import type { TelemetryEvent, PluginContext } from "./types";
import { v4, ensureDir, now } from "./utils";

export interface TelemetryStats {
  total_events: number;
  events_by_kind: Record<string, number>;
  events_by_phase: Record<string, number>;
  events_by_severity: Record<string, number>;
  total_tokens: number;
  total_duration_ms: number;
  phase_durations_ms: Record<string, number>;
  blocks_detected: number;
  blocks_resolved: number;
  tests_run: number;
  tests_failed: number;
  rollbacks: number;
  tools_absorbed: number;
}

export function appendEvent(
  ctx: PluginContext,
  event: Omit<TelemetryEvent, "eventid" | "at" | "flowid">
): TelemetryEvent {
  const full: TelemetryEvent = {
    eventid: v4(),
    at: now(),
    flowid: ctx.flowid,
    ...event,
  };
  ensureDir(path.dirname(ctx.telemetryPath));
  fs.appendFileSync(ctx.telemetryPath, JSON.stringify(full) + "\n", "utf8");
  return full;
}

export function readEvents(
  telemetryPath: string,
  opts?: { since?: string; kind?: string; limit?: number }
): TelemetryEvent[] {
  if (!fs.existsSync(telemetryPath)) return [];
  const lines = fs.readFileSync(telemetryPath, "utf8").trim().split("\n");
  let events: TelemetryEvent[] = [];
  for (const line of lines) {
    if (!line) continue;
    try {
      events.push(JSON.parse(line));
    } catch {
      // skip malformed
    }
  }
  if (opts?.since) {
    events = events.filter((e) => e.at >= opts.since!);
  }
  if (opts?.kind) {
    events = events.filter((e) => e.kind === opts.kind);
  }
  if (opts?.limit) {
    events = events.slice(-opts.limit);
  }
  return events;
}

export function computeStats(
  telemetryPath: string
): TelemetryStats {
  const events = readEvents(telemetryPath);
  const stats: TelemetryStats = {
    total_events: events.length,
    events_by_kind: {},
    events_by_phase: {},
    events_by_severity: {},
    total_tokens: 0,
    total_duration_ms: 0,
    phase_durations_ms: {},
    blocks_detected: 0,
    blocks_resolved: 0,
    tests_run: 0,
    tests_failed: 0,
    rollbacks: 0,
    tools_absorbed: 0,
  };

  for (const e of events) {
    stats.events_by_kind[e.kind] = (stats.events_by_kind[e.kind] ?? 0) + 1;
    stats.events_by_phase[e.phase] = (stats.events_by_phase[e.phase] ?? 0) + 1;
    stats.events_by_severity[e.severity] =
      (stats.events_by_severity[e.severity] ?? 0) + 1;
    if (e.tokens) stats.total_tokens += e.tokens;
    if (e.duration_ms) {
      stats.total_duration_ms += e.duration_ms;
      stats.phase_durations_ms[e.phase] =
        (stats.phase_durations_ms[e.phase] ?? 0) + e.duration_ms;
    }
    if (e.kind === "block-detected") stats.blocks_detected++;
    if (e.kind === "block-resolved") stats.blocks_resolved++;
    if (e.kind === "test-run") stats.tests_run++;
    if (e.kind === "test-fail") stats.tests_failed++;
    if (e.kind === "rollback") stats.rollbacks++;
    if (e.kind === "tool-absorbed") stats.tools_absorbed++;
  }

  return stats;
}
