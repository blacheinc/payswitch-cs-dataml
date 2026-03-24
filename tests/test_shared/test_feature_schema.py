"""Tests for shared feature schema."""

from shared.schemas.feature_schema import (
    ALL_FEATURE_NAMES,
    FEATURE_BY_NAME,
    FEATURE_DEFINITIONS,
    FEATURES_BY_GROUP,
    FEATURES_REQUIRING_IMPUTATION,
    IMPUTATION_FEATURE_NAMES,
    PRODUCT_45_FEATURES,
    PRODUCT_49_FEATURES,
    FeatureGroup,
    ImputationStrategy,
)


class TestFeatureDefinitions:
    def test_exactly_30_features(self):
        assert len(FEATURE_DEFINITIONS) == 30

    def test_indices_are_1_to_30(self):
        indices = [f.index for f in FEATURE_DEFINITIONS]
        assert indices == list(range(1, 31))

    def test_names_are_unique(self):
        assert len(ALL_FEATURE_NAMES) == len(set(ALL_FEATURE_NAMES))

    def test_all_groups_represented(self):
        groups = {f.group for f in FEATURE_DEFINITIONS}
        assert groups == set(FeatureGroup)

    def test_group_a_has_6_features(self):
        assert len(FEATURES_BY_GROUP[FeatureGroup.A]) == 6

    def test_group_b_has_4_features(self):
        assert len(FEATURES_BY_GROUP[FeatureGroup.B]) == 4


class TestProductAvailability:
    def test_product_45_has_28_features(self):
        # Product 45 has all except mobile_loan_history_count and mobile_max_loan_ghs
        assert len(PRODUCT_45_FEATURES) == 28

    def test_product_49_has_22_features(self):
        assert len(PRODUCT_49_FEATURES) == 22

    def test_mobile_features_only_in_product_49(self):
        assert "mobile_loan_history_count" not in PRODUCT_45_FEATURES
        assert "mobile_max_loan_ghs" not in PRODUCT_45_FEATURES
        assert "mobile_loan_history_count" in PRODUCT_49_FEATURES
        assert "mobile_max_loan_ghs" in PRODUCT_49_FEATURES


class TestImputation:
    def test_8_features_require_imputation(self):
        assert len(FEATURES_REQUIRING_IMPUTATION) == 8

    def test_imputation_features_match_spec(self):
        expected = {
            "months_on_time_24m", "worst_arrears_24m", "current_streak_on_time",
            "product_diversity_score", "has_judgement", "num_bounced_cheques",
            "has_adverse_default", "address_stability",
        }
        assert set(IMPUTATION_FEATURE_NAMES) == expected

    def test_median_strategy_features(self):
        median_features = [
            f.name for f in FEATURES_REQUIRING_IMPUTATION
            if f.imputation_strategy == ImputationStrategy.MEDIAN
        ]
        assert set(median_features) == {
            "months_on_time_24m", "current_streak_on_time", "address_stability"
        }

    def test_zero_strategy_features(self):
        zero_features = [
            f.name for f in FEATURES_REQUIRING_IMPUTATION
            if f.imputation_strategy == ImputationStrategy.ZERO
        ]
        assert set(zero_features) == {
            "worst_arrears_24m", "product_diversity_score",
            "has_judgement", "num_bounced_cheques", "has_adverse_default",
        }
