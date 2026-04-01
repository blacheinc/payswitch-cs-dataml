"""Tests for credit risk agent validator module."""

import sys
import os

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "training-agents", "credit-risk-agent"))

from modules.trainer import prepare_data
from modules.validator import check_thresholds, evaluate_model, METRIC_THRESHOLDS
from shared.schemas.feature_schema import ALL_FEATURE_NAMES


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_dummy_df(n=500):
    rng = np.random.RandomState(42)
    data = {name: rng.uniform(0, 1, n) for name in ALL_FEATURE_NAMES}
    data["default_flag"] = rng.choice([0, 1], n, p=[0.75, 0.25])
    data["max_successful_loan_ghs"] = rng.uniform(500, 10000, n)
    data["income_tier"] = rng.choice([0, 1, 2, 3], n)
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


def _train_quick_model():
    """Train a small XGBoost model for validator tests."""
    import xgboost as xgb

    df = _make_dummy_df(500)
    X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)

    model = xgb.XGBClassifier(
        n_estimators=50, max_depth=4, random_state=42, verbosity=0,
    )
    model.fit(X_train, y_train, verbose=False)
    return model, X_holdout, y_holdout


# ── Tests: evaluate_model ─────────────────────────────────────────────────


class TestEvaluateModel:
    def test_returns_expected_keys(self):
        model, X_holdout, y_holdout = _train_quick_model()
        metrics = evaluate_model(model, X_holdout, y_holdout)
        assert "auc" in metrics
        assert "f1" in metrics
        assert "precision" in metrics
        assert "recall" in metrics
        assert "log_loss" in metrics

    def test_auc_between_zero_and_one(self):
        model, X_holdout, y_holdout = _train_quick_model()
        metrics = evaluate_model(model, X_holdout, y_holdout)
        assert 0.0 <= metrics["auc"] <= 1.0

    def test_all_metrics_are_floats(self):
        model, X_holdout, y_holdout = _train_quick_model()
        metrics = evaluate_model(model, X_holdout, y_holdout)
        for key in ["auc", "f1", "precision", "recall", "log_loss"]:
            assert isinstance(metrics[key], float)

    def test_f1_precision_recall_bounded(self):
        model, X_holdout, y_holdout = _train_quick_model()
        metrics = evaluate_model(model, X_holdout, y_holdout)
        for key in ["f1", "precision", "recall"]:
            assert 0.0 <= metrics[key] <= 1.0

    def test_log_loss_is_positive(self):
        model, X_holdout, y_holdout = _train_quick_model()
        metrics = evaluate_model(model, X_holdout, y_holdout)
        assert metrics["log_loss"] > 0.0


# ── Tests: check_thresholds ──────────────────────────────────────────────


class TestCheckThresholds:
    def test_all_passing_returns_empty(self):
        metrics = {
            "auc": 0.90,
            "f1": 0.85,
            "precision": 0.80,
            "recall": 0.75,
            "log_loss": 0.30,
        }
        warnings = check_thresholds(metrics)
        assert warnings == []

    def test_auc_below_threshold(self):
        metrics = {
            "auc": 0.70,  # below 0.78
            "f1": 0.85,
            "precision": 0.80,
            "recall": 0.75,
            "log_loss": 0.30,
        }
        warnings = check_thresholds(metrics)
        assert len(warnings) == 1
        assert "AUC" in warnings[0]

    def test_multiple_failures(self):
        metrics = {
            "auc": 0.50,
            "f1": 0.50,
            "precision": 0.50,
            "recall": 0.50,
            "log_loss": 0.80,
        }
        warnings = check_thresholds(metrics)
        assert len(warnings) == 5  # all metrics fail

    def test_log_loss_above_max(self):
        metrics = {
            "auc": 0.90,
            "f1": 0.85,
            "precision": 0.80,
            "recall": 0.75,
            "log_loss": 0.60,  # above 0.50
        }
        warnings = check_thresholds(metrics)
        assert len(warnings) == 1
        assert "LogLoss" in warnings[0]

    def test_boundary_values_pass(self):
        """Metrics exactly at threshold should pass."""
        metrics = {
            "auc": 0.78,
            "f1": 0.75,
            "precision": 0.70,
            "recall": 0.65,
            "log_loss": 0.50,
        }
        warnings = check_thresholds(metrics)
        assert warnings == []
