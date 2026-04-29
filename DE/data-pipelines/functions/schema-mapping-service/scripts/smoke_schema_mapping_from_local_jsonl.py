"""
Upload a small JSONL sample to ADLS Gen2 bronze and run the real schema-mapping Systems 0–4.

Project execution dummified lines are raw bureau-shaped JSON. The orchestrator's
flattened_xds_schema_v1 step expects Product 45 columns under ``consumer_full_report_45.*``,
so this script wraps each line in ``{"consumer_full_report_45": <line>}`` by default.

Prerequisites:
  - DATALAKE_STORAGE_CONNECTION_STRING with bronze + silver containers (same as local Functions).
  - KEY_VAULT_URL: any non-empty URL (orchestrator constructs KeyVaultReader). If you use a
    placeholder URL, ensure datalake auth uses the connection string so Vault is never called.
  - Optional: real KEY_VAULT_URL + ``az login`` if you omit the connection string.

Service Bus: by default this script replaces the orchestrator writer with a no-op so you do
not need a Service Bus connection for a local smoke test. Pass ``--real-service-bus`` to use
the normal writer (requires Key Vault ``ServiceBusConnectionString`` or equivalent setup).

Examples (from schema-mapping-service directory):

  python scripts/smoke_schema_mapping_from_local_jsonl.py ^
    "../../project execution artifacts/consumer_dummified_output_1.json" ^
    --bank-id smoke-bank --max-lines 5

  python scripts/smoke_schema_mapping_from_local_jsonl.py ^
    "../../project execution artifacts/mobile_dummified_output_1.json" ^
    --bank-id smoke-bank --max-lines 5 --no-wrap-45
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class _NoOpServiceBusWriter:
    """Swallow progress / handoff publishes for offline smoke tests."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("publish_"):

            def _noop(*a: Any, **k: Any) -> None:
                return None

            return _noop
        raise AttributeError(name)


def _sample_jsonl_lines(
    path: Path,
    max_lines: int,
    *,
    wrap_consumer_45: bool,
) -> str:
    lines_out: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            if len(lines_out) >= max_lines:
                break
            line = raw.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError("Each JSONL line must be a JSON object.")
            if wrap_consumer_45 and "consumer_full_report_45" not in obj and "xds_payload" not in obj:
                obj = {"consumer_full_report_45": obj}
            lines_out.append(json.dumps(obj, ensure_ascii=False))
    if not lines_out:
        raise ValueError("No non-empty JSONL lines read from file.")
    return "\n".join(lines_out) + "\n"


def _upload_bronze(
    *,
    connection_string: str,
    relative_path: str,
    body: bytes,
) -> None:
    from azure.storage.filedatalake import DataLakeServiceClient

    dl = DataLakeServiceClient.from_connection_string(connection_string)
    fs = dl.get_file_system_client("bronze")
    fc = fs.get_file_client(relative_path)
    fc.upload_data(body, overwrite=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test schema-mapping on a local JSONL file via bronze upload."
    )
    parser.add_argument(
        "jsonl_path",
        type=Path,
        help="Path to JSONL (one JSON object per line).",
    )
    parser.add_argument("--bank-id", default="smoke-bank-local", help="bank_id in the handoff message.")
    parser.add_argument(
        "--training-upload-id",
        default="",
        help="UUID for training_upload_id (default: random).",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="UUID for run_id (default: random).",
    )
    parser.add_argument(
        "--date",
        default="",
        help="YYYY-MM-DD folder segment under training/ (default: UTC today).",
    )
    parser.add_argument("--max-lines", type=int, default=5, help="Lines to upload and process.")
    parser.add_argument(
        "--no-wrap-45",
        action="store_true",
        help="Do not wrap raw lines under consumer_full_report_45 (may fail flattened_xds_schema_v1).",
    )
    parser.add_argument(
        "--real-service-bus",
        action="store_true",
        help="Use real ServiceBusWriter instead of no-op (needs SB secret in Key Vault).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    conn = (os.getenv("DATALAKE_STORAGE_CONNECTION_STRING") or "").strip()
    if not conn:
        logging.error("Set DATALAKE_STORAGE_CONNECTION_STRING for bronze/silver upload and pipeline reads.")
        return 2

    kv_url = (os.getenv("KEY_VAULT_URL") or "").strip()
    if not kv_url:
        kv_url = "https://schema-smoke-placeholder.vault.azure.net/"
        os.environ.setdefault("KEY_VAULT_URL", kv_url)
        logging.warning(
            "KEY_VAULT_URL not set; using placeholder %s (datalake uses connection string only).",
            kv_url,
        )

    path = args.jsonl_path.expanduser().resolve()
    if not path.is_file():
        logging.error("File not found: %s", path)
        return 2

    upload_id = (args.training_upload_id or "").strip() or str(uuid.uuid4())
    run_id = (args.run_id or "").strip() or str(uuid.uuid4())
    date = (args.date or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        body_text = _sample_jsonl_lines(
            path,
            args.max_lines,
            wrap_consumer_45=not args.no_wrap_45,
        )
    except Exception as e:
        logging.error("Failed to build sample JSONL: %s", e)
        return 2

    bronze_rel = f"training/{args.bank_id}/{date}/{upload_id}.jsonl"
    logging.info("Uploading %s bytes to bronze/%s", len(body_text.encode("utf-8")), bronze_rel)
    try:
        _upload_bronze(connection_string=conn, relative_path=bronze_rel, body=body_text.encode("utf-8"))
    except Exception as e:
        logging.error("Bronze upload failed: %s", e, exc_info=args.verbose)
        return 2

    message_data = {
        "training_upload_id": upload_id,
        "bank_id": args.bank_id,
        "bronze_blob_path": f"bronze/{bronze_rel}",
        "file_format": "jsonl",
        "run_id": run_id,
    }

    from orchestrator import SchemaMappingOrchestrator  # noqa: E402

    orch = SchemaMappingOrchestrator(key_vault_url=kv_url)
    if not args.real_service_bus:
        orch.service_bus_writer = _NoOpServiceBusWriter()

    try:
        result = orch.run_pipeline(message_data)
        logging.info("Pipeline completed: keys=%s", list(result.keys()) if isinstance(result, dict) else type(result))
    except Exception as e:
        logging.error("Pipeline failed: %s", e, exc_info=args.verbose)
        return 1
    finally:
        try:
            from azure.storage.filedatalake import DataLakeServiceClient

            dl = DataLakeServiceClient.from_connection_string(conn)
            dl.get_file_system_client("bronze").get_file_client(bronze_rel).delete_file()
            logging.info("Removed temporary bronze blob: %s", bronze_rel)
        except Exception as e:
            logging.warning("Could not delete temporary bronze blob %s: %s", bronze_rel, e)

    logging.info("OK — schema-mapping Systems 0–4 ran on %s sample line(s).", args.max_lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
