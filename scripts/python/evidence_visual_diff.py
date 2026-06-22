#!/usr/bin/env python3
"""
evidence_visual_diff.py — Evidencia visual comparativa con diff (v3.1.0).

Cierra el GAP #4 del INTEGRATION-VERDICT.md:
  "Evidencia visual comparativa (baseline vs roto vs post-fix) con diff"

Captura snapshots de archivos en 3 momentos criticos:
  1. baseline: antes de implementar (fase reanclaje inicio)
  2. broken: despues de un test failure (cuando algo se rompe)
  3. post_fix: despues de la fix exitosa

Genera diffs unificados entre los 3 estados para que el agente pueda ver
exactamente que cambio, cuando se rompio, y como se arreglo.

CLI:
  # Capturar snapshot en un momento
  python3 evidence_visual_diff.py capture --flowid X --phase baseline --files file1.ts,file2.ts
  python3 evidence_visual_diff.py capture --flowid X --phase broken --files file1.ts
  python3 evidence_visual_diff.py capture --flowid X --phase post-fix --files file1.ts

  # Generar diff entre dos fases
  python3 evidence_visual_diff.py diff --flowid X --from baseline --to broken
  python3 evidence_visual_diff.py diff --flowid X --from baseline --to post-fix --format unified

  # Comparacion completa (3 estados)
  python3 evidence_visual_diff.py compare --flowid X --output VISUAL-DIFF-REPORT.yaml

  # Listar snapshots capturados
  python3 evidence_visual_diff.py list --flowid X
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir


VALID_PHASES = ["baseline", "broken", "post-fix", "intermediate"]


def snapshots_dir(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "visual-diff"


def capture_snapshot(
    repo_root: Path,
    flowid: str,
    phase: str,
    files: List[str],
    unit_id: str = "",
    note: str = "",
) -> Dict[str, Any]:
    """Captura snapshot de archivos en un momento dado."""
    if phase not in VALID_PHASES:
        return {"success": False, "error": f"phase invalida: {phase}. Validas: {VALID_PHASES}"}

    snap_dir = snapshots_dir(repo_root, flowid)
    snap_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    snapshot_id = f"snap-{phase}-{timestamp}"

    captured_files: List[Dict[str, Any]] = []
    for file_rel in files:
        file_path = repo_root / file_rel
        if not file_path.exists():
            captured_files.append({
                "path": file_rel,
                "exists": False,
                "hash": None,
                "size_bytes": 0,
                "lines": 0,
            })
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            captured_files.append({
                "path": file_rel,
                "exists": True,
                "hash": file_hash,
                "size_bytes": len(content.encode("utf-8")),
                "lines": len(lines),
                "content_preview": lines[:50],  # primer 50 lineas
            })
        except Exception as e:
            captured_files.append({
                "path": file_rel,
                "exists": True,
                "error": str(e),
            })

    snapshot = {
        "snapshot_id": snapshot_id,
        "flowid": flowid,
        "phase": phase,
        "unit_id": unit_id,
        "captured_at": now_iso(),
        "note": note,
        "files": captured_files,
        "summary": {
            "total_files": len(captured_files),
            "existing_files": sum(1 for f in captured_files if f.get("exists")),
            "total_lines": sum(f.get("lines", 0) for f in captured_files),
        },
    }

    output_path = snap_dir / f"{snapshot_id}.yaml"
    write_yaml(output_path, snapshot)
    log(f"Snapshot capturado: {snapshot_id} ({len(captured_files)} files, phase={phase})", "INFO")

    return {
        "success": True,
        "snapshot_id": snapshot_id,
        "phase": phase,
        "files_captured": len(captured_files),
        "output": str(output_path),
    }


def load_snapshot(repo_root: Path, flowid: str, phase: str, snapshot_id: str = "") -> Optional[Dict]:
    """Carga un snapshot por phase (el mas reciente) o por snapshot_id."""
    snap_dir = snapshots_dir(repo_root, flowid)
    if not snap_dir.exists():
        return None

    if snapshot_id:
        p = snap_dir / f"{snapshot_id}.yaml"
        if p.exists():
            return read_yaml(p)
        return None

    # Buscar el mas reciente de la phase
    candidates = sorted(snap_dir.glob(f"snap-{phase}-*.yaml"))
    if not candidates:
        return None
    return read_yaml(candidates[-1])


def generate_diff(
    snapshot_from: Dict,
    snapshot_to: Dict,
    format_type: str = "unified",
    max_lines: int = 200,
) -> Dict[str, Any]:
    """Genera diff entre dos snapshots."""
    files_from = {f["path"]: f for f in snapshot_from.get("files", [])}
    files_to = {f["path"]: f for f in snapshot_to.get("files", [])}

    all_paths = sorted(set(files_from.keys()) | set(files_to.keys()))
    diffs: List[Dict[str, Any]] = []
    total_added = 0
    total_removed = 0

    for path in all_paths:
        f_from = files_from.get(path, {})
        f_to = files_to.get(path, {})

        # Skip si ambos no existen
        if not f_from.get("exists") and not f_to.get("exists"):
            continue

        # Skip si mismo hash (sin cambios)
        if f_from.get("hash") == f_to.get("hash") and f_from.get("hash"):
            diffs.append({
                "path": path,
                "status": "unchanged",
                "hash_from": f_from.get("hash"),
                "hash_to": f_to.get("hash"),
            })
            continue

        # Generar diff
        content_from = "\n".join(f_from.get("content_preview", [])) if f_from.get("exists") else ""
        content_to = "\n".join(f_to.get("content_preview", [])) if f_to.get("exists") else ""

        if format_type == "unified":
            diff_lines = list(difflib.unified_diff(
                content_from.splitlines(keepends=True),
                content_to.splitlines(keepends=True),
                fromfile=f"{path} ({snapshot_from.get('phase', 'from')})",
                tofile=f"{path} ({snapshot_to.get('phase', 'to')})",
                n=3,
            ))
            diff_text = "".join(diff_lines)[:max_lines * 100]  # cap
        elif format_type == "json":
            diff_text = json.dumps({
                "from_hash": f_from.get("hash"),
                "to_hash": f_to.get("hash"),
                "from_lines": f_from.get("lines", 0),
                "to_lines": f_to.get("lines", 0),
            }, indent=2)
        else:
            diff_text = ""

        # Contar added/removed
        added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++")) if format_type == "unified" else 0
        removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---")) if format_type == "unified" else 0
        total_added += added
        total_removed += removed

        status = "modified"
        if not f_from.get("exists") and f_to.get("exists"):
            status = "created"
        elif f_from.get("exists") and not f_to.get("exists"):
            status = "deleted"

        diffs.append({
            "path": path,
            "status": status,
            "hash_from": f_from.get("hash"),
            "hash_to": f_to.get("hash"),
            "lines_from": f_from.get("lines", 0),
            "lines_to": f_to.get("lines", 0),
            "added_lines": added,
            "removed_lines": removed,
            "diff": diff_text,
        })

    return {
        "from_phase": snapshot_from.get("phase"),
        "to_phase": snapshot_to.get("phase"),
        "from_snapshot_id": snapshot_from.get("snapshot_id"),
        "to_snapshot_id": snapshot_to.get("snapshot_id"),
        "total_files_compared": len(all_paths),
        "total_files_changed": sum(1 for d in diffs if d["status"] != "unchanged"),
        "total_added_lines": total_added,
        "total_removed_lines": total_removed,
        "diffs": diffs,
    }


def compare_all_phases(repo_root: Path, flowid: str, format_type: str = "unified") -> Dict[str, Any]:
    """Compara baseline vs broken vs post-fix."""
    baseline = load_snapshot(repo_root, flowid, "baseline")
    broken = load_snapshot(repo_root, flowid, "broken")
    post_fix = load_snapshot(repo_root, flowid, "post-fix")

    report = {
        "visualdiffreport": "V1",
        "schema_version": "3.1.0",
        "flowid": flowid,
        "generated_at": now_iso(),
        "phases_available": {
            "baseline": baseline is not None,
            "broken": broken is not None,
            "post_fix": post_fix is not None,
        },
        "comparisons": {},
    }

    if baseline and broken:
        report["comparisons"]["baseline_to_broken"] = generate_diff(baseline, broken, format_type)
    if baseline and post_fix:
        report["comparisons"]["baseline_to_post_fix"] = generate_diff(baseline, post_fix, format_type)
    if broken and post_fix:
        report["comparisons"]["broken_to_post_fix"] = generate_diff(broken, post_fix, format_type)

    # Summary
    total_changes = sum(
        c.get("total_files_changed", 0)
        for c in report["comparisons"].values()
    )
    report["summary"] = {
        "total_comparisons": len(report["comparisons"]),
        "total_files_changed_across_comparisons": total_changes,
        "has_full_lifecycle": all([
            baseline is not None,
            broken is not None,
            post_fix is not None,
        ]),
    }

    return report


def list_snapshots(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Lista todos los snapshots capturados."""
    snap_dir = snapshots_dir(repo_root, flowid)
    if not snap_dir.exists():
        return {"success": True, "snapshots": [], "total": 0}

    snapshots = []
    for p in sorted(snap_dir.glob("snap-*.yaml")):
        data = read_yaml(p) or {}
        snapshots.append({
            "snapshot_id": data.get("snapshot_id"),
            "phase": data.get("phase"),
            "captured_at": data.get("captured_at"),
            "unit_id": data.get("unit_id", ""),
            "files_count": data.get("summary", {}).get("total_files", 0),
            "note": data.get("note", ""),
        })

    return {"success": True, "snapshots": snapshots, "total": len(snapshots)}


