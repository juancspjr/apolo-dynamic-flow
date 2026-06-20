#!/usr/bin/env python3
"""
run_all_tests.py — Runner de toda la suite de tests del plugin.

Ejecuta:
  - test_state_machine.py
  - test_loop_engine.py
  - test_block_detector.py
  - test_tool_absorber.py
  - test_python_scripts.py
"""

import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent


def main():
    tests = [
        "test_state_machine.py",
        "test_loop_engine.py",
        "test_block_detector.py",
        "test_tool_absorber.py",
        "test_python_scripts.py",
    ]
    failures = []
    for t in tests:
        print(f"\n{'='*60}")
        print(f"  RUNNING: {t}")
        print(f"{'='*60}")
        result = subprocess.run(
            ["python3", str(TESTS_DIR / t)],
            cwd=str(TESTS_DIR),
        )
        if result.returncode != 0:
            failures.append(t)

    print(f"\n{'='*60}")
    if failures:
        print(f"  FAIL: {len(failures)} tests fallaron")
        for f in failures:
            print(f"    - {f}")
        return 1
    print(f"  ALL {len(tests)} TESTS PASSED ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
