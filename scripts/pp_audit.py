#!/usr/bin/env python3
"""Pretty-print gateway JSON audit lines as the human-readable flight recorder.
Reads log lines on stdin."""

import json
import sys

for line in sys.stdin:
    try:
        r = json.loads(line)
    except json.JSONDecodeError:
        continue
    tool = r.get("tool")
    if not tool:
        continue
    ident = r.get("identity", "?")
    args = r.get("tool_args", {})
    err = r.get("error") or r.get("tool_error")
    verdict = "DENIED" if err else "ok"
    print(
        f"  [{verdict:6}] {ident:18} {tool:20} args={json.dumps(args)}"
        + (f"  ({err})" if err else "")
    )
