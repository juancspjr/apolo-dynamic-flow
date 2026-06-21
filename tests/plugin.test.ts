/**
 * plugin.test.ts — Suite de tests TypeScript para apolo-dynamic-flow v2.1.0.
 *
 * Cubre los 6 módulos nuevos:
 *   - core/runtime-logger
 *   - core/router
 *   - core/loop-engine-tree
 *   - core/micro-test-runner
 *   - absorbers/mcp-loader
 *   - parallel/hypothesis-runner
 *
 * Total: 32 tests (4 + 6 + 6 + 4 + 7 + 5).
 *
 * Run: npx tsc && node --test dist/tests/plugin.test.js
 */

import { strict as assert } from "node:assert";
import { describe, it, beforeEach, afterEach, before, after } from "node:test";
import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import {
  log,
  readRecentEntries,
  createFlowLogger,
  resolveLogPath,
  _resetSeqCache,
} from "../plugin/core/runtime-logger";
import {
  _resetRulesCache,
  loadRoutingRules,
  route,
  buildRoutingContext,
} from "../plugin/core/router";
import {
  _resetTreeCache,
  createRootNode,
  getNode,
  advance,
  detectCircuitBreaker,
  exportTree,
} from "../plugin/core/loop-engine-tree";
import {
  extractTestCommand,
  runTest,
} from "../plugin/core/micro-test-runner";
import {
  _resetMcpCache,
  detectAvailableMcps,
  isMcpAvailable,
  suggestMcpForTask,
  invokeMcp,
} from "../plugin/absorbers/mcp-loader";
import {
  planHypotheses,
  scoreHypothesis,
  selectWinner,
} from "../plugin/parallel/hypothesis-runner";

// ============================================================================
// Setup
// ============================================================================

const TEST_FLOW_ID = "APOLO-20260620-TEST";
const TEST_FLOW_PATH = fs.mkdtempSync(path.join(os.tmpdir(), "apolo-test-"));
const TEST_REPO_ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "apolo-repo-"));

