#!/usr/bin/env python3
"""
user_input_collector.py — Pausa para input del usuario (v3.2.0).

RESPONDE a la intencion del usuario:
  "solo se para cuando requiere informacion del usuario"

Cuando el orquestador encuentra una ambiguedad o decision que requiere
input humano, pausa y genera un QUESTION.yaml con:
  - question_id: identificador unico
  - question: la pregunta en lenguaje natural
  - context: informacion relevante para responder
  - options: opciones predefinidas (si aplica)
  - default: valor por defecto si el usuario no responde
  - timeout_seconds: tiempo maximo antes de usar default

El usuario responde via:
  - CLI: python3 user_input_collector.py answer --flowid X --question-id Q1 --answer "..."
  - Archivo: escribir la respuesta en ANSWERS/<question_id>.txt
  - Auto-yes: el sistema usa el default automaticamente (--yes flag en orquestador)

CLI:
  # El orquestador genera una pregunta
  python3 user_input_collector.py ask \\
      --flowid APOLO-X \\
      --question "Que archivos quieres incluir en el scope?" \\
      --context "El codebase tiene 50 archivos TS" \\
      --options '["plugin/","src/","tests/"]' \\
      --default "plugin/"

  # El usuario responde
  python3 user_input_collector.py answer \\
      --flowid APOLO-X \\
      --question-id Q-001 \\
      --answer "plugin/"

  # Ver preguntas pendientes
  python3 user_input_collector.py pending --flowid APOLO-X

  # Ver historial de Q&A
  python3 user_input_collector.py history --flowid APOLO-X
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir


def questions_dir(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "questions"


def answers_dir(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "answers"


def ask_question(
    repo_root: Path,
    flowid: str,
    question: str,
    context: str = "",
    options: List[str] = None,
    default: str = "",
    timeout_seconds: int = 300,
    question_type: str = "choice",  # choice | text | confirm
) -> Dict[str, Any]:
    """Genera una pregunta para el usuario."""
    q_dir = questions_dir(repo_root, flowid)
    q_dir.mkdir(parents=True, exist_ok=True)

    question_id = f"Q-{uuid.uuid4().hex[:8]}"
    asked_at = now_iso()

    q_data = {
        "question_id": question_id,
        "flowid": flowid,
        "asked_at": asked_at,
        "question": question,
        "context": context,
        "options": options or [],
        "default": default,
        "timeout_seconds": timeout_seconds,
        "type": question_type,
        "status": "pending",
    }

    q_path = q_dir / f"{question_id}.yaml"
    write_yaml(q_path, q_data)

    log(f"Pregunta generada: {question_id}", "INFO")
    log(f"  Q: {question}", "INFO")
    if options:
        log(f"  Options: {options}", "INFO")
    if default:
        log(f"  Default: {default}", "INFO")

    return {
        "success": True,
        "question_id": question_id,
        "question": question,
        "path": str(q_path),
        "message": f"Pregunta {question_id} pendiente — responder con: user_input_collector.py answer --flowid {flowid} --question-id {question_id} --answer '...'",
    }


def answer_question(
    repo_root: Path,
    flowid: str,
    question_id: str,
    answer: str,
) -> Dict[str, Any]:
    """Registra la respuesta del usuario a una pregunta."""
    q_path = questions_dir(repo_root, flowid) / f"{question_id}.yaml"
    if not q_path.exists():
        return {"success": False, "error": f"Pregunta {question_id} no encontrada"}

    q_data = read_yaml(q_path) or {}

    # Validar answer si es choice
    if q_data.get("type") == "choice" and q_data.get("options"):
        if answer not in q_data["options"]:
            return {
                "success": False,
                "error": f"Answer '{answer}' no esta en options: {q_data['options']}",
            }

    # Guardar respuesta
    a_dir = answers_dir(repo_root, flowid)
    a_dir.mkdir(parents=True, exist_ok=True)

    a_data = {
        "question_id": question_id,
        "flowid": flowid,
        "question": q_data.get("question", ""),
        "answer": answer,
        "answered_at": now_iso(),
        "asked_at": q_data.get("asked_at", ""),
    }

    a_path = a_dir / f"{question_id}.yaml"
    write_yaml(a_path, a_data)

    # Marcar pregunta como respondida
    q_data["status"] = "answered"
    q_data["answer"] = answer
    q_data["answered_at"] = now_iso()
    write_yaml(q_path, q_data)

    log(f"Pregunta {question_id} respondida: {answer}", "INFO")

    return {
        "success": True,
        "question_id": question_id,
        "answer": answer,
        "path": str(a_path),
    }


def get_pending_questions(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Lista preguntas pendientes (sin responder)."""
    q_dir = questions_dir(repo_root, flowid)
    if not q_dir.exists():
        return {"success": True, "pending": [], "total": 0}

    pending = []
    for q_file in q_dir.glob("Q-*.yaml"):
        q_data = read_yaml(q_file) or {}
        if q_data.get("status") == "pending":
            pending.append({
                "question_id": q_data.get("question_id"),
                "question": q_data.get("question"),
                "options": q_data.get("options", []),
                "default": q_data.get("default", ""),
                "asked_at": q_data.get("asked_at"),
            })

    return {"success": True, "pending": pending, "total": len(pending)}


