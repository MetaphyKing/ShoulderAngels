#!/usr/bin/env python3
"""Offline fake completer for ``--backend command`` (no API key).

Protocol: read one JSON object ``{"prompt": ..., "system": ...}`` from stdin;
write JSON ``{"text": ...}`` to stdout. Used by tests and as a copy-paste
host-LLM shim (Grok Bot / any agent can replace the body with a real call).
"""
from __future__ import annotations

import json
import sys

req = json.load(sys.stdin)
system = req.get("system") or ""

if "safe" in system and "bold" in system:
    text = json.dumps(
        {
            "safe": {
                "description": "Ship the smallest reversible change",
                "effort": "low",
                "risk": "low",
                "upside": "stable",
            },
            "bold": {
                "description": "Rewrite the risky path now",
                "effort": "high",
                "risk": "high",
                "upside": "10x",
            },
        }
    )
else:
    text = "1. The change ships.\n2. Tests stay green.\n3. Rollback remains easy."

json.dump({"text": text}, sys.stdout)
sys.stdout.write("\n")
