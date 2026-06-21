/**
 * loop-engine-tree.ts — Árbol de decisión D-NNN con circuit breaker.
 *
 * Cada nodo D-NNN representa un punto de decisión en el loop dinámico. Tiene 5
 * branches por defecto que cubren todos los outcomes posibles de un micro-test:
 *
 *   1. test_passes            → advance_phase   (terminal)
 *   2. test_fails_retriable   → retry_mp        (con next_node="AUTO" crea D-NNN+1)
 *   3. test_fails_terminal    → raise_blocker   (terminal)
 *   4. blocker_persists       → ask_operator    (terminal)
 *   5. iteration_exceeded     → circuit_break   (terminal)
 *
 * El árbol se persiste en `plan/active/<flowid>/decision-tree.json` y cada
 * avance se loguea vía runtime-logger.ts.
 *
 * Conforme al schema: schemas/json/loop-engine-decision.json
 */

import * as fs from "fs";
import * as path from "path";
import { log as auditLog } from "./runtime-logger";

// ============================================================================
// Types
// ============================================================================

export type DecisionCondition =
  | "test_passes"
  | "test_fails_retriable"
  | "test_fails_terminal"
  | "blocker_persists"
  | "iteration_exceeded"
  | "evidence_stale"
  | "evidence_contradicts"
  | "gate_pass"
  | "gate_refine"
  | "gate_escalate"
  | "gate_block";

export type DecisionAction =
  | "advance_phase"
  | "retry_mp"
  | "raise_blocker"
  | "ask_operator"
  | "circuit_break"
  | "collect_evidence"
  | "refine_plan"
  | "rollback"
  | "no_op";

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

export interface DecisionBranch {
  condition: DecisionCondition;
  action: DecisionAction;
  next_node: string; // "D-NNN" o "AUTO"
  reasoning: string;
  terminal: boolean;
}

export interface DecisionNode {
  id: string; // D-001
  flow_id: string;
  phase: Phase;
  state: {
    artifacts_present: string[];
    mp_active?: string;
    blocker_active: boolean;
    iteration: number; // 1-10
    last_test_result?: { passed: boolean; exit_code: number };
  };
  branches: DecisionBranch[];
  created_at: string;
  parent_node: string | null;
  resolved_at?: string;
  outcome?: DecisionCondition;
}

export interface DecisionTree {
  flow_id: string;
  nodes: Record<string, DecisionNode>;
  root_id: string;
  current_id: string;
  counter: number;
}

export interface AdvanceResult {
  action: DecisionAction;
  completed: boolean;
  circuit_breaker: boolean;
  node?: DecisionNode;
}

// ============================================================================
// Tree cache
// ============================================================================

const treeCache = new Map<string, DecisionTree>();

export function _resetTreeCache(): void {
  treeCache.clear();
}

function treePath(flowId: string, repoRoot: string = process.cwd()): string {
  return path.join(repoRoot, "plan", "active", flowId, "decision-tree.json");
}

