#!/usr/bin/env python3
"""test_intelligence.py — Tests de capacidades de inteligencia (v2.6.0)."""
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "python"))

def test_llm_bridge_available():
    from llm_bridge import is_available
    result = is_available()
    assert isinstance(result, bool)
    print("✓ llm_bridge: is_available() retorna bool")

def test_llm_bridge_chat_no_api():
    from llm_bridge import chat
    # Sin API key (o con ella), chat no debe crashear
    os.environ.pop("MINIMAX_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    result = chat([{"role": "user", "content": "test"}])
    assert result is None, f"Expected None without API, got {result}"
    print("✓ llm_bridge: chat() retorna None sin API key")

def test_self_healing_success_rates():
    from self_healing import compute_success_rates
    events = [
        {"actor": "agent:planner", "phase": "reanclaje", "outcome": "success", "action": "decision_made"},
        {"actor": "agent:planner", "phase": "reanclaje", "outcome": "success", "action": "decision_made"},
        {"actor": "agent:planner", "phase": "reanclaje", "outcome": "failure", "action": "decision_made"},
    ]
    rates = compute_success_rates(events)
    assert "planner" in rates
    assert rates["planner"]["reanclaje"]["success_rate"] > 0.6
    print(f"✓ self_healing: success_rate={rates['planner']['reanclaje']['success_rate']}")

def test_self_healing_suggestions():
    from self_healing import suggest_adjustments
    rates = {"planner": {"verdad": {"total": 5, "success": 1, "fail": 4, "success_rate": 0.2}}}
    suggestions = suggest_adjustments(rates)
    assert len(suggestions) > 0, "Expected suggestions for 20% success rate"
    assert suggestions[0]["agent"] == "planner"
    print(f"✓ self_healing: {len(suggestions)} sugerencias generadas")

def test_self_healing_patterns():
    from self_healing import analyze_failure_patterns
    events = [
        {"action": "test_failed", "phase": "implementation", "outcome": "failure", "message": "assertion error"},
        {"action": "test_failed", "phase": "implementation", "outcome": "failure", "message": "timeout"},
        {"action": "test_failed", "phase": "implementation", "outcome": "failure", "message": "compilation"},
    ]
    patterns = analyze_failure_patterns(events)
    assert len(patterns) > 0
    assert patterns[0]["count"] >= 3
    print(f"✓ self_healing: {len(patterns)} patrones detectados")

def test_generate_tests_stub():
    from generate_tests import generate_stub
    sym = {"language": "py", "symbol": "my_func", "args": ["x", "y"], "file": "src/mod.py", "line": 10}
    stub = generate_stub(sym)
    assert "def test_my_func" in stub
    assert "my_func" in stub
    print("✓ generate_tests: stub Python generado")

def test_generate_tests_ts():
    from generate_tests import generate_stub
    sym = {"language": "ts", "symbol": "myFunc", "args": [], "file": "src/mod.ts", "line": 5}
    stub = generate_stub(sym)
    assert "describe" in stub or "test" in stub.lower()
    print("✓ generate_tests: stub TypeScript generado")

def test_generate_tests_go():
    from generate_tests import generate_stub
    sym = {"language": "go", "symbol": "MyFunc", "args": [], "file": "src/mod.go", "line": 5}
    stub = generate_stub(sym)
    assert "func Test" in stub
    print("✓ generate_tests: stub Go generado")

def test_semantic_search_cosine():
    from semantic_search import cosine_sim
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    c = [0.0, 1.0, 0.0]
    assert cosine_sim(a, b) == 1.0
    assert cosine_sim(a, c) == 0.0
    print("✓ semantic_search: cosine_similarity (identical=1.0, orthogonal=0.0)")

def test_semantic_search_tf_idf():
    from semantic_search import tf_idf
    docs = {"file1": "function initialize flow state", "file2": "function calculate taxes"}
    results = tf_idf(docs, "initialize flow")
    assert len(results) > 0
    assert results[0][0] == "file1"
    print(f"✓ semantic_search: TF-IDF retorna {results[0][0]} como top match")

def test_refactor_detect_long():
    from refactor_engine import detect_smells
    ci = {"files": [{"path": "test.py", "language": "py", "symbols": {"functions": [{"name": "longFunc", "line": 1, "is_exported": True}], "classes": []}}]}
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "test.py"
        p.write_text("def longFunc():\n" + "    pass\n" * 60)
        smells = detect_smells(ci, Path(d))
        long_smells = [s for s in smells if s["smell"] == "long_function"]
        assert len(long_smells) > 0, f"Expected long_function smell, got {smells}"
        print(f"✓ refactor_engine: detectada función larga ({long_smells[0]['lines']} líneas)")

def test_refactor_detect_god_class():
    from refactor_engine import detect_smells
    methods = [{"name": f"m{i}", "line": i} for i in range(15)]
    ci = {"files": [{"path": "test.py", "language": "py", "symbols": {"functions": [], "classes": [{"name": "GodClass", "methods": methods}]}}]}
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "test.py"
        p.write_text("class GodClass:\n    pass\n")
        smells = detect_smells(ci, Path(d))
        god = [s for s in smells if s["smell"] == "god_class"]
        assert len(god) > 0
        print(f"✓ refactor_engine: detectada god class ({god[0]['methods']} métodos)")

def main():
    print("=== test_intelligence.py (v2.6.0) ===\n")
    tests = [
        test_llm_bridge_available, test_llm_bridge_chat_no_api,
        test_self_healing_success_rates, test_self_healing_suggestions, test_self_healing_patterns,
        test_generate_tests_stub, test_generate_tests_ts, test_generate_tests_go,
        test_semantic_search_cosine, test_semantic_search_tf_idf,
        test_refactor_detect_long, test_refactor_detect_god_class,
    ]
    passed = failed = 0
    for t in tests:
        try: t(); passed += 1
        except Exception as e: print(f"✗ {t.__name__}: {e}"); failed += 1
    print(f"\n{'='*50}")
    if failed == 0: print(f"✅ ALL {passed} INTELLIGENCE TESTS PASSED"); return 0
    else: print(f"❌ {failed} failed, {passed} passed"); return 1

if __name__ == "__main__":
    sys.exit(main())
