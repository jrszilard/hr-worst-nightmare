"""SQLAlchemy ORM models for contract-finder."""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.types import JSON

from backend.core.enums import (  # noqa: F401 – re-exported for convenience
    ApplicationOutcome,
    BudgetPeriod,
    ContractStatus,
    ContractType,
    OpportunityKind,
    PreferredContractType,
    PreferredDuration,
    ProposalStatus,
    SpendKind,
    SubmissionChannel,
)
from backend.platforms.resolve.resolution import ResolutionStatus, ResolutionTier
from backend.platforms.ats_registry import Capability


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ── Models ───────────────────────────────────────────────────────────────────


class OpportunityDB(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_platform_external_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    url = Column(String)
    title = Column(String)
    description = Column(Text)
    skills_required = Column(JSON)
    budget_min = Column(Float)
    budget_max = Column(Float)
    contract_type = Column(Enum(ContractType))
    duration = Column(String)
    proposals_count = Column(Integer)
    client_hire_rate = Column(Float)
    client_total_spent = Column(Float)
    client_location = Column(String)
    match_score = Column(Float)
    roi_score = Column(Float)
    connects_cost = Column(Integer)
    client_questions = Column(JSON)
    status = Column(Enum(ContractStatus), default=ContractStatus.new, nullable=False)
    source = Column(String, nullable=True)
    description_fit = Column(Float, nullable=True)
    skip_reason = Column(String, nullable=True)
    kind = Column(
        Enum(OpportunityKind),
        default=OpportunityKind.contract,
        server_default=OpportunityKind.contract.value,
        nullable=False,
    )
    submission_channel = Column(
        Enum(SubmissionChannel),
        default=SubmissionChannel.direct,
        server_default=SubmissionChannel.direct.value,
        nullable=False,
    )
    platform_meta = Column(JSON, nullable=True)
    review_flags = Column(JSON, nullable=True)
    is_finalist = Column(Boolean, nullable=False, default=False, server_default="0")
    feedback = Column(String, nullable=True)  # "liked" | "disliked" | None
    # External-apply resolution (SP1): the real terminal apply URL + ATS classification.
    resolved_url = Column(String, nullable=True)
    detected_ats = Column(String, nullable=True)
    ats_capability = Column(Enum(Capability), nullable=True)      # engine_fillable | multi_page | manual | aggregator
    resolution_status = Column(Enum(ResolutionStatus), nullable=True)  # resolved | blocked | dead | needs_human | unresolved
    resolution_tier = Column(Enum(ResolutionTier), nullable=True)      # data | headless | real_brave
    posted_at = Column(DateTime)
    fetched_at = Column(DateTime, default=lambda: datetime.now(UTC))

    # Relationships
    proposals = relationship("ProposalDB", back_populates="contract", cascade="all, delete-orphan")
    applications = relationship("ApplicationHistoryDB", back_populates="contract", cascade="all, delete-orphan")
    job_application = relationship(
        "JobApplicationDB", back_populates="opportunity",
        uselist=False, cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<OpportunityDB id={self.id} platform={self.platform!r} external_id={self.external_id!r}>"


class SkillPreferenceDB(Base):
    """Learned per-skill weight from job like/dislike feedback."""

    __tablename__ = "skill_preferences"

    skill = Column(String, primary_key=True)  # canonical, normalize_skill()'d
    weight = Column(Float, nullable=False, default=0.0, server_default="0")
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


# Back-compat alias — existing modules import ``ContractDB``.
ContractDB = OpportunityDB


class ProposalDB(Base):
    __tablename__ = "proposals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    content = Column(Text)
    sections = Column(JSON)
    matched_case_studies = Column(JSON)
    bid_amount = Column(Float)
    estimated_duration = Column(String)
    status = Column(Enum(ProposalStatus), default=ProposalStatus.draft, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    submitted_at = Column(DateTime, nullable=True)

    # Relationships
    contract = relationship("OpportunityDB", back_populates="proposals")
    applications = relationship("ApplicationHistoryDB", back_populates="proposal", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ProposalDB id={self.id} contract_id={self.contract_id} v{self.version}>"


class ApplicationHistoryDB(Base):
    __tablename__ = "application_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    proposal_id = Column(Integer, ForeignKey("proposals.id"), nullable=False)
    connects_spent = Column(Integer)
    outcome = Column(Enum(ApplicationOutcome), default=ApplicationOutcome.submitted, nullable=False)
    submitted_at = Column(DateTime, default=lambda: datetime.now(UTC))
    outcome_at = Column(DateTime, nullable=True)

    # Relationships
    contract = relationship("OpportunityDB", back_populates="applications")
    proposal = relationship("ProposalDB", back_populates="applications")

    def __repr__(self) -> str:
        return f"<ApplicationHistoryDB id={self.id} outcome={self.outcome!r}>"


class JobApplicationDB(Base):
    """Generated application content for a job-kind opportunity.

    One row per job that passed screening. Skipped jobs have no row. The
    presence of this row + ``applied`` is the single source of truth for the
    UI's Skipped / Ready / Applied bucket.
    """

    __tablename__ = "job_applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    opportunity_id = Column(
        Integer, ForeignKey("contracts.id"), nullable=False, unique=True
    )
    cover_letter = Column(Text, nullable=False)
    screening_answers = Column(JSON)  # [{"question": str, "answer": str}]
    review_flags = Column(JSON)       # list of flag dicts from GeneratedApplication
    generated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    applied = Column(Boolean, nullable=False, default=False)
    applied_at = Column(DateTime, nullable=True)

    opportunity = relationship("OpportunityDB", back_populates="job_application")

    def __repr__(self) -> str:
        return f"<JobApplicationDB id={self.id} opportunity_id={self.opportunity_id} applied={self.applied}>"


class BudgetSettingsDB(Base):
    """Singleton (id=1) spend caps. Mirrors AvailabilitySettingsDB."""

    __tablename__ = "budget_settings"

    id = Column(Integer, primary_key=True, default=1)
    connects_per_period = Column(Integer, nullable=False, default=60)
    generation_apps_per_period = Column(Integer, nullable=False, default=20)
    generation_dollars_per_period = Column(Float, nullable=False, default=5.0)  # display-only estimate; not enforced until token metering lands
    period = Column(Enum(BudgetPeriod), nullable=False, default=BudgetPeriod.week)
    per_run_max_apps = Column(Integer, nullable=True, default=5)
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class SpendEventDB(Base):
    """Append-only ledger of spend, summed per period for the budget meter."""

    __tablename__ = "spend_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(Enum(SpendKind), nullable=False)
    amount = Column(Float, nullable=False)
    opportunity_id = Column(Integer, ForeignKey("contracts.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))


class AvailabilitySettingsDB(Base):
    """Single-row table storing availability / rate preferences.

    The ``id`` column is always 1 — there is only ever one row.
    """

    __tablename__ = "availability_settings"

    id = Column(Integer, primary_key=True, default=1)
    hours_per_week = Column(Integer, nullable=False, default=40)
    max_concurrent_contracts = Column(Integer, nullable=False, default=3)
    current_committed_hours = Column(Integer, nullable=False, default=0)
    preferred_duration = Column(
        Enum(PreferredDuration), nullable=False, default=PreferredDuration.any
    )
    preferred_contract_type = Column(
        Enum(PreferredContractType), nullable=False, default=PreferredContractType.both
    )
    min_hourly_rate = Column(Float, nullable=False, default=75.0)
    min_fixed_budget = Column(Float, nullable=False, default=500.0)
    hourly_value = Column(Float, nullable=False, default=100.0)
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<AvailabilitySettingsDB hours_per_week={self.hours_per_week}>"
