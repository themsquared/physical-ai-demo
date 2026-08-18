#!/usr/bin/env python3
"""Extract the ordered tool-call sequence from a merged OTLP trace file.

The Repeatability receipt: two runs of the same mission must produce the
identical (agent, tool, arguments) sequence. Prints one line per call.
"""

import json
import sys


def main() -> None:
    doc = json.load(open(sys.argv[1]))
    calls = []
    for rs in doc["resourceSpans"]:
        svc = next(
            (
                a["value"].get("stringValue")
                for a in rs.get("resource", {}).get("attributes", [])
                if a["key"] == "service.name"
            ),
            "",
        )
        for ss in rs.get("scopeSpans", []):
            for sp in ss.get("spans", []):
                if not sp["name"].startswith("execute_tool"):
                    continue
                attrs = {
                    a["key"]: a["value"].get("stringValue", "") for a in sp.get("attributes", [])
                }
                calls.append(
                    (
                        int(sp["startTimeUnixNano"]),
                        svc,
                        attrs.get("gen_ai.tool.name", ""),
                        attrs.get("gen_ai.tool.call.arguments", ""),
                    )
                )
    for _, svc, tool, args in sorted(calls):
        print(f"{svc} {tool} {args}")


if __name__ == "__main__":
    main()
