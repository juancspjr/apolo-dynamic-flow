#!/usr/bin/env python3
"""
onboarding.py — Onboarding guiado interactivo (v2.7.0).

Guía al usuario paso a paso en la configuración inicial del plugin:
  1. Verifica prerrequisitos
  2. Pregunta tipo de proyecto
  3. Sugiere MCPs y skills según tipo
  4. Configura opencode.json
  5. Crea flow de ejemplo
  6. Genera plantilla de proyecto si se solicita

Uso:
  python3 onboarding.py --repo-root .
  python3 onboarding.py --repo-root . --non-interactive  # modo automático
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, cmd_available


def check_prerequisites() -> Dict[str, bool]:
    """Verifica prerrequisitos del sistema."""
    return {
        "node": cmd_available("node"),
        "npm": cmd_available("npm"),
        "python3": cmd_available("python3"),
        "git": cmd_available("git"),
        "curl": cmd_available("curl"),
        "pyyaml": _try_import("yaml"),
        "jsonschema": _try_import("jsonschema"),
    }


def _try_import(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def suggest_mcps(project_type: str) -> List[Dict[str, str]]:
    """Sugiere MCPs según tipo de proyecto."""
    suggestions = {
        "web": [
            {"name": "@playwright/mcp", "reason": "Browser testing for web apps"},
            {"name": "@koderspa/mcp-skills", "reason": "Frontend skills"},
        ],
        "api": [
            {"name": "@playwright/mcp", "reason": "API endpoint testing"},
            {"name": "opencode-fastedit", "reason": "Fast file editing"},
        ],
        "mobile": [
            {"name": "@playwright/mcp", "reason": "Mobile browser testing"},
        ],
        "cli": [
            {"name": "opencode-fastedit", "reason": "Fast file editing for CLI"},
        ],
        "general": [
            {"name": "@playwright/mcp", "reason": "Browser automation"},
            {"name": "opencode-fastedit", "reason": "Fast file editing"},
        ],
    }
    return suggestions.get(project_type, suggestions["general"])


def suggest_skills(project_type: str) -> List[str]:
    """Sugiere skills según tipo de proyecto."""
    skills = {
        "web": ["frontend", "ui-testing", "css", "react"],
        "api": ["backend", "api-design", "database", "security"],
        "mobile": ["mobile", "react-native", "ios", "android"],
        "cli": ["cli", "testing", "documentation"],
        "general": ["general", "testing", "documentation"],
    }
    return skills.get(project_type, skills["general"])


def generate_opencode_json(project_type: str, mcps: List[Dict], repo_root: Path) -> Dict:
    """Genera opencode.json configurado."""
    config = {
        "$schema": "https://opencode.ai/config.json",
        "plugin": ["./plugin/index.ts"],
        "mcp": {},
    }

    for mcp in mcps:
        name = mcp["name"]
        config["mcp"][name] = {
            "type": "local",
            "command": ["npx", "-y", f"{name}@latest"],
            "enabled": True,
        }

    return config


def run_onboarding(repo_root: Path, non_interactive: bool = False) -> Dict:
    """Ejecuta el onboarding."""
    results = {
        "onboarding": "V1",
        "version": 1,
        "started_at": now_iso(),
        "repo_root": str(repo_root),
    }

    # Step 1: Check prerequisites
    results["prerequisites"] = check_prerequisites()

    # Step 2: Determine project type
    if non_interactive:
        project_type = "general"
    else:
        print("\n=== Apolo Dynamic Flow — Onboarding ===\n")
        print("Select project type:")
        print("  1. Web (Next.js, React, Vue)")
        print("  2. API (Go, Python, Java, Node)")
        print("  3. Mobile (React Native, Flutter)")
        print("  4. CLI (Python, Go, Rust)")
        print("  5. General")
        try:
            choice = input("\nChoice (1-5): ").strip()
            project_type = {"1": "web", "2": "api", "3": "mobile", "4": "cli", "5": "general"}.get(choice, "general")
        except (EOFError, KeyboardInterrupt):
            project_type = "general"

    results["project_type"] = project_type

    # Step 3: Suggest MCPs
    suggested_mcps = suggest_mcps(project_type)
    results["suggested_mcps"] = suggested_mcps

    # Step 4: Suggest skills
    suggested_skills = suggest_skills(project_type)
    results["suggested_skills"] = suggested_skills

    # Step 5: Generate opencode.json
    opencode_config = generate_opencode_json(project_type, suggested_mcps, repo_root)
    results["opencode_json"] = opencode_config

    # Write opencode.json if not exists
    opencode_path = repo_root / "opencode.json"
    if not opencode_path.exists():
        write_yaml(opencode_path, opencode_config)
        results["opencode_json_written"] = True
    else:
        results["opencode_json_written"] = False

    # Step 6: Create example flow
    flowid = f"APOLO-{now_iso()[:10].replace('-', '')}-ONBOARDING"
    flow_dir = repo_root / "plan" / "active" / flowid
    flow_dir.mkdir(parents=True, exist_ok=True)
    (flow_dir / "evidence").mkdir(exist_ok=True)
    (flow_dir / "tests").mkdir(exist_ok=True)
    (flow_dir / "telemetry.jsonl").touch()

    # Create FLOW-STATE.yaml
    template = read_yaml(repo_root / "templates" / "FLOW-STATE.template.yaml") or {}
    template["flowid"] = flowid
    template["created_at"] = now_iso()
    template["updated_at"] = now_iso()
    template["phase_entered_at"] = now_iso()
    write_yaml(flow_dir / "FLOW-STATE.yaml", template)
    results["example_flow"] = flowid

    results["completed_at"] = now_iso()
    results["success"] = True

    return results


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    non_interactive = args.get("non-interactive", "") == "true"

    result = run_onboarding(repo_root, non_interactive)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
