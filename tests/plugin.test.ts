/**
 * Test suite del plugin apolo-dynamic-flow.
 * Cada hook se valida contra fixtures antes de activarse en runtime.
 *
 * Adaptado del repo de referencia a la estructura de nuestro plugin:
 *   - plugin/core/runtime-logger.ts (en vez de src/core/)
 *   - plugin/core/router.ts
 *   - plugin/core/loop-engine-tree.ts
 *   - plugin/core/micro-test-runner.ts
 *   - plugin/absorbers/mcp-loader.ts
 *   - plugin/parallel/hypothesis-runner.ts
 *
 * Ejecutar:
 *   npx tsc && node --test dist/tests/plugin.test.js
 */

import { strict as assert } from "node:assert";
import { describe, it, beforeEach, afterEach } from "node:test";
import {
  _resetSeqCache,
  createFlowLogger,
  log,
  readRecentEntries,
  resolveLogPath,
} from "../plugin/core/runtime-logger";
import {
  _resetRulesCache,
  buildRoutingContext,
  loadRoutingRules,
  route,
} from "../plugin/core/router";
import {
  _resetTreeCache,
  createRootNode,
  advance,
  detectCircuitBreaker,
} from "../plugin/core/loop-engine-tree";
import {
  extractTestCommand,
  runTest,
} from "../plugin/core/micro-test-runner";
import {
  _resetMcpCache,
  detectAvailableMcps,
  invokeMcp,
  isMcpAvailable,
  suggestMcpForTask,
} from "../plugin/absorbers/mcp-loader";
import {
  planHypotheses,
  selectWinner,
  scoreHypothesis,
} from "../plugin/parallel/hypothesis-runner";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
  readFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const TEST_FLOW_ID = "APOLO-20260620-TEST";
const TEST_FLOW_PATH = mkdtempSync(join(tmpdir(), "apolo-test-"));

// Helper: repo root temporal para routing-rules.json
const TEST_REPO_ROOT = mkdtempSync(join(tmpdir(), "apolo-repo-"));

// Crear routing-rules.json temporal en TEST_REPO_ROOT
function setupTestRepo() {
  mkdirSync(join(TEST_REPO_ROOT, "plan", "active"), { recursive: true });
  writeFileSync(
    join(TEST_REPO_ROOT, "routing-rules.json"),
    JSON.stringify({
      $schema: "./schemas/json/routing-rules.json",
      version: "v2.0",
      rules: [
        {
          id: "R-001",
          priority: 10,
          when: {
            phase: "reanclaje",
            artifacts_absent: ["00-OBJETIVO.yaml"],
          },
          then: {
            next_agent: "planner",
            reason: "No hay objetivo. El planner debe producir 00-OBJETIVO.yaml.",
          },
        },
        {
          id: "R-002",
          priority: 20,
          when: {
            phase: "planning-bootstrap",
            artifacts_present: ["00-OBJETIVO.yaml"],
            artifacts_absent: ["01-ASR.yaml"],
          },
          then: {
            next_agent: "surface-scanner",
            reason: "Objetivo definido pero falta ASR.",
          },
        },
        {
          id: "R-008",
          priority: 40,
          when: { blocker_active: true },
          then: {
            next_agent: "blocked",
            reason: "Hay bloqueo activo.",
            circuit_breaker: true,
          },
        },
        {
          id: "R-010",
          priority: 5,
          when: { phase: "cierre-flow" },
          then: {
            next_agent: "closed",
            reason: "Flow cerrado.",
          },
        },
      ],
    })
  );

  // Crear opencode.json mínimo con MCPs para test del mcp-loader
  writeFileSync(
    join(TEST_REPO_ROOT, "opencode.json"),
    JSON.stringify({
      $schema: "https://opencode.ai/config.json",
      plugin: ["./plugin/index.ts"],
      mcp: {
        "@playwright/mcp": {
          type: "local",
          command: ["npx", "-y", "@playwright/mcp@latest"],
          enabled: true,
        },
        "opencode-fastedit": {
          type: "local",
          command: ["npx", "-y", "opencode-fastedit@latest"],
          enabled: false,
        },
      },
    })
  );
}

