#!/usr/bin/env python3
"""test_hash_chain.py — Test standalone para hash chain (v2.6.3)."""
import sys, json, hashlib, tempfile, os
from pathlib import Path

_candidates = [
    Path(__file__).parent.parent / "scripts" / "python",
    Path("scripts/python"),
    Path.cwd() / "scripts" / "python",
]
for _p in _candidates:
    if (_p / "common.py").exists():
        sys.path.insert(0, str(_p))
        break

try:
    from secret_scanner import compute_hash_chain_entry, verify_hash_chain
except ImportError:
    print("SKIP: secret_scanner no disponible")
    sys.exit(0)

def main():
    genesis = hashlib.sha256(b"APOLO-DYNAMIC-FLOW-GENESIS-V1").hexdigest()
    prev = genesis
    lines = []
    for i in range(5):
        entry = {"seq": i+1, "actor": "test", "action": "test", "outcome": "success", "flow_id": "TEST"}
        entry["prev_hash"] = prev
        entry["entry_hash"] = compute_hash_chain_entry(entry, prev)
        lines.append(json.dumps(entry))
        prev = entry["entry_hash"]
    tmpf = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8")
    tmpf.write("\n".join(lines) + "\n")
    tmpf.close()
    valid, errors = verify_hash_chain(tmpf.name)
    os.unlink(tmpf.name)
    if valid:
        print("VALID")
        sys.exit(0)
    else:
        print("INVALID:", errors)
        sys.exit(1)

if __name__ == "__main__":
    main()
