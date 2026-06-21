#!/usr/bin/env python3
"""
code_generator.py — Generación automática de código (v2.7.0).

Escribe funciones/classes completas desde especificaciones.

Si LLM disponible: usa llm_bridge para generar código significativo.
Si no: usa plantillas deterministas por lenguaje.

Uso:
  python3 code_generator.py --language python --type function --name "calculate_tax" --args "amount,rate" --description "Calculate tax on amount"
  python3 code_generator.py --language typescript --type class --name "UserService" --methods "getUser,createUser"
  python3 code_generator.py --language go --type function --name "CalculateTax" --args "amount float64, rate float64"
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args


def generate_python_function(name: str, args: str, description: str = "") -> str:
    """Genera una función Python desde plantilla."""
    args_list = [a.strip() for a in args.split(",")] if args else []
    args_str = ", ".join(args_list)
    doc = description or f"TODO: Implement {name}."

    code = f'''def {name}({args_str}):
    """{doc}"""
    # TODO: Implement logic
    raise NotImplementedError("{name} not yet implemented")
'''
    return code


def generate_python_class(name: str, methods: str, description: str = "") -> str:
    """Genera una clase Python desde plantilla."""
    method_list = [m.strip() for m in methods.split(",")] if methods else []
    doc = description or f"{name} class."

    code = f'''class {name}:
    """{doc}"""

    def __init__(self):
        """Initialize {name}."""
        pass

'''
    for m in method_list:
        code += f'''    def {m}(self, *args, **kwargs):
        """TODO: Implement {m}."""
        raise NotImplementedError("{m} not yet implemented")

'''
    return code


def generate_typescript_function(name: str, args: str, description: str = "") -> str:
    """Genera una función TypeScript."""
    args_list = [a.strip() for a in args.split(",")] if args else []
    args_str = ", ".join(f"{a}: any" for a in args_list)
    doc = description or f"TODO: Implement {name}."

    code = f'''/**
 * {doc}
 */
export function {name}({args_str}): any {{
  // TODO: Implement logic
  throw new Error("{name} not yet implemented");
}}
'''
    return code


def generate_typescript_class(name: str, methods: str, description: str = "") -> str:
    """Genera una clase TypeScript."""
    method_list = [m.strip() for m in methods.split(",")] if methods else []
    doc = description or f"{name} class."

    code = f'''/**
 * {doc}
 */
export class {name} {{
  constructor() {{
    // Initialize
  }}

'''
    for m in method_list:
        code += f'''  {m}(...args: any[]): any {{
    // TODO: Implement {m}
    throw new Error("{m} not yet implemented");
  }}

'''
    code += "}\n"
    return code


def generate_go_function(name: str, args: str, description: str = "") -> str:
    """Genera una función Go."""
    # Go needs exported name (capitalized)
    go_name = name[0].upper() + name[1:] if name else "Function"
    doc = description or f"TODO: Implement {go_name}."

    code = f'''// {doc}
func {go_name}() error {{
	// TODO: Implement logic
	return fmt.Errorf("{go_name} not yet implemented")
}}
'''
    return code


def generate_go_struct(name: str, methods: str, description: str = "") -> str:
    """Genera un struct Go con métodos."""
    method_list = [m.strip() for m in methods.split(",")] if methods else []
    go_name = name[0].upper() + name[1:] if name else "Service"
    doc = description or f"{go_name} struct."

    code = f'''// {doc}
type {go_name} struct {{
	// fields
}}

'''
    for m in method_list:
        go_m = m[0].upper() + m[1:] if m else "Method"
        code += f'''// {go_m} TODO: Implement
func (s *{go_name}) {go_m}() error {{
	return fmt.Errorf("{go_m} not yet implemented")
}}

'''
    return code


def generate_rust_function(name: str, args: str, description: str = "") -> str:
    """Genera una función Rust."""
    snake_name = name.replace(" ", "_").lower()
    doc = description or f"TODO: Implement {snake_name}."

    code = f'''/// {doc}
pub fn {snake_name}() -> Result<(), String> {{
    // TODO: Implement logic
    Err("{snake_name} not yet implemented".to_string())
}}
'''
    return code


def generate_java_class(name: str, methods: str, description: str = "") -> str:
    """Genera una clase Java."""
    method_list = [m.strip() for m in methods.split(",")] if methods else []
    doc = description or f"{name} class."

    code = f'''/**
 * {doc}
 */
public class {name} {{

    public {name}() {{
        // Initialize
    }}

'''
    for m in method_list:
        code += f'''    public void {m}() {{
        // TODO: Implement {m}
        throw new UnsupportedOperationException("{m} not yet implemented");
    }}

'''
    code += "}\n"
    return code


def generate_cpp_class(name: str, methods: str, description: str = "") -> str:
    """Genera una clase C++."""
    method_list = [m.strip() for m in methods.split(",")] if methods else []
    doc = description or f"{name} class."

    code = f'''// {doc}
class {name} {{
public:
    {name}() {{
        // Initialize
    }}

'''
    for m in method_list:
        code += f'''    void {m}() {{
        // TODO: Implement {m}
        throw std::runtime_error("{m} not yet implemented");
    }}

'''
    code += "};\n"
    return code


def generate_php_class(name: str, methods: str, description: str = "") -> str:
    """Genera una clase PHP."""
    method_list = [m.strip() for m in methods.split(",")] if methods else []
    doc = description or f"{name} class."

    code = f'''<?php
/**
 * {doc}
 */
class {name} {{

    public function __construct() {{
        // Initialize
    }}

'''
    for m in method_list:
        code += f'''    public function {m}() {{
        // TODO: Implement {m}
        throw new Exception("{m} not yet implemented");
    }}

'''
    code += "}\n"
    return code


LANG_GENERATORS = {
    "python": {"function": generate_python_function, "class": generate_python_class},
    "typescript": {"function": generate_typescript_function, "class": generate_typescript_class},
    "go": {"function": generate_go_function, "class": generate_go_struct},
    "rust": {"function": generate_rust_function, "class": generate_rust_function},
    "java": {"function": generate_java_class, "class": generate_java_class},
    "cpp": {"function": generate_cpp_class, "class": generate_cpp_class},
    "c": {"function": generate_cpp_class, "class": generate_cpp_class},
    "php": {"function": generate_php_class, "class": generate_php_class},
}


def generate_with_llm(language: str, code_type: str, name: str, args: str = "",
                      methods: str = "", description: str = "") -> Optional[str]:
    """Usa LLM para generar código más inteligente."""
    try:
        from llm_bridge import is_available, chat
        if not is_available():
            return None

        prompt_parts = [f"Generate a {code_type} in {language}"]
        if name:
            prompt_parts.append(f"named '{name}'")
        if args:
            prompt_parts.append(f"with parameters: {args}")
        if methods:
            prompt_parts.append(f"with methods: {methods}")
        if description:
            prompt_parts.append(f"that: {description}")

        prompt = ". ".join(prompt_parts) + ". Provide only the code, no explanations."
        messages = [
            {"role": "system", "content": f"You are an expert {language} developer. Generate clean, production-ready code."},
            {"role": "user", "content": prompt},
        ]
        return chat(messages, temperature=0.2, max_tokens=2000)
    except ImportError:
        return None


def generate(language: str, code_type: str, name: str, args: str = "",
             methods: str = "", description: str = "", use_llm: bool = True) -> str:
    """Genera código. Si LLM disponible, usa LLM. Si no, usa plantilla determinista."""
    # Try LLM first
    if use_llm:
        llm_code = generate_with_llm(language, code_type, name, args, methods, description)
        if llm_code:
            return llm_code

    # Fallback to deterministic template
    lang_lower = language.lower()
    if lang_lower not in LANG_GENERATORS:
        lang_lower = "python"  # default

    generators = LANG_GENERATORS[lang_lower]
    gen_fn = generators.get(code_type, generators.get("function"))

    if code_type == "function":
        return gen_fn(name, args, description)
    else:
        return gen_fn(name, methods, description)


def main() -> int:
    args = parse_args(sys.argv[1:])
    language = args.get("language", "python")
    code_type = args.get("type", "function")
    name = args.get("name", "myFunction")
    func_args = args.get("args", "")
    methods = args.get("methods", "")
    description = args.get("description", "")
    output = args.get("output", "")

    code = generate(language, code_type, name, func_args, methods, description)

    if output:
        Path(output).write_text(code, encoding="utf-8")
        print(json.dumps({"success": True, "output": output, "lines": code.count("\n") + 1}))
    else:
        print(code)

    return 0


if __name__ == "__main__":
    sys.exit(main())
