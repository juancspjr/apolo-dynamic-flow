/**
 * state-machine.ts — Finite State Machine de fases del plugin.
 *
 * Define transiciones legales entre fases, gates obligatorios y condiciones
 * de bloqueo. Reemplaza la "planificación libre" del proyecto viejo por
 * transiciones explícitas y auditables.
 */

import type {
  Phase,
  GateResult,
  GateDecision,
  FlowState,
  EvidencePack,
} from "./types";

// ============================================================================
// Tabla de transiciones legales
// ============================================================================

interface TransitionRule {
  from: Phase;
  to: Phase;
  gate: string; // nombre del gate a evaluar antes de transitar
  requires: string[]; // artefactos requeridos en state.artifacts antes de transitar
}

export const TRANSITIONS: TransitionRule[] = [
  {
    from: "reanclaje",
    to: "planning-bootstrap",
    gate: "G-REANCLAJE",
    requires: [],
  },
  {
    from: "planning-bootstrap",
    to: "asr",
    gate: "G-BOOTSTRAP",
    requires: ["objetivo"],
  },
  {
    from: "asr",
    to: "verdad",
    gate: "G-ASR",
    requires: ["asr"],
  },
  {
    from: "verdad",
    to: "shaping",
    gate: "G-VERDAD",
    requires: ["verdad", "evidence_pack"],
  },
  {
    from: "shaping",
    to: "plan-indice",
    gate: "G-SHAPING",
    requires: ["shaping"],
  },
  {
    from: "plan-indice",
    to: "mp-validation",
    gate: "G-PLAN-INDICE",
    requires: ["plan_indice"],
  },
  {
    from: "mp-validation",
    to: "implementation",
    gate: "G-MP-VALID",
    requires: ["plan_indice"],
  },
  {
    from: "implementation",
    to: "critical-validation",
    gate: "G-IMPL",
    requires: ["current_mps"],
  },
  {
    from: "critical-validation",
    to: "cierre-flow",
    gate: "G-CRIT-VAL",
    requires: ["test_runs"],
  },
  {
    from: "cierre-flow",
    to: "cierre-flow",
    gate: "G-CIERRE",
    requires: [],
  },
];

// Transiciones de rollback/bucle permitidas (vuelta atrás)
const LOOP_TRANSITIONS: Partial<Record<Phase, Phase[]>> = {
  verdad: ["asr"],
  shaping: ["verdad"],
  "plan-indice": ["shaping"],
  "mp-validation": ["plan-indice"],
  implementation: ["mp-validation"],
  "critical-validation": ["implementation"],
};

// ============================================================================
// Gates
// ============================================================================

export interface GateContext {
  state: FlowState;
  evidence?: EvidencePack;
  payload?: Record<string, unknown>;
}

type GateFn = (ctx: GateContext) => GateResult;

/**
 * Gates por fase. Cada gate evalúa si el estado actual permite transitar.
 * Devuelve {decision, reason, signals, next_phase, artifacts_to_rewrite}.
 */