def main() -> int:
    argv = sys.argv[1:]
    action = "list"
    known = {"capture", "diff", "compare", "list"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if not flowid and action != "list":
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2))
        return 2

    if action == "capture":
        phase = args.get("phase", "")
        files_str = args.get("files", "")
        unit_id = args.get("unit-id", "")
        note = args.get("note", "")
        if not phase or not files_str:
            print(json.dumps({"success": False, "error": "Falta --phase y --files (comma-separated)"}, indent=2))
            return 2
        files = [f.strip() for f in files_str.split(",") if f.strip()]
        result = capture_snapshot(repo_root, flowid, phase, files, unit_id, note)
        print(json.dumps(result, indent=2))
        return 0 if result.get("success") else 1

    elif action == "diff":
        from_phase = args.get("from", "")
        to_phase = args.get("to", "")
        format_type = args.get("format", "unified")
        if not from_phase or not to_phase:
            print(json.dumps({"success": False, "error": "Falta --from y --to (phases)"}, indent=2))
            return 2
        snap_from = load_snapshot(repo_root, flowid, from_phase)
        snap_to = load_snapshot(repo_root, flowid, to_phase)
        if not snap_from:
            print(json.dumps({"success": False, "error": f"No hay snapshot para phase={from_phase}"}, indent=2))
            return 1
        if not snap_to:
            print(json.dumps({"success": False, "error": f"No hay snapshot para phase={to_phase}"}, indent=2))
            return 1
        result = generate_diff(snap_from, snap_to, format_type)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2, default=str))
        return 0

    elif action == "compare":
        format_type = args.get("format", "unified")
        report = compare_all_phases(repo_root, flowid, format_type)
        output = args.get("output")
        if output:
            write_yaml(Path(output), report)
            log(f"Reporte → {output}", "INFO")
        print(json.dumps({"success": True, **report}, ensure_ascii=False, indent=2, default=str))
        return 0

    elif action == "list":
        result = list_snapshots(repo_root, flowid) if flowid else {"success": True, "snapshots": [], "total": 0}
        print(json.dumps(result, indent=2))
        return 0

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