function setupTestRepo(): void {
  // routing-rules.json con las 10 reglas
  const routingRules = {
    $schema: "./schemas/json/routing-rules.json",
    version: "v2.0",
    rules: [
      {
        id: "R-010",
        priority: 5,
        when: { phase: "cierre-flow" },
        then: {
          next_agent: "closed",
          reason: "fase cierre-flow alcanzada — flow cerrado",
        },
      },
      {
        id: "R-001",
        priority: 10,
        when: {
          phase: "reanclaje",
          artifacts_absent: ["00-OBJETIVO.yaml"],
        },
        then: {
          next_agent: "planner",
          reason: "reanclaje sin 00-OBJETIVO — planner debe definir objetivo",
        },
      },
      {
        id: "R-009",
        priority: 15,
        when: {
          phase: "verdad",
          deep_evidence_required: true,
        },
        then: {
          next_agent: "evidence-acquisition",
          reason: "verdad con deep_evidence_required — disparar evidence-acquisition",
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
          reason: "objetivo definido sin ASR — surface-scanner debe mapear",
        },
      },
      {
        id: "R-003",
        priority: 20,
        when: {
          phase: "asr",
          artifacts_present: ["00-OBJETIVO.yaml", "01-ASR.yaml"],
          artifacts_absent: ["02-VERDAD.yaml"],
        },
        then: {
          next_agent: "truth-auditor",
          reason: "ASR presente sin VERDAD — truth-auditor debe auditar",
        },
      },
      {
        id: "R-004",
        priority: 20,
        when: {
          phase: "verdad",
          artifacts_present: ["02-VERDAD.yaml"],
          artifacts_absent: ["02.5-PLAN-SHAPING.yaml"],
        },
        then: {
          next_agent: "planner",
          reason: "verdad definida sin shaping — planner debe shapificar",
        },
      },
      {
        id: "R-005",
        priority: 20,
        when: {
          phase: "shaping",
          artifacts_present: ["02.5-PLAN-SHAPING.yaml"],
          artifacts_absent: ["03-PLAN-INDICE-DYNAMIC.yaml"],
        },
        then: {
          next_agent: "microplanner",
          reason: "shaping presente sin plan-indice — microplanner particiona",
        },
      },
      {
        id: "R-006",
        priority: 30,
        when: {
          phase: "implementation",
          mp_ready: true,
          blocker_active: false,
        },
        then: {
          next_agent: "implementer",
          reason: "implementation con MP listo y sin blocker — implementer muta",
        },
      },
      {
        id: "R-007",
        priority: 30,
        when: {
          phase: "critical-validation",
          mp_ready: true,
        },
        then: {
          next_agent: "mutation-guardian",
          reason: "critical-validation con MP listo — mutation-guardian valida",
        },
      },
      {
        id: "R-008",
        priority: 40,
        when: { blocker_active: true },
        then: {
          next_agent: "blocked",
          reason: "bloqueo activo — circuit breaker disparado, detener mutaciones",
          circuit_breaker: true,
        },
      },
    ],
  };
  fs.writeFileSync(
    path.join(TEST_REPO_ROOT, "routing-rules.json"),
    JSON.stringify(routingRules, null, 2),
    "utf8"
  );

  // opencode.json con @playwright/mcp enabled y opencode-fastedit DISABLED
  const opencode = {
    $schema: "https://opencode.ai/config.json",
    mcp: {
      "opencode-fastedit": {
        type: "local",
        command: ["npx", "-y", "opencode-fastedit"],
        enabled: false,
        description: "Edición rápida (deshabilitado en test)",
      },
      "@playwright/mcp": {
        type: "local",
        command: ["npx", "-y", "@playwright/mcp@latest"],
        enabled: true,
        description: "Captura visual + interacciones browser",
      },
      "@koderspa/mcp-skills": {
        type: "local",
        command: ["npx", "-y", "@koderspa/mcp-skills"],
        enabled: true,
        description: "Skills externas",
      },
    },
  };
  fs.writeFileSync(
    path.join(TEST_REPO_ROOT, "opencode.json"),
    JSON.stringify(opencode, null, 2),
    "utf8"
  );

  // schemas/json dir (referenciado en routing-rules.json)
  fs.mkdirSync(path.join(TEST_REPO_ROOT, "schemas", "json"), { recursive: true });
}

// Setup una vez al cargar el módulo
setupTestRepo();

// Limpieza del cache antes de cada bloque — los tests individuales pueden
// resetear también si lo necesitan.

// ============================================================================
// 1. RuntimeLogger (4 tests)
// ============================================================================

