#!/usr/bin/env python3
"""
absorb_external_skills.py — Absorbedor de skills externas desde URLs y repos.

PERMITE absorber skills de:
  1. GitHub repos (raw URLs o releases)
  2. Páginas especializadas con skills públicas (ej: awesome-opencode, skill-hubs)
  3. Gists
  4. URLs directas a archivos .md, .yaml, .py, .ts

Diferencia con absorb_mcp.py (que solo descubre lo local):
este script DESCARGA skills desde internet, las valida, y las registra
en .opencode/skills/ + TOOL-REGISTRY.yaml.

Fuentes soportadas:
  - github://owner/repo/path/to/SKILL.md
  - github-raw://owner/repo/branch/path/to/file
  - https://raw.githubusercontent.com/owner/repo/branch/path
  - https://gist.githubusercontent.com/user/id/raw
  - https://example.com/skills/my-skill.md
  - local://path/to/skill.md (copia desde path local)

Modos:
  --source <url>          Absorbe una sola skill
  --sources-file <file>   Absorbe múltiples desde un archivo (una URL por línea)
  --hub <name>            Absorbe desde un hub conocido (awesome-opencode, koderspa, etc.)

Uso:
  python3 absorb_external_skills.py \\
    --repo-root /path \\
    --source github://juancspjr/apolo-dynamic-flow/skills/my-skill/SKILL.md

  python3 absorb_external_skills.py \\
    --repo-root /path \\
    --sources-file skills-to-absorb.txt

  python3 absorb_external_skills.py \\
    --repo-root /path \\
    --hub awesome-opencode
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    cmd_available,
    gen_uuid,
    log,
    now_iso,
    parse_args,
    read_yaml,
    run_cmd,
    sha256,
    write_yaml,
)


# ============================================================================
# Hubs conocidos
# ============================================================================

KNOWN_HUBS: Dict[str, Dict[str, Any]] = {
    "awesome-opencode": {
        "description": "Repositorio curado de skills para OpenCode",
        "type": "github-tree",
        "owner": "opencode-ai",
        "repo": "awesome-opencode",
        "path": "skills",
        "branch": "main",
    },
    "koderspa-skills": {
        "description": "Skills de @koderspa/mcp-skills",
        "type": "npm-package",
        "package": "@koderspa/mcp-skills",
    },
    "apolo-loop-engine": {
        "description": "Skills de referencia de apolo-loop-engine",
        "type": "github-tree",
        "owner": "juancspjr",
        "repo": "apolo-loop-engine",
        "path": "skills",
        "branch": "main",
    },
}


# ============================================================================
# URL parsers
# ============================================================================

def parse_source_url(source: str) -> Dict[str, Any]:
    """Parsea una URL de source y devuelve metadata estandarizada."""
    # github://owner/repo/path
    if source.startswith("github://"):
        parts = source[9:].split("/", 2)
        if len(parts) < 3:
            return {"valid": False, "error": "format: github://owner/repo/path"}
        owner, repo, path = parts
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{path}"
        return {
            "valid": True,
            "type": "github-raw",
            "url": url,
            "owner": owner,
            "repo": repo,
            "path": path,
            "name": Path(path).stem,
        }

    # github-raw://owner/repo/branch/path
    if source.startswith("github-raw://"):
        parts = source[13:].split("/", 3)
        if len(parts) < 4:
            return {"valid": False, "error": "format: github-raw://owner/repo/branch/path"}
        owner, repo, branch, path = parts
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        return {
            "valid": True,
            "type": "github-raw",
            "url": url,
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "path": path,
            "name": Path(path).stem,
        }

    # local://path
    if source.startswith("local://"):
        path = source[8:]
        return {
            "valid": True,
            "type": "local",
            "path": path,
            "name": Path(path).stem,
        }

    # https://... (URL directa)
    if source.startswith("https://") or source.startswith("http://"):
        parsed = urlparse(source)
        # Detectar GitHub raw
        if "raw.githubusercontent.com" in parsed.netloc:
            parts = parsed.path.strip("/").split("/", 4)
            if len(parts) >= 5:
                owner, repo, branch, path = parts[0], parts[1], parts[2], "/".join(parts[3:])
                return {
                    "valid": True,
                    "type": "github-raw",
                    "url": source,
                    "owner": owner,
                    "repo": repo,
                    "branch": branch,
                    "path": path,
                    "name": Path(path).stem,
                }
        # Gist
        if "gist.githubusercontent.com" in parsed.netloc:
            return {
                "valid": True,
                "type": "gist",
                "url": source,
                "name": Path(parsed.path).stem,
            }
        # URL genérica
        return {
            "valid": True,
            "type": "url",
            "url": source,
            "name": Path(parsed.path).stem or "external-skill",
        }

    return {"valid": False, "error": f"unknown source format: {source}"}


# ============================================================================
# Fetchers
# ============================================================================

def fetch_url(url: str, timeout: int = 30) -> Tuple[bool, str, str]:
    """Descarga una URL con curl. Retorna (success, content, error)."""
    if not cmd_available("curl"):
        return False, "", "curl no disponible"
    code, out, err = run_cmd(
        ["curl", "-sSL", "--fail", "--max-time", str(timeout), url],
        timeout=timeout + 5,
    )
    if code == 0:
        return True, out, ""
    return False, "", f"curl exit={code}: {err[:200]}"


def fetch_github_tree(
    owner: str, repo: str, path: str, branch: str = "main"
) -> Tuple[bool, List[Dict[str, Any]], str]:
    """Lista archivos en un path de un repo de GitHub via API."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    ok, content, err = fetch_url(api_url)
    if not ok:
        return False, [], f"github API: {err}"
    try:
        data = json.loads(content)
        if isinstance(data, list):
            files = [
                {
                    "name": item["name"],
                    "path": item["path"],
                    "type": item["type"],
                    "download_url": item.get("download_url"),
                    "size": item.get("size", 0),
                }
                for item in data
                if item.get("type") in ("file", "dir")
            ]
            return True, files, ""
        else:
            return False, [], f"github API returned non-list: {data.get('message', '?')}"
    except Exception as e:
        return False, [], f"parse error: {e}"