setupTestRepo();

// ============================================================================
// Tests: RuntimeLogger
// ============================================================================

describe("RuntimeLogger", () => {
  beforeEach(() => {
    _resetSeqCache();
  });

  it("debe escribir entradas al runtime-audit.log", () => {
    log(
      {
        flow_id: TEST_FLOW_ID,
        actor: "plugin:apolo-dynamic-flow",
        action: "session_start",
        outcome: "success",
      },
      TEST_FLOW_PATH
    );

    const logPath = resolveLogPath(TEST_FLOW_ID, TEST_FLOW_PATH);
    assert.ok(existsSync(logPath), "log file should exist");

    const content = readFileSync(logPath, "utf-8");
    const lines = content.trim().split("\n");
    assert.ok(lines.length > 0, "should have at least one entry");

    const entry = JSON.parse(lines[lines.length - 1]);
    assert.strictEqual(entry.actor, "plugin:apolo-dynamic-flow");
    assert.strictEqual(entry.action, "session_start");
    assert.strictEqual(entry.outcome, "success");
    assert.strictEqual(entry.flow_id, TEST_FLOW_ID);
    assert.ok(entry.ts, "should have ts");
    assert.ok(entry.seq > 0, "should have seq > 0");
  });

  it("debe incrementar seq monotónicamente", () => {
    log(
      {
        flow_id: TEST_FLOW_ID,
        actor: "plugin:apolo-dynamic-flow",
        action: "session_start",
        outcome: "success",
      },
      TEST_FLOW_PATH
    );
    log(
      {
        flow_id: TEST_FLOW_ID,
        actor: "plugin:apolo-dynamic-flow",
        action: "command_executed",
        outcome: "success",
      },
      TEST_FLOW_PATH
    );

    const entries = readRecentEntries(TEST_FLOW_ID, 2, TEST_FLOW_PATH);
    assert.strictEqual(entries.length, 2);
    assert.ok(entries[1].seq > entries[0].seq, "seq should be monotonic");
  });

  it("createFlowLogger debe prepopular flow_id", () => {
    const logger = createFlowLogger(TEST_FLOW_ID, TEST_FLOW_PATH);
    logger.log({
      actor: "agent:truth-auditor",
      action: "decision_made",
      outcome: "success",
      decision: {
        type: "next_agent",
        value: "microplanner",
        reasoning: "verdad confirmada, proceder a microplanning",
      },
    });

    const entries = readRecentEntries(TEST_FLOW_ID, 1, TEST_FLOW_PATH);
    assert.strictEqual(entries[0].flow_id, TEST_FLOW_ID);
    assert.strictEqual(entries[0].decision?.value, "microplanner");
  });

  it("debe rechazar entradas sin campos required (sin lanzar, es pasivo)", () => {
    log(
      {
        flow_id: TEST_FLOW_ID,
        actor: undefined as any,
        action: "session_start" as any,
        outcome: "success",
      },
      TEST_FLOW_PATH
    );
    assert.ok(true, "logger should not throw on invalid input");
  });
});

// ============================================================================
// Tests: DeclarativeRouter
// ============================================================================

