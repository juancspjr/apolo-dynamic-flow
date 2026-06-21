#!/usr/bin/env python3
"""
install_deps.py — Auto-instalador de dependencias (v2.6.2).

Detecta e instala automáticamente las dependencias necesarias para que
el plugin funcione al 100%. Usa pip3 con --break-system-packages si es
necesario (PEP 668 en Ubuntu 24.04+).

Uso:
  python3 scripts/python/install_deps.py
  python3 scripts/python/install_deps.py --check
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

HARD_DEPS = {
    "PyYAML": {"import_name": "yaml", "min_version": "6.0"},
    "jsonschema": {"import_name": "jsonschema", "min_version": "4.0"},
}

OPTIONAL_DEPS = {
    "bandit": {"import_name": "bandit", "purpose": "Análisis de seguridad Python"},
    "radon": {"import_name": "radon", "purpose": "Complejidad ciclomática Python"},
    "coverage": {"import_name": "coverage", "purpose": "Coverage de tests Python"},
    "pytest": {"import_name": "pytest", "purpose": "Runner de tests Python"},
}


def check_dep(import_name):
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False


def install_package(package):
    # Intentar pip install --user primero
    cmd = [sys.executable, "-m", "pip", "install", "--user", "--quiet", package]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        return True
    # Si falla por PEP 668, intentar con --break-system-packages
    if "externally-managed-environment" in result.stderr or "break-system-packages" in result.stderr:
        cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages", "--quiet", package]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result.returncode == 0
    return False


def main():
    check_only = "--check" in sys.argv
    
    print("=== Verificación de dependencias ===\n")
    
    # Hard deps
    print("Dependencias OBLIGATORIAS:")
    all_ok = True
    for pkg, info in HARD_DEPS.items():
        installed = check_dep(info["import_name"])
        status = "✓" if installed else "✗"
        print(f"  {status} {pkg} ({info['import_name']})")
        if not installed:
            if check_only:
                print(f"    → Instalar con: pip3 install {pkg}")
                all_ok = False
            else:
                print(f"    → Instalando {pkg}...")
                if install_package(pkg):
                    print(f"    ✓ {pkg} instalado")
                else:
                    print(f"    ✗ No se pudo instalar {pkg}")
                    all_ok = False
    
    # Optional deps
    print("\nDependencias OPCIONALES:")
    for pkg, info in OPTIONAL_DEPS.items():
        installed = check_dep(info["import_name"])
        status = "✓" if installed else "○"
        print(f"  {status} {pkg} — {info['purpose']}")
        if not installed and not check_only:
            print(f"    → Instalando {pkg}...")
            if install_package(pkg):
                print(f"    ✓ {pkg} instalado")
            else:
                print(f"    ○ {pkg} no disponible (degradación graceful)")
    
    print()
    if all_ok:
        print("✅ Todas las dependencias obligatorias están instaladas")
        return 0
    else:
        print("❌ Faltan dependencias obligatorias")
        return 1


if __name__ == "__main__":
    sys.exit(main())