function ensureTreeDir(p: string): void {
  const dir = path.dirname(p);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function persistTree(tree: DecisionTree, repoRoot: string = process.cwd()): void {
  const p = treePath(tree.flow_id, repoRoot);
  ensureTreeDir(p);
  fs.writeFileSync(p, JSON.stringify(tree, null, 2), "utf8");
  treeCache.set(tree.flow_id, tree);
}

function loadTree(flowId: string, repoRoot: string = process.cwd()): DecisionTree | null {
  if (treeCache.has(flowId)) return treeCache.get(flowId)!;
  const p = treePath(flowId, repoRoot);
  if (!fs.existsSync(p)) return null;
  try {
    const raw = fs.readFileSync(p, "utf8");
    const tree = JSON.parse(raw) as DecisionTree;
    treeCache.set(flowId, tree);
    return tree;
  } catch {
    return null;
  }
}

// ============================================================================
// Node factories
// ============================================================================

function defaultBranches(): DecisionBranch[] {
  return [
    {
      condition: "test_passes",
      action: "advance_phase",
      next_node: "AUTO",
      reasoning: "Micro-test pasó — avanzar a la siguiente fase",
      terminal: true,
    },
    {
      condition: "test_fails_retriable",
      action: "retry_mp",
      next_node: "AUTO",
      reasoning: "Micro-test falló de forma retriable — reintentar MP con ajustes",
      terminal: false,
    },
    {
      condition: "test_fails_terminal",
      action: "raise_blocker",
      next_node: "AUTO",
      reasoning: "Micro-test falló de forma terminal — levantar bloqueo",
      terminal: true,
    },
    {
      condition: "blocker_persists",
      action: "ask_operator",
      next_node: "AUTO",
      reasoning: "Bloqueo persiste tras N intentos — pedir decisión al operador",
      terminal: true,
    },
    {
      condition: "iteration_exceeded",
      action: "circuit_break",
      next_node: "AUTO",
      reasoning: "Iteraciones agotadas — disparar circuit breaker",
      terminal: true,
    },
  ];
}

function nextNodeId(tree: DecisionTree): string {
  tree.counter += 1;
  return `D-${String(tree.counter).padStart(3, "0")}`;
}

export function createRootNode(
  flowId: string,
  phase: Phase,
  opts: {
    mp_active?: string;
    artifacts_present?: string[];
    repoRoot?: string;
  } = {}
): DecisionNode {
  const repoRoot = opts.repoRoot ?? process.cwd();
  let tree = loadTree(flowId, repoRoot);
  if (!tree) {
    tree = {
      flow_id: flowId,
      nodes: {},
      root_id: "D-001",
      current_id: "D-001",
      counter: 1,
    };
  }
  const node: DecisionNode = {
    id: "D-001",
    flow_id: flowId,
    phase,
    state: {
      artifacts_present: opts.artifacts_present ?? [],
      mp_active: opts.mp_active,
      blocker_active: false,
      iteration: 1,
    },
    branches: defaultBranches(),
    created_at: new Date().toISOString(),
    parent_node: null,
  };
  tree.nodes[node.id] = node;
  tree.root_id = node.id;
  tree.current_id = node.id;
  persistTree(tree, repoRoot);
  auditLog(
    {
      flow_id: flowId,
      actor: "plugin:apolo-dynamic-flow",
      action: "decision_made",
      outcome: "success",
      decision: {
        type: "route",
        value: node.id,
        reasoning: `Root node ${node.id} creado en fase ${phase}`,
        rule_id: node.id,
      },
      context: { phase, mp_active: opts.mp_active },
    },
    repoRoot
  );
  return node;
}

export function getNode(
  flowId: string,
  nodeId: string,
  repoRoot: string = process.cwd()
): DecisionNode | null {
  const tree = loadTree(flowId, repoRoot);
  if (!tree) return null;
  return tree.nodes[nodeId] ?? null;
}

// ============================================================================
// Advance
// ============================================================================

export function advance(
  flowId: string,
  flowPath: string,
  nodeId: string,
  condition: DecisionCondition,
  opts: { repoRoot?: string; failureReason?: string } = {}
): AdvanceResult {
  const repoRoot = opts.repoRoot ?? process.cwd();
  const tree = loadTree(flowId, repoRoot);
  if (!tree) {
    return {
      action: "no_op",
      completed: false,
      circuit_breaker: false,
    };
  }
  const node = tree.nodes[nodeId];
  if (!node) {
    return {
      action: "no_op",
      completed: false,
      circuit_breaker: false,
    };
  }

  const branch = node.branches.find((b) => b.condition === condition);
  if (!branch) {
    return {
      action: "no_op",
      completed: false,
      circuit_breaker: false,
    };
  }

  // Marcar nodo como resuelto
  node.resolved_at = new Date().toISOString();
  node.outcome = condition;

  // Caso terminal
  if (branch.terminal || branch.action === "advance_phase" ||
      branch.action === "raise_blocker" || branch.action === "ask_operator" ||
      branch.action === "circuit_break") {
    persistTree(tree, repoRoot);
    auditLog(
      {
        flow_id: flowId,
        actor: "plugin:apolo-dynamic-flow",
        action: "decision_made",
        outcome:
          branch.action === "circuit_break"
            ? "blocked"
            : branch.action === "raise_blocker"
            ? "blocked"
            : "success",
        decision: {
          type: "complete",
          value: branch.action,
          reasoning: branch.reasoning,
          rule_id: node.id,
        },
        context: { phase: node.phase, condition, node_id: node.id },
      },
      repoRoot
    );
    return {
      action: branch.action,
      completed: true,
      circuit_breaker: branch.action === "circuit_break",
    };
  }

  // Caso no-terminal: crear siguiente nodo si next_node === "AUTO"
  let nextNode: DecisionNode | undefined;
  if (branch.next_node === "AUTO") {
    const newId = nextNodeId(tree);
    const newIteration = Math.min(node.state.iteration + 1, 10);
    nextNode = {
      id: newId,
      flow_id: flowId,
      phase: node.phase,
      state: {
        artifacts_present: node.state.artifacts_present,
        mp_active: node.state.mp_active,
        blocker_active: node.state.blocker_active,
        iteration: newIteration,
      },
      branches: defaultBranches(),
      created_at: new Date().toISOString(),
      parent_node: node.id,
    };
    tree.nodes[newId] = nextNode;
    tree.current_id = newId;
  } else if (tree.nodes[branch.next_node]) {
    nextNode = tree.nodes[branch.next_node];
    tree.current_id = branch.next_node;
  }

  persistTree(tree, repoRoot);
  auditLog(
    {
      flow_id: flowId,
      actor: "plugin:apolo-dynamic-flow",
      action: "decision_made",
      outcome: "success",
      decision: {
        type: "route",
        value: branch.action,
        reasoning: branch.reasoning,
        rule_id: node.id,
      },
      context: {
        phase: node.phase,
        condition,
        node_id: node.id,
        next_node: nextNode?.id,
      },
    },
    repoRoot
  );

  return {
    action: branch.action,
    completed: false,
    circuit_breaker: false,
    node: nextNode,
  };
}

// ============================================================================
// Circuit Breaker detection
// ============================================================================

export interface FailureEntry {
  mp_id: string;
  reason: string;
  at: string;
}

export function detectCircuitBreaker(
  flowId: string,
  mpId: string,
  failures: FailureEntry[]
): boolean {
  // Tomar las últimas 3 entradas de failures para mpId
  const forMp = failures.filter((f) => f.mp_id === mpId).slice(-3);
  if (forMp.length < 3) return false;
  const firstReason = forMp[0].reason;
  return forMp.every((f) => f.reason === firstReason);
}

// ============================================================================
// Export tree
// ============================================================================

export function exportTree(
  flowId: string,
  repoRoot: string = process.cwd()
): DecisionTree | null {
  return loadTree(flowId, repoRoot);
}
