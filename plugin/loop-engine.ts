/**
 * loop-engine.ts — Motor de loop dinámico con circuit breaker adaptativo.
 *
 * Reemplaza la lógica "plan tras plan sin resolver" del proyecto viejo.
 * El loop:
 *   1. Evalúa el gate de la fase actual.
 *   2. Si pass → transita a la siguiente fase (reset loop counter).
 *   3. Si refine → incrementa loop counter; si < max → re-ejecuta fase con ajustes.
 *   4. Si escalate → transita a fase indicada en escalation_path.
 *   5. Si block → transita a 'blocked' y registra bloqueo.
 *   6. Si loop counter == max → fuerza escalate o block (no infinite loops).
 */

import type {
  FlowState,
  Phase,
  GateResult,
  Block,
  TelemetryEvent,
  PluginContext,
} from "./types";
import {
  evaluateGate,
  gateForTransition,
  nextPhase,
  canTransit,
} from "./state-machine";
import { v4 as uuid } from "./utils";

export interface LoopResult {
  state: FlowState;
  gateResult: GateResult;
  transitioned: boolean;
  fromPhase: Phase;
  toPhase: Phase;
  blockCreated?: Block;
  telemetry: TelemetryEvent[];
}

/**
 * Ejecuta UNA iteración del loop. No es recursiva — el caller decide si
 * sigue iterando. Esto permite que el orquestador exterior (TS) coordine
 * con scripts Python entre iteraciones.
 */
export function runLoopIteration(
  state: FlowState,
  ctx: PluginContext,
  gateContext?: { evidence?: import("./types").EvidencePack; payload?: Record<string, unknown> }
): LoopResult {
  const telemetry: TelemetryEvent[] = [];
  const now = new Date().toISOString();

  const emit = (e: Omit<TelemetryEvent, "eventid" | "at" | "flowid">) => {
    telemetry.push({
      eventid: uuid(),
      at: now,
      flowid: state.flowid,
      ...e,
    });
  };

  // 1. Identificar gate de la fase actual
  const target = nextPhase(state.phase);
  if (!target) {
    emit({
      kind: "phase-exit",
      phase: state.phase,
      severity: "info",
      message: `No hay siguiente fase desde ${state.phase}`,
    });
    return {
      state,
      gateResult: { decision: "pass", reason: "terminal phase", signals: {} },
      transitioned: false,
      fromPhase: state.phase,
      toPhase: state.phase,
      telemetry,
    };
  }

  const gateName = gateForTransition(state.phase, target);
  if (!gateName) {
    emit({
      kind: "block-detected",
      phase: state.phase,
      severity: "error",
      message: `No hay gate definido para transición ${state.phase} → ${target}`,
    });
    return blockAndStay(state, ctx, {
      kind: "fallback-impossible",
      description: `sin gate para ${state.phase} → ${target}`,
    }, telemetry);
  }

  // 2. Evaluar gate
  const gateResult = evaluateGate(gateName, {
    state,
    evidence: gateContext?.evidence,
    payload: gateContext?.payload,
  });

  emit({
    kind: "gate-evaluated",
    phase: state.phase,
    severity: gateResult.decision === "block" ? "critical" : "info",
    message: `gate ${gateName} → ${gateResult.decision}: ${gateResult.reason}`,
    payload: { signals: gateResult.signals },
  });

  // 3. Actuar según decisión
  switch (gateResult.decision) {
    case "pass":
      return transit(state, ctx, target, gateResult, telemetry, "gate-pass");

    case "refine": {
      // Incrementar loop counter
      const counter = state.loops[state.phase as keyof typeof state.loops];
      if (!counter) {
        // Fase sin counter (ej: cierre-flow) → solo registrar y quedarse
        return {
          state,
          gateResult,
          transitioned: false,
          fromPhase: state.phase,
          toPhase: state.phase,
          telemetry,
        };
      }
      const newCurrent = counter.current + 1;
      const maxed = newCurrent >= counter.max;

      emit({
        kind: "loop-iter",
        phase: state.phase,
        severity: maxed ? "warn" : "info",
        message: `loop iter ${newCurrent}/${counter.max}`,
      });

      // Actualizar counter
      const newState: FlowState = {
        ...state,
        loops: {
          ...state.loops,
          [state.phase]: {
            ...counter,
            current: newCurrent,
            last_decision: "refine",
          },
        },
      };

      if (maxed) {
        // Circuit breaker disparado
        if (state.circuit_breaker.policy === "fail-open-adaptive" &&
            state.circuit_breaker.escalation_path.length > 0) {
          const escalateTo = state.circuit_breaker.escalation_path[0] as Phase;
          if (canTransit(state.phase, escalateTo)) {
            return transit(newState, ctx, escalateTo, gateResult, telemetry, "circuit-breaker-escalate");
          }
        }
        // fail-closed o sin escalation_path → bloquear
        return blockAndStay(newState, ctx, {
          kind: "circuit-breaker-exhausted",
          description: `fase ${state.phase} agotó ${counter.max} iteraciones`,
          affected_units: gateResult.artifacts_to_rewrite,
        }, telemetry);
      }

      // No maxed → quedarse en la fase y volver a intentar
      newState.updated_at = new Date().toISOString();
      return {
        state: newState,
        gateResult,
        transitioned: false,
        fromPhase: state.phase,
        toPhase: state.phase,
        telemetry,
      };
    }

    case "escalate": {
      const escalateTo =
        state.circuit_breaker.escalation_path[0] as Phase | undefined;
      if (escalateTo && canTransit(state.phase, escalateTo)) {
        return transit(state, ctx, escalateTo, gateResult, telemetry, "gate-escalate");
      }
      return blockAndStay(state, ctx, {
        kind: "fallback-impossible",
        description: `escalate solicitado pero no hay escalation_path válido desde ${state.phase}`,
      }, telemetry);
    }

    case "block":
      return blockAndStay(state, ctx, {
        kind: "missing-artifact",
        description: gateResult.reason,
      }, telemetry);
  }
}

