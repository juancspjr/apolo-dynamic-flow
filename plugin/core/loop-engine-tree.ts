/**
 * loop-engine-tree.ts — Árbol de decisión del loop-engine.
 *
 * Reemplaza la lógica de "plan tras plan" por un árbol finito de decisiones.
 * Cada nodo D-NNN representa un estado del flow con hasta 5 ramificaciones.
 *
 * Conforme al schema: schemas/json/loop-engine-decision.json
 */

import * as fs from "fs";
import * as path from "path";
import { log } from "./runtime-logger";

// ============================================================================
// Types
// ============================================================================

export type BranchCondition =
  | "test_passes"
  | "test_fails_retriable"
  | "test_fails_terminal"
  | "blocker_resolved"
  | "blocker_persists"
  | "operator_confirms"
  | "operator_rejects"
  | "evidence_sufficient"
  | "evidence_insufficient"
  | "paradoja_detected"
  | "iteration_exceeded";

export type BranchAction =
  | "advance_phase"
  | "retry_mp"
  | "rollback_mp"
  | "raise_blocker"
  | "ask_operator"
  | "spawn_parallel_hypotheses"
  | "generate_evidence_script"
  | "circuit_break"
  | "close_flow";

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

export interface Branch {
  condition: BranchCondition;
  action: BranchAction;
  next_node: string | null;
  reasoning: string;
}

export interface NodeState {
  artifacts_present: string[];
  mp_active: string | null;
  blocker_active: boolean;
  iteration: number;
  last_test_result?: "pass" | "fail" | "skipped" | null;
}

export interface DecisionNode {
  id: string;
  flow_id: string;
  phase: Phase | string;
  state: NodeState;
  branches: Branch[];
  parent_node: string | null;
  created_at: string;
  resolved_at?: string | null;
  outcome?: "advanced" | "retried" | "rolled_back" | "blocked" | "operator_decision" | "circuit_broken" | "closed" | null;
}

export interface AdvanceResult {
  action: BranchAction;
  completed: boolean;
  circuit_breaker: boolean;
  node?: DecisionNode;
}

// ============================================================================
// Tree cache (per flow_id)
// ============================================================================

const treeCache = new Map<string, DecisionNode[]>();

export function _resetTreeCache(): void {
  treeCache.clear();
}

function getTree(flowId: string): DecisionNode[] {
  if (!treeCache.has(flowId)) {
    treeCache.set(flowId, []);
  }
  return treeCache.get(flowId)!;
}

function nextNodeId(flowId: string): string {
  const tree = getTree(flowId);
  return `D-${String(tree.length + 1).padStart(3, "0")}`;
}

// ============================================================================
// Default branches for a root node
// ============================================================================

function defaultBranches(): Branch[] {
  // next_node = "AUTO" significa "crear siguiente nodo automáticamente".
  // next_node = null significa "terminal, no crear siguiente".
  return [
    {
      condition: "test_passes",
      action: "advance_phase",
      next_node: null,
      reasoning: "Tests pasan, avanzar a la siguiente fase.",
    },
    {
      condition: "test_fails_retriable",
      action: "retry_mp",
      next_node: "AUTO",
      reasoning: "Tests fallan pero el error es retriable. Reintentar MP.",
    },
    {
      condition: "test_fails_terminal",
      action: "raise_blocker",
      next_node: null,
      reasoning: "Tests fallan de forma terminal. Levantar bloqueo.",
    },
    {
      condition: "blocker_persists",
      action: "ask_operator",
      next_node: null,
      reasoning: "El bloqueo persiste. Pedir decisión al operador.",
    },
    {
      condition: "iteration_exceeded",
      action: "circuit_break",
      next_node: null,
      reasoning: "Iteraciones agotadas. Circuit breaker.",
    },
  ];
}

// ============================================================================
// Public API
// ============================================================================

