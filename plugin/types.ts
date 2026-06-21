/**
 * types.ts — Tipos compartidos del plugin apolo-dynamic-flow.
 *
 * Todos los módulos importan desde aquí. Mantener estable.
 */

// ============================================================================
// Phase / State Machine
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

export interface LoopCounter {
  current: number;
  max: number;
  last_decision: "" | "pass" | "refine" | "escalate" | "block";
}

export interface Loops {
  reanclaje: LoopCounter;
  "planning-bootstrap": LoopCounter;
  asr: LoopCounter;
  verdad: LoopCounter;
  shaping: LoopCounter;
  "plan-indice": LoopCounter;
  "mp-validation": LoopCounter;
  implementation: LoopCounter;
  "critical-validation": LoopCounter;
}

export interface CircuitBreaker {
  policy: "fail-closed" | "fail-open-adaptive";
  escalation_path: string[];
}

export interface HistoryEntry {
  from: Phase;
  to: Phase;
  at: string; // ISO8601
  reason: string;
  version: number;
  tokens_consumed?: number;
}

export interface ToolAbsorbed {
  id: string;
  source: string;
  kind: "mcp" | "skill" | "plugin-tool" | "native" | "external-script";
  status: "active" | "degraded" | "disabled" | "unverified";
  registered_at: string;
  fallback?: string;
}

export interface OperatorHint {
  id: string;
  severity: "info" | "warn" | "error" | "critical";
  message: string;
  created_at: string;
  resolved: boolean;
}

export interface ArtifactsRef {
  objetivo?: string;
  asr?: string;
  verdad?: string;
  shaping?: string;
  plan_indice?: string;
  current_mps?: string[];
  evidence_pack?: string;
  test_runs?: string[];
  blocks_log?: string;
}

export interface FlowState {
  flowid: string;
  version: number;
  schema_version: "V2";
  created_at: string;
  updated_at: string;
  phase: Phase;
  phase_entered_at?: string;
  history: HistoryEntry[];
  loops: Loops;
  circuit_breaker: CircuitBreaker;
  artifacts: ArtifactsRef;
  tools_absorbed: ToolAbsorbed[];
  tokens_consumed_total: number;
  operator_hints: OperatorHint[];
}

// ============================================================================
// Gate Evaluation
// ============================================================================

export type GateDecision = "pass" | "refine" | "escalate" | "block";

export interface GateResult {
  decision: GateDecision;
  reason: string;
  signals: Record<string, { estado: GateDecision; nota: string }>;
  next_phase?: Phase;
  artifacts_to_rewrite?: string[];
}

// ============================================================================
// Evidence Pack
// ============================================================================

export type EvidenceKind =
  | "file-snapshot"
  | "git-diff"
  | "git-log"
  | "symbol-list"
  | "endpoint-probe"
  | "db-query"
  | "screenshot"
  | "dom-snapshot"
  | "curl-response"
  | "test-output"
  | "runtime-log"
  | "schema-validation"
  | "mcp-capability";

export interface EvidenceItem {
  id: string; // E-001
  kind: EvidenceKind;
  source: string;
  hash: string;
  size_bytes: number;
  captured_at: string;
  summary: string;
  raw_path?: string;
  tags?: string[];
  related_symbols?: string[];
}

export interface CapabilityMap {
  playwright: "available" | "degraded" | "unavailable";
  lsp: "available" | "degraded" | "unavailable";
  git: "available" | "degraded" | "unavailable";
  python: "available" | "degraded" | "unavailable";
  node: "available" | "degraded" | "unavailable";
  curl: "available" | "degraded" | "unavailable";
  psql: "available" | "degraded" | "unavailable";
  notes?: string;
}

export interface EvidencePack {
  evidencepack: "V2";
  version: number;
  flowid: string;
  created_at: string;
  collector: {
    script: string;
    script_hash: string;
    env_fingerprint: string;
    duration_ms: number;
    invoked_by: string;
  };
  items: EvidenceItem[];
  hash_chain: string;
  capabilities: CapabilityMap;
  degradation_log: Array<{
    tool: string;
    reason: string;
    fallback_used: string;
    at: string;
  }>;
}

// ============================================================================
// Test Run
// ============================================================================