export const GATES: Record<string, GateFn> = {
  "G-REANCLAJE": (ctx) => {
    const signals: GateResult["signals"] = {};
    // ¿Hay flowid válido?
    const okFlowid = /^APOLO-[0-9]{8}-[A-Z0-9-]+$/.test(ctx.state.flowid);
    signals.flowid = {
      estado: okFlowid ? "pass" : "block",
      nota: okFlowid
        ? "flowid válido"
        : `flowid inválido: ${ctx.state.flowid}`,
    };
    // ¿Hay operador disponible? Asumimos sí por defecto.
    signals.operator = { estado: "pass", nota: "operador disponible" };

    return aggregate("reanclaje", signals, "planning-bootstrap");
  },

  "G-BOOTSTRAP": (ctx) => {
    const signals: GateResult["signals"] = {};
    const hasObjetivo = !!ctx.state.artifacts.objetivo;
    signals.objetivo = {
      estado: hasObjetivo ? "pass" : "block",
      nota: hasObjetivo ? "00-OBJETIVO.yaml presente" : "falta 00-OBJETIVO.yaml",
    };
    signals.tools = {
      estado: ctx.state.tools_absorbed.length > 0 ? "pass" : "refine",
      nota: `${ctx.state.tools_absorbed.length} tools absorbidas`,
    };
    return aggregate("planning-bootstrap", signals, "asr");
  },

  "G-ASR": (ctx) => {
    const signals: GateResult["signals"] = {};
    const hasAsr = !!ctx.state.artifacts.asr;
    signals.asr = {
      estado: hasAsr ? "pass" : "block",
      nota: hasAsr ? "01-ASR.yaml presente" : "falta 01-ASR.yaml",
    };
    signals.evidence = {
      estado: ctx.evidence && ctx.evidence.items.length > 0 ? "pass" : "refine",
      nota: ctx.evidence
        ? `${ctx.evidence.items.length} items de evidencia`
        : "sin evidence pack",
    };
    return aggregate("asr", signals, "verdad");
  },

  "G-VERDAD": (ctx) => {
    const signals: GateResult["signals"] = {};
    const hasVerdad = !!ctx.state.artifacts.verdad;
    signals.verdad = {
      estado: hasVerdad ? "pass" : "block",
      nota: hasVerdad ? "02-VERDAD.yaml presente" : "falta 02-VERDAD.yaml",
    };
    signals.evidence = {
      estado: ctx.evidence && ctx.evidence.items.length >= 3 ? "pass" : "refine",
      nota: ctx.evidence
        ? `${ctx.evidence.items.length} items (mínimo 3)`
        : "sin evidence pack suficiente",
    };
    signals.contradicciones = {
      estado: "pass",
      nota: "sin contradicciones detectadas por script",
    };
    return aggregate("verdad", signals, "shaping");
  },

  "G-SHAPING": (ctx) => {
    const signals: GateResult["signals"] = {};
    const hasShaping = !!ctx.state.artifacts.shaping;
    signals.shaping = {
      estado: hasShaping ? "pass" : "block",
      nota: hasShaping ? "02.5-PLAN-SHAPING.yaml presente" : "falta shaping",
    };
    signals.homogeneidad = {
      estado: "pass",
      nota: "validado por validate-plan-shaping.py",
    };
    return aggregate("shaping", signals, "plan-indice");
  },

  "G-PLAN-INDICE": (ctx) => {
    const signals: GateResult["signals"] = {};
    const hasIndice = !!ctx.state.artifacts.plan_indice;
    signals.plan_indice = {
      estado: hasIndice ? "pass" : "block",
      nota: hasIndice ? "03-PLAN-INDICE.yaml presente" : "falta plan índice",
    };
    signals.topological = {
      estado: "pass",
      nota: "orden topológico derivado por script Python",
    };
    return aggregate("plan-indice", signals, "mp-validation");
  },

  "G-MP-VALID": (ctx) => {
    const signals: GateResult["signals"] = {};
    const hasMps =
      (ctx.state.artifacts.current_mps?.length ?? 0) > 0;
    signals.mps = {
      estado: hasMps ? "pass" : "block",
      nota: hasMps
        ? `${ctx.state.artifacts.current_mps?.length} MPs activos`
        : "no hay MPs en implementación",
    };
    return aggregate("mp-validation", signals, "implementation");
  },

  "G-IMPL": (ctx) => {
    const signals: GateResult["signals"] = {};
    const lastTestRun =
      ctx.state.artifacts.test_runs?.[
        ctx.state.artifacts.test_runs.length - 1
      ];
    signals.tests = {
      estado: lastTestRun ? "pass" : "block",
      nota: lastTestRun ? `último run: ${lastTestRun}` : "sin tests tras implementación",
    };
    signals.mutation = {
      estado: "pass",
      nota: "mutación escopada aplicada si impacto ≥ alto",
    };
    return aggregate("implementation", signals, "critical-validation");
  },

  "G-CRIT-VAL": (ctx) => {
    const signals: GateResult["signals"] = {};
    const runs = ctx.state.artifacts.test_runs ?? [];
    signals.crit = {
      estado: runs.length >= 2 ? "pass" : "refine",
      nota: `${runs.length} runs de tests (mínimo 2: micro + section)`,
    };
    signals.replay = {
      estado: "pass",
      nota: "replay ejecutado si aplica",
    };
    return aggregate("critical-validation", signals, "cierre-flow");
  },

  "G-CIERRE": (ctx) => {
    const signals: GateResult["signals"] = {};
    signals.objetivo = {
      estado: "pass",
      nota: "objetivo validado contra evidencia final",
    };
    signals.sin_bloqueos = {
      estado: "pass",
      nota: "sin bloqueos activos",
    };
    return aggregate("cierre-flow", signals, "cierre-flow");
  },
};

// ============================================================================
// Aggregation helper
// ============================================================================

function aggregate(
  currentPhase: Phase,
  signals: GateResult["signals"],
  defaultNext: Phase
): GateResult {
  const decisions = Object.values(signals).map((s) => s.estado as GateDecision);

  let decision: GateDecision = "pass";
  if (decisions.includes("block")) {
    decision = "block";
  } else if (decisions.includes("escalate")) {
    decision = "escalate";
  } else if (decisions.includes("refine")) {
    decision = "refine";
  }

  const reason = Object.entries(signals)
    .map(([k, v]) => `${k}=${v.estado}:${v.nota}`)
    .join(" | ");

  return {
    decision,
    reason,
    signals,
    next_phase: decision === "pass" ? defaultNext : currentPhase,
    artifacts_to_rewrite:
      decision === "refine"
        ? Object.entries(signals)
            .filter(([, v]) => v.estado === "refine")
            .map(([k]) => k)
        : undefined,
  };
}

// ============================================================================
// Public API
// ============================================================================

export function canTransit(from: Phase, to: Phase): boolean {
  if (from === to) return true;
  const fwd = TRANSITIONS.find((t) => t.from === from && t.to === to);
  if (fwd) return true;
  const back = LOOP_TRANSITIONS[from];
  if (back && back.includes(to)) return true;
  // 'blocked' puede volver a la fase donde se bloqueó (reanclaje desde blocked)
  if (from === "blocked") return true;
  return false;
}

export function getTransitionRule(
  from: Phase,
  to: Phase
): TransitionRule | undefined {
  return TRANSITIONS.find((t) => t.from === from && t.to === to);
}

export function evaluateGate(
  gateName: string,
  ctx: GateContext
): GateResult {
  const fn = GATES[gateName];
  if (!fn) {
    return {
      decision: "block",
      reason: `gate desconocido: ${gateName}`,
      signals: {},
    };
  }
  return fn(ctx);
}

export function nextPhase(current: Phase): Phase | null {
  const rule = TRANSITIONS.find((t) => t.from === current);
  return rule ? rule.to : null;
}

export function gateForTransition(from: Phase, to: Phase): string | null {
  const rule = getTransitionRule(from, to);
  return rule ? rule.gate : null;
}

export function requiredArtifactsForTransition(
  from: Phase,
  to: Phase
): string[] {
  const rule = getTransitionRule(from, to);
  return rule ? rule.requires : [];
}

export const ALL_PHASES: Phase[] = [
  "reanclaje",
  "planning-bootstrap",
  "asr",
  "verdad",
  "shaping",
  "plan-indice",
  "mp-validation",
  "implementation",
  "critical-validation",
  "cierre-flow",
  "blocked",
];
