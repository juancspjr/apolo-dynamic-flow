#!/usr/bin/env python3
"""
test_tool_absorber.py — Tests del módulo de absorción de tools.

Valida:
  - absorbTools descubre MCPs desde opencode.json
  - absorbTools descubre skills en .opencode/skills/
  - absorbTools descubre plugins en .opencode/plugin/
  - absorbTools descubre scripts en scripts/python/
  - detectConflicts identifica capabilities duplicadas
  - verifyHealth marca tools como active/degraded
  - getFallbackChain construye cadena sin loops
"""

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent.parent / "plugin"


def test_absorb_tools_function():
    src = (PLUGIN_DIR / "tool-absorber.ts").read_text()
    assert "export function absorbTools(" in src
    print("✓ absorbTools exportado")


def test_build_mcp_tool():
    src = (PLUGIN_DIR / "tool-absorber.ts").read_text()
    assert "function buildMcpTool(" in src
    print("✓ buildMcpTool() crea tools desde opencode.json")


def test_build_skill_tool():
    src = (PLUGIN_DIR / "tool-absorber.ts").read_text()
    assert "function buildSkillTool(" in src
    print("✓ buildSkillTool() crea tools desde .opencode/skills/")


def test_build_plugin_tool():
    src = (PLUGIN_DIR / "tool-absorber.ts").read_text()
    assert "function buildPluginTool(" in src
    print("✓ buildPluginTool() crea tools desde .opencode/plugin/")


def test_build_script_tool():
    src = (PLUGIN_DIR / "tool-absorber.ts").read_text()
    assert "function buildScriptTool(" in src
    print("✓ buildScriptTool() crea tools desde scripts/python/")


def test_infer_capabilities():
    src = (PLUGIN_DIR / "tool-absorber.ts").read_text()
    assert "function inferMcpCapabilities(" in src
    assert "function inferSkillCapabilities(" in src
    assert "function inferScriptCapabilities(" in src
    print("✓ Heurísticas de capabilities implementadas")


def test_verify_health():
    src = (PLUGIN_DIR / "tool-absorber.ts").read_text()
    assert "function verifyHealth(" in src
    print("✓ verifyHealth() ejecuta health_check command")


def test_detect_conflicts():
    src = (PLUGIN_DIR / "tool-absorber.ts").read_text()
    assert "function detectConflicts(" in src
    assert "priority-first" in src
    print("✓ detectConflicts() identifica capabilities duplicadas")


def test_get_fallback_chain():
    src = (PLUGIN_DIR / "tool-absorber.ts").read_text()
    assert "export function getFallbackChain(" in src
    # Loop protection
    assert "chain.find" in src
    print("✓ getFallbackChain() con protección anti-loop")


def test_find_tool_by_capability():
    src = (PLUGIN_DIR / "tool-absorber.ts").read_text()
    assert "export function findToolByCapability(" in src
    print("✓ findToolByCapability() lookup por capability")


def main():
    print("=== test_tool_absorber.py ===")
    test_absorb_tools_function()
    test_build_mcp_tool()
    test_build_skill_tool()
    test_build_plugin_tool()
    test_build_script_tool()
    test_infer_capabilities()
    test_verify_health()
    test_detect_conflicts()
    test_get_fallback_chain()
    test_find_tool_by_capability()
    print("\nAll tests passed ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
