#!/usr/bin/env python3
"""
test_python_scripts.py — Tests funcionales de los scripts Python.

Valida:
  - common.py: yaml_dump / yaml_load round-trip
  - common.py: sha256 / hash_file / hash_chain
  - common.py: parse_args
  - common.py: detect_capabilities
  - validate_artifact.py: detecta required faltante
  - validate_artifact.py: detecta type mismatch
  - generate_plan.py: topological_sort con dependencias
  - generate_plan.py: should_split detecta mixed concerns
  - collect_evidence.py: produce EVIDENCE-PACK.yaml con hash_chain
"""

import sys
import json
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts" / "python"
sys.path.insert(0, str(SCRIPTS_DIR))


def test_yaml_round_trip():
    import common
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
        },
    }
    yaml_text = common.yaml_dump(data)
    parsed = common.yaml_load(yaml_text)
    assert parsed["flowid"] == data["flowid"]
    assert parsed["version"] == data["version"]
    assert len(parsed["items"]) == 2
    assert parsed["items"][0]["id"] == "E-001"
    assert parsed["nested"]["a"] == 1
    assert parsed["nested"]["c"] is None
    assert parsed["nested"]["d"] is True
    print("✓ YAML round-trip preserva estructura")


def test_sha256():
    import common
    h = common.sha256("hello")
    assert len(h) == 64
    assert h == common.sha256("hello")
    assert h != common.sha256("world")
    print("✓ sha256 determinista")


def test_hash_chain():
    import common
    items = [{"hash": "a"}, {"hash": "b"}, {"hash": "c"}]
    chain = common.hash_chain(items)
    assert chain == common.sha256("abc")
    print("✓ hash_chain concatena hashes en orden")


def test_parse_args():
    import common
    args = common.parse_args(["--flowid", "APOLO-TEST", "--json", "--count", "5"])
    assert args["flowid"] == "APOLO-TEST"
    assert args["json"] == "true"  # flag sin valor
    assert args["count"] == "5"
    print("✓ parse_args soporta --key value y --flag")


def test_validate_required_missing():
    import common
    data = {"a": 1, "b": None}
    errors = common.validate_required(data, ["a", "b", "c"], "test")
    assert any("c" in e for e in errors), f"esperaba error por 'c' faltante: {errors}"
    assert any("b" in e for e in errors), f"esperaba error por 'b' null: {errors}"
    print("✓ validate_required detecta faltantes y nulls")


def test_validate_artifact_script():
    """Ejecuta validate_artifact.py con un artifact inválido."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        artifact = tmp_path / "artifact.yaml"
        schema = tmp_path / "schema.yaml"
        artifact.write_text("foo: bar\n")
        schema.write_text("type: object\nrequired:\n  - baz\n")
        result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "validate_artifact.py"),
             "--artifact", str(artifact), "--schema", str(schema)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1, f"esperaba exit 1, got {result.returncode}"
        assert "baz" in result.stderr or "baz" in result.stdout
    print("✓ validate_artifact.py detecta campo requerido faltante")


def test_generate_plan_topological_sort():
    """Verifica topological_sort con dependencias."""
    import generate_plan
    units = [
        {"id": "U-01", "dependenciasprevias": []},
        {"id": "U-02", "dependenciasprevias": ["U-01"]},
        {"id": "U-03", "dependenciasprevias": ["U-01", "U-02"]},
        {"id": "U-04", "dependenciasprevias": ["U-02"]},
    ]
    order = generate_plan.topological_sort(units)
    ids = [o["unit_id"] for o in order]
    # U-01 antes de U-02 antes de U-03 y U-04
    assert ids.index("U-01") < ids.index("U-02")
    assert ids.index("U-02") < ids.index("U-03")
    assert ids.index("U-02") < ids.index("U-04")
    print("✓ topological_sort respeta dependencias")


def test_generate_plan_should_split():
    """should_split detecta mixed concerns."""
    import generate_plan
    cluster = {
        "acoplamientosreales": {
            "archivos": [
                "internal/handlers/foo.go",
                "internal/ui/modal.tsx",
            ],
        }
    }
    splits = generate_plan.should_split(cluster)
    assert splits is not None
    assert "handler" in splits
    assert "ui" in splits
    print(f"✓ should_split detecta: {splits}")


def test_generate_plan_estimate_mps():
    """estimate_mps calcula MPs por símbolos."""
    import generate_plan
    assert generate_plan.estimate_mps([]) == "1"
    assert generate_plan.estimate_mps(["a", "b"]) == "1"
    assert generate_plan.estimate_mps(["a", "b", "c", "d", "e"]) == "2"
    assert generate_plan.estimate_mps(list(range(15))) == "4"
    print("✓ estimate_mps escala con símbolos acoplados")


def test_generate_plan_cluster_to_unit():
    """cluster_to_unit convierte cluster a unit válida."""
    import generate_plan
    cluster = {
        "componente": "cluster8",
        "estado5": "ER",
        "resumen": "test resumen",
        "acoplamientosreales": {
            "archivos": ["internal/handlers/foo.go"],
            "simbolos": ["Aprobar"],
        },
        "fronteraconfianza": {
            "confirmado": ["foo existe"],
            "pendienteoperador": [],
            "paradoja": [],
            "fueraalcance": [],
        },
    }
    unit = generate_plan.cluster_to_unit(cluster, "U-01", [])
    assert unit["id"] == "U-01"
    assert unit["origenverdad"]["componente"] == "cluster8"
    assert unit["admisibleaindice"] is True
    assert unit["tipocambio"] == "fix"
    print("✓ cluster_to_unit produce unit válida")


def test_collect_evidence_produces_pack():
    """collect_evidence.py genera EVIDENCE-PACK.yaml con hash_chain."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "foo.py").write_text("def bar():\n    pass\n")

        out = tmp_path / "EVIDENCE-PACK.yaml"
        result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "collect_evidence.py"),
             "--flowid", "APOLO-20260620-TEST",
             "--repo-root", str(repo),
             "--output", str(out),
             "--invoked-by", "test",
             "--scope-json", json.dumps({"paths": ["foo.py"], "git_diff": False})],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert out.exists(), "EVIDENCE-PACK.yaml no se creó"

        import common
        pack = common.read_yaml(out)
        assert pack is not None
        assert pack["flowid"] == "APOLO-20260620-TEST"
        assert len(pack["items"]) == 1
        assert pack["items"][0]["kind"] == "file-snapshot"
        assert pack["items"][0]["hash"] != ""
        assert pack["hash_chain"] != ""
        assert pack["capabilities"]["python"] == "available"
    print("✓ collect_evidence.py genera pack con hash_chain y capabilities")


def test_main():
    print("=== test_python_scripts.py ===")
    test_yaml_round_trip()
    test_sha256()
    test_hash_chain()
    test_parse_args()
    test_validate_required_missing()
    test_validate_artifact_script()
    test_generate_plan_topological_sort()
    test_generate_plan_should_split()
    test_generate_plan_estimate_mps()
    test_generate_plan_cluster_to_unit()
    test_collect_evidence_produces_pack()
    print("\nAll tests passed ✓")
    return 0


if __name__ == "__main__":
    sys.exit(test_main())
