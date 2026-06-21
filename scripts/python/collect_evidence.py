#!/usr/bin/env python3
"""
collect_evidence.py — Recolector determinista de evidencia.

NO piensa. Solo recopila data del repo, git, archivos, símbolos, endpoints,
DB queries, screenshots (si playwright disponible) y produce EVIDENCE-PACK.yaml
conforme al schema.

Uso:
  python3 collect_evidence.py \
    --flowid APOLO-20260620-MI-FLOW \
    --repo-root /path/to/repo \
    --output /path/to/EVIDENCE-PACK.yaml \
    --invoked-by orchestrator \
    --scope-json '{"paths":["src/foo.go"],"endpoints":["/api/v1/foo"],"git_diff":true}'
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Asegurar que podemos importar common.py
sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    cmd_available,
    detect_capabilities,
    elapsed_ms,
    extract_symbols,
    gen_evidence_id,
    gen_uuid,
    git_diff,
    git_log,
    git_status,
    hash_chain,
    hash_file,
    list_files,
    log,
    now_iso,
    parse_args,
    read_file_summary,
    run_cmd,
    sha256,
    write_yaml,
)

# v2.4.0: Security — secret detection and redaction
try:
    from secret_scanner import scan_evidence_pack
except ImportError:
    def scan_evidence_pack(pack, patterns=None):
        return pack, []  # stub: no redaction if secret_scanner unavailable


# ============================================================================
# Collectors
# ============================================================================

def collect_file_snapshot(repo_root: Path, file_path: str, idx: int) -> Dict[str, Any]:
    full = repo_root / file_path if not os.path.isabs(file_path) else Path(file_path)
    if not full.exists():
        return {
            "id": gen_evidence_id(idx),
            "kind": "file-snapshot",
            "source": file_path,
            "hash": "",
            "size_bytes": 0,
            "captured_at": now_iso(),
            "summary": f"ARCHIVO NO ENCONTRADO: {file_path}",
            "raw_path": "",
            "tags": ["missing"],
            "related_symbols": [],
        }
    h = hash_file(full) or ""
    summary = read_file_summary(full)
    symbols = extract_symbols(full)
    return {
        "id": gen_evidence_id(idx),
        "kind": "file-snapshot",
        "source": file_path,
        "hash": h,
        "size_bytes": full.stat().st_size,
        "captured_at": now_iso(),
        "summary": summary,
        "raw_path": "",
        "tags": [full.suffix.lstrip("."), "snapshot"],
        "related_symbols": symbols[:20],
    }


def collect_git_diff(repo_root: Path, ref: str, idx: int) -> Dict[str, Any]:
    diff = git_diff(repo_root, ref) or ""
    return {
        "id": gen_evidence_id(idx),
        "kind": "git-diff",
        "source": f"git diff {ref}",
        "hash": sha256(diff),
        "size_bytes": len(diff.encode("utf-8")),
        "captured_at": now_iso(),
        "summary": f"diff contra {ref}: {len(diff.splitlines())} líneas",
        "raw_path": "",
        "tags": ["git", "diff"],
        "related_symbols": [],
    }


def collect_git_log(repo_root: Path, n: int, idx: int) -> Dict[str, Any]:
    log_text = git_log(repo_root, n) or ""
    return {
        "id": gen_evidence_id(idx),
        "kind": "git-log",
        "source": f"git log -{n}",
        "hash": sha256(log_text),
        "size_bytes": len(log_text.encode("utf-8")),
        "captured_at": now_iso(),
        "summary": f"últimos {n} commits",
        "raw_path": "",
        "tags": ["git", "log"],
        "related_symbols": [],
    }


def collect_endpoint_probe(
    endpoint: str, idx: int, method: str = "GET"
) -> Dict[str, Any]:
    if not cmd_available("curl"):
        return {
            "id": gen_evidence_id(idx),
            "kind": "endpoint-probe",
            "source": f"{method} {endpoint}",
            "hash": "",
            "size_bytes": 0,
            "captured_at": now_iso(),
            "summary": "curl no disponible — no se pudo probe endpoint",
            "raw_path": "",
            "tags": ["endpoint", "skipped"],
            "related_symbols": [],
        }
    code, out, err = run_cmd(
        ["curl", "-sS", "-X", method, "-w", "\\n%{http_code}", endpoint],
        timeout=15,
    )
    full = out + err
    http_code = ""
    if "\n" in out:
        http_code = out.rsplit("\n", 1)[-1]
    return {
        "id": gen_evidence_id(idx),
        "kind": "endpoint-probe",
        "source": f"{method} {endpoint}",
        "hash": sha256(full),
        "size_bytes": len(full.encode("utf-8")),
        "captured_at": now_iso(),
        "summary": f"HTTP {http_code} (curl exit={code})",
        "raw_path": "",
        "tags": ["endpoint", method.lower()],
        "related_symbols": [],
    }


def collect_db_query(query: str, idx: int, db_url: str | None = None) -> Dict[str, Any]:
    if not cmd_available("psql"):
        return {
            "id": gen_evidence_id(idx),
            "kind": "db-query",
            "source": f"psql: {query[:60]}...",
            "hash": "",
            "size_bytes": 0,
            "captured_at": now_iso(),
            "summary": "psql no disponible — no se pudo ejecutar query",
            "raw_path": "",
            "tags": ["db", "skipped"],
            "related_symbols": [],
        }
    args = ["psql", "-A", "-t", "-F", "|", "-c", query]
    if db_url:
        args.extend(["-d", db_url])
    code, out, err = run_cmd(args, timeout=15)
    full = out + err
    return {
        "id": gen_evidence_id(idx),
        "kind": "db-query",
        "source": f"psql: {query[:80]}",
        "hash": sha256(full),
        "size_bytes": len(full.encode("utf-8")),
        "captured_at": now_iso(),
        "summary": f"psql exit={code}, {len(out.splitlines())} filas",
        "raw_path": "",
        "tags": ["db", "query"],
        "related_symbols": [],
    }


def collect_screenshot(url: str, idx: int, repo_root: Path) -> Dict[str, Any]:
    # Intentar playwright vía npx
    if not cmd_available("npx"):
        return {
            "id": gen_evidence_id(idx),
            "kind": "screenshot",
            "source": url,
            "hash": "",
            "size_bytes": 0,
            "captured_at": now_iso(),
            "summary": "npx/playwright no disponible — no se pudo capturar screenshot",
            "raw_path": "",
            "tags": ["screenshot", "skipped"],
            "related_symbols": [],
        }
    shot_path = repo_root / ".opencode" / "apolo-dynamic" / "screenshots" / f"{gen_uuid()}.png"
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    code, out, err = run_cmd(
        [
            "npx",
            "-y",
            "playwright",
            "screenshot",
            "--wait-for-timeout",
            "1000",
            url,
            str(shot_path),
        ],
        timeout=60,
    )
    if code != 0 or not shot_path.exists():
        return {
            "id": gen_evidence_id(idx),
            "kind": "screenshot",
            "source": url,
            "hash": "",
            "size_bytes": 0,
            "captured_at": now_iso(),
            "summary": f"playwright falló: {err[:200]}",
            "raw_path": "",
            "tags": ["screenshot", "failed"],
            "related_symbols": [],
        }
    h = hash_file(shot_path) or ""
    return {
        "id": gen_evidence_id(idx),
        "kind": "screenshot",
        "source": url,
        "hash": h,
        "size_bytes": shot_path.stat().st_size,
        "captured_at": now_iso(),
        "summary": f"screenshot {shot_path.name}",
        "raw_path": str(shot_path.relative_to(repo_root)),
        "tags": ["screenshot", "ui"],
        "related_symbols": [],
    }


def collect_symbol_list(
    repo_root: Path, file_pattern: str, idx: int
) -> Dict[str, Any]:
    files = list_files(repo_root, [file_pattern])
    all_symbols: List[str] = []
    for f in files[:50]:
        all_symbols.extend(extract_symbols(f))
    text = "\n".join(all_symbols)
    return {
        "id": gen_evidence_id(idx),
        "kind": "symbol-list",
        "source": f"glob:{file_pattern}",
        "hash": sha256(text),
        "size_bytes": len(text.encode("utf-8")),
        "captured_at": now_iso(),
        "summary": f"{len(all_symbols)} símbolos en {len(files)} archivos ({file_pattern})",
        "raw_path": "",
        "tags": ["symbols"],
        "related_symbols": all_symbols[:50],
    }


def collect_schema_validation(
    artifact_path: Path, schema_path: Path, idx: int
) -> Dict[str, Any]:
    """Valida un YAML contra un schema YAML mínimo (required fields)."""
    if not artifact_path.exists():
        return {
            "id": gen_evidence_id(idx),
            "kind": "schema-validation",
            "source": str(artifact_path),
            "hash": "",
            "size_bytes": 0,
            "captured_at": now_iso(),
            "summary": f"artifact no existe: {artifact_path}",
            "raw_path": "",
            "tags": ["schema", "missing"],
            "related_symbols": [],
        }
    if not schema_path.exists():
        return {
            "id": gen_evidence_id(idx),
            "kind": "schema-validation",
            "source": str(artifact_path),
            "hash": "",
            "size_bytes": 0,
            "captured_at": now_iso(),
            "summary": f"schema no existe: {schema_path}",
            "raw_path": "",
            "tags": ["schema", "missing-schema"],
            "related_symbols": [],
        }
    # Importar common.yaml_load
    from common import read_yaml, validate_required
    artifact = read_yaml(artifact_path) or {}
    schema = read_yaml(schema_path) or {}
    required = schema.get("required", []) if isinstance(schema, dict) else []
    errors = validate_required(artifact, required, str(artifact_path.name))
    text = "\n".join(errors) if errors else "OK"
    return {
        "id": gen_evidence_id(idx),
        "kind": "schema-validation",
        "source": str(artifact_path),
        "hash": sha256(text),
        "size_bytes": len(text.encode("utf-8")),
        "captured_at": now_iso(),
        "summary": f"validación: {len(errors)} errores" if errors else "validación OK",
        "raw_path": "",
        "tags": ["schema", "validation"],
        "related_symbols": [],
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    flowid = args.get("flowid", "")
    repo_root = Path(args.get("repo-root", ".")).resolve()
    output = Path(args.get("output", "EVIDENCE-PACK.yaml"))
    invoked_by = args.get("invoked-by", "orchestrator")
    scope_json = args.get("scope-json", "{}")

    if not flowid:
        log("--flowid requerido", "ERROR")
        return 2

    try:
        scope = json.loads(scope_json)
    except Exception as e:
        log(f"--scope-json inválido: {e}", "ERROR")
        return 2

    start_iso = now_iso()
    start_time = time.time()
    log(f"recolectando evidencia para flow {flowid}", "INFO")

    items: List[Dict[str, Any]] = []
    idx = 1
    degradations: List[Dict[str, Any]] = []

    # 1. File snapshots
    for fp in scope.get("paths", []):
        items.append(collect_file_snapshot(repo_root, fp, idx)); idx += 1

    # 2. Symbol lists (si hay patterns)
    for pattern in scope.get("symbol_patterns", []):
        items.append(collect_symbol_list(repo_root, pattern, idx)); idx += 1

    # 3. Git diff
    if scope.get("git_diff"):
        items.append(collect_git_diff(repo_root, "HEAD", idx)); idx += 1

    # 4. Git log
    if scope.get("git_log"):
        items.append(collect_git_log(repo_root, 20, idx)); idx += 1

    # 5. Endpoints
    for ep in scope.get("endpoints", []):
        items.append(collect_endpoint_probe(ep, idx)); idx += 1

    # 6. DB queries
    db_url = scope.get("db_url") or os.environ.get("DATABASE_URL")
    for q in scope.get("db_queries", []):
        items.append(collect_db_query(q, idx, db_url)); idx += 1

    # 7. Screenshots
    for url in scope.get("screenshots", []):
        items.append(collect_screenshot(url, idx, repo_root)); idx += 1

    # 8. Schema validations
    for sv in scope.get("schema_validations", []):
        items.append(
            collect_schema_validation(
                repo_root / sv["artifact"],
                repo_root / sv["schema"],
                idx,
            )
        ); idx += 1

    # Capabilities
    caps = detect_capabilities()
    # Registrar degradaciones
    if caps["playwright"] == "unavailable":
        degradations.append({
            "tool": "playwright",
            "reason": "no instalado",
            "fallback_used": "curl + DOM inspection",
            "at": now_iso(),
        })

    duration_ms = int((time.time() - start_time) * 1000)
    script_path = Path(__file__)
    script_hash = hash_file(script_path) or ""
    env_fp = sha256(json.dumps(caps, sort_keys=True))

    pack = {
        "evidencepack": "V2",
        "version": 1,
        "flowid": flowid,
        "created_at": start_iso,
        "collector": {
            "script": str(script_path.relative_to(repo_root)) if script_path.is_relative_to(repo_root) else str(script_path),
            "script_hash": script_hash,
            "env_fingerprint": env_fp,
            "duration_ms": duration_ms,
            "invoked_by": invoked_by,
        },
        "items": items,
        "hash_chain": hash_chain(items),
        "capabilities": caps,
        "degradation_log": degradations,
    }

    # v2.2.1: MERGE con evidencia del agente (modo híbrido)
    agent_evidence_json = args.get("agent-evidence", "")
    agent_summary = args.get("agent-summary", "")
    agent_tags = args.get("agent-tags", "")
    script_count = len(items)
    if agent_evidence_json:
        try:
            import json as _json
            agent_items = _json.loads(agent_evidence_json)
            if isinstance(agent_items, list):
                base_idx = 100
                for i, item in enumerate(agent_items):
                    if not isinstance(item, dict):
                        continue
                    agent_item = {
                        "id": f"E-{base_idx + i + 1:03d}",
                        "kind": item.get("kind", "agent-observation"),
                        "source": item.get("source", "agent"),
                        "hash": item.get("hash", sha256(_json.dumps(item, sort_keys=True))),
                        "size_bytes": item.get("size_bytes", 0),
                        "captured_at": now_iso(),
                        "summary": item.get("summary", "(agente sin summary)"),
                        "raw_path": item.get("raw_path", ""),
                        "tags": item.get("tags", []) + ["agent-contributed"],
                        "related_symbols": item.get("related_symbols", []),
                        "agent_observed": True,
                    }
                    if "agent_reasoning" in item:
                        agent_item["agent_reasoning"] = item["agent_reasoning"]
                    items.append(agent_item)
                pack["items"] = items
                pack["agent_contributed_count"] = len(agent_items)
                if agent_summary:
                    pack["agent_summary"] = agent_summary
                log(f"Agente aporto {len(agent_items)} items de evidencia", "INFO")
        except Exception as e:
            log(f"Error mergeando agent evidence: {e}", "WARN")

    write_yaml(output, pack)
    log(f"evidence pack escrito: {output} ({len(items)} items, {duration_ms}ms)", "INFO")

    # Stdout para el caller (TS)
    print(json.dumps({
        "success": True,
        "items": len(items),
        "hash_chain": pack["hash_chain"],
        "capabilities": caps,
        "duration_ms": duration_ms,
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
