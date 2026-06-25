"""Pydantic schemas for the contract-finder API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from backend.core.enums import (
    ApplicationOutcome,
    ContractStatus,
    ContractType,
    OpportunityKind,
    PreferredContractType,
    PreferredDuration,
    ProposalSectionType,
    ProposalStatus,
    ScannerState,
    SubmissionChannel,
)

# Alias names used by existing Pydantic schemas (kept for backward compatibility)
ContractStatusEnum = ContractStatus
ContractTypeEnum = ContractType
ProposalStatusEnum = ProposalStatus
ApplicationOutcomeEnum = ApplicationOutcome
ScannerStateEnum = ScannerState


# ── Contract / Opportunity schemas ───────────────────────────────────────────


class OpportunityCreate(BaseModel):
    """Schema for creating / upserting an opportunity (contract or job) from a platform scan."""

    platform: str
    external_id: str
    url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    skills_required: Optional[list[str]] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    contract_type: Optional[ContractTypeEnum] = None
    duration: Optional[str] = None
    proposals_count: Optional[int] = None
    client_hire_rate: Optional[float] = None
    client_total_spent: Optional[float] = None
    client_location: Optional[str] = None
    match_score: Optional[float] = None
    roi_score: Optional[float] = None
    connects_cost: Optional[int] = None
    client_questions: Optional[list[str]] = None
    posted_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    source: Optional[str] = None
    kind: OpportunityKind = OpportunityKind.contract
    submission_channel: SubmissionChannel = SubmissionChannel.direct
    platform_meta: Optional[dict] = None
    review_flags: Optional[list[dict]] = None


class Opportunity(BaseModel):
    """Full opportunity representation returned from the API (covers contracts and jobs)."""

    id: int
    platform: str
    external_id: str
    url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    skills_required: Optional[list[str]] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    contract_type: Optional[ContractTypeEnum] = None
    duration: Optional[str] = None
    proposals_count: Optional[int] = None
    client_hire_rate: Optional[float] = None
    client_total_spent: Optional[float] = None
    client_location: Optional[str] = None
    match_score: Optional[float] = None
    roi_score: Optional[float] = None
    connects_cost: Optional[int] = None
    client_questions: Optional[list[str]] = None
    status: ContractStatusEnum = ContractStatusEnum.new
    posted_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    source: Optional[str] = None
    description_fit: Optional[float] = None
    skip_reason: Optional[str] = None
    is_finalist: bool = False
    kind: OpportunityKind = OpportunityKind.contract
    submission_channel: SubmissionChannel = SubmissionChannel.direct
    platform_meta: Optional[dict] = None
    review_flags: Optional[list[dict]] = None

    model_config = {"from_attributes": True}

    @field_validator("skills_required", "client_questions", mode="before")
    @classmethod
    def _parse_json_strings(cls, v):
        """SQLite JSON columns may come back as strings — parse them.

        Handles double-encoded values (e.g. '"[\\"a\\"]"') by decoding
        repeatedly until the result is no longer a string.
        """
        if isinstance(v, str):
            import json
            try:
                parsed = json.loads(v)
                # Keep decoding if we got back another JSON string
                while isinstance(parsed, str):
                    parsed = json.loads(parsed)
                return parsed
            except (json.JSONDecodeError, TypeError, ValueError):
                return []
        return v

    @property
    def comp_min(self) -> Optional[float]:
        """Compensation floor (alias of budget_min; works for jobs and contracts)."""
        return self.budget_min

    @property
    def comp_max(self) -> Optional[float]:
        """Compensation ceiling (alias of budget_max)."""
        return self.budget_max


# Back-compat aliases — existing code imports ``Contract`` / ``ContractCreate``.
Contract = Opportunity
ContractCreate = OpportunityCreate


# ── Proposal schemas ─────────────────────────────────────────────────────────


class ProposalSection(BaseModel):
    """A single section within a structured proposal."""

    type: ProposalSectionType
    content: str
    annotation: Optional[str] = None
    case_study_ids: Optional[list[str]] = None


class Proposal(BaseModel):
    """Full proposal representation."""

    id: int
    contract_id: int
    version: int
    content: Optional[str] = None
    sections: Optional[list[ProposalSection]] = None
    matched_case_studies: Optional[list[str]] = None
    bid_amount: Optional[float] = None
    estimated_duration: Optional[str] = None
    status: ProposalStatusEnum = ProposalStatusEnum.draft
    created_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_validator("sections", "matched_case_studies", mode="before")
    @classmethod
    def _parse_json_strings(cls, v):
        """SQLite JSON columns may come back as strings — parse them.

        Handles double-encoded values by decoding repeatedly until the
        result is no longer a string.
        """
        if isinstance(v, str):
            import json
            try:
                parsed = json.loads(v)
                while isinstance(parsed, str):
                    parsed = json.loads(parsed)
                return parsed
            except (json.JSONDecodeError, TypeError, ValueError):
                return []
        return v


# ── Availability & profile schemas ───────────────────────────────────────────


class AvailabilityConfig(BaseModel):
    """Freelancer availability and rate preferences."""

    hours_per_week: int = 40
    max_concurrent_contracts: int = 3
    current_committed_hours: int = 0
    preferred_duration: PreferredDuration = PreferredDuration.any
    preferred_contract_type: PreferredContractType = PreferredContractType.both
    min_hourly_rate: float = 75.0
    min_fixed_budget: float = 500.0
    hourly_value: float = 100.0

    model_config = {"from_attributes": True}


class WeightedSkill(BaseModel):
    """A skill with a relevance weight (1.0 = core, 0.6 = adjacent)."""

    name: str
    weight: float = Field(ge=0.0, le=1.0)


class SkillProfile(BaseModel):
    """A skill category with description and skill list."""

    description: str
    skills: list[str]


class WorkExperience(BaseModel):
    """One employment entry for a Workday 'My Experience' page (user-provided, real)."""

    title: str = ""
    company: str = ""
    location: str = ""
    start: str = ""              # "YYYY-MM"
    end: Optional[str] = None    # "YYYY-MM", or None if current
    current: bool = False
    description: str = ""


class Education(BaseModel):
    """One education entry for a Workday 'My Experience' page (user-provided, real)."""

    school: str = ""
    degree: str = ""
    field: str = ""
    start: str = ""              # "YYYY"
    end: str = ""                # "YYYY"


class ApplicantInfo(BaseModel):
    """Applicant identity used to fill ATS application forms."""

    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    resume_path: str = ""
    country: str = ""
    location: str = ""  # residence (e.g. "New Hampshire"); grounds "where are you based?"
    work_authorization: str = ""
    needs_sponsorship: bool = False
    linkedin: str = ""
    website: str = ""
    github: str = ""
    work_history: list[WorkExperience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class LoadedProfile(BaseModel):
    """Fully parsed profile with structured skill tiers and metadata."""

    name: str
    studio: str
    positioning: str
    location: str = ""   # e.g. "Vermont"; drives the writing voice
    voice: str = ""      # optional full override of the voice clause
    framing: str = ""    # e.g. "a Sample Studio partnership"
    hourly_rate_range: list[float]
    tone: str
    selling_points: list[str]
    key_differentiators: dict[str, SkillProfile]
    core_skills: list[WeightedSkill]
    adjacent_skills: list[WeightedSkill]
    all_skills: list[WeightedSkill]
    applicant: Optional[ApplicantInfo] = None


class SearchConfig(BaseModel):
    """A single search configuration for the scanner."""

    name: str
    query: str
    category: str
    filters: Optional[dict] = None


# ── Scanner status ───────────────────────────────────────────────────────────


class ScannerStatus(BaseModel):
    """Current state of the contract scanner."""

    state: ScannerStateEnum = ScannerStateEnum.idle
    contracts_found: int = 0
    current_search: Optional[str] = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    errors: list[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
