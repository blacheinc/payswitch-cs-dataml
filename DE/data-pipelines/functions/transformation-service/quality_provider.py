from contracts import TransformRequest


class System04QualityAdapter:
    def get_score(self, request: TransformRequest) -> float | None:
        # If upstream starts sending quality score in request metadata, consume it here.
        payload = request.xds_payload or {}
        metadata = payload.get("metadata", {}) or {}
        score = metadata.get("data_quality_score")
        try:
            return float(score) if score is not None else None
        except (TypeError, ValueError):
            return None