export function createRootNode(
  flowId: string,
  flowPath: string,
  phase: Phase | string
): DecisionNode {
  const node: DecisionNode = {
    id: "D-001",
    flow_id: flowId,
    phase,
    state: {
      artifacts_present: [],
      mp_active: null,
      blocker_active: false,
      iteration: 1,
      last_test_result: null,
    },
    branches: defaultBranches(),
    parent_node: null,
    created_at: new Date().toISOString(),
    resolved_at: null,
    outcome: null,
  };

  const tree = getTree(flowId);
  tree.push(node);

  log({
    flow_id: flowId,
    actor: "plugin:apolo-dynamic-flow",
    action: "decision_made",
    outcome: "success",
    decision: {
      type: "next_agent",
      value: `D-001 creado en phase=${phase}`,
      reasoning: "Root node del decision tree creado.",
    },
  });

  return node;
}

export function getNode(flowId: string, nodeId: string): DecisionNode | undefined {
  return getTree(flowId).find((n) => n.id === nodeId);
}

export function advance(
  flowId: string,
  flowPath: string,
  nodeId: string,
  condition: BranchCondition
): AdvanceResult {
  const node = getNode(flowId, nodeId);
  if (!node) {
    return {
      action: "circuit_break" as BranchAction,
      completed: true,
      circuit_breaker: true,
    };
  }

  const branch = node.branches.find((b) => b.condition === condition);
  if (!branch) {
    return {
      action: "circuit_break" as BranchAction,
      completed: true,
      circuit_breaker: true,
    };
  }

  // Marcar nodo como resuelto
  node.resolved_at = new Date().toISOString();

  const isCircuitBreak = branch.action === "circuit_break";
  const isTerminal =
    branch.next_node === null ||
    branch.action === "advance_phase" ||
    branch.action === "circuit_break" ||
    branch.action === "close_flow";
  const shouldCreateNext = !isTerminal && branch.next_node === "AUTO";

  // Mapear outcome
  const outcomeMap: Record<BranchAction, DecisionNode["outcome"]> = {
    advance_phase: "advanced",
    retry_mp: "retried",
    rollback_mp: "rolled_back",
    raise_blocker: "blocked",
    ask_operator: "operator_decision",
    spawn_parallel_hypotheses: "retried",
    generate_evidence_script: "retried",
    circuit_break: "circuit_broken",
    close_flow: "closed",
  };
  node.outcome = outcomeMap[branch.action] ?? null;

  // Crear siguiente nodo solo si shouldCreateNext (branch.next_node === "AUTO")
  let nextNode: DecisionNode | undefined;
  if (shouldCreateNext) {
    nextNode = {
      id: nextNodeId(flowId),
      flow_id: flowId,
      phase: node.phase,
      state: {
        ...node.state,
        iteration: node.state.iteration + 1,
      },
      branches: defaultBranches(),
      parent_node: node.id,
      created_at: new Date().toISOString(),
      resolved_at: null,
      outcome: null,
    };
    getTree(flowId).push(nextNode);
  }

  log({
    flow_id: flowId,
    actor: "plugin:apolo-dynamic-flow",
    action: "decision_made",
    outcome: isCircuitBreak ? "blocked" : "success",
    decision: {
      type: "next_agent",
      value: branch.action,
      reasoning: branch.reasoning,
    },
  });

  return {
    action: branch.action,
    completed: isTerminal,
    circuit_breaker: isCircuitBreak,
    node: nextNode,
  };
}

/**
 * Detecta circuit breaker por patrón: 3+ fallos con la misma razón para el mismo MP.
 */
export function detectCircuitBreaker(
  flowId: string,
  mpId: string,
  failures: Array<{ mp_id: string; reason: string }>
): boolean {
  const mpFailures = failures.filter((f) => f.mp_id === mpId);
  if (mpFailures.length < 3) return false;

  // Tomar las últimas 3
  const recent = mpFailures.slice(-3);
  const reasons = new Set(recent.map((f) => f.reason));
  return reasons.size === 1; // misma razón en las 3
}

/**
 * Exporta el árbol completo a JSON (para debugging/inspección).
 */
export function exportTree(flowId: string): DecisionNode[] {
  return getTree(flowId);
}
