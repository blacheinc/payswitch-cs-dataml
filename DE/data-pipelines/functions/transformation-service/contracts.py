"""Request and response models for XDS transformation (training vs inference, contract version)."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from xds_payload_normalize import normalize_nested_xds_payload

BureauHitStatus = Literal["HIT", "THIN_FILE", "NO_RECORD"]
Decision = Literal["APPROVE", "CONDITIONAL_APPROVE", "REFER", "DECLINE", "FRAUD_HOLD"]
SUPPORTED_SOURCES: tuple[str, ...] = ("xds",)
CONTRACT_VERSION = "xds-transform-contract-v1"


@dataclass(frozen=True)
class ApplicantContext:
    loan_amount_requested: float
    loan_tenure_months: int
    monthly_income: float
    identity_reference: str


@dataclass(frozen=True)
class TransformRequest:
    flow_type: Literal["training", "inference"]
    request_id: str
    data_source_id: str
    source_system: str
    xds_payload: Dict[str, Any]
    applicant_context: ApplicantContext = field(
        default_factory=lambda: ApplicantContext(
            loan_amount_requested=0.0,
            loan_tenure_months=0,
            monthly_income=0.0,
            identity_reference="UNKNOWN",
        )
    )
    run_id: Optional[str] = None
    training_upload_id: Optional[str] = None

    def validate(self) -> None:
        if self.source_system.lower() not in SUPPORTED_SOURCES:
            raise ValueError(
                f"source_system must be one of {SUPPORTED_SOURCES}, got '{self.source_system}'"
            )
        if not self.request_id:
            raise ValueError("request_id is required")
        if not self.data_source_id:
            raise ValueError("data_source_id is required")

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TransformRequest":
        flow_type = payload.get("flow_type", "inference")
        app = payload.get("applicant_context", {}) or {}
        context = ApplicantContext(
            loan_amount_requested=float(app.get("loan_amount_requested", 0.0)),
            loan_tenure_months=int(app.get("loan_tenure_months", 0)),
            monthly_income=float(app.get("monthly_income", 0.0)),
            identity_reference=str(app.get("identity_reference", "UNKNOWN")),
        )

        raw_xds = payload.get("xds_payload", {}) or {}
        if isinstance(raw_xds, dict) and "__flat_row__" not in raw_xds:
            raw_xds = normalize_nested_xds_payload(raw_xds)
        request = cls(
            flow_type=flow_type,
            request_id=str(payload.get("request_id", payload.get("upload_id", ""))),
            data_source_id=str(payload.get("data_source_id", payload.get("bank_id", ""))),
            source_system=str(payload.get("source_system", "xds")),
            xds_payload=raw_xds,
            applicant_context=context,
            run_id=payload.get("run_id"),
            training_upload_id=payload.get("training_upload_id"),
        )
        request.validate()
        return request


@dataclass
class TransformDiagnostics:
    missing_feature_list: List[str] = field(default_factory=list)
    feature_coverage_ratio: float = 0.0
    thin_file_flag: int = 0
    no_record_flag: int = 0
    product45_available_flag: int = 0
    product49_available_flag: int = 0
    critical_field_missing_flag: int = 0
    data_quality_score_version: str = "s0_s4_v1"


@dataclass
class TransformResponse:
    request_id: str
    bureau_hit_status: BureauHitStatus
    features: Dict[str, Any]
    feature_provenance: Dict[str, str]
    metadata: Dict[str, Any]
    targets: Dict[str, Any]
    decision_package: Dict[str, Any]
    diagnostics: TransformDiagnostics
    transform_version: str
    rule_version: str
    scoring_timestamp: str
    contract_version: str = CONTRACT_VERSION

    @classmethod
    def create(
        cls,
        request_id: str,
        bureau_hit_status: BureauHitStatus,
        features: Dict[str, Any],
        feature_provenance: Dict[str, str],
        metadata: Dict[str, Any],
        targets: Dict[str, Any],
        decision_package: Dict[str, Any],
        diagnostics: TransformDiagnostics,
        transform_version: str = "v1",
        rule_version: str = "v1",
    ) -> "TransformResponse":
        return cls(
            request_id=request_id,
            bureau_hit_status=bureau_hit_status,
            features=features,
            feature_provenance=feature_provenance,
            metadata=metadata,
            targets=targets,
            decision_package=decision_package,
            diagnostics=diagnostics,
            transform_version=transform_version,
            rule_version=rule_version,
            scoring_timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "bureau_hit_status": self.bureau_hit_status,
            "features": self.features,
            "feature_provenance": self.feature_provenance,
            "metadata": self.metadata,
            "targets": self.targets,
            "decision_package": self.decision_package,
            "diagnostics": {
                "missing_feature_list": self.diagnostics.missing_feature_list,
                "feature_coverage_ratio": self.diagnostics.feature_coverage_ratio,
                "thin_file_flag": self.diagnostics.thin_file_flag,
                "no_record_flag": self.diagnostics.no_record_flag,
                "product45_available_flag": self.diagnostics.product45_available_flag,
                "product49_available_flag": self.diagnostics.product49_available_flag,
                "critical_field_missing_flag": self.diagnostics.critical_field_missing_flag,
                "data_quality_score_version": self.diagnostics.data_quality_score_version,
            },
            "transform_version": self.transform_version,
            "rule_version": self.rule_version,
            "scoring_timestamp": self.scoring_timestamp,
            "contract_version": self.contract_version,
        }