def get_history(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Historial de preguntas y respuestas."""
    a_dir = answers_dir(repo_root, flowid)
    if not a_dir.exists():
        return {"success": True, "history": [], "total": 0}

    history = []
    for a_file in sorted(a_dir.glob("Q-*.yaml")):
        a_data = read_yaml(a_file) or {}
        history.append(a_data)

    return {"success": True, "history": history, "total": len(history)}


def check_answer(repo_root: Path, flowid: str, question_id: str) -> Optional[str]:
    """Verifica si una pregunta tiene respuesta. Retorna el answer o None."""
    a_path = answers_dir(repo_root, flowid) / f"{question_id}.yaml"
    if not a_path.exists():
        return None
    a_data = read_yaml(a_path) or {}
    return a_data.get("answer")


def wait_for_answer(
    repo_root: Path,
    flowid: str,
    question_id: str,
    timeout_seconds: int = 300,
    use_default: bool = True,
) -> Dict[str, Any]:
    """Espera por la respuesta del usuario (con timeout)."""
    q_path = questions_dir(repo_root, flowid) / f"{question_id}.yaml"
    if not q_path.exists():
        return {"success": False, "error": f"Pregunta {question_id} no encontrada"}

    q_data = read_yaml(q_path) or {}
    default = q_data.get("default", "")

    start = time.time()
    while time.time() - start < timeout_seconds:
        answer = check_answer(repo_root, flowid, question_id)
        if answer is not None:
            return {
                "success": True,
                "question_id": question_id,
                "answer": answer,
                "source": "user",
                "waited_seconds": round(time.time() - start, 1),
            }
        time.sleep(2)

    # Timeout — usar default
    if use_default and default:
        # Auto-responder con default
        answer_question(repo_root, flowid, question_id, default)
        return {
            "success": True,
            "question_id": question_id,
            "answer": default,
            "source": "default",
            "waited_seconds": timeout_seconds,
            "message": "Timeout — usando default",
        }

    return {
        "success": False,
        "error": "Timeout esperando respuesta y no hay default",
        "question_id": question_id,
        "waited_seconds": timeout_seconds,
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    argv = sys.argv[1:]
    action = "pending"
    known = {"ask", "answer", "pending", "history", "wait"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if not flowid:
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2))
        return 2

    if action == "ask":
        question = args.get("question", "")
        if not question:
            print(json.dumps({"success": False, "error": "Falta --question"}, indent=2))
            return 2
        context = args.get("context", "")
        options = []
        if args.get("options"):
            try:
                options = json.loads(args["options"])
            except json.JSONDecodeError:
                options = [o.strip() for o in args["options"].split(",")]
        default = args.get("default", "")
        timeout = int(args.get("timeout", "300"))
        q_type = args.get("type", "choice")

        result = ask_question(repo_root, flowid, question, context, options, default, timeout, q_type)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    elif action == "answer":
        qid = args.get("question-id", "")
        answer = args.get("answer", "")
        if not qid or answer == "":
            print(json.dumps({"success": False, "error": "Falta --question-id y --answer"}, indent=2))
            return 2
        result = answer_question(repo_root, flowid, qid, answer)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["success"] else 1

    elif action == "pending":
        result = get_pending_questions(repo_root, flowid)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    elif action == "history":
        result = get_history(repo_root, flowid)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    elif action == "wait":
        qid = args.get("question-id", "")
        if not qid:
            print(json.dumps({"success": False, "error": "Falta --question-id"}, indent=2))
            return 2
        timeout = int(args.get("timeout", "300"))
        use_default = args.get("use-default", "true") == "true"
        result = wait_for_answer(repo_root, flowid, qid, timeout, use_default)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["success"] else 1

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
