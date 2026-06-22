#!/usr/bin/env python3
"""
static_analyzer.py — Análisis estatico de dependencias entre scripts (v3.5.0).

RESPONDE a tu pregunta: "debe haber recursos estaticos o a traves de script
que ayudan a acomodar este tipo de integraciones buscando las mejores formas
evitando daños colaterales"

Analiza estaticamente (sin ejecutar) todos los scripts Python del plugin y
construye un grafo de dependencias:
  - Que scripts importa cada script
  - Que scripts invoca cada script (via subprocess/run_cmd)
  - Que artefactos YAML produce cada script
  - Que artefactos YAML consume cada script
  - Deteccion de dependencias circulares
  - Deteccion de scripts aislados (no conectados al grafo)

CLI:
  python3 static_analyzer.py analyze --repo-root .
  python3 static_analyzer.py graph --repo-root .
  python3 static_analyzer.py circular --repo-root .
  python3 static_analyzer.py isolated --repo-root .
"""

from __future__ import annotations
import ast
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml


def analyze_script(script_path: Path, repo_root: Path) -> Dict[str, Any]:
    """Analiza un script Python estaticamente."""
    try:
        content = script_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content)
    except Exception as e:
        return {"script": script_path.name, "error": str(e), "imports": [], "invokes": [], "produces": [], "consumes": []}

    imports: List[str] = []
    invokes: List[str] = []
    produces: List[str] = []
    consumes: List[str] = []

    # 1. Imports (from X import Y)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

    # 2. Invocaciones (subprocess, run_cmd, run_script)
    # Buscar strings que parecen nombres de scripts .py
    script_refs = re.findall(r'["\']([a-z_]+\.py)["\']', content)
    invokes.extend(script_refs)

    # 3. Artefactos producidos (write_yaml, --output)
    output_patterns = re.findall(r'["\']([A-Z][A-Z0-9_-]+\.yaml)["\']', content)
    produces.extend(output_patterns)

    # 4. Artefactos consumidos (read_yaml, --evidence, --plan, etc.)
    input_patterns = re.findall(r'--(?:evidence|plan|code-index|impact-prediction|verdad|output)\s+["\']?([A-Z][A-Z0-9_-]+\.yaml)', content)
    consumes.extend(input_patterns)

    return {
        "script": script_path.name,
        "imports": list(set(imports)),
        "invokes": list(set(invokes)),
        "produces": list(set(produces)),
        "consumes": list(set(consumes)),
        "lines": len(content.splitlines()),
        "has_main": any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in ast.walk(tree)),
    }


def build_dependency_graph(repo_root: Path) -> Dict[str, Any]:
    """Construye el grafo de dependencias entre scripts."""
    scripts_dir = repo_root / "scripts" / "python"
    if not scripts_dir.exists():
        return {"success": False, "error": "scripts/python/ no existe"}

    scripts: Dict[str, Dict] = {}
    for script_path in scripts_dir.glob("*.py"):
        if script_path.name == "__init__.py":
            continue
        analysis = analyze_script(script_path, repo_root)
        scripts[script_path.name] = analysis

    # Construir grafo: A → B si A invoca B
    graph: Dict[str, List[str]] = defaultdict(list)
    for script_name, analysis in scripts.items():
        for invoked in analysis.get("invokes", []):
            if invoked in scripts and invoked != script_name:
                graph[script_name].append(invoked)

    # Detectar dependencias circulares
    circular = detect_circular_deps(graph)

    # Detectar scripts aislados (no invocados por nadie, no invocan a nadie)
    all_invoked = set()
    for deps in graph.values():
        all_invoked.update(deps)
    isolated = [s for s in scripts if s not in all_invoked and not graph.get(s)]

    return {
        "success": True,
        "total_scripts": len(scripts),
        "scripts": scripts,
        "dependency_graph": dict(graph),
        "circular_dependencies": circular,
        "isolated_scripts": isolated,
        "graph_stats": {
            "total_edges": sum(len(deps) for deps in graph.values()),
            "total_nodes": len(scripts),
            "avg_dependencies": round(sum(len(deps) for deps in graph.values()) / max(len(scripts), 1), 2),
        },
    }


def detect_circular_deps(graph: Dict[str, List[str]]) -> List[List[str]]:
    """Detecta dependencias circulares usando DFS."""
    visited: Set[str] = set()
    rec_stack: Set[str] = set()
    cycles: List[List[str]] = []

    def dfs(node: str, path: List[str]) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, path)
            elif neighbor in rec_stack:
                # Encontro ciclo
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)

        path.pop()
        rec_stack.discard(node)

    for node in graph:
        if node not in visited:
            dfs(node, [])

    return cycles


def analyze_all(repo_root: Path) -> Dict[str, Any]:
    """Ejecuta analisis estatico completo."""
    log("=" * 60, "INFO")
    log("STATIC ANALYZER v3.5.0 — Analisis de dependencias", "INFO")
    log("=" * 60, "INFO")

    graph_result = build_dependency_graph(repo_root)

    if not graph_result["success"]:
        return graph_result

    log(f"\n  Scripts analizados: {graph_result['total_scripts']}", "INFO")
    log(f"  Edges en grafo: {graph_result['graph_stats']['total_edges']}", "INFO")
    log(f"  Dependencias circulares: {len(graph_result['circular_dependencies'])}", "INFO")
    log(f"  Scripts aislados: {len(graph_result['isolated_scripts'])}", "INFO")

    if graph_result["circular_dependencies"]:
        log("\n  ⚠ DEPENDENCIAS CIRCULARES DETECTADAS:", "WARN")
        for cycle in graph_result["circular_dependencies"]:
            log(f"    → {' → '.join(cycle)}", "WARN")

    if graph_result["isolated_scripts"]:
        log("\n  ⚠ SCRIPTS AISLADOS (no conectados al grafo):", "WARN")
        for s in graph_result["isolated_scripts"]:
            log(f"    → {s}", "WARN")

    report = {
        "staticanalyzer": "V1",
        "schema_version": "3.5.0",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        **graph_result,
        "overall_healthy": len(graph_result["circular_dependencies"]) == 0,
        "verdict": (
            "HEALTHY — no hay dependencias circulares"
            if len(graph_result["circular_dependencies"]) == 0
            else f"UNHEALTHY — {len(graph_result['circular_dependencies'])} dependencias circulares"
        ),
    }

    report_path = repo_root / "STATIC-ANALYSIS-REPORT.yaml"
    write_yaml(report_path, report)
    return report


def main() -> int:
    argv = sys.argv[1:]
    action = "analyze"
    known = {"analyze", "graph", "circular", "isolated"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()

    if action == "analyze":
        r = analyze_all(repo_root)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0 if r.get("overall_healthy", False) else 1
    elif action == "graph":
        r = build_dependency_graph(repo_root)
        print(json.dumps({"success": True, "graph": r.get("dependency_graph", {}), "stats": r.get("graph_stats", {})}, indent=2))
        return 0
    elif action == "circular":
        r = build_dependency_graph(repo_root)
        print(json.dumps({"success": True, "circular": r.get("circular_dependencies", [])}, indent=2))
        return 0
    elif action == "isolated":
        r = build_dependency_graph(repo_root)
        print(json.dumps({"success": True, "isolated": r.get("isolated_scripts", [])}, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
