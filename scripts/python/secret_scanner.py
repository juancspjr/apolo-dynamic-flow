#!/usr/bin/env python3
"""
secret_scanner.py — Detector de secretos en evidencia y artifacts.

v2.4.0: Escanea contenido antes de escribirlo a EVIDENCE-PACK.yaml o
cualquier artifact que vaya a logs. Si detecta secretos, los REDACTA.

Usa patrones regex de security_config.yaml (no depende de detect-secrets
ni trufflehog externos — los patrones están integrados para cero dependencias).

Patrones detectados:
  - API keys genéricas
  - AWS Access Key / Secret Key
  - GitHub tokens (ghp_, gho_, ghs_, ghu_, ghr_)
  - Bearer tokens
  - Private keys (PEM)
  - Database connection strings
  - JWT tokens
  - Generic passwords
  - Slack tokens
  - Stripe keys

Uso:
  # Escanear un archivo
  python3 secret_scanner.py --scan-file path/to/file.yaml

  # Escanear un texto (stdin)
  echo "api_key=abc123..." | python3 secret_scanner.py --scan-stdin

  # Escanear y redactar (devuelve el texto con secretos reemplazados)
  python3 secret_scanner.py --scan-file file.yaml --redact --output file_redacted.yaml

  # Como lib: from secret_scanner import scan_text, redact_text
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml


# ============================================================================
# Default patterns (usados si security_config.yaml no existe)
# ============================================================================

DEFAULT_PATTERNS = [
    {
        "name": "aws_access_key",
        "pattern": r'AKIA[0-9A-Z]{16}',
        "replacement": '***REDACTED_AWS_KEY***',
    },
    {
        "name": "aws_secret_key",
        "pattern": r'(?i)aws_secret_access_key\s*[=:]\s*["\']?([A-Za-z0-9/+=]{40})["\']?',
        "replacement": 'aws_secret_access_key=***REDACTED***',
    },
    {
        "name": "github_token",
        "pattern": r'gh[pousr]_[A-Za-z0-9]{36}',
        "replacement": '***REDACTED_GITHUB_TOKEN***',
    },
    {
        "name": "bearer_token",
        "pattern": r'(?i)bearer\s+([A-Za-z0-9_\-\.]{20,})',
        "replacement": 'bearer ***REDACTED***',
    },
    {
        "name": "private_key",
        "pattern": r'-----BEGIN (RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----',
        "replacement": '***REDACTED_PRIVATE_KEY***',
    },
    {
        "name": "db_connection_string",
        "pattern": r'(postgresql|mysql|mongodb|redis)://[^\s:]+:[^\s@]+@',
        "replacement": r'\1://***REDACTED***:***REDACTED***@',
    },
    {
        "name": "jwt_token",
        "pattern": r'eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+',
        "replacement": '***REDACTED_JWT***',
    },
    {
        "name": "generic_password",
        "pattern": r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?([^\s"\']{8,})["\']?',
        "replacement": r'\1=***REDACTED***',
    },
    {
        "name": "generic_api_key",
        "pattern": r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?([A-Za-z0-9_\-]{20,})["\']?',
        "replacement": r'\1=***REDACTED***',
    },
    {
        "name": "slack_token",
        "pattern": r'xox[baprs]-[A-Za-z0-9-]+',
        "replacement": '***REDACTED_SLACK_TOKEN***',
    },
    {
        "name": "stripe_key",
        "pattern": r'(sk|pk)_(test_|live_)[A-Za-z0-9]{24,}',
        "replacement": '***REDACTED_STRIPE_KEY***',
    },
]


# ============================================================================
# Pattern loader
# ============================================================================

def load_patterns(config_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Carga patrones desde security_config.yaml o usa defaults.
    v2.5.1 FIX: siempre retorna patrones válidos, incluso si config falla.
    """
    # Siempre preparar DEFAULT_PATTERNS primero como fallback garantizado
    defaults = []
    for p in DEFAULT_PATTERNS:
        dp = dict(p)  # copia para no mutar el original
        try:
            dp["_compiled"] = re.compile(dp["pattern"])
        except re.error:
            dp["_compiled"] = None
        defaults.append(dp)

    if config_path is None:
        candidates = [
            Path.cwd() / "security_config.yaml",
            Path.cwd() / ".opencode" / "apolo-dynamic" / "security_config.yaml",
            Path(__file__).parent.parent.parent / "security_config.yaml",
        ]
        for c in candidates:
            if c.exists():
                config_path = c
                break

    if config_path and config_path.exists():
        try:
            config = read_yaml(config_path)
            if config and isinstance(config, dict):
                patterns = config.get("secret_patterns", [])
                if patterns and isinstance(patterns, list):
                    compiled = []
                    for p in patterns:
                        cp = dict(p)
                        try:
                            cp["_compiled"] = re.compile(cp["pattern"])
                        except re.error as e:
                            log(f"Patrón regex inválido '{cp.get('name')}': {e}", "WARN")
                            continue  # skip inválido, no añadir None
                        compiled.append(cp)
                    if compiled:
                        return compiled
                    log("security_config.yaml no tiene patrones válidos, usando defaults", "WARN")
        except Exception as e:
            log(f"Error cargando security_config.yaml: {e}, usando defaults", "WARN")

    return defaults


