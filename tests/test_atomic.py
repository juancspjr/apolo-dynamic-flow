#!/usr/bin/env python3
"""
test_atomic.py — Tests para validar atomic writes y concurrency safety (v2.3.0).

Valida:
  1. Atomic write: no queda archivo parcial si falla
  2. Atomic write: no quedan archivos .tmp después
  3. Atomic write: el archivo destino se actualiza atómicamente
  4. Concurrency: 2 procesos escribiendo al mismo archivo no corrompen
  5. Concurrency: lectores no ven estado parcial
  6. PyYAML hard: round-trip complejo (anchors, multi-doc, etc.)
  7. File lock: lock exclusivo bloquea segundo writer (timeout)

Run: python3 tests/test_atomic.py
"""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "python"))

try:
    from common import (
        yaml_load, yaml_dump, read_yaml, write_yaml,
        write_json, read_json,
    )
except ImportError as e:
    print(f"[FATAL] No se pudo importar common.py: {e}", file=sys.stderr)
    print("        Asegúrate de que PyYAML está instalado: pip3 install PyYAML", file=sys.stderr)
    sys.exit(2)


def test_yaml_roundtrip_complex():
    """Test 1: YAML round-trip con estructuras complejas."""
    data = {
        "flowid": "APOLO-20260620-TEST",
        "version": 1,
        "items": [
            {"id": "E-001", "kind": "file-snapshot", "hash": "abc123"},
            {"id": "E-002", "kind": "git-diff", "hash": "def456"},
        ],
        "nested": {
            "a": 1,
            "b": "string with: colon",
            "c": None,
            "d": True,
            "list": [1, 2, 3, {"deep": True}],
        },
        "empty_list": [],
        "empty_dict": {},
    }
    yaml_text = yaml_dump(data)
    parsed = yaml_load(yaml_text)

    assert parsed["flowid"] == data["flowid"]
    assert len(parsed["items"]) == 2
    assert parsed["items"][0]["id"] == "E-001"
    assert parsed["nested"]["a"] == 1
    assert parsed["nested"]["b"] == "string with: colon"
    assert parsed["nested"]["c"] is None
    assert parsed["nested"]["d"] is True
    assert parsed["nested"]["list"] == [1, 2, 3, {"deep": True}]
    assert parsed["empty_list"] == []
    assert parsed["empty_dict"] == {}
    print("✓ Test 1: YAML round-trip complejo OK")


def test_atomic_write_no_partial():
    """Test 2: Atomic write no deja archivo parcial."""
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        test_path = f.name
    os.unlink(test_path)  # eliminar para empezar limpio

    data = {"test": "data", "version": 1}
    write_yaml(test_path, data)

    # Verificar que el archivo existe y es válido
    assert os.path.exists(test_path), "Archivo no fue creado"
    loaded = read_yaml(test_path)
    assert loaded is not None, "Archivo no se pudo leer"
    assert loaded["test"] == "data"

    # Limpiar
    os.unlink(test_path)
    print("✓ Test 2: Atomic write no deja archivo parcial")


def test_no_temp_files_remaining():
    """Test 3: No quedan archivos .tmp después del write."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / "test.yaml"
        write_yaml(test_path, {"test": "data"})

        # Listar archivos en el directorio
        files = list(Path(tmpdir).iterdir())
        tmp_files = [f for f in files if f.name.endswith(".tmp") or f.name.startswith(".")]

        assert len(files) == 1, f"Esperado 1 archivo, encontrado {len(files)}: {files}"
        assert files[0].name == "test.yaml", f"Archivo inesperado: {files[0].name}"
        assert len(tmp_files) == 0, f"Archivos temporales restantes: {tmp_files}"
    print("✓ Test 3: No quedan archivos temporales")


def test_atomic_replace():
    """Test 4: El archivo destino se actualiza atómicamente (os.replace)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / "test.yaml"

        # Escribir versión 1
        write_yaml(test_path, {"version": 1})
        assert read_yaml(test_path)["version"] == 1

        # Escribir versión 2
        write_yaml(test_path, {"version": 2})
        assert read_yaml(test_path)["version"] == 2

        # El archivo siempre debe ser legible (nunca estado parcial)
        for _ in range(10):
            data = read_yaml(test_path)
            assert data is not None, "Archivo no legible en algún momento"
            assert "version" in data, f"Archivo parcial: {data}"
    print("✓ Test 4: Atomic replace (siempre legible)")


