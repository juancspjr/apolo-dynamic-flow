/**
 * hypothesis-runner.ts — Runner de hipótesis paralelas con scoring.
 *
 * Permite ejecutar N hipótesis en paralelo (cada una con su propio agente y
 * scope) y elegir un ganador determinista vía scoring objetivo.
 *
 * API:
 *   - planHypotheses(flowId, decision, count) → Hypothesis[]
 *   - scoreHypothesis(h)                      → number
 *   - selectWinner(flowId, hypotheses)        → {winner_id|null, total, completed, failed}
 *
 * Scoring:
 *   - status "completed"     → +10
 *   - status "failed"        → -20
 *   - evidence_refs.length   → +2 c/u
 *   - output (object) keys   → +min(keys, 5) (1 punto por key, hasta 5)
 *
 * Conforme al schema: schemas/json/runtime-audit-log.json
 * (action: parallel_hypothesis_started / parallel_hypothesis_winner)
 */

import { log as auditLog } from "../core/runtime-logger";

// ============================================================================
// Types
// ============================================================================

export type HypothesisStatus = "pending" | "completed" | "failed";

export interface HypothesisDecision {
  agent?: string;
  objective: string;
  scope?: Record<string, unknown>;
}

export interface Hypothesis {
  hypothesis_id: string; // H-1, H-2, ...
  flow_id: string;
  agent: string;
  status: HypothesisStatus;
  objective: string;
  scope?: Record<string, unknown>;
  evidence_refs?: string[];
  output?: Record<string, unknown>;
  error?: string;
  score?: number;
}

export interface WinnerResult {
  winner_id: string | null;
  total_hypotheses: number;
  completed: number;
  failed: number;
  winner_score?: number;
}

// ============================================================================
// planHypotheses
// ============================================================================

export function planHypotheses(
  flowId: string,
  decision: HypothesisDecision,
  count: number
): Hypothesis[] {
  const agent = decision.agent ?? "truth-auditor";
  const result: Hypothesis[] = [];
  for (let i = 1; i <= count; i++) {
    result.push({
      hypothesis_id: `H-${i}`,
      flow_id: flowId,
      agent,
      status: "pending",
      objective: decision.objective,
      scope: decision.scope,
    });
  }
  auditLog(
    {
      flow_id: flowId,
      actor: "plugin:apolo-dynamic-flow",
      action: "parallel_hypothesis_started",
      outcome: "success",
      context: { count, agent, objective: decision.objective },
    },
    process.cwd()
  );
  return result;
}

// ============================================================================
// scoreHypothesis
// ============================================================================

export function scoreHypothesis(h: Hypothesis): number {
  let score = 0;
  if (h.status === "completed") score += 10;
  if (h.status === "failed") score -= 20;
  if (Array.isArray(h.evidence_refs)) {
    score += 2 * h.evidence_refs.length;
  }
  if (h.output && typeof h.output === "object") {
    const keys = Object.keys(h.output).length;
    score += Math.min(keys, 5);
  }
  return score;
}

// ============================================================================
// selectWinner
// ============================================================================

export function selectWinner(
  flowId: string,
  hypotheses: Hypothesis[]
): WinnerResult {
  let completed = 0;
  let failed = 0;
  let winner: Hypothesis | null = null;
  let winnerScore = -Infinity;

  for (const h of hypotheses) {
    if (h.status === "completed") completed++;
    if (h.status === "failed") failed++;
    const s = scoreHypothesis(h);
    // Mutamos una copia para no romper el input
    if (h.status === "completed" && s > winnerScore) {
      winnerScore = s;
      winner = h;
    }
  }

  const winner_id = winner ? winner.hypothesis_id : null;

  auditLog(
    {
      flow_id: flowId,
      actor: "plugin:apolo-dynamic-flow",
      action: "parallel_hypothesis_winner",
      outcome: winner ? "success" : "skipped",
      decision: winner
        ? {
            type: "complete",
            value: winner_id as string,
            reasoning: `ganador elegido con score ${winnerScore}`,
            evidence_refs: winner.evidence_refs,
          }
        : {
            type: "complete",
            value: "null",
            reasoning: "ninguna hipótesis completó — sin ganador",
          },
      context: {
        total: hypotheses.length,
        completed,
        failed,
        winner_score: winner ? winnerScore : undefined,
      },
    },
    process.cwd()
  );

  return {
    winner_id,
    total_hypotheses: hypotheses.length,
    completed,
    failed,
    winner_score: winner ? winnerScore : undefined,
  };
}
