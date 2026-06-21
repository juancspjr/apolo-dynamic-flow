/**
 * hypothesis-runner.ts — Paralelizador de hipótesis.
 *
 * Permite al orquestador generar N hipótesis en paralelo (por ejemplo, 3
 * agents truth-auditor con inputs ligeramente diferentes) y seleccionar
 * la de mayor score.
 */

import { log } from "../core/runtime-logger";

// ============================================================================
// Types
// ============================================================================

export type HypothesisAgent =
  | "orchestrator"
  | "planner"
  | "surface-scanner"
  | "truth-auditor"
  | "microplanner"
  | "implementer"
  | "mutation-guardian"
  | "evidence-acquisition";

export type HypothesisStatus = "pending" | "running" | "completed" | "failed";

export interface Hypothesis {
  id: string;
  agent: HypothesisAgent;
  inputs: Record<string, unknown>;
  status: HypothesisStatus;
  output?: unknown;
  error?: string;
  evidence_refs?: string[];
  score?: number;
}

export interface HypothesisSpec {
  hypothesis_id: string;
  agent: HypothesisAgent;
  inputs: Record<string, unknown>;
  variant_description: string;
}

export interface WinnerResult {
  winner_id: string | null;
  winner?: Hypothesis;
  total_hypotheses: number;
  completed: number;
  failed: number;
}

// ============================================================================
// Public API
// ============================================================================

export function planHypotheses(
  flowId: string,
  decision: { type: string; value: string },
  count: number
): HypothesisSpec[] {
  const specs: HypothesisSpec[] = [];
  for (let i = 1; i <= count; i++) {
    specs.push({
      hypothesis_id: `H-${i}`,
      agent: decision.value as HypothesisAgent,
      inputs: {
        variant: i,
        total_variants: count,
      },
      variant_description: `Hipótesis ${i} de ${count} para agent=${decision.value}`,
    });
  }

  log({
    flow_id: flowId,
    actor: "plugin:apolo-dynamic-flow",
    action: "parallel_hypothesis_started",
    outcome: "success",
    decision: {
      type: "next_agent",
      value: decision.value,
      reasoning: `Planificadas ${count} hipótesis en paralelo para agent=${decision.value}.`,
    },
  });

  return specs;
}

export function scoreHypothesis(h: Hypothesis): number {
  let score = 0;

  if (h.status === "completed") {
    score += 10;
  } else if (h.status === "failed") {
    return -20;
  }

  if (h.evidence_refs && h.evidence_refs.length > 0) {
    score += h.evidence_refs.length * 2;
  }

  if (h.output && typeof h.output === "object") {
    score += Math.min(Object.keys(h.output as object).length, 5);
  }

  return score;
}

export function selectWinner(
  flowId: string,
  hypotheses: Hypothesis[]
): WinnerResult {
  const scored = hypotheses.map((h) => ({
    ...h,
    score: h.score ?? scoreHypothesis(h),
  }));

  const completed = scored.filter((h) => h.status === "completed");
  const failed = scored.filter((h) => h.status === "failed");

  let winner: Hypothesis | undefined;
  if (completed.length > 0) {
    winner = completed.reduce((max, h) => ((h.score ?? 0) > (max.score ?? 0) ? h : max));
  }

  const result: WinnerResult = {
    winner_id: winner?.id ?? null,
    winner,
    total_hypotheses: hypotheses.length,
    completed: completed.length,
    failed: failed.length,
  };

  log({
    flow_id: flowId,
    actor: "plugin:apolo-dynamic-flow",
    action: "parallel_hypothesis_winner",
    outcome: winner ? "success" : "failure",
    decision: {
      type: "complete",
      value: winner?.id ?? "none",
      reasoning: winner
        ? `Ganadora: ${winner.id} con score ${winner.score}. ${completed.length}/${hypotheses.length} completadas.`
        : `Ninguna hipótesis completó. ${failed.length}/${hypotheses.length} fallaron.`,
    },
  });

  return result;
}