describe("RuntimeLogger", () => {
  beforeEach(() => {
    _resetSeqCache();
    // Limpiar log si existe
    const logPath = resolveLogPath(TEST_FLOW_ID, TEST_REPO_ROOT);
    if (fs.existsSync(logPath)) {
      fs.unlinkSync(logPath);
    }
  });

  it("debe escribir entradas al runtime-audit.log", () => {
    log(
      {
        flow_id: TEST_FLOW_ID,
        actor: "plugin:apolo-dynamic-flow",
        action: "session_start",
        outcome: "success",
      },
      TEST_REPO_ROOT
    );
    const logPath = resolveLogPath(TEST_FLOW_ID, TEST_REPO_ROOT);
    assert.ok(fs.existsSync(logPath), "el archivo runtime-audit.log debe existir");

    const content = fs.readFileSync(logPath, "utf8");
    const entry = JSON.parse(content.trim().split("\n")[0]);
    assert.ok(entry.actor, "entry.actor debe estar presente");
    assert.ok(entry.action, "entry.action debe estar presente");
    assert.ok(entry.outcome, "entry.outcome debe estar presente");
    assert.strictEqual(entry.flow_id, TEST_FLOW_ID);
    assert.ok(entry.ts, "entry.ts debe estar presente");
    assert.ok(entry.seq > 0, "entry.seq debe ser > 0");
  });

  it("debe incrementar seq monotónicamente", () => {
    log(
      {
        flow_id: TEST_FLOW_ID,
        actor: "plugin:apolo-dynamic-flow",
        action: "session_start",
        outcome: "success",
      },
      TEST_REPO_ROOT
    );
    log(
      {
        flow_id: TEST_FLOW_ID,
        actor: "plugin:apolo-dynamic-flow",
        action: "decision_made",
        outcome: "success",
      },
      TEST_REPO_ROOT
    );
    const entries = readRecentEntries(TEST_FLOW_ID, 10, TEST_REPO_ROOT);
    assert.strictEqual(entries.length, 2, "debe haber 2 entradas");
    assert.ok(entries[1].seq > entries[0].seq, "seq debe ser monotónico creciente");
  });

  it("createFlowLogger debe prepopular flow_id", () => {
    const logger = createFlowLogger(TEST_FLOW_ID, TEST_REPO_ROOT);
    logger.log({
      actor: "plugin:apolo-dynamic-flow",
      action: "decision_made",
      outcome: "success",
      decision: {
        type: "next_agent",
        value: "planner",
        reasoning: "razón de test suficientemente larga para pasar el contrato",
      },
    });
    const entries = readRecentEntries(TEST_FLOW_ID, 10, TEST_REPO_ROOT);
    assert.strictEqual(entries.length, 1);
    assert.strictEqual(entries[0].flow_id, TEST_FLOW_ID);
    assert.ok(entries[0].decision, "decision debe estar presente");
    assert.strictEqual(entries[0].decision!.value, "planner");
  });

  it("debe rechazar entradas sin campos required (sin lanzar, es pasivo)", () => {
    // Pasamos actor undefined — el logger debe console.error y NO lanzar
    let didThrow = false;
    try {
      log(
        {
          flow_id: TEST_FLOW_ID,
          actor: undefined as any,
          action: "session_start",
          outcome: "success",
        },
        TEST_REPO_ROOT
      );
    } catch {
      didThrow = true;
    }
    assert.strictEqual(didThrow, false, "no debe lanzar aunque la entrada sea inválida");
  });
});

// ============================================================================
// 2. DeclarativeRouter (6 tests)
// ============================================================================

describe("DeclarativeRouter", () => {
  beforeEach(() => {
    _resetRulesCache();
  });

  it("debe cargar routing-rules.json", () => {
    const rules = loadRoutingRules(TEST_REPO_ROOT);
    assert.ok(rules.rules.length > 0, "rules.rules.length > 0");
    assert.ok(rules.version, "rules.version debe existir");
  });

  it("R-001 sin 00-OBJETIVO en reanclaje → planner", () => {
    const ctx = buildRoutingContext({
      flow_id: TEST_FLOW_ID,
      phase: "reanclaje",
      artifacts_present: [],
      repoRoot: TEST_REPO_ROOT,
    });
    const result = route(ctx);
    assert.strictEqual(result.next_agent, "planner");
    assert.strictEqual(result.rule_id, "R-001");
  });

  it("R-002 con 00-OBJETIVO sin 01-ASR → surface-scanner", () => {
    const ctx = buildRoutingContext({
      flow_id: TEST_FLOW_ID,
      phase: "planning-bootstrap",
      artifacts_present: ["00-OBJETIVO.yaml"],
      repoRoot: TEST_REPO_ROOT,
    });
    const result = route(ctx);
    assert.strictEqual(result.next_agent, "surface-scanner");
    assert.strictEqual(result.rule_id, "R-002");
  });

  it("R-008 con blocker_active → blocked, circuit_breaker true", () => {
    const ctx = buildRoutingContext({
      flow_id: TEST_FLOW_ID,
      phase: "implementation",
      artifacts_present: [],
      blocker_active: true,
      repoRoot: TEST_REPO_ROOT,
    });
    const result = route(ctx);
    assert.strictEqual(result.next_agent, "blocked");
    assert.strictEqual(result.rule_id, "R-008");
    assert.strictEqual(result.circuit_breaker, true);
  });

  it("R-010 phase cierre-flow → closed", () => {
    const ctx = buildRoutingContext({
      flow_id: TEST_FLOW_ID,
      phase: "cierre-flow",
      artifacts_present: [],
      repoRoot: TEST_REPO_ROOT,
    });
    const result = route(ctx);
    assert.strictEqual(result.next_agent, "closed");
    assert.strictEqual(result.rule_id, "R-010");
  });

  it("fallback: ninguna matchea → orchestrator, rule_id FALLBACK", () => {
    // phase=mp-validation con mp_ready=false y blocker_active=false
    // → ninguna regla R-001..R-010 matchea
    const ctx = buildRoutingContext({
      flow_id: TEST_FLOW_ID,
      phase: "mp-validation",
      artifacts_present: [],
      blocker_active: false,
      mp_ready: false,
      repoRoot: TEST_REPO_ROOT,
    });
    const result = route(ctx);
    assert.strictEqual(result.next_agent, "orchestrator");
    assert.strictEqual(result.rule_id, "FALLBACK");
  });
});

