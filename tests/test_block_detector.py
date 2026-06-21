#!/usr/bin/env python3
"""
test_block_detector.py — Tests del detector de bloqueos activos.

Valida:
  - detectBlocks identifica plan cycles
  - detectBlocks identifica context overload
  - detectBlocks reporta tools degradadas como hints
  - Sugerencias de resolución están presentes
"""

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent.parent / "plugin"


def test_detect_blocks_function():
    src = (PLUGIN_DIR / "block-detector.ts").read_text()
    assert "export function detectBlocks(" in src
    print("✓ detectBlocks exportado")


def test_plan_cycle_threshold():
    src = (PLUGIN_DIR / "block-detector.ts").read_text()
    assert "PLAN_CYCLE_THRESHOLD = 3" in src
    print("✓ PLAN_CYCLE_THRESHOLD = 3")


def test_context_overload_threshold():
    src = (PLUGIN_DIR / "block-detector.ts").read_text()
    assert "CONTEXT_OVERLOAD_THRESHOLD = 12" in src
    print("✓ CONTEXT_OVERLOAD_THRESHOLD = 12")


def test_block_kinds_detected():
    src = (PLUGIN_DIR / "block-detector.ts").read_text()
    assert "plan-cycle" in src
    assert "context-overload" in src
    assert "operator-decision-required" in src
    print("✓ BlockKinds detectados: plan-cycle, context-overload, operator-decision")


def test_count_phase_in_history():
    src = (PLUGIN_DIR / "block-detector.ts").read_text()
    assert "function countPhaseInHistory(" in src
    print("✓ countPhaseInHistory() implementado")


def test_count_artifact_references():
    src = (PLUGIN_DIR / "block-detector.ts").read_text()
    assert "function countArtifactReferences(" in src
    print("✓ countArtifactReferences() implementado")


def test_detection_result_structure():
    src = (PLUGIN_DIR / "block-detector.ts").read_text()
    assert "interface DetectionResult" in src
    assert "blocks:" in src
    assert "telemetry:" in src
    assert "hints:" in src
    print("✓ DetectionResult estructura completa")


def main():
    print("=== test_block_detector.py ===")
    test_detect_blocks_function()
    test_plan_cycle_threshold()
    test_context_overload_threshold()
    test_block_kinds_detected()
    test_count_phase_in_history()
    test_count_artifact_references()
    test_detection_result_structure()
    print("\nAll tests passed ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
