#!/usr/bin/env python3
"""
feedback_loop.py — Loop de feedback con el usuario (v2.8.1).

Cierra el GAP #10: "Feedback loop con el usuario (apolo-feedback)".

Permite al usuario registrar feedback cualitativo en cualquier punto del flow:
  - Por flow completo ("el flow X fue útil")
  - Por fase ("la fase reanclaje tomó demasiado")
  - Por símbolo/artefacto ("el scaffold de U-03 fue incorrecto")
  - Por sugerencia del sistema ("la recomendación de self_healing no aplicaba")

El feedback se almacena en .opencode/apolo-dynamic/FEEDBACK.jsonl (append-only,
un JSON por línea) y se agrega al contexto de self_healing.py para que el
sistema aprenda de preferencias del usuario.

CLI:
  # Registrar feedback
  python3 feedback_loop.py add \\
      --flowid APOLO-001 \\
      --phase reanclaje \\
      --rating 4 \\
      --comment "El scaffold fue bueno pero faltó incluir tests" \\
      --tags scaffold,tests

  # Listar feedback de un flow
  python3 feedback_loop.py list --flowid APOLO-001

  # Agregar para self-healing (resume por categoría)
  python3 feedback_loop.py aggregate --repo-root .

  # Buscar feedback por tag
  python3 feedback_loop.py search --tag scaffold
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir


FEEDBACK_FILE = "FEEDBACK.jsonl"


def feedback_path(repo_root: Path) -> Path:
    return repo_root / ".opencode" / "apolo-dynamic" / FEEDBACK_FILE


def add_feedback(
    repo_root: Path,
    flowid: str = "",
    phase: str = "",
    symbol: str = "",
    unit_id: str = "",
    rating: int = 0,
    comment: str = "",
    tags: str = "",
    category: str = "general",
) -> Dict[str, Any]:
    """Agrega una entrada de feedback al log append-only."""
    entry = {
        "feedback_id": f"FB-{uuid.uuid4().hex[:8]}",
        "at": now_iso(),
        "flowid": flowid,
        "phase": phase,
        "symbol": symbol,
        "unit_id": unit_id,
        "rating": max(0, min(5, rating)),  # 0-5
        "comment": comment,
        "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
        "category": category,
    }

    fpath = feedback_path(repo_root)
    fpath.parent.mkdir(parents=True, exist_ok=True)

    with open(fpath, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    log(f"Feedback registrado: {entry['feedback_id']} rating={rating}", "INFO")
    return entry


def list_feedback(repo_root: Path, flowid: str = "") -> List[Dict[str, Any]]:
    """Lista feedback, opcionalmente filtrado por flowid."""
    fpath = feedback_path(repo_root)
    if not fpath.exists():
        return []

    results = []
    for line in fpath.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if flowid and entry.get("flowid") != flowid:
                continue
            results.append(entry)
        except json.JSONDecodeError:
            continue
    return results


def search_feedback(repo_root: Path, tag: str = "", text: str = "") -> List[Dict[str, Any]]:
    """Busca feedback por tag o texto en comment."""
    fpath = feedback_path(repo_root)
    if not fpath.exists():
        return []

    results = []
    for line in fpath.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if tag:
                if tag not in entry.get("tags", []):
                    continue
            if text:
                if text.lower() not in entry.get("comment", "").lower():
                    continue
            results.append(entry)
        except json.JSONDecodeError:
            continue
    return results


def aggregate_feedback(repo_root: Path) -> Dict[str, Any]:
    """Agrega feedback para consumo de self_healing.py.

    Retorna un resumen con:
      - total_entries
      - avg_rating
      - rating_by_phase: {phase: avg_rating}
      - rating_by_category: {category: avg_rating}
      - common_tags: top 10 tags
      - low_rated_areas: fases/categorías con avg < 3
      - suggestions_for_self_healing: reglas derivadas
    """
    all_fb = list_feedback(repo_root)
    if not all_fb:
        return {
            "success": True,
            "total_entries": 0,
            "message": "No hay feedback registrado",
        }

    total = len(all_fb)
    ratings = [f.get("rating", 0) for f in all_fb]
    avg = sum(ratings) / total if total else 0

    by_phase: Dict[str, List[int]] = {}
    by_category: Dict[str, List[int]] = {}
    tag_counter: Dict[str, int] = {}

    for f in all_fb:
        phase = f.get("phase") or "unspecified"
        by_phase.setdefault(phase, []).append(f.get("rating", 0))
        cat = f.get("category") or "general"
        by_category.setdefault(cat, []).append(f.get("rating", 0))
        for t in f.get("tags", []):
            tag_counter[t] = tag_counter.get(t, 0) + 1

    avg_phase = {p: round(sum(v) / len(v), 2) for p, v in by_phase.items()}
    avg_cat = {c: round(sum(v) / len(v), 2) for c, v in by_category.items()}
    common_tags = sorted(tag_counter.items(), key=lambda x: -x[1])[:10]

    low_phases = [p for p, v in avg_phase.items() if v < 3.0]
    low_cats = [c for c, v in avg_cat.items() if v < 3.0]

    suggestions = []
    for p in low_phases:
        suggestions.append({
            "rule": f"Avoid automatic routing to phase '{p}' — user reports low satisfaction",
            "source": "feedback",
            "evidence": f"avg rating {avg_phase[p]}",
        })
    for c in low_cats:
        suggestions.append({
            "rule": f"Review category '{c}' workflow — user reports issues",
            "source": "feedback",
            "evidence": f"avg rating {avg_cat[c]}",
        })

    return {
        "success": True,
        "total_entries": total,
        "avg_rating": round(avg, 2),
        "rating_by_phase": avg_phase,
        "rating_by_category": avg_cat,
        "common_tags": [{"tag": t, "count": c} for t, c in common_tags],
        "low_rated_phases": low_phases,
        "low_rated_categories": low_cats,
        "suggestions_for_self_healing": suggestions,
        "generated_at": now_iso(),
    }


def _extract_action(argv: List[str]) -> tuple:
    """Extrae un subcomando posicional (si existe) y devuelve (action, argv_sin_action)."""
    if not argv:
        return "add", argv
    if not argv[0].startswith("--") and argv[0] not in ("--help", "-h"):
        # Solo tratar como subcomando si es una palabra conocida
        known = {"add", "list", "search", "aggregate"}
        if argv[0] in known:
            return argv[0], argv[1:]
    return "add", argv


def main() -> int:
    action, remaining = _extract_action(sys.argv[1:])
    args = parse_args(remaining)
    # --action override
    if "action" in args:
        action = args["action"]
    elif "mode" in args:
        action = args["mode"]
    repo_root = Path(args.get("repo-root", ".")).resolve()

    if action == "add":
        entry = add_feedback(
            repo_root=repo_root,
            flowid=args.get("flowid", ""),
            phase=args.get("phase", ""),
            symbol=args.get("symbol", ""),
            unit_id=args.get("unit-id", ""),
            rating=int(args.get("rating", "0") or 0),
            comment=args.get("comment", ""),
            tags=args.get("tags", ""),
            category=args.get("category", "general"),
        )
        print(json.dumps({"success": True, "feedback_id": entry["feedback_id"], "entry": entry}, ensure_ascii=False, indent=2))
        return 0

    elif action == "list":
        flowid = args.get("flowid", "")
        results = list_feedback(repo_root, flowid)
        print(json.dumps({"success": True, "count": len(results), "feedback": results}, ensure_ascii=False, indent=2))
        return 0

    elif action == "search":
        tag = args.get("tag", "")
        text = args.get("text", "") or args.get("q", "")
        results = search_feedback(repo_root, tag, text)
        print(json.dumps({"success": True, "count": len(results), "results": results}, ensure_ascii=False, indent=2))
        return 0

    elif action == "aggregate":
        summary = aggregate_feedback(repo_root)
        output = args.get("output")
        if output:
            write_yaml(Path(output), summary)
            log(f"Feedback agregado → {output}", "INFO")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