// ============================================================================
// 3. LoopEngineTree (6 tests)
// ============================================================================

describe("LoopEngineTree", () => {
  beforeEach(() => {
    _resetTreeCache();
  });

  it("createRootNode D-001 con 5 branches, iteration 1, parent_node null", () => {
    const flowId = "APOLO-20260620-LOOP-1";
    const node = createRootNode(flowId, "implementation", {
      repoRoot: TEST_REPO_ROOT,
    });
    assert.strictEqual(node.id, "D-001");
    assert.strictEqual(node.branches.length, 5);
    assert.strictEqual(node.state.iteration, 1);
    assert.strictEqual(node.parent_node, null);
  });

  it("advance test_passes → advance_phase, completed true, circuit_breaker false", () => {
    const flowId = "APOLO-20260620-LOOP-2";
    const root = createRootNode(flowId, "implementation", {
      repoRoot: TEST_REPO_ROOT,
    });
    const result = advance(flowId, TEST_FLOW_PATH, root.id, "test_passes", {
      repoRoot: TEST_REPO_ROOT,
    });
    assert.strictEqual(result.action, "advance_phase");
    assert.strictEqual(result.completed, true);
    assert.strictEqual(result.circuit_breaker, false);
  });

  it("advance test_fails_retriable → retry_mp, completed false, node existe y != D-001", () => {
    const flowId = "APOLO-20260620-LOOP-3";
    const root = createRootNode(flowId, "implementation", {
      repoRoot: TEST_REPO_ROOT,
    });
    const result = advance(flowId, TEST_FLOW_PATH, root.id, "test_fails_retriable", {
      repoRoot: TEST_REPO_ROOT,
    });
    assert.strictEqual(result.action, "retry_mp");
    assert.strictEqual(result.completed, false);
    assert.ok(result.node, "debe crear un siguiente nodo");
    assert.notStrictEqual(result.node!.id, "D-001", "el siguiente nodo != D-001");
  });

  it("advance iteration_exceeded → circuit_break, circuit_breaker true, completed true", () => {
    const flowId = "APOLO-20260620-LOOP-4";
    const root = createRootNode(flowId, "implementation", {
      repoRoot: TEST_REPO_ROOT,
    });
    const result = advance(flowId, TEST_FLOW_PATH, root.id, "iteration_exceeded", {
      repoRoot: TEST_REPO_ROOT,
    });
    assert.strictEqual(result.action, "circuit_break");
    assert.strictEqual(result.circuit_breaker, true);
    assert.strictEqual(result.completed, true);
  });

  it("detectCircuitBreaker 3 fallos misma razón → true", () => {
    const flowId = "APOLO-20260620-LOOP-5";
    const failures = [
      { mp_id: "MP-01", reason: "timeout", at: "2026-06-20T10:00:00Z" },
      { mp_id: "MP-01", reason: "timeout", at: "2026-06-20T10:01:00Z" },
      { mp_id: "MP-01", reason: "timeout", at: "2026-06-20T10:02:00Z" },
    ];
    const result = detectCircuitBreaker(flowId, "MP-01", failures);
    assert.strictEqual(result, true);
  });

  it("detectCircuitBreaker 3 fallos razones distintas → false", () => {
    const flowId = "APOLO-20260620-LOOP-6";
    const failures = [
      { mp_id: "MP-01", reason: "timeout", at: "2026-06-20T10:00:00Z" },
      { mp_id: "MP-01", reason: "assertion_error", at: "2026-06-20T10:01:00Z" },
      { mp_id: "MP-01", reason: "syntax_error", at: "2026-06-20T10:02:00Z" },
    ];
    const result = detectCircuitBreaker(flowId, "MP-01", failures);
    assert.strictEqual(result, false);
  });
});