def fetch_local(path: str) -> Tuple[bool, str, str]:
    """Lee un archivo local."""
    p = Path(path)
    if not p.exists():
        return False, "", f"file not found: {path}"
    try:
        return True, p.read_text(encoding="utf-8"), ""
    except Exception as e:
        return False, "", str(e)


# ============================================================================
# Skill validator
# ============================================================================

def validate_skill_content(content: str, filename: str) -> Dict[str, Any]:
    """Valida que el contenido tenga la estructura mínima de una skill."""
    issues: List[str] = []
    warnings: List[str] = []

    # Determinar tipo por extensión
    suffix = Path(filename).suffix.lower()

    if suffix == ".md":
        # SKILL.md: debe tener título y descripción
        if not content.startswith("#"):
            issues.append("SKILL.md debe empezar con # título")
        if "##" not in content:
            warnings.append("SKILL.md sin secciones ## (recomendado)")
        if len(content) < 100:
            warnings.append("SKILL.md muy corto (<100 chars)")
    elif suffix == ".py":
        # Script Python: debe compilar
        try:
            compile(content, filename, "exec")
        except SyntaxError as e:
            issues.append(f"Python syntax error: {e}")
    elif suffix == ".ts":
        # TypeScript: debe tener al menos un export o function
        if not re.search(r"(export|function|class|interface)\s", content):
            warnings.append("TS sin exports/functions/classes")
    elif suffix in (".yaml", ".yml"):
        # YAML: mínimo viable
        if ":" not in content:
            issues.append("YAML sin ningún ':'")
    elif suffix == ".json":
        try:
            json.loads(content)
        except Exception as e:
            issues.append(f"JSON inválido: {e}")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "size": len(content),
        "hash": sha256(content),
    }


def infer_skill_capabilities(name: str, content: str) -> List[str]:
    """Infiere capabilities de una skill por nombre + contenido."""
    lower = name.lower()
    caps: List[str] = []
    if "evidence" in lower or "capture" in lower:
        caps.extend(["capture", "evidence"])
    if "compare" in lower:
        caps.extend(["compare", "evidence"])
    if "plan" in lower:
        caps.extend(["plan", "shape"])
    if "test" in lower:
        caps.append("test")
    if "audit" in lower or "truth" in lower:
        caps.append("audit")
    if "frontend" in lower or "ui" in lower:
        caps.append("frontend")
    if "backend" in lower:
        caps.append("backend")
    if "security" in lower:
        caps.append("security")
    if "debug" in lower:
        caps.append("debug")
    if "edit" in lower:
        caps.extend(["edit", "read"])
    if "deploy" in lower or "ship" in lower:
        caps.append("deploy")
    if "research" in lower:
        caps.append("research")
    if "review" in lower:
        caps.append("review")
    if "build" in lower:
        caps.append("build")
    if "verify" in lower or "validate" in lower:
        caps.append("validate")
    if "design" in lower:
        caps.append("design")
    if "learn" in lower:
        caps.append("learn")
    if "optimize" in lower:
        caps.append("optimize")

    # También inferir del contenido
    content_lower = content.lower()
    if "playwright" in content_lower:
        caps.append("browser")
    if "curl" in content_lower:
        caps.append("http")
    if "git" in content_lower:
        caps.append("git")
    if "docker" in content_lower:
        caps.append("docker")
    if "sql" in content_lower or "psql" in content_lower:
        caps.append("db")

    return list(set(caps)) if caps else ["unknown"]


