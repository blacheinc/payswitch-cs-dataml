"""Typing protocols for parser, feature builder, hard-stop evaluator, rules, and quality score."""

from typing import Any, Dict, Protocol, Tuple

from contracts import BureauHitStatus, TransformRequest


class IXdsParser(Protocol):
    def parse(self, request: TransformRequest) -> Dict[str, Any]:
        ...


class IFeatureBuilder(Protocol):
    def build(
        self, extracted: Dict[str, Any], hit_status: BureauHitStatus
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        ...


class IHardStopEvaluator(Protocol):
    def evaluate(self, features: Dict[str, Any]) -> Dict[str, Any]:
        ...


class IRuleEngine(Protocol):
    def decide(
        self, features: Dict[str, Any], hard_stop: Dict[str, Any], hit_status: BureauHitStatus
    ) -> Dict[str, Any]:
        ...


class IQualityScoreProvider(Protocol):
    def get_score(self, request: TransformRequest) -> float | None:
        ...

