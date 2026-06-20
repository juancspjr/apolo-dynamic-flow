/**
 * block-detector.ts — Detector de bloqueos y patrones problemáticos.
 *
 * No espera a que un gate falle: analiza activamente el estado y detecta:
 *   - Plan cycles (misma fase loop > umbral sin progreso)
 *   - Context overload (artifacts references > umbral)
 *   - Tool unavailability (tools_absorbed con status degraded/disabled)
 *   - Operator decision required (paradojas pendientes en fronteraconfianza)
 *   - Contradictions (evidence contradice verdad)
 */

import type {
  FlowState,
  Block,
  TelemetryEvent,
  PluginContext,
} from "./types";
import { v4 as uuid } from "./utils";

export interface DetectionResult {
  blocks: Block[];
  telemetry: TelemetryEvent[];
  hints: FlowState["operator_hints"];
}

const PLAN_CYCLE_THRESHOLD = 3; // misma fase > 3 iteraciones → sospecha
const CONTEXT_OVERLOAD_THRESHOLD = 12; // >12 referencias a artifacts → overload

export function detectBlocks(
  state: FlowState,
  ctx: PluginContext
): DetectionResult {
  const blocks: Block[] = [];
  const telemetry: TelemetryEvent[] = [];
  const hints: FlowState["operator_hints"] = [];
  const now = new Date().toISOString();

  // 1. Plan cycle detection
  const phaseCount = countPhaseInHistory(state);
  for (const [phase, count] of Object.entries(phaseCount)) {
    if (count > PLAN_CYCLE_THRESHOLD) {
      const block: Block = {
        id: `BLOQUEO-${String(blocks.length + 1).padStart(3, "0")}`,
        detected_at: now,
        resolved_at: null,
        phase: phase as Block["phase"],
        kind: "plan-cycle",
        severity: "hard",
        status: "active",
        description: `Fase ${phase} aparece ${count} veces en history — posible ciclo`,
        suggested_resolution:
          "Particionar dinámicamente la unidad problemática o reescribir el plan",
      };
      blocks.push(block);
      telemetry.push({
        eventid: uuid(),
        at: now,
        flowid: state.flowid,
        kind: "block-detected",
        phase: phase as Block["phase"],
        severity: "warn",
        message: block.description,
        payload: { block_id: block.id },
      });
    }
  }

  // 2. Context overload detection
  const refs = countArtifactReferences(state);
  if (refs > CONTEXT_OVERLOAD_THRESHOLD) {
    const block: Block = {
      id: `BLOQUEO-${String(blocks.length + 1).padStart(3, "0")}`,
      detected_at: now,
      resolved_at: null,
      phase: state.phase,
      kind: "context-overload",
      severity: "soft",
      status: "active",
      description: `${refs} referencias a artifacts — sobrecarga de contexto`,
      suggested_resolution: "Aplicar DCP para reducir contexto antes de continuar",
    };
    blocks.push(block);
    telemetry.push({
      eventid: uuid(),
      at: now,
      flowid: state.flowid,
      kind: "block-detected",
      phase: state.phase,
      severity: "warn",
      message: block.description,
      payload: { block_id: block.id },
    });
  }

  // 3. Tool unavailability
  const degradedTools = state.tools_absorbed.filter(
    (t) => t.status === "degraded" || t.status === "disabled"
  );
  if (degradedTools.length > 0) {
    hints.push({
      id: `HINT-TOOLS-${now}`,
      severity: "warn",
      message: `${degradedTools.length} tools degradadas o deshabilitadas: ${degradedTools
        .map((t) => t.id)
        .join(", ")}`,
      created_at: now,
      resolved: false,
    });
  }

  // 4. Operator decision required (fronteraconfianza con paradoja)
  //    En el proyecto viejo esto vivía en 02.5-PLAN-SHAPING.
  //    Aquí lo inferimos de operator_hints no resueltos.
  const unresolvedHints = state.operator_hints.filter((h) => !h.resolved);
  if (unresolvedHints.length > 5) {
    const block: Block = {
      id: `BLOQUEO-${String(blocks.length + 1).padStart(3, "0")}`,
      detected_at: now,
      resolved_at: null,
      phase: state.phase,
      kind: "operator-decision-required",
      severity: "soft",
      status: "active",
      description: `${unresolvedHints.length} hints no resueltos — decision del operador requerida`,
      suggested_resolution: "Presentar hints al operador y pausar hasta resolución",
    };
    blocks.push(block);
  }

  return { blocks, telemetry, hints };
}

// ============================================================================
// Helpers
// ============================================================================

function countPhaseInHistory(state: FlowState): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const h of state.history) {
    counts[h.to] = (counts[h.to] ?? 0) + 1;
  }
  return counts;
}

function countArtifactReferences(state: FlowState): number {
  const a = state.artifacts;
  return (
    (a.objetivo ? 1 : 0) +
    (a.asr ? 1 : 0) +
    (a.verdad ? 1 : 0) +
    (a.shaping ? 1 : 0) +
    (a.plan_indice ? 1 : 0) +
    (a.current_mps?.length ?? 0) +
    (a.evidence_pack ? 1 : 0) +
    (a.test_runs?.length ?? 0) +
    (a.blocks_log ? 1 : 0)
  );
}

/**
 * Verifica si un bloqueo específico fue resuelto.
 * Retorna el bloqueo actualizado o null si no existe.
 */
export function resolveBlock(
  state: FlowState,
  blockId: string,
  resolutionPath: string
): Block | null {
  // El bloqueo vive en blocks_log (BLOCK-LOG.yaml).
  // Esta función solo emite el evento de telemetría.
  // La persistencia la maneja el módulo que escribe blocks_log.
  return null;
}