// ============================================================================
// 4. MicroTestRunner (4 tests)
// ============================================================================

describe("MicroTestRunner", () => {
  it("extractTestCommand camelCase 'echo hello'", () => {
    const tmp = path.join(TEST_REPO_ROOT, "mp-camelCase.yaml");
    fs.writeFileSync(
      tmp,
      [
        "mpid: MP-01",
        "criteriodeadmision:",
        "  testdeverdad:",
        "    comando: echo hello",
        "",
      ].join("\n"),
      "utf8"
    );
    const cmd = extractTestCommand(tmp);
    assert.strictEqual(cmd, "echo hello");
  });

  it("extractTestCommand snake_case 'echo world'", () => {
    const tmp = path.join(TEST_REPO_ROOT, "mp-snake.yaml");
    fs.writeFileSync(
      tmp,
      [
        "mpid: MP-02",
        "criterio_de_admision:",
        "  test_de_verdad:",
        "    comando: echo world",
        "",
      ].join("\n"),
      "utf8"
    );
    const cmd = extractTestCommand(tmp);
    assert.strictEqual(cmd, "echo world");
  });

  it("runTest 'echo hello' passed true, exit_code 0, stdout incluye 'hello'", () => {
    const flowId = "APOLO-20260620-MTR-1";
    const result = runTest(flowId, "MP-TEST-1", "echo hello", TEST_REPO_ROOT);
    assert.strictEqual(result.passed, true);
    assert.strictEqual(result.exit_code, 0);
    assert.ok(result.stdout.includes("hello"), "stdout debe incluir 'hello'");
  });

  it("runTest 'exit 1' passed false, exit_code 1", () => {
    const flowId = "APOLO-20260620-MTR-2";
    const result = runTest(flowId, "MP-TEST-2", "exit 1", TEST_REPO_ROOT);
    assert.strictEqual(result.passed, false);
    assert.strictEqual(result.exit_code, 1);
  });
});

// ============================================================================
// 5. McpAbsorber (7 tests)
// ============================================================================

describe("McpAbsorber", () => {
  beforeEach(() => {
    _resetMcpCache();
  });

  it("detectAvailableMcps descriptors.length > 0", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    assert.ok(registry.descriptors.length > 0, "debe haber al menos 1 descriptor");
  });

  it("isMcpAvailable 'mcp-inexistente-12345' → false", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    assert.strictEqual(isMcpAvailable(registry, "mcp-inexistente-12345"), false);
  });

  it("isMcpAvailable '@playwright/mcp' → true", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    assert.strictEqual(isMcpAvailable(registry, "@playwright/mcp"), true);
  });

  it("isMcpAvailable 'opencode-fastedit' → false (deshabilitado)", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    assert.strictEqual(isMcpAvailable(registry, "opencode-fastedit"), false);
  });

  it("suggestMcpForTask 'capturar pantalla del browser' → mcp=@playwright/mcp", () => {
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    const suggestion = suggestMcpForTask(registry, "capturar pantalla del browser");
    assert.ok(suggestion, "debe sugerir un MCP");
    assert.strictEqual(suggestion!.mcp, "@playwright/mcp");
  });

  it("invokeMcp con mcp-inexistente y fallback → fallback ejecutado, success true, fallback_used true", () => {
    const flowId = "APOLO-20260620-MCP-1";
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    let fallbackCalled = false;
    const result = invokeMcp(
      flowId,
      registry,
      "mcp-inexistente-12345",
      "some_tool",
      { x: 1 },
      () => {
        fallbackCalled = true;
        return { ok: true, via: "fallback" };
      },
      TEST_REPO_ROOT
    );
    assert.strictEqual(fallbackCalled, true, "el fallback debe ejecutarse");
    assert.strictEqual(result.success, true);
    assert.strictEqual(result.fallback_used, true);
  });

  it("invokeMcp sin fallback → success false, error existe", () => {
    const flowId = "APOLO-20260620-MCP-2";
    const registry = detectAvailableMcps(TEST_REPO_ROOT);
    const result = invokeMcp(
      flowId,
      registry,
      "mcp-inexistente-12345",
      "some_tool",
      { x: 1 },
      undefined,
      TEST_REPO_ROOT
    );
    assert.strictEqual(result.success, false);
    assert.ok(result.error, "debe tener un error message");
  });
});

