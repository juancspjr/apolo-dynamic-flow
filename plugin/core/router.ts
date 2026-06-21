/**
 * router.ts — Router declarativo basado en routing-rules.json.
 *
 * Reemplaza la lógica opaca de "qué agent invocar ahora" por reglas
 * declarativas que el operador puede editar sin tocar código TS.
 *
 * Conforme al schema: schemas/json/routing-rules.json
 */

import * as fs from "fs";
import * as path from "path";
import { log } from "./runtime-logger";

// ============================================================================
// Types
// ============================================================================

export type Phase =
  | "reanclaje"
  | "planning-bootstrap"
  | "asr"
  | "verdad"
  | "shaping"
  | "plan-indice"
  | "mp-validation"
  | "implementation"
  | "critical-validation"
  | "cierre-flow";

export type NextAgent =
  | "orchestrator"
  | "planner"
  | "surface-scanner"
  | "truth-auditor"
  | "microplanner"
  | "implementer"
  | "mutation-guardian"
  | "evidence-acquisition"
  | "blocked"
  | "closed";

export interface RoutingContext {
  flow_id: string;
  flow_path: string;
  phase: Phase | string;
  artifacts_present: string[];
  mp_active: string | null;
  blocker_active: boolean;
  deep_evidence_required: boolean;
  mp_ready?: boolean;
}

export interface RouteResult {
  rule_id: string;
  next_agent: NextAgent;
  reason: string;
  circuit_breaker: boolean;
}

interface Rule {
  id: string;
  priority?: number;
  when: {
    phase?: string;
    artifacts_present?: string[];
    artifacts_absent?: string[];
    blocker_active?: boolean;
    mp_ready?: boolean;
    deep_evidence_required?: boolean;
  };
  then: {
    next_agent: NextAgent;
    reason: string;
    circuit_breaker?: boolean;
  };
}

interface RoutingRules {
  version: string;
  rules: Rule[];
}

// ============================================================================
// Cache
// ============================================================================

let rulesCache: RoutingRules | null = null;

export function _resetRulesCache(): void {
  rulesCache = null;
}

// ============================================================================
// Loader
// ============================================================================

export function loadRoutingRules(
  repoRoot: string = process.cwd()
): RoutingRules {
  if (rulesCache) return rulesCache;

  const rulesPath = path.join(repoRoot, "routing-rules.json");
  if (!fs.existsSync(rulesPath)) {
    throw new Error(`routing-rules.json no encontrado en ${rulesPath}`);
  }

  try {
    const content = fs.readFileSync(rulesPath, "utf8");
    rulesCache = JSON.parse(content) as RoutingRules;
    return rulesCache;
  } catch (err) {
    throw new Error(`routing-rules.json inválido: ${err}`);
  }
}

// ============================================================================
// Matching
// ============================================================================

function matchesRule(rule: Rule, ctx: RoutingContext): boolean {
  const w = rule.when;

  // phase
  if (w.phase !== undefined && w.phase !== ctx.phase) {
    return false;
  }

  // artifacts_present: todos deben estar en ctx.artifacts_present
  if (w.artifacts_present) {
    for (const a of w.artifacts_present) {
      if (!ctx.artifacts_present.includes(a)) return false;
    }
  }

  // artifacts_absent: ninguno debe estar en ctx.artifacts_present
  if (w.artifacts_absent) {
    for (const a of w.artifacts_absent) {
      if (ctx.artifacts_present.includes(a)) return false;
    }
  }

  // blocker_active
  if (w.blocker_active !== undefined && w.blocker_active !== ctx.blocker_active) {
    return false;
  }

  // mp_ready
  if (w.mp_ready !== undefined && w.mp_ready !== (ctx.mp_ready ?? !!ctx.mp_active)) {
    return false;
  }

  // deep_evidence_required
  if (
    w.deep_evidence_required !== undefined &&
    w.deep_evidence_required !== ctx.deep_evidence_required
  ) {
    return false;
  }

  return true;
}

// ============================================================================
// Public API
// ============================================================================

export function route(
  ctx: RoutingContext,
  repoRoot: string = process.cwd()
): RouteResult {
  const rules = loadRoutingRules(repoRoot);

  // Ordenar por prioridad (1 = máxima). Default 50.
  const sorted = [...rules.rules].sort((a, b) => {
    const pa = a.priority ?? 50;
    const pb = b.priority ?? 50;
    return pa - pb;
  });

  for (const rule of sorted) {
    if (matchesRule(rule, ctx)) {
      const result: RouteResult = {
        rule_id: rule.id,
        next_agent: rule.then.next_agent,
        reason: rule.then.reason,
        circuit_breaker: rule.then.circuit_breaker ?? false,
      };

      // Loguear la decisión
      log({
        flow_id: ctx.flow_id,
        actor: "plugin:apolo-dynamic-flow",
        action: "decision_made",
        outcome: "success",
        decision: {
          type: "route",
          value: result.next_agent,
          reasoning: result.reason,
          rule_id: result.rule_id,
        },
      });

      return result;
    }
  }

  // Fallback: ninguna regla matchea → orchestrator
  const fallback: RouteResult = {
    rule_id: "FALLBACK",
    next_agent: "orchestrator",
    reason: "Ninguna regla de routing-rules.json matcheó el contexto actual.",
    circuit_breaker: false,
  };

  log({
    flow_id: ctx.flow_id,
    actor: "plugin:apolo-dynamic-flow",
    action: "decision_made",
    outcome: "warning",
    decision: {
      type: "route",
      value: fallback.next_agent,
      reasoning: fallback.reason,
    },
  });

  return fallback;
}

/**
 * Construye un RoutingContext desde un FlowState simplificado.
 */
export function buildRoutingContext(params: {
  flow_id: string;
  flow_path: string;
  phase: Phase | string;
  artifacts_present: string[];
  mp_active: string | null;
  blocker_active: boolean;
  deep_evidence_required: boolean;
  mp_ready?: boolean;
}): RoutingContext {
  return {
    flow_id: params.flow_id,
    flow_path: params.flow_path,
    phase: params.phase,
    artifacts_present: params.artifacts_present,
    mp_active: params.mp_active,
    blocker_active: params.blocker_active,
    deep_evidence_required: params.deep_evidence_required,
    mp_ready: params.mp_ready,
  };
}
