"""Tests for fraud detection agent trainer module."""

import importlib.util
import os
import sys

import numpy as np
import pandas as pd
import pytest

from shared.schemas.feature_schema import ALL_FEATURE_NAMES

# Load fraud-detection trainer by file path (avoids collision with credit-risk modules)
_agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "training-agents", "fraud-detection-agent"))
_spec = importlib.util.spec_from_file_location("fd_trainer", os.path.join(_agent_dir, "modules", "trainer.py"),
                                                submodule_search_locations=[_agent_dir])
_trainer = importlib.util.module_from_spec(_spec)
sys.modules["fd_trainer"] = _trainer
_spec.loader.exec_module(_trainer)

prepare_data = _trainer.prepare_data
classify_fraud_flag = _trainer.classify_fraud_flag
normalize_anomaly_score = _trainer.normalize_anomaly_score


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


# ── Tests: prepare_data ───────────────────────────────────────────────────


class TestPrepareData:
    def test_returns_two_dataframes(self):
        df = _make_dummy_df()
        result = prepare_data(df)
        assert len(result) == 2
        X_full, X_holdout = result
        assert isinstance(X_full, pd.DataFrame)
        assert isinstance(X_holdout, pd.DataFrame)

    def test_full_set_is_entire_dataset(self):
        df = _make_dummy_df(500)
        X_full, _ = prepare_data(df)
        assert len(X_full) == 500

    def test_holdout_is_15_percent(self):
        df = _make_dummy_df(1000)
        _, X_holdout = prepare_data(df)
        assert abs(len(X_holdout) / 1000 - 0.15) < 0.03

    def test_only_feature_columns(self):
        df = _make_dummy_df()
        X_full, X_holdout = prepare_data(df)
        assert set(X_full.columns) == set(ALL_FEATURE_NAMES)
        assert set(X_holdout.columns) == set(ALL_FEATURE_NAMES)


# ── Tests: classify_fraud_flag ────────────────────────────────────────────


class TestClassifyFraudFlag:
    """
    Isolation Forest scores are negative. More negative = more anomalous.
    medium_high_boundary (P1) < low_medium_boundary (P5) < 0.
    """

    def setup_method(self):
        self.thresholds = {
            "low_medium_boundary": -0.10,   # P5
            "medium_high_boundary": -0.20,  # P1
        }

    def test_high_flag_for_very_anomalous(self):
        # Score below P1 boundary => HIGH
        assert classify_fraud_flag(-0.25, self.thresholds) == "HIGH"

    def test_medium_flag_for_moderately_anomalous(self):
        # Score between P1 and P5 => MEDIUM
        assert classify_fraud_flag(-0.15, self.thresholds) == "MEDIUM"

    def test_low_flag_for_normal(self):
        # Score above P5 boundary => LOW
        assert classify_fraud_flag(-0.05, self.thresholds) == "LOW"

    def test_boundary_at_medium_high(self):
        # Exactly at P1 boundary: score < boundary is HIGH, score == boundary is MEDIUM
        assert classify_fraud_flag(-0.20, self.thresholds) == "MEDIUM"

    def test_boundary_at_low_medium(self):
        # Exactly at P5 boundary: score < boundary is MEDIUM, score == boundary is LOW
        assert classify_fraud_flag(-0.10, self.thresholds) == "LOW"


# ── Tests: normalize_anomaly_score ────────────────────────────────────────


class TestNormalizeAnomalyScore:
    def test_most_anomalous_gives_one(self):
        # min_score is most anomalous; normalized should be 1.0 (most suspicious)
        result = normalize_anomaly_score(-0.50, min_score=-0.50, max_score=0.0)
        assert result == pytest.approx(1.0)

    def test_least_anomalous_gives_zero(self):
        # max_score is least anomalous; normalized should be 0.0
        result = normalize_anomaly_score(0.0, min_score=-0.50, max_score=0.0)
        assert result == pytest.approx(0.0)

    def test_midpoint(self):
        result = normalize_anomaly_score(-0.25, min_score=-0.50, max_score=0.0)
        assert result == pytest.approx(0.5)

    def test_equal_min_max_returns_half(self):
        result = normalize_anomaly_score(-0.10, min_score=-0.10, max_score=-0.10)
        assert result == pytest.approx(0.5)

    def test_clipped_to_zero_one(self):
        # Score beyond range should be clipped
        result = normalize_anomaly_score(0.5, min_score=-0.50, max_score=0.0)
        assert result == pytest.approx(0.0)