// ============================================================================
// 6. ParallelHypothesisRunner (5 tests)
// ============================================================================

describe("ParallelHypothesisRunner", () => {
  it("planHypotheses 3 → length 3, agent truth-auditor", () => {
    const flowId = "APOLO-20260620-HYP-1";
    const result = planHypotheses(flowId, { objective: "test objetivo" }, 3);
    assert.strictEqual(result.length, 3);
    for (const h of result) {
      assert.strictEqual(h.agent, "truth-auditor");
    }
    assert.strictEqual(result[0].hypothesis_id, "H-1");
    assert.strictEqual(result[2].hypothesis_id, "H-3");
  });

  it("selectWinner con 3 hipótesis (H-1 score 10, H-2 score 15 completed, H-3 failed) → winner_id H-2, completed 2, failed 1", () => {
    const flowId = "APOLO-20260620-HYP-2";
    // H-1: completed, sin evidence_refs ni output → score 10
    // H-2: completed, con 2 evidence_refs y 1 output key → score 10 + 4 + 1 = 15
    // H-3: failed → score -20
    const hypotheses = [
      {
        hypothesis_id: "H-1",
        flow_id: flowId,
        agent: "truth-auditor",
        status: "completed" as const,
        objective: "test objetivo",
      },
      {
        hypothesis_id: "H-2",
        flow_id: flowId,
        agent: "truth-auditor",
        status: "completed" as const,
        objective: "test objetivo",
        evidence_refs: ["E-001", "E-002"],
        output: { key1: "value1" },
      },
      {
        hypothesis_id: "H-3",
        flow_id: flowId,
        agent: "truth-auditor",
        status: "failed" as const,
        objective: "test objetivo",
      },
    ];
    const result = selectWinner(flowId, hypotheses);
    assert.strictEqual(result.winner_id, "H-2");
    assert.strictEqual(result.completed, 2);
    assert.strictEqual(result.failed, 1);
  });

  it("selectWinner todas failed → winner_id null, failed 1", () => {
    const flowId = "APOLO-20260620-HYP-3";
    const hypotheses = [
      {
        hypothesis_id: "H-1",
        flow_id: flowId,
        agent: "truth-auditor",
        status: "failed" as const,
        objective: "test objetivo",
      },
    ];
    const result = selectWinner(flowId, hypotheses);
    assert.strictEqual(result.winner_id, null);
    assert.strictEqual(result.failed, 1);
  });

  it("scoreHypothesis completed con evidence_refs → score > 0", () => {
    const h = {
      hypothesis_id: "H-1",
      flow_id: "APOLO-20260620-HYP-4",
      agent: "truth-auditor",
      status: "completed" as const,
      objective: "test objetivo",
      evidence_refs: ["E-001", "E-002"],
    };
    const score = scoreHypothesis(h);
    assert.ok(score > 0, `score debe ser > 0, fue ${score}`);
  });

  it("scoreHypothesis failed → score < 0", () => {
    const h = {
      hypothesis_id: "H-1",
      flow_id: "APOLO-20260620-HYP-5",
      agent: "truth-auditor",
      status: "failed" as const,
      objective: "test objetivo",
    };
    const score = scoreHypothesis(h);
    assert.ok(score < 0, `score debe ser < 0, fue ${score}`);
  });
});

