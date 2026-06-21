/**
 * runtime-logger.ts — Logger JSON Lines con seq monotónico.
 *
 * Cada entrada se escribe a `plan/active/<flowid>/runtime-audit.log` en formato
 * JSON Lines (una entrada por línea). El seq es monotónico dentro del flow.
 *
 * CONTRATO: el logger es PASIVO. NUNCA lanza. Si una entrada es inválida,
 * la escribe a stderr pero no rompe el flujo.
 *
 * Conforme al schema: schemas/json/runtime-audit-log.json
 */

import * as crypto from "crypto";
import * as fs from "fs";
import * as path from "path";

// ============================================================================
// Types
// ============================================================================

export type AuditActor =
  | "plugin:apolo-dynamic-flow"
  | "agent:orchestrator"
  | "agent:planner"
  | "agent:surface-scanner"
  | "agent:truth-auditor"
  | "agent:microplanner"
  | "agent:implementer"
  | "agent:mutation-guardian"
  | "agent:evidence-acquisition"
  | "command:apolo-inspect"
  | "command:apolo-init-flow"
  | "command:apolo-absorb"
  | "command:apolo-serve-panel"
  | "operator"
  | "system";

export type AuditAction =
  | "session_start"
  | "session_end"
  | "command_executed"
  | "agent_invoked"
  | "artifact_read"
  | "artifact_written"
  | "artifact_validated"
  | "test_executed"
  | "test_passed"
  | "test_failed"
  | "decision_made"
  | "blocker_raised"
  | "blocker_resolved"
  | "phase_transition"
  | "mp_admitted"
  | "mp_rejected"
  | "flow_created"
  | "flow_closed"
  | "mcp_invoked"
  | "mcp_fallback"
  | "parallel_hypothesis_started"
  | "parallel_hypothesis_winner"
  | "script_generated"
  | "script_executed"
  | "circuit_breaker_triggered"
  | "warning"
  | "error";

export type AuditOutcome = "success" | "failure" | "warning" | "blocked" | "skipped";

export interface AuditEntry {
  ts: string;
  seq: number;
  flow_id: string;
  prev_hash?: string;  // v2.4.0: hash de la entrada anterior (hash chain)
  entry_hash?: string; // v2.4.0: hash de esta entrada (para verificación)
  actor: AuditActor;
  action: AuditAction;
  outcome: AuditOutcome;
  decision?: {
    type: "next_agent" | "admission" | "block" | "route" | "complete";
    value: string;
    reasoning: string;
    evidence_refs?: string[];
    rule_id?: string;
  };
  target?: string | null;
  duration_ms?: number;
  evidence?: { produced?: string[]; consumed?: string[] };
  context?: Record<string, unknown>;
}

export type PartialAuditEntry = Omit<AuditEntry, "ts" | "seq">;

// ============================================================================
// Seq cache (per flow_id)
// ============================================================================

const seqCache = new Map<string, number>();
const hashCache = new Map<string, string>();  // v2.4.0: último hash por flow_id

const GENESIS_SEED = "APOLO-DYNAMIC-FLOW-GENESIS-V1";

export function _resetSeqCache(): void {
  seqCache.clear();
  hashCache.clear();
}

function computeEntryHash(entry: Partial<AuditEntry>, prevHash: string): string {
  /** v2.4.0: Computa hash SHA256 de la entrada incluyendo el hash anterior. */
  const entryCopy = { ...entry };
  delete (entryCopy as any).entry_hash;
  delete (entryCopy as any).prev_hash;
  const entryStr = JSON.stringify(entryCopy, Object.keys(entryCopy).sort());
  const combined = prevHash + ":" + entryStr;
  return crypto.createHash("sha256").update(combined).digest("hex");
}

function getPrevHash(flowId: string): string {
  const cached = hashCache.get(flowId);
  if (cached) return cached;
  // Genesis hash
  return crypto.createHash("sha256").update(GENESIS_SEED).digest("hex");
}

function nextSeq(flowId: string): number {
  const current = seqCache.get(flowId) ?? 0;
  const next = current + 1;
  seqCache.set(flowId, next);
  return next;
}

// ============================================================================
// Path helpers
// ============================================================================

export function resolveLogPath(flowId: string, repoRoot: string = process.cwd()): string {
  return path.join(repoRoot, "plan", "active", flowId, "runtime-audit.log");
}

function ensureLogDir(logPath: string): void {
  const dir = path.dirname(logPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

// ============================================================================
// Public API
// ============================================================================

export function log(entry: PartialAuditEntry, repoRoot: string = process.cwd()): void {
  try {
    if (!entry.flow_id || !entry.actor || !entry.action || !entry.outcome) {
      console.error(`[runtime-logger] entrada inválida (faltan campos required):`, entry);
      return;
    }
    const logPath = resolveLogPath(entry.flow_id, repoRoot);
    ensureLogDir(logPath);
    const prevHash = getPrevHash(entry.flow_id);
    const fullEntry: AuditEntry = {
      ts: new Date().toISOString(),
      seq: nextSeq(entry.flow_id),
      ...entry,
      prev_hash: prevHash,
    };
    // v2.4.0: Computar hash de esta entrada
    fullEntry.entry_hash = computeEntryHash(fullEntry, prevHash);
    // Actualizar cache de hash
    hashCache.set(entry.flow_id, fullEntry.entry_hash);

    fs.appendFileSync(logPath, JSON.stringify(fullEntry) + "\n", "utf8");
  } catch (err) {
    console.error(`[runtime-logger] error escribiendo entrada:`, err);
  }
}

export function readRecentEntries(
  flowId: string,
  count: number = 10,
  repoRoot: string = process.cwd()
): AuditEntry[] {
  const logPath = resolveLogPath(flowId, repoRoot);
  if (!fs.existsSync(logPath)) return [];
  try {
    const content = fs.readFileSync(logPath, "utf8");
    const lines = content.trim().split("\n").filter(Boolean);
    const entries: AuditEntry[] = [];
    for (const line of lines) {
      try {
        entries.push(JSON.parse(line) as AuditEntry);
      } catch {
        // skip malformed
      }
    }
    return entries.slice(-count);
  } catch {
    return [];
  }
}

export function readAllEntries(flowId: string, repoRoot: string = process.cwd()): AuditEntry[] {
  return readRecentEntries(flowId, Number.MAX_SAFE_INTEGER, repoRoot);
}

export function createFlowLogger(flowId: string, repoRoot: string = process.cwd()): {
  log: (entry: Omit<PartialAuditEntry, "flow_id">) => void;
} {
  return {
    log: (entry) => log({ ...entry, flow_id: flowId } as PartialAuditEntry, repoRoot),
  };
}
