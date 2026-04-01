"""Tests for shared.fairness module."""

import numpy as np
import pandas as pd
import pytest

from shared.fairness import (
    _map_age_group,
    compute_disparate_impact,
    compute_equal_opportunity,
    run_fairness_checks,
)
from shared.schemas.feature_schema import ALL_FEATURE_NAMES


class TestMapAgeGroup:
    def test_prime(self):
        assert _map_age_group(1.00) == "PRIME"

    def test_young(self):
        assert _map_age_group(0.70) == "YOUNG"

    def test_mature(self):
        assert _map_age_group(0.90) == "MATURE"

    def test_senior(self):
        assert _map_age_group(0.65) == "SENIOR"

    def test_ineligible(self):
        assert _map_age_group(0.00) == "INELIGIBLE"

    def test_close_match(self):
        assert _map_age_group(0.71) == "YOUNG"  # Within 0.05 tolerance


class TestDisparateImpact:
    def test_equal_rates(self):
        y_pred = np.array([1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0])
        groups = pd.Series(["A", "A", "A", "A", "A", "A", "B", "B", "B", "B", "B", "B"])
        result = compute_disparate_impact(y_pred, groups)
        assert result["di_ratio"] >= 0.80
        assert not result["violation"]

    def test_unequal_rates_violation(self):
        y_pred = np.array([1]*10 + [0]*10 + [1]*2 + [0]*8)
        groups = pd.Series(["A"]*20 + ["B"]*10)
        result = compute_disparate_impact(y_pred, groups)
        # A: 50% approval, B: 20% approval → DI = 0.20/0.50 = 0.40
        assert result["violation"]
        assert result["di_ratio"] < 0.80

    def test_skips_ineligible(self):
        y_pred = np.array([1]*10 + [0]*10)
        groups = pd.Series(["INELIGIBLE"]*10 + ["PRIME"]*10)
        result = compute_disparate_impact(y_pred, groups)
        assert "INELIGIBLE" not in result["group_rates"]

    def test_insufficient_samples(self):
        y_pred = np.array([1, 0, 1])
        groups = pd.Series(["A", "A", "B"])
        result = compute_disparate_impact(y_pred, groups)
        # Too few per group — should not violate


class TestEqualOpportunity:
    def test_equal_fnr(self):
        y_true = np.array([1, 1, 1, 0, 0, 1, 1, 1, 0, 0])
        y_pred = np.array([1, 1, 0, 0, 0, 1, 1, 0, 0, 0])
        groups = pd.Series(["A"]*5 + ["B"]*5)
        result = compute_equal_opportunity(y_true, y_pred, groups)
        assert result["max_gap"] <= 0.10

    def test_unequal_fnr_violation(self):
        # Group A: FNR = 0 (all positives correctly classified)
        # Group B: FNR = 1.0 (all positives missed)
        y_true = np.array([1, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0])
        y_pred = np.array([1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        groups = pd.Series(["A"]*8 + ["B"]*8)
        result = compute_equal_opportunity(y_true, y_pred, groups)
        assert result["violation"]


class TestRunFairnessChecks:
    def _make_features(self, n=200):
        rng = np.random.RandomState(42)
        data = {name: rng.uniform(0, 1, n) for name in ALL_FEATURE_NAMES}
        # Mix of age groups
        data["applicant_age"] = rng.choice([0.70, 1.00, 0.90, 0.65], n, p=[0.2, 0.4, 0.3, 0.1])
        return pd.DataFrame(data)

    def test_returns_all_fields(self):
        features = self._make_features()
        y_true = np.random.RandomState(42).choice([0, 1], len(features))
        y_pred = np.random.RandomState(43).uniform(0, 1, len(features))
        result = run_fairness_checks(y_true, y_pred, features)
        assert "disparate_impact" in result
        assert "equal_opportunity" in result
        assert "violations" in result
        assert "passed" in result

    def test_perfect_fairness_passes(self):
        n = 200
        features = self._make_features(n)
        y_true = np.zeros(n)
        y_pred = np.full(n, 0.3)  # All same prediction → identical rates
        result = run_fairness_checks(y_true, y_pred, features)
        assert result["passed"]
