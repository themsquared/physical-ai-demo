#!/usr/bin/env python3
"""Merge the otel-collector's file-exporter JSONL into one OTLP JSON document
that `agentevals run` accepts.

Usage: merge_traces.py <in.jsonl> <out.json> [service-name-filter ...]
Optional filters keep only spans from the named services (e.g. the cognition
agents), which keeps eval extraction focused on agent behavior.
"""

import json
import sys


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    keep = set(sys.argv[3:])
    merged: list[dict] = []
    for line in open(src):
        line = line.strip()
        if not line:
            continue
        doc = json.loads(line)
        for rs in doc.get("resourceSpans", []):
            svc = next(
                (
                    a["value"].get("stringValue")
                    for a in rs.get("resource", {}).get("attributes", [])
                    if a["key"] == "service.name"
                ),
                "",
            )
            if keep and svc not in keep:
                continue
            merged.append(rs)
    json.dump({"resourceSpans": merged}, open(dst, "w"))
    print(f"merged {len(merged)} resourceSpans -> {dst}")


if __name__ == "__main__":
    main()