# ============================================================================
# Scanner
# ============================================================================

def scan_text(text: str, patterns: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Escanea un texto y retorna lista de secretos detectados.

    Returns: [{name, match, position, line}]
    """
    if patterns is None:
        patterns = load_patterns()

    findings: List[Dict[str, Any]] = []

    for p in patterns:
        compiled = p.get("_compiled")
        if compiled is None:
            continue

        for m in compiled.finditer(text):
            # Calcular línea
            line = text[:m.start()].count("\n") + 1
            findings.append({
                "name": p.get("name", "unknown"),
                "match": m.group(0)[:50] + "..." if len(m.group(0)) > 50 else m.group(0),
                "position": m.start(),
                "line": line,
                "replacement": p.get("replacement", "***REDACTED***"),
            })

    return findings


def redact_text(text: str, patterns: Optional[List[Dict[str, Any]]] = None) -> Tuple[str, List[Dict[str, Any]]]:
    """Redacta secretos en un texto. Retorna (texto_redactado, findings)."""
    if patterns is None:
        patterns = load_patterns()

    findings: List[Dict[str, Any]] = []
    redacted = text

    for p in patterns:
        compiled = p.get("_compiled")
        if compiled is None:
            continue

        replacement = p.get("replacement", "***REDACTED***")

        # Encontrar matches antes de reemplazar (para reportar)
        for m in compiled.finditer(redacted):
            line = redacted[:m.start()].count("\n") + 1
            findings.append({
                "name": p.get("name", "unknown"),
                "match": m.group(0)[:50] + "..." if len(m.group(0)) > 50 else m.group(0),
                "position": m.start(),
                "line": line,
                "redacted": True,
            })

        # Reemplazar
        redacted = compiled.sub(replacement, redacted)

    return redacted, findings


def scan_file(file_path: Path, patterns: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Escanea un archivo y retorna secretos detectados."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        log(f"No se pudo leer {file_path}: {e}", "WARN")
        return []
    return scan_text(content, patterns)


def scan_evidence_pack(pack: Dict[str, Any], patterns: Optional[List[Dict[str, Any]]] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Escanea y redacta secretos en un evidence pack completo.

    Escanea:
      - summary de cada item
      - raw_content si existe
      - agent_summary
      - cualquier string value en el pack

    Returns: (pack_redactado, findings)
    """
    if patterns is None:
        patterns = load_patterns()

    all_findings: List[Dict[str, Any]] = []
    pack_str = json.dumps(pack, default=str, ensure_ascii=False)

    # Escanear el pack completo como string
    redacted_str, findings = redact_text(pack_str, patterns)

    if findings:
        # Reconstruir el pack desde el string redactado
        try:
            redacted_pack = json.loads(redacted_str)
        except Exception:
            # Si falla el parse, redactar item por item
            redacted_pack = pack
            for item in redacted_pack.get("items", []):
                summary = item.get("summary", "")
                if summary:
                    redacted_summary, item_findings = redact_text(summary, patterns)
                    item["summary"] = redacted_summary
                    for f in item_findings:
                        f["item_id"] = item.get("id")
                        all_findings.append(f)
        else:
            redacted_pack = redacted_pack
            all_findings = findings
    else:
        redacted_pack = pack

    # Añadir metadata de redacción al pack
    if all_findings:
        redacted_pack["security_redaction"] = {
            "applied": True,
            "secrets_detected": len(all_findings),
            "patterns_matched": list(set(f["name"] for f in all_findings)),
            "redacted_at": now_iso(),
        }
        log(f"SECRET DETECTION: {len(all_findings)} secretos redactados del evidence pack", "WARN")

    return redacted_pack, all_findings


# ============================================================================
# Allowlist validator
# ============================================================================

def load_security_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Carga la configuración de seguridad."""
    if config_path is None:
        candidates = [
            Path.cwd() / "security_config.yaml",
            Path.cwd() / ".opencode" / "apolo-dynamic" / "security_config.yaml",
            Path(__file__).parent.parent.parent / "security_config.yaml",
        ]
        for c in candidates:
            if c.exists():
                config_path = c
                break

    if config_path and config_path.exists():
        return read_yaml(config_path) or {}
    return {}


def is_origin_allowed(url: str, config: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Verifica si una URL está en el allowlist de orígenes confiables.

    Returns: (allowed, reason)
    """
    if config is None:
        config = load_security_config()

    allowed_origins = config.get("allowed_origins", [])
    blocked_origins = config.get("blocked_origins", [])
    default_policy = config.get("default_policy", "deny")

    # 1. Verificar blocked_origins primero (denegación tiene prioridad)
    for blocked in blocked_origins:
        pattern = blocked.get("pattern", "")
        if _match_pattern(url, pattern):
            return False, f"BLOQUEADO: {blocked.get('description', pattern)}"

    # 2. Verificar allowed_origins
    for allowed in allowed_origins:
        pattern = allowed.get("pattern", "")
        if _match_pattern(url, pattern):
            return True, f"Allowlisted: {allowed.get('description', pattern)} (trust: {allowed.get('trust_level', '?')})"

    # 3. Aplicar default_policy
    if default_policy == "allow":
        return True, "Permitido por default_policy=allow"
    else:
        return False, f"RECHAZADO: URL no está en allowlist (default_policy=deny)"


def _match_pattern(url: str, pattern: str) -> bool:
    """Matchea URL contra un patrón glob-like."""
    from fnmatch import fnmatch
    # Convertir patrón glob a regex si contiene *
    if "*" in pattern:
        return fnmatch(url, pattern) or fnmatch(url.lower(), pattern.lower())
    return pattern in url


# ============================================================================
# Hash chain validator
# ============================================================================

def compute_hash_chain_entry(entry: Dict[str, Any], previous_hash: str, algorithm: str = "sha256") -> str:
    """Computa el hash de una entrada del audit log incluyendo el hash anterior."""
    import hashlib
    # Crear copia sin el campo prev_hash (para que el hash sea determinista)
    entry_copy = {k: v for k, v in entry.items() if k not in ("prev_hash", "entry_hash")}
    entry_str = json.dumps(entry_copy, sort_keys=True, default=str)
    combined = f"{previous_hash}:{entry_str}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def verify_hash_chain(log_path: Path, genesis_seed: str = "APOLO-DYNAMIC-FLOW-GENESIS-V1") -> Tuple[bool, List[str]]:
    """Verifica que el hash chain del audit log sea válido.

    Returns: (valid, errors)
    """
    import hashlib

    if not log_path.exists():
        return True, []  # Log vacío es válido

    errors: List[str] = []
    prev_hash = hashlib.sha256(genesis_seed.encode("utf-8")).hexdigest()

    try:
        content = log_path.read_text(encoding="utf-8")
    except Exception as e:
        return False, [f"Error leyendo log: {e}"]

    for i, line in enumerate(content.strip().split("\n"), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"Línea {i}: JSON inválido: {e}")
            continue

        stored_prev_hash = entry.get("prev_hash")
        if stored_prev_hash is None:
            # Si no tiene prev_hash, es una entrada pre-v2.4.0 — skip
            continue

        # Verificar que el prev_hash coincide
        if stored_prev_hash != prev_hash:
            errors.append(f"Línea {i}: prev_hash no coincide (esperado {prev_hash[:16]}..., got {stored_prev_hash[:16]}...)")

        # Computar hash para la siguiente entrada
        prev_hash = compute_hash_chain_entry(entry, prev_hash)

    return len(errors) == 0, errors


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    scan_file_arg = args.get("scan-file", "")
    scan_stdin = args.get("scan-stdin", "") == "true"
    redact = args.get("redact", "") == "true"
    output = args.get("output", "")
    verify_chain = args.get("verify-chain", "")
    as_json = args.get("json", "") == "json"

    # Modo verify-chain
    if verify_chain:
        log_path = Path(verify_chain)
        valid, errors = verify_hash_chain(log_path)
        if as_json:
            print(json.dumps({"valid": valid, "errors": errors}, indent=2))
        else:
            if valid:
                log(f"Hash chain VÁLIDO: {log_path}", "INFO")
            else:
                log(f"Hash chain INVÁLIDO: {len(errors)} errores", "ERROR")
                for e in errors:
                    print(f"  - {e}", file=sys.stderr)
        return 0 if valid else 1

    # Modo scan-stdin
    if scan_stdin:
        text = sys.stdin.read()
        if redact:
            redacted, findings = redact_text(text)
            if output:
                Path(output).write_text(redacted, encoding="utf-8")
            else:
                print(redacted)
        else:
            findings = scan_text(text)
            print(json.dumps({"findings": findings, "count": len(findings)}, indent=2))
        return 0 if not findings else 1

    # Modo scan-file
    if scan_file_arg:
        file_path = Path(scan_file_arg)
        if not file_path.exists():
            log(f"Archivo no encontrado: {file_path}", "ERROR")
            return 2

        if redact:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            redacted, findings = redact_text(content)
            if output:
                Path(output).write_text(redacted, encoding="utf-8")
                log(f"Redactado: {len(findings)} secretos → {output}", "INFO")
            else:
                print(redacted)
        else:
            findings = scan_file(file_path)
            if as_json:
                print(json.dumps({"file": str(file_path), "findings": findings, "count": len(findings)}, indent=2))
            else:
                if findings:
                    log(f"DETECTADOS {len(findings)} secretos en {file_path}", "WARN")
                    for f in findings:
                        print(f"  Línea {f['line']}: [{f['name']}] {f['match']}")
                else:
                    log(f"Sin secretos detectados en {file_path}", "INFO")
        return 0 if not findings else 1

    log("Uso: --scan-file <path> | --scan-stdin | --verify-chain <log_path> [--redact] [--output <path>]", "ERROR")
    return 2


if __name__ == "__main__":
    sys.exit(main())
