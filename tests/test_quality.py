#!/usr/bin/env python3
"""
test_quality.py — Tests de calidad del análisis (v2.5.0).

Valida:
  1. predict_impact.py: BFS multi-nivel detecta dependencias a profundidad 3+
  2. code_quality.py: detecta complejidad ciclomática alta
  3. code_quality.py: detecta vulnerabilidades de seguridad (simuladas)
  4. test_coverage.py: identifica símbolos sin cobertura
  5. lsp_integration.py: find-references funciona (con regex fallback)
  6. lsp_integration.py: get_diagnostics funciona
  7. code_quality.py: degradación graceful cuando herramientas no están disponibles

Los tests son resilientes: si una herramienta externa no está disponible,
el test pasa verificando que la degradación es graceful (se reporta en
`degradations` pero el script no falla).

Run: python3 tests/test_quality.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Hacer importable los scripts del patch (están al lado de este test).
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

# Si se corre desde el repo migrado (tests/test_quality.py), buscar
# scripts/python/ además.
REPO_SCRIPTS = THIS_DIR.parent / "scripts" / "python"
if REPO_SCRIPTS.exists():
    sys.path.insert(0, str(REPO_SCRIPTS))


# ============================================================================
# Stub fallback para common.py (cuando se corre aislado del patch)
# ============================================================================
#
# Cuando este test se ejecuta dentro del patch (sin common.py al lado),
# instalamos un stub mínimo que implementa las funciones que los scripts
# necesitan: log, now_iso, parse_args, read_yaml, write_yaml, run_cmd,
# cmd_available. Así los tests pueden validar la lógica de los scripts
# sin depender del common.py real (que vive en scripts/python/ en el
# plugin migrado).
#
# Cuando el test corre desde el plugin migrado, el common.py real se
# importa y el stub no se instala.

def _install_common_stub_if_needed() -> None:
    try:
        import common  # noqa: F401
        return  # Ya hay un common real disponible.
    except ImportError:
        pass

    stub = types.ModuleType("common")

    def now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def log(msg: str, level: str = "INFO") -> None:
        print(f"[{level}] {msg}", file=sys.stderr)

    def parse_args(argv: List[str]) -> Dict[str, str]:
        args: Dict[str, str] = {}
        i = 0
        while i < len(argv):
            a = argv[i]
            if a.startswith("--"):
                key = a[2:]
                if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                    args[key] = argv[i + 1]
                    i += 2
                else:
                    args[key] = "true"
                    i += 1
            else:
                i += 1
        return args

    def run_cmd(cmd, cwd: Optional[Path] = None, timeout: int = 60,
                capture: bool = True) -> Tuple[int, str, str]:
        if isinstance(cmd, str):
            cmd = ["bash", "-c", cmd]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=capture,
                text=True,
                timeout=timeout,
            )
            return (result.returncode, result.stdout or "", result.stderr or "")
        except subprocess.TimeoutExpired:
            return -1, "", "timeout"
        except Exception as e:
            return -1, "", str(e)

    def cmd_available(cmd: str) -> bool:
        code, _, _ = run_cmd(f"command -v {cmd} >/dev/null 2>&1", timeout=5)
        return code == 0

    # YAML stub minimalista (suficiente para los tests).
    def yaml_dump(obj: Any, indent: int = 0) -> str:
        pad = "  " * indent
        if obj is None:
            return "null"
        if isinstance(obj, bool):
            return "true" if obj else "false"
        if isinstance(obj, (int, float)):
            return str(obj)
        if isinstance(obj, str):
            return obj
        if isinstance(obj, list):
            if not obj:
                return "[]"
            out = []
            for item in obj:
                if isinstance(item, (dict, list)):
                    out.append(f"{pad}- {yaml_dump(item, indent + 1).lstrip()}")
                else:
                    out.append(f"{pad}- {yaml_dump(item, indent + 1)}")
            return "\n".join(out)
        if isinstance(obj, dict):
            if not obj:
                return "{}"
            out = []
            for k, v in obj.items():
                if isinstance(v, dict):
                    out.append(f"{pad}{k}:")
                    out.append(yaml_dump(v, indent + 1))
                elif isinstance(v, list):
                    out.append(f"{pad}{k}:")
                    out.append(yaml_dump(v, indent + 1))
                else:
                    out.append(f"{pad}{k}: {yaml_dump(v, indent)}")
            return "\n".join(out)
        return str(obj)

    def read_yaml(path) -> Optional[Any]:
        p = Path(path) if not isinstance(path, Path) else path
        if not p.exists():
            return None
        try:
            # Para tests, intentar json primero (más simple).
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def write_yaml(path, data: Any) -> None:
        p = Path(path) if not isinstance(path, Path) else path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml_dump(data) + "\n", encoding="utf-8")

    stub.now_iso = now_iso
    stub.log = log
    stub.parse_args = parse_args
    stub.run_cmd = run_cmd
    stub.cmd_available = cmd_available
    stub.read_yaml = read_yaml
    stub.write_yaml = write_yaml
    stub.yaml_dump = yaml_dump

    sys.modules["common"] = stub


_install_common_stub_if_needed()


def _import_predict_impact():
    """Importa predict_impact, fallback a path alternativo."""
    try:
        import predict_impact
        return predict_impact
    except ImportError:
        # Si tests/ está al lado de scripts/python/, ya está en sys.path.
        sys.path.insert(0, str(THIS_DIR.parent / "scripts" / "python"))
        import predict_impact
        return predict_impact


def _import_code_quality():
    try:
        import code_quality
        return code_quality
    except ImportError:
        sys.path.insert(0, str(THIS_DIR.parent / "scripts" / "python"))
        import code_quality
        return code_quality


def _import_test_coverage():
    try:
        import test_coverage
        return test_coverage
    except ImportError:
        sys.path.insert(0, str(THIS_DIR.parent / "scripts" / "python"))
        import test_coverage
        return test_coverage


def _import_lsp_integration():
    try:
        import lsp_integration
        return lsp_integration
    except ImportError:
        sys.path.insert(0, str(THIS_DIR.parent / "scripts" / "python"))
        import lsp_integration
        return lsp_integration


# ============================================================================
# Helpers: crear repos sintéticos para tests
# ============================================================================

def _make_chain_repo(repo_root: Path, depth: int = 4) -> Dict[str, Any]:
    """Crea un repo sintético con cadena A -> B -> C -> D -> E.

    El reverse_dependency_graph del CODE-INDEX se construye para que:
      A tenga dependiente B
      B tenga dependiente C
      C tenga dependiente D
      D tenga dependiente E

    Así el BFS debería alcanzar profundidad `depth`.
    """
    files = [f"src/file_{i}.py" for i in range(depth + 1)]
    for i, fpath in enumerate(files):
        full = repo_root / fpath
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(f"# file {i}\ndef func_{i}():\n    pass\n", encoding="utf-8")

    # reverse_dependency_graph: clave = archivo, valor = lista de archivos que lo importan.
    # A -> B -> C -> D -> E significa: B importa a A, C importa a B, etc.
    # En el reverse_dependency_graph: A -> [B], B -> [C], C -> [D], D -> [E].
    reverse_graph: Dict[str, List[str]] = {}
    for i in range(depth):
        reverse_graph[files[i]] = [files[i + 1]]

    code_index = {
        "schema_version": "2.5.0",
        "files": [{"path": f, "language": "python"} for f in files],
        "dependency_graph": {},
        "reverse_dependency_graph": reverse_graph,
    }
    return code_index


def _make_python_repo_with_complexity(repo_root: Path) -> Path:
    """Crea un archivo Python con una función de alta complejidad ciclomática."""
    target = repo_root / "complex_module.py"
    # Generar una función con muchos if/elif para forzar complejidad > 15.
    lines = ["def high_complexity_function(x):"]
    for i in range(20):
        lines.append(f"    if x == {i}:")
        lines.append(f"        return {i}")
    lines.append("    return -1")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _make_python_repo_with_secrets(repo_root: Path) -> Path:
    """Crea un archivo Python con patrones sospechosos de seguridad."""
    target = repo_root / "insecure_module.py"
    # Incluir un eval + exec (bandit los detecta como B102/B102).
    target.write_text(
        "def run_user_code(code_str):\n"
        "    # Peligroso: eval de input no confiable\n"
        "    result = eval(code_str)\n"
        "    exec(code_str)\n"
        "    return result\n",
        encoding="utf-8",
    )
    return target


# ============================================================================
# Tests
# ============================================================================

def test_predict_impact_bfs_multilevel():
    """Test 1: predict_impact.py BFS multi-nivel detecta profundidad 3+."""
    predict_impact = _import_predict_impact()
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        # Cadena A -> B -> C -> D -> E (profundidad 4 alcanzable).
        code_index = _make_chain_repo(repo_root, depth=4)
        # MP modifica solo A. El BFS debería encontrar B (nivel 1), C (nivel 2),
        # D (nivel 3), E (nivel 4).
        mp_files = ["src/file_0.py"]
        result = predict_impact.project_dependency_cascade(
            mp_files, code_index, cascade_depth=5
        )
        assert result["cascade_depth"] >= 3, (
            f"Esperado cascade_depth >= 3, got {result['cascade_depth']}"
        )
        assert result["total_affected_modules"] >= 3, (
            f"Esperado >=3 afectados, got {result['total_affected_modules']}"
        )
        # affected_by_level debería tener entradas para niveles 1, 2, 3, 4.
        levels = sorted(result["affected_by_level"].keys())
        assert 1 in levels and 4 in levels, (
            f"Esperado niveles 1..4 en affected_by_level, got {levels}"
        )
        print(f"  ✓ BFS multi-nivel: cascade_depth={result['cascade_depth']}, "
              f"affected_by_level={result['affected_by_level']}")


def test_predict_impact_bfs_cycle_safe():
    """Test 1b: BFS no entra en loop infinito con ciclos."""
    predict_impact = _import_predict_impact()
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        # Crear grafo cíclico: A -> B -> A.
        (repo_root / "a.py").write_text("# a\n", encoding="utf-8")
        (repo_root / "b.py").write_text("# b\n", encoding="utf-8")
        code_index = {
            "files": [{"path": "a.py"}, {"path": "b.py"}],
            "reverse_dependency_graph": {
                "a.py": ["b.py"],
                "b.py": ["a.py"],
            },
        }
        result = predict_impact.project_dependency_cascade(
            ["a.py"], code_index, cascade_depth=10
        )
        # No debe contar a.py ni b.py infinitas veces.
        assert result["total_affected_modules"] <= 2, (
            f"BFS con ciclo contó demasiados: {result['total_affected_modules']}"
        )
        print(f"  ✓ BFS cycle-safe: total_affected={result['total_affected_modules']}")


def test_code_quality_detects_high_complexity():
    """Test 2: code_quality.py detecta complejidad ciclomática alta."""
    code_quality = _import_code_quality()
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        target = _make_python_repo_with_complexity(repo_root)
        # Si radon está disponible, lo usa; si no, regex fallback.
        funcs, tool = code_quality.compute_complexity(target, "python")
        assert len(funcs) >= 1, f"Esperado >=1 función, got {len(funcs)}"
        # La función high_complexity_function debería tener complejidad > 15.
        hcf = next((f for f in funcs if f.get("function") == "high_complexity_function"), None)
        assert hcf is not None, "high_complexity_function no encontrada"
        cc = hcf.get("complexity", 0) or 0
        # Con regex: 20 ifs + 1 = 21. Con radon: también debería ser alto.
        assert cc > 15, f"Esperado complejidad > 15, got {cc} (tool={tool})"
        print(f"  ✓ Complejidad alta detectada: cc={cc} (tool={tool})")


def test_code_quality_detects_security_findings():
    """Test 3: code_quality.py detecta vulnerabilidades de seguridad (simuladas).

    Si bandit está instalado, debe detectar eval/exec.
    Si no está, el test verifica que la degradación se reporta gracefully.
    """
    code_quality = _import_code_quality()
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        target = _make_python_repo_with_secrets(repo_root)
        # run_security_for_language devuelve (findings, was_available, tool_name).
        findings, was_available, tool_name = code_quality.run_security_for_language(
            "python", target, repo_root
        )
        if was_available and tool_name == "bandit":
            # bandit debería detectar eval/exec como B102.
            assert len(findings) >= 1, (
                f"Esperado >=1 finding de bandit, got {len(findings)}"
            )
            print(f"  ✓ Bandit detectó {len(findings)} finding(s) de seguridad")
        else:
            # Bandit no disponible — verificar degradación graceful.
            print(f"  ✓ Degradación graceful: bandit no disponible, "
                  f"tool_name={tool_name}, findings={len(findings)}")
            # La función no debe crashear.
            assert isinstance(findings, list)


def test_test_coverage_identifies_uncovered_symbols():
    """Test 4: test_coverage.py identifica símbolos sin cobertura."""
    test_coverage = _import_test_coverage()
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        # Crear módulo con símbolos exportados y sin tests asociados.
        src = repo_root / "src"
        src.mkdir()
        (src / "module.py").write_text(
            "def public_function():\n"
            "    return 42\n"
            "def _private_function():\n"
            "    return 0\n"
            "class PublicClass:\n"
            "    pass\n",
            encoding="utf-8",
        )
        # No crear tests — todo debería quedar uncovered.
        report = test_coverage.analyze_coverage(repo_root, code_index=None)
        assert report["total_symbols"] >= 3, (
            f"Esperado >=3 símbolos, got {report['total_symbols']}"
        )
        assert report["covered_symbols"] == 0, (
            f"Esperado 0 cubiertos, got {report['covered_symbols']}"
        )
        assert report["uncovered_symbols"] >= 3, (
            f"Esperado >=3 uncovered, got {report['uncovered_symbols']}"
        )
        # critical_uncovered son los exportados sin test.
        assert len(report["critical_uncovered"]) >= 2, (
            f"Esperado >=2 critical_uncovered (public_function, PublicClass), "
            f"got {len(report['critical_uncovered'])}"
        )
        print(f"  ✓ Cobertura: {report['covered_symbols']}/{report['total_symbols']} "
              f"({report['coverage_percentage']}%) — "
              f"{len(report['critical_uncovered'])} críticos sin test")


def test_lsp_find_references_regex():
    """Test 5: lsp_integration.py find-references funciona con regex fallback."""
    lsp_integration = _import_lsp_integration()
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        # Crear 2 archivos Python: uno define foo(), otro la usa.
        (repo_root / "mod.py").write_text(
            "def foo():\n"
            "    return 1\n",
            encoding="utf-8",
        )
        (repo_root / "caller.py").write_text(
            "from mod import foo\n"
            "foo()\n"
            "x = foo()\n",
            encoding="utf-8",
        )
        result = lsp_integration.find_references("foo", repo_root)
        # El regex encuentra TODAS las ocurrencias (incluida la definición).
        assert result["count"] >= 2, (
            f"Esperado >=2 referencias, got {result['count']}"
        )
        # method debería ser 'regex' (no hay LSP configurado en el test).
        assert result["method"] == "regex", (
            f"Esperado method='regex', got '{result['method']}'"
        )
        print(f"  ✓ find-references: {result['count']} referencias "
              f"(method={result['method']})")


def test_lsp_get_diagnostics():
    """Test 6: lsp_integration.py get_diagnostics funciona."""
    lsp_integration = _import_lsp_integration()
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        # Crear archivo Python con TODO y print().
        target = repo_root / "messy.py"
        target.write_text(
            "# TODO: refactorizar esto\n"
            "def func():\n"
            "    print('debug')\n"
            "    return 1\n",
            encoding="utf-8",
        )
        result = lsp_integration.get_diagnostics(target, repo_root)
        assert result["count"] >= 2, (
            f"Esperado >=2 diagnostics (TODO + print), got {result['count']}"
        )
        # Verificar que detectó el TODO.
        rules = [d.get("rule") for d in result["diagnostics"]]
        assert "todo-comment" in rules, f"Esperado 'todo-comment' en rules, got {rules}"
        print(f"  ✓ get_diagnostics: {result['count']} diagnostics "
              f"(rules={set(rules)})")


def test_code_quality_graceful_degradation():
    """Test 7: code_quality.py degrada gracefully cuando herramientas no están."""
    code_quality = _import_code_quality()
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        # Crear 1 archivo Python + 1 TypeScript + 1 Go (sin tests ni herramientas).
        (repo_root / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
        (repo_root / "b.ts").write_text("export function g(): void {}\n", encoding="utf-8")
        (repo_root / "c.go").write_text("package main\nfunc h() {}\n", encoding="utf-8")

        report = code_quality.analyze_repo(repo_root)

        # Debe detectar los 3 lenguajes.
        assert "python" in report["languages_detected"], (
            f"Esperado python en languages_detected, got {report['languages_detected']}"
        )
        assert "typescript" in report["languages_detected"], (
            f"Esperado typescript en languages_detected, got {report['languages_detected']}"
        )
        assert "go" in report["languages_detected"], (
            f"Esperado go en languages_detected, got {report['languages_detected']}"
        )
        # Si bandit/gosec/eslint no están, debe haber degradaciones.
        # (No assertamos cantidad exacta porque puede que estén instalados.)
        assert isinstance(report["degradations"], list), (
            "degradations debe ser una lista"
        )
        # El reporte debe tener recommendations.
        assert len(report["recommendations"]) >= 1, (
            "Esperado >=1 recommendation"
        )
        # El reporte debe terminar con success (no crash).
        assert report["total_files"] == 3, (
            f"Esperado 3 archivos, got {report['total_files']}"
        )
        print(f"  ✓ Degradación graceful: {len(report['languages_detected'])} lenguajes, "
              f"{len(report['degradations'])} degradaciones, "
              f"{len(report['recommendations'])} recomendaciones")


# ============================================================================
# Runner
# ============================================================================

def main() -> int:
    print("=== test_quality.py (v2.5.0) ===\n")
    tests = [
        ("predict_impact BFS multi-nivel (profundidad 3+)", test_predict_impact_bfs_multilevel),
        ("predict_impact BFS cycle-safe (no infinite loop)", test_predict_impact_bfs_cycle_safe),
        ("code_quality detecta complejidad alta", test_code_quality_detects_high_complexity),
        ("code_quality detecta security findings (o degrada)", test_code_quality_detects_security_findings),
        ("test_coverage identifica símbolos sin cobertura", test_test_coverage_identifies_uncovered_symbols),
        ("lsp_integration find-references (regex)", test_lsp_find_references_regex),
        ("lsp_integration get_diagnostics", test_lsp_get_diagnostics),
        ("code_quality degradación graceful multi-lenguaje", test_code_quality_graceful_degradation),
    ]

    passed = 0
    failed = 0
    for name, test in tests:
        print(f"\n[TEST] {name}")
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAIL: {e}")
            failed += 1

    print(f"\n{'='*60}")
    if failed == 0:
        print(f"✅ ALL {passed} QUALITY TESTS PASSED (v2.5.0)")
        return 0
    else:
        print(f"❌ {failed} tests failed, {passed} passed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
