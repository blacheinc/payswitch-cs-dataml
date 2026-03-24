"""
Preprocessing module for the PaySwitch Credit Scoring Orchestrator.

Handles:
- Feature vector validation (30 features present and numeric)
- Missing value imputation for Product 49-only records
- Training dataset validation and imputation parameter computation
- Saving/loading imputation parameters to/from blob storage
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from shared.schemas.feature_schema import (
    ALL_FEATURE_NAMES,
    FEATURE_BY_NAME,
    FEATURES_REQUIRING_IMPUTATION,
    IMPUTATION_FEATURE_NAMES,
    ImputationStrategy,
)

logger = logging.getLogger("payswitch-cs.preprocessing")


# ── Imputation Parameter Computation (Training Time) ────────────────────────

def compute_imputation_params(df: pd.DataFrame) -> dict[str, float]:
    """
    Compute imputation values from a training dataset.

    For features with MEDIAN strategy: compute median from non-null values.
    For features with ZERO strategy: value is always 0.

    Args:
        df: Training DataFrame with all 30 feature columns.

    Returns:
        Dict mapping feature name → imputation value.
    """
    params: dict[str, float] = {}

    for feat_def in FEATURES_REQUIRING_IMPUTATION:
        if feat_def.imputation_strategy == ImputationStrategy.MEDIAN:
            col = df[feat_def.name]
            median_val = col.dropna().median()
            if pd.isna(median_val):
                logger.warning(
                    "Feature %s has no non-null values; defaulting median to 0.0",
                    feat_def.name,
                )
                median_val = 0.0
            params[feat_def.name] = float(median_val)
        elif feat_def.imputation_strategy == ImputationStrategy.ZERO:
            params[feat_def.name] = 0.0

    return params


def imputation_params_to_json(params: dict[str, float]) -> str:
    """Serialize imputation params to JSON for blob storage."""
    return json.dumps(params, indent=2)


def imputation_params_from_json(raw: str | bytes) -> dict[str, float]:
    """Deserialize imputation params from blob storage JSON."""
    data = json.loads(raw)
    return {k: float(v) for k, v in data.items()}


# ── Feature Vector Imputation (Inference Time) ─────────────────────────────

def impute_features(
    features: dict[str, Optional[float]],
    imputation_params: dict[str, float],
) -> dict[str, float]:
    """
    Impute null/missing feature values using pre-computed parameters.

    Used during inference to fill Product 49-only gaps before
    sending the feature vector to model agents.

    Args:
        features: Raw feature dict (may contain None values).
        imputation_params: Pre-computed imputation values from training.

    Returns:
        Complete feature dict with no None values.

    Raises:
        ValueError: If a feature is missing and has no imputation rule.
    """
    result: dict[str, float] = {}

    for feat_name in ALL_FEATURE_NAMES:
        value = features.get(feat_name)

        if value is not None and not _is_nan(value):
            result[feat_name] = float(value)
        elif feat_name in imputation_params:
            result[feat_name] = imputation_params[feat_name]
            logger.debug("Imputed %s = %.4f", feat_name, imputation_params[feat_name])
        else:
            raise ValueError(
                f"Feature '{feat_name}' is null/missing and has no imputation rule. "
                f"Ensure the feature vector is complete or the imputation params cover this feature."
            )

    return result


def _is_nan(value: Any) -> bool:
    """Check if a value is NaN (works for float and numpy types)."""
    try:
        return np.isnan(value)
    except (TypeError, ValueError):
        return False


# ── Training Dataset Validation ─────────────────────────────────────────────

# Required columns beyond the 30 features
TRAINING_TARGET_COLUMNS = ["default_flag", "max_successful_loan_ghs", "income_tier"]


def validate_training_dataset(df: pd.DataFrame) -> list[str]:
    """
    Validate a training dataset has the required structure.

    Returns:
        List of validation error messages (empty = valid).
    """
    errors: list[str] = []

    # Check all 30 feature columns exist
    missing_features = set(ALL_FEATURE_NAMES) - set(df.columns)
    if missing_features:
        errors.append(f"Missing feature columns: {sorted(missing_features)}")

    # Check target columns exist
    missing_targets = set(TRAINING_TARGET_COLUMNS) - set(df.columns)
    if missing_targets:
        errors.append(f"Missing target columns: {sorted(missing_targets)}")

    # Check dataset is not empty
    if len(df) == 0:
        errors.append("Dataset is empty (0 records)")

    # Check feature columns are numeric
    if not missing_features:
        for feat_name in ALL_FEATURE_NAMES:
            if feat_name in df.columns and not pd.api.types.is_numeric_dtype(df[feat_name]):
                errors.append(f"Feature '{feat_name}' is not numeric (dtype={df[feat_name].dtype})")

    return errors


# ── Inference Feature Vector Validation ─────────────────────────────────────

def validate_inference_features(
    features: dict[str, Optional[float]],
) -> list[str]:
    """
    Validate a feature vector for inference.

    Checks that all 30 feature names are present as keys.
    Null values are allowed (they'll be imputed).
    Non-imputable features must not be null.

    Returns:
        List of validation error messages (empty = valid).
    """
    errors: list[str] = []

    # Check all feature keys present
    missing = set(ALL_FEATURE_NAMES) - set(features.keys())
    if missing:
        errors.append(f"Missing features: {sorted(missing)}")

    # Check non-imputable features are not null
    imputable_set = set(IMPUTATION_FEATURE_NAMES)
    for feat_name in ALL_FEATURE_NAMES:
        if feat_name in features and feat_name not in imputable_set:
            val = features[feat_name]
            if val is None or _is_nan(val):
                errors.append(
                    f"Feature '{feat_name}' is null but has no imputation rule — "
                    f"must be provided by Data Engineer"
                )

    return errors


# ── Training Dataset Imputation ─────────────────────────────────────────────

def impute_training_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """
    Impute missing values in a training dataset and compute params.

    This is the main training-time preprocessing entry point.

    Returns:
        Tuple of (imputed DataFrame, imputation params dict).
    """
    params = compute_imputation_params(df)

    df_imputed = df.copy()
    for feat_name, fill_value in params.items():
        if feat_name in df_imputed.columns:
            df_imputed[feat_name] = df_imputed[feat_name].fillna(fill_value)

    return df_imputed, params
