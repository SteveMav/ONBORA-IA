from typing import Any, Literal

from pydantic import Field

from .base import ContractModel
from .profile import CompanyProfile
from .recommendation import RecommendationResult


class TurnResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    conversation_id: int
    message_id: int
    profile_snapshot_id: int
    profile: CompanyProfile
    recommendations: RecommendationResult | None = None
    assistant_message: str = Field(default="", max_length=2_000)
    ready_for_analysis: bool = False
    readiness_reason: str = Field(default="", max_length=500)
    next_questions: list[str] = Field(default_factory=list, max_length=10)
    replayed: bool = False


class GeneratedReportResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    report_id: int
    conversation_id: int
    report_type: Literal["kam", "business_twin"]
    status: Literal["final", "non_final"]
    data: dict[str, Any]
    rendered_text: str
    replayed: bool = False