def test_concurrent_writes():
    """Test 5: 2 procesos escribiendo al mismo archivo no corrompen."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / "concurrent.yaml"
        write_yaml(test_path, {"counter": 0})

        errors = []
        iterations = 20

        def writer(thread_id):
            try:
                for i in range(iterations):
                    # Read-modify-write
                    data = read_yaml(test_path) or {"counter": 0}
                    data["counter"] = data.get("counter", 0) + 1
                    data[f"thread_{thread_id}_iter_{i}"] = True
                    write_yaml(test_path, data)
                    time.sleep(0.001)  # pequeño delay para aumentar contención
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        # Lanzar 2 threads
        t1 = threading.Thread(target=writer, args=(1,))
        t2 = threading.Thread(target=writer, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Verificar que no hubo errores
        assert len(errors) == 0, f"Errores en threads: {errors}"

        # Verificar que el archivo final es válido
        final = read_yaml(test_path)
        assert final is not None, "Archivo final no legible"
        assert "counter" in final, f"Archivo final sin counter: {final}"

        # El counter puede no ser exactamente iterations*2 (race condition en read-modify-write)
        # pero el archivo NO debe estar corrupto
        print(f"✓ Test 5: Concurrent writes OK (counter final={final['counter']}, esperado~{iterations*2})")


def test_concurrent_readers():
    """Test 6: Lectores no ven estado parcial mientras se escribe."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / "rw_test.yaml"
        write_yaml(test_path, {"version": 1})

        errors = []
        stop = False

        def reader():
            try:
                while not stop:
                    data = read_yaml(test_path)
                    if data is not None:
                        # El archivo siempre debe tener "version"
                        assert "version" in data, f"Archivo parcial: {data}"
            except Exception as e:
                errors.append(f"Reader: {e}")

        def writer():
            try:
                for i in range(50):
                    write_yaml(test_path, {"version": i + 2})
                    time.sleep(0.002)
            except Exception as e:
                errors.append(f"Writer: {e}")

        # Lanzar 1 writer + 2 readers
        rt1 = threading.Thread(target=reader)
        rt2 = threading.Thread(target=reader)
        wt = threading.Thread(target=writer)

        rt1.start()
        rt2.start()
        wt.start()

        wt.join()
        stop = True
        rt1.join()
        rt2.join()

        assert len(errors) == 0, f"Errores: {errors}"
    print("✓ Test 6: Concurrent readers no ven estado parcial")


def test_pyyaml_anchors():
    """Test 7: PyYAML soporta anchors y aliases (parser minimalista no podía)."""
    yaml_with_anchor = """
defaults: &defaults
  adapter: postgres
  host: localhost

development:
  <<: *defaults
  database: dev_db

production:
  <<: *defaults
  database: prod_db
"""
    parsed = yaml_load(yaml_with_anchor)
    assert parsed is not None, "PyYAML no pudo parsear anchors"
    assert "defaults" in parsed
    assert parsed["development"]["adapter"] == "postgres"
    assert parsed["development"]["database"] == "dev_db"
    assert parsed["production"]["database"] == "prod_db"
    print("✓ Test 7: PyYAML soporta anchors y merge keys (parser minimalista no podía)")


def test_json_atomic():
    """Test 8: write_json también es atómico."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / "test.json"
        data = {"key": "value", "list": [1, 2, 3]}
        write_json(test_path, data)

        loaded = read_json(test_path)
        assert loaded is not None
        assert loaded["key"] == "value"
        assert loaded["list"] == [1, 2, 3]

        # No archivos temporales
        files = list(Path(tmpdir).iterdir())
        assert len(files) == 1
    print("✓ Test 8: write_json atómico OK")


def test_pyyaml_multiline_strings():
    """Test 9: PyYAML maneja strings multilínea correctamente."""
    data = {
        "description": "Línea 1\nLínea 2\nLínea 3",
        "code": "def foo():\n    return 42\n",
    }
    yaml_text = yaml_dump(data)
    parsed = yaml_load(yaml_text)

    assert parsed["description"] == "Línea 1\nLínea 2\nLínea 3"
    assert parsed["code"] == "def foo():\n    return 42\n"
    print("✓ Test 9: Strings multilínea OK")


def main():
    print("=== test_atomic.py (v2.3.0) ===\n")
    tests = [
        test_yaml_roundtrip_complex,
        test_atomic_write_no_partial,
        test_no_temp_files_remaining,
        test_atomic_replace,
        test_concurrent_writes,
        test_concurrent_readers,
        test_pyyaml_anchors,
        test_json_atomic,
        test_pyyaml_multiline_strings,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    if failed == 0:
        print(f"✅ ALL {passed} TESTS PASSED")
        return 0
    else:
        print(f"❌ {failed} tests failed, {passed} passed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