# ============================================================================
# Skill installer
# ============================================================================

def install_skill(
    name: str,
    content: str,
    source_url: str,
    repo_root: Path,
    target_subdir: Optional[str] = None,
) -> Dict[str, Any]:
    """Instala una skill en .opencode/skills/<name>/ o ruta personalizada."""
    # Determinar ruta destino
    if target_subdir:
        dest_dir = repo_root / ".opencode" / "skills" / target_subdir
    else:
        dest_dir = repo_root / ".opencode" / "skills" / name

    dest_dir.mkdir(parents=True, exist_ok=True)

    # Determinar nombre de archivo
    # Si es SKILL.md, usar SKILL.md; si no, usar el nombre + extensión inferida
    if "<SKILL" in content[:200] or content.startswith("#"):
        dest_file = dest_dir / "SKILL.md"
    else:
        # Usar extensión del source si es detectable
        if source_url.endswith(".py"):
            dest_file = dest_dir / f"{name}.py"
        elif source_url.endswith(".ts"):
            dest_file = dest_dir / f"{name}.ts"
        elif source_url.endswith((".yaml", ".yml")):
            dest_file = dest_dir / f"{name}.yaml"
        elif source_url.endswith(".json"):
            dest_file = dest_dir / f"{name}.json"
        else:
            dest_file = dest_dir / "SKILL.md"

    # Validar contenido
    validation = validate_skill_content(content, dest_file.name)
    if not validation["valid"]:
        return {
            "success": False,
            "name": name,
            "error": f"validation failed: {validation['issues']}",
        }

    # Escribir archivo
    dest_file.write_text(content, encoding="utf-8")

    # Inferir capabilities
    caps = infer_skill_capabilities(name, content)

    # Registrar en TOOL-REGISTRY.yaml
    reg_path = repo_root / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml"
    reg = read_yaml(reg_path) or {
        "toolregistry": "V2",
        "version": 0,
        "updated_at": now_iso(),
        "tools": [],
        "conflicts": [],
    }

    tool_id = f"skill:external/{name}"
    # Verificar si ya existe
    existing = next((t for t in reg.get("tools", []) if t.get("id") == tool_id), None)
    if existing:
        # Actualizar
        existing["source"] = str(dest_file)
        existing["status"] = "active"
        existing["last_verified_at"] = now_iso()
        existing["capabilities"] = caps
        existing["hash"] = validation["hash"]
        action = "updated"
    else:
        # Añadir
        reg.setdefault("tools", []).append({
            "id": tool_id,
            "source": str(dest_file),
            "kind": "skill",
            "name": name,
            "status": "active",
            "registered_at": now_iso(),
            "last_verified_at": now_iso(),
            "capabilities": caps,
            "invoke": {
                "method": "ts-function",
                "target": f"loadSkill({name})",
            },
            "health_check": {
                "command": f"test -f {dest_file}",
                "expected_exit": 0,
                "interval_seconds": 600,
            },
            "hash": validation["hash"],
            "external_url": source_url,
        })
        action = "added"

    reg["version"] = int(reg.get("version", 0)) + 1
    reg["updated_at"] = now_iso()
    write_yaml(reg_path, reg)

    return {
        "success": True,
        "name": name,
        "action": action,
        "path": str(dest_file),
        "capabilities": caps,
        "size": validation["size"],
        "hash": validation["hash"],
        "warnings": validation["warnings"],
    }


# ============================================================================
# Source processors
# ============================================================================

