"""Download curated *_features.parquet and *_metadata.parquet and write CSVs locally.

Requires GOLD_STORAGE_CONNECTION_STRING in the environment (e.g. from local.settings.json).

Usage:
  set GOLD_STORAGE_CONNECTION_STRING=...
  python scripts/export_curated_parquet_to_csv.py [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

import pandas as pd
from azure.storage.blob import BlobServiceClient

DEFAULT_BLOB_PREFIX = (
    "ml-training/source_system=xds/data_source_id=b4ed5120-65f4-46c5-b687-dc895a1d6bbf/"
    "20260404T044201Z_59e2dfd9-93bd-411f-aa39-6c369c30c07f"
)
CONTAINER = "curated"


def _load_conn_from_settings(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    conn = (data.get("Values") or {}).get("GOLD_STORAGE_CONNECTION_STRING")
    if not conn:
        raise SystemExit(f"No GOLD_STORAGE_CONNECTION_STRING in {path}")
    return conn


def read_parquet_blob(conn: str, blob_path: str) -> pd.DataFrame:
    bsc = BlobServiceClient.from_connection_string(conn)
    blob = bsc.get_container_client(CONTAINER).get_blob_client(blob_path)
    raw = blob.download_blob().readall()
    return pd.read_parquet(io.BytesIO(raw))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--settings",
        type=Path,
        help="local.settings.json path (loads GOLD_STORAGE_CONNECTION_STRING)",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_BLOB_PREFIX,
        help="Blob path without _features / _metadata suffix",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[4] / "curated_csv_export",
        help="Directory for output CSV files",
    )
    args = parser.parse_args()

    conn = os.environ.get("GOLD_STORAGE_CONNECTION_STRING")
    if args.settings:
        conn = _load_conn_from_settings(args.settings)
    if not conn:
        sys.exit("Set GOLD_STORAGE_CONNECTION_STRING or pass --settings")

    prefix = str(args.prefix).strip().rstrip("/")
    features_blob = f"{prefix}_features.parquet"
    metadata_blob = f"{prefix}_metadata.parquet"
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, blob_path in (
        ("features", features_blob),
        ("metadata", metadata_blob),
    ):
        df = read_parquet_blob(conn, blob_path)
        out_path = out_dir / f"{name}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8")
        print(f"Wrote {out_path}  shape={df.shape}")


if __name__ == "__main__":
    main()
