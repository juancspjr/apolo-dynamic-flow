#!/usr/bin/env python3
"""
test_security.py — Tests de seguridad para v2.4.0.

Valida:
  1. Detección de AWS Access Key
  2. Detección de GitHub token
  3. Detección de private key (PEM)
  4. Detección de DB connection string
  5. Detección de JWT
  6. Detección de password genérico
  7. Redacción reemplaza el secreto
  8. Allowlist permite orígenes confiables
  9. Allowlist rechaza orígenes no confiables
  10. Allowlist bloquea SSRF (localhost, 169.254.169.254)
  11. Hash chain detecta manipulación
  12. Hash chain válido pasa verificación

Run: python3 tests/test_security.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "python"))

from secret_scanner import (
    scan_text, redact_text, is_origin_allowed, load_security_config,
    compute_hash_chain_entry, verify_hash_chain,
)


def test_aws_access_key():
    """Test 1: Detección de AWS Access Key."""
    text = "aws_key = AKIAIOSFODNN7EXAMPLE"
    findings = scan_text(text)
    assert len(findings) >= 1, f"Esperado >=1 finding, got {len(findings)}"
    assert any(f["name"] == "aws_access_key" for f in findings)
    print("✓ Test 1: AWS Access Key detectado")


def test_github_token():
    """Test 2: Detección de GitHub token."""
    text = "token = ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    findings = scan_text(text)
    assert len(findings) >= 1
    assert any(f["name"] == "github_token" for f in findings)
    print("✓ Test 2: GitHub token detectado")


def test_private_key():
    """Test 3: Detección de private key PEM."""
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA..."
    findings = scan_text(text)
    assert len(findings) >= 1
    assert any(f["name"] == "private_key" for f in findings)
    print("✓ Test 3: Private key PEM detectado")


def test_db_connection_string():
    """Test 4: Detección de DB connection string."""
    text = "postgresql://user:secretpass@localhost:5432/db"
    findings = scan_text(text)
    assert len(findings) >= 1
    assert any(f["name"] == "db_connection_string" for f in findings)
    print("✓ Test 4: DB connection string detectado")


def test_jwt():
    """Test 5: Detección de JWT."""
    text = "Authorization: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    findings = scan_text(text)
    assert len(findings) >= 1
    assert any(f["name"] == "jwt_token" for f in findings)
    print("✓ Test 5: JWT detectado")


def test_generic_password():
    """Test 6: Detección de password genérico."""
    text = 'password = "mySecretPassword123"'
    findings = scan_text(text)
    assert len(findings) >= 1
    assert any(f["name"] == "generic_password" for f in findings)
    print("✓ Test 6: Password genérico detectado")


def test_redaction():
    """Test 7: Redacción reemplaza el secreto."""
    text = "aws_key = AKIAIOSFODNN7EXAMPLE"
    redacted, findings = redact_text(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted, "Secreto no redactado"
    assert "***REDACTED" in redacted, f"Redacción no aplicada: {redacted}"
    assert len(findings) >= 1
    print(f"✓ Test 7: Redacción OK → '{redacted}'")


def test_allowlist_allowed():
    """Test 8: Allowlist permite orígenes confiables."""
    # Cargar config de seguridad (debe estar en el directorio del plugin)
    config_path = Path(__file__).parent.parent / "security_config.yaml"
    config = load_security_config(config_path)
    allowed, reason = is_origin_allowed(
        "github://juancspjr/apolo-dynamic-flow/skills/my-skill/SKILL.md",
        config
    )
    assert allowed, f"Esperado allowed=True, got: {reason}"
    print(f"✓ Test 8: Allowlist permite origen confiable ({reason})")


def test_allowlist_denied():
    """Test 9: Allowlist rechaza orígenes no confiables."""
    config_path = Path(__file__).parent.parent / "security_config.yaml"
    config = load_security_config(config_path)
    allowed, reason = is_origin_allowed(
        "https://evil.com/malicious-skill.md",
        config
    )
    assert not allowed, f"Esperado allowed=False, got: {reason}"
    print(f"✓ Test 9: Allowlist rechaza origen no confiable ({reason})")


def test_ssrf_blocked():
    """Test 10: Allowlist bloquea SSRF (localhost, metadata endpoint)."""
    config_path = Path(__file__).parent.parent / "security_config.yaml"
    config = load_security_config(config_path)

    # Localhost
    allowed, _ = is_origin_allowed("http://localhost:8080/skill.md", config)
    assert not allowed, "Localhost debería estar bloqueado"

    # AWS metadata
    allowed, _ = is_origin_allowed("http://169.254.169.254/latest/meta-data/", config)
    assert not allowed, "AWS metadata debería estar bloqueado"

    # file://
    allowed, _ = is_origin_allowed("file:///etc/passwd", config)
    assert not allowed, "file:// debería estar bloqueado"

    print("✓ Test 10: SSRF protection (localhost, metadata, file:// bloqueados)")


def test_hash_chain_valid():
    """Test 11: Hash chain válido pasa verificación."""
    import hashlib

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        genesis = hashlib.sha256("APOLO-DYNAMIC-FLOW-GENESIS-V1".encode()).hexdigest()
        prev = genesis

        for i in range(5):
            entry = {"seq": i + 1, "actor": "test", "action": "test", "outcome": "success", "flow_id": "TEST"}
            entry["prev_hash"] = prev
            entry["entry_hash"] = compute_hash_chain_entry(entry, prev)
            f.write(json.dumps(entry) + "\n")
            prev = entry["entry_hash"]

        log_path = Path(f.name)

    valid, errors = verify_hash_chain(log_path)
    assert valid, f"Hash chain debería ser válido: {errors}"
    os.unlink(log_path)
    print("✓ Test 11: Hash chain válido pasa verificación")


def test_hash_chain_tampered():
    """Test 12: Hash chain detecta manipulación."""
    import hashlib

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        genesis = hashlib.sha256("APOLO-DYNAMIC-FLOW-GENESIS-V1".encode()).hexdigest()
        prev = genesis

        entries = []
        for i in range(3):
            entry = {"seq": i + 1, "actor": "test", "action": "test", "outcome": "success", "flow_id": "TEST"}
            entry["prev_hash"] = prev
            entry["entry_hash"] = compute_hash_chain_entry(entry, prev)
            entries.append(entry)
            prev = entry["entry_hash"]

        # Manipular la segunda entrada
        entries[1]["actor"] = "HACKED"

        for e in entries:
            f.write(json.dumps(e) + "\n")

        log_path = Path(f.name)

    valid, errors = verify_hash_chain(log_path)
    assert not valid, "Hash chain debería detectar manipulación"
    assert len(errors) > 0, "Debería haber errores"
    os.unlink(log_path)
    print(f"✓ Test 12: Hash chain detecta manipulación ({len(errors)} errores)")


def main():
    print("=== test_security.py (v2.4.0) ===\n")
    tests = [
        test_aws_access_key,
        test_github_token,
        test_private_key,
        test_db_connection_string,
        test_jwt,
        test_generic_password,
        test_redaction,
        test_allowlist_allowed,
        test_allowlist_denied,
        test_ssrf_blocked,
        test_hash_chain_valid,
        test_hash_chain_tampered,
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
        print(f"✅ ALL {passed} SECURITY TESTS PASSED")
        return 0
    else:
        print(f"❌ {failed} tests failed, {passed} passed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
