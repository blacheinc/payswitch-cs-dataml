"""
POST one or more inference payloads to the local (or deployed) transform/inference endpoint.

The API accepts exactly one applicant per request. Files with a top-level "samples" array
are posted once per element.

Usage (from transformation-service directory, with func host running elsewhere):

  python scripts/post_inference_samples.py --payload payload_inference_1_sample.json
  python scripts/post_inference_samples.py --payload payload_inference_multiple_samples.json

If the function uses function-level auth, pass --code <key> (or set FUNCTIONS_KEY in the env).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _load_payloads(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "samples" in data:
        samples = data["samples"]
        if not isinstance(samples, list):
            raise SystemExit('"samples" must be a JSON array')
        return samples
    if isinstance(data, dict):
        return [data]
    raise SystemExit("JSON root must be an object, a list, or an object with 'samples'")


def _post(url: str, body: dict[str, Any]) -> tuple[int, str]:
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        return e.code, text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get(
            "INFERENCE_HTTP_URL", "http://localhost:7071/api/transform/inference"
        ),
        help="Full URL to transform/inference (default: localhost or INFERENCE_HTTP_URL)",
    )
    parser.add_argument(
        "--code",
        default=os.environ.get("FUNCTIONS_KEY", ""),
        help="Function key (appended as ?code= or &code=)",
    )
    parser.add_argument(
        "--payload",
        type=Path,
        default=Path("payload_inference_1_sample.json"),
        help="Path to JSON: single request object, array of requests, or {samples: [...]}",
    )
    args = parser.parse_args()

    path = args.payload
    if not path.is_file():
        sys.exit(f"Payload file not found: {path.resolve()}")

    url = args.base_url.strip()
    code = (args.code or "").strip()
    if code:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}code={code}"

    bodies = _load_payloads(path)
    for i, body in enumerate(bodies):
        rid = body.get("request_id", f"index-{i}")
        status, text = _post(url, body)
        print(f"[{i + 1}/{len(bodies)}] request_id={rid} HTTP {status}")
        if status != 200:
            print(text[:2000])
            sys.exit(1)
        try:
            obj = json.loads(text)
            print(
                "  bureau_hit_status:",
                obj.get("bureau_hit_status"),
                "decision:",
                (obj.get("decision_package") or {}).get("decision"),
            )
        except json.JSONDecodeError:
            print("  (non-JSON body)")


if __name__ == "__main__":
    main()
