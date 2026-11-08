"""Send checkout traffic and print a latency/status summary.

    python workloads/scripts/traffic.py --url http://localhost:8080 --requests 50

Useful to create baseline telemetry before an incident and to watch the effect
of one (e.g. p95 going from ~200 ms to ~2 s in db mode). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter

BODY = json.dumps(
    {"user_id": "u-7", "items": [{"sku": "sku-1", "quantity": 2, "unit_price_cents": 1500}]}
).encode()


def send(url: str) -> tuple[int, float]:
    request = urllib.request.Request(  # noqa: S310 - URL comes from the operator
        f"{url}/checkout", data=BODY, headers={"Content-Type": "application/json"}
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    return status, time.perf_counter() - start


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--requests", type=int, default=50)
    args = parser.parse_args()

    results = [send(args.url) for _ in range(args.requests)]
    latencies = sorted(seconds * 1000 for _, seconds in results)
    statuses = Counter(status for status, _ in results)
    p95 = statistics.quantiles(latencies, n=20)[-1] if len(latencies) >= 2 else latencies[0]
    print(  # noqa: T201 - CLI output
        f"requests={len(results)} statuses={dict(statuses)} "
        f"p50={statistics.median(latencies):.0f}ms p95={p95:.0f}ms max={latencies[-1]:.0f}ms"
    )


if __name__ == "__main__":
    main()
