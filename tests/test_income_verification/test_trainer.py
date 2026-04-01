"""Tests for income verification agent trainer module."""

import importlib.util
import os
import sys

import numpy as np
import pandas as pd
import pytest

from shared.schemas.feature_schema import ALL_FEATURE_NAMES

_agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "training-agents", "income-verification-agent"))
_spec = importlib.util.spec_from_file_location("iv_trainer", os.path.join(_agent_dir, "modules", "trainer.py"),
                                                submodule_search_locations=[_agent_dir])
_trainer = importlib.util.module_from_spec(_spec)
sys.modules["iv_trainer"] = _trainer
_spec.loader.exec_module(_trainer)

prepare_data = _trainer.prepare_data
NUM_CLASSES = _trainer.NUM_CLASSES


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
    def test_returns_six_splits(self):
        df = _make_dummy_df()
        result = prepare_data(df)
        assert len(result) == 6

    def test_split_proportions_approximate(self):
        df = _make_dummy_df(1000)
        X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)
        total = len(X_train) + len(X_val) + len(X_holdout)
        assert total == 1000
        assert abs(len(X_train) / total - 0.70) < 0.05
        assert abs(len(X_val) / total - 0.15) < 0.05
        assert abs(len(X_holdout) / total - 0.15) < 0.05

    def test_drops_null_target_rows(self):
        df = _make_dummy_df(500)
        df.loc[0:49, "income_tier"] = np.nan
        X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)
        total = len(X_train) + len(X_val) + len(X_holdout)
        assert total == 450

    def test_target_has_four_classes(self):
        df = _make_dummy_df(1000)
        _, _, _, y_train, y_val, y_holdout = prepare_data(df)
        all_y = pd.concat([y_train, y_val, y_holdout])
        assert set(all_y.unique()) == {0, 1, 2, 3}
        assert NUM_CLASSES == 4

    def test_target_is_int(self):
        df = _make_dummy_df()
        _, _, _, y_train, _, _ = prepare_data(df)
        assert y_train.dtype in (np.int32, np.int64, int)

    def test_only_feature_columns_in_X(self):
        df = _make_dummy_df()
        X_train, *_ = prepare_data(df)
        assert set(X_train.columns) == set(ALL_FEATURE_NAMES)

    def test_stratified_split_preserves_class_proportions(self):
        """Each split should have roughly the same class distribution."""
        df = _make_dummy_df(2000)
        _, _, _, y_train, y_val, y_holdout = prepare_data(df)

        train_dist = y_train.value_counts(normalize=True).sort_index()
        val_dist = y_val.value_counts(normalize=True).sort_index()
        holdout_dist = y_holdout.value_counts(normalize=True).sort_index()

        for cls in [0, 1, 2, 3]:
            # Each class proportion should be within 5% of training set proportion
            assert abs(train_dist[cls] - val_dist[cls]) < 0.05
            assert abs(train_dist[cls] - holdout_dist[cls]) < 0.05