// ============================================================================
// Helpers
// ============================================================================

function transit(
  state: FlowState,
  ctx: PluginContext,
  to: Phase,
  gateResult: GateResult,
  telemetry: TelemetryEvent[],
  reason: string
): LoopResult {
  const now = new Date().toISOString();
  const fromPhase = state.phase;

  const newState: FlowState = {
    ...state,
    version: state.version + 1,
    phase: to,
    phase_entered_at: now,
    updated_at: now,
    history: [
      ...state.history,
      {
        from: fromPhase,
        to,
        at: now,
        reason,
        version: state.version + 1,
      },
    ],
    // Reset loop counter de la fase destino
    loops: resetCounter(state.loops, to),
  };

  telemetry.push({
    eventid: uuid(),
    at: now,
    flowid: state.flowid,
    kind: "phase-enter",
    phase: to,
    severity: "info",
    message: `transit ${fromPhase} → ${to} (${reason})`,
  });

  return {
    state: newState,
    gateResult,
    transitioned: true,
    fromPhase,
    toPhase: to,
    telemetry,
  };
}

function blockAndStay(
  state: FlowState,
  ctx: PluginContext,
  blockData: {
    kind: Block["kind"];
    description: string;
    affected_units?: string[];
  },
  telemetry: TelemetryEvent[]
): LoopResult {
  const now = new Date().toISOString();
  const blockId = `BLOQUEO-${String(state.history.length + 1).padStart(3, "0")}`;
  const block: Block = {
    id: blockId,
    detected_at: now,
    resolved_at: null,
    phase: state.phase,
    kind: blockData.kind,
    severity: "hard",
    status: "active",
    description: blockData.description,
    affected_units: blockData.affected_units,
    suggested_resolution: suggestResolution(blockData.kind),
  };

  const newState: FlowState = {
    ...state,
    version: state.version + 1,
    phase: "blocked",
    phase_entered_at: now,
    updated_at: now,
    history: [
      ...state.history,
      {
        from: state.phase,
        to: "blocked",
        at: now,
        reason: `block: ${blockData.description}`,
        version: state.version + 1,
      },
    ],
    artifacts: {
      ...state.artifacts,
      blocks_log: ctx.blocksPath,
    },
  };

  telemetry.push({
    eventid: uuid(),
    at: now,
    flowid: state.flowid,
    kind: "block-detected",
    phase: state.phase,
    severity: "critical",
    message: `${blockId}: ${blockData.description}`,
    payload: { block },
  });

  return {
    state: newState,
    gateResult: {
      decision: "block",
      reason: blockData.description,
      signals: {},
    },
    transitioned: true,
    fromPhase: state.phase,
    toPhase: "blocked",
    blockCreated: block,
    telemetry,
  };
}

function resetCounter(loops: FlowState["loops"], phase: Phase): FlowState["loops"] {
  if (phase in loops) {
    return {
      ...loops,
      [phase]: { ...(loops as any)[phase], current: 0, last_decision: "" },
    };
  }
  return loops;
}

function suggestResolution(kind: Block["kind"]): string {
  const map: Record<Block["kind"], string> = {
    "missing-artifact": "Generar el artefacto faltante con el script Python correspondiente",
    "missing-evidence": "Ejecutar scripts/python/collect_evidence.py con el scope requerido",
    "contradiction": "Recolectar evidencia adicional o pedir decisión al operador",
    "unverifiable-mutation": "Reducir scope del MP o pedir mutación específica al operador",
    "fallback-impossible": "Instalar tool faltante o redefinir el gate",
    "circuit-breaker-exhausted": "Reescribir el plan dinámico con nueva partición de unidades",
    "tool-unavailable": "Absorber tool externa o degradar con justificación",
    "operator-decision-required": "Notificar al operador y esperar respuesta",
    "plan-cycle": "Forzar partición dinámica de la unidad problemática",
    "context-overload": "Aplicar DCP para reducir contexto antes de continuar",
  };
  return map[kind];
}
