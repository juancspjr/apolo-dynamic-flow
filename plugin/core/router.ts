/**
 * router.ts — Router declarativo basado en routing-rules.json.
 *
 * Reemplaza el hardcoding de "qué agent sigue en qué fase" por un sistema
 * declarativo: las reglas se cargan desde `routing-rules.json` (en el repoRoot),
 * se ordenan por `priority` (1=máxima, default 50), y la primera que cumple
 * TODAS las condiciones del `when` determina el `next_agent`.
 *
 * Contrato:
 *   - Si ninguna regla matchea → fallback a `orchestrator` con rule_id "FALLBACK".
 *   - Cada decisión se loguea vía runtime-logger.ts (auditable).
 *
 * Conforme al schema: schemas/json/routing-rules.json
 */

import * as fs from "fs";
import * as path from "path";
import { log as auditLog } from "./runtime-logger";

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
  | "cierre-flow"
  | "blocked";

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

export interface RoutingCondition {
  phase?: Phase;
  artifacts_present?: string[];
  artifacts_absent?: string[];
  blocker_active?: boolean;
  mp_ready?: boolean;
  deep_evidence_required?: boolean;
}

export interface RoutingAction {
  next_agent: NextAgent;
  reason: string;
  circuit_breaker?: boolean;
}

export interface RoutingRule {
  id: string;
  priority?: number;
  when: RoutingCondition;
  then: RoutingAction;
}

export interface RoutingRulesFile {
  version: string;
  rules: RoutingRule[];
}

export interface RoutingContext {
  flow_id: string;
  phase: Phase;
  artifacts_present?: string[];
  blocker_active?: boolean;
  mp_ready?: boolean;
  deep_evidence_required?: boolean;
  repoRoot?: string;
}

export interface RouteResult {
  next_agent: NextAgent;
  rule_id: string;
  reason: string;
  circuit_breaker: boolean;
}

// ============================================================================
// Rules cache
// ============================================================================

let rulesCache: RoutingRulesFile | null = null;
let cachedRepoRoot: string | null = null;

export function _resetRulesCache(): void {
  rulesCache = null;
  cachedRepoRoot = null;
}

export function loadRoutingRules(repoRoot: string = process.cwd()): RoutingRulesFile {
  if (rulesCache && cachedRepoRoot === repoRoot) {
    return rulesCache;
  }
  const rulesPath = path.join(repoRoot, "routing-rules.json");
  if (!fs.existsSync(rulesPath)) {
    const empty: RoutingRulesFile = { version: "v0.0", rules: [] };
    rulesCache = empty;
    cachedRepoRoot = repoRoot;
    return empty;
  }
  try {
    const raw = fs.readFileSync(rulesPath, "utf8");
    const parsed = JSON.parse(raw) as RoutingRulesFile;
    // Ordenar por priority asc (default 50)
    const sorted: RoutingRulesFile = {
      version: parsed.version ?? "v0.0",
      rules: (parsed.rules ?? []).slice().sort((a, b) => {
        const pa = typeof a.priority === "number" ? a.priority : 50;
        const pb = typeof b.priority === "number" ? b.priority : 50;
        return pa - pb;
      }),
    };
    rulesCache = sorted;
    cachedRepoRoot = repoRoot;
    return sorted;
  } catch {
    const empty: RoutingRulesFile = { version: "v0.0", rules: [] };
    rulesCache = empty;
    cachedRepoRoot = repoRoot;
    return empty;
  }
}

// ============================================================================
// Matching
// ============================================================================

function matchesCondition(
  cond: RoutingCondition,
  ctx: RoutingContext
): boolean {
  if (cond.phase && cond.phase !== ctx.phase) return false;

  if (cond.artifacts_present && cond.artifacts_present.length > 0) {
    const present = new Set(ctx.artifacts_present ?? []);
    for (const a of cond.artifacts_present) {
      if (!present.has(a)) return false;
    }
  }

  if (cond.artifacts_absent && cond.artifacts_absent.length > 0) {
    const present = new Set(ctx.artifacts_present ?? []);
    for (const a of cond.artifacts_absent) {
      if (present.has(a)) return false;
    }
  }

  if (typeof cond.blocker_active === "boolean") {
    if (!!ctx.blocker_active !== cond.blocker_active) return false;
  }

  if (typeof cond.mp_ready === "boolean") {
    if (!!ctx.mp_ready !== cond.mp_ready) return false;
  }

  if (typeof cond.deep_evidence_required === "boolean") {
    if (!!ctx.deep_evidence_required !== cond.deep_evidence_required) return false;
  }

  return true;
}

export function buildRoutingContext(input: {
  flow_id: string;
  phase: Phase;
  artifacts_present?: string[];
  blocker_active?: boolean;
  mp_ready?: boolean;
  deep_evidence_required?: boolean;
  repoRoot?: string;
}): RoutingContext {
  return {
    flow_id: input.flow_id,
    phase: input.phase,
    artifacts_present: input.artifacts_present ?? [],
    blocker_active: input.blocker_active ?? false,
    mp_ready: input.mp_ready ?? false,
    deep_evidence_required: input.deep_evidence_required ?? false,
    repoRoot: input.repoRoot ?? process.cwd(),
  };
}

export function route(ctx: RoutingContext): RouteResult {
  const repoRoot = ctx.repoRoot ?? process.cwd();
  const rules = loadRoutingRules(repoRoot);

  for (const rule of rules.rules) {
    if (matchesCondition(rule.when, ctx)) {
      const result: RouteResult = {
        next_agent: rule.then.next_agent,
        rule_id: rule.id,
        reason: rule.then.reason,
        circuit_breaker: rule.then.circuit_breaker ?? false,
      };
      auditLog(
        {
          flow_id: ctx.flow_id,
          actor: "plugin:apolo-dynamic-flow",
          action: "decision_made",
          outcome: result.circuit_breaker ? "blocked" : "success",
          decision: {
            type: "next_agent",
            value: result.next_agent,
            reasoning: result.reason,
            rule_id: result.rule_id,
          },
          context: {
            phase: ctx.phase,
            artifacts_present: ctx.artifacts_present,
            blocker_active: ctx.blocker_active,
            mp_ready: ctx.mp_ready,
            deep_evidence_required: ctx.deep_evidence_required,
          },
        },
        repoRoot
      );
      return result;
    }
  }

  // Fallback: ninguna regla matchea → orchestrator con rule_id FALLBACK
  const fallback: RouteResult = {
    next_agent: "orchestrator",
    rule_id: "FALLBACK",
    reason: "ninguna regla de routing matcheó — fallback a orchestrator",
    circuit_breaker: false,
  };
  auditLog(
    {
      flow_id: ctx.flow_id,
      actor: "plugin:apolo-dynamic-flow",
      action: "decision_made",
      outcome: "warning",
      decision: {
        type: "next_agent",
        value: fallback.next_agent,
        reasoning: fallback.reason,
        rule_id: fallback.rule_id,
      },
      context: {
        phase: ctx.phase,
        artifacts_present: ctx.artifacts_present,
        blocker_active: ctx.blocker_active,
        mp_ready: ctx.mp_ready,
        deep_evidence_required: ctx.deep_evidence_required,
      },
    },
    repoRoot
  );
  return fallback;
}