// ============================================================================
// 7. ContextQueryTools v2.2.0 (3 tests)
// ============================================================================
//
// Estos tests invocan los 3 scripts Python nuevos (context_query.py,
// registry_recommend.py, health_check.py) directamente via spawnSync,
// emulando el comportamiento de los 3 tools nuevas expuestas en index.ts:
//   - apolo.context.query
//   - apolo.registry.recommend
//   - apolo.health.check
//
// Para que funcionen, requieren:
//   - El project root como repo-root (process.cwd() al ejecutar node --test)
//   - Un TOOL-REGISTRY.yaml válido (presente en .opencode/apolo-dynamic/)
//   - Para context_query: un FLOW-STATE.yaml mínimo (se crea en before())
// ============================================================================

describe("ContextQueryTools", () => {
  // El project root es el cwd al ejecutar `node --test dist/tests/plugin.test.js`
  // desde el directorio del plugin (lo hace install.sh y npm test).
  const PROJECT_ROOT = process.cwd();
  const SCRIPTS_DIR = path.join(PROJECT_ROOT, "scripts", "python");

  // Flowid dedicado para test 1 (no choca con datos preexistentes)
  const V22_TEST_FLOWID = "APOLO-20260620-V22-CTXTEST";
  const V22_TEST_FLOW_DIR = path.join(
    PROJECT_ROOT,
    "plan",
    "active",
    V22_TEST_FLOWID
  );

  before(() => {
    // Crear FLOW-STATE.yaml mínimo para que handler_next_phase devuelva
    // current_phase="verdad" y next_phase="shaping".
    fs.mkdirSync(V22_TEST_FLOW_DIR, { recursive: true });
    const flowStateYaml = [
      "flowstate: V2",
      `flowid: ${V22_TEST_FLOWID}`,
      "version: 1",
      "schema_version: V2",
      'created_at: "2026-06-21T00:00:00Z"',
      'updated_at: "2026-06-21T00:00:00Z"',
      "phase: verdad",
      'phase_entered_at: "2026-06-21T00:00:00Z"',
      "history: []",
      "loops:",
      "  reanclaje:",
      "    current: 0",
      "    max: 2",
      '    last_decision: ""',
      "  verdad:",
      "    current: 0",
      "    max: 2",
      '    last_decision: ""',
      "circuit_breaker:",
      "  policy: fail-closed",
      "  escalation_path: []",
      "artifacts:",
      '  objetivo: ""',
      '  asr: ""',
      '  verdad: ""',
      '  shaping: ""',
      '  plan_indice: ""',
      "  current_mps: []",
      '  evidence_pack: ""',
      "  test_runs: []",
      '  blocks_log: ""',
      "tools_absorbed: []",
      "tokens_consumed_total: 0",
      "operator_hints: []",
      "",
    ].join("\n");
    fs.writeFileSync(
      path.join(V22_TEST_FLOW_DIR, "FLOW-STATE.yaml"),
      flowStateYaml,
      "utf8"
    );
  });

  after(() => {
    // Limpiar el flow de test
    try {
      fs.rmSync(V22_TEST_FLOW_DIR, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  });

  // --------------------------------------------------------------------------
  // Test 1: apolo.context.query responde "qué fase sigue"
  // --------------------------------------------------------------------------

  it("apolo.context.query responde 'qué fase sigue' con {current_phase, next_phase}", () => {
    const scriptPath = path.join(SCRIPTS_DIR, "context_query.py");
    assert.ok(
      fs.existsSync(scriptPath),
      `context_query.py debe existir en ${scriptPath}`
    );

    const result = spawnSync(
      "python3",
      [
        scriptPath,
        "--flowid",
        V22_TEST_FLOWID,
        "--repo-root",
        PROJECT_ROOT,
        "--phase",
        "",
        "--question",
        "qué fase sigue",
      ],
      { encoding: "utf8", timeout: 30000 }
    );

    assert.strictEqual(
      result.status,
      0,
      `context_query.py debe terminar exit_code=0 (got ${result.status}) stderr=${result.stderr?.slice(0, 300)}`
    );

    const response = JSON.parse(result.stdout);
    assert.ok(
      response.current_phase !== undefined,
      "response debe tener current_phase"
    );
    assert.ok(
      response.next_phase !== undefined,
      "response debe tener next_phase"
    );
    // Con el FLOW-STATE.yaml que setupeamos (phase=verdad), next_phase debe ser "shaping"
    assert.strictEqual(response.current_phase, "verdad");
    assert.strictEqual(response.next_phase, "shaping");
    assert.ok(response._meta, "response debe tener _meta");
    assert.strictEqual(response._meta.handler, "next_phase");
  });

  // --------------------------------------------------------------------------
  // Test 2: apolo.registry.recommend recomienda run_tests para tarea de testing
  // --------------------------------------------------------------------------

  it("apolo.registry.recommend recomienda run_tests para tarea de testing", () => {
    const scriptPath = path.join(SCRIPTS_DIR, "registry_recommend.py");
    assert.ok(
      fs.existsSync(scriptPath),
      `registry_recommend.py debe existir en ${scriptPath}`
    );

    const result = spawnSync(
      "python3",
      [
        scriptPath,
        "--task",
        "correr tests de la unidad U-01",
        "--repo-root",
        PROJECT_ROOT,
        "--top",
        "3",
      ],
      { encoding: "utf8", timeout: 10000 }
    );

    assert.strictEqual(
      result.status,
      0,
      `registry_recommend.py debe terminar exit_code=0 (got ${result.status}) stderr=${result.stderr?.slice(0, 300)}`
    );

    const response = JSON.parse(result.stdout);
    assert.ok(
      Array.isArray(response.top_recommendations),
      "top_recommendations debe ser un array"
    );
    assert.ok(
      response.top_recommendations.length > 0,
      "debe haber al menos 1 recomendación"
    );
    assert.strictEqual(
      response.top_recommendations[0].tool_name,
      "run_tests",
      `esperaba run_tests como top recommendation, got ${response.top_recommendations[0].tool_name}`
    );
    // Sanity: la tool matcheó capability 'test' o 'run'
    assert.ok(
      response.top_recommendations[0].score > 0,
      "el score de run_tests debe ser > 0"
    );
  });

  // --------------------------------------------------------------------------
  // Test 3: apolo.health.check retorna summary con total_tools > 0
  // --------------------------------------------------------------------------

  it("apolo.health.check retorna summary con total_tools > 0", () => {
    const scriptPath = path.join(SCRIPTS_DIR, "health_check.py");
    assert.ok(
      fs.existsSync(scriptPath),
      `health_check.py debe existir en ${scriptPath}`
    );

    const result = spawnSync(
      "python3",
      [
        scriptPath,
        "--repo-root",
        PROJECT_ROOT,
        "--fix",
        "false",
        "--json",
        "true",
      ],
      { encoding: "utf8", timeout: 30000 }
    );

    // health_check.py returns exit 1 if there are unhealthy tools, but JSON is valid.
    // Aceptamos status 0 o 1 (no >1 que sería error real).
    assert.ok(
      result.status === 0 || result.status === 1,
      `health_check.py status debe ser 0 o 1 (got ${result.status}) stderr=${result.stderr?.slice(0, 300)}`
    );

    const response = JSON.parse(result.stdout);
    assert.ok(response.summary, "response debe tener summary");
    assert.ok(
      typeof response.summary.total_tools === "number",
      "summary.total_tools debe ser un número"
    );
    assert.ok(
      response.summary.total_tools > 0,
      `summary.total_tools debe ser > 0 (got ${response.summary.total_tools})`
    );
    // Sanity: healthy + unhealthy == total
    assert.strictEqual(
      response.summary.healthy + response.summary.unhealthy,
      response.summary.total_tools,
      "healthy + unhealthy debe sumar total_tools"
    );
  });
});
