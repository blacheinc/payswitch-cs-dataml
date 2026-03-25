"""
Feature schema for the PaySwitch Credit Scoring Engine.

Defines all 30 features from XDS credit bureau data (Ghana),
their groups, weights, product availability, and imputation rules.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FeatureGroup(str, Enum):
    """Feature groups with their weight contributions to credit scoring."""
    A = "A"  # Payment History (35%)
    B = "B"  # Current Exposure (25%)
    C = "C"  # Credit History Depth (15%)
    D = "D"  # Adverse Records (15%)
    E = "E"  # Enquiry Activity (5%)
    F = "F"  # Demographics (5%)


GROUP_WEIGHTS: dict[FeatureGroup, float] = {
    FeatureGroup.A: 0.35,
    FeatureGroup.B: 0.25,
    FeatureGroup.C: 0.15,
    FeatureGroup.D: 0.15,
    FeatureGroup.E: 0.05,
    FeatureGroup.F: 0.05,
}


class ImputationStrategy(str, Enum):
    """How to impute missing values for Product 49-only records."""
    MEDIAN = "median"       # Use median from training data
    ZERO = "zero"           # Fill with 0
    NONE = "none"           # Feature is always available or not imputed


@dataclass(frozen=True)
class FeatureDefinition:
    """Definition of a single feature in the credit scoring feature set."""
    name: str
    index: int                          # 1-30
    group: FeatureGroup
    available_product_45: bool
    available_product_49: bool
    imputation_strategy: ImputationStrategy = ImputationStrategy.NONE
    description: str = ""


# ── All 30 Feature Definitions ─────────────────────────────────────────────

FEATURE_DEFINITIONS: list[FeatureDefinition] = [
    # ── Group A: Payment History (35%) ──────────────────────────────────────
    FeatureDefinition(
        name="highest_delinquency_rating",
        index=1, group=FeatureGroup.A,
        available_product_45=True, available_product_49=True,
        description="Worst delinquency rating across all accounts",
    ),
    FeatureDefinition(
        name="months_on_time_24m",
        index=2, group=FeatureGroup.A,
        available_product_45=True, available_product_49=False,
        imputation_strategy=ImputationStrategy.MEDIAN,
        description="Number of on-time payment months in last 24 months",
    ),
    FeatureDefinition(
        name="worst_arrears_24m",
        index=3, group=FeatureGroup.A,
        available_product_45=True, available_product_49=False,
        imputation_strategy=ImputationStrategy.ZERO,
        description="Worst arrears months in last 24 months",
    ),
    FeatureDefinition(
        name="current_streak_on_time",
        index=4, group=FeatureGroup.A,
        available_product_45=True, available_product_49=False,
        imputation_strategy=ImputationStrategy.MEDIAN,
        description="Current consecutive on-time payment streak",
    ),
    FeatureDefinition(
        name="has_active_arrears",
        index=5, group=FeatureGroup.A,
        available_product_45=True, available_product_49=True,
        description="Whether applicant has any active arrears (0/1)",
    ),
    FeatureDefinition(
        name="total_arrear_amount_ghs",
        index=6, group=FeatureGroup.A,
        available_product_45=True, available_product_49=True,
        description="Total arrear amount in GHS",
    ),

    # ── Group B: Current Exposure (25%) ─────────────────────────────────────
    FeatureDefinition(
        name="total_outstanding_debt_ghs",
        index=7, group=FeatureGroup.B,
        available_product_45=True, available_product_49=True,
        description="Total outstanding debt in GHS",
    ),
    FeatureDefinition(
        name="utilisation_ratio",
        index=8, group=FeatureGroup.B,
        available_product_45=True, available_product_49=True,
        description="Credit utilisation ratio (0-1)",
    ),
    FeatureDefinition(
        name="num_active_accounts",
        index=9, group=FeatureGroup.B,
        available_product_45=True, available_product_49=True,
        description="Number of active credit accounts",
    ),
    FeatureDefinition(
        name="total_monthly_instalment_ghs",
        index=10, group=FeatureGroup.B,
        available_product_45=True, available_product_49=True,
        description="Total monthly instalment obligations in GHS",
    ),

    # ── Group C: Credit History Depth (15%) ─────────────────────────────────
    FeatureDefinition(
        name="credit_age_months",
        index=11, group=FeatureGroup.C,
        available_product_45=True, available_product_49=True,
        description="Age of credit history in months",
    ),
    FeatureDefinition(
        name="num_accounts_total",
        index=12, group=FeatureGroup.C,
        available_product_45=True, available_product_49=True,
        description="Total number of credit accounts (open + closed)",
    ),
    FeatureDefinition(
        name="num_closed_accounts_good",
        index=13, group=FeatureGroup.C,
        available_product_45=True, available_product_49=True,
        description="Number of closed accounts in good standing (C/P)",
    ),
    FeatureDefinition(
        name="product_diversity_score",
        index=14, group=FeatureGroup.C,
        available_product_45=True, available_product_49=False,
        imputation_strategy=ImputationStrategy.ZERO,
        description="Diversity of credit product types (0-1)",
    ),
    FeatureDefinition(
        name="mobile_loan_history_count",
        index=15, group=FeatureGroup.C,
        available_product_45=False, available_product_49=True,
        imputation_strategy=ImputationStrategy.ZERO,
        description="Number of mobile loan accounts",
    ),
    FeatureDefinition(
        name="mobile_max_loan_ghs",
        index=16, group=FeatureGroup.C,
        available_product_45=False, available_product_49=True,
        imputation_strategy=ImputationStrategy.ZERO,
        description="Maximum mobile loan amount in GHS",
    ),

    # ── Group D: Adverse Records (15%) ──────────────────────────────────────
    FeatureDefinition(
        name="has_judgement",
        index=17, group=FeatureGroup.D,
        available_product_45=True, available_product_49=False,
        imputation_strategy=ImputationStrategy.ZERO,
        description="Whether applicant has any court judgements (0/1)",
    ),
    FeatureDefinition(
        name="has_written_off",
        index=18, group=FeatureGroup.D,
        available_product_45=True, available_product_49=True,
        description="Whether applicant has any written-off accounts (0/1)",
    ),
    FeatureDefinition(
        name="has_charged_off",
        index=19, group=FeatureGroup.D,
        available_product_45=True, available_product_49=True,
        description="Whether applicant has any charged-off accounts (0/1)",
    ),
    FeatureDefinition(
        name="has_legal_handover",
        index=20, group=FeatureGroup.D,
        available_product_45=True, available_product_49=True,
        description="Whether applicant has any legal handover accounts (0/1)",
    ),
    FeatureDefinition(
        name="num_bounced_cheques",
        index=21, group=FeatureGroup.D,
        available_product_45=True, available_product_49=False,
        imputation_strategy=ImputationStrategy.ZERO,
        description="Number of bounced cheques on record",
    ),
    FeatureDefinition(
        name="has_adverse_default",
        index=22, group=FeatureGroup.D,
        available_product_45=True, available_product_49=False,
        imputation_strategy=ImputationStrategy.ZERO,
        description="Whether applicant has any adverse default records (0/1)",
    ),

    # ── Group E: Enquiry Activity (5%) ──────────────────────────────────────
    FeatureDefinition(
        name="num_enquiries_3m",
        index=23, group=FeatureGroup.E,
        available_product_45=True, available_product_49=True,
        description="Number of credit enquiries in last 3 months",
    ),
    FeatureDefinition(
        name="num_enquiries_12m",
        index=24, group=FeatureGroup.E,
        available_product_45=True, available_product_49=True,
        description="Number of credit enquiries in last 12 months",
    ),
    FeatureDefinition(
        name="enquiry_reason_flags",
        index=25, group=FeatureGroup.E,
        available_product_45=True, available_product_49=True,
        description="Encoded enquiry reason flags",
    ),

    # ── Group F: Demographics (5%) ──────────────────────────────────────────
    FeatureDefinition(
        name="applicant_age",
        index=26, group=FeatureGroup.F,
        available_product_45=True, available_product_49=True,
        description="Applicant age at time of application",
    ),
    FeatureDefinition(
        name="identity_verified",
        index=27, group=FeatureGroup.F,
        available_product_45=True, available_product_49=True,
        description="Whether identity has been verified (0/1)",
    ),
    FeatureDefinition(
        name="num_dependants",
        index=28, group=FeatureGroup.F,
        available_product_45=True, available_product_49=True,
        description="Number of dependants",
    ),
    FeatureDefinition(
        name="has_employer_detail",
        index=29, group=FeatureGroup.F,
        available_product_45=True, available_product_49=True,
        description="Whether employer details are on file (0/1)",
    ),
    FeatureDefinition(
        name="address_stability",
        index=30, group=FeatureGroup.F,
        available_product_45=True, available_product_49=False,
        imputation_strategy=ImputationStrategy.MEDIAN,
        description="Address stability score (0-1)",
    ),
]


# ── Convenience Lookups ─────────────────────────────────────────────────────

# Ordered list of all 30 feature names (canonical column order)
ALL_FEATURE_NAMES: list[str] = [f.name for f in FEATURE_DEFINITIONS]

# Lookup by name
FEATURE_BY_NAME: dict[str, FeatureDefinition] = {f.name: f for f in FEATURE_DEFINITIONS}

# Features that require imputation (Product 49-only nulls)
FEATURES_REQUIRING_IMPUTATION: list[FeatureDefinition] = [
    f for f in FEATURE_DEFINITIONS
    if f.imputation_strategy != ImputationStrategy.NONE
]

# Feature names that require imputation
IMPUTATION_FEATURE_NAMES: list[str] = [f.name for f in FEATURES_REQUIRING_IMPUTATION]

# Features by group
FEATURES_BY_GROUP: dict[FeatureGroup, list[FeatureDefinition]] = {}
for _feat in FEATURE_DEFINITIONS:
    FEATURES_BY_GROUP.setdefault(_feat.group, []).append(_feat)

# Features available per product
PRODUCT_45_FEATURES: list[str] = [f.name for f in FEATURE_DEFINITIONS if f.available_product_45]
PRODUCT_49_FEATURES: list[str] = [f.name for f in FEATURE_DEFINITIONS if f.available_product_49]
