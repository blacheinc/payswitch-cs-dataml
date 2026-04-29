"""
Run transformation-service inference logic on a local JSON/JSONL file (e.g. dummified bureau lines).

Uses the same code path as HTTP JSONL batch inference: _xds_payload_from_jsonl_object +
_run_inference_batch_jsonl. Service Bus publishes are skipped when no connection string is set;
set TRANSFORM_DISABLE_BACKEND_EVENT=1 to suppress backend topic publishes.

Examples (from transformation-service directory):

  python scripts/smoke_inference_from_jsonl_file.py ^
    "../../project execution artifacts/consumer_dummified_output_1.json" ^
    --data-source-id 00000000-0000-0000-0000-000000000001 --max-lines 2

  python scripts/smoke_inference_from_jsonl_file.py ^
    "../../project execution artifacts/mobile_dummified_output_1.json" ^
    --data-source-id 00000000-0000-0000-0000-000000000002 --max-lines 2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path


def _service_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test inference on a JSONL file.")
    parser.add_argument(
        "jsonl_path",
        type=Path,
        help="Path to JSONL (one JSON object per line) or a small JSON array file.",
    )
    parser.add_argument(
        "--data-source-id",
        default="00000000-0000-0000-0000-000000000001",
        help="Bank / data source id passed through the inference pipeline.",
    )
    parser.add_argument(
        "--source-system",
        default="xds",
        help="source_system field on the inference payload.",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=3,
        help="Maximum lines to process (default 3). Large artifacts stay fast.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging.",
    )
    parser.add_argument(
        "--use-key-vault",
        action="store_true",
        help="Keep KEY_VAULT_URL from the environment (LLM PII + Service Bus via Vault). "
        "Default: temporarily unset KEY_VAULT_URL so local smoke uses rule-based PII only and "
        "does not open Key Vault for the bundled schema-mapping ServiceBusWriter.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    os.environ.setdefault("TRANSFORM_DISABLE_BACKEND_EVENT", "1")

    _saved_kv: str | None = None
    if not args.use_key_vault:
        _saved_kv = os.environ.pop("KEY_VAULT_URL", None)
        if _saved_kv:
            logging.info(
                "Temporarily unset KEY_VAULT_URL for this process (use --use-key-vault to keep it)."
            )

    root = _service_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    path = args.jsonl_path.expanduser().resolve()
    if not path.is_file():
        logging.error("File not found: %s", path)
        return 2

    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        logging.error("Empty file: %s", path)
        return 2

    objects: list[dict] = []
    if raw.startswith("["):
        data = json.loads(raw)
        if not isinstance(data, list):
            logging.error("JSON array root must be a list of objects.")
            return 2
        for i, item in enumerate(data[: args.max_lines]):
            if isinstance(item, dict):
                objects.append(item)
            else:
                logging.warning("Skipping non-object array element at index %s", i)
    else:
        for i, line in enumerate(raw.splitlines(), start=1):
            if len(objects) >= args.max_lines:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                logging.error("Line %s: invalid JSON: %s", i, e)
                return 2
            if not isinstance(obj, dict):
                logging.error("Line %s: expected JSON object.", i)
                return 2
            objects.append(obj)

    if not objects:
        logging.error("No objects to process.")
        return 2

    try:
        from function_app import _run_inference_batch_jsonl  # noqa: E402

        parsed = [(i + 1, obj) for i, obj in enumerate(objects)]
        out = _run_inference_batch_jsonl(
            parsed,
            data_source_id=args.data_source_id,
            source_system=args.source_system,
            models_to_run=None,
        )
        logging.info(
            "Batch finished: total_lines=%s succeeded=%s failed=%s",
            out.get("total_lines"),
            out.get("succeeded"),
            out.get("failed"),
        )
        if out.get("errors"):
            for err in out["errors"]:
                logging.error("Line %s error: %s", err.get("line"), err.get("error"))
            return 1
        logging.info("OK — inference path executed for %s line(s).", len(parsed))
        return 0
    finally:
        if _saved_kv is not None:
            os.environ["KEY_VAULT_URL"] = _saved_kv


if __name__ == "__main__":
    raise SystemExit(main())