describe("DeclarativeRouter", () => {
  beforeEach(() => {
    _resetRulesCache();
  });

  it("debe cargar routing-rules.json", () => {
    const rules = loadRoutingRules(TEST_REPO_ROOT);
    assert.ok(rules.rules.length > 0, "should have rules");
    assert.ok(rules.version, "should have version");
  });

  it("R-001: sin 00-OBJETIVO.yaml en reanclaje → planner", () => {
    const result = route(
      buildRoutingContext({
        flow_id: TEST_FLOW_ID,
        flow_path: TEST_FLOW_PATH,
        phase: "reanclaje",
        artifacts_present: [],
        mp_active: null,
        blocker_active: false,
        deep_evidence_required: false,
      }),
      TEST_REPO_ROOT
    );
    assert.strictEqual(result.next_agent, "planner");
    assert.strictEqual(result.rule_id, "R-001");
  });

  it("R-002: con 00-OBJETIVO pero sin 01-ASR → surface-scanner", () => {
    const result = route(
      buildRoutingContext({
        flow_id: TEST_FLOW_ID,
        flow_path: TEST_FLOW_PATH,
        phase: "planning-bootstrap",
        artifacts_present: ["00-OBJETIVO.yaml"],
        mp_active: null,
        blocker_active: false,
        deep_evidence_required: false,
      }),
      TEST_REPO_ROOT
    );
    assert.strictEqual(result.next_agent, "surface-scanner");
    assert.strictEqual(result.rule_id, "R-002");
  });

  it("R-008: con blocker_active → blocked + circuit_breaker", () => {
    const result = route(
      buildRoutingContext({
        flow_id: TEST_FLOW_ID,
        flow_path: TEST_FLOW_PATH,
        phase: "implementation",
        artifacts_present: [
          "00-OBJETIVO.yaml",
          "01-ASR.yaml",
          "02-VERDAD.yaml",
          "03-PLAN-INDICE-DYNAMIC.yaml",
        ],
        mp_active: "MP-01",
        blocker_active: true,
        deep_evidence_required: false,
      }),
      TEST_REPO_ROOT
    );
    assert.strictEqual(result.next_agent, "blocked");
    assert.strictEqual(result.circuit_breaker, true);
    assert.strictEqual(result.rule_id, "R-008");
  });

  it("R-010: phase cierre-flow → closed", () => {
    const result = route(
      buildRoutingContext({
        flow_id: TEST_FLOW_ID,
        flow_path: TEST_FLOW_PATH,
        phase: "cierre-flow",
        artifacts_present: [],
        mp_active: null,
        blocker_active: false,
        deep_evidence_required: false,
      }),
      TEST_REPO_ROOT
    );
    assert.strictEqual(result.next_agent, "closed");
    assert.strictEqual(result.rule_id, "R-010");
  });

  it("fallback: ninguna regla matchea → orchestrator", () => {
    const result = route(
      buildRoutingContext({
        flow_id: TEST_FLOW_ID,
        flow_path: TEST_FLOW_PATH,
        phase: "asr",
        artifacts_present: ["01-ASR.yaml"],
        mp_active: null,
        blocker_active: false,
        deep_evidence_required: false,
      }),
      TEST_REPO_ROOT
    );
    assert.strictEqual(result.next_agent, "orchestrator");
    assert.strictEqual(result.rule_id, "FALLBACK");
  });
});

// ============================================================================
// Tests: LoopEngineTree
// ============================================================================

