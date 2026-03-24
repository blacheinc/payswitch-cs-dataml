"""Tests for orchestrator preprocessing module."""

import json

import numpy as np
import pandas as pd
import pytest

from orchestrator.modules.preprocessing import (
    compute_imputation_params,
    imputation_params_from_json,
    imputation_params_to_json,
    impute_features,
    impute_training_dataset,
    validate_inference_features,
    validate_training_dataset,
)
from shared.schemas.feature_schema import ALL_FEATURE_NAMES, IMPUTATION_FEATURE_NAMES


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_complete_features(value: float = 0.5) -> dict[str, float]:
    """Create a complete feature dict with all 30 features set to `value`."""
    return {name: value for name in ALL_FEATURE_NAMES}


def _make_training_df(n_rows: int = 100) -> pd.DataFrame:
    """Create a valid training DataFrame with all required columns."""
    rng = np.random.default_rng(42)
    data = {name: rng.random(n_rows) for name in ALL_FEATURE_NAMES}
    data["default_flag"] = rng.choice([0, 1], size=n_rows)
    data["max_successful_loan_ghs"] = rng.uniform(500, 10000, size=n_rows)
    data["income_tier"] = rng.choice([0, 1, 2, 3], size=n_rows)
    return pd.DataFrame(data)


# ── Tests: compute_imputation_params ────────────────────────────────────────

class TestComputeImputationParams:
    def test_returns_all_imputation_features(self):
        df = _make_training_df()
        params = compute_imputation_params(df)
        assert set(params.keys()) == set(IMPUTATION_FEATURE_NAMES)

    def test_median_features_get_median_value(self):
        df = _make_training_df()
        params = compute_imputation_params(df)
        # months_on_time_24m uses MEDIAN strategy
        expected = df["months_on_time_24m"].median()
        assert abs(params["months_on_time_24m"] - expected) < 1e-6

    def test_zero_features_get_zero(self):
        df = _make_training_df()
        params = compute_imputation_params(df)
        # worst_arrears_24m uses ZERO strategy
        assert params["worst_arrears_24m"] == 0.0
        assert params["has_judgement"] == 0.0
        assert params["num_bounced_cheques"] == 0.0
        assert params["has_adverse_default"] == 0.0
        assert params["product_diversity_score"] == 0.0

    def test_all_null_column_defaults_to_zero(self):
        df = _make_training_df()
        df["months_on_time_24m"] = np.nan
        params = compute_imputation_params(df)
        assert params["months_on_time_24m"] == 0.0


# ── Tests: imputation_params JSON round-trip ────────────────────────────────

class TestImputationParamsJson:
    def test_round_trip(self):
        original = {"months_on_time_24m": 0.75, "worst_arrears_24m": 0.0}
        json_str = imputation_params_to_json(original)
        restored = imputation_params_from_json(json_str)
        assert restored == original

    def test_from_json_bytes(self):
        raw = b'{"months_on_time_24m": 0.5}'
        params = imputation_params_from_json(raw)
        assert params["months_on_time_24m"] == 0.5


# ── Tests: impute_features (inference time) ─────────────────────────────────

class TestImputeFeatures:
    def test_complete_features_pass_through(self):
        features = _make_complete_features(0.7)
        params = {name: 0.0 for name in IMPUTATION_FEATURE_NAMES}
        result = impute_features(features, params)
        assert all(v == 0.7 for v in result.values())

    def test_null_imputable_features_get_filled(self):
        features = _make_complete_features(0.7)
        features["months_on_time_24m"] = None
        features["worst_arrears_24m"] = None
        params = {"months_on_time_24m": 0.55, "worst_arrears_24m": 0.0}
        result = impute_features(features, params)
        assert result["months_on_time_24m"] == 0.55
        assert result["worst_arrears_24m"] == 0.0

    def test_nan_values_get_imputed(self):
        features = _make_complete_features(0.7)
        features["address_stability"] = float("nan")
        params = {"address_stability": 0.42}
        result = impute_features(features, params)
        assert result["address_stability"] == 0.42

    def test_non_imputable_null_raises(self):
        features = _make_complete_features(0.7)
        features["highest_delinquency_rating"] = None  # Not imputable
        params = {name: 0.0 for name in IMPUTATION_FEATURE_NAMES}
        with pytest.raises(ValueError, match="no imputation rule"):
            impute_features(features, params)

    def test_output_has_all_30_features(self):
        features = _make_complete_features(0.5)
        params = {name: 0.0 for name in IMPUTATION_FEATURE_NAMES}
        result = impute_features(features, params)
        assert set(result.keys()) == set(ALL_FEATURE_NAMES)
        assert len(result) == 30


# ── Tests: validate_training_dataset ────────────────────────────────────────

class TestValidateTrainingDataset:
    def test_valid_dataset_no_errors(self):
        df = _make_training_df()
        errors = validate_training_dataset(df)
        assert errors == []

    def test_missing_feature_columns(self):
        df = _make_training_df()
        df = df.drop(columns=["highest_delinquency_rating", "applicant_age"])
        errors = validate_training_dataset(df)
        assert any("Missing feature columns" in e for e in errors)

    def test_missing_target_columns(self):
        df = _make_training_df()
        df = df.drop(columns=["default_flag"])
        errors = validate_training_dataset(df)
        assert any("Missing target columns" in e for e in errors)

    def test_empty_dataset(self):
        df = _make_training_df(0)
        errors = validate_training_dataset(df)
        assert any("empty" in e.lower() for e in errors)

    def test_non_numeric_feature(self):
        df = _make_training_df()
        df["applicant_age"] = "not_a_number"
        errors = validate_training_dataset(df)
        assert any("not numeric" in e for e in errors)


# ── Tests: validate_inference_features ──────────────────────────────────────

class TestValidateInferenceFeatures:
    def test_complete_features_no_errors(self):
        features = _make_complete_features()
        errors = validate_inference_features(features)
        assert errors == []

    def test_missing_features(self):
        features = _make_complete_features()
        del features["highest_delinquency_rating"]
        errors = validate_inference_features(features)
        assert any("Missing features" in e for e in errors)

    def test_null_imputable_feature_is_ok(self):
        features = _make_complete_features()
        features["months_on_time_24m"] = None  # Imputable
        errors = validate_inference_features(features)
        assert errors == []

    def test_null_non_imputable_feature_is_error(self):
        features = _make_complete_features()
        features["highest_delinquency_rating"] = None
        errors = validate_inference_features(features)
        assert any("no imputation rule" in e for e in errors)


# ── Tests: impute_training_dataset ──────────────────────────────────────────

class TestImputeTrainingDataset:
    def test_fills_nulls_and_returns_params(self):
        df = _make_training_df()
        # Inject some nulls in imputable columns
        df.loc[0:10, "months_on_time_24m"] = np.nan
        df.loc[5:15, "address_stability"] = np.nan

        df_imputed, params = impute_training_dataset(df)

        # No nulls in imputable columns after imputation
        for feat_name in IMPUTATION_FEATURE_NAMES:
            assert df_imputed[feat_name].isna().sum() == 0, f"{feat_name} still has nulls"

        # Params are present
        assert set(params.keys()) == set(IMPUTATION_FEATURE_NAMES)