export type TestTrigger =
  | "micro-change"
  | "section-change"
  | "full-plan"
  | "manual"
  | "pre-merge";

export type TestKind =
  | "unit"
  | "integration"
  | "mutation"
  | "e2e"
  | "contract"
  | "schema-validation";

export interface TestResult {
  id: string;
  name: string;
  status: "pass" | "fail" | "skip" | "error" | "flaky";
  duration_ms: number;
  stdout_hash: string;
  stderr_hash: string;
  assertion: string;
  failure_detail?: string;
  mutation_details?: {
    mutants_generated: number;
    mutants_killed: number;
    mutants_survived: number;
    mutation_score: number;
  };
}

export interface TestRun {
  testrun: "V2";
  version: number;
  flowid: string;
  run_id: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  trigger: TestTrigger;
  scope: {
    kind: TestKind;
    targets: string[];
    mp_id?: string;
  };
  tests: TestResult[];
  summary: {
    total: number;
    passed: number;
    failed: number;
    skipped: number;
    errors: number;
    flaky: number;
  };
  exit_code: number;
  rollback_triggered: boolean;
  rollback_log?: string;
}

// ============================================================================
// Tool Registry / Absorption
// ============================================================================

export interface RegisteredTool {
  id: string;
  source: string;
  kind: "mcp" | "skill" | "plugin-tool" | "native" | "external-script";
  name?: string;
  status: "active" | "degraded" | "disabled" | "unverified";
  registered_at: string;
  last_verified_at?: string;
  capabilities: string[];
  invoke: {
    method: "mcp-call" | "bash-script" | "ts-function" | "http-endpoint";
    target: string;
    input_schema?: object;
    output_schema?: object;
  };
  fallback?: string;
  health_check?: {
    command: string;
    expected_exit: number;
    interval_seconds: number;
  };
  notes?: string;
}

export interface ToolRegistry {
  toolregistry: "V2";
  version: number;
  updated_at: string;
  tools: RegisteredTool[];
  conflicts: Array<{
    tools: string[];
    capability: string;
    resolution: "priority-first" | "manual-pick" | "merge" | "fallback-chain";
    resolved_at?: string;
  }>;
}

// ============================================================================
// Block Log
// ============================================================================

export type BlockKind =
  | "missing-artifact"
  | "missing-evidence"
  | "contradiction"
  | "unverifiable-mutation"
  | "fallback-impossible"
  | "circuit-breaker-exhausted"
  | "tool-unavailable"
  | "operator-decision-required"
  | "plan-cycle"
  | "context-overload";

export interface Block {
  id: string; // BLOQUEO-001
  detected_at: string;
  resolved_at: string | null;
  phase: Phase;
  kind: BlockKind;
  severity: "soft" | "hard" | "critical";
  status: "active" | "resolved" | "escalated" | "deferred";
  description: string;
  affected_units?: string[];
  affected_artifacts?: string[];
  suggested_resolution?: string;
  resolution_path?: string;
  linked_telemetry?: string[];
}

// ============================================================================
// Telemetry
// ============================================================================

export type TelemetryKind =
  | "phase-enter"
  | "phase-exit"
  | "loop-iter"
  | "gate-evaluated"
  | "block-detected"
  | "block-resolved"
  | "escalate"
  | "degrade"
  | "tool-absorbed"
  | "tool-invoked"
  | "tool-failed"
  | "evidence-captured"
  | "plan-version-bump"
  | "test-run"
  | "test-fail"
  | "rollback"
  | "tokens-spent"
  | "operator-hint";

export interface TelemetryEvent {
  eventid: string;
  flowid: string;
  at: string;
  kind: TelemetryKind;
  phase: Phase;
  severity: "info" | "warn" | "error" | "critical";
  message: string;
  payload?: Record<string, unknown>;
  tokens?: number;
  duration_ms?: number;
}

// ============================================================================
// Plugin context (passed to hooks)
// ============================================================================

export interface PluginContext {
  flowid: string;
  statePath: string;
  evidencePath: string;
  blocksPath: string;
  telemetryPath: string;
  toolRegistryPath: string;
  repoRoot: string;
  log: (msg: string, severity?: "info" | "warn" | "error") => void;
  emit: (event: Omit<TelemetryEvent, "eventid" | "at" | "flowid">) => void;
}