def process_source(source: str, repo_root: Path) -> Dict[str, Any]:
    """Procesa una source URL y la instala como skill."""
    parsed = parse_source_url(source)
    if not parsed.get("valid"):
        return {"success": False, "source": source, "error": parsed.get("error")}

    log(f"Procesando source: {source}", "INFO")

    # GitHub raw / URL directa / Gist
    if parsed["type"] in ("github-raw", "url", "gist"):
        ok, content, err = fetch_url(parsed["url"])
        if not ok:
            return {"success": False, "source": source, "error": err}
        return install_skill(parsed["name"], content, parsed["url"], repo_root)

    # Local file
    elif parsed["type"] == "local":
        ok, content, err = fetch_local(parsed["path"])
        if not ok:
            return {"success": False, "source": source, "error": err}
        return install_skill(parsed["name"], content, f"local://{parsed['path']}", repo_root)

    return {"success": False, "source": source, "error": f"unsupported type: {parsed['type']}"}


def process_hub(hub_name: str, repo_root: Path) -> Dict[str, Any]:
    """Procesa un hub conocido y absorbe todas sus skills."""
    hub = KNOWN_HUBS.get(hub_name)
    if not hub:
        return {"success": False, "hub": hub_name, "error": "unknown hub"}

    log(f"Absorbiendo hub: {hub_name} ({hub['description']})", "INFO")

    if hub["type"] == "github-tree":
        ok, files, err = fetch_github_tree(
            hub["owner"], hub["repo"], hub["path"], hub.get("branch", "main")
        )
        if not ok:
            return {"success": False, "hub": hub_name, "error": err}

        results: List[Dict[str, Any]] = []
        for f in files:
            if f["type"] == "file" and f["download_url"]:
                # Solo procesar archivos .md, .py, .ts, .yaml
                if not any(f["name"].endswith(ext) for ext in (".md", ".py", ".ts", ".yaml", ".yml")):
                    continue
                log(f"  Descargando: {f['name']}", "INFO")
                ok, content, err = fetch_url(f["download_url"])
                if ok:
                    result = install_skill(
                        Path(f["name"]).stem,
                        content,
                        f["download_url"],
                        repo_root,
                        target_subdir=hub_name,
                    )
                    result["source_file"] = f["name"]
                    results.append(result)
                else:
                    results.append({
                        "success": False,
                        "source": f["download_url"],
                        "error": err,
                    })

        success_count = sum(1 for r in results if r.get("success"))
        return {
            "success": True,
            "hub": hub_name,
            "total_files": len(files),
            "processed": len(results),
            "succeeded": success_count,
            "failed": len(results) - success_count,
            "results": results,
        }

    elif hub["type"] == "npm-package":
        return {
            "success": False,
            "hub": hub_name,
            "error": "npm-package hubs deben absorberse via absorb_mcp.py",
        }

    return {"success": False, "hub": hub_name, "error": "unsupported hub type"}


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    source = args.get("source", "")
    sources_file = args.get("sources-file", "")
    hub = args.get("hub", "")

    if not source and not sources_file and not hub:
        log("Uso: --source <url> | --sources-file <file> | --hub <name>", "ERROR")
        log("Hubs conocidos: " + ", ".join(KNOWN_HUBS.keys()), "ERROR")
        return 2

    start = time.time()

    # Asegurar que existe .opencode/apolo-dynamic/
    (repo_root / ".opencode" / "apolo-dynamic").mkdir(parents=True, exist_ok=True)
    (repo_root / ".opencode" / "skills").mkdir(parents=True, exist_ok=True)

    all_results: List[Dict[str, Any]] = []

    # Procesar hub
    if hub:
        result = process_hub(hub, repo_root)
        all_results.append(result)

    # Procesar source única
    if source:
        result = process_source(source, repo_root)
        all_results.append(result)

    # Procesar sources file
    if sources_file:
        sources_path = Path(sources_file)
        if not sources_path.exists():
            log(f"Sources file no encontrado: {sources_file}", "ERROR")
            return 2
        for line in sources_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            result = process_source(line, repo_root)
            all_results.append(result)

    duration_ms = int((time.time() - start) * 1000)

    # Resumen
    success_count = sum(1 for r in all_results if r.get("success"))
    fail_count = len(all_results) - success_count

    summary = {
        "absorbexternalskills": "V1",
        "version": 1,
        "generated_at": now_iso(),
        "duration_ms": duration_ms,
        "total_sources": len(all_results),
        "succeeded": success_count,
        "failed": fail_count,
        "results": all_results,
    }

    print(json.dumps(summary, indent=2, default=str, ensure_ascii=False))

    log(
        f"Absorción externa: {success_count}/{len(all_results)} OK, "
        f"{fail_count} failed, {duration_ms}ms",
        "INFO" if fail_count == 0 else "WARN",
    )

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
