# APOLO Dynamic Flow

> **Plugin de orquestación de agentes para OpenCode** con flujos dinámicos, recolección determinista de evidencia, planes generados por Python, tests automáticos tras cada cambio y absorción de tools externas.

[![Tests](https://img.shields.io/badge/tests-37%2F37%20passing-brightgreen)](#10-tests)
[![License](https://img.shields.io/badge/license-MIT-blue)](#licencia)
[![Node](https://img.shields.io/badge/node-%E2%89%A518-green)](#prerrequisitos)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](#prerrequisitos)

## Tabla de contenidos

1. [Qué es este plugin](#1-qué-es-este-plugin)
2. [Prerrequisitos](#2-prerrequisitos)
3. [Instalación](#3-instalación)
4. [Verificación](#4-verificación-de-la-instalación)
5. [Integración con OpenCode](#5-integración-con-opencode)
6. [Estructura](#6-estructura-completa-del-plugin)
7. [CLI apolo-inspect](#7-uso-del-cli-apolo-inspectsh)
8. [Panel de telemetría](#8-panel-de-telemetría)
9. [Configuración](#9-configuración-avanzada)
10. [Tests](#10-tests)
11. [Troubleshooting](#11-troubleshooting)
12. [Cómo funciona](#12-cómo-funciona-internamente)
13. [Docs adicionales](#13-documentación-adicional)
14. [Licencia](#licencia)

## 1. Qué es este plugin

Plugin TypeScript para OpenCode que **reemplaza a `apolo-flow-guardian.ts`**. Orquesta agentes con:

- **State machine explícita** con transiciones legales y gates por fase.
- **Loop dinámico con circuit breaker adaptativo** — cada fase tiene `max` iteraciones.
- **Recolección determinista de evidencia** — scripts Python capturan archivos, git diff, símbolos, endpoints, DB queries, screenshots.
- **Planes generados por Python** — `generate_plan.py` lee evidence + verdad y produce `DYNAMIC-PLAN.yaml` con topological sort.
- **Tests automáticos tras cada cambio** — rollback automático vía `git restore` si falla.
- **Absorción automática de tools externas** — MCPs, skills, plugins, scripts.
- **Telemetría append-only** + panel HTML.
- **Routing declarativo** — `routing-rules.json` con 10 reglas editables sin código.
- **Árbol de decisión D-NNN** — circuit breaker por patrón de fallos.
- **Tests TypeScript ejecutables** — 32 tests con `node --test`.

## 2. Prerrequisitos

| Herramienta | Versión mínima | Verificar | Instalar |
|---|---|---|---|
| Node.js | 18.0.0 | `node --version` | `sudo apt install -y nodejs` |
| npm | 9.0.0 | `npm --version` | `sudo apt install -y npm` |
| Python 3 | 3.10 | `python3 --version` | `sudo apt install -y python3` |
| curl | cualquiera | `curl --version` | `sudo apt install -y curl` |
| git | cualquiera | `git --version` | `sudo apt install -y git` |

Dependencias opcionales (auto-instaladas por `install.sh`):

- **PyYAML** — `pip3 install --user PyYAML`
- **jsonschema** — `pip3 install --user jsonschema`
- **playwright** — `npx playwright install chromium`

## 3. Instalación

### Método A — `install.sh` (recomendado)

```bash
git clone https://github.com/juancspjr/apolo-dynamic-flow.git
cd apolo-dynamic-flow
./install.sh
