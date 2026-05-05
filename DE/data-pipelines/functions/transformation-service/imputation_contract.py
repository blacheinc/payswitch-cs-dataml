"""DE imputation policy merge: static bootstrap JSON, optional live contract blob, drift checks."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Tuple

from auth_clients import get_blob_service_client


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _live_contract_container() -> str:
    return os.getenv("DE_IMPUTATION_LIVE_CONTRACT_CONTAINER", "model-artifacts").strip() or "model-artifacts"


def _live_contract_blob_name() -> str:
    return os.getenv(
        "DE_IMPUTATION_LIVE_CONTRACT_BLOB", "contracts/de_imputation_contract_live.json"
    ).strip() or "contracts/de_imputation_contract_live.json"


def _median_drift_threshold() -> float:
    raw = (os.getenv("DE_IMPUTATION_MEDIAN_DRIFT_THRESHOLD") or "0.05").strip()
    try:
        v = float(raw)
        return max(0.0, v)
    except ValueError:
        return 0.05


def _static_policy_path() -> Path:
    return Path(__file__).resolve().parent / "config" / "de_imputation_policy.json"


def load_static_policy() -> Dict[str, Any]:
    with _static_policy_path().open("r", encoding="utf-8") as f:
        return json.load(f)


def load_live_contract_from_blob() -> Dict[str, Any] | None:
    try:
        blob_service = get_blob_service_client(
            connection_string_env_vars=(
                "SILVER_STORAGE_CONNECTION_STRING",
                "GOLD_STORAGE_CONNECTION_STRING",
            ),
            account_url_env_vars=(
                "SILVER_STORAGE_ACCOUNT_URL",
                "GOLD_STORAGE_ACCOUNT_URL",
                "AZURE_STORAGE_ACCOUNT_URL",
            ),
        )
    except ValueError:
        return None
    blob_client = blob_service.get_blob_client(
        container=_live_contract_container(),
        blob=_live_contract_blob_name(),
    )
    try:
        raw = blob_client.download_blob().readall()
    except Exception:
        return None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def write_live_contract_to_blob(contract: Dict[str, Any]) -> str:
    blob_service = get_blob_service_client(
        connection_string_env_vars=(
            "SILVER_STORAGE_CONNECTION_STRING",
            "GOLD_STORAGE_CONNECTION_STRING",
        ),
        account_url_env_vars=(
            "SILVER_STORAGE_ACCOUNT_URL",
            "GOLD_STORAGE_ACCOUNT_URL",
            "AZURE_STORAGE_ACCOUNT_URL",
        ),
    )
    blob_client = blob_service.get_blob_client(
        container=_live_contract_container(),
        blob=_live_contract_blob_name(),
    )
    payload = json.dumps(contract, default=str).encode("utf-8")
    blob_client.upload_blob(payload, overwrite=True)
    return f"{_live_contract_container()}/{_live_contract_blob_name()}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float))


def _feature_median(feature_rows: List[Dict[str, Any]], name: str) -> float | None:
    vals = [float(r[name]) for r in feature_rows if _is_number(r.get(name))]
    if not vals:
        return None
    return float(median(vals))


@dataclass
class MedianUpdate:
    feature: str
    old_value: float | None
    candidate_value: float | None
    drift_abs: float | None
    updated: bool


def build_live_contract(
    feature_rows: List[Dict[str, Any]],
    *,
    training_upload_id: str | None,
    run_id: str | None,
    static_policy: Dict[str, Any],
    previous_live_contract: Dict[str, Any] | None,
    threshold: float,
) -> Tuple[Dict[str, Any], List[MedianUpdate], bool]:
    feature_strategies = dict(static_policy.get("feature_strategies", {}) or {})
    prev_strategies = {}
    if previous_live_contract:
        prev_strategies = dict(previous_live_contract.get("feature_strategies", {}) or {})

    updates: List[MedianUpdate] = []
    any_updated = False

    for name, cfg in feature_strategies.items():
        strategy = str((cfg or {}).get("strategy", "")).upper()
        if strategy != "MEDIAN":
            continue

        old_val = None
        prev_cfg = prev_strategies.get(name, {})
        if _is_number(prev_cfg.get("value")):
            old_val = float(prev_cfg["value"])
        elif _is_number(cfg.get("value")):
            old_val = float(cfg["value"])

        candidate = _feature_median(feature_rows, name)
        if candidate is None:
            updates.append(
                MedianUpdate(
                    feature=name,
                    old_value=old_val,
                    candidate_value=None,
                    drift_abs=None,
                    updated=False,
                )
            )
            continue

        drift = abs(candidate - old_val) if old_val is not None else None
        should_update = old_val is None or (drift is not None and drift >= threshold)
        if should_update:
            cfg["value"] = round(candidate, 6)
            feature_strategies[name] = cfg
            any_updated = True
        updates.append(
            MedianUpdate(
                feature=name,
                old_value=old_val,
                candidate_value=round(candidate, 6),
                drift_abs=None if drift is None else round(drift, 6),
                updated=should_update,
            )
        )

    policy_version = f"de-imputation-live-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    live_contract = {
        **static_policy,
        "policy_version": policy_version,
        "source": "de-living-contract",
        "generated_at": _utc_now_iso(),
        "feature_strategies": feature_strategies,
        "living_contract": {
            "enabled": True,
            "threshold_abs": threshold,
            "training_upload_id": training_upload_id,
            "run_id": run_id,
            "updated": any_updated,
            "median_updates": [
                {
                    "feature": u.feature,
                    "old_value": u.old_value,
                    "candidate_value": u.candidate_value,
                    "drift_abs": u.drift_abs,
                    "updated": u.updated,
                }
                for u in updates
            ],
        },
    }
    return live_contract, updates, any_updated


def resolve_effective_policy() -> Dict[str, Any]:
    static_policy = load_static_policy()
    enabled = (os.getenv("DE_IMPUTATION_ENABLE_LIVE_POLICY") or "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not enabled:
        return static_policy
    live = load_live_contract_from_blob()
    if not (isinstance(live, dict) and live.get("feature_strategies")):
        return static_policy
    # Keep static contract shape authoritative and only overlay live strategy values/version metadata.
    merged = dict(static_policy)
    merged["feature_strategies"] = dict(static_policy.get("feature_strategies", {}) or {})
    for name, cfg in dict(live.get("feature_strategies", {}) or {}).items():
        if not isinstance(cfg, dict):
            continue
        base_cfg = dict(merged["feature_strategies"].get(name, {}) or {})
        base_cfg.update(cfg)
        merged["feature_strategies"][name] = base_cfg
    merged["policy_version"] = live.get("policy_version", static_policy.get("policy_version"))
    merged["source"] = live.get("source", static_policy.get("source"))
    if isinstance(live.get("living_contract"), dict):
        merged["living_contract"] = live["living_contract"]
    return merged


def refresh_live_contract_from_training(
    *,
    feature_rows: List[Dict[str, Any]],
    training_upload_id: str | None,
    run_id: str | None,
) -> Dict[str, Any]:
    static_policy = load_static_policy()
    prev = load_live_contract_from_blob()
    threshold = _median_drift_threshold()
    live_contract, updates, any_updated = build_live_contract(
        feature_rows,
        training_upload_id=training_upload_id,
        run_id=run_id,
        static_policy=static_policy,
        previous_live_contract=prev,
        threshold=threshold,
    )
    path = write_live_contract_to_blob(live_contract)
    return {
        "path": path,
        "updated": any_updated,
        "threshold_abs": threshold,
        "updates": [
            {
                "feature": u.feature,
                "old_value": u.old_value,
                "candidate_value": u.candidate_value,
                "drift_abs": u.drift_abs,
                "updated": u.updated,
            }
            for u in updates
        ],
        "policy_version": live_contract.get("policy_version"),
    }

