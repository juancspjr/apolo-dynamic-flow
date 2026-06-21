#!/usr/bin/env python3
"""
github_actions.py — Generador de GitHub Actions workflows (v2.7.0).

Genera workflows de CI/CD para:
  - Test en cada PR (Python + TypeScript)
  - Lint + type check
  - Build
  - Security scan
  - Release

Uso:
  python3 github_actions.py --repo-root . --output .github/workflows/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args


CI_WORKFLOW = '''name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test-python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install PyYAML jsonschema pytest
      - run: python3 tests/run_all_tests.py
      - run: python3 tests/test_atomic.py
      - run: python3 tests/test_security.py
      - run: python3 tests/test_quality.py
      - run: python3 tests/test_intelligence.py

  test-typescript:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: npm install
      - run: npx tsc --noEmit
      - run: node --test dist/tests/plugin.test.js

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install bandit radon
      - run: bandit -r scripts/ -f json -o bandit-report.json || true
      - run: radon cc scripts/ -s || true
'''

SECURITY_WORKFLOW = '''name: Security

on:
  push:
    branches: [main]
  schedule:
    - cron: "0 0 * * 0"

jobs:
  security-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install bandit safety
      - run: bandit -r scripts/ -f json -o bandit-report.json || true
      - run: safety check --json || true
      - uses: actions/upload-artifact@v4
        with:
          name: security-reports
          path: "*.json"
'''

RELEASE_WORKFLOW = '''name: Release

on:
  push:
    tags:
      - "v*"

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: npm install
      - run: npx tsc
      - name: Create Release
        uses: softprops/action-gh-release@v1
        with:
          generate_release_notes: true
'''


def generate_workflows(output_dir: Path) -> Dict:
    """Genera todos los workflows."""
    output_dir.mkdir(parents=True, exist_ok=True)

    workflows = {
        "ci.yml": CI_WORKFLOW,
        "security.yml": SECURITY_WORKFLOW,
        "release.yml": RELEASE_WORKFLOW,
    }

    files_created = 0
    for name, content in workflows.items():
        (output_dir / name).write_text(content, encoding="utf-8")
        files_created += 1

    return {
        "success": True,
        "workflows_created": files_created,
        "output": str(output_dir),
        "workflows": list(workflows.keys()),
    }


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    output = Path(args.get("output", str(repo_root / ".github" / "workflows")))

    result = generate_workflows(output)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
