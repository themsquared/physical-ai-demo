#!/usr/bin/env python3
"""Send one A2A message. Usage: a2a_send.py <url> <token> <text>"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from agents.a2a import a2a_send  # noqa: E402

if __name__ == "__main__":
    url, token, text = sys.argv[1], sys.argv[2], sys.argv[3]
    print(asyncio.run(a2a_send(url, text, token=token, timeout=120)))
