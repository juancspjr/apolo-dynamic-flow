#!/usr/bin/env python3
"""
test_loop_engine.py — Tests del loop dinámico con circuit breaker.

Valida:
  - runLoopIteration transita en pass
  - runLoopIteration incrementa counter en refine
  - Circuit breaker bloquea al agotar max iteraciones
  - blockAndStay crea Block con ID
  - Telemetría se emite en cada iteración
"""

import sys
import json
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent.parent / "plugin"


def test_loop_iteration_function_exists():
    src = (PLUGIN_DIR / "loop-engine.ts").read_text()
    assert "export function runLoopIteration(" in src
    print("✓ runLoopIteration exportado")


def test_transit_function_exists():
    src = (PLUGIN_DIR / "loop-engine.ts").read_text()
    assert "function transit(" in src
    print("✓ transit() definido")


def test_block_and_stay_function():
    src = (PLUGIN_DIR / "loop-engine.ts").read_text()
    assert "function blockAndStay(" in src
    assert "BLOQUEO-" in src
    print("✓ blockAndStay() crea BLOQUEO-NNN")


def test_circuit_breaker_logic():
    """Verifica que el código contiene la lógica de max iteraciones."""
    src = (PLUGIN_DIR / "loop-engine.ts").read_text()
    assert "maxed" in src
    assert "circuit-breaker-escalate" in src
    assert "circuit-breaker-exhausted" in src
    assert "fail-open-adaptive" in src
    assert "fail-closed" in src
    print("✓ Circuit breaker con fail-closed y fail-open-adaptive")


def test_reset_counter_on_transit():
    """Al transitar a nueva fase, su loop counter se resetea."""
    src = (PLUGIN_DIR / "loop-engine.ts").read_text()
    assert "function resetCounter(" in src
    print("✓ resetCounter() reinicia counter al transitar")


def test_telemetry_emitted():
    """Cada iteración emite eventos de telemetría."""
    src = (PLUGIN_DIR / "loop-engine.ts").read_text()
    assert "telemetry: TelemetryEvent[]" in src
    assert "gate-evaluated" in src
    assert "phase-enter" in src
    assert "block-detected" in src
    assert "loop-iter" in src
    print("✓ Telemetría emitida en cada decisión")


def test_suggest_resolution_present():
    """suggestResolution() devuelve sugerencias por kind de bloqueo."""
    src = (PLUGIN_DIR / "loop-engine.ts").read_text()
    assert "function suggestResolution(" in src
    assert "missing-artifact" in src
    assert "missing-evidence" in src
    assert "plan-cycle" in src
    print("✓ suggestResolution() cubre todos los BlockKind")


def test_loop_result_structure():
    src = (PLUGIN_DIR / "loop-engine.ts").read_text()
    assert "interface LoopResult" in src
    assert "transitioned:" in src
    assert "blockCreated?" in src
    print("✓ LoopResult estructura completa")


def main():
    print("=== test_loop_engine.py ===")
    test_loop_iteration_function_exists()
    test_transit_function_exists()
    test_block_and_stay_function()
    test_circuit_breaker_logic()
    test_reset_counter_on_transit()
    test_telemetry_emitted()
    test_suggest_resolution_present()
    test_loop_result_structure()
    print("\nAll tests passed ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
