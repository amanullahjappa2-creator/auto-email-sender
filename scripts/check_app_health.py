#!/usr/bin/env python3
"""Quick app health probe for local or deployed MailFlow Studio instances."""

import json
import sys
import urllib.error
import urllib.request


def main() -> int:
    url = "http://127.0.0.1:5000/healthz"
    if len(sys.argv) > 1:
        url = sys.argv[1]

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if response.status == 200 else 1
    except urllib.error.URLError as exc:
        print(f"MailFlow health check failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
