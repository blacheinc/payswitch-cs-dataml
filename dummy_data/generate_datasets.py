"""
Generate synthetic training datasets for the PaySwitch Credit Scoring Engine.

Creates 3 parquet files matching the DE contract:
1. clean_50k.parquet   — 50k records, all features + targets populated, no nulls
2. missing_10k.parquet — 10k records with realistic Product 45/49 gaps + some null targets
3. broken_1k.parquet   — 1k records with validation errors (missing columns, bad types)

Feature values use the actual bin weights from Section 2 of the
Credit Scoring Engine Model Parameters PDF.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── Bin definitions per Section 2 of the PDF ────────────────────────────────
# Each feature maps to (possible_values, probability_weights)
# Values are the actual 0-1 bin weights from the document.

FEATURE_BINS = {
    # Group A: Payment History (35%)
    "highest_delinquency_rating": {
        "values": [1.00, 0.85, 0.70, 0.50, 0.00],
        "weights": [0.40, 0.20, 0.15, 0.15, 0.10],  # Most have no delinquency
    },
    "months_on_time_24m": {
        "values": [1.00, 0.80, 0.55, 0.25, 0.00],
        "weights": [0.30, 0.30, 0.20, 0.15, 0.05],
    },
    "worst_arrears_24m": {
        "values": [1.00, 0.70, 0.40, 0.15, 0.00],
        "weights": [0.50, 0.20, 0.15, 0.10, 0.05],
    },
    "current_streak_on_time": {
        "values": [1.00, 0.75, 0.45, 0.20],
        "weights": [0.25, 0.30, 0.25, 0.20],
    },
    "has_active_arrears": {
        "values": [1.00, 0.00],  # No=1.00, Yes=0.00
        "weights": [0.75, 0.25],
    },
    "total_arrear_amount_ghs": {
        "values": [1.00, 0.70, 0.35, 0.10, 0.00],
        "weights": [0.55, 0.20, 0.12, 0.08, 0.05],
    },
    # Group B: Exposure (25%)
    "total_outstanding_debt_ghs": {
        "values": [1.00, 0.80, 0.60, 0.30, 0.05],
        "weights": [0.15, 0.30, 0.25, 0.20, 0.10],
    },
    "utilisation_ratio": {
        "values": [1.00, 0.80, 0.50, 0.20, 0.05],
        "weights": [0.20, 0.25, 0.25, 0.20, 0.10],
    },
    "num_active_accounts": {
        "values": [0.85, 1.00, 0.55, 0.15],
        "weights": [0.30, 0.35, 0.25, 0.10],
    },
    "total_monthly_instalment_ghs": {
        "values": [1.00, 0.85, 0.60, 0.30, 0.05],
        "weights": [0.20, 0.30, 0.25, 0.15, 0.10],
    },
    # Group C: Credit Depth (15%)
    "credit_age_months": {
        "values": [1.00, 0.85, 0.65, 0.40, 0.15],
        "weights": [0.10, 0.25, 0.30, 0.20, 0.15],
    },
    "num_accounts_total": {
        "values": [1.00, 0.80, 0.55, 0.30, 0.00],
        "weights": [0.10, 0.25, 0.25, 0.25, 0.15],
    },
    "num_closed_accounts_good": {
        "values": [1.00, 0.75, 0.45, 0.10],
        "weights": [0.15, 0.25, 0.30, 0.30],
    },
    "product_diversity_score": {
        "values": [1.00, 0.80, 0.55, 0.30],
        "weights": [0.10, 0.20, 0.30, 0.40],
    },
    "mobile_loan_history_count": {
        "values": [1.00, 0.95, 0.85, 0.60, 0.20],
        "weights": [0.10, 0.15, 0.25, 0.30, 0.20],
    },
    "mobile_max_loan_ghs": {
        "values": [0.65, 0.50, 0.35, 0.20],  # Small-to-medium mobile loans typical
        "weights": [0.20, 0.30, 0.30, 0.20],
    },
    # Group D: Adverse (15%)
    "has_judgement": {
        "values": [1.00, 0.00],  # 0=No judgement (1.00), 1=Has judgement (0.00 = HARD STOP)
        "weights": [0.92, 0.08],
    },
    "has_written_off": {
        "values": [1.00, 0.00],
        "weights": [0.90, 0.10],
    },
    "has_charged_off": {
        "values": [1.00, 0.00],
        "weights": [0.88, 0.12],
    },
    "has_legal_handover": {
        "values": [1.00, 0.00],
        "weights": [0.93, 0.07],
    },
    "num_bounced_cheques": {
        "values": [1.00, 0.80, 0.50, 0.00],  # 0 cheques → 1.00, etc.
        "weights": [0.85, 0.08, 0.04, 0.03],
    },
    "has_adverse_default": {
        "values": [1.00, 0.00],
        "weights": [0.85, 0.15],
    },
    # Group E: Enquiries (5%)
    "num_enquiries_3m": {
        "values": [1.00, 0.75, 0.35, 0.05],
        "weights": [0.45, 0.30, 0.15, 0.10],
    },
    "num_enquiries_12m": {
        "values": [1.00, 0.80, 0.40, 0.10],
        "weights": [0.35, 0.30, 0.20, 0.15],
    },
    "enquiry_reason_flags": {
        "values": [0.90, 0.70, 0.50, 0.30, 0.10],
        "weights": [0.25, 0.25, 0.25, 0.15, 0.10],
    },
    # Group F: Demographics (5%)
    "applicant_age": {
        "values": [0.00, 0.70, 1.00, 0.90, 0.65, 0.00],  # Ineligible/Young/Prime/Mature/Senior/Ineligible
        "weights": [0.01, 0.20, 0.40, 0.25, 0.13, 0.01],
    },
    "identity_verified": {
        "values": [1.00, 0.00],
        "weights": [0.90, 0.10],
    },
    "num_dependants": {
        "values": [1.00, 0.85, 0.65, 0.40],
        "weights": [0.25, 0.35, 0.25, 0.15],
    },
    "has_employer_detail": {
        "values": [1.00, 0.60],
        "weights": [0.65, 0.35],
    },
    "address_stability": {
        "values": [1.00, 0.75, 0.40],
        "weights": [0.50, 0.30, 0.20],
    },
}

# Feature groups and their weight contribution to credit score
GROUP_WEIGHTS = {
    "A": 0.35,
    "B": 0.25,
    "C": 0.15,
    "D": 0.15,
    "E": 0.05,
    "F": 0.05,
}

FEATURE_GROUPS = {
    "highest_delinquency_rating": "A", "months_on_time_24m": "A",
    "worst_arrears_24m": "A", "current_streak_on_time": "A",
    "has_active_arrears": "A", "total_arrear_amount_ghs": "A",
    "total_outstanding_debt_ghs": "B", "utilisation_ratio": "B",
    "num_active_accounts": "B", "total_monthly_instalment_ghs": "B",
    "credit_age_months": "C", "num_accounts_total": "C",
    "num_closed_accounts_good": "C", "product_diversity_score": "C",
    "mobile_loan_history_count": "C", "mobile_max_loan_ghs": "C",
    "has_judgement": "D", "has_written_off": "D",
    "has_charged_off": "D", "has_legal_handover": "D",
    "num_bounced_cheques": "D", "has_adverse_default": "D",
    "num_enquiries_3m": "E", "num_enquiries_12m": "E",
    "enquiry_reason_flags": "E",
    "applicant_age": "F", "identity_verified": "F",
    "num_dependants": "F", "has_employer_detail": "F",
    "address_stability": "F",
}

FEATURE_NAMES = list(FEATURE_BINS.keys())

# Product 49-only missing features (8)
PRODUCT_49_MISSING = [
    "months_on_time_24m", "worst_arrears_24m", "current_streak_on_time",
    "product_diversity_score", "has_judgement", "num_bounced_cheques",
    "has_adverse_default", "address_stability",
]

# Product 45-only missing features (2)
PRODUCT_45_MISSING = [
    "mobile_loan_history_count", "mobile_max_loan_ghs",
]


def generate_features(rng: np.random.Generator, n: int) -> pd.DataFrame:
    """Generate n rows of binned feature values using PDF weights."""
    data = {}
    for feat_name, bins in FEATURE_BINS.items():
        values = bins["values"]
        weights = bins["weights"]
        data[feat_name] = rng.choice(values, size=n, p=weights)
    return pd.DataFrame(data)


def compute_credit_score(features: pd.DataFrame) -> np.ndarray:
    """
    Compute credit score (300-850) from weighted feature averages.
    credit_score = 300 + (550 * weighted_ensemble_score)
    """
    group_scores = {}
    for group in GROUP_WEIGHTS:
        group_features = [f for f, g in FEATURE_GROUPS.items() if g == group]
        group_avg = features[group_features].mean(axis=1)
        group_scores[group] = group_avg * GROUP_WEIGHTS[group]

    ensemble_score = sum(group_scores.values())
    return (300 + 550 * ensemble_score).round().astype(int).clip(300, 850)


def score_to_grade(score: int) -> str:
    if score >= 750: return "A"
    if score >= 700: return "B"
    if score >= 650: return "C"
    if score >= 600: return "D"
    if score >= 520: return "E"
    return "F"


def grade_to_decision(grade: str) -> str:
    return {
        "A": "APPROVE", "B": "APPROVE", "C": "APPROVE",
        "D": "CONDITIONAL_APPROVE", "E": "REFER", "F": "DECLINE",
    }[grade]


def generate_targets(
    rng: np.random.Generator,
    features: pd.DataFrame,
    n: int,
) -> pd.DataFrame:
    """Generate target columns correlated with features."""
    # default_flag: ~25% default rate, correlated with adverse features
    # Lower feature values = worse profile = higher default probability
    risk_score = (
        (1 - features["has_active_arrears"]) * 0.25
        + (1 - features["highest_delinquency_rating"]) * 0.20
        + (1 - features["has_written_off"]) * 0.15
        + (1 - features["has_charged_off"]) * 0.10
        + (1 - features["worst_arrears_24m"]) * 0.10
        + (1 - features["months_on_time_24m"]) * 0.10
        + (1 - features["has_adverse_default"]) * 0.10
    )
    # Add noise and calibrate to ~25% default rate
    default_prob = risk_score + rng.normal(0, 0.15, size=n)
    default_flag = (default_prob > np.percentile(default_prob, 75)).astype(int)

    # max_successful_loan_ghs: correlated with credit depth + income signals
    loan_base = (
        features["credit_age_months"] * 2000
        + features["num_closed_accounts_good"] * 3000
        + features["total_outstanding_debt_ghs"] * 2000
        + features["has_employer_detail"] * 1500
    )
    loan_noise = rng.normal(0, 500, size=n)
    max_loan = (loan_base + loan_noise).clip(500, 10000).round(2)

    # income_tier: ~25% Low, ~40% Mid, ~25% Upper-Mid, ~10% High
    income_score = (
        features["total_monthly_instalment_ghs"] * 0.25
        + features["total_outstanding_debt_ghs"] * 0.20
        + features["has_employer_detail"] * 0.20
        + features["applicant_age"] * 0.15
        + features["credit_age_months"] * 0.10
        + features["num_accounts_total"] * 0.10
    )
    # Use percentile-based cuts to get desired distribution
    p25 = np.percentile(income_score, 25)
    p65 = np.percentile(income_score, 65)
    p90 = np.percentile(income_score, 90)
    income_tier = np.digitize(income_score, bins=[p25, p65, p90]).astype(int)
    income_tier = np.clip(income_tier, 0, 3)

    return pd.DataFrame({
        "default_flag": default_flag,
        "max_successful_loan_ghs": max_loan,
        "income_tier": income_tier,
    })


def generate_metadata(
    rng: np.random.Generator,
    features: pd.DataFrame,
    n: int,
    product_source: str = "45+49",
) -> pd.DataFrame:
    """Generate metadata columns."""
    credit_scores = compute_credit_score(features)
    grades = np.array([score_to_grade(s) for s in credit_scores])
    decisions = np.array([grade_to_decision(g) for g in grades])

    # Data quality score: higher for complete data
    dqs = rng.uniform(0.75, 1.0, size=n).round(2)

    # Age: from applicant_age bins → actual age
    age_map = {0.00: 17, 0.70: 22, 1.00: 33, 0.90: 50, 0.65: 68}
    ages = np.array([
        age_map.get(v, 35) + rng.integers(-3, 4)
        for v in features["applicant_age"]
    ]).clip(18, 75)

    # Credit age months: from credit_age_months bins → actual months
    cam_map = {1.00: 96, 0.85: 60, 0.65: 36, 0.40: 18, 0.15: 6}
    credit_months = np.array([
        cam_map.get(v, 36) + rng.integers(-6, 7)
        for v in features["credit_age_months"]
    ]).clip(0, 360)

    if isinstance(product_source, str):
        product_sources = np.full(n, product_source)
    else:
        product_sources = product_source

    bureau_status = np.where(
        np.isin(product_sources, ["45+49", "45"]), "HIT", "THIN_FILE"
    )

    return pd.DataFrame({
        "request_id": [f"REQ-{i+1:06d}" for i in range(n)],
        "credit_score": credit_scores,
        "score_grade": grades,
        "decision_label": decisions,
        "data_quality_score": dqs,
        "product_source": product_sources,
        "bureau_hit_status": bureau_status,
        "applicant_age_at_application": ages,
        "credit_age_months_at_application": credit_months,
    })


def generate_clean_dataset(n: int, seed: int = 42) -> pd.DataFrame:
    """Generate a clean dataset with all features populated."""
    rng = np.random.default_rng(seed)
    features = generate_features(rng, n)
    targets = generate_targets(rng, features, n)
    metadata = generate_metadata(rng, features, n, product_source="45+49")
    return pd.concat([features, targets, metadata], axis=1)


def generate_missing_dataset(n: int, seed: int = 123) -> pd.DataFrame:
    """Generate a dataset with realistic product-based missing values."""
    rng = np.random.default_rng(seed)
    features = generate_features(rng, n)
    targets = generate_targets(rng, features, n)

    # Assign product sources: 40% product_45, 30% product_49, 30% both
    product_choices = rng.choice(
        ["45", "49", "45+49"], size=n, p=[0.40, 0.30, 0.30]
    )
    metadata = generate_metadata(rng, features, n, product_source=product_choices)

    # Apply nulls based on product source
    for i in range(n):
        if product_choices[i] == "45":
            for feat in PRODUCT_45_MISSING:
                features.at[i, feat] = np.nan
        elif product_choices[i] == "49":
            for feat in PRODUCT_49_MISSING:
                features.at[i, feat] = np.nan

    # Some null targets (realistic)
    ambiguous_mask = rng.random(n) < 0.05
    targets.loc[ambiguous_mask, "default_flag"] = np.nan

    no_paid_loans_mask = rng.random(n) < 0.20
    targets.loc[no_paid_loans_mask, "max_successful_loan_ghs"] = np.nan

    no_income_data_mask = rng.random(n) < 0.15
    targets.loc[no_income_data_mask, "income_tier"] = np.nan

    return pd.concat([features, targets, metadata], axis=1)


def generate_broken_dataset(n: int, seed: int = 999) -> pd.DataFrame:
    """Generate a dataset with validation errors for testing."""
    rng = np.random.default_rng(seed)
    features = generate_features(rng, n)
    targets = generate_targets(rng, features, n)
    metadata = generate_metadata(rng, features, n, product_source="45+49")

    df = pd.concat([features, targets, metadata], axis=1)

    # Error 1: Drop 3 feature columns entirely
    df = df.drop(columns=["highest_delinquency_rating", "utilisation_ratio", "applicant_age"])

    # Error 2: Drop a target column
    df = df.drop(columns=["income_tier"])

    # Error 3: Replace a feature column with string values (wrong dtype)
    df["has_active_arrears"] = "N/A"

    return df


def main():
    output_dir = Path(__file__).parent

    print("Generating clean_50k.parquet (50,000 records)...")
    clean = generate_clean_dataset(50_000)
    clean.to_parquet(output_dir / "clean_50k.parquet", index=False)
    print(f"  Shape: {clean.shape}, Nulls: {clean.isnull().sum().sum()}")

    print("Generating missing_10k.parquet (10,000 records)...")
    missing = generate_missing_dataset(10_000)
    missing.to_parquet(output_dir / "missing_10k.parquet", index=False)
    null_count = missing[FEATURE_NAMES].isnull().sum()
    print(f"  Shape: {missing.shape}, Feature nulls:\n{null_count[null_count > 0].to_string()}")

    print("Generating broken_1k.parquet (1,000 records)...")
    broken = generate_broken_dataset(1_000)
    broken.to_parquet(output_dir / "broken_1k.parquet", index=False)
    print(f"  Shape: {broken.shape}, Columns: {list(broken.columns)}")

    print("\nDone! All datasets saved to dummy_data/")


if __name__ == "__main__":
    main()