describe("LoopEngineTree", () => {
  beforeEach(() => {
    _resetTreeCache();
  });

  it("createRootNode debe crear D-001 con 5 branches", () => {
    const node = createRootNode(TEST_FLOW_ID, TEST_FLOW_PATH, "reanclaje");
    assert.strictEqual(node.id, "D-001");
    assert.strictEqual(node.branches.length, 5);
    assert.strictEqual(node.state.iteration, 1);
    assert.strictEqual(node.parent_node, null);
  });

  it("advance con test_passes → advance_phase (terminal)", () => {
    createRootNode(TEST_FLOW_ID, TEST_FLOW_PATH, "reanclaje");
    const result = advance(TEST_FLOW_ID, TEST_FLOW_PATH, "D-001", "test_passes");
    assert.strictEqual(result.action, "advance_phase");
    assert.strictEqual(result.completed, true);
    assert.strictEqual(result.circuit_breaker, false);
  });

  it("advance con test_fails_retriable → retry_mp, next node", () => {
    createRootNode(TEST_FLOW_ID, TEST_FLOW_PATH, "reanclaje");
    const result = advance(TEST_FLOW_ID, TEST_FLOW_PATH, "D-001", "test_fails_retriable");
    assert.strictEqual(result.action, "retry_mp");
    assert.strictEqual(result.completed, false);
    assert.ok(result.node, "should have next node");
    assert.notStrictEqual(result.node?.id, "D-001");
  });

  it("advance con iteration_exceeded → circuit_break", () => {
    createRootNode(TEST_FLOW_ID, TEST_FLOW_PATH, "reanclaje");
    const result = advance(TEST_FLOW_ID, TEST_FLOW_PATH, "D-001", "iteration_exceeded");
    assert.strictEqual(result.action, "circuit_break");
    assert.strictEqual(result.circuit_breaker, true);
    assert.strictEqual(result.completed, true);
  });

  it("detectCircuitBreaker: 3 fallos misma razón → true", () => {
    const failures = [
      { mp_id: "MP-01", reason: "assertion failed" },
      { mp_id: "MP-01", reason: "assertion failed" },
      { mp_id: "MP-01", reason: "assertion failed" },
    ];
    assert.ok(detectCircuitBreaker(TEST_FLOW_ID, "MP-01", failures));
  });

  it("detectCircuitBreaker: 3 fallos razones distintas → false", () => {
    const failures = [
      { mp_id: "MP-01", reason: "assertion failed" },
      { mp_id: "MP-01", reason: "timeout" },
      { mp_id: "MP-01", reason: "compilation error" },
    ];
    assert.ok(!detectCircuitBreaker(TEST_FLOW_ID, "MP-01", failures));
  });
});

// ============================================================================
// Tests: MicroTest Runner
// ============================================================================

describe("MicroTestRunner", () => {
  it("extractTestCommand debe extraer comando camelCase", () => {
    const tmpMp = join(TEST_FLOW_PATH, "MP-TEST.yaml");
    writeFileSync(
      tmpMp,
      `id: MP-TEST
criteriodeadmision:
  testdeverdad:
    tipo: bash
    comando: "echo hello"
`
    );
    const cmd = extractTestCommand(tmpMp);
    assert.strictEqual(cmd, "echo hello");
  });

  it("extractTestCommand debe extraer comando snake_case", () => {
    const tmpMp = join(TEST_FLOW_PATH, "MP-TEST-SNAKE.yaml");
    writeFileSync(
      tmpMp,
      `id: MP-TEST
criterio_de_admision:
  test_de_verdad:
    tipo: bash
    comando: "echo world"
`
    );
    const cmd = extractTestCommand(tmpMp);
    assert.strictEqual(cmd, "echo world");
  });

  it("runTest debe ejecutar comando y retornar resultado exitoso", () => {
    const result = runTest(TEST_FLOW_ID, "MP-TEST", "echo hello");
    assert.strictEqual(result.passed, true);
    assert.strictEqual(result.exit_code, 0);
    assert.ok(result.stdout.includes("hello"));
    assert.ok(result.duration_ms >= 0);
  });

  it("runTest debe fallar graceful en comando inválido", () => {
    const result = runTest(TEST_FLOW_ID, "MP-TEST", "exit 1");
    assert.strictEqual(result.passed, false);
    assert.strictEqual(result.exit_code, 1);
  });
});

// ============================================================================
// Tests: McpAbsorber
// ============================================================================

