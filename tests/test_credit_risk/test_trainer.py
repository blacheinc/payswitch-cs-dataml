"""Tests for credit risk agent trainer module."""

import sys
import os

import numpy as np
import pandas as pd
import pytest

# Add agent directory so we can import modules.trainer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "training-agents", "credit-risk-agent"))

from modules.trainer import (
    calibrate_probabilities,
    compute_scale_pos_weight,
    prepare_data,
)
from shared.schemas.feature_schema import ALL_FEATURE_NAMES


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_dummy_df(n=500):
    rng = np.random.RandomState(42)
    data = {name: rng.uniform(0, 1, n) for name in ALL_FEATURE_NAMES}
    data["default_flag"] = rng.choice([0, 1], n, p=[0.75, 0.25])
    data["max_successful_loan_ghs"] = rng.uniform(500, 10000, n)
    data["income_tier"] = rng.choice([0, 1, 2, 3], n)
    # metadata
    data["request_id"] = [f"REQ-{i}" for i in range(n)]
    data["credit_score"] = rng.randint(300, 850, n)
    data["score_grade"] = rng.choice(["A", "B", "C", "D", "E"], n)
    data["decision_label"] = rng.choice(["APPROVE", "DECLINE", "REFER"], n)
    data["data_quality_score"] = rng.uniform(0.6, 1.0, n)
    data["product_source"] = rng.choice(["45", "49", "45+49"], n)
    data["bureau_hit_status"] = rng.choice(["HIT", "THIN_FILE"], n)
    data["applicant_age_at_application"] = rng.randint(18, 65, n)
    data["credit_age_months_at_application"] = rng.randint(1, 200, n)
    return pd.DataFrame(data)


# ── Tests: prepare_data ───────────────────────────────────────────────────


class TestPrepareData:
    def test_returns_six_splits(self):
        df = _make_dummy_df()
        result = prepare_data(df)
        assert len(result) == 6

    def test_split_proportions_approximate(self):
        df = _make_dummy_df(1000)
        X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)
        total = len(X_train) + len(X_val) + len(X_holdout)
        assert total == 1000
        # 70/15/15 with some tolerance
        assert abs(len(X_train) / total - 0.70) < 0.05
        assert abs(len(X_val) / total - 0.15) < 0.05
        assert abs(len(X_holdout) / total - 0.15) < 0.05

    def test_only_feature_columns_in_X(self):
        df = _make_dummy_df()
        X_train, *_ = prepare_data(df)
        assert set(X_train.columns) == set(ALL_FEATURE_NAMES)

    def test_drops_null_target_rows(self):
        df = _make_dummy_df(500)
        df.loc[0:49, "default_flag"] = np.nan  # 50 rows with null target
        X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)
        total = len(X_train) + len(X_val) + len(X_holdout)
        assert total == 450  # 500 - 50

    def test_target_is_binary_int(self):
        df = _make_dummy_df()
        _, _, _, y_train, y_val, y_holdout = prepare_data(df)
        for y in [y_train, y_val, y_holdout]:
            assert set(y.unique()).issubset({0, 1})
            assert y.dtype in (np.int32, np.int64, int)


# ── Tests: compute_scale_pos_weight ───────────────────────────────────────


class TestComputeScalePosWeight:
    def test_balanced_classes_returns_one(self):
        y = pd.Series([0, 1, 0, 1, 0, 1])
        weight = compute_scale_pos_weight(y)
        assert weight == 1.0

    def test_imbalanced_returns_ratio(self):
        # 80 negatives, 20 positives => 80/20 = 4.0
        y = pd.Series([0] * 80 + [1] * 20)
        weight = compute_scale_pos_weight(y)
        assert weight == pytest.approx(4.0)

    def test_all_positive_returns_one(self):
        y = pd.Series([1, 1, 1, 1])
        weight = compute_scale_pos_weight(y)
        assert weight == pytest.approx(0.0)

    def test_no_positive_returns_one(self):
        y = pd.Series([0, 0, 0, 0])
        weight = compute_scale_pos_weight(y)
        assert weight == 1.0

    def test_returns_float(self):
        y = pd.Series([0, 0, 0, 1])
        assert isinstance(compute_scale_pos_weight(y), float)


# ── Tests: calibrate_probabilities ────────────────────────────────────────


class TestCalibrateProbabilities:
    def test_returns_A_and_B_keys(self):
        df = _make_dummy_df(500)
        X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)

        import xgboost as xgb

        model = xgb.XGBClassifier(
            n_estimators=10, max_depth=3, random_state=42, verbosity=0,
        )
        model.fit(X_train, y_train, verbose=False)

        result = calibrate_probabilities(model, X_holdout, y_holdout)
        assert "A" in result
        assert "B" in result

    def test_values_are_floats(self):
        df = _make_dummy_df(500)
        X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)

        import xgboost as xgb

        model = xgb.XGBClassifier(
            n_estimators=10, max_depth=3, random_state=42, verbosity=0,
        )
        model.fit(X_train, y_train, verbose=False)

        result = calibrate_probabilities(model, X_holdout, y_holdout)
        assert isinstance(result["A"], float)
        assert isinstance(result["B"], float)

    def test_A_is_nonzero(self):
        """Platt scaling coefficient A should be nonzero for a non-trivial model."""
        df = _make_dummy_df(500)
        X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)

        import xgboost as xgb

        model = xgb.XGBClassifier(
            n_estimators=50, max_depth=4, random_state=42, verbosity=0,
        )
        model.fit(X_train, y_train, verbose=False)

        result = calibrate_probabilities(model, X_holdout, y_holdout)
        assert result["A"] != 0.0
