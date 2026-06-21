"""
common.py — Utilidades Python compartidas por todos los scripts del plugin.

Sin dependencias externas (yaml, jsonschema son stdlib-friendly).
Para proyectos serios, instalar PyYAML y jsonschema y reemplazar los stubs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# Time
# ============================================================================

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def elapsed_ms(start_iso: str) -> int:
    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    except Exception:
        return 0


# ============================================================================
# Hashing
# ============================================================================

def sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hash_file(path) -> Optional[str]:
    p = Path(path) if not isinstance(path, Path) else path
    try:
        return sha256(p.read_bytes())
    except Exception:
        return None


def hash_chain(items: List[Dict[str, Any]]) -> str:
    concat = "".join(i.get("hash", "") for i in items)
    return sha256(concat)


# ============================================================================
# YAML (parser/serializer minimalista — sin PyYAML)
# ============================================================================

def yaml_dump(obj: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, (int, float)):
        return str(obj)
    if isinstance(obj, str):
        if re.search(r"[:#\[\]{}&*!|>'\"%@`]", obj) or "\n" in obj:
            return json.dumps(obj)
        return obj
    if isinstance(obj, list):
        if not obj:
            return "[]"
        out = []
        for item in obj:
            if isinstance(item, (dict, list)):
                inner = yaml_dump(item, indent + 1).lstrip()
                out.append(f"{pad}- {inner}")
            else:
                out.append(f"{pad}- {yaml_dump(item, indent + 1)}")
        return "\n".join(out)
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        out = []
        for k, v in obj.items():
            if v is None:
                out.append(f"{pad}{k}: null")
            elif isinstance(v, dict):
                if not v:
                    out.append(f"{pad}{k}: {{}}")
                else:
                    out.append(f"{pad}{k}:")
                    out.append(yaml_dump(v, indent + 1))
            elif isinstance(v, list):
                if not v:
                    out.append(f"{pad}{k}: []")
                else:
                    out.append(f"{pad}{k}:")
                    out.append(yaml_dump(v, indent + 1))
            else:
                out.append(f"{pad}{k}: {yaml_dump(v, indent)}")
        return "\n".join(out)
    return str(obj)


def yaml_load(text: str) -> Any:
    """Parser YAML mínimo. Soporta objetos, listas, scalars, anidados por indent.

    Reglas:
      - `key: value` → parent[key] = scalar
      - `key:` (vacío) → parent[key] será dict o list según el primer hijo
      - `- item` → append a la lista del padre
      - `- key: value` → append un dict con esa key
    """
    lines = text.split("\n")
    root: Any = {}
    # stack entry: (indent, node, parent_ref, key_in_parent_or_None)
    # Si key_in_parent es None, el node es la root o un item de lista.
    stack: List[Tuple[int, Any, Any, Optional[str]]] = [(-1, root, None, None)]

    def find_parent(indent: int) -> Tuple[Any, Any, Optional[str]]:
        """Pop stack hasta encontrar el padre correcto para esta indent.
        Retorna (parent_node, parent_owner, key_in_parent).
        parent_owner y key_in_parent sirven para reemplazar dict por list si hace falta.
        """
        while len(stack) > 1 and stack[-1][0] > indent:
            stack.pop()
        # Ahora stack[-1] es el padre. Pero si está al mismo indent, también hay que
        # ver si es sibling (mismo nivel) o hijo.
        if stack[-1][0] == indent and stack[-1][3] is not None:
            # Es un dict-value esperando hijos al mismo indent — ese es el padre
            pass
        elif stack[-1][0] >= indent:
            # Pop al mismo nivel (siblings)
            stack.pop()
        return (stack[-1][1], stack[-1][2], stack[-1][3])

    for raw in lines:
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        trimmed = line.strip()

        if trimmed.startswith("- "):
            value = trimmed[2:].strip()
            # Encontrar el padre: la lista contenedora
            # Pop stack hasta encontrar el nodo que contiene la lista
            while len(stack) > 1 and stack[-1][0] > indent:
                stack.pop()
            # El padre potencial es stack[-1][1]
            top_indent, top_node, top_owner, top_key = stack[-1]

            # Si el top es un dict con key pendiente (vacío), reemplazar por lista
            if (
                top_key is not None
                and isinstance(top_node, dict)
                and len(top_node) == 0
                and isinstance(top_owner, dict)
                and top_owner.get(top_key) is top_node
            ):
                top_owner[top_key] = []
                top_node = top_owner[top_key]
                stack[-1] = (top_indent, top_node, top_owner, top_key)
            # Si el top es un dict esperando sub-keys (no vacío), no es válido
            # para un `-`. Pop y reintentar con su padre.
            if isinstance(top_node, dict) and top_key is not None and top_node:
                # El `- ` está a la misma indent que una key previa, debería
                # haber sido inicializado como lista. Eso significa que el primer
                # hijo fue una sub-key, lo cual es un YAML inválido para nuestra
                # sintaxis. Lo mejor es pop y buscar arriba.
                stack.pop()
                top_indent, top_node, top_owner, top_key = stack[-1]
                if (
                    top_key is not None
                    and isinstance(top_owner, dict)
                    and isinstance(top_owner.get(top_key), list)
                ):
                    top_node = top_owner[top_key]
                    stack[-1] = (top_indent, top_node, top_owner, top_key)

            if not isinstance(top_node, list):
                # No hay lista contenedora — ignorar
                continue

            if ": " in value or value.endswith(":"):
                # Item tipo dict
                obj: Dict[str, Any] = {}
                # Procesar la primera sub-key dentro del item
                if ": " in value:
                    k, _, rest = value.partition(": ")
                    obj[k.strip()] = _parse_scalar(rest.strip())
                else:
                    # key: sin valor → sub-dict o sub-list
                    k = value[:-1].strip()
                    obj[k] = {}
                top_node.append(obj)
                # Las sub-keys del item estarán a indent + 2
                stack.append((indent + 2, obj, top_node, None))
                # Si la key quedó como dict vacío, marcar como pendiente
                if ": " not in value:
                    stack.append((indent + 4, obj[k], obj, k))
            else:
                top_node.append(_parse_scalar(value))
            continue

        # Línea tipo `key: value` o `key:`
        # Pop stack hasta encontrar dónde insertar
        while len(stack) > 1 and stack[-1][0] > indent:
            stack.pop()
        # Si el top está al mismo indent y es un dict-value, ya es el padre.
        # Si el top está a mayor indent (no debería tras el pop), seguimos.
        if stack[-1][0] > indent:
            # Caso raro — skip
            continue
        if stack[-1][0] == indent and stack[-1][3] is None and isinstance(stack[-1][1], dict):
            # Top es root o un dict al mismo nivel — OK
            parent = stack[-1][1]
        elif stack[-1][0] < indent:
            # Top es padre — necesitamos entrar en el último sub-dict
            # Esto pasa cuando la línea anterior era `key:` vacío
            parent = stack[-1][1]
        else:
            # Top al mismo indent y es dict — es el padre
            parent = stack[-1][1]

        if ": " in trimmed:
            key, _, value = trimmed.partition(": ")
            key = key.strip()
            value = value.strip()
            if value == "":
                # Sub-dict o sub-list — inicializar como dict vacío, se convierte
                # en lista si el primer hijo es `- `
                child: Dict[str, Any] = {}
                parent[key] = child
                stack.append((indent + 2, child, parent, key))
            elif value == "[]":
                parent[key] = []
            elif value == "{}":
                parent[key] = {}
            else:
                parent[key] = _parse_scalar(value)
        elif trimmed.endswith(":"):
            key = trimmed[:-1].strip()
            child = {}
            parent[key] = child
            stack.append((indent + 2, child, parent, key))
    return root


def _parse_scalar(raw: str) -> Any:
    if raw in ("null", "~", ""):
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    if (raw.startswith('"') and raw.endswith('"')) or (
        raw.startswith("'") and raw.endswith("'")
    ):
        return raw[1:-1]
    return raw


def read_yaml(path) -> Optional[Any]:
    p = Path(path) if not isinstance(path, Path) else path
    if not p.exists():
        return None
    try:
        return yaml_load(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] yaml_load falló en {p}: {e}", file=sys.stderr)
        return None


def write_yaml(path, data: Any) -> None:
    p = Path(path) if not isinstance(path, Path) else path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml_dump(data) + "\n", encoding="utf-8")


# ============================================================================
# JSON
# ============================================================================

def read_json(path) -> Optional[Any]:
    p = Path(path) if not isinstance(path, Path) else path
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path, data: Any) -> None:
    p = Path(path) if not isinstance(path, Path) else path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ============================================================================
# Subprocess
# ============================================================================

def run_cmd(
    cmd: List[str] | str,
    cwd: Optional[Path] = None,
    timeout: int = 60,
    capture: bool = True,
) -> Tuple[int, str, str]:
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
        return (
            result.returncode,
            result.stdout or "",
            result.stderr or "",
        )
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def cmd_available(cmd: str) -> bool:
    code, _, _ = run_cmd(f"command -v {cmd} >/dev/null 2>&1", timeout=5)
    return code == 0


# ============================================================================
# Capability detection
# ============================================================================

def detect_capabilities() -> Dict[str, str]:
    caps = {
        "playwright": "unavailable",
        "lsp": "unavailable",
        "git": "unavailable",
        "python": "available",  # nosotros somos Python
        "node": "unavailable",
        "curl": "unavailable",
        "psql": "unavailable",
    }
    if cmd_available("git"):
        caps["git"] = "available"
    if cmd_available("node"):
        caps["node"] = "available"
    if cmd_available("curl"):
        caps["curl"] = "available"
    if cmd_available("psql"):
        caps["psql"] = "available"
    # LSP: asumimos disponible si hay typescript-language-server o gopls
    if cmd_available("typescript-language-server") or cmd_available("gopsl") or cmd_available("gopls"):
        caps["lsp"] = "available"
    # Playwright: chequear node_modules
    try:
        result = subprocess.run(
            ["node", "-e", "require.resolve('@playwright/test')"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            caps["playwright"] = "available"
    except Exception:
        pass
    return caps


# ============================================================================
# IDs
# ============================================================================

def gen_uuid() -> str:
    return str(uuid.uuid4())


def gen_run_id() -> str:
    return f"run-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def gen_evidence_id(index: int) -> str:
    return f"E-{str(index).zfill(3)}"


def gen_block_id(existing: List[Dict[str, Any]]) -> str:
    next_n = len(existing) + 1
    return f"BLOQUEO-{str(next_n).zfill(3)}"


# ============================================================================
# Flow paths
# ============================================================================

def flow_dir(repo_root: Path, flowid: str) -> Path:
    return repo_root / "plan" / "active" / flowid


def evidence_path(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml"


def state_path(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "FLOW-STATE.yaml"


def blocks_path(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "BLOCK-LOG.yaml"


def telemetry_path(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "telemetry.jsonl"


def tool_registry_path(repo_root: Path) -> Path:
    return repo_root / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml"


# ============================================================================
# Schema validation (mínima — sin jsonschema)
# ============================================================================

def validate_required(data: Dict[str, Any], required: List[str], path: str = "") -> List[str]:
    errors: List[str] = []
    for key in required:
        if key not in data:
            errors.append(f"{path}.{key}: campo requerido faltante")
        elif data[key] is None:
            errors.append(f"{path}.{key}: es null")
    return errors


def validate_enum(value: Any, allowed: List[str], path: str) -> List[str]:
    if value is None:
        return []
    if value not in allowed:
        return [f"{path}: valor '{value}' no está en {allowed}"]
    return []


def validate_pattern(value: str, pattern: str, path: str) -> List[str]:
    if value is None:
        return []
    if not re.fullmatch(pattern, value):
        return [f"{path}: valor '{value}' no cumple {pattern}"]
    return []


# ============================================================================
# CLI args
# ============================================================================

def parse_args(argv: List[str]) -> Dict[str, str]:
    """Parser simple: --key value o --flag."""
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


def log(msg: str, level: str = "INFO") -> None:
    print(f"[{level}] {msg}", file=sys.stderr)


# ============================================================================
# Git helpers
# ============================================================================

def git_diff(repo_root: Path, ref: str = "HEAD") -> Optional[str]:
    code, out, _ = run_cmd(["git", "diff", ref], cwd=repo_root, timeout=30)
    return out if code == 0 else None


def git_log(repo_root: Path, n: int = 20) -> Optional[str]:
    code, out, _ = run_cmd(
        ["git", "log", f"-{n}", "--pretty=format:%H|%an|%ad|%s"],
        cwd=repo_root,
        timeout=30,
    )
    return out if code == 0 else None


def git_status(repo_root: Path) -> Optional[str]:
    code, out, _ = run_cmd(["git", "status", "--porcelain"], cwd=repo_root, timeout=10)
    return out if code == 0 else None


def git_head_sha(repo_root: Path) -> Optional[str]:
    code, out, _ = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root, timeout=5)
    return out.strip() if code == 0 else None


# ============================================================================
# File helpers
# ============================================================================

def list_files(repo_root: Path, patterns: List[str]) -> List[Path]:
    """Lista archivos que matchean alguno de los patrones (glob)."""
    results: List[Path] = []
    for pattern in patterns:
        if pattern.startswith("/"):
            pattern = pattern[1:]
        for p in repo_root.glob(pattern):
            if p.is_file():
                results.append(p)
    return results


def read_file_summary(path, max_chars: int = 300) -> str:
    p = Path(path) if not isinstance(path, Path) else path
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"(error leyendo: {e})"
    # Tomar primeras líneas relevantes
    lines = text.split("\n")
    summary_lines = [l for l in lines[:30] if l.strip() and not l.strip().startswith("//")]
    summary = " | ".join(summary_lines)[:max_chars]
    return summary


def extract_symbols_go(path: Path) -> List[str]:
    """Extrae nombres de funciones/structs/interfaces de un .go."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    symbols = re.findall(
        r"^(func|type)\s+(\([^)]+\)\s+)?(\w+)", text, re.MULTILINE
    )
    return [s[2] for s in symbols if s[2]]


def extract_symbols_ts(path: Path) -> List[str]:
    """Extrae nombres de funciones/clases/interfaces de un .ts."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    symbols = re.findall(
        r"^\s*(export\s+)?(function|class|interface|const|type)\s+(\w+)",
        text,
        re.MULTILINE,
    )
    return [s[2] for s in symbols if s[2]]


def extract_symbols_py(path: Path) -> List[str]:
    """Extrae nombres de funciones/clases de un .py."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    symbols = re.findall(
        r"^\s*(def|class)\s+(\w+)", text, re.MULTILINE
    )
    return [s[1] for s in symbols if s[1]]


def extract_symbols(path: Path) -> List[str]:
    suffix = path.suffix.lower()
    if suffix == ".go":
        return extract_symbols_go(path)
    if suffix in (".ts", ".tsx", ".js", ".jsx"):
        return extract_symbols_ts(path)
    if suffix == ".py":
        return extract_symbols_py(path)
    return []