describe("McpAbsorber", () => {
  beforeEach(() => {
    _resetMcpCache();
  });

  it("detectAvailableMcps debe retornar registry no vacío", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    assert.ok(registry.descriptors.length > 0);
    assert.ok(registry.loaded_at);
  });

  it("isMcpAvailable debe retornar false para MCP inexistente", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    assert.ok(!isMcpAvailable(registry, "mcp-inexistente-12345"));
  });

  it("isMcpAvailable debe retornar true para @playwright/mcp habilitado", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    assert.ok(isMcpAvailable(registry, "@playwright/mcp"));
  });

  it("isMcpAvailable debe retornar false para opencode-fastedit deshabilitado", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    assert.ok(!isMcpAvailable(registry, "opencode-fastedit"));
  });

  it("suggestMcpForTask debe sugerir playwright para tarea de captura", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    const suggestion = suggestMcpForTask(registry, "capturar pantalla del browser");
    assert.ok(suggestion, "should suggest a tool");
    assert.strictEqual(suggestion!.mcp, "@playwright/mcp");
  });

  it("invokeMcp debe ejecutar fallback si MCP no disponible", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    let fallbackCalled = false;
    const result = invokeMcp(
      TEST_FLOW_ID,
      registry,
      "mcp-inexistente",
      "tool",
      {},
      () => {
        fallbackCalled = true;
        return "fallback-result";
      }
    );
    assert.strictEqual(fallbackCalled, true);
    assert.strictEqual(result.success, true);
    assert.strictEqual(result.result, "fallback-result");
    assert.ok(result.fallback_used);
  });

  it("invokeMcp debe retornar error si MCP no disponible y sin fallback", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    const result = invokeMcp(
      TEST_FLOW_ID,
      registry,
      "mcp-inexistente",
      "tool",
      {}
    );
    assert.strictEqual(result.success, false);
    assert.ok(result.error);
  });
});

// ============================================================================
// Tests: ParallelHypothesisRunner
// ============================================================================

describe("ParallelHypothesisRunner", () => {
  it("planHypotheses debe crear N specs", () => {
    const specs = planHypotheses(
      TEST_FLOW_ID,
      { type: "next_agent", value: "truth-auditor" },
      3
    );
    assert.strictEqual(specs.length, 3);
    assert.ok(specs[0].hypothesis_id);
    assert.ok(specs[0].agent);
    assert.strictEqual(specs[0].agent, "truth-auditor");
  });

  it("selectWinner debe elegir el de mayor score", () => {
    const hypotheses = [
      {
        id: "H-1",
        agent: "truth-auditor" as const,
        inputs: {},
        status: "completed" as const,
        output: { result: "good" },
        evidence_refs: ["e1", "e2"],
        score: 10,
      },
      {
        id: "H-2",
        agent: "truth-auditor" as const,
        inputs: {},
        status: "completed" as const,
        output: { result: "better" },
        evidence_refs: ["e1", "e2", "e3", "e4"],
        score: 15,
      },
      {
        id: "H-3",
        agent: "truth-auditor" as const,
        inputs: {},
        status: "failed" as const,
        error: "timeout",
      },
    ];
    const result = selectWinner(TEST_FLOW_ID, hypotheses);
    assert.strictEqual(result.winner_id, "H-2");
    assert.strictEqual(result.completed, 2);
    assert.strictEqual(result.failed, 1);
  });

  it("selectWinner debe retornar null si ninguna completó", () => {
    const hypotheses = [
      {
        id: "H-1",
        agent: "truth-auditor" as const,
        inputs: {},
        status: "failed" as const,
        error: "error",
      },
    ];
    const result = selectWinner(TEST_FLOW_ID, hypotheses);
    assert.strictEqual(result.winner_id, null);
    assert.strictEqual(result.failed, 1);
  });

  it("scoreHypothesis debe dar score positivo a completed con evidence", () => {
    const h = {
      id: "H-1",
      agent: "truth-auditor" as const,
      inputs: {},
      status: "completed" as const,
      output: { x: 1 },
      evidence_refs: ["e1", "e2"],
    };
    const score = scoreHypothesis(h);
    assert.ok(score > 0);
  });

  it("scoreHypothesis debe dar score negativo a failed", () => {
    const h = {
      id: "H-1",
      agent: "truth-auditor" as const,
      inputs: {},
      status: "failed" as const,
      error: "timeout",
    };
    const score = scoreHypothesis(h);
    assert.ok(score < 0);
  });
});

// ============================================================================
// Limpieza
// ============================================================================

afterEach(() => {
  // No limpiar TEST_FLOW_PATH para inspección manual
});
